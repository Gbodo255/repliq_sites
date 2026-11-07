"""Responsive behaviour support.

The original site's own CSS (including its ``@media`` queries) is preserved
verbatim, so responsive layout is reproduced by keeping that CSS rather than
regenerating it.  This module only (a) guarantees a ``<meta name=viewport>`` tag
exists so mobile rendering matches, and (b) reports, per breakpoint, the
captured page dimensions for the side-by-side preview.
"""
from __future__ import annotations

import re

_VIEWPORT_RE = re.compile(r"<meta[^>]+name=['\"]?viewport", re.I)

# Kept intentionally minimal so it never overrides the site's own responsive CSS.
RESPONSIVE_CSS = (
    "/* responsive.css - the original site CSS (with its media queries) is kept\n"
    "   verbatim and drives the responsive layout. Only safe, non-destructive\n"
    "   fallbacks live here. */\n"
    "body.nav-open { overflow: hidden; }\n"
    "/* Web-component popups (menus/dropdowns slotted into a shadow DOM) are\n"
    "   hidden on the live site by component logic that the static copy loses\n"
    "   when its JavaScript is stripped; the capture marked the ones that were\n"
    "   collapsed so they stay collapsed here instead of rendering open. */\n"
    "[data-rx-collapsed] { display: none !important; }\n"
)

VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1">'


def has_viewport_meta(html: str) -> bool:
    return bool(_VIEWPORT_RE.search(html or ""))


def responsive_report(viewport_names: list[str]) -> dict:
    return {
        "captured_viewports": viewport_names,
        "strategy": "original CSS preserved; viewport meta ensured",
    }
