from app.core.utils import (
    categorize,
    content_type_ext,
    ext_from_url,
    safe_filename,
    same_site,
    short_hash,
    slugify,
)


def test_slugify():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("") == "page"
    assert slugify("/a/b/c/") == "a-b-c"


def test_safe_filename():
    # Takes the basename and sanitises unsafe characters (callers strip queries).
    assert safe_filename("pic name.PNG") == "pic_name.PNG"
    assert safe_filename("a/b/c.js") == "c.js"
    assert safe_filename("") == "file"
    assert "/" not in safe_filename("a/b/c.js")


def test_categorize():
    assert categorize(".png") == "images"
    assert categorize(".svg") == "icons"
    assert categorize(".woff2") == "fonts"
    assert categorize(".css") == "css"
    assert categorize(".mp4") == "videos"
    assert categorize("", "image/webp") == "images"
    assert categorize("", "font/woff2") == "fonts"
    assert categorize(".xyz") == "other"


def test_content_type_ext():
    assert content_type_ext("text/css; charset=utf-8") == ".css"
    assert content_type_ext("image/png") == ".png"


def test_ext_from_url():
    assert ext_from_url("https://x.com/a/b.min.css?v=2") == ".css"
    assert ext_from_url("https://x.com/noext") == ""


def test_same_site():
    assert same_site("www.iana.org", "iana.org")
    assert same_site("a.example.com", "example.com")
    assert same_site("example.com", "example.com")
    assert not same_site("example.com", "evil.com")
    assert not same_site(None, "x.com")


def test_short_hash_stable():
    assert short_hash("abc") == short_hash("abc")
    assert len(short_hash("abc", 8)) == 8
