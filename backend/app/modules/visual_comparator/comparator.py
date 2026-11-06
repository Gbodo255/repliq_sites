"""Visual comparison between the original and the generated screenshots.

Implements a dependency-light SSIM (structural similarity) using numpy only -
local means/variances are computed with an integral-image box filter - plus a
pixel-difference ratio and a red-tinted diff image highlighting the regions
that differ.  Screenshots are aligned by cropping to the common top region
(full-page captures routinely differ in height).
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

_DIFF_THRESHOLD = 28          # per-channel abs diff considered "different"
_MAX_DIM = 1600               # downscale cap for speed


def _max_pixels() -> int:
    # The SSIM maps need ~12 float64 arrays of the image size: keep that small
    # on memory-constrained hosts.
    from app.config import settings
    return 600_000 if settings.low_memory else 2_400_000


def _load_rgb(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _align(a: Image.Image, b: Image.Image) -> tuple[np.ndarray, np.ndarray, int, int]:
    wa, ha = a.size
    wb, hb = b.size
    w = min(wa, wb)
    h = min(ha, hb)
    a = a.crop((0, 0, w, h))
    b = b.crop((0, 0, w, h))
    scale = min(1.0, _MAX_DIM / h if h > _MAX_DIM else 1.0, (_max_pixels() / float(w * h)) ** 0.5)
    if scale < 1.0:
        new = (max(1, int(w * scale)), max(1, int(h * scale)))
        a = a.resize(new)
        b = b.resize(new)
    return np.asarray(a), np.asarray(b), w, h


def _boxmean(img: np.ndarray, w: int) -> np.ndarray:
    ii = np.cumsum(np.cumsum(img, axis=0), axis=1)
    ii = np.pad(ii, ((1, 0), (1, 0)), mode="constant")
    s = ii[w:, w:] - ii[:-w, w:] - ii[w:, :-w] + ii[:-w, :-w]
    return s / float(w * w)


def _ssim_gray(a: np.ndarray, b: np.ndarray, win: int = 7, L: float = 255.0) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if min(a.shape) < win:
        win = max(1, min(a.shape))
    C1 = (0.01 * L) ** 2
    C2 = (0.03 * L) ** 2
    mu_a = _boxmean(a, win)
    mu_b = _boxmean(b, win)
    mu_a2, mu_b2, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    var_a = _boxmean(a * a, win) - mu_a2
    var_b = _boxmean(b * b, win) - mu_b2
    cov = _boxmean(a * b, win) - mu_ab
    num = (2 * mu_ab + C1) * (2 * cov + C2)
    den = (mu_a2 + mu_b2 + C1) * (var_a + var_b + C2)
    ssim_map = num / den
    return float(np.clip(ssim_map.mean(), -1.0, 1.0))


def compare(original_png: bytes, generated_png: bytes) -> dict:
    orig = _load_rgb(original_png)
    gen = _load_rgb(generated_png)
    wa, ha = orig.size
    wb, hb = gen.size
    a, b, common_w, common_h = _align(orig, gen)

    gray_a = a.mean(axis=2)
    gray_b = b.mean(axis=2)
    ssim = _ssim_gray(gray_a, gray_b)

    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
    mask = diff > _DIFF_THRESHOLD
    diff_ratio = float(mask.mean())

    # Build a red-tinted diff overlay on top of the generated capture.
    overlay = b.copy()
    overlay[mask] = (0.35 * overlay[mask] + np.array([0.65 * 255, 0, 0])).astype(np.uint8)
    diff_img = Image.fromarray(overlay)
    buf = io.BytesIO()
    diff_img.save(buf, format="PNG")

    issues = []
    if ssim < 0.6:
        issues.append(f"Low structural similarity (SSIM={ssim:.2f})")
    if diff_ratio > 0.35:
        issues.append(f"Large differing area ({diff_ratio*100:.0f}% of pixels)")
    if hb < 0.7 * ha:
        issues.append("Generated page is much shorter than the original (possible missing content)")
    elif hb > 1.4 * ha:
        issues.append("Generated page is much taller than the original (layout overflow)")

    return {
        "ssim": round(ssim, 4),
        "diff_ratio": round(diff_ratio, 4),
        "width": common_w,
        "height_original": ha,
        "height_generated": hb,
        "diff_png": buf.getvalue(),
        "issues": issues,
    }
