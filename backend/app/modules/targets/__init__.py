"""Output targets: turn the verified static build into the format the user chose."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.modules.exporter.exporter import zip_project

TARGETS: dict[str, dict] = {
    "static": {"label": "HTML / CSS / JS", "arc": "site-html"},
    "react": {"label": "React (Vite)", "arc": "site-react"},
    "nextjs": {"label": "Next.js", "arc": "site-nextjs"},
    "wordpress_theme": {"label": "WordPress theme", "arc": "wordpress-theme"},
    "wordpress_headless": {"label": "WordPress headless (Next.js)", "arc": "wordpress-headless"},
}
WORDPRESS_TARGETS = {"wordpress_theme", "wordpress_headless"}


def normalize_targets(values) -> list[str]:
    out = [v for v in (values or []) if v in TARGETS]
    return list(dict.fromkeys(out)) or ["static"]


def build_target(target: str, *, site_dir: Path, out_root: Path, exports_dir: Path,
                 page_records: list[dict], source_url: str, posts: dict | None = None,
                 screenshot: bytes | None = None, model=None) -> dict:
    """Generate one target into ``out_root/<target>`` and zip it. Returns a summary."""
    from app.modules.targets.model import build_model
    from app.modules.targets.react_next import build_next, build_react
    from app.modules.targets.wordpress import build_wp_headless, build_wp_theme

    exports_dir.mkdir(parents=True, exist_ok=True)
    zip_path = exports_dir / f"{target}.zip"
    arc = TARGETS[target]["arc"]
    if target == "static":
        zip_project(site_dir, zip_path, arc_root=arc)
        return {"target": target, "zip": zip_path.name, "info": {}}

    out = out_root / target
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    model = model or build_model(site_dir, page_records, source_url)
    if target == "react":
        info = build_react(model, site_dir, out)
    elif target == "nextjs":
        info = build_next(model, site_dir, out)
    elif target == "wordpress_theme":
        info = build_wp_theme(model, site_dir, out, posts=posts, screenshot=screenshot)
    else:
        info = build_wp_headless(model, site_dir, out, posts=posts)
    zip_project(out, zip_path, arc_root=arc)
    return {"target": target, "zip": zip_path.name, "info": info}
