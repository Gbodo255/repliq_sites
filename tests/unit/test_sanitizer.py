from bs4 import BeautifulSoup

from app.modules.sanitizer.external import purge_css, purge_soup, purge_tree

HTML = """<!DOCTYPE html><html><head>
<link rel="preconnect" href="https://fonts.gstatic.com">
<link rel="canonical" href="https://site.com/">
<link rel="stylesheet" href="assets/css/app.css">
<meta property="og:image" content="https://site.com/og.png">
<meta name="description" content="Hello">
<script type="application/ld+json">{"url":"https://site.com"}</script>
<style>.a{background:url(https://cdn.com/x.png)} @import url("https://fonts.googleapis.com/css?family=X");</style>
</head><body>
<!-- https://comment.example -->
<a href="https://facebook.com/page" target="_blank" rel="noopener">FB</a>
<a href="pages/about.html">About</a>
<img src="https://cdn.com/missing.jpg" srcset="assets/a.png 1x, https://cdn.com/b.png 2x">
<iframe src="https://www.youtube.com/embed/x"></iframe>
<div data-bg="https://cdn.com/bg.jpg" style="background-image:url('https://cdn.com/s.png')">x</div>
<svg xmlns="http://www.w3.org/2000/svg"><use href="https://cdn.com/sprite.svg#i"></use></svg>
<form action="https://api.site.com/submit"><input value="https://typed.example"></form>
<p>Visit https://text.example for more</p>
</body></html>"""


def test_purge_removes_every_external_reference():
    soup = BeautifulSoup(HTML, "lxml")
    n = purge_soup(soup)
    out = str(soup)
    assert n > 10
    for host in ("fonts.gstatic.com", "facebook.com", "cdn.com", "youtube.com", "api.site.com",
                 "comment.example", "og.png", "googleapis"):
        assert host not in out, host
    # Kept: local refs, the namespace URI, visible text and form values.
    assert 'href="assets/css/app.css"' in out
    assert 'href="pages/about.html"' in out
    assert "http://www.w3.org/2000/svg" in out
    assert "https://text.example" in out
    assert "https://typed.example" in out
    assert 'srcset="assets/a.png 1x"' in out
    assert '<meta content="Hello" name="description"/>' in out


def test_dry_run_audit_is_clean_after_purge(tmp_path):
    (tmp_path / "index.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "a.css").write_text("@import url(https://x.com/a.css); .b{background:url(//cdn.x/y.png)}\n/*# sourceMappingURL=a.css.map */", encoding="utf-8")
    first = purge_tree(tmp_path)
    assert first["total"] > 0
    audit = purge_tree(tmp_path, dry_run=True)
    assert audit["total"] == 0


def test_keep_external_links_option():
    soup = BeautifulSoup('<a href="https://other.com">x</a><img src="https://cdn.com/a.png">', "lxml")
    purge_soup(soup, keep_external_links=True)
    out = str(soup)
    assert 'href="https://other.com"' in out
    assert "cdn.com" not in out


def test_purge_css():
    css, n = purge_css(".a{background:url('https://x.com/a.png')} .b{background:url(local.png)}")
    assert n == 1 and "x.com" not in css and "local.png" in css
