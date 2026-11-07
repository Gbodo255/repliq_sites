"""The replication orchestrator.

Runs the full pipeline for one project as a background asyncio task and streams
progress over the event bus::

    crawl -> analyze -> download assets -> build pages -> re-link assets
          -> import WordPress content (if any) -> purge external references
          -> quality loop (compare + layout fix) -> audit -> output targets
          -> export -> done

The job can be cancelled, updates the persisted project state at every
milestone, and records failures instead of hiding them.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from statistics import mean

from app.config import settings
from app.core.events import ProgressEvent, bus
from app.core.logging import get_logger
from app.core.security import UnsafeUrlError, validate_target_url
from app.models.domain import CompareResult, ReplicationOptions
from app.modules.analyzer.analyzer import analyze
from app.modules.asset_downloader.downloader import AssetStore
from app.modules.auto_fixer.fixer import relink_remaining_assets
from app.modules.auto_fixer.layout import LayoutFixer
from app.modules.browser.renderer import Renderer
from app.modules.crawler.crawler import canonicalize, crawl
from app.modules.exporter.exporter import zip_project
from app.modules.interaction_analyzer.interactions import interaction_report
from app.modules.page_builder.builder import SiteBuilder
from app.modules.responsive_analyzer.responsive import responsive_report
from app.modules.sanitizer.external import purge_tree
from app.modules.targets import TARGETS, WORDPRESS_TARGETS, build_target, normalize_targets
from app.modules.visual_comparator.comparator import compare
from app.services.project_store import store

log = get_logger("service")

_MODE_DEFAULTS = {
    "auto": dict(max_depth=1, max_pages=12, viewports=["desktop", "mobile"], fix_cycles=2),
    "full": dict(max_depth=2, max_pages=40,
                 viewports=["desktop", "laptop", "tablet", "mobile", "small"], fix_cycles=3),
    "single_page": dict(max_depth=0, max_pages=1, viewports=["desktop", "mobile"], fix_cycles=2),
}
_MAX_COMPARE_PAGES = 40
_LOW_MEM_COMPARE_PAGES = 1


def _resolve_options(req) -> ReplicationOptions:
    mode = req.mode.value if hasattr(req.mode, "value") else str(req.mode)
    base = _MODE_DEFAULTS.get(mode, _MODE_DEFAULTS["auto"])
    valid = {v.name for v in settings.viewports}
    vps = req.viewports or base["viewports"]
    vps = [v for v in vps if v in valid] or ["desktop", "mobile"]
    cap = (settings.max_pages if (mode != "full" or settings.low_memory)
           else max(settings.max_pages, base["max_pages"]))
    outputs = getattr(req, "outputs", None)
    return ReplicationOptions(
        max_pages=min(req.max_pages or base["max_pages"], cap),
        max_depth=req.max_depth if req.max_depth is not None else base["max_depth"],
        viewport_names=vps,
        fix_cycles=req.fix_cycles if req.fix_cycles is not None else base["fix_cycles"],
        mode=mode,
        keep_js=bool(req.keep_js) if req.keep_js is not None else False,
        run_quality_check=req.run_quality_check if req.run_quality_check is not None else True,
        outputs=normalize_targets([o.value if hasattr(o, "value") else o for o in (outputs or [])]),
        keep_external_links=bool(getattr(req, "keep_external_links", False) or False),
        import_wp_content=getattr(req, "import_wp_content", None) is not False,
    )


def _grade(score: float | None) -> str:
    if score is None:
        return "-"
    return "A" if score >= 0.97 else "B" if score >= 0.92 else "C" if score >= 0.85 else "D"


class JobManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def is_running(self, pid: str) -> bool:
        t = self._tasks.get(pid)
        return bool(t and not t.done())

    def cancel(self, pid: str) -> bool:
        t = self._tasks.get(pid)
        if t and not t.done():
            t.cancel()
            return True
        return False

    def _spawn(self, pid: str, coro) -> None:
        bus.drop(pid)                 # fresh progress channel for every job
        task = asyncio.create_task(coro)
        self._tasks[pid] = task
        task.add_done_callback(lambda _t, p=pid: self._tasks.pop(p, None))

    def start(self, req) -> dict:
        url = validate_target_url(req.url)       # raises UnsafeUrlError on bad input
        options = _resolve_options(req)
        detail = store.create(req.name or "", url, options)
        self._spawn(detail["id"], self._run(detail["id"], url, options))
        return detail

    def rerun(self, pid: str) -> dict:
        """Replicate the same URL again with the same options (refresh)."""
        detail = store.get(pid)
        if not detail:
            raise KeyError(pid)
        if self.is_running(pid):
            return detail
        opts = ReplicationOptions(**{k: v for k, v in (detail.get("options") or {}).items()
                                     if k in ReplicationOptions.__dataclass_fields__})
        store.reset_for_rerun(pid)
        self._spawn(pid, self._run(pid, detail["url"], opts))
        return store.get(pid) or detail

    def add_outputs(self, pid: str, targets: list[str]) -> dict:
        """Generate additional output formats from an existing replication."""
        detail = store.get(pid)
        if not detail:
            raise KeyError(pid)
        if self.is_running(pid):
            raise RuntimeError("A job is already running for this project")
        targets = normalize_targets(targets)
        self._spawn(pid, self._build_outputs_job(pid, targets))
        return detail

    # ------------------------------------------------------------- pipeline
    def _emitter(self, pid: str):
        last = {"v": 0.0}

        def emit(phase: str, message: str, progress: float = -1.0,
                 level: str = "info", data: dict | None = None) -> None:
            if progress is not None and progress >= 0:
                last["v"] = progress
            bus.emit(ProgressEvent(job_id=pid, phase=phase, message=message,
                                   progress=last["v"], level=level, data=data or {}))
        return emit

    async def _run(self, pid: str, seed_url: str, options: ReplicationOptions) -> None:
        detail = store.get(pid) or {}
        started = time.time()
        emit = self._emitter(pid)

        detail["status"] = "running"
        detail["options"] = options.__dict__
        store.save(detail)
        emit("start", f"Starting replication of {seed_url}", 1, data={"options": options.__dict__})

        site_dir = store.site_dir(pid)
        shots_dir = store.screenshots_dir(pid)
        try:
            async with Renderer() as renderer:
                # 1. Crawl + render.
                pages = await crawl(renderer, seed_url, options, emit=emit)
                ok_pages = [p for p in pages if p.ok and p.html]
                if not ok_pages:
                    errs = "; ".join(sorted({p.error for p in pages if p.error}))[:300]
                    raise RuntimeError(f"No page could be rendered ({errs or 'site unreachable or blocked'}).")
                skipped = len(pages) - len(ok_pages)
                if skipped:
                    emit("crawl", f"{skipped} page(s) skipped (HTTP errors / rate limiting)", level="warn")
                detail["pages_count"] = len(ok_pages)
                store.save(detail)
                if settings.low_memory:
                    # Free Chromium's memory while assets are downloaded and
                    # pages are built; it is relaunched for the quality loop.
                    await renderer.close()
                    import gc
                    gc.collect()

                # 2. Analyse.
                emit("analyze", "Analysing structure, palette, components", 51)
                analysis = analyze(ok_pages, seed_url)
                analysis["interactions"] = interaction_report(ok_pages)
                analysis["responsive"] = responsive_report(options.viewport_names)

                # 3. Build.
                builder = SiteBuilder(site_dir, options, emit=emit)
                builder.plan(ok_pages, seed_url)
                wp_content = None
                async with AssetStore(site_dir, options, emit=emit) as assets:
                    await builder.download_assets(ok_pages, assets)
                    page_records = builder.localize_and_write(ok_pages, assets)

                    # 3b. Late-discovered assets (always, not only on issues).
                    emit("fix", "Re-linking late-discovered assets", 88)
                    await relink_remaining_assets(site_dir, page_records, assets, options, emit)

                    # 3c. Content database of a WordPress source.
                    wants_wp = bool(set(options.outputs) & WORDPRESS_TARGETS)
                    if wants_wp and options.import_wp_content and "WordPress" in analysis.get("frameworks", []):
                        from app.modules.targets.wp_source import fetch_wordpress_content
                        page_map = {}
                        for r in page_records:
                            if r.status == "built":
                                key = "" if r.output_path == "index.html" else Path(r.output_path).stem
                                page_map[canonicalize(r.url)] = key
                        try:
                            wp_content = await fetch_wordpress_content(seed_url, assets, page_map, emit=emit)
                        except Exception as exc:  # noqa: BLE001 - optional enrichment
                            emit("content", f"WordPress content import skipped: {exc}", level="warn")
                        if wp_content:
                            store.wp_content_path(pid).write_text(
                                json.dumps(wp_content, ensure_ascii=False), encoding="utf-8")

                    builder.write_support(assets, page_records, analysis,
                                          {"generated_at": time.time(), "options": options.__dict__})

                    # 3d. Zero external reference.
                    purge = purge_tree(site_dir, keep_external_links=options.keep_external_links)
                    emit("purge", f"Removed {purge['total']} external reference(s)", 90,
                         data={"removed": purge["total"]})
                    self._write_site_readme(site_dir, seed_url, options, page_records, assets, analysis)

                    detail["assets_count"] = len(assets.ok_assets())
                    detail["assets_bytes"] = assets.total_bytes
                    detail["asset_cache_hits"] = assets.cache.hits
                    detail["pages"] = [r.to_dict() for r in page_records]
                    detail["assets"] = assets.manifest()[:1500]
                    detail["analysis"] = analysis
                    store.save(detail)

                # 4. Quality loop (compare + layout fix).
                comparisons, avg_ssim, fixer = [], None, None
                if options.run_quality_check and options.viewport_names:
                    if settings.low_memory:
                        self._release_capture_memory(ok_pages)
                        await renderer.start()
                    comparisons, avg_ssim, fixer = await self._quality_loop(
                        renderer, site_dir, shots_dir, options, ok_pages, page_records, emit)
                    detail["comparisons"] = [c.to_dict() for c in comparisons]
                    detail["avg_ssim"] = avg_ssim

            # 5. Audit: prove that nothing external remains.
            audit = purge_tree(site_dir, keep_external_links=options.keep_external_links, dry_run=True)
            detail["quality"] = self._quality_report(page_records, comparisons, fixer, purge, audit, assets_failed=sum(
                1 for a in detail.get("assets", []) if a.get("status") == "error"))
            (site_dir / "data" / "quality-report.json").write_text(
                json.dumps(detail["quality"], indent=2, ensure_ascii=False), encoding="utf-8")
            store.save(detail)

            # 6. Output targets + export.
            zip_project(site_dir, store.zip_path(pid))
            detail["has_zip"] = True
            await self._build_outputs(pid, detail, options.outputs, wp_content, emit)

            detail["status"] = "completed"
            detail["error"] = ""
            detail["duration"] = round(time.time() - started, 1)
            store.save(detail)
            emit("done", f"Replication complete - {detail['pages_count']} page(s), "
                         f"{detail['assets_count']} asset(s)", 100, level="success",
                 data={"avg_ssim": detail.get("avg_ssim")})
        except asyncio.CancelledError:
            detail["status"] = "cancelled"
            detail["error"] = "Cancelled by user"
            detail["duration"] = round(time.time() - started, 1)
            store.save(detail)
            emit("done", "Replication cancelled", level="warn")
            raise
        except UnsafeUrlError as exc:
            self._fail(detail, started, f"Rejected URL: {exc}", emit)
        except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
            log.exception("job %s failed", pid)
            self._fail(detail, started, str(exc), emit)
        finally:
            bus.close(pid)

    async def _build_outputs(self, pid: str, detail: dict, targets: list[str], wp_content, emit) -> None:
        site_dir = store.site_dir(pid)
        if wp_content is None and store.wp_content_path(pid).exists():
            try:
                wp_content = json.loads(store.wp_content_path(pid).read_text(encoding="utf-8"))
            except ValueError:
                wp_content = None
        screenshot = None
        shot = store.screenshots_dir(pid) / "index__desktop__original.png"
        if shot.exists():
            screenshot = shot.read_bytes()
        exports = {e["target"]: e for e in detail.get("exports", []) if isinstance(e, dict)}
        model = None
        for i, target in enumerate(targets):
            emit("export", f"Generating {TARGETS[target]['label']} output", 96 + int(3 * i / max(1, len(targets))))
            try:
                if target == "static":
                    if not store.zip_path(pid).exists():
                        await asyncio.to_thread(zip_project, site_dir, store.zip_path(pid))
                    exports[target] = {"target": target, "label": TARGETS[target]["label"],
                                       "zip": store.zip_path(pid).name,
                                       "size": store.zip_path(pid).stat().st_size, "info": {}, "error": ""}
                    continue
                if model is None:
                    from app.modules.targets.model import build_model
                    model = await asyncio.to_thread(build_model, site_dir, detail.get("pages", []), detail["url"])
                res = await asyncio.to_thread(
                    build_target, target, site_dir=site_dir, out_root=store.outputs_dir(pid),
                    exports_dir=store.exports_dir(pid), page_records=detail.get("pages", []),
                    source_url=detail["url"], posts=wp_content, screenshot=screenshot, model=model)
                zp = store.exports_dir(pid) / res["zip"]
                exports[target] = {"target": target, "label": TARGETS[target]["label"],
                                   "zip": res["zip"], "size": zp.stat().st_size if zp.exists() else 0,
                                   "info": res.get("info", {}), "error": ""}
                emit("export", f"{TARGETS[target]['label']} ready", data={"target": target})
            except Exception as exc:  # noqa: BLE001 - one target never sinks the others
                log.exception("target %s failed", target)
                exports[target] = {"target": target, "label": TARGETS[target]["label"], "zip": "",
                                   "size": 0, "info": {}, "error": str(exc)}
                emit("export", f"{TARGETS[target]['label']} failed: {exc}", level="error")
        detail["exports"] = [exports[t] for t in TARGETS if t in exports]
        store.save(detail)

    async def _build_outputs_job(self, pid: str, targets: list[str]) -> None:
        emit = self._emitter(pid)
        detail = store.get(pid) or {}
        prev = detail.get("status")
        detail["status"] = "running"
        store.save(detail)
        try:
            await self._build_outputs(pid, detail, targets, None, emit)
            opts = detail.get("options") or {}
            opts["outputs"] = list(dict.fromkeys((opts.get("outputs") or []) + targets))
            detail["options"] = opts
            detail["status"] = prev if prev in ("completed", "failed") else "completed"
            store.save(detail)
            emit("done", "Outputs generated", 100, level="success")
        except Exception as exc:  # noqa: BLE001
            detail["status"] = prev or "completed"
            store.save(detail)
            emit("done", f"Output generation failed: {exc}", level="error")
        finally:
            bus.close(pid)

    def _fail(self, detail, started, msg, emit):
        detail["status"] = "failed"
        detail["error"] = msg
        detail["duration"] = round(time.time() - started, 1)
        store.save(detail)
        emit("done", f"Replication failed: {msg}", level="error")

    async def _quality_loop(self, renderer, site_dir: Path, shots_dir: Path,
                            options, pages, page_records, emit):
        by_url = {}
        for rp in pages:
            by_url[rp.url] = rp
        pairs = [(by_url[rec.url], rec) for rec in page_records
                 if rec.status == "built" and rec.url in by_url]
        compare_set = pairs[:_MAX_COMPARE_PAGES]
        cycles = options.fix_cycles
        if settings.low_memory:
            # Small host: check the home page only, one correction cycle.
            compare_set = pairs[:_LOW_MEM_COMPARE_PAGES]
            cycles = min(cycles, 1)
        fixer = LayoutFixer(options.viewport_names)
        sem = asyncio.Semaphore(max(1, settings.page_concurrency))

        async def one(rp, rec, vp):
            orig = rp.screenshots.get(vp)
            if not orig:
                return None
            file_uri = (site_dir / rec.output_path).resolve().as_uri()
            async with sem:
                shot = await renderer.inspect_url(file_uri, vp)
            if not shot:
                return None
            gen, sig = shot
            res = await asyncio.to_thread(compare, orig, gen)
            slug = rec.output_path.replace("/", "_").rsplit(".", 1)[0]
            op = shots_dir / f"{slug}__{vp}__original.png"
            gp = shots_dir / f"{slug}__{vp}__generated.png"
            dp = shots_dir / f"{slug}__{vp}__diff.png"
            op.write_bytes(orig)
            gp.write_bytes(gen)
            dp.write_bytes(res["diff_png"])
            cmp = CompareResult(
                page_url=rec.url, viewport=vp, ssim=res["ssim"], diff_ratio=res["diff_ratio"],
                original_png=f"screenshots/{op.name}", generated_png=f"screenshots/{gp.name}",
                diff_png=f"screenshots/{dp.name}", width=res["width"],
                height_original=res["height_original"], height_generated=res["height_generated"],
                issues=res["issues"],
            )
            return cmp, rec, vp, sig

        comparisons: list = []
        avg_ssim = None
        for cycle in range(cycles + 1):
            emit("compare", f"Visual comparison pass {cycle + 1}", 91)
            jobs = [(rp, rec, vp) for rp, rec in compare_set for vp in options.viewport_names]
            if settings.low_memory:
                results = [await one(*j) for j in jobs]      # one image in memory at a time
            else:
                results = await asyncio.gather(*(one(*j) for j in jobs))
            results = [r for r in results if r]
            comparisons = [r[0] for r in results]
            ssims = [c.ssim for c in comparisons]
            avg_ssim = round(mean(ssims), 4) if ssims else None
            total_issues = sum(len(c.issues) for c in comparisons)
            emit("compare", f"Pass {cycle + 1}: avg SSIM={avg_ssim}, {total_issues} issue(s)",
                 93 + cycle, data={"avg_ssim": avg_ssim, "issues": total_issues})
            if cycle >= cycles:
                break
            # Layout fixer: restore the original computed state where it diverges.
            added = 0
            touched = set()
            by_rec = {rec.output_path: rp for rp, rec in compare_set}
            for cmp, rec, vp, sig in results:
                orig_sig = by_rec[rec.output_path].signatures.get(vp) or {}
                n = fixer.add(rec.output_path, vp, orig_sig, sig)
                if n:
                    added += n
                    touched.add(rec.output_path)
            for rel in touched:
                fixer.write(site_dir, rel)
            if not added:
                emit("fix", "Layout matches the original: no further correction needed")
                break
            emit("fix", f"Layout auto-fix: {added} correction(s) on {len(touched)} page(s)",
                 data={"fixed": added, "pages": len(touched)})
        return comparisons, avg_ssim, fixer

    @staticmethod
    def _release_capture_memory(pages) -> None:
        """Drop capture data no longer needed once pages are built (small hosts)."""
        for i, rp in enumerate(pages):
            rp.html = ""
            rp.snapshots = {}
            for k in ("base_styles", "vp_styles", "vp_classes"):
                rp.analysis.pop(k, None)
            if i >= _LOW_MEM_COMPARE_PAGES:
                rp.screenshots = {}
                rp.signatures = {}
        import gc
        gc.collect()

    @staticmethod
    def _quality_report(page_records, comparisons, fixer, purge, audit, assets_failed: int) -> dict:
        pages = []
        for rec in page_records:
            if rec.status != "built":
                continue
            mine = [c for c in comparisons if c.page_url == rec.url]
            score = round(min(c.ssim for c in mine), 4) if mine else None
            pages.append({
                "url": rec.url, "output_path": rec.output_path, "title": rec.title,
                "score": score, "grade": _grade(score),
                "viewports": {c.viewport: c.ssim for c in mine},
                "issues": sorted({i for c in mine for i in c.issues}),
                "fixes_applied": fixer.count(rec.output_path) if fixer else 0,
            })
        scores = [p["score"] for p in pages if p["score"] is not None]
        overall = round(mean(scores), 4) if scores else None
        return {
            "overall_score": overall,
            "grade": _grade(overall),
            "pages": pages,
            "external_refs_removed": purge.get("total", 0),
            "external_refs_remaining": audit.get("total", 0),
            "assets_failed": assets_failed,
        }

    @staticmethod
    def _write_site_readme(site_dir: Path, seed_url, options, page_records, assets, analysis) -> None:
        ok_pages = [r for r in page_records if r.status == "built"]
        lines = [
            "# Replicated site",
            "",
            "Local, self-contained copy generated by the Universal Website Replication Engine.",
            "",
            "## How to open",
            "",
            "Open `index.html` in any browser. All assets and internal pages are "
            "local and relative, so it works fully offline. The copy contains no "
            "link or reference to any external host.",
            "",
            "## Contents",
            "",
            f"- Pages: {len(ok_pages)}",
            f"- Assets downloaded: {len(assets.ok_assets())} "
            f"({assets.total_bytes / 1024 / 1024:.1f} MB)",
            f"- Detected frameworks: {', '.join(analysis.get('frameworks') or ['n/a'])}",
            f"- Palette: {', '.join(analysis.get('palette', [])[:6])}",
            "",
            "## Pages",
            "",
        ]
        for r in ok_pages:
            lines.append(f"- [{r.title or r.output_path}]({r.output_path})")
        lines += [
            "",
            "## Notes",
            "",
            "- Captured from the browser-rendered DOM, so JavaScript frameworks are "
            "reproduced from what they display.",
            "- Scroll-reveal animations captured from the live site (initial state + "
            "real transition) and common interactions (menus, accordions, tabs, "
            "carousels, sticky headers, forms) are re-implemented by "
            "`js/interactions.js`; `prefers-reduced-motion` is respected.",
            "- Embedded third-party widgets (maps, videos, iframes, canvases) are "
            "reproduced as images.",
            "- See `data/quality-report.json` for the per-page fidelity score.",
        ]
        (site_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


manager = JobManager()
