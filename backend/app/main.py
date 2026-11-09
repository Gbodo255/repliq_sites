"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.auth_routes import router as auth_router
from app.api.routes import router as api_router
from app.api.websocket import ws_router
from app.config import REPO_ROOT, settings
from app.core.aio import ensure_proactor_loop
from app.core.logging import get_logger

# Playwright spawns a browser subprocess; on Windows that needs the Proactor loop.
ensure_proactor_loop()

log = get_logger("main")


def create_app() -> FastAPI:
    app = FastAPI(title="Universal Website Replication Engine", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.google_oauth_enabled:
        log.info("Google sign-in enabled")
    elif settings.dev_auth:
        log.warning("DEV_AUTH enabled: local dev-login active (do NOT use in production)")
    else:
        log.warning("No auth configured: set GOOGLE_CLIENT_ID/SECRET, or DEV_AUTH=true for local testing")

    app.include_router(auth_router)
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/api")
    async def api_root():
        return {"name": "Universal Website Replication Engine", "version": __version__}

    # Serve the built frontend (production) if present. In dev the Vite server
    # runs separately and proxies /api + /ws to this backend.
    dist = REPO_ROOT / "frontend" / "dist"
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
        index_file = dist / "index.html"

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            # Never shadow the API / websocket namespaces.
            if full_path.startswith(("api", "ws", "assets")):
                raise HTTPException(404, "Not found")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
                return FileResponse(candidate)
            return FileResponse(index_file)  # SPA fallback for client-side routes

        log.info("Serving built frontend from %s", dist)
    else:
        @app.get("/")
        async def root():
            return JSONResponse({
                "message": "Backend running. Start the frontend dev server (npm run dev) "
                           "or build it (npm run build) to use the UI.",
                "api": "/api",
                "docs": "/docs",
            })

    try:
        from app.services.project_store import store
        for p in store.list(limit=500):
            if p.get("status") in ("running", "queued"):
                d = store.get(p["id"])
                if d:
                    d["status"] = "failed"
                    d["error"] = "Interrupted: the server restarted during the replication. Please run it again."
                    store.save(d)
    except Exception:  # noqa: BLE001 - never block startup
        pass
    log.info("App ready. Projects dir: %s", settings.projects_dir)
    return app


app = create_app()
