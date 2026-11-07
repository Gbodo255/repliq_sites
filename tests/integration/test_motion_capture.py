"""Browser test: capture + replay of animations and behaviour (offline).

Renders a local fixture (``file://``, no network), rebuilds the offline copy and
checks that it actually animates: scroll-reveal elements start hidden and reveal
on scroll, the sticky header gains its captured class, and the carousel advances.

Opt-in (needs Chromium)::

    set RUN_BROWSER_TESTS=1 && python -m pytest tests/integration/test_motion_capture.py -v
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

FIXTURE = (Path(__file__).resolve().parent.parent / "fixtures" / "motion.html").as_uri()


def test_motion_capture_and_replay():
    from app.core.aio import ensure_proactor_loop
    ensure_proactor_loop()

    from app.models.domain import ReplicationOptions
    from app.modules.asset_downloader.downloader import AssetStore
    from app.modules.browser.renderer import Renderer
    from app.modules.page_builder.builder import SiteBuilder

    async def run():
        out = Path(tempfile.mkdtemp(prefix="rxmotion_"))
        options = ReplicationOptions(max_pages=1, max_depth=0,
                                     viewport_names=["desktop"], fix_cycles=0,
                                     run_quality_check=False)
        async with Renderer() as r:
            page = await r.capture_page(FIXTURE, options.viewport_names)
            assert page.ok, page.error
            # Scroll-reveals detected by effect, sticky-header class captured.
            assert page.analysis.get("reveal"), "no scroll-reveal captured"
            rows = (page.analysis.get("scroll_state") or {}).get("rows") or []
            assert any("scrolled" in row[1] for row in rows), rows

            builder = SiteBuilder(out, options)
            builder.plan([page], FIXTURE)
            async with AssetStore(out, options) as assets:
                await builder.download_assets([page], assets)
                records = builder.localize_and_write([page], assets)
                builder.write_support(assets, records, {"interactions": {}}, {"generated_at": 0})

            copy_uri = (out / "index.html").resolve().as_uri()
            ctx = await r._browser.new_context(viewport={"width": 1440, "height": 900})
            p = await ctx.new_page()
            await p.goto(copy_uri, wait_until="load")
            await p.wait_for_timeout(400)

            last_op = ("() => { const e=[...document.querySelectorAll('.reveal[data-rx-reveal-i]')];"
                       " return parseFloat(getComputedStyle(e[e.length-1]).opacity); }")
            op0 = await p.evaluate(last_op)
            assert op0 < 0.2, f"reveal not hidden initially (opacity={op0})"

            await p.evaluate(
                "() => { const e=[...document.querySelectorAll('.reveal[data-rx-reveal-i]')];"
                " e[e.length-1].scrollIntoView({block:'center'}); }")
            await p.wait_for_timeout(900)
            op1 = await p.evaluate(last_op)
            assert op1 > 0.9, "reveal did not reveal on scroll"

            assert await p.evaluate(
                "() => document.getElementById('masthead').classList.contains('scrolled')")

            t0 = await p.evaluate("() => document.querySelector('.swiper-wrapper').style.transform || ''")
            await p.evaluate("() => { const b=document.querySelector('.swiper-button-next'); b && b.click(); }")
            await p.wait_for_timeout(200)
            t1 = await p.evaluate("() => document.querySelector('.swiper-wrapper').style.transform || ''")
            assert t0 != t1 and "-" in t1, f"carousel did not advance ({t0!r}->{t1!r})"

            await p.evaluate("() => window.ReplicatorInteractions.freeze()")
            await p.wait_for_timeout(50)
            assert await p.evaluate(
                "() => [...document.querySelectorAll('.reveal[data-rx-reveal-i]')]"
                ".every(el => parseFloat(getComputedStyle(el).opacity) > 0.9)")
            await ctx.close()

    asyncio.run(run())
