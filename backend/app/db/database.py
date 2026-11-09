"""SQLite index of projects and user accounts.

A lightweight ``projects`` table powers the dashboard and project listing (the
full detail is also mirrored to ``projects/<id>/project.json`` on disk, so the
system is resilient even if the DB is removed), and a ``users`` table holds the
Google-authenticated accounts. Every project carries the ``user_id`` of its
owner so listings/dashboards are scoped per user. Access is serialised with a
lock because the SQLite connection is shared across the async job and request
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
    user_id       TEXT DEFAULT '',
    data          TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    sub         TEXT UNIQUE,
    email       TEXT,
    name        TEXT,
    picture     TEXT,
    created_at  REAL NOT NULL,
    last_login  REAL NOT NULL
);
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
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first release (idempotent)."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
        if "user_id" not in cols:
            self._conn.execute("ALTER TABLE projects ADD COLUMN user_id TEXT DEFAULT ''")
        # Safe now that the column is guaranteed to exist (fresh or migrated).
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at DESC)")

    # ------------------------------------------------------------- projects
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
            detail.get("user_id", ""),
            json.dumps(detail, ensure_ascii=False),
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO projects
                   (id,name,url,status,created_at,updated_at,pages_count,assets_count,assets_bytes,avg_ssim,error,user_id,data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, url=excluded.url, status=excluded.status,
                     updated_at=excluded.updated_at, pages_count=excluded.pages_count,
                     assets_count=excluded.assets_count, assets_bytes=excluded.assets_bytes,
                     avg_ssim=excluded.avg_ssim, error=excluded.error, user_id=excluded.user_id,
                     data=excluded.data""",
                row,
            )
            self._conn.commit()

    def get(self, project_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM projects WHERE id=?", (project_id,))
            r = cur.fetchone()
        return json.loads(r["data"]) if r else None

    def list_summaries(self, limit: int = 100, user_id: str | None = None) -> list[dict]:
        cols = """id,name,url,status,created_at,updated_at,
                  pages_count,assets_count,assets_bytes,avg_ssim,error"""
        with self._lock:
            if user_id is None:
                cur = self._conn.execute(
                    f"SELECT {cols} FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,))
            else:
                cur = self._conn.execute(
                    f"SELECT {cols} FROM projects WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                    (user_id, limit))
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def delete(self, project_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.commit()

    def dashboard(self, user_id: str | None = None) -> dict:
        where = "WHERE user_id=?" if user_id is not None else ""
        params = (user_id,) if user_id is not None else ()
        with self._lock:
            cur = self._conn.execute(
                f"""SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                           COALESCE(SUM(pages_count),0) AS pages,
                           COALESCE(SUM(assets_count),0) AS assets,
                           COALESCE(SUM(assets_bytes),0) AS bytes
                    FROM projects {where}""",
                params,
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

    # ------------------------------------------------------------- users
    def upsert_user(self, user: dict) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO users (id,sub,email,name,picture,created_at,last_login)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     email=excluded.email, name=excluded.name,
                     picture=excluded.picture, last_login=excluded.last_login""",
                (user["id"], user.get("sub", ""), user.get("email", ""), user.get("name", ""),
                 user.get("picture", ""), user.get("created_at", now), now),
            )
            self._conn.commit()

    def get_user(self, user_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
            r = cur.fetchone()
        return dict(r) if r else None

    def get_user_by_sub(self, sub: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM users WHERE sub=?", (sub,))
            r = cur.fetchone()
        return dict(r) if r else None


# Global singleton.
db = Database()
