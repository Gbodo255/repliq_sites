"""Browser-side capture of JS-driven motion: Web Animations + hover states.

The offline copy strips the site's JavaScript, so anything the runtime animated
by script is lost. Two library-agnostic captures recover a large part of it:

* **Web Animations** - modern runtimes (Framer Motion, Motion One, Framer's
  "appear" optimiser, many hand-written intros) animate through
  ``Element.animate()``. :data:`ANIM_HOOK_JS` is installed as an init script so
  every such call is recorded with its element *before* the animation finishes
  and disappears from ``document.getAnimations()``. :data:`ANIM_COLLECT_JS` then
  reads the real keyframes / timing back from each effect, tags the element
  with ``data-rx-a`` and returns a compact table that
  :mod:`app.modules.interaction_analyzer.motion_css` turns into ``@keyframes``.

* **Hover states** - :data:`HOVER_TAG_JS` tags hoverable elements
  (``data-rx-h``) before serialisation; the renderer then hovers each one with
  the real mouse and :data:`HOVER_READ_JS` diffs the computed style of the
  element and its descendants. JS-driven hovers (Framer ``whileHover``,
  class toggles on ``mouseenter``) become plain ``:hover`` rules.
"""
from __future__ import annotations

# Installed with context.add_init_script: runs before any page script.
ANIM_HOOK_JS = r"""
(() => {
  if (window.__rxAnim || typeof Element === 'undefined' || !Element.prototype.animate) return;
  const rec = [];
  window.__rxAnim = rec;
  window.__rxPhase = window.__rxPhase || 'load';
  const orig = Element.prototype.animate;
  Element.prototype.animate = function () {
    const a = orig.apply(this, arguments);
    try {
      if (window.__rxPhase !== 'off' && rec.length < 1500)
        rec.push({ el: this, a: a, ph: window.__rxPhase });
    } catch (e) {}
    return a;
  };
})();
"""

ANIM_COLLECT_JS = r"""
() => {
  const rec = (window.__rxAnim || []).slice();
  const seen = new Set(rec.map(r => r.a));
  // Animations built with `new Animation(new KeyframeEffect(...))` bypass the
  // hook: pick up the ones still running (loops, mostly).
  try {
    for (const a of document.getAnimations()) {
      if (seen.has(a)) continue;
      if (typeof CSSAnimation !== 'undefined' && a instanceof CSSAnimation) continue;
      if (typeof CSSTransition !== 'undefined' && a instanceof CSSTransition) continue;
      const t = a.effect && a.effect.target;
      if (t) rec.push({ el: t, a: a, ph: 'load' });
    }
  } catch (e) {}
  const SKIP = { offset: 1, computedOffset: 1, easing: 1, composite: 1 };
  const kebab = (k) => k === 'cssFloat' ? 'float' : (k.indexOf('--') === 0 ? k : k.replace(/[A-Z]/g, m => '-' + m.toLowerCase()));
  const byEl = new Map();
  for (const r of rec) {
    const el = r.el;
    try {
      if (!el || !el.isConnected || el.nodeType !== 1) continue;
      if (el.hasAttribute('data-rx-reveal-i') || el.closest('[data-rx-ignore]')) continue;
      const eff = r.a.effect;
      if (!eff || !eff.getKeyframes || eff.pseudoElement) continue;
      const tm = eff.getTiming();
      const dur = typeof tm.duration === 'number' ? tm.duration : 0;
      if (!(dur > 0) || dur > 120000) continue;
      const kfs = eff.getKeyframes();
      if (!kfs.length || kfs.length > 24) continue;
      const frames = [], props = new Set();
      let distinct = new Set();
      for (const k of kfs) {
        const f = { o: (k.computedOffset != null ? k.computedOffset : k.offset), e: k.easing || 'linear', p: {} };
        for (const key in k) {
          if (SKIP[key]) continue;
          const v = k[key];
          if (v == null || v === '') continue;
          const s = String(v);
          if (s.length > 400) continue;
          const css = kebab(key);
          f.p[css] = s; props.add(css);
        }
        distinct.add(JSON.stringify(f.p));
        frames.push(f);
      }
      if (!props.size || (frames.length > 1 && distinct.size < 2)) continue;
      const sig = Array.from(props).sort().join(',');
      let list = byEl.get(el);
      if (!list) { list = []; byEl.set(el, list); }
      if (list.length >= 6 || list.some(x => x.sig === sig)) continue;   // first run wins
      list.push({ sig: sig, ph: r.ph, kf: frames, d: Math.round(dur),
                  dl: Math.round(tm.delay || 0),
                  it: tm.iterations === Infinity ? -1 : (tm.iterations || 1),
                  dir: tm.direction || 'normal', ez: tm.easing || 'linear' });
    } catch (e) {}
  }
  const out = [];
  let i = 0;
  for (const [el, list] of byEl) {
    if (i >= 300) break;
    const view = list.some(x => x.ph === 'scroll' && x.it !== -1);
    el.setAttribute('data-rx-a', String(i));
    if (view) el.setAttribute('data-rx-a-view', '');
    out.push({ i: i, t: view ? 'view' : 'load',
               a: list.map(x => ({ kf: x.kf, d: x.d, dl: x.dl, it: x.it, dir: x.dir, ez: x.ez })) });
    i++;
  }
  return out;
}
"""

# Tag hoverable elements (top of each pointer region) before serialisation.
HOVER_TAG_JS = r"""
(max) => {
  const body = document.body;
  if (!body) return 0;
  const vw = innerWidth, vh = innerHeight;
  const picked = [];
  const pickedSet = new Set();
  const els = body.querySelectorAll('*');
  const cap = Math.min(els.length, 5000);
  for (let i = 0; i < cap && picked.length < max; i++) {
    const el = els[i];
    const tag = el.tagName.toLowerCase();
    if (tag === 'svg' || el.closest('svg') || el.closest('[data-rx-ignore]')) continue;
    const isCtl = tag === 'a' || tag === 'button' || el.getAttribute('role') === 'button';
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { continue; }
    if (!isCtl && cs.cursor !== 'pointer') continue;
    // Top of the pointer region only: a pointer child of a picked element is
    // covered by the parent's descendant diff.
    let p = el.parentElement, nested = false;
    for (let d = 0; p && d < 4; d++, p = p.parentElement) if (pickedSet.has(p)) { nested = true; break; }
    if (nested) continue;
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.width * r.height > 0.6 * vw * vh) continue;
    if (cs.position === 'fixed' && r.top > vh) continue;
    el.setAttribute('data-rx-h', String(picked.length));
    picked.push(el); pickedSet.add(el);
  }
  window.__rxH = picked;
  return picked.length;
}
"""

# Bring candidate n into view; return its centre in viewport coordinates.
HOVER_AIM_JS = r"""
(n) => {
  const el = (window.__rxH || [])[n];
  if (!el || !el.isConnected) return null;
  el.scrollIntoView({ block: 'center', inline: 'nearest' });
  const r = el.getBoundingClientRect();
  if (r.width < 4 || r.height < 4) return null;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return null;
  const hit = document.elementFromPoint(x, y);
  if (!hit || !(hit === el || el.contains(hit))) return null;   // covered
  return { x: x, y: y };
}
"""

# Finish every finite animation so the hovered / un-hovered state settles now.
FINISH_JS = r"""
() => {
  try {
    for (const a of document.getAnimations()) {
      try {
        if (a.effect && a.effect.getTiming().iterations !== Infinity && a.playState !== 'finished') a.finish();
      } catch (e) {}
    }
  } catch (e) {}
}
"""

# Computed visual state of candidate n and its descendants, keyed by a
# tag:nth-of-type path relative to the candidate ('' = the candidate). Nodes
# under an infinite animation are skipped (they change on their own).
HOVER_READ_JS = r"""
(n) => {
  const root = (window.__rxH || [])[n];
  if (!root || !root.isConnected) return null;
  const PROPS = ['color', 'background-color', 'background-image', 'border-top-color',
    'border-right-color', 'border-bottom-color', 'border-left-color', 'box-shadow',
    'opacity', 'transform', 'translate', 'scale', 'rotate', 'filter', 'backdrop-filter',
    'text-decoration-line', 'text-decoration-color', 'outline-color', 'outline-style',
    'fill', 'stroke', 'visibility', 'clip-path', 'border-radius', 'letter-spacing'];
  const looping = (el) => {
    try { return el.getAnimations().some(a => { try { return a.effect.getTiming().iterations === Infinity; } catch (e) { return false; } }); }
    catch (e) { return false; }
  };
  const out = {};
  const walk = (el, path, depth) => {
    if (Object.keys(out).length >= 80) return;
    if (!looping(el)) {
      const cs = getComputedStyle(el);
      const s = {};
      for (const p of PROPS) s[p] = cs.getPropertyValue(p);
      s['__td'] = cs.transitionDuration;
      out[path] = s;
    }
    if (depth >= 6) return;
    const count = {};
    for (const c of el.children) {
      const t = c.tagName.toLowerCase();
      count[t] = (count[t] || 0) + 1;
      if (t === 'script' || t === 'style' || t === 'template' || t === 'noscript') continue;
      walk(c, (path ? path + '>' : '') + t + ':nth-of-type(' + count[t] + ')', depth + 1);
    }
  };
  walk(root, '', 0);
  return out;
}
"""

# Web Animations started by the last hover, keyed like HOVER_READ_JS paths:
# their duration/easing become the copy's transition.
HOVER_TIMING_JS = r"""
(args) => {
  const n = args[0], from = args[1];
  const root = (window.__rxH || [])[n];
  const rec = (window.__rxAnim || []).slice(from);
  const out = {};
  if (!root) return out;
  const rel = (el) => {
    const parts = [];
    while (el && el !== root) {
      const p = el.parentElement;
      if (!p) return null;
      let i = 1, s = el;
      while ((s = s.previousElementSibling)) if (s.tagName === el.tagName) i++;
      parts.unshift(el.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      el = p;
    }
    return el === root ? parts.join('>') : null;
  };
  for (const r of rec) {
    try {
      if (!root.contains(r.el)) continue;
      const tm = r.a.effect.getTiming();
      const d = typeof tm.duration === 'number' ? Math.round(tm.duration) : 0;
      if (!(d > 0) || d > 5000) continue;
      const k = rel(r.el);
      if (k === null || out[k]) continue;
      out[k] = d + 'ms ' + (tm.easing || 'ease');
    } catch (e) {}
  }
  return out;
}
"""

HOVER_TIMING_START_JS = "() => (window.__rxAnim || []).length"


# --- Scroll-linked animations (parallax, scrub, pinning) ----------------------
# The page is scrolled in steps top -> bottom, then bottom -> top, reading the
# visual state of every element at each stop. An element is *scroll-linked* when
# its state varies with the scroll position AND is the same at a given position
# on both passes (one-shot reveals and direction-dependent headers are not).
# Its samples become a keyframe track replayed on a scroll timeline. JS pinning
# (position toggled to fixed) is turned into a ``translate`` track from the
# element's offset to its parent. Elements are tagged ``data-rx-s``.
SCROLL_TRACK_JS = r"""
async (opts) => {
  const body = document.body;
  if (!body) return null;
  const se = document.scrollingElement || document.documentElement;
  const vh = innerHeight;
  const maxY = Math.max(0, se.scrollHeight - vh);
  if (maxY < vh * 0.25) return null;
  const smooth = !!document.querySelector('html.lenis, html.has-scroll-smooth, [data-scroll-container], .locomotive-scroll');
  const wait = smooth ? 380 : 90;
  const maxSteps = smooth ? Math.min(opts.maxSteps, 24) : opts.maxSteps;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const SKIPTAG = { SCRIPT: 1, STYLE: 1, LINK: 1, META: 1, NOSCRIPT: 1, TEMPLATE: 1, BR: 1, HEAD: 1, TITLE: 1 };
  const PROPS = ['transform', 'opacity', 'filter', 'clip-path', 'translate', 'scale', 'rotate',
                 'background-position', 'background-color', 'color', 'position'];
  const els = [];
  const all = body.querySelectorAll('*');
  for (let k = 0; k < all.length && els.length < opts.maxEls; k++) {
    const el = all[k];
    if (SKIPTAG[el.tagName] || (el.tagName !== 'svg' && el.closest('svg'))) continue;
    if (el.closest('[data-rx-ignore]')) continue;
    try {
      if (el.getAnimations().some(a => { try { return a.effect.getTiming().iterations === Infinity; } catch (e) { return false; } })) continue;
    } catch (e) {}
    if (getComputedStyle(el).display === 'none') continue;
    els.push(el);
  }
  const read = () => {
    const out = new Array(els.length);
    for (let j = 0; j < els.length; j++) {
      const el = els[j];
      if (!el.isConnected) { out[j] = ''; continue; }
      const cs = getComputedStyle(el);
      let s = '';
      for (const p of PROPS) s += cs.getPropertyValue(p) + '\u0001';
      // Layout offset to the parent, without the element's own transform
      // (that one is tracked separately).
      const par = el.parentElement;
      let dy = 0;
      if (par) {
        let ty = 0;
        const tf = cs.transform;
        if (tf && tf !== 'none') { try { ty = new DOMMatrixReadOnly(tf).m42; } catch (e) {} }
        dy = Math.round(el.getBoundingClientRect().top - par.getBoundingClientRect().top - ty);
      }
      out[j] = s + dy;
    }
    return out;
  };
  const n = Math.min(maxSteps, Math.ceil(maxY / (vh * 0.25))) + 1;
  const ys = [];
  for (let i = 0; i < n; i++) ys.push(Math.round(maxY * i / (n - 1)));
  const down = [], up = new Array(n);
  for (let i = 0; i < n; i++) { window.scrollTo(0, ys[i]); await frame(); await sleep(wait); down.push(read()); }
  for (let i = n - 1; i >= 0; i--) { window.scrollTo(0, ys[i]); await frame(); await sleep(wait); up[i] = read(); }
  window.scrollTo(0, 0); await frame(); await sleep(wait);

  const norm = (s) => s.replace(/-?\d*\.?\d+(e-?\d+)?/g, m => String(Math.round(parseFloat(m) * 20) / 20));
  const result = [];
  const colorOf = new Map();   // element -> its colour track (inherited by children)
  for (let j = 0; j < els.length && result.length < opts.maxOut; j++) {
    const d = down.map(r => norm(r[j])), u = up.map(r => norm(r[j]));
    if (new Set(d).size < 2) continue;
    const C = new Set();
    for (let i = 1; i < n; i++) if (d[i] !== d[i - 1] || u[i] !== u[i - 1]) { C.add(i); C.add(i - 1); }
    let miss = 0;
    for (const i of C) if (d[i] !== u[i]) miss++;
    if (!C.size || miss > 0.2 * C.size) continue;
    // Per-property tracks (raw values from the downward pass).
    const rows = down.map(r => r[j].split('\u0001'));
    const tracks = {};
    let pinned = false;
    PROPS.forEach((p, k) => {
      const vals = rows.map(r => r[k]);
      if (new Set(vals.map(norm)).size < 2) return;
      if (p === 'position') { pinned = true; return; }
      tracks[p] = vals;
    });
    if (tracks['color']) {
      const sig = tracks['color'].join('|');
      colorOf.set(els[j], sig);
      const par = els[j].parentElement;
      if (par && colorOf.get(par) === sig) delete tracks['color'];   // inherited
    }
    if (pinned && !tracks['translate']) {
      // The copy keeps the position serialised at the top of the page: if that
      // is `fixed`, the element stays put while its parent scrolls away.
      const posK = PROPS.indexOf('position');
      const fixed0 = rows[0][posK] === 'fixed';
      const dys = rows.map(r => parseInt(r[PROPS.length], 10) || 0);
      const need = dys.map((v, i) => v - dys[0] - (fixed0 ? ys[i] - ys[0] : 0));
      if (need.some(v => Math.abs(v) > 1)) tracks['translate'] = need.map(v => '0px ' + v + 'px');
    }
    const keys = Object.keys(tracks);
    if (!keys.length) continue;
    // Trim the constant head/tail: keep one sample of context on each side.
    let a = 0, b = n - 1;
    const same = (i1, i2) => keys.every(k => norm(tracks[k][i1]) === norm(tracks[k][i2]));
    while (a < b && same(a, a + 1)) a++;
    while (b > a && same(b, b - 1)) b--;
    if (a >= b) continue;
    const idx = [];
    for (let i = a; i <= b; i++) {
      // drop interior points of flat plateaus
      if (i > a && i < b && same(i, i - 1) && same(i, i + 1)) continue;
      idx.push(i);
    }
    const p = {};
    for (const k of keys) p[k] = idx.map(i => tracks[k][i]);
    const id = result.length;
    els[j].setAttribute('data-rx-s', String(id));
    els[j].setAttribute('data-rx-s-r', ys[a] + ',' + ys[b]);
    result.push({ i: id, y: idx.map(i => ys[i]), p: p });
  }
  return { els: result, maxY: maxY, vh: vh, steps: n };
}
"""
