"""End-to-end pipeline test (opt-in, requires network).

Run with::

    set RUN_NETWORK_TESTS=1 && python -m pytest tests/integration -v
"""
import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_NETWORK_TESTS"),
    reason="network test; set RUN_NETWORK_TESTS=1 to enable",
)


def test_replicate_example_single_page():
    from app.core.aio import ensure_proactor_loop
    ensure_proactor_loop()

    from app.core.events import bus
    from app.models.schemas import ReplicationMode, ReplicationRequest
    from app.services.project_store import store
    from app.services.replication_service import manager

    async def run():
        detail = manager.start(
            ReplicationRequest(url="https://example.com", mode=ReplicationMode.single_page)
        )
        pid = detail["id"]
        async for ev in bus.channel(pid).subscribe(replay=True):
            if ev.phase == "done":
                break
        return store.get(pid)

    final = asyncio.run(run())
    assert final["status"] == "completed", final.get("error")
    assert final["pages_count"] >= 1
    site = store.site_dir(final["id"])
    assert (site / "index.html").exists()
    assert (site / "js" / "interactions.js").exists()
    assert (site / "data" / "pages-manifest.json").exists()
    assert store.zip_path(final["id"]).exists()
