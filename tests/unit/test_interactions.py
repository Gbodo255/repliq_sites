"""Unit tests for the motion / behaviour re-implementation (no browser)."""
import json

from app.models.domain import RenderedPage
from app.modules.interaction_analyzer.interactions import INTERACTIONS_JS, interaction_report
from app.modules.page_builder.builder import SiteBuilder


def test_interactions_js_exposes_motion_api():
    # The generated runtime must ship every captured-motion feature + API.
    for token in (
        "setupReveal", "setupScrollState", "setupCarousels", "buildCarousel",
        "revealAll", "function freeze", "data-rx-reveal", "data-rx-scroll",
        "prefers-reduced-motion",
    ):
        assert token in INTERACTIONS_JS, token
    assert "revealAll: revealAll" in INTERACTIONS_JS
    assert "freeze: freeze" in INTERACTIONS_JS


def test_interaction_report_counts_captured_motion():
    pages = [
        RenderedPage(
            url="https://x.test/", final_url="https://x.test/", title="",
            html="<div class='swiper'></div>",
            analysis={
                "reveal": [[0, None, None, None, "opacity .6s"], [0, None, None, None, "opacity .6s"]],
                "scroll_state": {"rows": [["body", ["scrolled"]]], "threshold": 60},
            },
        ),
        RenderedPage(
            url="https://x.test/a", final_url="https://x.test/a", title="",
            html="<div data-aos='fade'></div>",
            analysis={"reveal": [[0, None, None, None, "opacity .6s"]], "scroll_state": {}},
        ),
    ]
    rep = interaction_report(pages)
    assert rep["reveals_captured"] == 3
    assert rep["scroll_state_pages"] == 1
    assert rep.get("carousel") == 1          # markup marker still detected
    assert rep.get("scroll_reveal") == 1     # data-aos marker on the 2nd page


def test_inject_body_attrs_escapes_and_merges():
    html = "<!DOCTYPE html><html><body class='x'><p>hi</p></body></html>"
    out = SiteBuilder._inject_body_attrs(
        html,
        {
            "data-rx-reveal": [[0, "matrix(1, 0, 0, 1, 0, 40)", None, None, "opacity .6s"]],
            "data-rx-scroll": {"rows": [["body", ["scrolled"]]], "threshold": 60},
        },
    )
    # The original body attributes are preserved and ours are added once.
    assert out.count("<body") == 1
    assert "class='x'" in out
    assert "data-rx-reveal='" in out
    assert "data-rx-scroll='" in out
    # A '<' inside any JSON value is neutralised so it can never close a tag.
    assert "<script" not in SiteBuilder._inject_body_attrs(
        "<body></body>", {"data-rx-reveal": ["</script"]}
    ).replace("<body", "")
    # The injected JSON is still valid once HTML entities are decoded.
    attr = out.split("data-rx-scroll='", 1)[1].split("'", 1)[0]
    decoded = attr.replace("&amp;", "&").replace("&#39;", "'").replace("\\u003c", "<")
    assert json.loads(decoded)["threshold"] == 60


def test_inject_body_attrs_noop_without_attrs():
    html = "<body><p>hi</p></body>"
    assert SiteBuilder._inject_body_attrs(html, {}) == html
