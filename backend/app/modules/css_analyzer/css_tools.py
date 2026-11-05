"""CSS helpers: discover and rewrite ``url(...)`` / ``@import`` references."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urldefrag, urljoin

# url( ... ) with optional quotes.
_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+?)\1\s*\)""", re.I)
# @import "x"; or @import url(x);  (url() form handled by _URL_RE as well)
_IMPORT_RE = re.compile(r"""@import\s+(['"])([^'"]+?)\1""", re.I)


def _usable(ref: str) -> bool:
    ref = ref.strip()
    return bool(ref) and not ref.startswith(("data:", "#", "about:"))


def extract_css_urls(css_text: str, base_url: str) -> list[str]:
    """Return absolute URLs referenced from a CSS blob."""
    found: list[str] = []
    seen: set[str] = set()

    def add(ref: str) -> None:
        if not _usable(ref):
            return
        try:
            absu = urldefrag(urljoin(base_url, ref))[0]
        except ValueError:
            return
        if absu.startswith(("http://", "https://")) and absu not in seen:
            seen.add(absu)
            found.append(absu)

    for m in _URL_RE.finditer(css_text):
        add(m.group(2))
    for m in _IMPORT_RE.finditer(css_text):
        add(m.group(2))
    return found


def rewrite_css_urls(css_text: str, base_url: str, mapper: Callable[[str], str | None]) -> str:
    """Rewrite references in CSS.

    ``mapper`` receives an absolute URL and returns the replacement string
    (typically a relative local path) or ``None`` to leave it unchanged.
    """

    def _abs(ref: str) -> str | None:
        if not _usable(ref):
            return None
        try:
            return urldefrag(urljoin(base_url, ref))[0]
        except ValueError:
            return None

    def _url_sub(m: re.Match) -> str:
        quote, ref = m.group(1), m.group(2)
        absu = _abs(ref)
        if absu is None:
            return m.group(0)
        replacement = mapper(absu)
        if replacement is None:
            return m.group(0)
        return f"url({quote}{replacement}{quote})"

    def _import_sub(m: re.Match) -> str:
        quote, ref = m.group(1), m.group(2)
        absu = _abs(ref)
        if absu is None:
            return m.group(0)
        replacement = mapper(absu)
        if replacement is None:
            return m.group(0)
        return f'@import {quote}{replacement}{quote}'

    css_text = _IMPORT_RE.sub(_import_sub, css_text)
    css_text = _URL_RE.sub(_url_sub, css_text)
    return css_text
