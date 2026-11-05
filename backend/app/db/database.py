"""SQLite index of projects.

A single lightweight table powers the dashboard and project listing.  The full
project detail is also mirrored to ``projects/<id>/project.json`` on disk, so
the system is resilient even if the DB is removed.  Access is serialised with a
lock because SQLite connections are shared across the async job and request
handlers.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    url           TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    pages_count   INTEGER DEFAULT 0,
    assets_count  INTEGER DEFAULT 0,
    assets_bytes  INTEGER DEFAULT 0,
    avg_ssim      REAL,
    error         TEXT DEFAULT '',
    data          TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
"""


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def upsert(self, detail: dict) -> None:
        now = time.time()
        row = (
            detail["id"],
            detail.get("name", ""),
            detail.get("url", ""),
            detail.get("status", "queued"),
            detail.get("created_at", now),
            now,
            detail.get("pages_count", 0),
            detail.get("assets_count", 0),
            detail.get("assets_bytes", 0),
            detail.get("avg_ssim"),
            detail.get("error", ""),
            json.dumps(detail, ensure_ascii=False),
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO projects
                   (id,name,url,status,created_at,updated_at,pages_count,assets_count,assets_bytes,avg_ssim,error,data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, url=excluded.url, status=excluded.status,
                     updated_at=excluded.updated_at, pages_count=excluded.pages_count,
                     assets_count=excluded.assets_count, assets_bytes=excluded.assets_bytes,
                     avg_ssim=excluded.avg_ssim, error=excluded.error, data=excluded.data""",
                row,
            )
            self._conn.commit()

    def get(self, project_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM projects WHERE id=?", (project_id,))
            r = cur.fetchone()
        return json.loads(r["data"]) if r else None

    def list_summaries(self, limit: int = 100) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                """SELECT id,name,url,status,created_at,updated_at,
                          pages_count,assets_count,assets_bytes,avg_ssim,error
                   FROM projects ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def delete(self, project_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.commit()

    def dashboard(self) -> dict:
        with self._lock:
            cur = self._conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                          SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                          COALESCE(SUM(pages_count),0) AS pages,
                          COALESCE(SUM(assets_count),0) AS assets,
                          COALESCE(SUM(assets_bytes),0) AS bytes
                   FROM projects"""
            )
            r = cur.fetchone()
        return {
            "projects_total": r["total"] or 0,
            "projects_completed": r["completed"] or 0,
            "projects_running": r["running"] or 0,
            "pages_total": r["pages"] or 0,
            "assets_total": r["assets"] or 0,
            "assets_bytes": r["bytes"] or 0,
        }


# Global singleton.
db = Database()
