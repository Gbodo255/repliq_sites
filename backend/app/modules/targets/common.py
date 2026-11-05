"""Helpers shared by the output generators."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from bs4 import Tag

from app.modules.targets.jsx import JsxContext, _open, html_to_nodes, nodes_to_jsx
from app.modules.targets.model import HeadItem, PageModel, Shell, SiteModel, _open_tag_html, render_tokens

STATIC_DIRS = ("assets", "css", "js")
_BODY_CHILD_RE = re.compile(r"(?<![-\w.#])body(\s*)>(\s*)(?!\s*#root)")


def pascal(key: str, used: set[str]) -> str:
    base = "".join(p.capitalize() for p in re.split(r"[^a-zA-Z0-9]+", key) if p) or "Home"
    if base[0].isdigit():
        base = "P" + base
    name = base
    i = 2
    while name in used:
        name = f"{base}{i}"
        i += 1
    used.add(name)
    return name


def copy_static(site_dir: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for d in STATIC_DIRS:
        src = site_dir / d
        if src.is_dir():
            shutil.copytree(src, dest / d, dirs_exist_ok=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def js_route(key: str) -> str:
    return "/" if not key else f"/{key}"


def detok(text: str, asset_prefix: str = "", page_url=js_route) -> str:
    return render_tokens(text, asset_prefix, page_url)


def detok_nodes(nodes: list, asset_prefix: str = "", page_url=js_route) -> list:
    return html_to_nodes(detok("".join(str(n) for n in nodes), asset_prefix, page_url))


def detok_tag(tag: Tag, asset_prefix: str = "", page_url=js_route) -> Tag:
    html = detok(_open_tag_html(tag) + f"</{tag.name}>", asset_prefix, page_url)
    return next(n for n in html_to_nodes(html) if isinstance(n, Tag))


def shell_jsx(shell: Shell | None, ctx: JsxContext, children: str = "{children}",
              asset_prefix: str = "", page_url=js_route) -> str:
    if shell is None:
        return children
    pre = nodes_to_jsx(detok_nodes(shell.prefix, asset_prefix, page_url), ctx)
    suf = nodes_to_jsx(detok_nodes(shell.suffix, asset_prefix, page_url), ctx)
    mid = children
    if shell.wrapper is not None:
        inner = shell_jsx(shell.inner, ctx, children, asset_prefix, page_url) if shell.inner else children
        w = detok_tag(shell.wrapper, asset_prefix, page_url)
        mid = _open(w) + ">" + inner + "</" + w.name + ">"
    return pre + mid + suf


def head_jsx(page: PageModel, asset_prefix: str = "", page_url=js_route, with_title: bool = True) -> str:
    """React 19 hoistable head elements, in the page's original order."""
    out = []
    if with_title and page.title:
        out.append("<title>{" + json.dumps(page.title, ensure_ascii=False) + "}</title>")
    for i, item in enumerate(page.head):
        attrs = {k: detok(v, asset_prefix, page_url) for k, v in item.attrs.items()}
        if item.kind == "style":
            css = detok(item.css, asset_prefix, page_url)
            href = f"rx-{page.key or 'home'}-{i}"
            media = (attrs.get("media") or "").strip()
            if media and media.lower() != "all":
                css = f"@media {media} {{\n{css}\n}}"
            out.append(f'<style href="{href}" precedence="default">' + "{"
                       + json.dumps(css, ensure_ascii=False) + "}</style>")
        elif item.kind == "link":
            props = []
            rels = attrs.get("rel", "")
            for k, v in attrs.items():
                kk = {"crossorigin": "crossOrigin", "hreflang": "hrefLang", "imagesrcset": "imageSrcSet",
                      "imagesizes": "imageSizes", "fetchpriority": "fetchPriority",
                      "referrerpolicy": "referrerPolicy", "class": "className"}.get(k.lower(), k.lower())
                if kk in ("integrity",) or not re.match(r"^[A-Za-z][A-Za-z0-9-]*$", kk):
                    continue
                props.append(kk + "={" + json.dumps(v, ensure_ascii=False) + "}")
            if "stylesheet" in rels.split():
                props.append('precedence="default"')
            out.append("<link " + " ".join(props) + " />")
        elif item.kind == "meta":
            props = [k.lower() + "={" + json.dumps(v, ensure_ascii=False) + "}"
                     for k, v in attrs.items() if re.match(r"^[a-z-]+$", k.lower()) and k.lower() != "http-equiv"]
            out.append("<meta " + " ".join(props) + " />")
    return "".join(out)


def attrs_map(model: SiteModel, asset_prefix: str = "", page_url=js_route) -> dict:
    out = {}
    for p in model.pages:
        out[js_route(p.key)] = {
            "h": {k: detok(v, asset_prefix, page_url) for k, v in p.html_attrs.items() if k not in ("lang",)},
            "b": {k: detok(v, asset_prefix, page_url) for k, v in p.body_attrs.items()},
        }
    return out


ATTRS_SCRIPT = (
    "(function(){var M=__MAP__;var p=location.pathname.replace(/\\/+$/,'')||'/';"
    "var m=M[p]||M['/']||{h:{},b:{}};"
    "function ap(el,a){for(var k in a){try{if(k==='class'){el.className=a[k]}else{el.setAttribute(k,a[k])}}catch(e){}}}"
    "ap(document.documentElement,m.h);"
    "if(document.body){ap(document.body,m.b)}else{new MutationObserver(function(_,o){"
    "if(document.body){ap(document.body,m.b);o.disconnect()}}).observe(document.documentElement,{childList:true})}})();"
)


def attrs_script(model: SiteModel) -> str:
    return ATTRS_SCRIPT.replace("__MAP__", json.dumps(attrs_map(model), ensure_ascii=False)
                                .replace("</", "<\\/"))


def nest_body_selectors(css: str) -> str:
    """``body > x`` -> ``body > #root > x`` (React SPA mounts in #root)."""
    return _BODY_CHILD_RE.sub(lambda m: "body" + m.group(1) + ">" + m.group(2) + "#root > ", css)


def page_middle_jsx(page: PageModel, ctx: JsxContext, asset_prefix: str = "", page_url=js_route) -> str:
    return nodes_to_jsx(detok_nodes(page.middle, asset_prefix, page_url), ctx)


def head_items_html(items: list[HeadItem]) -> str:
    return "\n".join(i.html() for i in items)
