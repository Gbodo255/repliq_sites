"""Standalone command-line replication (no server required).

Drives the exact same in-process pipeline the API uses and prints live
progress.  Example::

    python replicate_cli.py https://example.com --mode auto
    python replicate_cli.py https://example.com --mode full --pages 20
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.aio import ensure_proactor_loop

ensure_proactor_loop()

from app.core.events import bus  # noqa: E402
from app.core.security import UnsafeUrlError  # noqa: E402
from app.models.schemas import ReplicationMode, ReplicationRequest  # noqa: E402
from app.services.project_store import store  # noqa: E402
from app.services.replication_service import manager  # noqa: E402


async def _run(args) -> int:
    try:
        req = ReplicationRequest(
            url=args.url,
            name=args.name,
            mode=ReplicationMode(args.mode),
            max_pages=args.pages,
            max_depth=args.depth,
            fix_cycles=args.fix_cycles,
            keep_js=args.keep_js,
            run_quality_check=not args.no_quality,
            outputs=args.outputs,
            keep_external_links=args.keep_external_links,
        )
        detail = manager.start(req)
    except UnsafeUrlError as exc:
        print(f"[error] {exc}")
        return 2

    pid = detail["id"]
    print(f"Project {pid} -> {detail['url']}")
    last = -1
    async for ev in bus.channel(pid).subscribe(replay=True):
        pct = int(ev.progress)
        bar = f"{pct:3d}%" if pct != last else "    "
        last = pct
        tag = {"error": "ERR", "warn": "WRN", "success": "OK "}.get(ev.level, "   ")
        print(f"[{tag}] {bar} {ev.phase:<8} {ev.message}")
        if ev.phase == "done":
            break

    final = store.get(pid) or {}
    print("-" * 60)
    print(f"Status      : {final.get('status')}")
    print(f"Pages       : {final.get('pages_count')}")
    print(f"Assets      : {final.get('assets_count')} "
          f"({(final.get('assets_bytes') or 0) / 1024 / 1024:.1f} MB)")
    if final.get("avg_ssim") is not None:
        print(f"Avg SSIM    : {final.get('avg_ssim')}")
    print(f"Output site : {store.site_dir(pid) / 'index.html'}")
    print(f"ZIP export  : {store.zip_path(pid)}")
    q = final.get("quality") or {}
    if q:
        print(f"Fidelity    : {q.get('overall_score')} (grade {q.get('grade')}), "
              f"external refs remaining: {q.get('external_refs_remaining')}")
    for e in final.get("exports", []):
        status = e.get("error") or str(store.export_file(pid, e["target"]))
        print(f"Output      : {e['label']:<30} {status}")
    if final.get("error"):
        print(f"Error       : {final.get('error')}")
    return 0 if final.get("status") == "completed" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Replicate a website locally.")
    ap.add_argument("url")
    ap.add_argument("--name", default=None)
    ap.add_argument("--mode", default="auto", choices=["auto", "full", "single_page"])
    ap.add_argument("--pages", type=int, default=None)
    ap.add_argument("--depth", type=int, default=None)
    ap.add_argument("--fix-cycles", dest="fix_cycles", type=int, default=None)
    ap.add_argument("--keep-js", dest="keep_js", action="store_true", default=None)
    ap.add_argument("--no-quality", dest="no_quality", action="store_true")
    ap.add_argument("--output", dest="outputs", action="append",
                    choices=["static", "react", "nextjs", "wordpress_theme", "wordpress_headless"],
                    help="Output format (repeatable). Default: static")
    ap.add_argument("--keep-external-links", dest="keep_external_links", action="store_true", default=None)
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
