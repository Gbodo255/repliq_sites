"""Import the *content database* of a WordPress source site.

When the replicated site runs on WordPress, its public REST API exposes the
posts, categories and tags.  They are downloaded (with every image they use,
localised through the regular :class:`AssetStore`) so the generated WordPress
theme / headless project can re-create them in the target database.

Only public data is read; nothing behind authentication is accessed.
"""
from __future__ import annotations

import posixpath
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.core.security import is_safe_url
from app.core.utils import same_site
from app.modules.asset_downloader.downloader import AssetStore
from app.modules.sanitizer.external import purge_soup

log = get_logger("wp_source")

_MAX_POSTS = 200
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ReplicationEngine/1.0",
            "Accept": "application/json"}


def _api(base: str, route: str, **params) -> str:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}/?rest_route={route}" + (f"&{q}" if q else "")


async def _get_json(client: httpx.AsyncClient, url: str):
    if not is_safe_url(url):
        return None, {}
    try:
        r = await client.get(url)
        if r.status_code >= 400:
            return None, {}
        return r.json(), r.headers
    except (httpx.HTTPError, ValueError):
        return None, {}


async def fetch_wordpress_content(seed_url: str, store: AssetStore, page_map: dict[str, str],
                                  emit=lambda **k: None) -> dict | None:
    """Return ``{"posts": [...], "categories": [...], "tags": [...]}`` or ``None``.

    ``page_map`` maps canonical source URLs to page keys so links inside posts
    that target captured pages become ``{{P:key}}`` tokens.
    """
    p = urlparse(seed_url)
    base = f"{p.scheme}://{p.netloc}"
    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        probe, _ = await _get_json(client, _api(base, "/"))
        if not isinstance(probe, dict) or "namespaces" not in probe:
            return None
        if "wp/v2" not in probe.get("namespaces", []):
            return None
        emit(phase="content", message="WordPress detected: importing posts, categories and tags")

        cats, _ = await _get_json(client, _api(base, "/wp/v2/categories", per_page=100))
        tags, _ = await _get_json(client, _api(base, "/wp/v2/tags", per_page=100))
        posts: list[dict] = []
        page = 1
        while len(posts) < _MAX_POSTS:
            batch, headers = await _get_json(client, _api(base, "/wp/v2/posts", per_page=50, page=page, _embed=1))
            if not isinstance(batch, list) or not batch:
                break
            posts.extend(batch)
            total_pages = int(headers.get("x-wp-totalpages", "1") or 1)
            if page >= total_pages:
                break
            page += 1

    out_posts = []
    slugs = {x.get("slug") for x in posts if isinstance(x, dict)}
    for post in posts[:_MAX_POSTS]:
        if not isinstance(post, dict):
            continue
        html = (post.get("content") or {}).get("rendered", "")
        excerpt = (post.get("excerpt") or {}).get("rendered", "")
        content = await _localize(html, base, store, page_map, slugs)
        featured = ""
        try:
            media = (post.get("_embedded") or {}).get("wp:featuredmedia") or []
            src = media[0].get("source_url") if media else ""
            if src:
                rec = await store.fetch(src, source_page=post.get("link", ""))
                if rec and rec.status == "ok":
                    featured = "{{A}}/" + rec.local_path
        except (AttributeError, IndexError, TypeError):
            pass
        out_posts.append({
            "slug": post.get("slug", ""),
            "title": BeautifulSoup((post.get("title") or {}).get("rendered", ""), "html.parser").get_text(),
            "date": post.get("date", ""),
            "content": content,
            "excerpt": BeautifulSoup(excerpt, "html.parser").get_text(" ", strip=True),
            "categories": post.get("categories", []),
            "tags": post.get("tags", []),
            "featured": featured,
        })
    simple = lambda items: [{"id": t.get("id"), "name": t.get("name"), "slug": t.get("slug"),
                             "description": t.get("description", "")}
                            for t in (items or []) if isinstance(t, dict)]
    log.info("WordPress content: %d posts", len(out_posts))
    emit(phase="content", message=f"Imported {len(out_posts)} post(s) from the WordPress database")
    return {"posts": out_posts, "categories": simple(cats), "tags": simple(tags)}


async def _localize(html: str, base: str, store: AssetStore, page_map: dict[str, str], post_slugs: set) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    host = urlparse(base).hostname
    for img in soup.find_all(["img", "source"]):
        for attr in ("src", "data-src"):
            u = img.get(attr)
            if u:
                rec = await store.fetch(urljoin(base + "/", u))
                if rec and rec.status == "ok":
                    img["src" if attr == "data-src" else attr] = "{{A}}/" + rec.local_path
        for attr in ("srcset", "data-srcset"):
            if img.get(attr):
                parts = []
                for part in img[attr].split(","):
                    bits = part.strip().split()
                    if not bits:
                        continue
                    rec = await store.fetch(urljoin(base + "/", bits[0]))
                    if rec and rec.status == "ok":
                        bits[0] = "{{A}}/" + rec.local_path
                        parts.append(" ".join(bits))
                if parts:
                    img["srcset"] = ", ".join(parts)
                else:
                    del img[attr]
        img.attrs.pop("data-srcset", None) if img.get("srcset") else None
    for a in soup.find_all("a", href=True):
        u = urljoin(base + "/", a["href"])
        pu = urlparse(u)
        if not same_site(pu.hostname, host):
            continue
        from app.modules.crawler.crawler import canonicalize
        key = page_map.get(canonicalize(u))
        if key is not None:
            a["href"] = "{{P:" + key + "}}"
            continue
        last = posixpath.basename(pu.path.rstrip("/"))
        if last in post_slugs:
            a["href"] = "{{POST:" + last + "}}"
            continue
        rec = None
        if re.search(r"\.(jpe?g|png|gif|webp|avif|svg|pdf)$", pu.path, re.I):
            rec = await store.fetch(u)
        if rec and rec.status == "ok":
            a["href"] = "{{A}}/" + rec.local_path
    purge_soup(soup)
    return str(soup)
