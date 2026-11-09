"""Which scripts the hybrid "keep animation JavaScript" mode keeps.

The default copy strips every script and replays the captured motion; ``keep_js``
keeps everything (framework runtimes included, which usually re-render or break
the static DOM). The hybrid mode (``keep_anim_js``) sits in between: it keeps

* recognised animation / interaction libraries (GSAP, Lenis, Lottie, Three.js,
  Swiper, AOS, jQuery plugins, Webflow IX...),
* the site's own classic scripts (same origin, not ES modules) - that is where
  the animation set-up code usually lives,
* inline scripts that drive one of those libraries,

and drops framework runtimes (Next, Nuxt, Framer, Remix, SvelteKit, Gatsby,
React/Vue bundles), hydration payloads and every other third-party script
(trackers, chat widgets, ads).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

FRAMEWORK_SRC = re.compile(
    r"(/_next/|/_nuxt/|framerusercontent\.com/sites/|framer\.com/(m|edit)/|/build/_shared/|"
    r"/_app/immutable/|/_astro/[^?]*client|gatsby|react-dom|react\.production|"
    r"vue(\.runtime)?(\.global)?(\.prod)?(\.min)?\.js|webpack-runtime|/static/js/(main|runtime)[.-]|"
    r"svelte|preact|hydrat|polyfills?[.-][0-9a-f]{6,})",
    re.I,
)
ANIM_LIB_SRC = re.compile(
    r"(gsap|scrolltrigger|scrollsmoother|splittext|lenis|locomotive|lottie|bodymovin|"
    r"\bthree(\.module)?(\.min)?\.js|/three@|rive|anime(\.es)?(\.min)?\.js|animejs|\baos(\.min)?\.js|"
    r"\bwow(\.min)?\.js|swiper|splide|glide|slick|owl\.carousel|flickity|splitting|split-?type|"
    r"barba|scrollmagic|parallax|rellax|typed(\.umd)?(\.min)?\.js|particles|vanta|matter(\.min)?\.js|"
    r"pixi|jquery|webflow|velocity|motion(\.min)?\.js|popmotion|tween)",
    re.I,
)
INLINE_FRAMEWORK = re.compile(
    r"(__NEXT_DATA__|self\.__next_f|__NUXT__|__remixContext|__sveltekit|__framer|"
    r"hydrateRoot|ReactDOM|__GATSBY|__APOLLO_STATE__)",
)
INLINE_ANIM = re.compile(
    r"\b(gsap|ScrollTrigger|ScrollSmoother|Lenis|LocomotiveScroll|lottie|bodymovin|THREE|anime|AOS|"
    r"WOW|Swiper|Splide|Glide|Flickity|Typed|Splitting|SplitType|barba|Webflow|jQuery|Rellax|"
    r"particlesJS|VANTA|rive)\b|\$\(\s*(document|window|function|['\"])",
)


def keep_anim_script(src: str | None, page_url: str, text: str = "", stype: str = "") -> bool:
    """True when the hybrid mode keeps this <script> (``src`` absolute)."""
    stype = (stype or "").lower()
    if stype and stype not in ("text/javascript", "application/javascript", "module"):
        return False                      # templates, JSON payloads, speculation rules...
    if src:
        if FRAMEWORK_SRC.search(src):
            return False
        if ANIM_LIB_SRC.search(src):
            return True
        same_site = urlparse(src).netloc.lower() == urlparse(page_url).netloc.lower()
        return same_site and stype != "module"
    if INLINE_FRAMEWORK.search(text or ""):
        return False
    return bool(INLINE_ANIM.search(text or ""))


def has_framework_runtime(html: str, page_url: str) -> bool:
    """Did the captured page run on a framework runtime (which the hybrid mode drops)?"""
    soup = BeautifulSoup(html, "lxml")
    for s in soup.find_all("script"):
        src = s.get("src")
        if src and FRAMEWORK_SRC.search(src):
            return True
        if not src and INLINE_FRAMEWORK.search(s.string or ""):
            return True
        if (s.get("type") or "").lower() == "module" and not (src and ANIM_LIB_SRC.search(src)):
            return True
    return False
