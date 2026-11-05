"""Framework-neutral model of a replicated site.

Every output target (React, Next.js, WordPress theme, headless WordPress) is
generated from the *verified* static build in ``site/``.  This module parses
that build once into a neutral representation:

* every URL is tokenised so each target can re-root it:
  ``{{A}}/assets/x.png`` for local files and ``{{P:slug}}`` for captured pages
  (``{{P:}}`` is the home page),
* each page keeps its exact ``<html>`` / ``<body>`` attributes, its ordered
  head styles (links + inline ``<style>``), and its body nodes,
* the markup shared by every page (header / footer / site wrapper) is
  detected structurally and exposed as a *shell* so targets can turn it into
  layout components, ``header.php`` / ``footer.php``, etc.
"""
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment

from app.modules.css_analyzer.css_tools import _URL_RE  # noqa: PLC2701 - shared regex

A = "{{A}}"
_PAGE_TOKEN_RE = re.compile(r"\{\{P:([a-z0-9-]*)\}\}")
_INJECTED_SCRIPT = "js/interactions.js"
_INJECTED_CSS = "css/responsive.css"
_URL_ATTRS = ("href", "src", "poster", "data")
_HEAD_LINK_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "mask-icon", "preload"}
_HEADER_HINT = re.compile(r"(^|[\s_-])(header|masthead|navbar|topbar|top-bar|site-header)([\s_-]|$)", re.I)
_FOOTER_HINT = re.compile(r"(^|[\s_-])(footer|colophon|site-footer)([\s_-]|$)", re.I)


def attrs_to_dict(tag: Tag) -> dict[str, str]:
    out = {}
    for k, v in tag.attrs.items():
        out[k] = " ".join(v) if isinstance(v, list) else ("" if v is None else str(v))
    return out


def node_html(node) -> str:
    return str(node)


def is_blank(node) -> bool:
    return isinstance(node, NavigableString) and not isinstance(node, Comment) and not str(node).strip()


def open_tag_sig(tag: Tag) -> str:
    return tag.name + json.dumps(attrs_to_dict(tag), sort_keys=True)


@dataclass
class HeadItem:
    kind: str                     # link | style | meta
    attrs: dict[str, str]
    css: str = ""

    def html(self) -> str:
        attrs = "".join(f' {k}="{_esc(v)}"' for k, v in self.attrs.items())
        if self.kind == "style":
            return f"<style{attrs}>{self.css}</style>"
        return f"<{self.kind}{attrs}>"

    def key(self) -> str:
        return self.html()


@dataclass
class PageModel:
    key: str                      # "" for home, else slug
    title: str
    source_url: str
    output_path: str
    html_attrs: dict[str, str]
    body_attrs: dict[str, str]
    head: list[HeadItem]
    description: str
    soup: BeautifulSoup
    body_nodes: list = field(default_factory=list)   # top-level body children
    middle: list = field(default_factory=list)       # nodes not covered by the shell

    @property
    def route(self) -> str:
        return "/" if not self.key else f"/{self.key}"

    def middle_html(self) -> str:
        return "".join(node_html(n) for n in self.middle)

    def body_html(self) -> str:
        return "".join(node_html(n) for n in self.body_nodes)


@dataclass
class Shell:
    """Markup shared by every page, wrapped around the page-specific middle."""
    prefix: list = field(default_factory=list)
    wrapper: Tag | None = None
    inner: "Shell | None" = None
    suffix: list = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.prefix and not self.suffix and self.wrapper is None

    def open_html(self) -> str:
        out = "".join(node_html(n) for n in self.prefix)
        if self.wrapper is not None:
            out += _open_tag_html(self.wrapper)
            if self.inner:
                out += self.inner.open_html()
        return out

    def close_html(self) -> str:
        out = ""
        if self.wrapper is not None:
            if self.inner:
                out += self.inner.close_html()
            out += f"</{self.wrapper.name}>"
        out += "".join(node_html(n) for n in self.suffix)
        return out


@dataclass
class SiteModel:
    pages: list[PageModel]
    shell: Shell
    lang: str
    site_name: str
    source_url: str
    post_chrome: Shell = field(default_factory=Shell)   # header/footer for non-replicated views

    def default_head(self) -> list[HeadItem]:
        """Home head without page-specific layout fixes (for posts, archives...)."""
        return [h for h in self.home.head
                if not (h.kind == "style" and h.attrs.get("id") in ("rx-fidelity", "rx-responsive"))]

    @property
    def home(self) -> PageModel:
        for p in self.pages:
            if p.key == "":
                return p
        return self.pages[0]

    def common_head(self) -> list[HeadItem]:
        """Head items present (identically) on every page, in home order."""
        if not self.pages:
            return []
        sets = [{h.key() for h in p.head} for p in self.pages]
        common = set.intersection(*sets)
        return [h for h in self.home.head if h.key() in common]


def _esc(v: str) -> str:
    return v.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _open_tag_html(tag: Tag) -> str:
    attrs = "".join(f' {k}="{_esc(v)}"' for k, v in attrs_to_dict(tag).items())
    return f"<{tag.name}{attrs}>"


def render_tokens(text: str, asset_prefix: str, page_url) -> str:
    """Replace tokens: ``asset_prefix`` for ``{{A}}``; ``page_url(key)`` for pages."""
    text = text.replace(A, asset_prefix)
    return _PAGE_TOKEN_RE.sub(lambda m: page_url(m.group(1)), text)


# --------------------------------------------------------------------------
# tokenisation
# --------------------------------------------------------------------------
class _Tokenizer:
    def __init__(self, root: Path, page_keys: dict[str, str]) -> None:
        self.root = root
        self.page_keys = page_keys          # output rel path -> key

    def url(self, value: str, page_dir: str) -> str:
        v = value.strip()
        if not v or v.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "{{", "about:", "blob:")):
            return value
        if re.match(r"^[a-z][a-z0-9+.-]*:", v, re.I) or v.startswith("//"):
            return value  # absolute (already purged by the sanitizer) - leave
        path, sep, rest = _split_suffix(v)
        joined = posixpath.normpath(posixpath.join(page_dir, path)) if page_dir else posixpath.normpath(path)
        if joined.startswith(".."):
            return value
        if joined in self.page_keys:
            return "{{P:" + self.page_keys[joined] + "}}" + sep + rest
        return f"{A}/{joined}{sep}{rest}"

    def css(self, text: str, page_dir: str) -> str:
        def sub(m):
            quote, ref = m.group(1), m.group(2)
            if ref.strip().startswith(("data:", "#")):
                return m.group(0)
            return f"url({quote}{self.url(ref, page_dir)}{quote})"
        return _URL_RE.sub(sub, text)

    def srcset(self, value: str, page_dir: str) -> str:
        parts = []
        for part in value.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            bits[0] = self.url(bits[0], page_dir)
            parts.append(" ".join(bits))
        return ", ".join(parts)

    def soup(self, soup: BeautifulSoup, page_dir: str) -> None:
        for el in soup.find_all(True):
            for attr in _URL_ATTRS:
                if isinstance(el.get(attr), str):
                    el[attr] = self.url(el[attr], page_dir)
            for attr in ("srcset", "imagesrcset"):
                if el.get(attr):
                    el[attr] = self.srcset(el[attr], page_dir)
            if el.get("style"):
                el["style"] = self.css(el["style"], page_dir)
            if el.get("srcdoc"):
                inner = BeautifulSoup(el["srcdoc"], "html.parser")
                self.soup(inner, page_dir)
                el["srcdoc"] = str(inner)
        for st in soup.find_all("style"):
            if st.string:
                st.string.replace_with(self.css(st.string, page_dir))


def _split_suffix(v: str) -> tuple[str, str, str]:
    for i, ch in enumerate(v):
        if ch in "?#":
            return v[:i], ch, v[i + 1:]
    return v, "", ""


# --------------------------------------------------------------------------
# shell detection
# --------------------------------------------------------------------------
def _elements(nodes: list) -> list:
    return [n for n in nodes if not is_blank(n)]


def _common_prefix(lists: list[list]) -> int:
    n = 0
    while all(len(lst) > n for lst in lists):
        ref = node_html(lists[0][n])
        if all(node_html(lst[n]) == ref for lst in lists[1:]):
            n += 1
        else:
            break
    return n


def _detect_shell(node_lists: list[list], depth: int = 0) -> tuple[Shell, list[list]]:
    """Return the shared shell and, per page, the remaining middle nodes."""
    lists = [_elements(nl) for nl in node_lists]
    shell = Shell()
    if not lists or any(not lst for lst in lists):
        return shell, lists
    if len(lists) == 1:
        lst = lists[0]
        i = 0
        while i < len(lst) - 1 and (_looks(lst[i], _HEADER_HINT, "header") or _is_skip_link(lst[i])):
            i += 1
        j = len(lst)
        while j - 1 > i and _looks(lst[j - 1], _FOOTER_HINT, "footer"):
            j -= 1
        pre, mid, suf = lst[:i], lst[i:j], lst[j:]
        if len(mid) > 1 and not pre:
            # Site wrapper (e.g. <div id="page">) followed by floating widgets:
            # keep the wrapper whose first child is the site header as middle.
            for k, node in enumerate(mid):
                kids = _elements(list(node.children)) if isinstance(node, Tag) else []
                if node.name in ("div", "section", "body") and kids and (
                        _looks(kids[0], _HEADER_HINT, "header")
                        or (len(kids) > 1 and _is_skip_link(kids[0]) and _looks(kids[1], _HEADER_HINT, "header"))):
                    pre, suf, mid = mid[:k], mid[k + 1:] + suf, [node]
                    break
    else:
        p = _common_prefix(lists)
        rev = [list(reversed(lst[p:])) for lst in lists]
        s = _common_prefix(rev)
        pre = lists[0][:p]
        suf = lists[0][len(lists[0]) - s:] if s else []
        mids = [lst[p:len(lst) - s] for lst in lists]
        lists = mids
        mid = None
    shell.prefix, shell.suffix = pre, suf
    mids = [mid] if len(node_lists) == 1 else lists
    # Descend into a wrapper element shared by every page (e.g. <div id="page">).
    if depth < 4 and all(len(m) == 1 and isinstance(m[0], Tag) for m in mids):
        sigs = {open_tag_sig(m[0]) for m in mids}
        if len(sigs) == 1 and mids[0][0].name not in ("main", "article") \
                and "!important" not in (mids[0][0].get("style") or ""):
            shell.wrapper = mids[0][0]
            inner, inner_mids = _detect_shell([list(m[0].children) for m in mids], depth + 1)
            shell.inner = inner
            return shell, inner_mids
    return shell, mids


def _is_skip_link(node) -> bool:
    return isinstance(node, Tag) and node.name == "a" and "skip" in " ".join(node.get("class") or []).lower()


def _looks(node, rx: re.Pattern, tagname: str) -> bool:
    if not isinstance(node, Tag):
        return False
    if node.name == tagname:
        return True
    ident = (node.get("id") or "") + " " + " ".join(node.get("class") or [])
    return bool(rx.search(ident)) and node.name in ("div", "section", "nav", "header", "footer")


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def build_model(site_dir: Path, page_records: list[dict], source_url: str) -> SiteModel:
    built = [r for r in page_records if r.get("status") == "built" and r.get("output_path")]
    built.sort(key=lambda r: (r["output_path"] != "index.html", r["output_path"]))
    page_keys: dict[str, str] = {}
    for r in built:
        rel = r["output_path"]
        page_keys[rel] = "" if rel == "index.html" else posixpath.splitext(posixpath.basename(rel))[0]
    tok = _Tokenizer(site_dir, page_keys)

    pages: list[PageModel] = []
    for r in built:
        rel = r["output_path"]
        path = site_dir / rel
        if not path.exists():
            continue
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
        page_dir = posixpath.dirname(rel)
        for s in soup.find_all("script", src=True):
            if s["src"].endswith(_INJECTED_SCRIPT):
                s.decompose()
        for link in soup.find_all("link", href=True):
            if link["href"].endswith(_INJECTED_CSS):
                link.decompose()
        for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
            c.extract()
        tok.soup(soup, page_dir)

        head_items: list[HeadItem] = []
        description = ""
        if soup.head:
            for el in soup.head.find_all(["link", "style", "meta"], recursive=True):
                if el.name == "link":
                    rels = {x.lower() for x in (el.get("rel") or [])}
                    if not rels & _HEAD_LINK_RELS:
                        continue
                    if "preload" in rels and (el.get("as") or "") not in ("font", "style", "image"):
                        continue
                    head_items.append(HeadItem("link", attrs_to_dict(el)))
                elif el.name == "style":
                    head_items.append(HeadItem("style", attrs_to_dict(el), el.string or el.get_text()))
                else:
                    name = (el.get("name") or "").lower()
                    if name == "description":
                        description = el.get("content") or ""
                    if name in ("description", "theme-color", "robots"):
                        head_items.append(HeadItem("meta", attrs_to_dict(el)))
        body = soup.body or soup
        nodes = [n for n in body.children if not isinstance(n, Comment)]
        nodes = [n for n in nodes if not (isinstance(n, Tag) and n.name == "script")]
        title = (soup.title.get_text(strip=True) if soup.title else "") or r.get("title") or ""
        pages.append(PageModel(
            key=page_keys[rel], title=title, source_url=r.get("url", ""), output_path=rel,
            html_attrs=attrs_to_dict(soup.html) if soup.html else {},
            body_attrs=attrs_to_dict(soup.body) if soup.body else {},
            head=head_items, description=description, soup=soup, body_nodes=nodes,
        ))

    shell, mids = _detect_shell([p.body_nodes for p in pages]) if pages else (Shell(), [])
    for p, m in zip(pages, mids):
        p.middle = m
    home = next((p for p in pages if p.key == ""), pages[0] if pages else None)
    site_name = ""
    if home:
        site_name = re.split(r"\s+[–|\-—:]\s+", home.title)[0].strip() or home.title
    post_chrome = Shell()
    if home is not None and home.middle:
        post_chrome, _ = _detect_shell([home.middle])
        if post_chrome.wrapper is None and not post_chrome.prefix and not post_chrome.suffix:
            post_chrome = Shell()
    return SiteModel(
        pages=pages, shell=shell, post_chrome=post_chrome,
        lang=(home.html_attrs.get("lang") if home else "") or "en",
        site_name=site_name or "Replicated site", source_url=source_url,
    )
