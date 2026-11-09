"""Pydantic schemas for the HTTP/WebSocket API."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ReplicationMode(str, Enum):
    auto = "auto"            # optimized defaults, just give a URL
    full = "full"           # crawl many pages, all viewports, quality loop
    single_page = "single_page"


class OutputTarget(str, Enum):
    static = "static"                          # HTML / CSS / JS
    react = "react"                            # React + Vite
    nextjs = "nextjs"                          # Next.js (App Router)
    wordpress_theme = "wordpress_theme"        # installable WordPress theme
    wordpress_headless = "wordpress_headless"  # WordPress + Next.js front-end
    figma = "figma"                            # editable Figma design (plugin)


class ReplicationRequest(BaseModel):
    url: str = Field(..., description="Seed URL of the site to replicate")
    name: str | None = Field(None, description="Optional project name")
    mode: ReplicationMode = ReplicationMode.auto
    max_depth: int | None = Field(None, ge=0, le=5)
    max_pages: int | None = Field(None, ge=1, le=300)
    viewports: list[str] | None = Field(
        None, description="Viewport names to capture, e.g. ['desktop','mobile']"
    )
    fix_cycles: int | None = Field(None, ge=0, le=5)
    keep_js: bool | None = Field(
        None, description="Keep the site's original JavaScript (default: strip framework runtime)"
    )
    keep_anim_js: bool | None = Field(
        None, description="Hybrid: keep the site's animation libraries and own scripts, "
                          "drop framework runtimes and third-party scripts"
    )
    run_quality_check: bool | None = None
    outputs: list[OutputTarget] | None = Field(
        None, description="Output formats to generate (default: static HTML)"
    )
    keep_external_links: bool | None = Field(
        None, description="Keep links to other websites (default: removed - zero external link)"
    )
    import_wp_content: bool | None = Field(
        None, description="Import posts/categories from a WordPress source (WordPress outputs)"
    )


class OutputsRequest(BaseModel):
    targets: list[OutputTarget]


class AssetOut(BaseModel):
    url: str
    category: str
    ext: str
    local_path: str
    status: str
    size: int
    content_type: str = ""
    source_page: str = ""
    error: str = ""


class PageOut(BaseModel):
    url: str
    title: str
    depth: int
    output_path: str
    status: str
    html_bytes: int
    screenshots: dict[str, str] = {}
    error: str = ""


class CompareOut(BaseModel):
    page_url: str
    viewport: str
    ssim: float
    diff_ratio: float
    original_png: str
    generated_png: str
    diff_png: str
    issues: list[str] = []


class ProjectSummary(BaseModel):
    id: str
    name: str
    url: str
    status: JobStatus
    created_at: float
    updated_at: float
    pages_count: int = 0
    assets_count: int = 0
    assets_bytes: int = 0
    avg_ssim: float | None = None
    error: str = ""


class ProjectDetail(ProjectSummary):
    options: dict = {}
    pages: list[PageOut] = []
    assets: list[AssetOut] = []
    comparisons: list[CompareOut] = []


class JobAccepted(BaseModel):
    job_id: str
    project_id: str
    status: JobStatus


class DashboardStats(BaseModel):
    projects_total: int
    projects_completed: int
    projects_running: int
    pages_total: int
    assets_total: int
    assets_bytes: int
    recent: list[ProjectSummary]
