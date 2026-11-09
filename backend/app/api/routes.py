"""REST API routes (all gated behind a signed-in Google account)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from app.core.oauth import current_user
from app.core.security import UnsafeUrlError
from app.models.schemas import JobAccepted, OutputsRequest, ReplicationRequest
from app.modules.targets import TARGETS
from app.services.project_store import store
from app.services.replication_service import manager

router = APIRouter(prefix="/api")

_MEDIA = {
    ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".avif": "image/avif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".otf": "font/otf", ".mp4": "video/mp4", ".webm": "video/webm", ".md": "text/markdown",
}


def _safe_file(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(400, "Invalid path")
    if not target.is_file():
        raise HTTPException(404, "Not found")
    return target


def _owned(pid: str, user: dict) -> dict:
    """Return the project detail if it belongs to ``user``, else 404."""
    detail = store.get(pid)
    if not detail or detail.get("user_id", "") != user["id"]:
        raise HTTPException(404, "Project not found")
    return detail


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/replicate", response_model=JobAccepted)
async def replicate(req: ReplicationRequest, user: dict = Depends(current_user)):
    try:
        detail = manager.start(req, user_id=user["id"])
    except UnsafeUrlError as exc:
        raise HTTPException(400, str(exc))
    return JobAccepted(job_id=detail["id"], project_id=detail["id"], status="running")


@router.get("/dashboard")
async def dashboard(user: dict = Depends(current_user)):
    stats = store.dashboard(user["id"])
    stats["recent"] = store.list(limit=8, user_id=user["id"])
    return stats


@router.get("/projects")
async def list_projects(limit: int = 100, user: dict = Depends(current_user)):
    return store.list(limit=limit, user_id=user["id"])


@router.get("/projects/{pid}")
async def get_project(pid: str, user: dict = Depends(current_user)):
    detail = _owned(pid, user)
    detail["is_running"] = manager.is_running(pid)
    return detail


@router.post("/projects/{pid}/cancel")
async def cancel_project(pid: str, user: dict = Depends(current_user)):
    _owned(pid, user)
    cancelled = manager.cancel(pid)
    return {"cancelled": cancelled}


@router.delete("/projects/{pid}")
async def delete_project(pid: str, user: dict = Depends(current_user)):
    _owned(pid, user)
    manager.cancel(pid)
    store.delete(pid)
    return {"deleted": True}


@router.get("/targets")
async def list_targets(user: dict = Depends(current_user)):
    return [{"id": k, "label": v["label"]} for k, v in TARGETS.items()]


@router.get("/projects/{pid}/download")
async def download_zip(pid: str, target: str = "static", user: dict = Depends(current_user)):
    detail = _owned(pid, user)
    if target not in TARGETS:
        raise HTTPException(400, "Unknown target")
    zp = store.export_file(pid, target)
    if not zp.exists():
        raise HTTPException(404, "Export not ready")
    import re as _re
    base = _re.sub(r"[^A-Za-z0-9._-]+", "_", detail.get("name") or "site").strip("_")[:60] or "site"
    return FileResponse(zp, media_type="application/zip", filename=f"{base}-{target}-{pid}.zip")


@router.post("/projects/{pid}/rerun")
async def rerun_project(pid: str, user: dict = Depends(current_user)):
    _owned(pid, user)
    try:
        manager.rerun(pid)
    except KeyError:
        raise HTTPException(404, "Project not found")
    return {"project_id": pid, "status": "running"}


@router.post("/projects/{pid}/outputs")
async def add_outputs(pid: str, req: OutputsRequest, user: dict = Depends(current_user)):
    _owned(pid, user)
    try:
        manager.add_outputs(pid, [t.value for t in req.targets])
    except KeyError:
        raise HTTPException(404, "Project not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"project_id": pid, "status": "running"}


@router.get("/projects/{pid}/site/{path:path}")
async def serve_site(pid: str, path: str = "", user: dict = Depends(current_user)):
    _owned(pid, user)
    base = store.site_dir(pid)
    rel = path or "index.html"
    if rel.endswith("/"):
        rel += "index.html"
    target = _safe_file(base, rel)
    media = _MEDIA.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media)


@router.get("/projects/{pid}/screenshots/{name}")
async def serve_screenshot(pid: str, name: str, user: dict = Depends(current_user)):
    _owned(pid, user)
    target = _safe_file(store.screenshots_dir(pid), name)
    return FileResponse(target, media_type="image/png")
