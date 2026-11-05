"""Asset download + localisation.

``AssetStore`` owns the ``assets/`` tree of a single project.  Given an
absolute URL it downloads the resource once (deduped by URL and by content
hash), stores it under the right category folder, and hands back the local
relative path.  CSS files are parsed recursively so that fonts and
background-images they reference are downloaded too, and the stylesheet text is
rewritten to point at the local copies.
"""
from __future__ import annotations

import asyncio
import json
import posixpath
import time
from pathlib import Path

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.core.security import is_safe_url
from app.core.utils import (
    categorize,
    content_type_ext,
    ext_from_url,
    safe_filename,
    sha1_bytes,
    short_hash,
)
from app.models.domain import AssetRecord, ReplicationOptions
from app.modules.css_analyzer.css_tools import extract_css_urls, rewrite_css_urls

log = get_logger("assets")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


class AssetCache:
    """Cross-project HTTP cache for assets (keyed by URL, TTL-bounded).

    Re-running a replication, or replicating several sites that share CDNs
    (fonts, libraries), then costs no network round-trip for known assets.
    """

    def __init__(self, base: Path | None = None, ttl_hours: int | None = None) -> None:
        self.base = base or settings.cache_dir / "assets"
        self.ttl = (ttl_hours if ttl_hours is not None else settings.cache_ttl_hours) * 3600
        self.hits = 0

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = sha1_bytes(url.encode("utf-8", "ignore"))
        d = self.base / key[:2]
        return d / f"{key}.bin", d / f"{key}.json"

    def get(self, url: str) -> tuple[bytes, str] | None:
        if self.ttl <= 0:
            return None
        data_p, meta_p = self._paths(url)
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            if time.time() - meta.get("ts", 0) > self.ttl:
                return None
            data = data_p.read_bytes()
        except (OSError, ValueError):
            return None
        self.hits += 1
        return data, meta.get("content_type", "")

    def put(self, url: str, data: bytes, content_type: str) -> None:
        if self.ttl <= 0:
            return
        data_p, meta_p = self._paths(url)
        try:
            data_p.parent.mkdir(parents=True, exist_ok=True)
            data_p.write_bytes(data)
            meta_p.write_text(json.dumps({"url": url, "content_type": content_type,
                                          "ts": time.time()}), encoding="utf-8")
        except OSError:
            pass


class AssetStore:
    def __init__(self, output_root: Path, options: ReplicationOptions, emit=lambda **k: None) -> None:
        self.root = output_root
        self.options = options
        self.emit = emit
        self.by_url: dict[str, AssetRecord] = {}
        self.by_hash: dict[str, str] = {}          # content hash -> rel path
        self.used_paths: set[str] = set()
        self.total_bytes = 0
        self._inflight: dict[str, asyncio.Future] = {}
        self._sem = asyncio.Semaphore(max(1, settings.asset_concurrency))
        self._client: httpx.AsyncClient | None = None
        self.cache = AssetCache()

    async def __aenter__(self) -> "AssetStore":
        self._client = httpx.AsyncClient(
            headers=_HEADERS, timeout=httpx.Timeout(25.0), follow_redirects=False
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------ public
    def manifest(self) -> list[dict]:
        return [r.to_dict() for r in self.by_url.values()]

    def ok_assets(self) -> list[AssetRecord]:
        return [r for r in self.by_url.values() if r.status == "ok"]

    async def fetch(self, url: str, source_page: str = "") -> AssetRecord | None:
        if url in self.by_url:
            return self.by_url[url]
        if url in self._inflight:
            return await self._inflight[url]
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[url] = fut
        try:
            rec = await self._do_fetch(url, source_page)
            fut.set_result(rec)
            return rec
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("fetch error %s: %s", url, exc)
            rec = AssetRecord(url=url, status="error", error=str(exc), source_page=source_page)
            self.by_url[url] = rec
            fut.set_result(rec)
            return rec
        finally:
            self._inflight.pop(url, None)

    def add_generated(self, key: str, data: bytes, filename: str, category: str = "images") -> AssetRecord:
        """Register an asset produced by the engine itself (not downloaded)."""
        ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        rel = self._assign_path(filename, category, ext)
        abs_path = self.root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)
        rec = AssetRecord(url=key, category=category, ext=ext, local_path=rel, status="ok",
                          size=len(data), content_type="image/png", content_hash=sha1_bytes(data))
        self.by_url[key] = rec
        self.total_bytes += len(data)
        return rec

    # ------------------------------------------------------------- internals
    def _assign_path(self, url: str, category: str, ext: str) -> str:
        name = safe_filename(posixpath.basename(url.split("?")[0]))
        stem, dot, cur_ext = name.rpartition(".")
        if not dot:
            stem, cur_ext = name, ""
        if not stem:
            stem = short_hash(url, 10)
        final_ext = ext or ("." + cur_ext if cur_ext else "")
        rel = f"assets/{category}/{stem}{final_ext}"
        if rel in self.used_paths:
            rel = f"assets/{category}/{stem}-{short_hash(url, 6)}{final_ext}"
        self.used_paths.add(rel)
        return rel

    async def _download(self, url: str) -> tuple[bytes | None, str, str]:
        """Return (bytes, content_type, error).  Follows redirects with SSRF checks."""
        assert self._client is not None
        cached = self.cache.get(url)
        if cached is not None:
            return cached[0], cached[1], ""
        data, ctype, err = await self._download_network(url)
        if data is not None:
            self.cache.put(url, data, ctype)
        return data, ctype, err

    async def _download_network(self, url: str) -> tuple[bytes | None, str, str]:
        """Return (bytes, content_type, error).  Follows redirects with SSRF checks
        and backs off politely when the server rate-limits (429/503)."""
        assert self._client is not None
        current = url
        hops = 0
        throttle_tries = 0
        while hops < 6:
            if not is_safe_url(current):
                return None, "", "blocked (unsafe host)"
            retry_wait = 0.0
            async with self._sem:
                try:
                    async with self._client.stream("GET", current) as resp:
                        if resp.status_code in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("location")
                            if not loc:
                                return None, "", f"redirect without location ({resp.status_code})"
                            current = str(httpx.URL(current).join(loc))
                            hops += 1
                            continue
                        if resp.status_code in (429, 503) and throttle_tries < 4:
                            ra = resp.headers.get("retry-after") or ""
                            retry_wait = min(30.0, float(ra) if ra.strip().isdigit() else 2.0 * (2 ** throttle_tries))
                            throttle_tries += 1
                        elif resp.status_code >= 400:
                            return None, "", f"HTTP {resp.status_code}"
                        else:
                            ctype = resp.headers.get("content-type", "")
                            clen = resp.headers.get("content-length")
                            if clen and clen.isdigit() and int(clen) > settings.max_asset_bytes:
                                return None, ctype, "too large (content-length)"
                            chunks, size = [], 0
                            async for chunk in resp.aiter_bytes():
                                size += len(chunk)
                                if size > settings.max_asset_bytes:
                                    return None, ctype, "too large"
                                chunks.append(chunk)
                            return b"".join(chunks), ctype, ""
                except (httpx.HTTPError, OSError) as exc:
                    return None, "", str(exc)
            await asyncio.sleep(retry_wait)
        return None, "", "too many redirects"

    async def _do_fetch(self, url: str, source_page: str) -> AssetRecord:
        rec = AssetRecord(url=url, source_page=source_page)
        if not is_safe_url(url):
            rec.status = "skipped"
            rec.error = "unsafe/blocked host"
            self.by_url[url] = rec
            return rec
        if self.total_bytes >= settings.max_total_bytes:
            rec.status = "skipped"
            rec.error = "total budget exceeded"
            self.by_url[url] = rec
            return rec

        data, ctype, err = await self._download(url)
        if data is None:
            rec.status = "error" if err and "too large" not in err else "skipped"
            rec.error = err
            self.by_url[url] = rec
            return rec

        ext = ext_from_url(url) or content_type_ext(ctype) or ""
        category = categorize(ext, ctype)
        is_css = category == "css" or ctype.split(";")[0].strip() == "text/css"
        rec.content_type = ctype
        rec.ext = ext
        rec.category = category
        rec.size = len(data)

        # Dedupe non-CSS assets by content hash.
        digest = sha1_bytes(data)
        rec.content_hash = digest
        if not is_css and digest in self.by_hash:
            rec.local_path = self.by_hash[digest]
            rec.status = "ok"
            self.by_url[url] = rec
            return rec

        rel = self._assign_path(url, category, ext)
        rec.local_path = rel
        # Register before recursing so cyclic @imports terminate.
        self.by_url[url] = rec
        abs_path = self.root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        if is_css:
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = data.decode("latin-1", errors="replace")
            nested = extract_css_urls(text, url)
            mapping: dict[str, str] = {}
            for nurl in nested:
                child = await self.fetch(nurl, source_page=url)
                if child and child.status == "ok" and child.local_path:
                    rel_to_child = posixpath.relpath(
                        child.local_path, posixpath.dirname(rel)
                    )
                    mapping[nurl] = rel_to_child
            rewritten = rewrite_css_urls(text, url, lambda u: mapping.get(u))
            abs_path.write_text(rewritten, encoding="utf-8")
            rec.size = len(rewritten.encode("utf-8"))
        else:
            abs_path.write_bytes(data)
            self.by_hash[digest] = rel

        rec.status = "ok"
        self.total_bytes += rec.size
        self.emit(
            phase="assets",
            message=f"Downloaded {rel}",
            data={"url": url, "path": rel, "size": rec.size, "category": category},
        )
        return rec
