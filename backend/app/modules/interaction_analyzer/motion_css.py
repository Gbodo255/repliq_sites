"""Turn captured JS motion into plain CSS for the offline copy.

* :func:`animation_css` - Web Animations captured on the live page
  (see :mod:`app.modules.browser.motion`) become ``@keyframes`` bound to their
  ``[data-rx-a]`` element. ``load`` animations replay on page load; ``view``
  ones are held on their first frame until ``interactions.js`` marks the element
  ``rx-a-run`` when it scrolls into view; loops run forever. Everything is
  disabled under ``prefers-reduced-motion`` and when the copy is frozen for a
  quality screenshot (``html.rx-frozen``), so the static capture is shown.
* :func:`hover_css` - hover-state diffs become ``[data-rx-h]:hover`` rules
  (``!important``: the runtime left the resting state as inline styles).
"""
from __future__ import annotations

import re

_PROP_RE = re.compile(r"^(--[\w-]+|-?[a-z][a-z0-9-]*)$")
_BAD_VALUE = re.compile(r"[{}<>;]|/\*|\*/")
_PATH_RE = re.compile(r"^([a-z][a-z0-9-]*:nth-of-type\(\d+\)(>[a-z][a-z0-9-]*:nth-of-type\(\d+\))*)?$")
_EASE_RE = re.compile(r"^[a-z-]+(\([0-9a-zA-Z.,%\s+-]*\))?$")
_DIRECTIONS = {"normal", "reverse", "alternate", "alternate-reverse"}


def _ok_value(v) -> bool:
    s = str(v)
    return bool(s) and len(s) <= 400 and not _BAD_VALUE.search(s)


def _ease(e) -> str:
    s = str(e or "linear").strip()
    return s if len(s) <= 2000 and _EASE_RE.match(s) else "linear"


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _keyframes(name: str, frames: list) -> str:
    blocks = []
    for f in frames or []:
        try:
            off = float(f.get("o"))
        except (TypeError, ValueError):
            continue
        if not 0 <= off <= 1:
            continue
        decls = [f"{k}:{v}" for k, v in (f.get("p") or {}).items()
                 if _PROP_RE.match(str(k)) and _ok_value(v)]
        if not decls:
            continue
        ez = _ease(f.get("e"))
        if ez != "linear":
            decls.append(f"animation-timing-function:{ez}")
        pct = f"{round(off * 100, 3):g}%"
        blocks.append(f"{pct}{{{';'.join(decls)}}}")
    if not blocks:
        return ""
    return f"@keyframes {name}{{{''.join(blocks)}}}"


def animation_css(entries: list) -> str:
    """CSS for captured Web Animations (``analysis['anims']``)."""
    out: list[str] = []
    any_view = False
    for e in entries or []:
        i = _int(e.get("i"), -1)
        if i < 0:
            continue
        parts = []
        for j, a in enumerate((e.get("a") or [])[:6]):
            name = f"rxa{i}-{j}"
            kf = _keyframes(name, a.get("kf"))
            if not kf:
                continue
            d = max(1, min(_int(a.get("d")), 120000))
            dl = max(-120000, min(_int(a.get("dl")), 120000))
            it = _int(a.get("it"), 1)
            count = "infinite" if it < 0 else str(max(1, min(it, 1000)))
            direction = a.get("dir") if a.get("dir") in _DIRECTIONS else "normal"
            # Loops hold nothing; finite runs only pin their first frame during
            # the delay, then hand back to the captured static (= final) state.
            fill = "both" if it < 0 else "backwards"
            out.append(kf)
            parts.append(f"{name} {d}ms {_ease(a.get('ez'))} {dl}ms {count} {direction} {fill}")
        if parts:
            out.append(f'[data-rx-a="{i}"]{{animation:{",".join(parts)}}}')
            any_view = any_view or e.get("t") == "view"
    if not out:
        return ""
    if any_view:
        out.append("html.rx-a-ready [data-rx-a-view]:not(.rx-a-run){animation-play-state:paused}")
    out.append("html.rx-frozen [data-rx-a]{animation:none!important}")
    out.append("@media (prefers-reduced-motion:reduce){[data-rx-a]{animation:none!important}}")
    return "/* rx-motion: Web Animations captured from the live site */\n" + "\n".join(out)


def hover_css(entries: list) -> str:
    """CSS for captured hover states (``analysis['hover']``)."""
    rules: list[str] = []
    for e in entries or []:
        i = _int(e.get("i"), -1)
        if i < 0:
            continue
        base = f'[data-rx-h="{i}"]'
        for r in e.get("r") or []:
            path = str(r.get("p") or "")
            if not _PATH_RE.match(path):
                continue
            decls = [f"{k}:{v}!important" for k, v in (r.get("s") or {}).items()
                     if _PROP_RE.match(str(k)) and _ok_value(v)]
            if not decls:
                continue
            tail = f">{path}" if path else ""
            tr = str(r.get("tr") or "")
            m = re.match(r"^(\d+)ms (.+)$", tr)
            if m and _EASE_RE.match(m.group(2)):
                props = ",".join(k for k in (r.get("s") or {}) if _PROP_RE.match(str(k)))
                rules.append(f"{base}{tail}{{transition-property:{props};"
                             f"transition-duration:{m.group(1)}ms;"
                             f"transition-timing-function:{m.group(2)}}}")
            rules.append(f"{base}:hover{tail}{{{';'.join(decls)}}}")
    if not rules:
        return ""
    return ("/* rx-hover: hover states driven by the original JavaScript */\n"
            "@media (hover:hover){\n" + "\n".join(rules) + "\n}")


def _media(width_range) -> str:
    if not width_range:
        return ""
    lo, hi = width_range
    conds = []
    if lo:
        conds.append(f"(min-width:{int(lo)}px)")
    if hi:
        conds.append(f"(max-width:{int(hi)}px)")
    return " and ".join(conds)


def scroll_css(data: dict, width_range=None) -> str:
    """CSS for scroll-linked tracks (``analysis['scroll_anims']``).

    Native scroll timelines (``animation-timeline: scroll(root)`` over the
    captured scroll range) where supported; elsewhere the animation is paused
    and ``interactions.js`` scrubs it with a negative ``animation-delay``.
    Limited to the captured breakpoint's width range: at other widths the
    layout, and so the scroll distances, differ.
    """
    kfs: list[str] = []
    rules: list[str] = []
    native: list[str] = []
    for e in (data or {}).get("els") or []:
        i = _int(e.get("i"), -1)
        ys = e.get("y") or []
        props = e.get("p") or {}
        if i < 0 or len(ys) < 2:
            continue
        try:
            ys = [float(y) for y in ys]
        except (TypeError, ValueError):
            continue
        y0, y1 = ys[0], ys[-1]
        if y1 <= y0:
            continue
        frames = []
        for k, y in enumerate(ys):
            decls = [f"{prop}:{vals[k]}" for prop, vals in props.items()
                     if _PROP_RE.match(str(prop)) and k < len(vals) and _ok_value(vals[k])]
            if decls:
                frames.append(f"{round((y - y0) / (y1 - y0) * 100, 3):g}%{{{';'.join(decls)}}}")
        if len(frames) < 2:
            continue
        name = f"rxs{i}"
        kfs.append(f"@keyframes {name}{{{''.join(frames)}}}")
        sel = f'[data-rx-s="{i}"]'
        rules.append(f"{sel}{{animation:{name} 1s linear both paused}}")
        native.append(f"{sel}{{animation:{name} linear both;animation-timeline:scroll(root block);"
                      f"animation-range:{y0:g}px {y1:g}px}}")
    if not kfs:
        return ""
    body = "\n".join(rules) + "\n@supports (animation-timeline:scroll()){\n" + "\n".join(native) + "\n}"
    media = _media(width_range)
    if media:
        body = f"@media {media}{{\n{body}\n}}"
    return ("/* rx-scroll: scroll-linked animations captured from the live site */\n"
            + "\n".join(kfs) + "\n" + body
            + "\nhtml.rx-frozen [data-rx-s]{animation:none!important}"
            + "\n@media (prefers-reduced-motion:reduce){[data-rx-s]{animation:none!important}}")


def marquee_css(entries: list) -> str:
    """CSS loops for JS-driven marquees (``analysis['marquee']``)."""
    out = []
    for e in entries or []:
        i = _int(e.get("i"), -1)
        try:
            speed, length = float(e.get("speed")), float(e.get("len"))
        except (TypeError, ValueError):
            continue
        if i < 0 or not (speed > 0 and length > 0):
            continue
        fn = "translateY" if e.get("ax") == "y" else "translateX"
        a, b = (0, -length) if (e.get("dir") or -1) < 0 else (-length, 0)
        dur = max(0.5, min(length / speed, 600))
        out.append(f"@keyframes rxm{i}{{from{{transform:{fn}({a:g}px)}}to{{transform:{fn}({b:g}px)}}}}")
        out.append(f'[data-rx-marquee="{i}"]{{animation:rxm{i} {dur:.2f}s linear infinite}}')
    if not out:
        return ""
    return ("/* rx-marquee: JS-driven tickers captured from the live site */\n" + "\n".join(out)
            + "\nhtml.rx-frozen [data-rx-marquee]{animation:none!important}"
            + "\n@media (prefers-reduced-motion:reduce){[data-rx-marquee]{animation:none!important}}")


def motion_css(analysis: dict, width_range=None) -> str:
    parts = [animation_css(analysis.get("anims") or []),
             scroll_css(analysis.get("scroll_anims") or {}, width_range),
             marquee_css(analysis.get("marquee") or []),
             hover_css(analysis.get("hover") or [])]
    return "\n".join(p for p in parts if p)
