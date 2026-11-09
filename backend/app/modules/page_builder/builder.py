"""Assemble the self-contained local site.

Given the rendered pages and a populated :class:`AssetStore`, the builder:

1. assigns each captured page a local output path (``index.html`` for the seed,
   ``pages/<slug>.html`` for the rest),
2. discovers every asset referenced by the pages and downloads it,
3. rewrites each page's HTML to point at local assets + local pages, injects the
   viewport meta, the small responsive stylesheet and ``interactions.js``, and
   writes the ``.html`` files, and
4. writes the support files (``css/responsive.css``, ``js/interactions.js`` and
   the JSON manifests under ``data/``).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import posixpath
from pathlib import Path

import re

from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.modules.auto_fixer.layout import media_ranges
from app.core.utils import categorize, ext_from_url, safe_filename, short_hash, slugify
from app.models.domain import PageRecord, RenderedPage, ReplicationOptions
from app.modules.asset_downloader.downloader import AssetStore
from app.modules.crawler.crawler import canonicalize
from app.modules.css_analyzer.css_tools import extract_css_urls  # noqa: F401 (re-export friendliness)
from app.modules.dom_parser.rewriter import collect_asset_urls, localize_html
from app.modules.interaction_analyzer.interactions import INTERACTIONS_JS
from app.modules.interaction_analyzer.motion_css import motion_css
from app.modules.interaction_analyzer.players import write_page_media, write_vendor
from app.modules.dom_parser.script_policy import has_framework_runtime
from app.modules.responsive_analyzer.responsive import (
    RESPONSIVE_CSS,
    VIEWPORT_META,
    has_viewport_meta,
)

log = get_logger("builder")

_ASSET_CATEGORIES_FROM_RESOURCES = {"images", "icons", "fonts", "videos", "css"}


class SiteBuilder:
    def __init__(self, output_root: Path, options: ReplicationOptions, emit=lambda **k: None) -> None:
        self.root = output_root
        self.options = options
        self.emit = emit
        self.page_map: dict[str, str] = {}   # canonical url -> rel output path
        self._used_slugs: set[str] = set()

    # ------------------------------------------------------------- planning
    def plan(self, pages: list[RenderedPage], seed_url: str) -> None:
        seed_c = canonicalize(seed_url)
        index_assigned = False
        # First, try to map the seed exactly to index.html.
        for p in pages:
            keys = self._keys(p)
            if seed_c in keys and not index_assigned:
                self._assign(p, "index.html")
                index_assigned = True
        for p in pages:
            if any(k in self.page_map for k in self._keys(p)):
                continue
            if not index_assigned:
                self._assign(p, "index.html")
                index_assigned = True
            else:
                self._assign(p, f"pages/{self._slug(p.url)}.html")

    def _keys(self, page: RenderedPage) -> list[str]:
        keys = [canonicalize(page.url)]
        if page.final_url:
            keys.append(canonicalize(page.final_url))
        return list(dict.fromkeys(keys))

    def _assign(self, page: RenderedPage, rel: str) -> None:
        for k in self._keys(page):
            self.page_map[k] = rel

    def _slug(self, url: str) -> str:
        from urllib.parse import urlparse

        p = urlparse(url)
        path = p.path.strip("/")
        slug = slugify(path.replace("/", "-")) if path else "home"
        if p.query:
            slug = f"{slug}-{short_hash(p.query, 5)}"
        if slug in self._used_slugs:
            slug = f"{slug}-{short_hash(url, 5)}"
        self._used_slugs.add(slug)
        return slug

    # ------------------------------------------------------------- assets
    def _candidate_asset_urls(self, pages: list[RenderedPage]) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        def add(u: str):
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

        for p in pages:
            base = p.final_url or p.url
            if p.html:
                for u in collect_asset_urls(p.html, base, self.options.js_keep):
                    add(u)
            # Assets referenced only by a smaller-breakpoint DOM variant
            # (Framer re-renders per breakpoint) must be downloaded too.
            for vhtml in ((p.analysis or {}).get("bp_dom") or {}).values():
                for u in collect_asset_urls(vhtml, base, self.options.js_keep):
                    add(u)
            for u in p.stylesheet_urls:
                add(u)
            # Runtime-loaded resources that are clearly assets (bg images, fonts...).
            for u in p.resource_urls:
                ext = ext_from_url(u)
                cat = categorize(ext)
                if cat in _ASSET_CATEGORIES_FROM_RESOURCES:
                    add(u)
                elif cat == "js" and self.options.js_keep:
                    add(u)
        return urls

    async def download_assets(self, pages: list[RenderedPage], store: AssetStore) -> None:
        candidates = self._candidate_asset_urls(pages)
        total = len(candidates)
        self.emit(phase="assets", message=f"Found {total} candidate assets", progress=52,
                  data={"total": total})
        done = 0

        async def one(url: str):
            nonlocal done
            await store.fetch(url)
            done += 1
            if done % 5 == 0 or done == total:
                pct = 52 + int(28 * done / max(1, total))
                self.emit(phase="assets",
                          message=f"Downloaded {done}/{total} assets",
                          progress=min(pct, 80),
                          data={"done": done, "total": total,
                                "bytes": store.total_bytes})

        # The store's own semaphore bounds real concurrency.
        await asyncio.gather(*(one(u) for u in candidates))
        ok = len(store.ok_assets())
        self.emit(phase="assets", message=f"Assets ready: {ok}/{total} ok", progress=80,
                  data={"ok": ok, "total": total, "bytes": store.total_bytes})

    # ------------------------------------------------------------- write pages
    def localize_and_write(self, pages: list[RenderedPage], store: AssetStore) -> list[PageRecord]:
        records: list[PageRecord] = []
        self._vendor_libs: set[str] = getattr(self, "_vendor_libs", set())
        page_lookup = self._make_page_lookup()
        asset_lookup = self._make_asset_lookup(store)
        n = len([p for p in pages if p.html])
        i = 0
        for p in pages:
            rel = None
            for k in self._keys(p):
                if k in self.page_map:
                    rel = self.page_map[k]
                    break
            if rel is None or not p.html:
                records.append(PageRecord(url=p.url, title=p.title, status="error",
                                          error=p.error or "no HTML captured"))
                continue
            i += 1
            page_dir = posixpath.dirname(rel)
            depth_prefix = "../" * (page_dir.count("/") + 1) if page_dir else ""
            head_inject = ""
            if not has_viewport_meta(p.html):
                head_inject += VIEWPORT_META
            head_inject += f'<link rel="stylesheet" href="{depth_prefix}css/responsive.css">'
            resp_css = self._responsive_inline_css(p)
            if resp_css:
                head_inject += f'<style id="rx-responsive">{resp_css}</style>'
            # The site's own JavaScript drives the motion (keep_js, or the
            # hybrid mode on a page with no framework runtime): no replays.
            site_js = self.options.keep_js or (
                self.options.keep_anim_js and not has_framework_runtime(p.html, p.final_url or p.url))
            mo_css = "" if site_js else motion_css(p.analysis or {}, self._primary_range())
            if mo_css:
                head_inject += f'<style id="rx-motion">{mo_css}</style>'
            body_inject = f'<script src="{depth_prefix}js/interactions.js"></script>'

            snap_lookup: dict[str, str] = {}
            stem = posixpath.splitext(posixpath.basename(rel))[0]
            for sid, png in (p.snapshots or {}).items():
                rec_snap = store.add_generated(
                    f"rx-snap://{rel}/{sid}", png, f"embed-{stem}-{sid}.png")
                snap_lookup[sid] = rec_snap.local_path

            body_attrs: dict[str, object] = {}
            bp = self._breakpoint_classes(p)
            if bp:
                body_attrs["data-rx-bp"] = bp
            reveal = p.analysis.get("reveal") or []
            if reveal and not site_js:
                body_attrs["data-rx-reveal"] = reveal
            scroll_state = p.analysis.get("scroll_state") or {}
            if scroll_state.get("rows") and not site_js:
                body_attrs["data-rx-scroll"] = scroll_state
            text_fx = p.analysis.get("text_fx") or []
            if text_fx and not site_js:
                body_attrs["data-rx-text"] = text_fx
            media_spec, libs = ({}, set()) if site_js else write_page_media(self.root, p, rel, depth_prefix)
            if media_spec:
                body_attrs["data-rx-media"] = media_spec
                self._vendor_libs |= libs
            p_html = self._inject_body_attrs(p.html, body_attrs)

            # Per-breakpoint DOM variants (Framer & other runtimes re-render a
            # different DOM per breakpoint; a single captured DOM only matches at
            # the primary width). Inject each distinct variant and switch by
            # width so the copy matches the live site at every viewport.
            p_html, bp_css = self._merge_bp_variants(p, p_html)
            if bp_css:
                head_inject += f'<style id="rx-breakpoints">{bp_css}</style>'

            html = localize_html(
                p_html, p.final_url or p.url, page_dir,
                asset_lookup, page_lookup,
                keep_js=self.options.js_keep,
                inject_head=head_inject,
                inject_body_end=body_inject,
                snap_lookup=snap_lookup,
            )
            out_path = self.root / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            data = html.encode("utf-8")
            out_path.write_text(html, encoding="utf-8")
            rec = PageRecord(
                url=p.url, title=p.title, output_path=rel, status="built",
                html_bytes=len(data), links=p.links,
            )
            records.append(rec)
            self.emit(phase="build", message=f"Wrote {rel}",
                      progress=min(80 + int(10 * i / max(1, n)), 90),
                      data={"path": rel})
        return records

    def _primary_range(self):
        """Width range of the primary (captured) breakpoint, or None if alone."""
        names = list(self.options.viewport_names or [])
        if len(names) < 2:
            return None
        return media_ranges(names).get(names[0])

    def _responsive_inline_css(self, page: RenderedPage) -> str:
        """Inline styles the original JavaScript set per breakpoint, as CSS."""
        per_vp = page.analysis.get("vp_styles") or {}
        if not per_vp:
            return ""
        from app.modules.auto_fixer.layout import _valid_path, render_css
        ranges = media_ranges(list(per_vp))
        rules = {}
        for vp, diffs in per_vp.items():
            clean = {}
            for sel, props in (diffs or {}).items():
                if not _valid_path(sel):
                    continue
                ok = {k: v for k, v in props.items()
                      if re.match(r"^[a-z-]+$", k) and v is not None and "<" not in str(v) and "{" not in str(v)}
                if ok:
                    clean[sel] = ok
            if clean:
                rules[vp] = clean
        if not rules:
            return ""
        return render_css(rules, ranges).replace(
            "rx-fidelity: restores the original computed layout state",
            "rx-responsive: inline styles set by the original JavaScript per breakpoint")

    @staticmethod
    def _inject_body_attrs(html: str, attrs: dict) -> str:
        """Add ``data-rx-*`` attributes (JSON values) to the first <body> tag."""
        if not attrs:
            return html
        parts = []
        for name, value in attrs.items():
            attr = (json.dumps(value, separators=(",", ":"))
                    .replace("&", "&amp;").replace("'", "&#39;").replace("<", "\\u003c"))
            parts.append(f"{name}='{attr}'")
        injected = "<body " + " ".join(parts)
        # A function replacement avoids re.sub interpreting backslashes (<).
        return re.sub(r"<body\b", lambda _m: injected, html, count=1, flags=re.I)

    # ----------------------------------------------------- breakpoint variants
    _VARIANT_SKIP_TAGS = {"script", "style", "link", "meta", "noscript", "template"}

    @classmethod
    def _dominant_root(cls, body) -> tuple:
        """The body's main content wrapper (most descendants), e.g. Framer's
        ``<div id="main">``. Scripts/links/meta are ignored."""
        best, best_n = None, -1
        for child in body.find_all(recursive=False):
            if not getattr(child, "name", None) or child.name in cls._VARIANT_SKIP_TAGS:
                continue
            n = len(child.find_all(True))
            if n > best_n:
                best, best_n = child, n
        return best, best_n

    @staticmethod
    def _struct_fp(root) -> str:
        """Structural fingerprint (tag + first class per descendant). Two DOMs
        that a framework re-rendered for different breakpoints differ here
        (Framer swaps the breakpoint ancestor class); a single CSS-responsive
        DOM is identical, so its variant is skipped (no bloat)."""
        parts = []
        for el in root.find_all(True)[:4000]:
            cls = el.get("class") or []
            parts.append(el.name + "." + (cls[0] if cls else ""))
        return hashlib.md5("|".join(parts).encode("utf-8", "ignore")).hexdigest()

    def _merge_bp_variants(self, page: RenderedPage, primary_html: str) -> tuple[str, str]:
        """Inject each distinct per-breakpoint DOM variant as a sibling content
        root and return ``(merged_html, media_css)`` that shows exactly one per
        width. No-op when no variant was captured or all variants match the
        primary DOM (pure CSS-responsive site)."""
        bp_dom = (page.analysis or {}).get("bp_dom") or {}
        vps = list(self.options.viewport_names)
        if not bp_dom or len(vps) < 2:
            return primary_html, ""
        primary_vp = vps[0]
        soup = BeautifulSoup(primary_html, "lxml")
        body = soup.body
        if body is None:
            return primary_html, ""
        proot, pn = self._dominant_root(body)
        if proot is None or pn < 20:
            return primary_html, ""
        proot_fp = self._struct_fp(proot)
        # groups[i] = {vps:set, fp:str, tag:str}; group 0 is the primary DOM.
        groups = [{"vps": {primary_vp}, "fp": proot_fp, "tag": "g0"}]
        for name in vps[1:]:
            vhtml = bp_dom.get(name)
            if not vhtml:
                groups[0]["vps"].add(name)
                continue
            vbody = BeautifulSoup(vhtml, "lxml").body
            vroot, vn = (self._dominant_root(vbody) if vbody else (None, -1))
            if vroot is None or vn < 20:
                groups[0]["vps"].add(name)
                continue
            vfp = self._struct_fp(vroot)
            match = next((g for g in groups if g["fp"] == vfp), None)
            if match is not None:
                match["vps"].add(name)
                continue
            tag = f"g{len(groups)}"
            vroot["data-rx-bpv"] = tag
            proot.insert_after(vroot)
            groups.append({"vps": {name}, "fp": vfp, "tag": tag})
        if len(groups) == 1:
            return primary_html, ""   # every breakpoint shares the primary DOM
        proot["data-rx-bpv"] = "g0"
        ranges = media_ranges(vps)
        css = ["/* rx-breakpoints: per-breakpoint DOM variants (framework re-render) */"]
        for g in groups:
            for vp_name, (lo, hi) in ranges.items():
                if vp_name in g["vps"]:
                    continue
                conds = []
                if lo:
                    conds.append(f"(min-width:{lo}px)")
                if hi is not None:
                    conds.append(f"(max-width:{hi}px)")
                guard = f"@media {' and '.join(conds)}" if conds else "@media all"
                css.append(f'{guard}{{[data-rx-bpv="{g["tag"]}"]{{display:none!important}}}}')
        # The @media rules above are a no-JS fallback. A framework (Framer) often
        # pins its own `display:...!important` on a variant root, whose id/class
        # selector outranks our ``[data-rx-bpv]`` attribute selector, so the
        # hidden variant would leak and double the page height. Emit the visible
        # width range per group so interactions.js enforces the choice with an
        # inline ``!important`` display, which beats any stylesheet rule.
        bpv_ranges = []
        for g in groups:
            los = [ranges[v][0] for v in g["vps"] if v in ranges]
            his = [ranges[v][1] for v in g["vps"] if v in ranges]
            lo = min(los) if los else 0
            hi = None if any(h is None for h in his) else (max(his) if his else None)
            bpv_ranges.append([g["tag"], lo, hi])
        body["data-rx-bpv-ranges"] = json.dumps(bpv_ranges, separators=(",", ":"))
        return str(soup), "\n".join(css)

    def _breakpoint_classes(self, page: RenderedPage) -> list:
        """Classes that the original JavaScript toggles per breakpoint.

        Returns ``[[min, max|null, addHtml, removeHtml, addBody, removeBody], ...]``
        relative to the classes serialised in the HTML (primary viewport), so
        ``interactions.js`` can replay them on load and on resize.
        """
        base = page.analysis.get("base_classes")
        per_vp = page.analysis.get("vp_classes") or {}
        if not base or len(per_vp) < 2:
            return []
        ranges = media_ranges(list(per_vp))
        out = []
        b_html, b_body = set(base[0].split()), set(base[1].split())
        for vp, (lo, hi) in ranges.items():
            cls = per_vp.get(vp)
            if not cls:
                continue
            v_html, v_body = set(cls[0].split()), set(cls[1].split())
            row = [lo, hi, sorted(v_html - b_html), sorted(b_html - v_html),
                   sorted(v_body - b_body), sorted(b_body - v_body)]
            out.append(row)
        if all(not any(r[2:]) for r in out):
            return []
        return out

    def _make_page_lookup(self):
        def lookup(abs_url: str) -> str | None:
            return self.page_map.get(canonicalize(abs_url))
        return lookup

    def _make_asset_lookup(self, store: AssetStore):
        def lookup(abs_url: str) -> str | None:
            rec = store.by_url.get(abs_url)
            if rec and rec.status == "ok" and rec.local_path:
                return rec.local_path
            return None
        return lookup

    # ------------------------------------------------------------- support files
    def write_support(self, store: AssetStore, page_records: list[PageRecord],
                      analysis: dict, extras: dict) -> None:
        (self.root / "css").mkdir(parents=True, exist_ok=True)
        (self.root / "js").mkdir(parents=True, exist_ok=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)

        (self.root / "css" / "responsive.css").write_text(RESPONSIVE_CSS, encoding="utf-8")
        (self.root / "js" / "interactions.js").write_text(INTERACTIONS_JS, encoding="utf-8")
        write_vendor(self.root, getattr(self, "_vendor_libs", set()))

        (self.root / "data" / "assets-manifest.json").write_text(
            json.dumps(store.manifest(), indent=2, ensure_ascii=False), encoding="utf-8")
        (self.root / "data" / "pages-manifest.json").write_text(
            json.dumps([r.to_dict() for r in page_records], indent=2, ensure_ascii=False),
            encoding="utf-8")
        (self.root / "data" / "analysis.json").write_text(
            json.dumps({**analysis, **extras}, indent=2, ensure_ascii=False), encoding="utf-8")
