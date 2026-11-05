import json
import subprocess
import shutil
import zipfile

import pytest
from bs4 import BeautifulSoup

from app.modules.auto_fixer.layout import LayoutFixer, diff_signatures, media_ranges
from app.modules.targets import build_target
from app.modules.targets.jsx import JsxContext, html_to_nodes, nodes_to_jsx, style_object
from app.modules.targets.model import build_model

PAGE = """<!DOCTYPE html><html lang="fr" class="js"><head>
<meta charset="utf-8"><title>{title} – Acme</title>
<meta name="description" content="Desc {title}">
<link rel="stylesheet" href="{up}assets/css/site.css">
<style>.hero{{background:url({up}assets/images/bg.png)}}</style>
<link rel="stylesheet" href="{up}css/responsive.css">
</head><body class="page-{key} home">
<header class="site-header"><a href="{up}index.html">Home</a> <a href="{about}">About</a></header>
<main><h1>{title}</h1><p>Hello <b>world</b> <i>!</i></p>
<img src="{up}assets/images/logo.png" srcset="{up}assets/images/logo.png 1x">
<table><tr><td>a</td></tr></table>
<svg viewbox="0 0 10 10" stroke-width="2"><lineargradient id="g"></lineargradient></svg>
<div style="color:red !important">imp</div>
<label for="x">L</label><input id="x" value="v"><textarea>t</textarea>
</main>
<footer id="colophon">© Acme</footer>
<script src="{up}js/interactions.js"></script>
</body></html>"""


@pytest.fixture()
def site(tmp_path):
    s = tmp_path / "site"
    (s / "pages").mkdir(parents=True)
    (s / "assets" / "css").mkdir(parents=True)
    (s / "assets" / "images").mkdir(parents=True)
    (s / "css").mkdir()
    (s / "js").mkdir()
    (s / "assets" / "css" / "site.css").write_text("body > header{color:blue}", encoding="utf-8")
    (s / "css" / "responsive.css").write_text("", encoding="utf-8")
    (s / "js" / "interactions.js").write_text("", encoding="utf-8")
    (s / "index.html").write_text(PAGE.format(title="Home", up="", key="home", about="pages/about.html"), encoding="utf-8")
    (s / "pages" / "about.html").write_text(PAGE.format(title="About", up="../", key="about", about="about.html"), encoding="utf-8")
    records = [
        {"url": "https://acme.com/", "title": "Home", "output_path": "index.html", "status": "built"},
        {"url": "https://acme.com/about", "title": "About", "output_path": "pages/about.html", "status": "built"},
    ]
    return s, records


def test_model_tokenises_and_detects_shell(site):
    s, records = site
    m = build_model(s, records, "https://acme.com/")
    assert [p.key for p in m.pages] == ["", "about"]
    assert m.site_name == "Home"
    about = m.pages[1]
    assert about.body_attrs["class"] == "page-about home"
    hrefs = [h.attrs.get("href") for h in about.head if h.kind == "link"]
    assert hrefs == ["{{A}}/assets/css/site.css"]           # injected responsive.css removed
    assert "{{A}}/assets/images/bg.png" in about.head[2].css or any(
        "{{A}}/assets/images/bg.png" in h.css for h in about.head)
    # Header and footer are identical on both pages -> shared shell.
    assert [n.name for n in m.shell.prefix] == ["header"]
    assert [n.name for n in m.shell.suffix] == ["footer"]
    assert "{{P:about}}" in m.shell.open_html() and "{{P:}}" in m.shell.open_html()
    assert [n.name for n in about.middle] == ["main"]


def test_jsx_conversion_rules():
    ctx = JsxContext(ssr=True)
    jsx = nodes_to_jsx(html_to_nodes(
        '<p class="a" style="font-size:12px;--x:1">Hi <b>x</b></p>'
        '<label for="i">L</label><input id="i" value="v" checked>'
        '<table><tr><td>a</td></tr></table>'
        '<svg viewbox="0 0 1 1" stroke-width="2"><path d="M0"></path></svg>'
        '<div><span style="color:red !important">x</span></div>'), ctx)
    assert 'className={"a"}' in jsx
    assert 'style={{"fontSize": "12px", "--x": "1"}}' in jsx
    assert '{"Hi "}' in jsx                                  # whitespace preserved
    assert 'htmlFor={"i"}' in jsx and 'defaultValue={"v"}' in jsx and "defaultChecked" in jsx
    assert "<table><tbody><tr>" in jsx                       # implicit tbody made explicit
    assert 'viewBox={"0 0 1 1"}' in jsx and 'strokeWidth={"2"}' in jsx
    assert "dangerouslySetInnerHTML" in jsx                  # svg children + !important parent
    assert ctx.raw_fallbacks == 1
    assert style_object("color: red !important") is None


def test_layout_fixer_restores_hidden_content():
    orig = {"body>div:nth-of-type(1)": ["block", "visible", "1", "none", 100, 50],
            "body>p:nth-of-type(1)": ["block", "visible", "1", "none", 10, 10]}
    gen = {"body>div:nth-of-type(1)": ["block", "visible", "0", "matrix(1, 0, 0, 1, 0, 40)", 100, 50],
           "body>p:nth-of-type(1)": ["block", "visible", "1", "none", 10, 10]}
    fixes = diff_signatures(orig, gen)
    assert fixes == {"body>div:nth-of-type(1)": {"opacity": "1", "transform": "none"}}
    ranges = media_ranges(["desktop", "mobile"])
    assert ranges["mobile"][0] == 0 and ranges["desktop"][1] is None
    fx = LayoutFixer(["desktop", "mobile"])
    assert fx.add("index.html", "desktop", orig, gen) == 2
    assert fx.add("index.html", "desktop", orig, orig) == 0   # accumulates, never regresses
    assert fx.count("index.html") == 1


def _js_files(root):
    return [p for p in root.rglob("*.jsx")]


def test_all_targets_generate(site, tmp_path):
    s, records = site
    out, exp = tmp_path / "out", tmp_path / "exp"
    for t in ("static", "react", "nextjs", "wordpress_theme", "wordpress_headless"):
        res = build_target(t, site_dir=s, out_root=out, exports_dir=exp, page_records=records,
                           source_url="https://acme.com/")
        assert (exp / res["zip"]).exists()
        with zipfile.ZipFile(exp / res["zip"]) as zf:
            assert zf.namelist()

    react = out / "react"
    assert (react / "src" / "pages" / "Home.jsx").exists() and (react / "src" / "pages" / "About.jsx").exists()
    assert "body > #root > header" in (react / "public" / "assets" / "css" / "site.css").read_text()
    pkg = json.loads((react / "package.json").read_text())
    assert pkg["scripts"]["dev"] == "vite"

    nxt = out / "nextjs"
    assert (nxt / "app" / "page.jsx").exists() and (nxt / "app" / "about" / "page.jsx").exists()
    shell = (nxt / "components" / "SiteShell.jsx").read_text(encoding="utf-8")
    assert 'href={"/about"}' in shell and "{children}" in shell

    with zipfile.ZipFile(out / "wordpress_theme" / "rx-home.zip") as zf:
        names = set(zf.namelist())
        for f in ("style.css", "functions.php", "header.php", "footer.php", "page.php", "index.php",
                  "inc/importer.php", "inc/template.php", "inc/data/pages.json", "inc/heads/about.html",
                  "inc/heads/_default.html", "inc/parts/post-open.html"):
            assert f"rx-home/{f}" in names, f
        pages = json.loads(zf.read("rx-home/inc/data/pages.json").decode("utf-8"))
    assert {p["slug"] for p in pages} == {"home", "about"}
    assert not (out / "wordpress_theme" / "rx-home").exists()      # only the installable zip ships
    theme = out / "wordpress_theme"

    hl = out / "wordpress_headless"
    assert (hl / "frontend" / "lib" / "wordpress.js").exists()
    with zipfile.ZipFile(hl / "wordpress" / "rx-home-content.zip") as zf:
        assert "rx-home-content/rx-home-content.php" in zf.namelist()
    fallback = json.loads((hl / "frontend" / "content" / "pages.json").read_text(encoding="utf-8"))
    assert all("{{" not in p["html"] for p in fallback)
    assert 'data-rx-i="c-1"' in fallback[0]["html"]          # !important kept via scoped rule

    # No external URL anywhere in the generated code.
    for root in (react, nxt, theme, hl):
        for p in root.rglob("*"):
            if p.suffix in (".jsx", ".html", ".json", ".css") and "node_modules" not in p.parts:
                txt = p.read_text(encoding="utf-8")
                assert "acme.com" not in txt or p.name in ("README.md", "site.json"), p


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
def test_wordpress_php_is_valid(site, tmp_path):
    s, records = site
    build_target("wordpress_theme", site_dir=s, out_root=tmp_path / "o", exports_dir=tmp_path / "e",
                 page_records=records, source_url="https://acme.com/")
    build_target("wordpress_headless", site_dir=s, out_root=tmp_path / "o", exports_dir=tmp_path / "e",
                 page_records=records, source_url="https://acme.com/")
    unz = tmp_path / "unz"
    for z in (tmp_path / "o").rglob("*.zip"):
        with zipfile.ZipFile(z) as zf:
            zf.extractall(unz / z.stem)
    phps = list(unz.rglob("*.php"))
    assert len(phps) >= 10
    for php in phps:
        r = subprocess.run(["php", "-l", str(php)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
