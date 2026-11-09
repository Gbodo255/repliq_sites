"""Automatic correction pass.

The honest, reliable fix the engine can make automatically is *asset
re-linking*: after the first build + visual comparison, a generated page may
still reference a remote URL for a resource that was only discovered late (for
example a background image injected at runtime).  This pass scans every built
HTML file for leftover ``http(s)://`` asset references, downloads them, and
rewrites them to local paths.

Arbitrary layout divergence is **not** auto-corrected - that is reported by the
visual comparator instead of being silently papered over.
"""
from __future__ import annotations

import posixpath
from pathlib import Path

from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.models.domain import PageRecord, ReplicationOptions
from app.modules.asset_downloader.downloader import AssetStore
from app.modules.css_analyzer.css_tools import extract_css_urls, rewrite_css_urls

log = get_logger("fixer")


# Only these <link rel> values point at real downloadable assets. Discovery
# links (alternate/RSS, EditURI, pingback, oEmbed, api.w.org, dns-prefetch, ...)
# must stay as-is, not be downloaded as "assets".
_ASSET_LINK_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "mask-icon", "preload", "manifest"}


def _is_remote(value: str | None) -> bool:
    return bool(value) and value.strip().lower().startswith(("http://", "https://"))


def _collect_remote_refs(soup: BeautifulSoup, keep_js: bool) -> set[str]:
    refs: set[str] = set()
    for img in soup.find_all("img"):
        for a in ("src", "data-src"):
            if _is_remote(img.get(a)):
                refs.add(img[a].strip())
        for a in ("srcset", "data-srcset"):
            if img.get(a):
                for part in img[a].split(","):
                    u = part.strip().split(" ")[0]
                    if _is_remote(u):
                        refs.add(u)
    for tag in soup.find_all(["source", "video", "audio"]):
        for a in ("src", "poster"):
            if _is_remote(tag.get(a)):
                refs.add(tag[a].strip())
    for link in soup.find_all("link", href=True):
        rels = {r.lower() for r in (link.get("rel") or [])}
        if not (rels & _ASSET_LINK_RELS):
            continue  # skip oEmbed / RSS / EditURI / pingback / api.w.org etc.
        if (link.get("as") or "").lower() == "script" and not keep_js:
            continue
        if _is_remote(link.get("href")):
            refs.add(link["href"].strip())
    if keep_js:
        for s in soup.find_all("script", src=True):
            if _is_remote(s.get("src")):
                refs.add(s["src"].strip())
    for el in soup.find_all(style=True):
        for u in extract_css_urls(el["style"], ""):
            if _is_remote(u):
                refs.add(u)
    for st in soup.find_all("style"):
        if st.string:
            for u in extract_css_urls(st.string, ""):
                if _is_remote(u):
                    refs.add(u)
    return refs


async def relink_remaining_assets(
    root: Path,
    page_records: list[PageRecord],
    store: AssetStore,
    options: ReplicationOptions,
    emit=lambda **k: None,
) -> int:
    fixed_total = 0
    for rec in page_records:
        if rec.status != "built" or not rec.output_path:
            continue
        path = root / rec.output_path
        if not path.exists():
            continue
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
        remotes = _collect_remote_refs(soup, options.js_keep)
        if not remotes:
            continue

        page_dir = posixpath.dirname(rec.output_path)
        mapping: dict[str, str] = {}
        for url in remotes:
            asset = await store.fetch(url, source_page=rec.url)
            if asset and asset.status == "ok" and asset.local_path:
                mapping[url] = posixpath.relpath(asset.local_path, page_dir) if page_dir else asset.local_path
        if not mapping:
            continue

        changed = _apply_mapping(soup, mapping, options.js_keep)
        if changed:
            path.write_text(str(soup), encoding="utf-8")
            fixed_total += changed
            emit(phase="fix", message=f"Re-linked {changed} asset(s) in {rec.output_path}",
                 data={"path": rec.output_path, "fixed": changed})
    return fixed_total


def _apply_mapping(soup: BeautifulSoup, mapping: dict[str, str], keep_js: bool) -> int:
    count = 0

    def repl(v: str | None) -> str | None:
        nonlocal count
        if v and v.strip() in mapping:
            count += 1
            return mapping[v.strip()]
        return None

    for img in soup.find_all("img"):
        for a in ("src", "data-src"):
            nv = repl(img.get(a))
            if nv:
                img[a] = nv
        for a in ("srcset", "data-srcset"):
            if img.get(a):
                parts = []
                for part in img[a].split(","):
                    bits = part.strip().split(" ")
                    nv = mapping.get(bits[0])
                    if nv:
                        count += 1
                        bits[0] = nv
                    parts.append(" ".join(bits))
                img[a] = ", ".join(parts)
    for tag in soup.find_all(["source", "video", "audio"]):
        for a in ("src", "poster"):
            nv = repl(tag.get(a))
            if nv:
                tag[a] = nv
    for link in soup.find_all("link", href=True):
        nv = repl(link.get("href"))
        if nv:
            link["href"] = nv
    if keep_js:
        for s in soup.find_all("script", src=True):
            nv = repl(s.get("src"))
            if nv:
                s["src"] = nv
    for el in soup.find_all(style=True):
        new = rewrite_css_urls(el["style"], "", lambda u: mapping.get(u))
        if new != el["style"]:
            count += 1
            el["style"] = new
    for st in soup.find_all("style"):
        if st.string:
            new = rewrite_css_urls(st.string, "", lambda u: mapping.get(u))
            if new != st.string:
                count += 1
                st.string.replace_with(new)
    return count
