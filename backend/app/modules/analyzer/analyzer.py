"""Structural + visual analysis of the captured pages.

Produces a JSON-serialisable report (written to ``data/analysis.json``) that
records the colour palette, fonts, detected front-end framework, navigation,
reusable components and a per-page outline.  The renderer already sampled
computed colours/fonts in-browser; here we merge those with a static structural
pass over the rendered DOM.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.models.domain import RenderedPage

_FRAMEWORK_SIGNS = [
    ("Next.js", ["__next", "__NEXT_DATA__", "/_next/"]),
    ("Nuxt", ["__nuxt", "__NUXT__", "/_nuxt/"]),
    ("React", ["data-reactroot", "data-reactid", "react"]),
    ("Vue", ["data-v-", "data-server-rendered", "__vue__"]),
    ("Angular", ["ng-version", "ng-app", "_nghost", "_ngcontent"]),
    ("Svelte", ["svelte-"]),
    ("WordPress", ["wp-content", "wp-includes", "wp-json"]),
    ("Webflow", ["w-nav", "data-wf-", "webflow"]),
    ("Framer", ["framer-", "data-framer"]),
    ("Gatsby", ["___gatsby", "gatsby-"]),
    ("Elementor", ["elementor", "elementor-widget"]),
]

_COMPONENT_HINTS = {
    "carousel": ["carousel", "swiper", "slick", "glide", "splide", "embla"],
    "slider": ["slider", "range-slider"],
    "accordion": ["accordion", "faq", "collapsible"],
    "tabs": ["tab-", "tabs", "nav-tabs", "role=tab"],
    "modal": ["modal", "dialog", "lightbox", "popup"],
    "gallery": ["gallery", "masonry", "lightgallery"],
    "dropdown": ["dropdown", "has-submenu", "sub-menu"],
    "mobile_nav": ["hamburger", "menu-toggle", "navbar-toggle", "burger", "nav-toggle"],
    "form": ["<form"],
}


def _detect_framework(all_html: str) -> list[str]:
    low = all_html.lower()
    hits = []
    for name, signs in _FRAMEWORK_SIGNS:
        if any(s.lower() in low for s in signs):
            hits.append(name)
    return hits


def _page_outline(soup: BeautifulSoup) -> dict:
    headings = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        txt = h.get_text(" ", strip=True)
        if txt:
            headings.append({"level": h.name, "text": txt[:120]})
    return {
        "headings": headings[:40],
        "sections": len(soup.find_all("section")),
        "images": len(soup.find_all("img")),
        "forms": len(soup.find_all("form")),
        "links": len(soup.find_all("a", href=True)),
        "nav_items": len(soup.select("nav a")),
    }


def _detect_components(html_low: str) -> list[str]:
    found = []
    for name, hints in _COMPONENT_HINTS.items():
        if any(h in html_low for h in hints):
            found.append(name)
    return found


def analyze(pages: list[RenderedPage], seed_url: str) -> dict:
    palette = Counter()
    fonts = Counter()
    components: Counter = Counter()
    all_html_parts = []
    page_reports = []

    for p in pages:
        if not p.html:
            continue
        all_html_parts.append(p.html[:200000])
        for c in p.analysis.get("palette", []):
            palette[c] += 1
        for f in p.analysis.get("fonts", []):
            # font-family values can be comma lists; keep the first family.
            first = f.split(",")[0].strip().strip("'\"")
            if first:
                fonts[first] += 1
        soup = BeautifulSoup(p.html, "lxml")
        outline = _page_outline(soup)
        comps = _detect_components(p.html.lower())
        for c in comps:
            components[c] += 1
        page_reports.append({
            "url": p.url,
            "title": p.title,
            "ok": p.ok,
            "node_count": p.analysis.get("nodeCount", outline["links"]),
            "components": comps,
            **outline,
        })

    all_html = "\n".join(all_html_parts)
    return {
        "seed_url": seed_url,
        "host": urlparse(seed_url).hostname,
        "pages_count": len(pages),
        "frameworks": _detect_framework(all_html),
        "palette": [c for c, _ in palette.most_common(16)],
        "fonts": [f for f, _ in fonts.most_common(10)],
        "components": [c for c, _ in components.most_common()],
        "pages": page_reports,
    }
