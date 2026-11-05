"""Assorted helpers: hashing, filename/slug sanitation, URL<->path mapping."""
from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import re
from urllib.parse import unquote, urlparse

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("image/webp", ".webp")

# Asset category -> set of extensions.
CATEGORY_EXT: dict[str, set[str]] = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".ico"},
    "icons": {".svg"},
    "fonts": {".woff", ".woff2", ".ttf", ".otf", ".eot"},
    "videos": {".mp4", ".webm", ".ogg", ".mov", ".m4v"},
    "css": {".css"},
    "js": {".js", ".mjs"},
}
_EXT_CATEGORY: dict[str, str] = {ext: cat for cat, exts in CATEGORY_EXT.items() for ext in exts}

_CONTENT_TYPE_EXT = {
    "text/css": ".css",
    "text/javascript": ".js",
    "application/javascript": ".js",
    "application/x-javascript": ".js",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "font/ttf": ".ttf",
    "font/otf": ".otf",
    "application/font-woff": ".woff",
    "application/font-woff2": ".woff2",
    "application/vnd.ms-fontobject": ".eot",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/json": ".json",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def short_hash(text: str, length: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:length]


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def slugify(text: str, fallback: str = "page") -> str:
    text = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return text or fallback


def safe_filename(name: str, fallback: str = "file") -> str:
    name = unquote(name or "").strip().replace("\\", "/").split("/")[-1]
    name = _SAFE_NAME_RE.sub("_", name).strip("._")
    # Avoid absurdly long names.
    if len(name) > 120:
        root, dot, ext = name.rpartition(".")
        name = (root[:100] + dot + ext) if dot else name[:120]
    return name or fallback


def content_type_ext(content_type: str | None) -> str | None:
    if not content_type:
        return None
    ct = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(ct) or mimetypes.guess_extension(ct)


def ext_from_url(url: str) -> str:
    path = urlparse(url).path
    ext = posixpath.splitext(path)[1].lower()
    return ext if 0 < len(ext) <= 6 and ext.replace(".", "").isalnum() else ""


def categorize(ext: str, content_type: str | None = None) -> str:
    cat = _EXT_CATEGORY.get(ext.lower())
    if cat:
        return cat
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct.startswith("image/"):
            return "icons" if "svg" in ct else "images"
        if ct.startswith("video/"):
            return "videos"
        if ct.startswith("font/") or "font" in ct:
            return "fonts"
        if "css" in ct:
            return "css"
        if "javascript" in ct:
            return "js"
    return "other"


def same_site(host_a: str | None, host_b: str | None) -> bool:
    """True if two hosts belong to the same registrable site (www-insensitive).

    Uses a simple heuristic (exact match, or one is a subdomain of the other,
    or they share the last two labels) which is robust offline and adequate for
    scoping a single-site crawl.
    """
    if not host_a or not host_b:
        return False
    a = host_a.lower().lstrip(".")
    b = host_b.lower().lstrip(".")
    if a.startswith("www."):
        a = a[4:]
    if b.startswith("www."):
        b = b[4:]
    if a == b or a.endswith("." + b) or b.endswith("." + a):
        return True
    la, lb = a.split("."), b.split(".")
    return len(la) >= 2 and len(lb) >= 2 and la[-2:] == lb[-2:]
