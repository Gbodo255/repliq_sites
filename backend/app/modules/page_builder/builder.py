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
import json
import posixpath
from pathlib import Path

import re

from app.core.logging import get_logger
from app.modules.auto_fixer.layout import media_ranges
from app.core.utils import categorize, ext_from_url, safe_filename, short_hash, slugify
from app.models.domain import PageRecord, RenderedPage, ReplicationOptions
from app.modules.asset_downloader.downloader import AssetStore
from app.modules.crawler.crawler import canonicalize
from app.modules.css_analyzer.css_tools import extract_css_urls  # noqa: F401 (re-export friendliness)
from app.modules.dom_parser.rewriter import collect_asset_urls, localize_html
from app.modules.interaction_analyzer.interactions import INTERACTIONS_JS
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
                for u in collect_asset_urls(p.html, base, self.options.keep_js):
                    add(u)
            for u in p.stylesheet_urls:
                add(u)
            # Runtime-loaded resources that are clearly assets (bg images, fonts...).
            for u in p.resource_urls:
                ext = ext_from_url(u)
                cat = categorize(ext)
                if cat in _ASSET_CATEGORIES_FROM_RESOURCES:
                    add(u)
                elif cat == "js" and self.options.keep_js:
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
            if reveal:
                body_attrs["data-rx-reveal"] = reveal
            scroll_state = p.analysis.get("scroll_state") or {}
            if scroll_state.get("rows"):
                body_attrs["data-rx-scroll"] = scroll_state
            p_html = self._inject_body_attrs(p.html, body_attrs)

            html = localize_html(
                p_html, p.final_url or p.url, page_dir,
                asset_lookup, page_lookup,
                keep_js=self.options.keep_js,
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

        (self.root / "data" / "assets-manifest.json").write_text(
            json.dumps(store.manifest(), indent=2, ensure_ascii=False), encoding="utf-8")
        (self.root / "data" / "pages-manifest.json").write_text(
            json.dumps([r.to_dict() for r in page_records], indent=2, ensure_ascii=False),
            encoding="utf-8")
        (self.root / "data" / "analysis.json").write_text(
            json.dumps({**analysis, **extras}, indent=2, ensure_ascii=False), encoding="utf-8")
