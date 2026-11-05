"""Internal domain objects used by the engine modules.

These are plain dataclasses (not pydantic) so the hot paths stay cheap and the
modules have no dependency on the web layer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ReplicationOptions:
    max_pages: int = 40
    max_depth: int = 2
    viewport_names: list[str] = field(default_factory=lambda: ["desktop", "mobile"])
    fix_cycles: int = 1
    mode: str = "auto"              # auto | full | single_page
    keep_js: bool = False          # strip framework runtime JS by default
    download_media: bool = True    # download videos
    run_quality_check: bool = True
    outputs: list[str] = field(default_factory=lambda: ["static"])
    keep_external_links: bool = False   # default: zero external link in the copy
    import_wp_content: bool = True      # import posts/categories from a WordPress source


@dataclass
class AssetRecord:
    url: str
    category: str = "other"
    ext: str = ""
    local_path: str = ""           # path relative to project output root
    status: str = "pending"        # pending | ok | skipped | error
    size: int = 0
    content_type: str = ""
    content_hash: str = ""
    source_page: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageRecord:
    url: str
    title: str = ""
    depth: int = 0
    output_path: str = ""          # relative to project output root
    status: str = "pending"        # pending | rendered | built | error
    html_bytes: int = 0
    screenshots: dict[str, str] = field(default_factory=dict)  # viewport -> rel path
    links: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RenderedPage:
    """Raw output of the browser renderer for a single page."""
    url: str
    final_url: str
    title: str
    html: str                      # fully rendered DOM (outerHTML)
    status_code: int = 200
    retry_after: float = 0.0
    throttled_resources: int = 0   # sub-resources refused with 429/503 during capture
    ok: bool = True
    error: str = ""
    links: list[str] = field(default_factory=list)
    stylesheet_urls: list[str] = field(default_factory=list)
    resource_urls: list[str] = field(default_factory=list)
    screenshots: dict[str, bytes] = field(default_factory=dict)  # viewport -> png bytes
    signatures: dict[str, dict] = field(default_factory=dict)    # viewport -> layout signature
    snapshots: dict[str, bytes] = field(default_factory=dict)    # data-rx-snap id -> png
    analysis: dict = field(default_factory=dict)


@dataclass
class CompareResult:
    page_url: str
    viewport: str
    ssim: float = 0.0
    diff_ratio: float = 1.0        # fraction of pixels that differ notably
    original_png: str = ""         # rel path
    generated_png: str = ""        # rel path
    diff_png: str = ""             # rel path
    width: int = 0
    height_original: int = 0
    height_generated: int = 0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
