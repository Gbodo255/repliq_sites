"""Browser test: Lottie player, text effects and a rAF marquee, captured and replayed.

The fixture is served over HTTP (lottie-web loads its JSON with XHR); the copy is
opened from disk, where the replayed player must work without any fetch.

Opt-in (needs Chromium)::

    set RUN_BROWSER_TESTS=1 && python -m pytest tests/integration/test_players_capture.py -v
"""
import asyncio
import functools
import http.server
import os
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_BROWSER_TESTS"),
    reason="browser test; set RUN_BROWSER_TESTS=1 to enable",
)

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "players"
VENDOR = ROOT / "backend" / "app" / "static" / "vendor" / "lottie.min.js"


@pytest.fixture()
def site_url():
    srv_dir = Path(tempfile.mkdtemp(prefix="rxplayers_site_"))
    for f in FIXTURE_DIR.iterdir():
        shutil.copy(f, srv_dir / f.name)
    shutil.copy(VENDOR, srv_dir / "lottie.min.js")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv_dir))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    httpd.shutdown()


def test_players_text_and_marquee(site_url):
    from app.core.aio import ensure_proactor_loop
    ensure_proactor_loop()

    from app.models.domain import ReplicationOptions
    from app.modules.asset_downloader.downloader import AssetStore
    from app.modules.browser.renderer import Renderer
    from app.modules.page_builder.builder import SiteBuilder

    async def run():
        out = Path(tempfile.mkdtemp(prefix="rxplayers_"))
        options = ReplicationOptions(max_pages=1, max_depth=0, viewport_names=["desktop"],
                                     fix_cycles=0, run_quality_check=False)
        async with Renderer() as r:
            page = await r.capture_page(site_url, options.viewport_names)
            assert page.ok, page.error
            assert [m["i"] for m in page.analysis.get("lottie") or []] == [0], page.analysis.get("lottie")
            assert "lottie:0" in page.media
            kinds = sorted(fx["k"] for fx in page.analysis.get("text_fx") or [])
            assert kinds == ["count", "rotate", "type"], page.analysis.get("text_fx")
            count = next(fx for fx in page.analysis["text_fx"] if fx["k"] == "count")
            assert count["to"] == 120 and count["suf"] == "+", count
            typ = next(fx for fx in page.analysis["text_fx"] if fx["k"] == "type")
            assert set(typ["words"]) == {"apps", "sites"}, typ
            mq = page.analysis.get("marquee") or []
            assert len(mq) == 1 and mq[0]["ax"] == "x" and mq[0]["dir"] == -1, mq
            assert abs(mq[0]["speed"] - 60) < 15 and abs(mq[0]["len"] - 600) < 2, mq

            builder = SiteBuilder(out, options)
            builder.plan([page], site_url)
            async with AssetStore(out, options) as assets:
                await builder.download_assets([page], assets)
                records = builder.localize_and_write([page], assets)
                builder.write_support(assets, records, {"interactions": {}}, {"generated_at": 0})
            assert (out / "js" / "vendor" / "lottie.min.js").exists()
            assert not (out / "js" / "vendor" / "rive.js").exists()     # only what is needed

            ctx = await r._browser.new_context(viewport={"width": 1440, "height": 900})
            p = await ctx.new_page()
            await p.goto((out / "index.html").resolve().as_uri(), wait_until="load")
            await p.wait_for_timeout(800)
            # Lottie replayed by the vendored player (not the original script).
            assert await p.evaluate("() => !!window.lottie && !!document.querySelector('#lot svg')")
            sig = "() => [...document.querySelectorAll('#lot g')].map(g => g.getAttribute('transform')).join('|')"
            a = await p.evaluate(sig)
            await p.wait_for_timeout(300)
            assert a != await p.evaluate(sig), "lottie not animating"
            # Marquee moves.
            mx = "() => new DOMMatrix(getComputedStyle(document.getElementById('track')).transform).m41"
            x0 = await p.evaluate(mx)
            await p.wait_for_timeout(300)
            assert x0 != await p.evaluate(mx)
            # Count-up ends on the captured final value; typewriter & rotator change.
            await p.wait_for_timeout(1500)
            assert await p.evaluate("() => document.getElementById('count').textContent") == "120+"
            t1 = await p.evaluate("() => document.getElementById('type').textContent")
            r1 = await p.evaluate("() => document.getElementById('rot').textContent")
            await p.wait_for_timeout(700)
            assert t1 != await p.evaluate("() => document.getElementById('type').textContent")
            assert r1 != await p.evaluate("() => document.getElementById('rot').textContent")
            await ctx.close()

    asyncio.run(run())
