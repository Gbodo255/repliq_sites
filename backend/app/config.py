"""Central configuration.

Values are read from the environment (optionally via a ``.env`` file placed in
the ``backend`` directory) and fall back to safe defaults.  A single
``settings`` instance is exposed for the rest of the application to import.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../backend
REPO_ROOT = BACKEND_DIR.parent                                # .../Replicator

# Load backend/.env if present (never raises when the file is missing).
load_dotenv(BACKEND_DIR / ".env")


def _get(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _get(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int


# Breakpoints captured for every page (desktop -> small mobile), per spec.
DEFAULT_VIEWPORTS: list[Viewport] = [
    Viewport("desktop", 1440, 900),
    Viewport("laptop", 1280, 800),
    Viewport("tablet", 768, 1024),
    Viewport("mobile", 390, 844),
    Viewport("small", 360, 780),
]


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: _get("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in _get(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",") if o.strip()
        )
    )

    projects_dir: Path = field(
        default_factory=lambda: (
            Path(p) if (p := _get("PROJECTS_DIR", "projects")) and Path(p).is_absolute()
            else REPO_ROOT / _get("PROJECTS_DIR", "projects")
        )
    )

    max_pages: int = field(default_factory=lambda: _int("MAX_PAGES", 40))
    max_depth: int = field(default_factory=lambda: _int("MAX_DEPTH", 2))
    page_concurrency: int = field(default_factory=lambda: _int("PAGE_CONCURRENCY", 3))
    asset_concurrency: int = field(default_factory=lambda: _int("ASSET_CONCURRENCY", 8))

    max_asset_mb: float = field(default_factory=lambda: float(_get("MAX_ASSET_MB", "25")))
    max_total_mb: float = field(default_factory=lambda: float(_get("MAX_TOTAL_MB", "600")))

    nav_timeout_ms: int = field(default_factory=lambda: _int("NAV_TIMEOUT_MS", 45000))
    headful: bool = field(default_factory=lambda: _bool("HEADFUL", False))

    app_password: str = field(default_factory=lambda: _get("APP_PASSWORD", ""))
    # Small hosts (e.g. 512 MB free tiers): lighter Chromium, one page at a time.
    low_memory: bool = field(default_factory=lambda: _bool("LOW_MEMORY", False))
    block_trackers: bool = field(default_factory=lambda: _bool("BLOCK_TRACKERS", True))
    cache_ttl_hours: int = field(default_factory=lambda: _int("ASSET_CACHE_TTL_HOURS", 168))
    block_private_hosts: bool = field(default_factory=lambda: _bool("BLOCK_PRIVATE_HOSTS", True))
    default_fix_cycles: int = field(default_factory=lambda: _int("DEFAULT_FIX_CYCLES", 1))

    # --- Authentication (Google OAuth) ---------------------------------------
    # Set GOOGLE_CLIENT_ID/SECRET from a Google Cloud "Web application" OAuth
    # client. OAUTH_REDIRECT_URI must exactly match an Authorized redirect URI
    # there ("{PUBLIC_BASE_URL}/api/auth/google/callback"); left empty, it is
    # derived from the incoming request. SESSION_SECRET signs the login cookie.
    google_client_id: str = field(default_factory=lambda: _get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: _get("GOOGLE_CLIENT_SECRET", ""))
    oauth_redirect_uri: str = field(default_factory=lambda: _get("OAUTH_REDIRECT_URI", ""))
    public_base_url: str = field(default_factory=lambda: _get("PUBLIC_BASE_URL", "").rstrip("/"))
    session_secret: str = field(default_factory=lambda: _get("SESSION_SECRET", "dev-insecure-change-me"))
    session_days: int = field(default_factory=lambda: _int("SESSION_DAYS", 30))
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", False))
    # Local testing without real Google credentials: enables POST /api/auth/dev-login.
    dev_auth: bool = field(default_factory=lambda: _bool("DEV_AUTH", False))

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    viewports: tuple[Viewport, ...] = field(default_factory=lambda: tuple(DEFAULT_VIEWPORTS))

    @property
    def db_path(self) -> Path:
        return self.projects_dir / "replicator.db"

    @property
    def cache_dir(self) -> Path:
        return self.projects_dir / "_cache"

    @property
    def max_asset_bytes(self) -> int:
        return int(self.max_asset_mb * 1024 * 1024)

    @property
    def max_total_bytes(self) -> int:
        return int(self.max_total_mb * 1024 * 1024)

    def viewport(self, name: str) -> Viewport | None:
        for v in self.viewports:
            if v.name == name:
                return v
        return None


settings = Settings()

# Make sure the projects directory exists as early as possible.
settings.projects_dir.mkdir(parents=True, exist_ok=True)
