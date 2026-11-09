"""Write the player payloads (Lottie / Rive) of a captured page into the copy.

Payloads are written as small JS files that register themselves on
``window.__rxMedia`` (loaded with a <script> tag) instead of JSON fetched with
XHR: that works when the copy is opened straight from disk (``file://``), where
fetch/XHR of local files is blocked. The vendored players are copied only when a
site needs them; the Rive WebAssembly is shipped base64-encoded for the same
reason (a blob URL is built from it at runtime).
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from app.models.domain import RenderedPage

VENDOR_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "vendor"

LOTTIE_LIB = "js/vendor/lottie.min.js"
RIVE_LIB = "js/vendor/rive.js"
RIVE_WASM = "js/vendor/rive-wasm.js"


def write_page_media(root: Path, page: RenderedPage, rel: str, depth_prefix: str) -> tuple[dict, set[str]]:
    """Write this page's payload files; return (body attribute value, libs needed)."""
    media = page.media or {}
    if not media:
        return {}, set()
    tag = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    out_dir = root / "js" / "rx-media"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_lottie = {str(m["i"]): m for m in (page.analysis.get("lottie") or [])}
    meta_rive = {str(m["i"]): m for m in (page.analysis.get("rive") or [])}
    spec: dict = {"lottie": {}, "rive": {}}
    libs: set[str] = set()
    for key, payload in media.items():
        kind, _, idx = key.partition(":")
        name = f"{tag}-{kind}-{idx}"
        if kind == "lottie" and idx in meta_lottie:
            body = payload.decode("utf-8")
            libs.add("lottie")
            spec["lottie"][idx] = {"k": name, "src": f"{depth_prefix}js/rx-media/{name}.js",
                                   "loop": bool(meta_lottie[idx].get("loop", True))}
        elif kind == "rive" and idx in meta_rive:
            body = json.dumps(base64.b64encode(payload).decode("ascii"))
            libs.add("rive")
            spec["rive"][idx] = {"k": name, "src": f"{depth_prefix}js/rx-media/{name}.js"}
        else:
            continue
        (out_dir / f"{name}.js").write_text(
            f'(window.__rxMedia=window.__rxMedia||{{}})["{name}"]={body};', encoding="utf-8")
    if not libs:
        return {}, set()
    spec["lib"] = {"lottie": depth_prefix + LOTTIE_LIB, "rive": depth_prefix + RIVE_LIB,
                   "wasm": depth_prefix + RIVE_WASM}
    return spec, libs


def write_vendor(root: Path, libs: set[str]) -> None:
    """Copy the vendored players a replica needs into ``js/vendor``."""
    if not libs:
        return
    dst = root / "js" / "vendor"
    dst.mkdir(parents=True, exist_ok=True)
    if "lottie" in libs:
        (dst / "lottie.min.js").write_bytes((VENDOR_DIR / "lottie.min.js").read_bytes())
    if "rive" in libs:
        (dst / "rive.js").write_bytes((VENDOR_DIR / "rive.js").read_bytes())
        wasm = base64.b64encode((VENDOR_DIR / "rive.wasm").read_bytes()).decode("ascii")
        (dst / "rive-wasm.js").write_text(f'window.__rxRiveWasm="{wasm}";', encoding="utf-8")
