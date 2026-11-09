"""Playwright-based page renderer.

A single :class:`Renderer` owns one Chromium instance for the lifetime of a job
and renders pages in isolated browser contexts.  For every page it:

* loads the URL and waits for the network to settle,
* scrolls the full height to trigger lazy-loaded content,
* serialises the *rendered* DOM (``outerHTML`` after JS execution) so that
  React/Vue/Next/etc. sites are captured from what the browser actually shows,
* records every resource the page fetched (images, fonts, css, media) via the
  Performance API, which is the most reliable way to find lazy / srcset /
  background-image assets,
* captures full-page screenshots at each requested breakpoint, and
* runs a small in-page analysis script (palette, fonts, metrics).
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urldefrag, urljoin

from playwright.async_api import Browser, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.config import Viewport, settings
from app.core.logging import get_logger
from app.models.domain import RenderedPage
from app.modules.browser import motion as _motion
from app.modules.browser import players as _players

log = get_logger("renderer")

# JS run in-page to collect links, stylesheet hrefs, loaded resources + analysis.
_COLLECT_JS = r"""
() => {
  const abs = (u) => { try { return new URL(u, document.baseURI).href; } catch(e){ return null; } };
  const links = [...document.querySelectorAll('a[href]')]
    .map(a => abs(a.getAttribute('href'))).filter(Boolean);
  const sheets = [...document.querySelectorAll('link[rel~="stylesheet"][href]')]
    .map(l => abs(l.getAttribute('href'))).filter(Boolean);
  let resources = [];
  try {
    resources = performance.getEntriesByType('resource').map(e => e.name).filter(Boolean);
  } catch(e) {}
  // Small visual analysis sample.
  const colorCount = {}, fontCount = {};
  const sample = document.querySelectorAll('body *');
  const cap = Math.min(sample.length, 3000);
  for (let i = 0; i < cap; i++) {
    const cs = getComputedStyle(sample[i]);
    for (const prop of ['color','background-color','border-top-color']) {
      const c = cs.getPropertyValue(prop);
      if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent')
        colorCount[c] = (colorCount[c]||0)+1;
    }
    const ff = cs.getPropertyValue('font-family');
    if (ff) fontCount[ff] = (fontCount[ff]||0)+1;
  }
  const top = (obj, n) => Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,n).map(x=>x[0]);
  return {
    links, sheets, resources,
    title: document.title || '',
    lang: document.documentElement.lang || '',
    analysis: {
      palette: top(colorCount, 12),
      fonts: top(fontCount, 8),
      scrollHeight: document.body ? document.body.scrollHeight : 0,
      nodeCount: document.querySelectorAll('*').length,
    }
  };
}
"""

_AUTOSCROLL_JS = r"""
async () => {
  await new Promise((resolve) => {
    let total = 0;
    const step = Math.max(300, Math.floor(window.innerHeight * 0.85));
    const timer = setInterval(() => {
      const before = document.body ? document.body.scrollHeight : 0;
      window.scrollBy(0, step);
      total += step;
      if (total >= (document.body ? document.body.scrollHeight : 0) || total > 40000) {
        clearInterval(timer);
        window.scrollTo(0, 0);
        resolve();
      }
    }, 120);
  });
}
"""


# Third-party trackers, ads, chat widgets and consent-management platforms.
# Blocking them makes rendering faster, keeps cookie banners out of the copy and
# removes noise from the visual comparison. They never carry site content.
_BLOCK_RE = re.compile(
    r"^https?://([^/]*\.)?("
    r"google-analytics\.com|googletagmanager\.com|googleadservices\.com|doubleclick\.net|"
    r"googlesyndication\.com|adservice\.google\.[a-z.]+|connect\.facebook\.net|facebook\.com/tr|"
    r"hotjar\.(com|io)|clarity\.ms|segment\.(com|io)|mixpanel\.com|amplitude\.com|"
    r"fullstory\.com|mouseflow\.com|crazyegg\.com|matomo\.cloud|plausible\.io|"
    r"bat\.bing\.com|snap\.licdn\.com|ads\.linkedin\.com|analytics\.tiktok\.com|"
    r"static\.ads-twitter\.com|criteo\.(com|net)|taboola\.com|outbrain\.com|"
    r"cookiebot\.com|cookielaw\.org|onetrust\.com|"
    r"axept\.io|didomi\.io|privacy-center\.org|usercentrics\.eu|iubenda\.com|"
    r"quantcast\.com|consensu\.org|trustarc\.com|termly\.io|"
    r"intercom\.io|intercomcdn\.com|crisp\.chat|tawk\.to|zopim\.com"
    r")",
    re.I,
)

# Freezes animations/transitions at their end state so screenshots (original
# and generated) are deterministic. Only used for capture, never written out.
_FREEZE_CSS = (
    "*,*::before,*::after{transition:none!important;animation-duration:0s!important;"
    "animation-delay:0s!important;animation-iteration-count:1!important;"
    "caret-color:transparent!important;scroll-behavior:auto!important}"
)

# Prepares the live DOM for a faithful serialisation:
#  * CSS-in-JS rules injected through insertRule (empty <style> text) are
#    written back as text, adoptedStyleSheets are materialised,
#  * form state (value/checked/selected) is reflected into attributes,
#  * lazy <img> placeholders are replaced by the image actually displayed,
#  * iframes and canvases are tagged so they can be snapshotted as images,
#  * anti-flicker classes left by blocked tag managers are removed.
_PREPARE_JS = r"""
() => {
  const out = { snaps: [] };
  for (const st of document.querySelectorAll('style')) {
    try {
      const sh = st.sheet;
      if (sh && sh.cssRules && sh.cssRules.length && !(st.textContent || '').trim()) {
        st.textContent = [...sh.cssRules].map(r => r.cssText).join('\n');
      }
    } catch (e) {}
  }
  try {
    const adopted = document.adoptedStyleSheets || [];
    for (const sh of adopted) {
      const s = document.createElement('style');
      s.setAttribute('data-rx-adopted', '');
      s.textContent = [...sh.cssRules].map(r => r.cssText).join('\n');
      document.head.appendChild(s);
    }
  } catch (e) {}
  for (const el of document.querySelectorAll('input, textarea, select')) {
    try {
      if (el.tagName === 'INPUT') {
        const t = (el.type || '').toLowerCase();
        if (t === 'checkbox' || t === 'radio') { el.checked ? el.setAttribute('checked', '') : el.removeAttribute('checked'); }
        else if (t !== 'password' && t !== 'file' && el.value) el.setAttribute('value', el.value);
      } else if (el.tagName === 'TEXTAREA') { el.textContent = el.value; }
      else { for (const o of el.options) { o.selected ? o.setAttribute('selected', '') : o.removeAttribute('selected'); } }
    } catch (e) {}
  }
  for (const img of document.querySelectorAll('img')) {
    const src = img.getAttribute('src') || '';
    if (img.currentSrc && (!src || src.startsWith('data:'))) img.setAttribute('src', img.currentSrc);
  }
  let n = 0;
  const MAX_SNAPS = (window.__rxMaxSnaps || 24);
  for (const el of document.querySelectorAll('iframe, canvas')) {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || n >= MAX_SNAPS) continue;
    el.setAttribute('data-rx-snap', String(n));
    out.snaps.push({ id: String(n), w: Math.round(r.width), h: Math.round(r.height), tag: el.tagName.toLowerCase() });
    n++;
  }
  // Web-component popups: a menu/dropdown slotted into a custom element's
  // shadow DOM is hidden on the live page by the component's own CSS/JS. In the
  // static copy that JS is stripped and the element is never upgraded, so the
  // slotted content would render open. Mark the ones that are collapsed NOW
  // (ground truth from the live page) so the copy keeps them hidden. Scoped to
  // web-component content only, so standard responsive menus are untouched.
  try {
    const inCustom = (el) => {
      for (let p = el; p; p = p.parentElement) {
        const t = p.tagName || '';
        if (t.indexOf('-') > 0 && t.indexOf('RX-') !== 0) return true;
      }
      return false;
    };
    const notVisible = (el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return cs.display === 'none' || cs.visibility === 'hidden'
        || parseFloat(cs.opacity) < 0.05 || r.width < 2 || r.height < 2;
    };
    const marks = new Set();
    const state = {};
    for (const c of document.querySelectorAll('[aria-controls][aria-expanded]')) {
      const exp = c.getAttribute('aria-expanded') === 'true';
      for (const id of (c.getAttribute('aria-controls') || '').split(/\s+/)) {
        if (!id) continue;
        if (exp) state[id] = true; else if (!(id in state)) state[id] = false;
      }
    }
    for (const id in state) {
      if (state[id]) continue;
      let e = null; try { e = document.getElementById(id); } catch (x) {}
      if (e) marks.add(e);
    }
    for (const e of document.querySelectorAll('[slot]')) marks.add(e);
    for (const el of marks) {
      if (el.hasAttribute('data-rx-collapsed') || el.hasAttribute('data-rx-reveal-i')) continue;
      if (inCustom(el) && notVisible(el)) el.setAttribute('data-rx-collapsed', '');
    }
    // Component content rendered INSIDE a shadow root is out of reach of a
    // document stylesheet, so freeze the live hidden state of its menu-like
    // elements as an inline !important style (serialised with the declarative
    // shadow DOM). Scoped to menu/dropdown/option-ish names to avoid touching
    // unrelated shadow internals.
    const MENU = /(menu|dropdown|panel|popover|popup|flyout|submenu|listbox|option|disclosure|collapse|accordion|drawer)/i;
    const roots = [];
    const collect = (r) => { for (const el of r.querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot); };
    collect(document);
    for (let i = 0; i < roots.length; i++) collect(roots[i]);
    for (const root of roots) {
      for (const el of root.querySelectorAll('*')) {
        try {
          if (el.hasAttribute('data-rx-reveal-i') || el.style.display) continue;
          const sig = (el.getAttribute('class') || '') + ' ' + (el.getAttribute('role') || '');
          if (!MENU.test(sig)) continue;
          if (el.getClientRects().length === 0 || getComputedStyle(el).display === 'none')
            el.style.setProperty('display', 'none', 'important');
        } catch (e) {}
      }
    }
  } catch (e) {}
  document.documentElement.classList.remove('async-hide');
  return out;
}
"""

# Reads a snapshotted canvas's pixels (see Renderer._canvas_pixels).
_CANVAS_PIXELS_JS = r"""
(sid) => {
  const c = document.querySelector('[data-rx-snap="' + sid + '"]');
  if (!c || c.tagName !== 'CANVAS' || !c.width || !c.height) return { mode: 'shot' };
  let gl = null, ctx = null;
  try { gl = c.getContext('webgl2') || c.getContext('webgl'); } catch (e) {}
  if (!gl) { try { ctx = c.getContext('2d'); } catch (e) {} }
  try {
    const attrs = (gl || ctx) && (gl || ctx).getContextAttributes ? (gl || ctx).getContextAttributes() : null;
    if (attrs && attrs.alpha === false) return { mode: 'shot' };     // opaque: screenshot is exact
  } catch (e) {}
  let url = '';
  try { url = c.toDataURL('image/png'); } catch (e) { return { mode: 'shot' }; }   // tainted
  let blank = true;
  try {
    const t = document.createElement('canvas');
    t.width = 48; t.height = 48;
    const tc = t.getContext('2d');
    tc.drawImage(c, 0, 0, 48, 48);
    const px = tc.getImageData(0, 0, 48, 48).data;
    for (let i = 3; i < px.length; i += 4) if (px[i] > 8) { blank = false; break; }
  } catch (e) { blank = false; }
  if (blank) {
    // A blank WebGL buffer (no preserveDrawingBuffer): an embedded 3D scene is
    // better as a screenshot, a full-screen transparent effect is dropped.
    const r = c.getBoundingClientRect();
    const big = r.width * r.height > 0.5 * innerWidth * innerHeight;
    return { mode: (gl && !big) ? 'shot' : 'drop' };
  }
  return { mode: 'data', url: url };
}
"""

# Serialises the DOM, including open shadow roots as declarative shadow DOM.
_SERIALIZE_JS = r"""
() => {
  const de = document.documentElement;
  const roots = [];
  for (const el of document.querySelectorAll('*')) { if (el.shadowRoot) roots.push(el.shadowRoot); }
  if (roots.length && de.getHTML) {
    try {
      const attrs = [...de.attributes].map(a => ' ' + a.name + '="' + a.value.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"').join('');
      return '<html' + attrs + '>' + de.getHTML({ serializableShadowRoots: true, shadowRoots: roots }) + '</html>';
    } catch (e) {}
  }
  return de.outerHTML;
}
"""

# Serialises just the <body> (open shadow roots included). Used to capture a
# breakpoint-specific DOM variant for frameworks (Framer, and any JS runtime)
# that *re-render* a different DOM per breakpoint instead of reflowing one DOM
# with CSS media queries. The serialised <body> of the smaller breakpoints is
# injected into the offline copy and shown/hidden by width, so the copy matches
# the live site at every viewport (not just the one captured at primary width).
_SERIALIZE_BODY_JS = r"""
() => {
  const b = document.body;
  if (!b) return "";
  const roots = [];
  for (const el of b.querySelectorAll('*')) { if (el.shadowRoot) roots.push(el.shadowRoot); }
  if (roots.length && b.getHTML) {
    try {
      const attrs = [...b.attributes].map(a => ' ' + a.name + '="' + a.value.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"').join('');
      return '<body' + attrs + '>' + b.getHTML({ serializableShadowRoots: true, shadowRoots: roots }) + '</body>';
    } catch (e) {}
  }
  return b.outerHTML;
}
"""

# Light prepare run before a variant <body> serialisation: pin the image the
# current breakpoint actually displays and reflect form state, mirroring the
# relevant parts of _PREPARE_JS (which ran once at primary width).
_PREPARE_VARIANT_JS = r"""
() => {
  for (const img of document.querySelectorAll('img')) {
    const src = img.getAttribute('src') || '';
    if (img.currentSrc && (!src || src.startsWith('data:'))) img.setAttribute('src', img.currentSrc);
  }
  for (const el of document.querySelectorAll('input, textarea, select')) {
    try {
      if (el.tagName === 'INPUT') {
        const t = (el.type || '').toLowerCase();
        if (t === 'checkbox' || t === 'radio') { el.checked ? el.setAttribute('checked', '') : el.removeAttribute('checked'); }
        else if (t !== 'password' && t !== 'file' && el.value) el.setAttribute('value', el.value);
      } else if (el.tagName === 'TEXTAREA') { el.textContent = el.value; }
    } catch (e) {}
  }
}
"""

# Bake the live layout of a breakpoint variant before serialising it.
#
# Frameworks like Framer keep several breakpoint layouts in one DOM and let their
# RUNTIME pick/scale the one that fits: a component authored at a fixed desktop
# width (e.g. 2888px) is fitted into a phone viewport with a runtime
# ``transform: scale(...)`` on a wrapper whose box is sized to the *scaled*
# result. None of that is in the serialised HTML, so once the runtime is stripped
# the wide layout renders at full width and ``aspect-ratio`` boxes explode the
# page height. The live computed layout is the ground truth, so pin the used
# width/height and any transform for the elements that carry runtime layout, as
# inline styles the static copy keeps. Scoped to boxes that actually diverge
# (transformed, or wider than the viewport, or holding such a child) to bound the
# HTML growth; text-level spans and svg internals are left untouched.
_BAKE_VARIANT_JS = r"""
() => {
  const body = document.body;
  if (!body) return 0;
  const vw = window.innerWidth || 0;
  const SKIP = { SCRIPT:1, STYLE:1, LINK:1, META:1, NOSCRIPT:1, TEMPLATE:1, BR:1, svg:1 };
  const els = body.querySelectorAll('*');
  const cap = Math.min(els.length, 8000);
  // First pass: flag elements whose live box carries runtime layout - a
  // transform (Framer scales fixed-width breakpoint content to fit) or a used
  // width wider than the viewport (a fixed-width component the runtime clips
  // inside a smaller box). ``getComputedStyle`` is read pre-transform, so the
  // used width of a scaled component is still its authored width.
  const flag = new Set();
  for (let i = 0; i < cap; i++) {
    const el = els[i];
    if (SKIP[el.tagName]) continue;
    if (el.tagName !== 'svg' && el.closest && el.closest('svg')) continue;
    const cs = getComputedStyle(el);
    const transformed = cs.transform && cs.transform !== 'none';
    const wide = parseFloat(cs.width) > vw + 4;
    if (transformed || wide) {
      flag.add(el);
      // its ancestors hold the (often smaller, clipped) box it sits in, so pin
      // them too: that is what keeps the page from ballooning offline.
      for (let p = el.parentElement; p && p !== body; p = p.parentElement) {
        if (SKIP[p.tagName]) continue;
        flag.add(p);
      }
    }
  }
  let n = 0;
  for (const el of flag) {
    try {
      const cs = getComputedStyle(el);
      // Used (pre-transform) box size + the element's own transform. Baking each
      // element's own size and transform reproduces the live cascade exactly,
      // with no double-counting of ancestor transforms.
      const w = parseFloat(cs.width), h = parseFloat(cs.height);
      if (!isNaN(w) && w >= 1) el.style.setProperty('width', Math.round(w * 100) / 100 + 'px');
      if (!isNaN(h) && h >= 1) el.style.setProperty('height', Math.round(h * 100) / 100 + 'px');
      if (cs.transform && cs.transform !== 'none') {
        el.style.setProperty('transform', cs.transform);
        el.style.setProperty('transform-origin', cs.transformOrigin);
      }
      n++;
    } catch (e) {}
  }
  return n;
}
"""

# Structural path of an element, anchored on the nearest unique id.
_PATH_FN = r"""
  const body = document.body;
  const idCount = {};
  for (const e of document.querySelectorAll('[id]')) idCount[e.id] = (idCount[e.id] || 0) + 1;
  const anchor = (e) => e.id && idCount[e.id] === 1 && /^[A-Za-z][\w-]*$/.test(e.id);
  const pathOf = (el) => {
    const parts = [];
    while (el && el !== body) {
      if (anchor(el)) return ['[id="' + el.id + '"]'].concat(parts).join('>');
      let i = 1, s = el;
      while ((s = s.previousElementSibling)) if (s.tagName === el.tagName) i++;
      parts.unshift(el.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      el = el.parentElement;
    }
    return el === body ? 'body>' + parts.join('>') : null;
  };
"""

# Inline styles of every element (JS often writes viewport-dependent heights,
# widths or positions as inline styles).
STYLES_JS = "() => {" + _PATH_FN + r"""
  const out = {};
  if (!body) return out;
  let n = 0;
  for (const el of body.querySelectorAll('[style]')) {
    if (n++ > 5000) break;
    if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') continue;
    const p = pathOf(el);
    if (p) out[p] = el.getAttribute('style') || '';
  }
  return out;
}"""

# Given the inline styles serialised in the HTML (``base``), return for this
# viewport the declarations that differ, with the value to restore (the inline
# value, or the computed value when the inline declaration does not exist here).
STYLE_DIFF_JS = "(base) => {" + _PATH_FN + r"""
  const out = {};
  if (!body) return out;
  const SKIP = /^(transition|animation|will-change|transform|opacity|translate|rotate|scale)/;
  const parse = (s) => { const t = document.createElement('div'); t.setAttribute('style', s || ''); const o = {}; for (let i = 0; i < t.style.length; i++) { const k = t.style[i]; o[k] = t.style.getPropertyValue(k); } return o; };
  const current = {};
  let n = 0;
  for (const el of body.querySelectorAll('[style]')) {
    if (n++ > 5000) break;
    const p = pathOf(el);
    if (p) current[p] = el;
  }
  const paths = new Set(Object.keys(base).concat(Object.keys(current)));
  for (const p of paths) {
    let el = current[p];
    if (!el) { try { el = document.querySelector(p); } catch (e) { el = null; } }
    if (!el) continue;
    const now = el.getAttribute('style') || '';
    if (now === (base[p] || '')) continue;
    const a = parse(base[p]), b = parse(now);
    const props = new Set(Object.keys(a).concat(Object.keys(b)));
    const cs = getComputedStyle(el);
    const diff = {};
    for (const k of props) {
      if (SKIP.test(k) || k.startsWith('--')) continue;
      if (a[k] === b[k]) continue;
      diff[k] = (k in b) ? b[k] : cs.getPropertyValue(k);
    }
    if (Object.keys(diff).length) out[p] = diff;
  }
  return out;
}"""

# Per-element visibility/layout signature used by the layout auto-fixer.
# Keys are structural CSS paths (nth-of-type chains) that survive the rebuild.
SIGNATURE_JS = "() => {" + _PATH_FN + r"""
  const out = {};
  if (!body) return out;
  const skip = new Set(['script', 'style', 'link', 'meta', 'noscript', 'template', 'br']);
  let count = 0;
  for (const el of body.querySelectorAll('*')) {
    if (count > 4000) break;
    const tag = el.tagName.toLowerCase();
    if (skip.has(tag)) continue;
    if (tag !== 'svg' && el.closest('svg')) continue;
    if (el.hasAttribute('data-rx-ignore')) continue;
    const p = pathOf(el);
    if (!p) continue;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    out[p] = [cs.display, cs.visibility, cs.opacity, cs.transform, Math.round(r.width), Math.round(r.height)];
    count++;
  }
  return out;
}"""


# --- Motion capture (scroll-reveal animations) -------------------------------
# Captured in two passes in the SAME page context (so live element references
# survive on ``window.__rxM0`` between the two ``evaluate`` calls):
#
#   _MOTION_BEFORE_JS : before any scroll, remember every element that is in a
#       "pre-animation" resting state (hidden-ish: opacity<0.95, a transform, or
#       visibility:hidden) together with its transition properties.
#   _MOTION_AFTER_JS  : after the full auto-scroll (which fires the site's own
#       scroll-reveal logic, whatever the library), see which of those elements
#       became visible. Those are genuine scroll reveals; tag each one with
#       ``data-rx-reveal-i`` and return a compact table so interactions.js can
#       replay the exact entrance (initial state -> revealed state + transition)
#       on the offline copy. Detection is by *effect*, so it is library-agnostic
#       (AOS, WOW, GSAP/ScrollTrigger, Framer whileInView, custom IO, ...).
_MOTION_BEFORE_JS = r"""
() => {
  const body = document.body;
  if (!body) { window.__rxM0 = []; return 0; }
  const arr = [];
  const els = body.querySelectorAll('*');
  const cap = Math.min(els.length, 6000);
  for (let i = 0; i < cap; i++) {
    const el = els[i];
    const tag = el.tagName.toLowerCase();
    if (tag==='script'||tag==='style'||tag==='link'||tag==='meta'||tag==='noscript'||tag==='template'||tag==='br') continue;
    if (tag !== 'svg' && el.closest('svg')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    const op = parseFloat(cs.opacity);
    const tf = cs.transform;
    const vis = cs.visibility;
    const hidden = (op < 0.95) || (tf && tf !== 'none') || vis === 'hidden';
    if (!hidden) continue;
    // A looping animation (spinner, marquee) is not an entrance: leave it to
    // the Web Animations capture.
    try {
      if (el.getAnimations().some(an => { try { return an.effect.getTiming().iterations === Infinity; } catch (e) { return false; } })) continue;
    } catch (e) {}
    arr.push({ el: el, o0: op, t0: tf, v0: vis,
               tp: cs.transitionProperty, td: cs.transitionDuration,
               te: cs.transitionTimingFunction, tdl: cs.transitionDelay });
    if (arr.length >= 1500) break;
  }
  window.__rxM0 = arr;
  return arr.length;
}
"""

_MOTION_AFTER_JS = r"""
() => {
  const arr = window.__rxM0 || [];
  const table = [];
  let i = 0;
  for (const rec of arr) {
    const el = rec.el;
    if (!el || !el.isConnected) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const op1 = parseFloat(cs.opacity);
    const tf1 = cs.transform;
    const vis1 = cs.visibility;
    const revealed =
      (rec.o0 < 0.95 && op1 >= 0.95) ||
      (rec.v0 === 'hidden' && vis1 !== 'hidden') ||
      (rec.t0 && rec.t0 !== 'none' && tf1 !== rec.t0);
    if (!revealed) continue;
    // Build a clean single transition. Computed transition-* are comma-joined
    // lists aligned by index; durations/delays are safe to split on commas, but
    // a timing function can itself contain commas (cubic-bezier/steps), so only
    // reuse it when it is a simple keyword.
    let trans = '';
    if (rec.tp && /opacity|transform|all/.test(rec.tp)) {
      const durs = (rec.td || '').split(',').map(s => parseFloat(s)).filter(v => !isNaN(v));
      const maxd = durs.length ? Math.max.apply(null, durs) : 0;
      if (maxd > 0) {
        let ease = 'cubic-bezier(.22,.61,.36,1)';
        const te = (rec.te || '').trim();
        if (te && te.indexOf(',') === -1 && te.indexOf('(') === -1) ease = te;
        let delay = '0s';
        const dl = (rec.tdl || '').trim();
        if (dl && dl.indexOf(',') === -1) delay = dl;
        const d = maxd + 's';
        trans = 'opacity ' + d + ' ' + ease + ' ' + delay + ', transform ' + d + ' ' + ease + ' ' + delay;
      }
    }
    if (!trans) trans = 'opacity .7s cubic-bezier(.22,.61,.36,1), transform .7s cubic-bezier(.22,.61,.36,1)';
    const o0 = (rec.o0 < 0.95) ? +rec.o0.toFixed(3) : (rec.v0 === 'hidden' ? 0 : null);
    const t0 = (rec.t0 && rec.t0 !== 'none') ? rec.t0 : null;
    if (o0 === null && t0 === null) continue;
    const o1 = (op1 < 0.999) ? +op1.toFixed(3) : null;
    const t1 = (tf1 && tf1 !== 'none') ? tf1 : null;
    el.setAttribute('data-rx-reveal-i', String(i));
    table.push([o0, t0, o1, t1, trans]);
    i++;
    if (i >= 400) break;
  }
  try { delete window.__rxM0; } catch (e) { window.__rxM0 = null; }
  return { table: table };
}
"""

# Classes the original JavaScript toggles on scroll (sticky/shrinking headers,
# "scrolled" nav, reveal-on-scroll back-to-top). Sampled at rest and scrolled,
# returning the added classes so interactions.js can toggle them past a
# threshold. Only *added* classes are reported, so the site's own CSS styles the
# state; nothing is invented.
_SCROLL_STATE_JS = "async () => {" + _PATH_FN + r"""
  const read = () => {
    const h = document.documentElement.className || '';
    const b = body ? (body.className || '') : '';
    const header = document.querySelector(
      'header, [role="banner"], .header, .site-header, #header, .navbar, .nav-bar, nav.fixed, nav.sticky');
    let hp = null, hc = '';
    if (header && header !== body) { hp = pathOf(header); hc = header.className || ''; }
    return { h, b, hp, hc };
  };
  const at = async (y, wait) => { window.scrollTo(0, y); await new Promise(r => setTimeout(r, wait)); return read(); };
  const a = await at(0, 120);
  const s = await at(Math.max(600, Math.round(window.innerHeight * 0.9)), 260);
  await at(0, 80);
  const added = (from, to) => {
    const f = new Set((from || '').split(/\s+/).filter(Boolean));
    return (to || '').split(/\s+/).filter(Boolean).filter(c => !f.has(c));
  };
  const rows = [];
  const ah = added(a.h, s.h); if (ah.length) rows.push(['html', ah]);
  const ab = added(a.b, s.b); if (ab.length) rows.push(['body', ab]);
  if (a.hp && a.hp === s.hp) { const ac = added(a.hc, s.hc); if (ac.length) rows.push([a.hp, ac]); }
  return { rows: rows, threshold: 60 };
}"""


_LOW_MEM_MAX_SHOT_H = 6000   # px; reference and generated shots use the same cap
_MAX_SHOT_H = 30000          # px; height cap for full-tier shots (very tall pages)


# Make web fonts faithful at capture time: a font declared with
# ``font-display: optional`` (or ``fallback``) is dropped for the page's
# lifetime if it is not ready within ~100 ms of first layout, which happens
# routinely over the network - so the live capture keeps the system fallback
# while the offline copy (fonts on disk) uses the real font, and they diverge.
# Relax font-display, force every declared face to download, then reflow.
_FONT_FIX_JS = r"""async () => {
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }   // cross-origin
    if (!rules) continue;
    for (const rule of rules) {
      try {
        if (rule.type === 5 /* CSSFontFaceRule */) {
          const d = rule.style.getPropertyValue('font-display');
          if (d === 'optional' || d === 'fallback' || d === '')
            rule.style.setProperty('font-display', 'swap');
        }
      } catch (e) {}
    }
  }
  try {
    await Promise.all([...document.fonts].map(
      f => f.status === 'loaded' ? 1 : f.load().catch(() => {})));
  } catch (e) {}
  // Force a style/layout recalc so the now-loaded fonts are applied.
  document.documentElement.style.setProperty('--rx-reflow', String(Date.now()));
  void document.documentElement.offsetHeight;
}"""


# --- Design extraction (for the Figma export) --------------------------------
# Walks the fully rendered local copy and emits a NESTED tree of design nodes
# that mirrors the DOM container structure, with real geometry + computed styles:
#   FRAME : a container (fill/border/radius/shadow), with auto-layout parameters
#           when it is a flexbox (direction, gap, padding, alignment).
#   TEXT  : a text block (font, size, weight, colour, alignment).
#   IMG   : an <img>/background image or an <svg> (vector).
# Coordinates are RELATIVE to the parent. Pure wrappers (no paint, no layout,
# one child) are collapsed, and each FRAME carries a structural signature so the
# plugin can turn repeated siblings (cards, nav items) into components + instances.
_DESIGN_JS = r"""
() => {
  const toRGBA = (s) => {
    if (!s) return null;
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return [p[0] / 255, p[1] / 255, p[2] / 255, (p.length > 3 ? p[3] : 1)];
  };
  const parseShadow = (s) => {
    if (!s || s === 'none' || s.indexOf('inset') >= 0) return null;
    const cm = s.match(/rgba?\([^)]+\)/);
    const color = cm ? toRGBA(cm[0]) : [0, 0, 0, 0.25];
    const nums = ((cm ? s.replace(cm[0], '') : s).match(/-?\d*\.?\d+px/g) || []).map(x => parseFloat(x));
    if (nums.length < 2) return null;
    return { x: nums[0] || 0, y: nums[1] || 0, blur: nums[2] || 0, spread: nums[3] || 0, color };
  };
  const abs = (u) => { try { return new URL(u, document.baseURI).href; } catch (e) { return null; } };
  const px = (v) => { const n = parseFloat(v); return isNaN(n) ? 0 : n; };
  const INLINE = { A:1,SPAN:1,STRONG:1,EM:1,B:1,I:1,U:1,SMALL:1,LABEL:1,CODE:1,MARK:1,SUB:1,SUP:1,BR:1,ABBR:1,CITE:1,Q:1,S:1,TIME:1,WBR:1,DEL:1,INS:1,BDI:1,BDO:1,DFN:1,KBD:1,SAMP:1,VAR:1 };
  const SKIP = { SCRIPT:1,STYLE:1,LINK:1,META:1,NOSCRIPT:1,TEMPLATE:1,HEAD:1 };
  const mapJ = (j) => ({ 'flex-start':'MIN','center':'CENTER','flex-end':'MAX','space-between':'SPACE_BETWEEN','space-around':'SPACE_BETWEEN','space-evenly':'SPACE_BETWEEN' }[j] || 'MIN');
  const mapA = (a) => ({ 'flex-start':'MIN','center':'CENTER','flex-end':'MAX','stretch':'MIN','baseline':'BASELINE','normal':'MIN' }[a] || 'MIN');
  const pageW = document.documentElement.clientWidth;
  const pageH = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
  let budget = 1500;

  const styleFrame = (cs, node) => {
    const bg = toRGBA(cs.backgroundColor);
    if (bg && bg[3] > 0.01) node.fill = bg;
    const bw = px(cs.borderTopWidth), bc = toRGBA(cs.borderTopColor);
    if (bw > 0.4 && bc && bc[3] > 0.01) { node.borderColor = bc; node.borderW = bw; }
    const sh = parseShadow(cs.boxShadow); if (sh) node.shadow = sh;
    const rad = px(cs.borderTopLeftRadius); if (rad) node.radius = rad;
    if (cs.overflow === 'hidden' || cs.overflow === 'clip') node.clip = true;
  };
  const autoLayout = (cs, node) => {
    if (cs.display !== 'flex' && cs.display !== 'inline-flex') return;
    const col = (cs.flexDirection || '').indexOf('column') === 0;
    node.layout = col ? 'VERTICAL' : 'HORIZONTAL';
    node.gap = col ? px(cs.rowGap) : px(cs.columnGap);
    node.pad = [px(cs.paddingTop), px(cs.paddingRight), px(cs.paddingBottom), px(cs.paddingLeft)];
    node.primary = mapJ(cs.justifyContent);
    node.counter = mapA(cs.alignItems);
    if (cs.flexWrap === 'wrap') node.wrap = true;
  };
  const isTextBlock = (el) => {
    let hasText = false;
    for (const n of el.childNodes) {
      if (n.nodeType === 3) { if (n.nodeValue.trim()) hasText = true; }
      else if (n.nodeType === 1) {
        if (INLINE[n.tagName]) continue;
        const d = getComputedStyle(n).display;
        if (d.indexOf('inline') === 0 || d === 'contents') continue;
        return false;
      }
    }
    return hasText;
  };

  const build = (el, pl, pt) => {
    if (budget-- < 0 || SKIP[el.tagName]) return null;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return null;
    const op = parseFloat(cs.opacity); if (op < 0.02) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    if (r.top > pageH + 400 || (r.top + r.height) < -400 || r.left > pageW + 400 || (r.left + r.width) < -400) return null;
    const node = { x: Math.round((r.left - pl) * 10) / 10, y: Math.round((r.top - pt) * 10) / 10,
                   w: Math.round(r.width), h: Math.round(r.height) };
    if (op < 1) node.opacity = op;
    const tag = el.tagName.toLowerCase();

    if (tag === 'img' && (el.currentSrc || el.getAttribute('src'))) {
      node.t = 'IMG'; node.src = el.currentSrc || abs(el.getAttribute('src'));
      const rad = px(cs.borderTopLeftRadius); if (rad) node.radius = rad;
      return node;
    }
    if (tag === 'svg') {
      try { node.t = 'IMG'; node.svg = new XMLSerializer().serializeToString(el); return node; } catch (e) { return null; }
    }
    if (isTextBlock(el)) {
      let txt = (el.innerText || el.textContent || '').replace(/ /g, ' ').trim();
      if (!txt) return null;
      if (txt.length > 2000) txt = txt.slice(0, 2000);
      const lh = cs.lineHeight;
      node.t = 'TEXT'; node.text = txt;
      node.font = (cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim();
      node.size = px(cs.fontSize) || 16; node.weight = parseInt(cs.fontWeight) || 400;
      node.color = toRGBA(cs.color) || [0, 0, 0, 1]; node.align = cs.textAlign;
      if (lh && lh.endsWith('px')) node.lh = px(lh);
      if (cs.letterSpacing && cs.letterSpacing.endsWith('px')) node.ls = px(cs.letterSpacing);
      return node;
    }
    node.t = 'FRAME'; node.children = [];
    styleFrame(cs, node);
    autoLayout(cs, node);
    const bgi = cs.backgroundImage;
    if (bgi && bgi.indexOf('url(') === 0) {
      const mu = bgi.match(/url\(["']?([^"')]+)["']?\)/);
      if (mu) node.children.push({ t: 'IMG', x: 0, y: 0, w: node.w, h: node.h, src: abs(mu[1]), fit: 'cover', radius: node.radius || 0 });
    }
    for (const kid of el.children) { const c = build(kid, r.left, r.top); if (c) node.children.push(c); }
    const painted = node.fill || node.borderColor || node.shadow;
    if (!node.children.length && !painted) return null;
    // Collapse a pure wrapper (no paint, no layout, one child) into its child.
    if (node.children.length === 1 && !node.layout && !painted && !node.clip && !node.radius) {
      const c = node.children[0];
      c.x = (c.x || 0) + node.x; c.y = (c.y || 0) + node.y;
      if (node.opacity != null && node.opacity < 1) c.opacity = Math.min(c.opacity == null ? 1 : c.opacity, node.opacity);
      return c;
    }
    const cls = (el.getAttribute('class') || '').split(/\s+/)[0] || '';
    node.sig = tag + '.' + cls + ':' + node.children.map(c => c.t[0]).join('') + ':' + node.children.length;
    return node;
  };

  let bg = toRGBA(getComputedStyle(document.body).backgroundColor);
  if (!bg || bg[3] < 0.02) bg = [1, 1, 1, 1];
  const children = [];
  for (const kid of document.body.children) { const c = build(kid, 0, 0); if (c) children.push(c); }
  const root = { t: 'FRAME', x: 0, y: 0, w: Math.round(pageW), h: Math.round(pageH), children };
  return { w: Math.round(pageW), h: Math.round(pageH), bg, name: document.title || '', root };
}
"""


_CURRENTCOLOR_PROPS = ("border-top-color", "border-right-color", "border-bottom-color",
                       "border-left-color", "text-decoration-color", "outline-color")


def _media_kind(resp) -> str:
    try:
        u = resp.url.split("?", 1)[0].lower()
        ct = (resp.headers.get("content-type") or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    if u.endswith(".riv"):
        return "rive"
    if u.endswith(".lottie"):
        return "dotlottie"
    if u.endswith(".json") or "json" in ct:
        return "json"
    return ""


def _lottie_size(obj) -> tuple[int, int] | None:
    if isinstance(obj, dict) and isinstance(obj.get("layers"), list) and "fr" in obj and "op" in obj:
        try:
            return int(obj.get("w") or 0), int(obj.get("h") or 0)
        except (TypeError, ValueError):
            return 0, 0
    return None


async def _grab_media(resp, out: list[dict]) -> None:
    """Keep Lottie animations (JSON / dotLottie) and Rive files from responses."""
    import io
    import json as _json
    import zipfile
    kind = _media_kind(resp)
    try:
        if resp.status != 200:
            return
        body = await resp.body()
    except Exception:  # noqa: BLE001
        return
    if not body or len(body) > 6_000_000:
        return
    if kind == "rive":
        if body[:4] == b"RIVE":
            out.append({"kind": "rive", "url": resp.url, "data": body})
        return
    if kind == "dotlottie":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                names = [n for n in z.namelist() if n.startswith("animations/") and n.endswith(".json")]
                if not names:
                    return
                text = z.read(names[0]).decode("utf-8")
        except Exception:  # noqa: BLE001
            return
    else:
        if body.lstrip()[:1] != b"{":
            return
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return
    try:
        size = _lottie_size(_json.loads(text))
    except ValueError:
        return
    if size is None:
        return
    out.append({"kind": "lottie", "url": resp.url, "text": text, "w": size[0], "h": size[1]})


async def _inline_lottie_images(page, text: str, base_url: str) -> bytes | None:
    """Embed a Lottie's external image assets as data URIs (copy works offline)."""
    import base64
    import json as _json
    try:
        obj = _json.loads(text)
    except ValueError:
        return None
    fetched = 0
    for a in obj.get("assets") or []:
        if not isinstance(a, dict) or a.get("e") == 1 or not a.get("p") or fetched >= 30:
            continue
        p = str(a["p"])
        if p.startswith("data:"):
            continue
        try:
            u = urljoin(base_url, str(a.get("u") or "") + p)
            r = await page.context.request.get(u, timeout=8000)
            if r.ok:
                data = await r.body()
                if len(data) <= 3_000_000:
                    ct = (r.headers.get("content-type") or "image/png").split(";")[0]
                    a["u"], a["p"], a["e"] = "", f"data:{ct};base64,{base64.b64encode(data).decode()}", 1
                    fetched += 1
        except Exception:  # noqa: BLE001
            continue
    return _json.dumps(obj, separators=(",", ":")).encode("utf-8")


class Renderer:
    def __init__(self) -> None:
        self._pw = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=not settings.headful,
            args=["--disable-dev-shm-usage", "--no-sandbox"] + (
                ["--disable-gpu", "--no-zygote", "--renderer-process-limit=1",
                 "--disable-site-isolation-trials",
                 "--disable-features=IsolateOrigins,site-per-process,Translate,MediaRouter,OptimizationHints",
                 "--disable-extensions", "--disable-background-networking", "--disable-sync",
                 "--disable-component-update", "--mute-audio",
                 "--js-flags=--max-old-space-size=160"] if settings.low_memory else []),
        )
        log.info("Chromium launched (headless=%s)", not settings.headful)

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()
        self._browser = None
        self._pw = None

    async def __aenter__(self) -> "Renderer":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _new_context(self, vp: Viewport, block: bool = True,
                           reduced_motion: bool = False):
        assert self._browser is not None, "Renderer not started"
        context = await self._browser.new_context(
            viewport={"width": vp.width, "height": vp.height},
            device_scale_factor=1,
            ignore_https_errors=True,
            service_workers="block",
            # For deterministic quality shots: reduced-motion makes JS runtimes
            # that honour it (Framer, GSAP, ...) render the settled final state
            # instead of an entrance animation caught mid-flight.
            reduced_motion="reduce" if reduced_motion else "no-preference",
        )
        if block and settings.block_trackers:
            await context.route(_BLOCK_RE, lambda route: route.abort())
        if settings.low_memory:
            async def _no_media(route):
                if route.request.resource_type == "media":
                    await route.abort()
                else:
                    await route.continue_()
            await context.route(re.compile(r"\.(mp4|webm|ogg|ogv|mov|m4v|mp3|wav|m3u8|mpd)(\?|$)", re.I), _no_media)
        return context

    def _vp(self, name: str) -> Viewport:
        return settings.viewport(name) or Viewport("desktop", 1440, 900)

    async def capture_page(self, url: str, viewport_names: list[str]) -> RenderedPage:
        primary = self._vp(viewport_names[0] if viewport_names else "desktop")
        context = await self._new_context(primary)
        # Record every Element.animate() call (Framer Motion & co.) before any
        # page script runs, so finished animations can still be read back.
        try:
            await context.add_init_script(_motion.ANIM_HOOK_JS)
            await context.add_init_script(_players.PLAYER_HOOK_JS)
        except Exception:
            pass
        page = await context.new_page()
        result = RenderedPage(url=url, final_url=url, title="", html="")
        # Lottie JSON / dotLottie / Rive files seen on the network.
        media_tasks: list = []
        media_found: list[dict] = []

        def _on_media(r):
            if len(media_tasks) < 80 and _media_kind(r):
                media_tasks.append(asyncio.ensure_future(_grab_media(r, media_found)))

        page.on("response", _on_media)

        def _on_response(r):
            try:
                if r.status in (429, 503) and r.request.resource_type != "document":
                    result.throttled_resources += 1
                    ra = r.headers.get("retry-after") or ""
                    if ra.strip().isdigit():
                        result.retry_after = max(result.retry_after, float(ra))
            except Exception:  # noqa: BLE001
                pass

        page.on("response", _on_response)
        try:
            # Navigate on DOMContentLoaded, not "load": many real sites never
            # fire "load" cleanly (hanging third-party resources, beacons, long
            # polling), which would time out and fail the whole page even though
            # the DOM is fully there. If even DCL times out, proceed with the
            # partial DOM rather than failing hard.
            resp = None
            try:
                resp = await page.goto(url, wait_until="domcontentloaded",
                                       timeout=settings.nav_timeout_ms)
            except PlaywrightTimeoutError:
                pass
            result.status_code = resp.status if resp else 0
            if resp is not None and result.status_code in (429, 503):
                ra = resp.headers.get("retry-after") or ""
                result.retry_after = float(ra) if ra.strip().isdigit() else 0.0
                result.ok = False
                result.error = f"HTTP {result.status_code} (rate limited)"
                return result
            # Best-effort: let late resources and the network settle, but never
            # fail the capture if they do not (bounded, swallowed).
            for _state, _t in (("load", 8000), ("networkidle", 6000)):
                try:
                    await page.wait_for_load_state(_state, timeout=_t)
                except Exception:
                    pass
            # Resting (pre-animation) state, read before any scroll so elements
            # that animate into view are seen in their hidden starting state.
            await self._settle(page, scroll=False)
            await self._fonts_ready(page)
            try:
                await page.evaluate(_MOTION_BEFORE_JS)
            except Exception:
                pass
            # Scroll the full height: triggers lazy-load AND the site's own
            # scroll-reveal logic. Then read which elements became visible.
            await self._set_phase(page, "scroll")
            await self._settle(page, scroll=True)
            await self._fonts_ready(page)
            try:
                motion = await page.evaluate(_MOTION_AFTER_JS)
            except Exception:
                motion = {}
            await self._set_phase(page, "off")
            # Scroll-linked animations (parallax, scrub, JS pinning): sampled
            # top->bottom->top; ends back at the top for serialisation.
            try:
                scroll_anims = await page.evaluate(_motion.SCROLL_TRACK_JS, {
                    "maxEls": 1500 if settings.low_memory else 4000,
                    "maxSteps": 20 if settings.low_memory else 40,
                    "maxOut": 250,
                })
            except Exception as exc:
                log.debug("scroll tracks %s failed: %s", url, exc)
                scroll_anims = None
            # Phase 3: players (Lottie / Rive), text effects, JS marquees.
            players_meta: dict = {}
            try:
                await self._capture_players(page, result, media_tasks, media_found, players_meta)
            except Exception as exc:  # best effort
                log.debug("players %s failed: %s", url, exc)
            # Web Animations (JS-driven intros, in-view and looping animations)
            # read back with their real keyframes; elements tagged data-rx-a.
            try:
                anims = await page.evaluate(_motion.ANIM_COLLECT_JS)
            except Exception:
                anims = []
            # Tag hoverable elements now so the tags are in the serialised DOM;
            # they are probed after serialisation.
            try:
                n_hover = await page.evaluate(
                    _motion.HOVER_TAG_JS, 16 if settings.low_memory else 60)
            except Exception:
                n_hover = 0

            if settings.low_memory:
                await page.evaluate("() => { window.__rxMaxSnaps = 8; }")
            prep = await page.evaluate(_PREPARE_JS)
            collected = await page.evaluate(_COLLECT_JS)
            result.final_url = urldefrag(page.url)[0]
            result.title = collected.get("title") or ""
            result.links = self._absolutize(result.final_url, collected.get("links", []))
            result.stylesheet_urls = self._absolutize(result.final_url, collected.get("sheets", []))
            result.resource_urls = self._absolutize(result.final_url, collected.get("resources", []))
            result.analysis = collected.get("analysis", {})
            result.analysis["lang"] = collected.get("lang", "")

            # Serialise the fully rendered DOM (open shadow roots included).
            result.analysis["base_styles"] = await page.evaluate(STYLES_JS)
            result.analysis["base_classes"] = await page.evaluate("() => [document.documentElement.className || '', document.body ? (document.body.className || '') : '']")
            result.analysis["reveal"] = (motion or {}).get("table") or []
            result.analysis["anims"] = anims or []
            result.analysis.update(players_meta)
            result.analysis["scroll_anims"] = scroll_anims or {}
            result.html = "<!DOCTYPE html>\n" + await page.evaluate(_SERIALIZE_JS)
            result.ok = True

            # Classes the original JS toggles on scroll (sticky/shrinking header).
            try:
                result.analysis["scroll_state"] = await page.evaluate(_SCROLL_STATE_JS)
            except Exception:
                result.analysis["scroll_state"] = {}

            # Iframes/canvases (third-party embeds, maps, charts) cannot be
            # copied as code, so they are reproduced as pixel-exact images.
            for snap in prep.get("snaps", []):
                try:
                    png = await self._canvas_pixels(page, snap["id"]) if snap.get("tag") == "canvas" else None
                    if png is None:
                        loc = page.locator(f'[data-rx-snap="{snap["id"]}"]').first
                        png = await loc.screenshot(type="png", timeout=6000)
                    if png:
                        result.snapshots[snap["id"]] = png
                except Exception as exc:  # best effort
                    log.debug("snapshot %s#%s failed: %s", url, snap["id"], exc)

            # Screenshots + layout signatures per requested viewport.
            await self._freeze(page)
            primary_vp = viewport_names[0] if viewport_names else "desktop"
            for name in viewport_names:
                if name != primary_vp and n_hover and "hover" not in result.analysis:
                    await self._hover_pass(page, url, result, primary_vp, n_hover)
                vp = self._vp(name)
                try:
                    await page.set_viewport_size({"width": vp.width, "height": vp.height})
                    await self._settle(page, scroll=True)
                    result.analysis.setdefault("vp_classes", {})[name] = await page.evaluate("() => [document.documentElement.className || '', document.body ? (document.body.className || '') : '']")
                    result.screenshots[name] = await self._shot(page, vp)
                    result.signatures[name] = await page.evaluate(SIGNATURE_JS)
                    result.analysis.setdefault("vp_styles", {})[name] = await page.evaluate(
                        STYLE_DIFF_JS, result.analysis.get("base_styles") or {})
                    # Capture the re-rendered <body> for every non-primary
                    # breakpoint (Framer & co. swap the DOM per breakpoint). The
                    # serialised body is injected into the copy and shown at this
                    # width; the primary body is already in result.html. Skipped
                    # on low-memory hosts to keep the footprint small.
                    if name != primary_vp and not settings.low_memory:
                        await page.evaluate(_PREPARE_VARIANT_JS)
                        # Bake the live runtime layout (scaled fixed-width
                        # components) so the stripped-runtime copy keeps it.
                        try:
                            await page.evaluate(_BAKE_VARIANT_JS)
                        except Exception:
                            pass
                        body_html = await page.evaluate(_SERIALIZE_BODY_JS)
                        if body_html:
                            result.analysis.setdefault("bp_dom", {})[name] = body_html
                except Exception as exc:  # pragma: no cover - screenshot is best effort
                    log.warning("screenshot %s@%s failed: %s", url, name, exc)
            if n_hover and "hover" not in result.analysis:
                await self._hover_pass(page, url, result, primary_vp, n_hover)
        except Exception as exc:
            result.ok = False
            result.error = str(exc)
            log.warning("render failed %s: %s", url, exc)
        finally:
            await context.close()
        return result

    async def screenshot_url(self, url: str, viewport_name: str) -> bytes | None:
        """Screenshot a (possibly local file://) URL - used for quality checks."""
        shot = await self.inspect_url(url, viewport_name)
        return shot[0] if shot else None

    async def inspect_url(self, url: str, viewport_name: str) -> tuple[bytes, dict] | None:
        """Return ``(full-page png, layout signature)`` for a generated page."""
        vp = self._vp(viewport_name)
        context = await self._new_context(vp, block=False, reduced_motion=True)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=settings.nav_timeout_ms)
            await self._fonts_ready(page)
            await self._freeze(page)
            await self._settle(page, scroll=True)
            png = await self._shot(page, vp)
            sig = await page.evaluate(SIGNATURE_JS)
            return png, sig
        except Exception as exc:
            log.warning("qa screenshot failed %s@%s: %s", url, viewport_name, exc)
            return None
        finally:
            await context.close()

    async def extract_design(self, url: str, viewport_name: str = "desktop") -> dict | None:
        """Open a (local) copy and return its design tree for the Figma export."""
        vp = self._vp(viewport_name)
        context = await self._new_context(vp, block=False, reduced_motion=True)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=settings.nav_timeout_ms)
            await self._fonts_ready(page)
            await self._freeze(page)
            await self._settle(page, scroll=True)      # trigger lazy + reveal
            await page.evaluate("() => window.scrollTo(0, 0)")
            await page.wait_for_timeout(200)
            return await page.evaluate(_DESIGN_JS)
        except Exception as exc:  # pragma: no cover - best effort
            log.warning("design extract failed %s@%s: %s", url, viewport_name, exc)
            return None
        finally:
            await context.close()

    async def _shot(self, page, vp: Viewport) -> bytes:
        # Always clip to the viewport WIDTH (full height). A full-page capture
        # expands to the document's scroll *width* too, so a single horizontally
        # overflowing element - a marquee, a JS-pinned horizontal-scroll gallery
        # whose clipping is lost with its script - blows the frame out to
        # thousands of px wide and wrecks the comparison against the (clipped)
        # original. Clipping to the width a visitor actually sees keeps original
        # and copy on the same frame and is faithful to the live screenshot.
        height = await page.evaluate(
            "() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)")
        cap = _LOW_MEM_MAX_SHOT_H if settings.low_memory else _MAX_SHOT_H
        h = max(vp.height, min(int(height or vp.height), cap))
        # full_page=True is required for the clip to reach past the viewport;
        # clip then bounds the WIDTH to what a visitor sees (and the height cap).
        return await page.screenshot(full_page=True, type="png",
                                     clip={"x": 0, "y": 0, "width": vp.width, "height": h})

    async def _fonts_ready(self, page) -> None:
        try:
            # font-display:optional/fallback locks the system fallback when a web
            # font loads a touch late - routine over the network. The captured
            # screenshot would then show the fallback, misrepresenting the real
            # design (and diverging from the offline copy, whose fonts load
            # instantly from disk). Neutralise font-display, force every declared
            # face to download, then reflow so the intended font is applied.
            await page.evaluate(_FONT_FIX_JS)
            await page.evaluate(
                "() => Promise.race([document.fonts ? document.fonts.ready.then(() => 1) : 1,"
                " new Promise(r => setTimeout(r, 4000))])"
            )
        except Exception:
            pass

    async def _freeze(self, page) -> None:
        try:
            await page.evaluate(
                "(css) => { const s = document.createElement('style'); s.setAttribute('data-rx-ignore','');"
                " s.textContent = css; (document.head || document.documentElement).appendChild(s);"
                " document.querySelectorAll('video').forEach(v => { try { v.pause(); v.currentTime = 0; } catch(e){} });"
                # On the generated copy, force every captured animation/carousel to
                # its resolved state so the quality screenshot is deterministic and
                # matches the (also frozen) original. No-op on the live site.
                " try { if (window.ReplicatorInteractions && window.ReplicatorInteractions.freeze) window.ReplicatorInteractions.freeze(); } catch(e){} }",
                _FREEZE_CSS,
            )
        except Exception:
            pass

    @staticmethod
    async def _canvas_pixels(page, sid: str) -> bytes | None:
        """A canvas's own pixels, transparency kept.

        An element screenshot of a transparent canvas (particles, noise, cursor
        trails) bakes the page *behind* it into the image, which then ghosts
        over the copy. Returns ``None`` to fall back to a screenshot (opaque or
        tainted canvases, blank WebGL buffers of embedded scenes) and ``b""``
        to drop a blank full-screen overlay.
        """
        res = await page.evaluate(_CANVAS_PIXELS_JS, sid)
        if not res or res.get("mode") == "shot":
            return None
        if res.get("mode") == "drop":
            return b""
        data = res.get("url") or ""
        if not data.startswith("data:image/png;base64,"):
            return None
        import base64
        return base64.b64decode(data.split(",", 1)[1])

    async def _capture_players(self, page, result, media_tasks, media_found, meta_out: dict) -> None:
        """Lottie / Rive players, text effects and JS marquees (page at rest)."""
        try:
            meta_out["text_fx"] = await page.evaluate(_players.TEXT_COLLECT_JS) or []
        except Exception:
            meta_out["text_fx"] = []
        try:
            meta_out["marquee"] = await page.evaluate(
                _players.MARQUEE_JS, {"maxEls": 1500 if settings.low_memory else 4000}) or []
        except Exception:
            meta_out["marquee"] = []
        if media_tasks:
            await asyncio.wait(media_tasks, timeout=8)
        lotties = [m for m in media_found if m["kind"] == "lottie"]
        rivs = [m for m in media_found if m["kind"] == "rive"]
        found = await page.evaluate(_players.LOTTIE_COLLECT_JS) or []
        meta = []
        used: set[int] = set()
        for f in found:
            data = f.get("data")
            src_url = ""
            if not data:
                pick = None
                for k, m in enumerate(lotties):          # by URL first
                    if k not in used and m["url"] and m["url"] in (f.get("src"), f.get("path")):
                        pick = k
                        break
                if pick is None:                          # then by size, in order
                    for k, m in enumerate(lotties):
                        if k not in used and m["w"] == f.get("w") and m["h"] == f.get("h"):
                            pick = k
                            break
                if pick is None:
                    continue
                used.add(pick)
                data, src_url = lotties[pick]["text"], lotties[pick]["url"]
            # Only replay what plays by itself (animating now, or declared
            # autoplay); hover/scroll-driven ones keep their static frame.
            if not (f.get("live") or f.get("autoplay")):
                continue
            payload = await _inline_lottie_images(page, data, src_url or result.final_url)
            if not payload:
                continue
            result.media[f"lottie:{f['i']}"] = payload
            loop = f.get("loop")
            meta.append({"i": f["i"], "loop": True if loop is None else bool(loop)})
        meta_out["lottie"] = meta
        if rivs:
            canvases = await page.evaluate(_players.RIVE_CANVAS_JS) or []
            if len(canvases) == len(rivs):
                pairs = list(zip(canvases, rivs))
            elif len(rivs) == 1 and canvases:
                pairs = [(max(canvases, key=lambda c: c["w"] * c["h"]), rivs[0])]
            else:
                pairs = []
            rmeta = []
            for c, rv in pairs:
                result.media[f"rive:{c['i']}"] = rv["data"]
                rmeta.append({"i": c["i"]})
            meta_out["rive"] = rmeta

    @staticmethod
    async def _set_phase(page, phase: str) -> None:
        try:
            await page.evaluate("(p) => { window.__rxPhase = p; }", phase)
        except Exception:
            pass

    async def _hover_pass(self, page, url, result, primary_vp, n_hover) -> None:
        """Probe hover states at the primary width.

        Runs right AFTER the primary viewport's screenshot / style capture so
        the extra time it takes does not shift what those record (autoplaying
        heroes drift with time), and before other breakpoints re-render the DOM.
        """
        try:
            vp = self._vp(primary_vp)
            await page.set_viewport_size({"width": vp.width, "height": vp.height})
            result.analysis["hover"] = await self._probe_hover(page, n_hover)
        except Exception as exc:  # best effort
            result.analysis["hover"] = []
            log.debug("hover probe %s failed: %s", url, exc)

    async def _probe_hover(self, page, count: int) -> list[dict]:
        """Hover each tagged element and diff the computed style it produces."""
        out: list[dict] = []
        await self._set_phase(page, "hover")
        try:
            for n in range(count):
                aim = await page.evaluate(_motion.HOVER_AIM_JS, n)
                if not aim:
                    continue
                await page.mouse.move(1, 1)
                await page.evaluate(_motion.FINISH_JS)
                before = await page.evaluate(_motion.HOVER_READ_JS, n)
                if not before:
                    continue
                mark = await page.evaluate(_motion.HOVER_TIMING_START_JS)
                await page.mouse.move(aim["x"], aim["y"])
                await page.wait_for_timeout(60)
                await page.evaluate(_motion.FINISH_JS)
                await page.wait_for_timeout(30)
                after = await page.evaluate(_motion.HOVER_READ_JS, n) or {}
                timing = await page.evaluate(_motion.HOVER_TIMING_JS, [n, mark]) or {}
                rows = []
                for path, b in before.items():
                    a = after.get(path)
                    if not a:
                        continue
                    diff = {k: v for k, v in a.items()
                            if not k.startswith("__") and v != b.get(k)}
                    # Colours that merely follow currentColor come with `color`.
                    for k in _CURRENTCOLOR_PROPS:
                        if k in diff and b.get(k) == b.get("color") and a.get(k) == a.get("color"):
                            del diff[k]
                    if not diff:
                        continue
                    row = {"p": path, "s": diff}
                    # A CSS transition already animates it; otherwise use the
                    # runtime's own animation timing, when one ran.
                    if path in timing and (b.get("__td") or "0s").strip() in ("0s", "0s, 0s"):
                        row["tr"] = timing[path]
                    rows.append(row)
                if rows:
                    out.append({"i": n, "r": rows[:40]})
        finally:
            try:
                await page.mouse.move(1, 1)
                await page.evaluate(_motion.FINISH_JS)
                await page.evaluate("() => window.scrollTo(0, 0)")
            except Exception:
                pass
            await self._set_phase(page, "off")
        return out

    async def _settle(self, page, scroll: bool = True) -> None:
        if scroll:
            try:
                await page.evaluate(_AUTOSCROLL_JS)
            except Exception:
                pass
        await page.wait_for_timeout(350)

    @staticmethod
    def _absolutize(base: str, urls: list[str]) -> list[str]:
        out, seen = [], set()
        for u in urls:
            if not u:
                continue
            try:
                full = urldefrag(urljoin(base, u))[0]
            except ValueError:
                continue
            if full and full not in seen and full.startswith(("http://", "https://")):
                seen.add(full)
                out.append(full)
        return out
