"""Zero-external-reference guarantee.

After assets have been localised and re-linked, anything that still points
outside the generated project is neutralised so the copy never contacts or
links to another host:

* ``<a href>`` / ``<area href>`` to another site (or to a page of the source
  site that was not captured) become ``#``; ``target``/``rel`` are dropped,
* ``<link>`` / ``<meta>`` carrying absolute URLs (canonical, preconnect,
  dns-prefetch, alternate, og:image, ...) are removed,
* remote media that could not be downloaded is replaced by a transparent pixel
  (``img``) or cleared (``source``, ``video``, ``audio``, ``iframe``, ...),
* remote ``url(...)`` in inline styles, ``<style>`` blocks and CSS files is
  replaced by an inert value; remote ``@import`` statements are removed,
* JSON-LD / JSON data scripts, HTML comments, ``data-*`` attributes holding
  absolute URLs and CSS source maps are stripped.

Namespace URIs (``xmlns``) are identifiers rather than links and are kept.
Visible text is never modified.  The same pass in ``dry_run`` mode is the
auditor that proves nothing external remains.
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment

_REMOTE_RE = re.compile(r"^\s*(https?:)?//", re.I)
_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)\s*((?:https?:)?//[^'")\s]+)\s*\1\s*\)""", re.I)
_CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*)?(['"]?)\s*(?:https?:)?//[^;]*?;""", re.I
)
_SOURCEMAP_RE = re.compile(r"/[*/]#\s*sourceMappingURL=[^\n*]*(\*/)?", re.I)
_BLANK_GIF = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
_INERT_URL = 'url("data:,")'

# attribute -> how to neutralise it
_LINK_ATTRS = {"href"}                    # a, area
_MEDIA_ATTRS = {"src", "poster", "data", "background", "lowsrc", "dynsrc"}
_SRCSET_ATTRS = {"srcset", "imagesrcset"}
_DROP_ATTRS = {"action", "formaction", "ping", "cite", "longdesc", "codebase",
               "manifest", "itemtype", "itemid", "profile"}
_KEEP_ATTRS = {"xmlns"}


def is_remote(value: str | None) -> bool:
    return bool(value) and bool(_REMOTE_RE.match(value))


def purge_css(text: str) -> tuple[str, int]:
    count = 0

    def _imp(_m):
        nonlocal count
        count += 1
        return ""

    def _url(_m):
        nonlocal count
        count += 1
        return _INERT_URL

    text = _CSS_IMPORT_RE.sub(_imp, text)
    text = _CSS_URL_RE.sub(_url, text)
    text, n = _SOURCEMAP_RE.subn("", text)
    return text, count + n


def _purge_srcset(value: str) -> tuple[str, int]:
    keep, removed = [], 0
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if is_remote(part.split()[0]):
            removed += 1
        else:
            keep.append(part)
    return ", ".join(keep), removed


def purge_soup(soup: BeautifulSoup, keep_external_links: bool = False) -> int:
    count = 0

    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
        count += 1

    for s in soup.find_all("script"):
        stype = (s.get("type") or "").lower()
        if "json" in stype or is_remote(s.get("src")):
            s.decompose()
            count += 1

    for link in soup.find_all("link"):
        if is_remote(link.get("href")) or is_remote(link.get("imagesrcset")):
            link.decompose()
            count += 1
    for meta in soup.find_all("meta"):
        if is_remote(meta.get("content")):
            meta.decompose()
            count += 1

    for el in soup.find_all(True):
        name = el.name
        for attr in list(el.attrs):
            val = el.attrs.get(attr)
            if isinstance(val, list):
                val = " ".join(val)
            if not isinstance(val, str):
                continue
            low = attr.lower()
            if low in _KEEP_ATTRS or low.startswith("xmlns:"):
                continue
            if low == "style":
                new, n = purge_css(val)
                if n:
                    el[attr] = new
                    count += n
                continue
            if low in _SRCSET_ATTRS:
                new, n = _purge_srcset(val)
                if n:
                    count += n
                    if new:
                        el[attr] = new
                    else:
                        del el[attr]
                continue
            if low == "srcdoc":
                inner = BeautifulSoup(val, "lxml")
                n = purge_soup(inner, keep_external_links)
                if n:
                    el[attr] = str(inner)
                    count += n
                continue
            if not is_remote(val):
                continue
            if low in _LINK_ATTRS and name in ("a", "area"):
                if keep_external_links:
                    continue
                el[attr] = "#"
                el.attrs.pop("target", None)
                el.attrs.pop("rel", None)
            elif low in _MEDIA_ATTRS and name == "img" and low == "src":
                el[attr] = _BLANK_GIF
            elif low in _MEDIA_ATTRS or low in _LINK_ATTRS or low in _DROP_ATTRS \
                    or low.startswith("data-") or low in {"xlink:href", "content", "value"}:
                if low == "value" and name not in ("param",):
                    continue  # a form value is user-visible text, not a reference
                del el[attr]
            else:
                continue
            count += 1

    for st in soup.find_all("style"):
        if st.string:
            new, n = purge_css(st.string)
            if n:
                st.string.replace_with(new)
                count += n
    return count


def purge_html_file(path: Path, keep_external_links: bool = False, dry_run: bool = False) -> int:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
    n = purge_soup(soup, keep_external_links)
    if n and not dry_run:
        path.write_text(str(soup), encoding="utf-8")
    return n


def purge_css_file(path: Path, dry_run: bool = False) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    new, n = purge_css(text)
    if n and not dry_run:
        path.write_text(new, encoding="utf-8")
    return n


def purge_tree(root: Path, keep_external_links: bool = False, dry_run: bool = False) -> dict:
    """Purge (or, with ``dry_run``, audit) every HTML/CSS file under ``root``."""
    report = {"html": 0, "css": 0, "files": {}}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suf = path.suffix.lower()
        if suf in (".html", ".htm"):
            n = purge_html_file(path, keep_external_links, dry_run)
            report["html"] += n
        elif suf == ".css":
            n = purge_css_file(path, dry_run)
            report["css"] += n
        elif suf in (".js", ".mjs") and not dry_run:
            text = path.read_text(encoding="utf-8", errors="replace")
            new, n = _SOURCEMAP_RE.subn("", text)
            if n:
                path.write_text(new, encoding="utf-8")
            continue
        else:
            continue
        if n:
            report["files"][path.relative_to(root).as_posix()] = n
    report["total"] = report["html"] + report["css"]
    return report
