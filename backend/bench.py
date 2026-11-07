"""Benchmark & continuous-improvement harness for the replication engine.

Golden-cache strategy (keeps the live web untouched between iterations):

  * ``crawl``  -- hit each live site ONCE and pickle its rendered pages (fully
    rendered HTML + original per-viewport screenshots + layout signatures) into
    ``projects/_bench/<slug>/golden.pkl``.  This is the only phase that touches
    the live web.
  * ``score``  -- for every cached site, reload the golden pages, rebuild the
    offline copy and compare it against the cached originals WITHOUT
    re-crawling.  Downloaded assets come from the engine's persistent asset
    cache (filled on the first score, reused for 7 days), so re-scoring after an
    engine change is fast and makes no request to the origin site.

The score phase writes ``projects/_bench/report.json`` (latest run) and appends
to ``projects/_bench/history.jsonl`` so fidelity can be tracked across
iterations, plus per-site diff images under ``projects/_bench/<slug>/shots/``.

Usage::

    python bench.py crawl                 # crawl sites missing from the cache
    python bench.py crawl --force         # re-crawl everything
    python bench.py crawl --only books hn # crawl a subset
    python bench.py score                 # score every cached site
    python bench.py score --only tailwind
    python bench.py run                   # crawl missing, then score
    python bench.py list                  # show the site panel + cache state
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pickle
import shutil
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from app.core.aio import ensure_proactor_loop

ensure_proactor_loop()

from app.config import settings  # noqa: E402
from app.models.domain import ReplicationOptions  # noqa: E402
from app.modules.analyzer.analyzer import analyze  # noqa: E402
from app.modules.asset_downloader.downloader import AssetStore  # noqa: E402
from app.modules.auto_fixer.fixer import relink_remaining_assets  # noqa: E402
from app.modules.browser.renderer import Renderer  # noqa: E402
from app.modules.crawler.crawler import crawl  # noqa: E402
from app.modules.interaction_analyzer.interactions import interaction_report  # noqa: E402
from app.modules.page_builder.builder import SiteBuilder  # noqa: E402
from app.modules.responsive_analyzer.responsive import responsive_report  # noqa: E402
from app.modules.sanitizer.external import purge_tree  # noqa: E402
from app.services.replication_service import manager  # noqa: E402


# --------------------------------------------------------------------------- #
# The benchmark panel: diverse site types, all tolerant of a single polite      #
# browser visit.  books/quotes.toscrape.com are purpose-built scraping sandboxes.#
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Site:
    slug: str
    url: str
    kind: str
    mode: str = "auto"
    max_pages: int = 3
    max_depth: int = 1


PANEL: list[Site] = [
    Site("example",   "https://example.com",             "static-minimal",   "single_page", 1, 0),
    Site("neverssl",  "http://neverssl.com",             "static-minimal",   "single_page", 1, 0),
    Site("books",     "https://books.toscrape.com/",     "ecommerce",        "auto", 3, 1),
    Site("quotes",    "https://quotes.toscrape.com/",    "list-pagination",  "auto", 3, 1),
    Site("hn",        "https://news.ycombinator.com/",   "news-forum",       "single_page", 1, 0),
    Site("bootstrap", "https://getbootstrap.com/",       "framework-docs",   "auto", 3, 1),
    Site("wpnews",    "https://wordpress.org/news/",     "wordpress-blog",   "auto", 3, 1),
    Site("w3c",       "https://www.w3.org/",             "institutional",    "auto", 3, 1),
    Site("tailwind",  "https://tailwindcss.com/",        "saas-marketing",   "single_page", 1, 0),
    Site("portfolio", "https://brittanychiang.com/",     "portfolio-anim",   "single_page", 1, 0),
    # --- Harder panel (complex CSS, web fonts, dark mode, sliders, grids) ---
    Site("astro",     "https://astro.build/",            "framework-market", "single_page", 1, 0),
    Site("ghost",     "https://ghost.org/",              "cms-marketing",    "single_page", 1, 0),
    Site("basecamp",  "https://basecamp.com/",           "product-market",   "single_page", 1, 0),
    Site("csstricks", "https://css-tricks.com/",         "wp-editorial",     "auto", 3, 1),
    Site("mdn",       "https://developer.mozilla.org/en-US/", "docs-dense",  "single_page", 1, 0),
    Site("remix",     "https://remix.run/",              "react-animated",   "single_page", 1, 0),
]
PANEL_BY_SLUG = {s.slug: s for s in PANEL}

# Two viewports are enough signal for the benchmark while halving compare cost.
VIEWPORTS = ["desktop", "mobile"]
FIX_CYCLES = 2

BENCH_DIR = settings.projects_dir / "_bench"


def _options(site: Site) -> ReplicationOptions:
    return ReplicationOptions(
        max_pages=site.max_pages,
        max_depth=site.max_depth,
        viewport_names=list(VIEWPORTS),
        fix_cycles=FIX_CYCLES,
        mode=site.mode,
        keep_js=False,
        run_quality_check=True,
        outputs=["static"],
        keep_external_links=False,
        import_wp_content=False,
    )


def _golden_path(slug: str) -> Path:
    return BENCH_DIR / slug / "golden.pkl"


def _quiet(*_a, **_k) -> None:
    """Silent emit sink for the pipeline's progress events (positional or kw)."""


# --------------------------------------------------------------------------- #
# Crawl phase - the only phase that touches the live web.                       #
# --------------------------------------------------------------------------- #
async def crawl_site(renderer: Renderer, site: Site) -> dict:
    opts = _options(site)
    t0 = time.time()
    pages = await crawl(renderer, site.url, opts, emit=_quiet)
    ok = [p for p in pages if p.ok and p.html]
    if not ok:
        errs = "; ".join(sorted({p.error for p in pages if p.error}))[:200]
        return {"slug": site.slug, "ok": False, "error": errs or "no page rendered"}
    gp = _golden_path(site.slug)
    gp.parent.mkdir(parents=True, exist_ok=True)
    with gp.open("wb") as fh:
        pickle.dump({"url": site.url, "options": opts, "pages": ok,
                     "kind": site.kind, "crawled_at": time.time()}, fh,
                    protocol=pickle.HIGHEST_PROTOCOL)
    throttled = sum(p.throttled_resources for p in ok)
    return {"slug": site.slug, "ok": True, "pages": len(ok),
            "throttled": throttled, "secs": round(time.time() - t0, 1),
            "size_kb": round(gp.stat().st_size / 1024)}


async def cmd_crawl(sites: list[Site], force: bool) -> None:
    todo = [s for s in sites if force or not _golden_path(s.slug).exists()]
    skip = [s for s in sites if s not in todo]
    for s in skip:
        print(f"  cached   {s.slug:<10} (use --force to re-crawl)")
    if not todo:
        print("Nothing to crawl.")
        return
    async with Renderer() as renderer:
        for i, site in enumerate(todo):
            print(f"  crawling {site.slug:<10} {site.url} ...", flush=True)
            try:
                res = await crawl_site(renderer, site)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAILED   {site.slug:<10} {exc}")
                traceback.print_exc()
                continue
            if res["ok"]:
                extra = f", {res['throttled']} throttled sub-resources" if res["throttled"] else ""
                print(f"  OK       {site.slug:<10} {res['pages']} page(s), "
                      f"{res['secs']}s, {res['size_kb']} KB{extra}")
            else:
                print(f"  EMPTY    {site.slug:<10} {res['error']}")
            if i < len(todo) - 1:
                await asyncio.sleep(2.0)   # polite gap between origins


# --------------------------------------------------------------------------- #
# Score phase - fully offline (rebuild + compare against cached originals).      #
# --------------------------------------------------------------------------- #
async def build_site(slug: str, data: dict) -> tuple[Path, Path, list, list, dict]:
    opts: ReplicationOptions = data["options"]
    url: str = data["url"]
    pages = data["pages"]

    site_dir = BENCH_DIR / slug / "site"
    shots_dir = BENCH_DIR / slug / "shots"
    if site_dir.exists():
        shutil.rmtree(site_dir, ignore_errors=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)

    analysis = analyze(pages, url)
    analysis["interactions"] = interaction_report(pages)
    analysis["responsive"] = responsive_report(opts.viewport_names)

    builder = SiteBuilder(site_dir, opts, emit=_quiet)
    builder.plan(pages, url)
    async with AssetStore(site_dir, opts, emit=_quiet) as assets:
        await builder.download_assets(pages, assets)
        page_records = builder.localize_and_write(pages, assets)
        await relink_remaining_assets(site_dir, page_records, assets, opts, _quiet)
        builder.write_support(assets, page_records, analysis,
                              {"generated_at": time.time(), "options": opts.__dict__})
        purge = purge_tree(site_dir, keep_external_links=opts.keep_external_links)
        assets_failed = sum(1 for r in assets.by_url.values() if r.status == "error")
    return site_dir, shots_dir, pages, page_records, {"purge": purge, "assets_failed": assets_failed}


async def score_site(renderer: Renderer, slug: str) -> dict:
    gp = _golden_path(slug)
    if not gp.exists():
        return {"slug": slug, "ok": False, "error": "not crawled"}
    with gp.open("rb") as fh:
        data = pickle.load(fh)
    opts: ReplicationOptions = data["options"]
    t0 = time.time()
    site_dir, shots_dir, pages, page_records, extra = await build_site(slug, data)

    comparisons, avg_ssim, fixer = await manager._quality_loop(
        renderer, site_dir, shots_dir, opts, pages, page_records, _quiet)
    audit = purge_tree(site_dir, keep_external_links=opts.keep_external_links, dry_run=True)
    report = manager._quality_report(page_records, comparisons, fixer,
                                      extra["purge"], audit, extra["assets_failed"])

    # Worst (page, viewport) pairs for diagnosis.
    worst = sorted(
        ({"url": c.page_url, "viewport": c.viewport, "ssim": c.ssim,
          "diff_ratio": c.diff_ratio, "diff_png": c.diff_png, "issues": c.issues}
         for c in comparisons),
        key=lambda d: d["ssim"],
    )[:4]
    all_issues: dict[str, int] = {}
    for c in comparisons:
        for issue in c.issues:
            all_issues[issue] = all_issues.get(issue, 0) + 1

    return {
        "slug": slug,
        "kind": data.get("kind", "?"),
        "ok": True,
        "overall": report["overall_score"],
        "grade": report["grade"],
        "avg_ssim": avg_ssim,
        "pages": len([p for p in report["pages"] if p["score"] is not None]),
        "viewports": VIEWPORTS,
        "fixes": sum(p["fixes_applied"] for p in report["pages"]),
        "external_remaining": report["external_refs_remaining"],
        "assets_failed": extra["assets_failed"],
        "worst": worst,
        "issues": all_issues,
        "secs": round(time.time() - t0, 1),
    }


async def cmd_score(sites: list[Site]) -> None:
    cached = [s for s in sites if _golden_path(s.slug).exists()]
    missing = [s.slug for s in sites if not _golden_path(s.slug).exists()]
    for slug in missing:
        print(f"  skip     {slug:<10} (not crawled - run `bench.py crawl`)")
    if not cached:
        print("No cached sites to score.")
        return

    results: list[dict] = []
    async with Renderer() as renderer:          # file:// only, no live network
        for site in cached:
            print(f"  scoring  {site.slug:<10} ...", flush=True)
            try:
                res = await score_site(renderer, site.slug)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAILED   {site.slug:<10} {exc}")
                traceback.print_exc()
                results.append({"slug": site.slug, "ok": False, "error": str(exc)})
                continue
            results.append(res)
            if res["ok"]:
                pct = f"{res['overall'] * 100:.1f}%" if res["overall"] is not None else "n/a"
                print(f"  ->       {site.slug:<10} {pct:>7}  grade {res['grade']}  "
                      f"({res['pages']} pg, {res['fixes']} fixes, {res['secs']}s)")

    _print_table(results)
    _save_report(results)


# --------------------------------------------------------------------------- #
# Reporting                                                                     #
# --------------------------------------------------------------------------- #
def _print_table(results: list[dict]) -> None:
    ok = [r for r in results if r.get("ok")]
    print("\n" + "=" * 72)
    print(f"{'SITE':<11}{'TYPE':<18}{'CONCORDANCE':>12}  {'GR':<3}{'FIX':>4}{'EXT':>4}")
    print("-" * 72)
    for r in sorted(ok, key=lambda r: (r["overall"] is None, r["overall"] or 0)):
        pct = f"{r['overall'] * 100:.2f}%" if r["overall"] is not None else "   n/a"
        print(f"{r['slug']:<11}{r['kind']:<18}{pct:>12}  {r['grade']:<3}"
              f"{r['fixes']:>4}{r['external_remaining']:>4}")
    for r in results:
        if not r.get("ok"):
            print(f"{r['slug']:<11}{'ERROR':<18}  {r.get('error', '')[:30]}")
    if ok:
        scores = [r["overall"] for r in ok if r["overall"] is not None]
        if scores:
            avg = sum(scores) / len(scores)
            below = sum(1 for s in scores if s < 0.99)
            a_grade = sum(1 for r in ok if r["grade"] == "A")
            print("-" * 72)
            print(f"{'MEAN':<11}{'':<18}{avg * 100:>11.2f}%   "
                  f"{a_grade}/{len(scores)} grade-A, {below} below 99%")
    print("=" * 72)
    # Top issues across the panel, to steer the next engine fix.
    issues: dict[str, int] = {}
    for r in ok:
        for issue, n in (r.get("issues") or {}).items():
            issues[issue] = issues.get(issue, 0) + n
    if issues:
        print("Most common issues:")
        for issue, n in sorted(issues.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  x{n:<3} {issue}")


def _save_report(results: list[dict]) -> None:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
               "viewports": VIEWPORTS, "results": results}
    (BENCH_DIR / "report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = [r for r in results if r.get("ok") and r.get("overall") is not None]
    summary = {"ts": payload["ts"], "iso": payload["iso"],
               "mean": round(sum(r["overall"] for r in ok) / len(ok), 4) if ok else None,
               "scores": {r["slug"]: r["overall"] for r in ok}}
    with (BENCH_DIR / "history.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(f"\nReport: {BENCH_DIR / 'report.json'}")
    print(f"History appended: {BENCH_DIR / 'history.jsonl'}")


def cmd_list(sites: list[Site]) -> None:
    print(f"{'SLUG':<11}{'TYPE':<18}{'MODE':<12}{'CACHE':<8}URL")
    for s in sites:
        state = "yes" if _golden_path(s.slug).exists() else "-"
        print(f"{s.slug:<11}{s.kind:<18}{s.mode:<12}{state:<8}{s.url}")


# --------------------------------------------------------------------------- #
def _select(only: list[str] | None) -> list[Site]:
    if not only:
        return list(PANEL)
    chosen = []
    for slug in only:
        if slug not in PANEL_BY_SLUG:
            raise SystemExit(f"Unknown site '{slug}'. Known: {', '.join(PANEL_BY_SLUG)}")
        chosen.append(PANEL_BY_SLUG[slug])
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser(description="Replication-engine benchmark harness.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("crawl", "score", "run"):
        p = sub.add_parser(name)
        p.add_argument("--only", nargs="*", default=None, help="restrict to these slugs")
        if name in ("crawl", "run"):
            p.add_argument("--force", action="store_true", help="re-crawl even if cached")
    sub.add_parser("list")
    args = ap.parse_args()

    if args.cmd == "list":
        cmd_list(PANEL)
        return 0

    sites = _select(getattr(args, "only", None))
    if args.cmd == "crawl":
        asyncio.run(cmd_crawl(sites, force=args.force))
    elif args.cmd == "score":
        asyncio.run(cmd_score(sites))
    elif args.cmd == "run":
        async def _both():
            await cmd_crawl(sites, force=args.force)
            await cmd_score(sites)
        asyncio.run(_both())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
