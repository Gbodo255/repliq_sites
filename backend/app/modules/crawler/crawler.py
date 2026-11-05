"""Site crawler.

Discovers and renders the public pages of a single site using several
complementary sources: the rendered links of already-visited pages, the
``sitemap.xml`` and the ``robots.txt``.  Scope is restricted to the seed site
and bounded by ``max_pages`` / ``max_depth`` for safety.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.core.security import is_safe_url
from app.core.utils import same_site
from app.models.domain import RenderedPage, ReplicationOptions
from app.modules.browser.renderer import Renderer

log = get_logger("crawler")

_NON_PAGE_EXT = re.compile(
    r"\.(pdf|zip|rar|7z|gz|tar|dmg|exe|msi|png|jpe?g|gif|webp|avif|svg|ico|"
    r"mp4|webm|mp3|wav|woff2?|ttf|otf|css|js|json|xml|rss|csv|docx?|xlsx?|pptx?)(\?|$)",
    re.I,
)
_MAX_RETRIES = 4
_COOLDOWN_S = 45
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "ftp:")


def canonicalize(url: str) -> str:
    url = urldefrag(url)[0]
    p = urlparse(url)
    scheme = p.scheme.lower()
    netloc = p.netloc.lower()
    if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc.rsplit(":", 1)[0]
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", p.query, ""))


def _is_crawlable(url: str, seed_host: str) -> bool:
    low = url.lower()
    if any(low.startswith(s) for s in _SKIP_SCHEMES):
        return False
    if not url.startswith(("http://", "https://")):
        return False
    if _NON_PAGE_EXT.search(url):
        return False
    if not same_site(urlparse(url).hostname, seed_host):
        return False
    return is_safe_url(url)


async def _discover_sitemap(seed: str, seed_host: str) -> list[str]:
    """Return same-site page URLs from robots.txt + sitemap.xml (best effort)."""
    base = f"{urlparse(seed).scheme}://{urlparse(seed).netloc}"
    found: list[str] = []
    candidates = [urljoin(base, "/sitemap.xml")]
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        # robots.txt -> Sitemap: lines
        try:
            r = await client.get(urljoin(base, "/robots.txt"))
            if r.status_code < 400:
                for line in r.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        candidates.append(line.split(":", 1)[1].strip())
        except Exception:
            pass
        seen_maps: set[str] = set()
        queue = list(dict.fromkeys(candidates))
        while queue and len(seen_maps) < 8:
            sm = queue.pop(0)
            if sm in seen_maps or not is_safe_url(sm):
                continue
            seen_maps.add(sm)
            try:
                r = await client.get(sm)
                if r.status_code >= 400:
                    continue
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text, re.I)
                for loc in locs:
                    loc = loc.strip()
                    if loc.lower().endswith(".xml"):
                        queue.append(loc)           # nested sitemap index
                    elif _is_crawlable(loc, seed_host):
                        found.append(canonicalize(loc))
            except Exception:
                continue
    # Preserve order, dedupe.
    return list(dict.fromkeys(found))


async def crawl(
    renderer: Renderer,
    seed_url: str,
    options: ReplicationOptions,
    emit=lambda **k: None,
) -> list[RenderedPage]:
    seed = canonicalize(seed_url)
    seed_host = urlparse(seed).hostname or ""
    max_pages = max(1, options.max_pages)
    max_depth = 0 if options.mode == "single_page" else max(0, options.max_depth)

    visited: set[str] = set()
    frontier: list[tuple[str, int]] = [(seed, 0)]
    rendered: list[RenderedPage] = []

    # Sitemap URLs (depth 1) are queued *after* the seed: the seed is rendered
    # alone first so it never competes with other pages for the server's quota.
    sitemap_urls: list[tuple[str, int]] = []
    if max_depth > 0 and options.mode != "single_page":
        emit(phase="crawl", message="Reading sitemap.xml / robots.txt", progress=3)
        for u in await _discover_sitemap(seed, seed_host):
            if u != seed:
                sitemap_urls.append((u, 1))

    sem = asyncio.Semaphore(max(1, settings.page_concurrency))
    polite = {"throttled": False, "delay": 0.0}
    serial = asyncio.Lock()

    async def _capture(url: str) -> RenderedPage:
        if polite["throttled"]:
            async with serial:                      # one page at a time once rate-limited
                await asyncio.sleep(polite["delay"])
                return await renderer.capture_page(url, options.viewport_names)
        return await renderer.capture_page(url, options.viewport_names)

    async def render_one(url: str, depth: int) -> RenderedPage:
        async with sem:
            emit(phase="crawl", message=f"Rendering {url}",
                 data={"url": url, "depth": depth})
            page = await _capture(url)
            # The seed is essential (no seed, no copy): give it more patience.
            retries = _MAX_RETRIES * 2 if depth == 0 else _MAX_RETRIES
            cap = 60.0 if depth == 0 else 30.0
            for attempt in range(retries):
                transient = (page.status_code in (429, 503) or page.status_code >= 500
                             or (page.ok and page.throttled_resources > 0))
                if not transient:
                    break
                polite["throttled"] = True
                polite["delay"] = min(10.0, max(polite["delay"] * 2, 2.0))
                wait = min(cap, max(page.retry_after, polite["delay"] * (attempt + 1)))
                why = (f"HTTP {page.status_code}" if page.status_code >= 400
                       else f"{page.throttled_resources} resource(s) refused")
                emit(phase="crawl", level="warn",
                     message=f"Server is rate limiting ({why}) - retrying {url} in {wait:.0f}s",
                     data={"url": url, "attempt": attempt + 1})
                await asyncio.sleep(wait)
                page = await _capture(url)
            if page.status_code >= 400 and page.ok and depth > 0:
                page.ok = False
                page.error = f"HTTP {page.status_code}"
            if page.status_code >= 400 and not page.ok:
                emit(phase="crawl", level="warn",
                     message=f"Skipped {url}: {page.error or 'HTTP ' + str(page.status_code)}",
                     data={"url": url})
            return page

    # BFS, one depth level at a time so concurrency stays bounded and ordered.
    while frontier and len(visited) < max_pages:
        # Take a batch of not-yet-visited URLs at the current frontier.
        batch: list[tuple[str, int]] = []
        for url, depth in frontier:
            cu = canonicalize(url)
            if cu in visited or cu in {canonicalize(b[0]) for b in batch}:
                continue
            batch.append((cu, depth))
            if len(visited) + len(batch) >= max_pages:
                break
        frontier = [f for f in frontier if canonicalize(f[0]) not in {canonicalize(b[0]) for b in batch}]
        if not batch:
            break

        for cu, depth in batch:
            visited.add(cu)

        pages = await asyncio.gather(*(render_one(u, d) for u, d in batch))
        next_frontier: list[tuple[str, int]] = []
        for page, (cu, depth) in zip(pages, batch):
            rendered.append(page)
            pct = 5 + int(45 * len(visited) / max_pages)
            emit(phase="crawl",
                 message=(f"Captured {page.title or cu} ({len(visited)}/{max_pages})" if page.ok
                          else f"Could not capture {cu}: {page.error}"),
                 progress=min(pct, 50),
                 data={"url": cu, "ok": page.ok, "links": len(page.links)})
            if depth < max_depth and page.ok:
                for link in page.links:
                    lc = canonicalize(link)
                    if lc not in visited and _is_crawlable(lc, seed_host):
                        next_frontier.append((lc, depth + 1))
        frontier = next_frontier + sitemap_urls
        sitemap_urls = []

    # Second chance for pages refused by rate limiting: cool down, then retry
    # one page at a time so the copy is complete and its reference screenshots
    # are not degraded by refused stylesheets/images.
    retry_idx = [i for i, p in enumerate(rendered)
                 if p.status_code in (429, 503) or (p.ok and p.throttled_resources > 0)]
    if retry_idx:
        emit(phase="crawl", level="warn",
             message=f"Cooling down {_COOLDOWN_S}s before retrying {len(retry_idx)} rate-limited page(s)")
        await asyncio.sleep(_COOLDOWN_S)
        for i in retry_idx:
            url = rendered[i].url
            emit(phase="crawl", message=f"Retrying {url}", data={"url": url})
            again = await renderer.capture_page(url, options.viewport_names)
            prev = rendered[i]
            better = (again.ok and again.status_code < 400) and (
                not prev.ok or prev.status_code >= 400
                or again.throttled_resources < prev.throttled_resources)
            if better:
                rendered[i] = again
            await asyncio.sleep(3)
        for p in rendered:
            if p.status_code >= 400 and p.ok:
                p.ok = False
                p.error = f"HTTP {p.status_code}"

    still = sum(1 for p in rendered if p.ok and p.throttled_resources > 0)
    if still:
        emit(phase="crawl", level="warn",
             message=f"{still} page(s) captured while the server still refused some resources")
    log.info("crawl finished: %d pages", len(rendered))
    return rendered
