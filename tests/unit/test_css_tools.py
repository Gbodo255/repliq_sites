from app.modules.css_analyzer.css_tools import extract_css_urls, rewrite_css_urls

CSS = """
@import "base.css";
@font-face { font-family: X; src: url('/fonts/x.woff2') format('woff2'); }
.hero { background: url("https://cdn.site/img/bg.png") no-repeat; }
.icon { background-image: url(/i/icon.svg); }
.data { background: url(data:image/png;base64,AAAA); }
"""

BASE = "https://cdn.site/css/main.css"


def test_extract_urls_resolves_and_skips_data():
    urls = extract_css_urls(CSS, BASE)
    assert "https://cdn.site/css/base.css" in urls
    assert "https://cdn.site/fonts/x.woff2" in urls
    assert "https://cdn.site/img/bg.png" in urls
    assert "https://cdn.site/i/icon.svg" in urls
    assert all("data:" not in u for u in urls)


def test_rewrite_maps_known_urls_only():
    mapping = {
        "https://cdn.site/fonts/x.woff2": "../fonts/x.woff2",
        "https://cdn.site/img/bg.png": "../images/bg.png",
    }
    out = rewrite_css_urls(CSS, BASE, lambda u: mapping.get(u))
    assert "url('../fonts/x.woff2')" in out
    assert 'url("../images/bg.png")' in out
    # Unmapped stays as original reference.
    assert "url(/i/icon.svg)" in out
    # data URI untouched.
    assert "data:image/png;base64,AAAA" in out
