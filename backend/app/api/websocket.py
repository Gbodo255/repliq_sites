"""WebSocket endpoint streaming live job progress."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import bus
from app.core.logging import get_logger

log = get_logger("ws")
ws_router = APIRouter()


@ws_router.websocket("/ws/jobs/{job_id}")
async def job_progress(ws: WebSocket, job_id: str) -> None:
    await ws.accept()
    channel = bus.channel(job_id)
    try:
        async for event in channel.subscribe(replay=True):
            await ws.send_json(event.to_dict())
            if event.phase == "done":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - transport errors
        log.debug("ws %s closed: %s", job_id, exc)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
