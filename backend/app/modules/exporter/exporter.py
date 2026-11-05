"""Export a generated project as a ZIP archive."""
from __future__ import annotations

import zipfile
from pathlib import Path


def zip_project(site_dir: Path, out_zip: Path, arc_root: str = "replicated-site") -> Path:
    """Zip ``site_dir`` into ``out_zip`` with everything under ``arc_root/``.

    The archive is written atomically (to a temp name, then renamed) and the
    output file is never included in itself.
    """
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_zip.with_suffix(out_zip.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(site_dir.rglob("*")):
            if path.is_dir():
                continue
            if path.resolve() == out_zip.resolve():
                continue
            rel = path.relative_to(site_dir).as_posix()
            zf.write(path, f"{arc_root}/{rel}")
    tmp.replace(out_zip)
    return out_zip
