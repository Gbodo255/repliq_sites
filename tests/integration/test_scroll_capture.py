"""Browser test: scroll-linked animations captured and replayed on a scroll timeline.

Opt-in (needs Chromium)::

    set RUN_BROWSER_TESTS=1 && python -m pytest tests/integration/test_scroll_capture.py -v
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

FIXTURE = (Path(__file__).resolve().parent.parent / "fixtures" / "scroll.html").as_uri()

_TY = "(id) => { const m = new DOMMatrix(getComputedStyle(document.getElementById(id)).transform); return m.m42; }"
_OP = "(id) => parseFloat(getComputedStyle(document.getElementById(id)).opacity)"
_TOP = "(id) => Math.round(document.getElementById(id).getBoundingClientRect().top)"


def test_scroll_linked_capture_and_replay():
    from app.core.aio import ensure_proactor_loop
    ensure_proactor_loop()

    from app.models.domain import ReplicationOptions
    from app.modules.asset_downloader.downloader import AssetStore
    from app.modules.browser.renderer import Renderer
    from app.modules.page_builder.builder import SiteBuilder

    async def run():
        out = Path(tempfile.mkdtemp(prefix="rxscroll_"))
        options = ReplicationOptions(max_pages=1, max_depth=0,
                                     viewport_names=["desktop"], fix_cycles=0,
                                     run_quality_check=False)
        async with Renderer() as r:
            page = await r.capture_page(FIXTURE, options.viewport_names)
            assert page.ok, page.error
            tracked = {}
            import re
            for m in re.finditer(r'<div id="(\w+)"[^>]*data-rx-s="(\d+)"', page.html):
                tracked[m.group(1)] = m.group(2)
            assert set(tracked) == {"para", "fade", "pin"}, tracked   # not 'once' nor 'hdr'

            builder = SiteBuilder(out, options)
            builder.plan([page], FIXTURE)
            async with AssetStore(out, options) as assets:
                await builder.download_assets([page], assets)
                records = builder.localize_and_write([page], assets)
                builder.write_support(assets, records, {"interactions": {}}, {"generated_at": 0})

            orig = await r._browser.new_context(viewport={"width": 1440, "height": 900})
            po = await orig.new_page()
            await po.goto(FIXTURE, wait_until="load")
            copy = await r._browser.new_context(viewport={"width": 1440, "height": 900})
            pc = await copy.new_page()
            await pc.goto((out / "index.html").resolve().as_uri(), wait_until="load")
            for y in (0, 450, 1000, 2200):
                for p in (po, pc):
                    await p.evaluate(f"() => window.scrollTo(0, {y})")
                    await p.wait_for_timeout(250)
                ty_o, ty_c = await po.evaluate(_TY, "para"), await pc.evaluate(_TY, "para")
                assert abs(ty_o - ty_c) < 0.3 * 225 + 2, (y, ty_o, ty_c)   # within one sample step
                op_o, op_c = await po.evaluate(_OP, "fade"), await pc.evaluate(_OP, "fade")
                assert abs(op_o - op_c) < 0.12, (y, op_o, op_c)
                top_o, top_c = await po.evaluate(_TOP, "pin"), await pc.evaluate(_TOP, "pin")
                assert abs(top_o - top_c) < 240, (y, top_o, top_c)
            await orig.close()
            await copy.close()

    asyncio.run(run())
