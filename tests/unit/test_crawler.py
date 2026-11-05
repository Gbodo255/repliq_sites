from app.modules.crawler.crawler import _is_crawlable, canonicalize


def test_canonicalize():
    assert canonicalize("https://X.com:443/a/#frag") == "https://x.com/a"
    assert canonicalize("http://x.com:80/") == "http://x.com/"
    assert canonicalize("https://x.com/a/b/") == "https://x.com/a/b"


def test_is_crawlable_scope_and_filetypes():
    host = "example.com"
    assert _is_crawlable("https://example.com/about", host)
    assert _is_crawlable("https://www.example.com/x", host)
    assert not _is_crawlable("https://other.com/x", host)
    assert not _is_crawlable("https://example.com/file.pdf", host)
    assert not _is_crawlable("https://example.com/a.jpg", host)
    assert not _is_crawlable("mailto:a@b.com", host)
    assert not _is_crawlable("javascript:void(0)", host)
