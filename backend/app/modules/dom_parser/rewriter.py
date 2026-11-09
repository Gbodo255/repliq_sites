"""Rewrite a rendered page's HTML into a self-contained local document.

Two entry points:

* :func:`collect_asset_urls` - find every asset the HTML references so the
  downloader can fetch them first.
* :func:`localize_html` - produce the final HTML with every URL rewritten to a
  local relative path (assets + captured internal pages), framework runtime
  scripts stripped (unless ``keep_js``), and lazy-load attributes resolved.
"""
from __future__ import annotations

import posixpath
import re
from typing import Callable
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

from app.modules.dom_parser.script_policy import keep_anim_script

from app.modules.css_analyzer.css_tools import extract_css_urls, rewrite_css_urls

_PLACEHOLDER_RE = re.compile(r"^(data:image/(gif|svg|png);base64,|data:,)|^$", re.I)
# Scripts worth keeping even when stripping JS (structured data).
_KEEP_SCRIPT_TYPES = {"application/json", "application/ld+json"}


def _abs(base: str, ref: str | None) -> str | None:
    if not ref:
        return None
    ref = ref.strip()
    if not ref or ref.startswith(("data:", "#", "mailto:", "tel:", "javascript:", "blob:")):
        return None
    try:
        u = urldefrag(urljoin(base, ref))[0]
    except ValueError:
        return None
    return u if u.startswith(("http://", "https://")) else None


def _iter_srcset(value: str):
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        yield bits[0], (" " + " ".join(bits[1:]) if len(bits) > 1 else "")


def collect_asset_urls(html: str, base_url: str, keep_js: bool | str = False) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    seen: set[str] = set()

    def add(u: str | None):
        if u and u not in seen:
            seen.add(u)
            found.append(u)

    for link in soup.find_all("link", href=True):
        rels = {r.lower() for r in (link.get("rel") or [])}
        if rels & {"stylesheet", "icon", "shortcut", "apple-touch-icon", "mask-icon", "preload", "manifest"}:
            if "preload" in rels and (link.get("as") or "").lower() == "script" and keep_js is not True:
                continue
            add(_abs(base_url, link.get("href")))

    for img in soup.find_all("img"):
        add(_abs(base_url, img.get("src")))
        add(_abs(base_url, img.get("data-src")))
        for attr in ("srcset", "data-srcset"):
            if img.get(attr):
                for u, _ in _iter_srcset(img[attr]):
                    add(_abs(base_url, u))

    for tag in soup.find_all(["source", "video", "audio"]):
        add(_abs(base_url, tag.get("src")))
        add(_abs(base_url, tag.get("poster")))
        if tag.get("srcset"):
            for u, _ in _iter_srcset(tag["srcset"]):
                add(_abs(base_url, u))

    if keep_js:
        for s in soup.find_all("script", src=True):
            u = _abs(base_url, s.get("src"))
            if keep_js is True or keep_anim_script(u, base_url, "", s.get("type") or ""):
                add(u)

    # Inline style="" and <style> blocks.
    for el in soup.find_all(style=True):
        for u in extract_css_urls(el["style"], base_url):
            add(u)
    for st in soup.find_all("style"):
        if st.string:
            for u in extract_css_urls(st.string, base_url):
                add(u)

    return found


def localize_html(
    html: str,
    page_base_url: str,
    page_dir: str,
    asset_lookup: Callable[[str], str | None],
    page_lookup: Callable[[str], str | None],
    keep_js: bool | str = False,  # True: keep all, "anim": hybrid (script_policy), False: strip
    inject_head: str = "",
    inject_body_end: str = "",
    snap_lookup: dict[str, str] | None = None,
) -> str:
    """Return localized HTML.

    ``asset_lookup`` / ``page_lookup`` map an absolute URL to a path relative to
    the project root (or ``None`` if not captured).  ``page_dir`` is the output
    directory of this page relative to the root, used to compute relative links.
    """
    soup = BeautifulSoup(html, "lxml")

    def rel_asset(u: str | None) -> str | None:
        if not u:
            return None
        root_rel = asset_lookup(u)
        if not root_rel:
            return None
        return posixpath.relpath(root_rel, page_dir) if page_dir else root_rel

    def rel_page(u: str | None) -> str | None:
        if not u:
            return None
        root_rel = page_lookup(u)
        if not root_rel:
            return None
        return posixpath.relpath(root_rel, page_dir) if page_dir else root_rel

    # Drop <base> so relative URLs resolve against the local file.
    for b in soup.find_all("base"):
        b.decompose()

    # Embedded iframes / canvases captured as images by the renderer.
    snap_lookup = snap_lookup or {}
    for el in soup.find_all(attrs={"data-rx-snap": True}):
        sid = el.get("data-rx-snap")
        del el["data-rx-snap"]
        root_rel = snap_lookup.get(sid)
        if not root_rel:
            continue
        local = posixpath.relpath(root_rel, page_dir) if page_dir else root_rel
        if el.name == "canvas":
            el.name = "img"
            el["src"] = local
            el["alt"] = ""
            el.clear()
        else:  # iframe: keep the element (and its CSS box), show the capture
            for a in ("src", "loading", "allow", "sandbox", "allowfullscreen"):
                el.attrs.pop(a, None)
            el["srcdoc"] = (
                "<style>html,body{margin:0;height:100%;overflow:hidden}"
                "img{display:block;width:100%;height:100%;object-fit:cover}</style>"
                f'<img src="{local}" alt="">'
            )
            el.clear()

    # Inline event handlers reference the stripped runtime: drop them so the
    # static copy never throws "x is not defined" errors.
    if not keep_js:
        for el in soup.find_all(True):
            for attr in [a for a in el.attrs if a.lower().startswith("on")]:
                del el[attr]

    # Scripts: strip framework runtime unless explicitly kept.
    for s in soup.find_all("script"):
        stype = (s.get("type") or "").lower()
        if keep_js == "anim" and not keep_anim_script(
                _abs(page_base_url, s.get("src")), page_base_url, s.string or "", stype):
            if stype not in _KEEP_SCRIPT_TYPES:
                s.decompose()
            continue
        if keep_js:
            u = _abs(page_base_url, s.get("src"))
            local = rel_asset(u)
            if local:
                s["src"] = local
                s.attrs.pop("integrity", None)
                s.attrs.pop("crossorigin", None)
        elif stype not in _KEEP_SCRIPT_TYPES:
            s.decompose()

    # Links.
    for link in soup.find_all("link", href=True):
        rels = {r.lower() for r in (link.get("rel") or [])}
        if (link.get("as") or "").lower() == "script" and keep_js is not True:
            link.decompose()
            continue
        local = rel_asset(_abs(page_base_url, link.get("href")))
        if local:
            link["href"] = local
            link.attrs.pop("integrity", None)
            link.attrs.pop("crossorigin", None)

    # Images (incl. lazy-load resolution + srcset).
    for img in soup.find_all("img"):
        src_abs = _abs(page_base_url, img.get("src"))
        # Resolve common lazy patterns when the visible src is a placeholder.
        if (not src_abs or _PLACEHOLDER_RE.match(img.get("src", ""))) and img.get("data-src"):
            src_abs = _abs(page_base_url, img.get("data-src"))
        local = rel_asset(src_abs)
        if local:
            img["src"] = local
        img.attrs.pop("loading", None)
        chosen_srcset = img.get("srcset") or img.get("data-srcset")
        if chosen_srcset:
            img["srcset"] = _rewrite_srcset(chosen_srcset, page_base_url, rel_asset)
        img.attrs.pop("data-src", None)
        img.attrs.pop("data-srcset", None)

    for tag in soup.find_all(["source", "video", "audio"]):
        local = rel_asset(_abs(page_base_url, tag.get("src")))
        if local:
            tag["src"] = local
        if tag.get("poster"):
            p = rel_asset(_abs(page_base_url, tag.get("poster")))
            if p:
                tag["poster"] = p
        if tag.get("srcset"):
            tag["srcset"] = _rewrite_srcset(tag["srcset"], page_base_url, rel_asset)

    # Inline styles and <style> blocks.
    for el in soup.find_all(style=True):
        el["style"] = rewrite_css_urls(el["style"], page_base_url, lambda u: rel_asset(u))
    for st in soup.find_all("style"):
        if st.string:
            st.string.replace_with(
                rewrite_css_urls(st.string, page_base_url, lambda u: rel_asset(u))
            )

    # Internal navigation links -> local captured pages.
    for a in soup.find_all("a", href=True):
        target = _abs(page_base_url, a.get("href"))
        if not target:
            continue
        local = rel_page(target)
        if local:
            a["href"] = local
        else:
            a["href"] = target  # keep absolute to the live site

    # Injections (quality/interaction helpers). html.parser keeps the fragment
    # from being wrapped in <html>/<body>, so every top-level node is appended.
    if inject_head and soup.head:
        for node in list(BeautifulSoup(inject_head, "html.parser").contents):
            soup.head.append(node)
    if inject_body_end and soup.body:
        for node in list(BeautifulSoup(inject_body_end, "html.parser").contents):
            soup.body.append(node)

    return str(soup)


def _rewrite_srcset(value: str, base: str, rel_asset: Callable[[str], str | None]) -> str:
    out = []
    for url, descriptor in _iter_srcset(value):
        absu = _abs(base, url)
        local = rel_asset(absu) if absu else None
        out.append((local or url) + descriptor)
    return ", ".join(out)
