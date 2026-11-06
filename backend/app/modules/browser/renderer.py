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

from app.config import Viewport, settings
from app.core.logging import get_logger
from app.models.domain import RenderedPage

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
  document.documentElement.classList.remove('async-hide');
  return out;
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


_LOW_MEM_MAX_SHOT_H = 6000   # px; reference and generated shots use the same cap


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

    async def _new_context(self, vp: Viewport, block: bool = True):
        assert self._browser is not None, "Renderer not started"
        context = await self._browser.new_context(
            viewport={"width": vp.width, "height": vp.height},
            device_scale_factor=1,
            ignore_https_errors=True,
            service_workers="block",
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
        page = await context.new_page()
        result = RenderedPage(url=url, final_url=url, title="", html="")

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
            resp = await page.goto(url, wait_until="load", timeout=settings.nav_timeout_ms)
            result.status_code = resp.status if resp else 0
            if result.status_code in (429, 503):
                ra = (resp.headers.get("retry-after") or "") if resp else ""
                result.retry_after = float(ra) if ra.strip().isdigit() else 0.0
                result.ok = False
                result.error = f"HTTP {result.status_code} (rate limited)"
                return result
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await self._settle(page)
            await self._fonts_ready(page)

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
            result.html = "<!DOCTYPE html>\n" + await page.evaluate(_SERIALIZE_JS)
            result.ok = True

            # Iframes/canvases (third-party embeds, maps, charts) cannot be
            # copied as code, so they are reproduced as pixel-exact images.
            for snap in prep.get("snaps", []):
                try:
                    loc = page.locator(f'[data-rx-snap="{snap["id"]}"]').first
                    result.snapshots[snap["id"]] = await loc.screenshot(type="png", timeout=6000)
                except Exception as exc:  # best effort
                    log.debug("snapshot %s#%s failed: %s", url, snap["id"], exc)

            # Screenshots + layout signatures per requested viewport.
            await self._freeze(page)
            for name in viewport_names:
                vp = self._vp(name)
                try:
                    await page.set_viewport_size({"width": vp.width, "height": vp.height})
                    await self._settle(page, scroll=True)
                    result.analysis.setdefault("vp_classes", {})[name] = await page.evaluate("() => [document.documentElement.className || '', document.body ? (document.body.className || '') : '']")
                    result.screenshots[name] = await self._shot(page, vp)
                    result.signatures[name] = await page.evaluate(SIGNATURE_JS)
                    result.analysis.setdefault("vp_styles", {})[name] = await page.evaluate(
                        STYLE_DIFF_JS, result.analysis.get("base_styles") or {})
                except Exception as exc:  # pragma: no cover - screenshot is best effort
                    log.warning("screenshot %s@%s failed: %s", url, name, exc)
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
        context = await self._new_context(vp, block=False)
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

    async def _shot(self, page, vp: Viewport) -> bytes:
        if not settings.low_memory:
            return await page.screenshot(full_page=True, type="png")
        height = await page.evaluate(
            "() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)")
        cap = max(vp.height, min(int(height or vp.height), _LOW_MEM_MAX_SHOT_H))
        return await page.screenshot(full_page=True, type="png",
                                     clip={"x": 0, "y": 0, "width": vp.width, "height": cap})

    async def _fonts_ready(self, page) -> None:
        try:
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
                " document.querySelectorAll('video').forEach(v => { try { v.pause(); v.currentTime = 0; } catch(e){} }); }",
                _FREEZE_CSS,
            )
        except Exception:
            pass

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
