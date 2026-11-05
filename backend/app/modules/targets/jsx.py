"""HTML -> JSX conversion for the React / Next.js outputs.

Produces real, editable JSX (``className``, style objects, ``htmlFor``...) while
guaranteeing a byte-faithful render:

* every text node is emitted as a JS string expression, so whitespace between
  inline elements is preserved exactly (JSX would otherwise collapse it),
* ``<svg>`` / ``<math>`` keep their root element in JSX but their children are
  injected verbatim (the HTML parser restores SVG tag/attribute casing),
* anything React cannot express faithfully - ``!important`` inline styles,
  declarative shadow DOM, namespaced tags, markup the HTML parser would
  restructure during hydration - is rendered through ``dangerouslySetInnerHTML``
  on its parent element, so nothing is ever lost or altered,
* table whitespace and implicit ``<tbody>`` are normalised to avoid hydration
  mismatches.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment, Doctype

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
RAW_CHILDREN = {"svg", "math"}
DROP = {"script", "noscript", "template"}
NO_WS_PARENTS = {"table", "thead", "tbody", "tfoot", "tr", "colgroup", "select", "optgroup",
                 "datalist", "frameset"}
BLOCKS_IN_P = {"address", "article", "aside", "blockquote", "details", "dialog", "div", "dl",
               "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
               "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol", "p", "pre",
               "section", "table", "ul"}
_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_ATTR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

ATTR_MAP = {
    "class": "className", "for": "htmlFor", "tabindex": "tabIndex", "readonly": "readOnly",
    "maxlength": "maxLength", "minlength": "minLength", "colspan": "colSpan",
    "rowspan": "rowSpan", "contenteditable": "contentEditable", "crossorigin": "crossOrigin",
    "srcset": "srcSet", "autoplay": "autoPlay", "playsinline": "playsInline",
    "frameborder": "frameBorder", "allowfullscreen": "allowFullScreen", "datetime": "dateTime",
    "enctype": "encType", "accept-charset": "acceptCharset", "http-equiv": "httpEquiv",
    "novalidate": "noValidate", "autocomplete": "autoComplete", "autofocus": "autoFocus",
    "cellpadding": "cellPadding", "cellspacing": "cellSpacing", "usemap": "useMap",
    "inputmode": "inputMode", "enterkeyhint": "enterKeyHint", "spellcheck": "spellCheck",
    "referrerpolicy": "referrerPolicy", "fetchpriority": "fetchPriority",
    "formaction": "formAction", "formnovalidate": "formNoValidate", "formmethod": "formMethod",
    "formtarget": "formTarget", "formenctype": "formEncType", "accesskey": "accessKey",
    "itemprop": "itemProp", "itemscope": "itemScope", "itemtype": "itemType", "itemid": "itemID",
    "itemref": "itemRef", "hreflang": "hrefLang", "charset": "charSet",
    "marginwidth": "marginWidth", "marginheight": "marginHeight", "srcdoc": "srcDoc",
    "srclang": "srcLang", "nomodule": "noModule", "controlslist": "controlsList",
    "disablepictureinpicture": "disablePictureInPicture",
    "disableremoteplayback": "disableRemotePlayback", "imagesrcset": "imageSrcSet",
    "imagesizes": "imageSizes", "popovertarget": "popoverTarget",
    "popovertargetaction": "popoverTargetAction", "ismap": "isMap", "allowtransparency": "allowTransparency",
    "xlink:href": "xlinkHref", "xmlns:xlink": "xmlnsXlink", "xml:lang": "xmlLang",
    "xml:space": "xmlSpace", "viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio",
}
BOOLEAN = {"allowfullscreen", "async", "autofocus", "autoplay", "checked", "controls", "default",
           "defer", "disabled", "formnovalidate", "hidden", "inert", "ismap", "itemscope", "loop",
           "multiple", "muted", "nomodule", "novalidate", "open", "playsinline", "readonly",
           "required", "reversed", "selected", "disablepictureinpicture", "disableremoteplayback"}


class JsxContext:
    def __init__(self, ssr: bool = True) -> None:
        self.ssr = ssr
        self.raw_fallbacks = 0


def _attr_str(v) -> str:
    return " ".join(v) if isinstance(v, list) else ("" if v is None else str(v))


def _camel_css(prop: str) -> str:
    prop = prop.strip()
    if prop.startswith("--"):
        return prop
    low = prop.lower()
    if low.startswith("-ms-"):
        low = "ms-" + low[4:]
    elif low.startswith("-"):
        low = low[1:]
        parts = low.split("-")
        return parts[0].capitalize() + "".join(p.capitalize() for p in parts[1:])
    parts = low.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _split_decls(style: str) -> list[str]:
    out, buf, depth, quote = [], [], 0, ""
    for ch in style:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def style_object(style: str) -> dict[str, str] | None:
    """Parse an inline style; ``None`` when it cannot be expressed in React."""
    obj: dict[str, str] = {}
    for decl in _split_decls(style):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        prop, val = prop.strip(), val.strip()
        if not prop or not val:
            continue
        if "!important" in val.replace(" ", "").lower():
            return None
        obj[_camel_css(prop)] = val
    return obj


def _problem(el: Tag, ctx: JsxContext) -> bool:
    """True if ``el`` itself cannot be expressed faithfully as JSX."""
    if not _TAG_RE.match(el.name or ""):
        return True
    if el.name == "template":
        return True
    st = el.get("style")
    if st and style_object(_attr_str(st)) is None:
        return True
    if ctx.ssr:
        parent = el.parent if isinstance(el.parent, Tag) else None
        if parent is not None:
            if parent.name == "p" and el.name in BLOCKS_IN_P:
                return True
            if el.name in ("a", "form", "button") and el.find_parent(el.name) is not None:
                return True
            if el.name == parent.name and el.name in ("li", "dt", "dd", "option", "h1", "h2", "h3", "h4", "h5", "h6"):
                return True
    return False


def _subtree_has_problem(el: Tag, ctx: JsxContext) -> bool:
    for d in el.find_all(True):
        if d.name in RAW_CHILDREN:
            continue
        if d.find_parent(RAW_CHILDREN) is not None:
            continue
        if _problem(d, ctx):
            return True
    return False


def _jsx_attrs(el: Tag, svg_root: bool = False) -> list[str]:
    out = []
    name = el.name
    attrs = dict(el.attrs)
    if name == "textarea":
        attrs.pop("value", None)
    for k, v in attrs.items():
        low = k.lower()
        if low.startswith("on") or low in ("xmlns:xlink",) and not svg_root:
            continue
        val = _attr_str(v)
        if low == "style":
            obj = style_object(val)
            if obj:
                out.append("style={" + json.dumps(obj, ensure_ascii=False) + "}")
            continue
        if name in ("input",) and low == "value":
            out.append("defaultValue={" + json.dumps(val, ensure_ascii=False) + "}")
            continue
        if name == "input" and low == "checked":
            out.append("defaultChecked")
            continue
        if name == "option" and low == "selected":
            continue  # handled on <select>
        if low.startswith(("data-", "aria-")):
            prop = low
        elif low in ATTR_MAP:
            prop = ATTR_MAP[low]
        elif svg_root and "-" in low:
            prop = _camel_css(low)
        else:
            prop = low
        if not _ATTR_RE.match(prop.replace(":", "")) or ":" in prop:
            continue
        if low in BOOLEAN and val in ("", low):
            out.append(prop)
            continue
        out.append(prop + "={" + json.dumps(val, ensure_ascii=False) + "}")
    if name == "select":
        sel = [o.get("value", o.get_text()) for o in el.find_all("option") if o.has_attr("selected")]
        if sel:
            value = sel if el.has_attr("multiple") else sel[0]
            out.append("defaultValue={" + json.dumps(value, ensure_ascii=False) + "}")
    if name == "textarea":
        out.append("defaultValue={" + json.dumps(el.get_text(), ensure_ascii=False) + "}")
    return out


def _open(el: Tag, extra: list[str] | None = None, svg_root: bool = False) -> str:
    parts = [el.name] + _jsx_attrs(el, svg_root) + (extra or [])
    return "<" + " ".join(parts)


def _raw(el: Tag, ctx: JsxContext, inner: str | None = None) -> str:
    ctx.raw_fallbacks += 1
    html = inner if inner is not None else el.decode_contents()
    if el.name in VOID:
        return _open(el) + " />"
    return _open(el, ["dangerouslySetInnerHTML={{ __html: " + json.dumps(html, ensure_ascii=False) + " }}"],
                 svg_root=el.name == "svg") + " />"


def node_to_jsx(node, ctx: JsxContext, children_slot: str | None = None, slot_el: Tag | None = None) -> str:
    """Convert one node. If ``slot_el`` is this element, its children become ``children_slot``."""
    if isinstance(node, (Comment, Doctype)):
        return ""
    if isinstance(node, NavigableString):
        text = str(node)
        parent = node.parent
        if not text.strip() and isinstance(parent, Tag) and parent.name in NO_WS_PARENTS:
            return ""
        return "{" + json.dumps(text, ensure_ascii=False) + "}" if text else ""
    if not isinstance(node, Tag):
        return ""
    name = node.name
    if name in DROP:
        return ""
    if name == "style":
        css = node.string or node.get_text()
        return _open(node, ["dangerouslySetInnerHTML={{ __html: " + json.dumps(css, ensure_ascii=False) + " }}"]) + " />"
    if name in RAW_CHILDREN:
        inner = node.decode_contents()
        if not inner.strip():
            return _open(node, svg_root=True) + " />"
        return _open(node, ["dangerouslySetInnerHTML={{ __html: " + json.dumps(inner, ensure_ascii=False) + " }}"],
                     svg_root=True) + " />"
    if name in VOID:
        return _open(node) + " />"
    if node is slot_el:
        return _open(node) + ">" + children_slot + "</" + name + ">"
    if name == "textarea":
        return _open(node) + " />"
    kids = list(node.children)
    if any(isinstance(k, Tag) and k.name not in DROP and _problem(k, ctx) for k in kids):
        return _raw(node, ctx)
    body = []
    pending_rows: list[str] = []
    for k in kids:
        if name == "table" and isinstance(k, Tag) and k.name == "tr":
            pending_rows.append(node_to_jsx(k, ctx, children_slot, slot_el))
            continue
        if pending_rows and not (isinstance(k, NavigableString) and not str(k).strip()):
            body.append("<tbody>" + "".join(pending_rows) + "</tbody>")
            pending_rows = []
        body.append(node_to_jsx(k, ctx, children_slot, slot_el))
    if pending_rows:
        body.append("<tbody>" + "".join(pending_rows) + "</tbody>")
    inner = "".join(body)
    if not inner:
        return _open(node) + " />"
    return _open(node) + ">" + inner + "</" + name + ">"


def nodes_to_jsx(nodes: list, ctx: JsxContext) -> str:
    """Convert top-level nodes into the body of a JSX fragment."""
    parts = []
    for n in nodes:
        if isinstance(n, Tag) and n.name not in DROP and _problem(n, ctx):
            # A top-level element React cannot express: keep it verbatim inside
            # a layout-neutral wrapper.
            ctx.raw_fallbacks += 1
            parts.append('<div style={{ display: "contents" }} dangerouslySetInnerHTML={{ __html: '
                         + json.dumps(str(n), ensure_ascii=False) + ' }} />')
        else:
            parts.append(node_to_jsx(n, ctx))
    return "".join(p for p in parts if p)


def html_to_nodes(html: str) -> list:
    """Parse an HTML fragment into top-level nodes (no html/body wrapping)."""
    return list(BeautifulSoup(html, "html.parser").contents)


def tag_with_slot(tag: Tag, slot: str, ctx: JsxContext) -> str:
    """Render a wrapper element whose children are replaced by ``slot``."""
    return _open(tag) + ">" + slot + "</" + tag.name + ">"
