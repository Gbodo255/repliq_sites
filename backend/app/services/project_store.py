"""Project persistence: on-disk layout + state mirror.

Each project lives under ``projects/<id>/``::

    site/          the generated self-contained website (index.html, ...)
    screenshots/   original / generated / diff PNGs for the quality report
    export.zip     downloadable archive of site/
    project.json   full project detail (mirrors the SQLite row)
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from app.config import settings
from app.db.database import db
from app.models.domain import ReplicationOptions


class ProjectStore:
    def __init__(self, base: Path | None = None) -> None:
        self.base = base or settings.projects_dir
        self.base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- paths
    def project_dir(self, pid: str) -> Path:
        return self.base / pid

    def site_dir(self, pid: str) -> Path:
        return self.project_dir(pid) / "site"

    def screenshots_dir(self, pid: str) -> Path:
        return self.project_dir(pid) / "screenshots"

    def zip_path(self, pid: str) -> Path:
        return self.project_dir(pid) / "export.zip"

    def manifest_path(self, pid: str) -> Path:
        return self.project_dir(pid) / "project.json"

    def outputs_dir(self, pid: str) -> Path:
        return self.project_dir(pid) / "outputs"

    def exports_dir(self, pid: str) -> Path:
        return self.project_dir(pid) / "exports"

    def wp_content_path(self, pid: str) -> Path:
        return self.project_dir(pid) / "wp-content.json"

    def export_file(self, pid: str, target: str) -> Path:
        if target == "static":
            return self.zip_path(pid)
        return self.exports_dir(pid) / f"{target}.zip"

    def reset_for_rerun(self, pid: str) -> None:
        """Clear generated artefacts (the asset cache makes the re-run fast)."""
        for d in (self.site_dir(pid), self.screenshots_dir(pid), self.outputs_dir(pid), self.exports_dir(pid)):
            shutil.rmtree(d, ignore_errors=True)
        self.site_dir(pid).mkdir(parents=True, exist_ok=True)
        self.screenshots_dir(pid).mkdir(parents=True, exist_ok=True)
        detail = self.get(pid) or {}
        detail.update({"status": "queued", "error": "", "pages": [], "assets": [], "comparisons": [],
                       "exports": [], "quality": {}, "has_zip": False, "avg_ssim": None,
                       "pages_count": 0, "assets_count": 0, "assets_bytes": 0})
        self.save(detail)

    # ------------------------------------------------------------- lifecycle
    def create(self, name: str, url: str, options: ReplicationOptions) -> dict:
        pid = uuid.uuid4().hex[:12]
        now = time.time()
        self.site_dir(pid).mkdir(parents=True, exist_ok=True)
        self.screenshots_dir(pid).mkdir(parents=True, exist_ok=True)
        detail = {
            "id": pid,
            "name": name or url,
            "url": url,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "options": options.__dict__,
            "pages_count": 0,
            "assets_count": 0,
            "assets_bytes": 0,
            "avg_ssim": None,
            "error": "",
            "pages": [],
            "assets": [],
            "comparisons": [],
            "analysis": {},
            "has_zip": False,
            "exports": [],
            "quality": {},
            "duration": 0.0,
        }
        self.save(detail)
        return detail

    def save(self, detail: dict) -> None:
        detail["updated_at"] = time.time()
        pid = detail["id"]
        self.project_dir(pid).mkdir(parents=True, exist_ok=True)
        self.manifest_path(pid).write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        db.upsert(detail)

    def get(self, pid: str) -> dict | None:
        mp = self.manifest_path(pid)
        if mp.exists():
            try:
                return json.loads(mp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return db.get(pid)

    def list(self, limit: int = 100) -> list[dict]:
        return db.list_summaries(limit)

    def delete(self, pid: str) -> bool:
        d = self.project_dir(pid)
        existed = d.exists()
        if existed:
            shutil.rmtree(d, ignore_errors=True)
        db.delete(pid)
        return existed

    def dashboard(self) -> dict:
        return db.dashboard()


store = ProjectStore()
