"""Browser test: Web Animations + JS hover states captured and replayed as CSS.

Opt-in (needs Chromium)::

    set RUN_BROWSER_TESTS=1 && python -m pytest tests/integration/test_waapi_capture.py -v
"""
import asyncio
import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_BROWSER_TESTS"),
    reason="browser test; set RUN_BROWSER_TESTS=1 to enable",
)

FIXTURE = (Path(__file__).resolve().parent.parent / "fixtures" / "waapi.html").as_uri()


def test_waapi_and_hover_capture_and_replay():
    from app.core.aio import ensure_proactor_loop
    ensure_proactor_loop()

    from app.models.domain import ReplicationOptions
    from app.modules.asset_downloader.downloader import AssetStore
    from app.modules.browser.renderer import Renderer
    from app.modules.page_builder.builder import SiteBuilder

    async def run():
        out = Path(tempfile.mkdtemp(prefix="rxwaapi_"))
        options = ReplicationOptions(max_pages=1, max_depth=0,
                                     viewport_names=["desktop"], fix_cycles=0,
                                     run_quality_check=False)
        async with Renderer() as r:
            page = await r.capture_page(FIXTURE, options.viewport_names)
            assert page.ok, page.error
            anims = page.analysis.get("anims") or []
            triggers = sorted(e["t"] for e in anims)
            assert triggers == ["load", "load", "view"], anims
            assert any(a["it"] == -1 for e in anims for a in e["a"]), "loop not captured"
            hover = page.analysis.get("hover") or []
            assert hover, "JS hover not captured"
            paths = {row["p"] for e in hover for row in e["r"]}
            assert "" in paths and "div:nth-of-type(1)" in paths, hover

            builder = SiteBuilder(out, options)
            builder.plan([page], FIXTURE)
            async with AssetStore(out, options) as assets:
                await builder.download_assets([page], assets)
                records = builder.localize_and_write([page], assets)
                builder.write_support(assets, records, {"interactions": {}}, {"generated_at": 0})

            html = (out / "index.html").read_text(encoding="utf-8")
            assert '<style id="rx-motion">' in html
            copy_uri = (out / "index.html").resolve().as_uri()
            ctx = await r._browser.new_context(viewport={"width": 1440, "height": 900})
            p = await ctx.new_page()
            await p.goto(copy_uri, wait_until="load")

            names = await p.evaluate(
                "() => document.getAnimations().map(a => a.animationName).filter(Boolean)")
            assert any(n.startswith("rxa") for n in names), names
            # The in-view animation waits paused until scrolled to.
            st = await p.evaluate(
                "() => getComputedStyle(document.getElementById('late')).animationPlayState")
            assert st == "paused", st
            await p.evaluate("() => document.getElementById('late').scrollIntoView({block:'center'})")
            await p.wait_for_timeout(300)
            st = await p.evaluate(
                "() => getComputedStyle(document.getElementById('late')).animationPlayState")
            assert st == "running", st

            # Hover reproduced by CSS alone.
            await p.evaluate("() => window.scrollTo(0, 0)")
            box = await p.locator("#card").bounding_box()
            await p.mouse.move(box["x"] + 20, box["y"] + 20)
            await p.wait_for_timeout(400)
            bg = await p.evaluate("() => getComputedStyle(document.getElementById('card')).backgroundColor")
            fg = await p.evaluate("() => getComputedStyle(document.querySelector('#card .label')).color")
            assert bg == "rgb(35, 55, 255)", bg
            assert fg == "rgb(255, 255, 255)", fg
            await ctx.close()

    asyncio.run(run())
