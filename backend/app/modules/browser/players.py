"""Browser-side capture for animation *players* and JS-driven continuous motion.

Phase 3 of the motion pipeline (phases 1-2 live in :mod:`.motion`):

* **Lottie** - lottie-web's SVG renderer marks its clip paths
  ``__lottie_element_*`` and LottieFiles web components carry a ``src``; the
  animation JSON comes from the network (matched by size / URL) or from a hook
  on the global ``lottie`` / ``bodymovin`` (inline ``animationData``). The copy
  ships the JSON and a vendored lottie-web and replays it.
* **Rive** - ``.riv`` files seen on the network are matched to canvases that are
  being redrawn; the copy replays them with a vendored Rive runtime.
* **Text effects** - typewriters, word rotators and number count-ups, recorded
  as text changes from page load (no extra capture time).
* **JS marquees** - transforms moving at a steady speed with no CSS / Web
  Animation behind them (requestAnimationFrame loops).
"""
from __future__ import annotations

# Init script (installed with ANIM_HOOK_JS).
PLAYER_HOOK_JS = r"""
(() => {
  if (window.__rxText) return;
  // Lottie (UMD global): remember containers + params, incl. inline data.
  window.__rxLottie = [];
  const wrap = (lib) => {
    if (!lib || lib.__rxWrapped || typeof lib.loadAnimation !== 'function') return lib;
    const orig = lib.loadAnimation.bind(lib);
    lib.loadAnimation = function (params) {
      const anim = orig(params);
      try {
        if (window.__rxLottie.length < 40)
          window.__rxLottie.push({ container: params && (params.container || params.wrapper), params: params || {} });
      } catch (e) {}
      return anim;
    };
    try { lib.__rxWrapped = true; } catch (e) {}
    return lib;
  };
  ['lottie', 'bodymovin'].forEach((name) => {
    let v = window[name];
    try {
      Object.defineProperty(window, name, { configurable: true, enumerable: true,
        get() { return v; }, set(n) { v = wrap(n); } });
      if (v) v = wrap(v);
    } catch (e) {}
  });
  // Text changes of small elements, with time and capture phase.
  const rec = new Map();
  window.__rxText = rec;
  const t0 = performance.now();
  const SKIP = { SCRIPT: 1, STYLE: 1, BODY: 1, HTML: 1, HEAD: 1, TITLE: 1, NOSCRIPT: 1 };
  const note = (el) => {
    if (!el || el.nodeType !== 1 || SKIP[el.tagName] || el.childElementCount > 6) return;
    const txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (txt.length > 120) return;
    let list = rec.get(el);
    if (!list) { if (rec.size >= 300) return; list = []; rec.set(el, list); }
    if (list.length && list[list.length - 1].x === txt) return;
    if (list.length < 600) list.push({ x: txt, t: Math.round(performance.now() - t0), p: window.__rxPhase || 'load' });
  };
  const start = () => {
    try {
      new MutationObserver((ms) => {
        for (const m of ms) note(m.type === 'characterData' ? m.target.parentElement : m.target);
      }).observe(document.documentElement, { subtree: true, childList: true, characterData: true });
    } catch (e) {}
  };
  if (document.documentElement) start();
  else document.addEventListener('readystatechange', start, { once: true });
})();
"""

# Lottie containers; tags data-rx-lottie (+ data-rx-lottie-host on a web
# component host). `live` = still animating now (sampled twice).
LOTTIE_COLLECT_JS = r"""
async () => {
  const found = [];
  const seen = new Set();
  const roots = [document];
  for (const el of document.querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
  for (const root of roots) {
    for (const marker of root.querySelectorAll('[id^="__lottie_element_"]')) {
      const svg = marker.closest('svg');
      if (!svg || seen.has(svg) || !svg.parentElement) continue;
      seen.add(svg);
      found.push({ svg: svg, box: svg.parentElement, host: (root !== document) ? root.host : null });
    }
  }
  if (!found.length) return [];
  const sig = (svg) => {
    let s = '';
    const nodes = svg.querySelectorAll('g,path');
    for (let i = 0; i < nodes.length && i < 400; i++) {
      const n = nodes[i];
      s += (n.getAttribute('transform') || '') + (n.getAttribute('opacity') || '') + (n.getAttribute('d') || '').length + '|';
    }
    return s;
  };
  const before = found.map(f => sig(f.svg));
  await new Promise(r => setTimeout(r, 450));
  const hooks = window.__rxLottie || [];
  const abs = (u) => { try { return u ? new URL(u, location.href).href : ''; } catch (e) { return ''; } };
  return found.map((f, i) => {
    const vb = (f.svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
    const hook = hooks.find(h => h.container && (h.container === f.box || (h.container.contains && h.container.contains(f.svg))));
    let data = null, path = '', loop = null, autoplay = null;
    if (hook) {
      const p = hook.params || {};
      try { if (p.animationData) { const s = JSON.stringify(p.animationData); if (s.length < 4e6) data = s; } } catch (e) {}
      path = p.path || '';
      if (p.loop !== undefined) loop = !!p.loop;
      if (p.autoplay !== undefined) autoplay = !!p.autoplay;
    }
    let src = '';
    if (f.host) {
      src = f.host.getAttribute('src') || '';
      if (loop === null && f.host.hasAttribute('loop')) loop = true;
      if (autoplay === null && f.host.hasAttribute('autoplay')) autoplay = true;
      f.host.setAttribute('data-rx-lottie-host', String(i));
    }
    f.box.setAttribute('data-rx-lottie', String(i));
    return { i: i, w: vb[2] || 0, h: vb[3] || 0, src: abs(src), path: abs(path), data: data,
             live: sig(f.svg) !== before[i], loop: loop, autoplay: autoplay };
  });
}
"""

# Canvases being redrawn right now (2D-readable): Rive candidates, DOM order.
RIVE_CANVAS_JS = r"""
async () => {
  const cs = [...document.querySelectorAll('canvas')].filter(c => {
    const r = c.getBoundingClientRect();
    return c.width > 8 && c.height > 8 && r.width > 8 && r.height > 8;
  });
  const shot = (c) => { try { const d = c.toDataURL('image/png'); return d.length + ':' + d.slice(-96); } catch (e) { return null; } };
  const a = cs.map(shot);
  await new Promise(r => setTimeout(r, 400));
  const out = [];
  cs.forEach((c, i) => {
    const b = shot(c);
    if (a[i] === null || b === null || a[i] === b) return;
    const r = c.getBoundingClientRect();
    out.push({ el: c, w: Math.round(r.width), h: Math.round(r.height) });
  });
  return out.map((o, i) => { o.el.setAttribute('data-rx-rive', String(i)); return { i: i, w: o.w, h: o.h }; });
}
"""

# Typewriters, word rotators and count-ups from the recorded text changes.
# Numbers that went down while the scroll sampler ran are scroll read-outs.
TEXT_COLLECT_JS = r"""
() => {
  const rec = window.__rxText;
  if (!rec) return [];
  const NUM = /^([^\d-]*?)(-?\d[\d,.\s]*)([^\d]*)$/;
  const parseNum = (s) => {
    const m = NUM.exec(s);
    if (!m) return null;
    const raw = m[2].replace(/[\s,]/g, '');
    const v = parseFloat(raw);
    if (isNaN(v)) return null;
    const dec = raw.indexOf('.') >= 0 ? raw.split('.')[1].length : 0;
    return { v: v, pre: m[1], suf: m[3], dec: dec, sep: m[2].indexOf(',') >= 0 };
  };
  const median = (arr) => { if (!arr.length) return 0; const s = arr.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
  const out = [];
  for (const [el, list] of rec) {
    if (out.length >= 60) break;
    if (!el.isConnected || list.length < 3 || el.closest('[data-rx-ignore]')) continue;
    // A child carrying the same stream is the real target.
    if ([...el.children].some(c => rec.has(c) && rec.get(c).length >= list.length - 1)) continue;
    const texts = list.map(e => e.x);
    const distinct = [...new Set(texts)];
    if (distinct.length < 2) continue;
    const span = list[list.length - 1].t - list[0].t;
    if (span < 300) continue;
    const nums = texts.map(parseNum);
    if (nums.every(n => n)) {
      const vals = nums.map(n => n.v);
      let down = false;
      for (let k = 1; k < vals.length; k++) if (vals[k] < vals[k - 1]) down = true;
      if (down || list.some(e => e.p === 'off') || vals[vals.length - 1] <= vals[0]) continue;
      const last = nums[nums.length - 1];
      el.setAttribute('data-rx-text', String(out.length));
      out.push({ i: out.length, k: 'count', from: vals[0], to: last.v, pre: last.pre, suf: last.suf,
                 dec: last.dec, sep: last.sep, d: Math.max(400, Math.min(span, 6000)) });
      continue;
    }
    // Typewriter: most steps add or remove one trailing character.
    let unit = 0;
    const adds = [];
    for (let k = 1; k < list.length; k++) {
      const a = texts[k - 1], b = texts[k];
      const add = b.length === a.length + 1 && b.indexOf(a) === 0;
      const del = a.length === b.length + 1 && a.indexOf(b) === 0;
      if (add || del) unit++;
      if (add) adds.push(list[k].t - list[k - 1].t);
    }
    if (list.length >= 6 && unit >= 0.6 * (list.length - 1)) {
      // A word is a peak: reached by typing, left by deleting.
      const peak = (k) => k + 1 < texts.length && texts[k + 1].length < texts[k].length
                          && (k === 0 || texts[k - 1].length < texts[k].length);
      const words = [];
      const holds = [];
      for (let k = 0; k < texts.length; k++) {
        if (!peak(k) || !texts[k]) continue;
        if (words.indexOf(texts[k]) < 0) words.push(texts[k]);
        holds.push(list[k + 1].t - list[k].t);
      }
      const final = texts[texts.length - 1];
      if (!words.length && final) words.push(final);
      if (!words.length) continue;
      el.setAttribute('data-rx-text', String(out.length));
      out.push({ i: out.length, k: 'type', words: words.slice(0, 12),
                 speed: Math.max(20, Math.min(median(adds) || 80, 400)),
                 hold: Math.max(400, Math.min(median(holds) || 1500, 6000)) });
      continue;
    }
    // Rotator: whole-word swaps on a rhythm.
    if (distinct.length > 20 || distinct.some(t => t.length > 60)) continue;
    const gaps = [];
    for (let k = 1; k < list.length; k++) gaps.push(list[k].t - list[k - 1].t);
    const gap = median(gaps);
    if (gap < 250 || gaps.length < 3) continue;
    // A timer, not a reaction (scroll direction, hover): regular rhythm.
    if (gaps.filter(g => Math.abs(g - gap) <= 0.4 * gap).length < 0.6 * gaps.length) continue;
    if (texts.length <= distinct.length && distinct.length < 3) continue;   // no cycle seen
    el.setAttribute('data-rx-text', String(out.length));
    out.push({ i: out.length, k: 'rotate', words: distinct, gap: Math.min(gap, 8000) });
  }
  return out;
}
"""

# JS-driven marquees: steady transform motion with no CSS/Web Animation behind
# it. Loop length = period of the repeated children (else half the track).
MARQUEE_JS = r"""
async (opts) => {
  const body = document.body;
  if (!body) return [];
  const median = (a) => { const s = a.slice().sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
  const els = [];
  const all = body.querySelectorAll('*');
  for (let k = 0; k < all.length && els.length < opts.maxEls; k++) {
    const el = all[k];
    if (el.childElementCount < 2 || el.closest('svg') || el.closest('[data-rx-ignore]')) continue;
    els.push(el);
  }
  const pos = () => els.map(el => {
    const t = getComputedStyle(el).transform;
    if (!t || t === 'none') return [0, 0];
    try { const m = new DOMMatrixReadOnly(t); return [m.m41, m.m42]; } catch (e) { return [0, 0]; }
  });
  const samples = [], times = [];
  for (let s = 0; s < 4; s++) {
    samples.push(pos()); times.push(performance.now());
    if (s < 3) await new Promise(r => setTimeout(r, 330));
  }
  const out = [];
  for (let j = 0; j < els.length && out.length < 20; j++) {
    const el = els[j];
    try { if (el.getAnimations().length) continue; } catch (e) {}
    if (el.parentElement && el.parentElement.hasAttribute('data-rx-marquee')) continue;
    for (const ax of [0, 1]) {
      const v = [];
      for (let s = 1; s < 4; s++) v.push((samples[s][j][ax] - samples[s - 1][j][ax]) / ((times[s] - times[s - 1]) / 1000));
      const moving = v.filter(x => Math.abs(x) > 4);
      if (moving.length < 2) continue;
      const sgn = Math.sign(median(moving));
      const same = moving.filter(x => Math.sign(x) === sgn);           // tolerate one wrap jump
      if (same.length < 2) continue;
      const speed = Math.abs(median(same));
      if (same.some(x => Math.abs(Math.abs(x) - speed) > 0.35 * speed)) continue;
      const kids = [...el.children];
      const sigs = kids.map(c => c.outerHTML.length + ':' + (c.textContent || '').slice(0, 40));
      let period = 0;
      for (let p = 1; p <= kids.length / 2 && !period; p++) {
        let rep = true;
        for (let q = p; q < kids.length; q++) if (sigs[q] !== sigs[q - p]) { rep = false; break; }
        if (rep) period = p;
      }
      let L = 0;
      if (period) {
        const a = kids[0].getBoundingClientRect(), b = kids[period].getBoundingClientRect();
        L = Math.abs(ax === 0 ? b.left - a.left : b.top - a.top);
      }
      if (!(L > 8)) L = (ax === 0 ? el.scrollWidth : el.scrollHeight) / 2;
      if (!(L > 8)) continue;
      el.setAttribute('data-rx-marquee', String(out.length));
      out.push({ i: out.length, ax: ax === 0 ? 'x' : 'y', dir: sgn,
                 speed: Math.round(speed * 10) / 10, len: Math.round(L * 10) / 10 });
      break;
    }
  }
  return out;
}
"""
