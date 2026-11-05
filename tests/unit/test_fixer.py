from bs4 import BeautifulSoup

from app.modules.auto_fixer.fixer import _collect_remote_refs

# A WordPress-style head mixing real assets with discovery links.
HTML = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://site.com/style.css">
<link rel="icon" href="https://site.com/favicon.ico">
<link rel="preload" as="font" href="https://site.com/font.woff2">
<link rel="alternate" type="application/rss+xml" href="https://site.com/feed/">
<link rel="EditURI" href="https://site.com/xmlrpc.php?rsd">
<link rel="https://api.w.org/" href="https://site.com/wp-json/">
<link rel="alternate" type="application/json+oembed" href="https://site.com/wp-json/oembed/1.0/embed?url=x">
<link rel="pingback" href="https://site.com/xmlrpc.php">
</head><body>
<img src="https://site.com/img/a.png">
</body></html>"""


def test_fixer_ignores_non_asset_link_rels():
    soup = BeautifulSoup(HTML, "lxml")
    refs = _collect_remote_refs(soup, keep_js=False)
    # Real assets are picked up.
    assert "https://site.com/style.css" in refs
    assert "https://site.com/favicon.ico" in refs
    assert "https://site.com/font.woff2" in refs
    assert "https://site.com/img/a.png" in refs
    # Discovery links are NOT downloaded as assets.
    assert "https://site.com/feed/" not in refs
    assert "https://site.com/xmlrpc.php?rsd" not in refs
    assert "https://site.com/wp-json/" not in refs
    assert "https://site.com/xmlrpc.php" not in refs
    assert not any("oembed" in r for r in refs)
