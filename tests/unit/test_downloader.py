import asyncio

import httpx

from app.models.domain import ReplicationOptions
from app.modules.asset_downloader import downloader as dl
from app.modules.asset_downloader.downloader import AssetStore

CSS = "@font-face{font-family:X;src:url('/f.woff2')} .a{background:url('https://ex.com/img.png')}"


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("style.css"):
        return httpx.Response(200, headers={"content-type": "text/css"}, text=CSS)
    if url.endswith("f.woff2"):
        return httpx.Response(200, headers={"content-type": "font/woff2"}, content=b"FONTDATA")
    if url.endswith("img.png") or url.endswith("dup.png"):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"PNGDATA123")
    return httpx.Response(404)


def test_download_css_recursion_rewrite_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "is_safe_url", lambda u: True)

    async def run():
        store = AssetStore(tmp_path, ReplicationOptions())
        store._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), follow_redirects=False
        )
        try:
            css = await store.fetch("https://ex.com/style.css")
            dup = await store.fetch("https://ex.com/dup.png")
            return store, css, dup
        finally:
            await store._client.aclose()

    store, css, dup = asyncio.run(run())

    assert css.status == "ok" and css.category == "css"
    font = store.by_url.get("https://ex.com/f.woff2")
    img = store.by_url.get("https://ex.com/img.png")
    assert font and font.status == "ok" and font.category == "fonts"
    assert img and img.status == "ok" and img.category == "images"

    # The CSS file on disk was rewritten to local relative paths.
    css_text = (tmp_path / css.local_path).read_text(encoding="utf-8")
    assert "../fonts/" in css_text
    assert "../images/" in css_text

    # Identical bytes are deduped to the same local file.
    assert dup.local_path == img.local_path
    assert (tmp_path / img.local_path).exists()
