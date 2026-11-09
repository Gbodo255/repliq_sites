"""Unit tests for captured motion -> CSS (no browser)."""
from app.modules.interaction_analyzer.motion_css import animation_css, hover_css, motion_css


def _anim(**kw):
    a = {"kf": [{"o": 0, "e": "linear", "p": {"opacity": "0", "transform": "translateY(40px)"}},
                {"o": 1, "e": "linear", "p": {"opacity": "1", "transform": "none"}}],
         "d": 600, "dl": 100, "it": 1, "dir": "normal", "ez": "cubic-bezier(0.22, 1, 0.36, 1)"}
    a.update(kw)
    return a


def test_load_animation_becomes_keyframes():
    css = animation_css([{"i": 0, "t": "load", "a": [_anim()]}])
    assert "@keyframes rxa0-0{0%{opacity:0;transform:translateY(40px)}100%{opacity:1;transform:none}}" in css
    assert '[data-rx-a="0"]{animation:rxa0-0 600ms cubic-bezier(0.22, 1, 0.36, 1) 100ms 1 normal backwards}' in css
    assert "rx-a-run" not in css                      # no in-view element
    assert "prefers-reduced-motion:reduce" in css
    assert "html.rx-frozen [data-rx-a]{animation:none!important}" in css


def test_loop_and_view_triggers():
    css = animation_css([
        {"i": 1, "t": "load", "a": [_anim(it=-1, kf=[{"o": 0, "e": "linear", "p": {"transform": "rotate(0deg)"}},
                                                     {"o": 1, "e": "linear", "p": {"transform": "rotate(360deg)"}}])]},
        {"i": 2, "t": "view", "a": [_anim()]},
    ])
    assert "infinite normal both" in css
    assert "html.rx-a-ready [data-rx-a-view]:not(.rx-a-run){animation-play-state:paused}" in css


def test_per_frame_easing_and_property_names():
    css = animation_css([{"i": 3, "t": "load", "a": [_anim(kf=[
        {"o": 0, "e": "ease-in", "p": {"background-color": "red", "--x": "1"}},
        {"o": 0.5, "e": "linear", "p": {"background-color": "blue"}},
        {"o": 1, "e": "linear", "p": {"background-color": "green"}},
    ])]}])
    assert "0%{background-color:red;--x:1;animation-timing-function:ease-in}" in css
    assert "50%{background-color:blue}" in css


def test_injection_is_rejected():
    css = animation_css([{"i": 4, "t": "load", "a": [_anim(
        ez="x}</style><script>", dir="sideways",
        kf=[{"o": 0, "e": "linear", "p": {"opacity": "0;}body{display:none", "color": "red"}},
            {"o": 1, "e": "linear", "p": {"bad name": "1", "color": "blue"}}])]}])
    assert "</style>" not in css and "display:none" not in css and "bad name" not in css
    assert " linear 100ms 1 normal backwards" in css
    assert hover_css([{"i": 0, "r": [{"p": "div>script", "s": {"color": "red"}}]}]) == ""
    assert hover_css([{"i": 0, "r": [{"p": "", "s": {"color": "red}</style>"}}]}]) == ""


def test_empty_inputs():
    assert animation_css([]) == ""
    assert animation_css([{"i": 0, "t": "load", "a": [_anim(kf=[])]}]) == ""
    assert motion_css({}) == ""


def test_hover_rules_with_runtime_timing():
    css = hover_css([{"i": 2, "r": [
        {"p": "", "s": {"background-color": "rgb(35, 55, 255)"}, "tr": "250ms linear"},
        {"p": "div:nth-of-type(1)>span:nth-of-type(2)", "s": {"color": "rgb(255, 255, 255)"}},
    ]}])
    assert css.startswith("/* rx-hover")
    assert "@media (hover:hover){" in css
    assert '[data-rx-h="2"]{transition-property:background-color;transition-duration:250ms;transition-timing-function:linear}' in css
    assert '[data-rx-h="2"]:hover{background-color:rgb(35, 55, 255)!important}' in css
    assert '[data-rx-h="2"]:hover>div:nth-of-type(1)>span:nth-of-type(2){color:rgb(255, 255, 255)!important}' in css



def test_scroll_tracks_become_scroll_timeline():
    from app.modules.interaction_analyzer.motion_css import scroll_css
    data = {"els": [{"i": 0, "y": [0, 450, 900],
                     "p": {"transform": ["none", "matrix(1, 0, 0, 1, 0, 135)", "matrix(1, 0, 0, 1, 0, 270)"],
                           "opacity": ["1", "0.6", "bad;}x"]}}]}
    css = scroll_css(data, (1100, None))
    assert "@keyframes rxs0{0%{transform:none;opacity:1}50%{transform:matrix(1, 0, 0, 1, 0, 135);opacity:0.6}100%{transform:matrix(1, 0, 0, 1, 0, 270)}}" in css
    assert "@media (min-width:1100px){" in css
    assert '[data-rx-s="0"]{animation:rxs0 1s linear both paused}' in css
    assert "animation-timeline:scroll(root block);animation-range:0px 900px" in css
    assert "@supports (animation-timeline:scroll())" in css
    assert "html.rx-frozen [data-rx-s]{animation:none!important}" in css


def test_scroll_tracks_rejects_bad_input():
    from app.modules.interaction_analyzer.motion_css import scroll_css
    assert scroll_css({}) == ""
    assert scroll_css({"els": [{"i": 0, "y": [0], "p": {"opacity": ["1"]}}]}) == ""
    assert scroll_css({"els": [{"i": 0, "y": [100, 100], "p": {"opacity": ["1", "0"]}}]}) == ""
    assert "min-width" not in scroll_css({"els": [{"i": 1, "y": [0, 10], "p": {"opacity": ["1", "0"]}}]})
