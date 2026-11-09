"""Hybrid "keep animation JavaScript" mode: which scripts survive (no browser)."""
from app.models.domain import ReplicationOptions
from app.modules.dom_parser.rewriter import collect_asset_urls, localize_html
from app.modules.dom_parser.script_policy import has_framework_runtime, keep_anim_script

PAGE = "https://site.test/about/"


def test_keep_anim_script_rules():
    assert keep_anim_script("https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js", PAGE)
    assert keep_anim_script("https://unpkg.com/lenis@1.1.0/dist/lenis.min.js", PAGE)
    assert keep_anim_script("https://site.test/wp-content/themes/x/js/main.js", PAGE)       # site's own
    assert not keep_anim_script("https://site.test/_next/static/chunks/main-abc.js", PAGE)  # framework
    assert not keep_anim_script("https://framerusercontent.com/sites/abc/script_main.mjs", PAGE, "", "module")
    assert not keep_anim_script("https://site.test/assets/app.js", PAGE, "", "module")      # ES module
    assert not keep_anim_script("https://www.googletagmanager.com/gtag/js?id=G-1", PAGE)    # tracker
    assert not keep_anim_script("https://widget.example.com/chat.js", PAGE)                  # 3rd party
    assert keep_anim_script(None, PAGE, "gsap.to('.hero', {y: 0});")
    assert keep_anim_script(None, PAGE, "$(document).ready(function(){ $('.slider').slick(); });")
    assert not keep_anim_script(None, PAGE, "window.dataLayer=[];function gtag(){dataLayer.push(arguments)}")
    assert not keep_anim_script(None, PAGE, 'self.__next_f.push([1,"..."])')
    assert not keep_anim_script(None, PAGE, "{}", "application/json")


def test_has_framework_runtime():
    assert has_framework_runtime('<script src="/_next/static/chunks/main.js"></script>', PAGE)
    assert has_framework_runtime('<script type="module" src="/x.mjs"></script>', PAGE)
    assert has_framework_runtime('<script>self.__next_f.push(1)</script>', PAGE)
    assert not has_framework_runtime('<script src="/js/gsap.min.js"></script><script>gsap.to(1)</script>', PAGE)


HTML = """<!DOCTYPE html><html><head>
<link rel="preload" as="script" href="/_next/static/chunks/main.js">
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<script src="/_next/static/chunks/main.js"></script>
<script src="https://www.googletagmanager.com/gtag/js?id=G-1"></script>
<script>window.dataLayer=[];</script>
<script type="application/ld+json">{"@type":"Organization"}</script>
</head><body><button onclick="openMenu()">x</button>
<script src="/js/site.js"></script>
<script>gsap.to('.hero', {opacity: 1});</script>
</body></html>"""


def test_rewriter_hybrid_mode_filters_scripts():
    urls = collect_asset_urls(HTML, PAGE, "anim")
    assert "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" in urls
    assert "https://site.test/js/site.js" in urls
    assert not any("_next" in u or "googletagmanager" in u for u in urls)

    lookup = {"https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js": "assets/js/gsap.min.js",
              "https://site.test/js/site.js": "assets/js/site.js"}
    out = localize_html(HTML, PAGE, "about", lambda u: lookup.get(u), lambda u: None, keep_js="anim")
    assert 'src="../assets/js/gsap.min.js"' in out
    assert 'src="../assets/js/site.js"' in out
    assert "gsap.to('.hero'" in out
    assert "_next" not in out and "googletagmanager" not in out and "dataLayer" not in out
    assert "application/ld+json" in out
    assert 'onclick="openMenu()"' in out          # site handlers kept with the site's scripts


def test_options_js_keep():
    assert ReplicationOptions().js_keep is False
    assert ReplicationOptions(keep_anim_js=True).js_keep == "anim"
    assert ReplicationOptions(keep_js=True, keep_anim_js=True).js_keep is True
