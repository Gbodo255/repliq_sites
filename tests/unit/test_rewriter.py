from app.modules.dom_parser.rewriter import collect_asset_urls, localize_html

HTML = """<!DOCTYPE html>
<html><head>
<link rel="stylesheet" href="https://site.com/css/app.css">
<link rel="icon" href="https://site.com/favicon.ico">
<script src="https://site.com/app.js"></script>
</head>
<body>
<img src="https://site.com/img/logo.png" srcset="https://site.com/img/logo@2x.png 2x">
<img data-src="https://site.com/img/lazy.jpg" src="data:image/gif;base64,AAAA">
<a href="https://site.com/about">About</a>
<a href="https://other.com/x">External</a>
<div style="background:url('https://site.com/img/bg.png')"></div>
</body></html>"""

BASE = "https://site.com/"


def test_collect_asset_urls():
    urls = collect_asset_urls(HTML, BASE, keep_js=False)
    assert "https://site.com/css/app.css" in urls
    assert "https://site.com/favicon.ico" in urls
    assert "https://site.com/img/logo.png" in urls
    assert "https://site.com/img/logo@2x.png" in urls
    assert "https://site.com/img/lazy.jpg" in urls
    assert "https://site.com/img/bg.png" in urls
    # JS not collected when keep_js is False.
    assert "https://site.com/app.js" not in urls


def test_localize_strips_js_and_rewrites():
    assets = {
        "https://site.com/css/app.css": "assets/css/app.css",
        "https://site.com/favicon.ico": "assets/images/favicon.ico",
        "https://site.com/img/logo.png": "assets/images/logo.png",
        "https://site.com/img/logo@2x.png": "assets/images/logo@2x.png",
        "https://site.com/img/lazy.jpg": "assets/images/lazy.jpg",
        "https://site.com/img/bg.png": "assets/images/bg.png",
    }
    pages = {"https://site.com/about": "pages/about.html"}
    out = localize_html(
        HTML, BASE, page_dir="",
        asset_lookup=lambda u: assets.get(u),
        page_lookup=lambda u: pages.get(u),
        keep_js=False,
    )
    assert "app.js" not in out               # framework JS stripped
    assert 'href="assets/css/app.css"' in out
    assert 'src="assets/images/logo.png"' in out
    assert "assets/images/logo@2x.png 2x" in out   # srcset rewritten
    assert 'src="assets/images/lazy.jpg"' in out   # lazy data-src resolved
    assert 'href="pages/about.html"' in out        # internal link localized
    assert 'href="https://other.com/x"' in out     # external link preserved
    assert "assets/images/bg.png" in out           # inline style url() rewritten


def test_localize_relative_paths_for_subpage():
    assets = {"https://site.com/img/logo.png": "assets/images/logo.png"}
    out = localize_html(
        '<html><body><img src="https://site.com/img/logo.png"></body></html>',
        BASE, page_dir="pages",
        asset_lookup=lambda u: assets.get(u),
        page_lookup=lambda u: None,
        keep_js=False,
    )
    assert 'src="../assets/images/logo.png"' in out
