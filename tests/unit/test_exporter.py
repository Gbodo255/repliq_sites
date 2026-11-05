import zipfile
from pathlib import Path

from app.modules.exporter.exporter import zip_project


def test_zip_project(tmp_path: Path):
    site = tmp_path / "site"
    (site / "assets" / "css").mkdir(parents=True)
    (site / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (site / "assets" / "css" / "style.css").write_text("body{}", encoding="utf-8")

    out = tmp_path / "export.zip"
    zip_project(site, out, arc_root="replicated-site")

    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "replicated-site/index.html" in names
    assert "replicated-site/assets/css/style.css" in names
