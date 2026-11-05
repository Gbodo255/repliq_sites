"""Layout auto-fixer.

During capture the renderer records, for every element of the *original* page
and for every breakpoint, a small layout signature (computed ``display``,
``visibility``, ``opacity``, ``transform`` and box size) keyed by a structural
CSS path (``body>div:nth-of-type(2)>section:nth-of-type(1)``).  The quality
loop records the same signature on the *generated* page.

Whenever the two disagree - typically content that the stripped JavaScript used
to reveal (scroll animations, sliders, tabs, preloaders...) or that is now shown
although the live site hid it - this module emits targeted CSS overrides that
restore the original computed state, scoped by a media query to the breakpoint
where the divergence was observed.  Overrides accumulate across fix cycles so a
corrected element never regresses.
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.config import settings

_TAG_OK = re.compile(r"^[a-z][a-z0-9-]*:nth-of-type\(\d+\)$")
_STYLE_ID = "rx-fidelity"
_MAX_RULES_PER_VIEWPORT = 800


def media_ranges(viewport_names: list[str]) -> dict[str, tuple[int, int | None]]:
    """Split the width axis between the captured breakpoints (midpoints)."""
    vps = sorted(
        {n: settings.viewport(n).width for n in viewport_names if settings.viewport(n)}.items(),
        key=lambda kv: kv[1],
    )
    out: dict[str, tuple[int, int | None]] = {}
    for i, (name, width) in enumerate(vps):
        lo = 0 if i == 0 else (vps[i - 1][1] + width) // 2
        hi = None if i == len(vps) - 1 else (width + vps[i + 1][1]) // 2 - 1
        out[name] = (lo, hi)
    return out


_ROOT_OK = re.compile(r'^(body|\[id="[A-Za-z][\w-]*"\])$')


def _valid_path(path: str) -> bool:
    parts = path.split(">")
    return bool(_ROOT_OK.match(parts[0])) and all(_TAG_OK.match(p) for p in parts[1:])


def _visible(sig: list) -> bool:
    display, visibility, opacity, _t, w, h = sig
    try:
        op = float(opacity)
    except (TypeError, ValueError):
        op = 1.0
    return display != "none" and visibility != "hidden" and op > 0.01 and (w > 0 or h > 0)


def diff_signatures(original: dict, generated: dict) -> dict[str, dict[str, str]]:
    """Return ``{selector: {property: value}}`` restoring the original state."""
    fixes: dict[str, dict[str, str]] = {}
    for path, o in original.items():
        g = generated.get(path)
        if not g or len(o) < 6 or len(g) < 6 or not _valid_path(path):
            continue
        ov, gv = _visible(o), _visible(g)
        if not ov and not gv:
            continue
        props: dict[str, str] = {}
        if o[0] != g[0]:
            props["display"] = o[0]
        if o[1] != g[1]:
            props["visibility"] = o[1]
        try:
            if abs(float(o[2]) - float(g[2])) > 0.05:
                props["opacity"] = o[2]
        except (TypeError, ValueError):
            pass
        if o[3] != g[3] and ov:
            props["transform"] = o[3]
        if props:
            fixes[path] = props
        if len(fixes) >= _MAX_RULES_PER_VIEWPORT:
            break
    return fixes


def render_css(rules_by_vp: dict[str, dict[str, dict[str, str]]], ranges: dict) -> str:
    chunks = ["/* rx-fidelity: restores the original computed layout state */"]
    for vp, rules in rules_by_vp.items():
        if not rules:
            continue
        lo, hi = ranges.get(vp, (0, None))
        conds = []
        if lo:
            conds.append(f"(min-width: {lo}px)")
        if hi:
            conds.append(f"(max-width: {hi}px)")
        body = "\n".join(
            "  " + sel + "{" + ";".join(f"{k}:{v}!important" for k, v in props.items()) + "}"
            for sel, props in rules.items()
        )
        chunks.append(f"@media {' and '.join(conds)} {{\n{body}\n}}" if conds else body)
    return "\n".join(chunks)


def apply_fix_css(html_path: Path, css: str) -> None:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "lxml")
    for old in soup.find_all("style", id=_STYLE_ID):
        old.decompose()
    if css.strip() and soup.head:
        tag = soup.new_tag("style", id=_STYLE_ID)
        tag.string = css
        soup.head.append(tag)
    html_path.write_text(str(soup), encoding="utf-8")


class LayoutFixer:
    """Accumulates per-page, per-breakpoint overrides across fix cycles."""

    def __init__(self, viewport_names: list[str]) -> None:
        self.ranges = media_ranges(viewport_names)
        self.rules: dict[str, dict[str, dict[str, dict[str, str]]]] = {}

    def add(self, page_rel: str, viewport: str, original: dict, generated: dict) -> int:
        new = diff_signatures(original or {}, generated or {})
        bucket = self.rules.setdefault(page_rel, {}).setdefault(viewport, {})
        added = 0
        for sel, props in new.items():
            cur = bucket.setdefault(sel, {})
            for k, v in props.items():
                if cur.get(k) != v:
                    cur[k] = v
                    added += 1
        return added

    def count(self, page_rel: str) -> int:
        return sum(len(r) for r in self.rules.get(page_rel, {}).values())

    def write(self, root: Path, page_rel: str) -> None:
        rules = self.rules.get(page_rel)
        if not rules:
            return
        apply_fix_css(root / page_rel, render_css(rules, self.ranges))
