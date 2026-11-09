"""WebSocket endpoint streaming live job progress (owner-only)."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import bus
from app.core.logging import get_logger
from app.core.oauth import SESSION_COOKIE, load_session
from app.db.database import db
from app.services.project_store import store

log = get_logger("ws")
ws_router = APIRouter()


def _authorized(ws: WebSocket, job_id: str) -> bool:
    """The session cookie must belong to the owner of ``job_id``."""
    token = ws.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    uid = load_session(token)
    if not uid or not db.get_user(uid):
        return False
    return store.owns(job_id, uid)


@ws_router.websocket("/ws/jobs/{job_id}")
async def job_progress(ws: WebSocket, job_id: str) -> None:
    if not _authorized(ws, job_id):
        await ws.close(code=1008)
        return
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
