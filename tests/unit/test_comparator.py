import io

import numpy as np
from PIL import Image

from app.modules.visual_comparator.comparator import compare


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype("uint8")).save(buf, format="PNG")
    return buf.getvalue()


def test_identical_images_ssim_one():
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, size=(200, 300, 3), dtype=np.uint8)
    png = _png(arr)
    res = compare(png, png)
    assert res["ssim"] > 0.99
    assert res["diff_ratio"] < 0.01
    assert res["issues"] == []
    assert isinstance(res["diff_png"], (bytes, bytearray))


def test_different_images_lower_ssim():
    a = np.zeros((200, 300, 3), dtype=np.uint8)
    b = np.full((200, 300, 3), 255, dtype=np.uint8)
    res = compare(_png(a), _png(b))
    assert res["ssim"] < 0.5
    assert res["diff_ratio"] > 0.5


def test_handles_different_heights():
    a = np.full((400, 300, 3), 120, dtype=np.uint8)
    b = np.full((250, 300, 3), 120, dtype=np.uint8)
    res = compare(_png(a), _png(b))
    assert res["height_original"] == 400
    assert res["height_generated"] == 250
    # Overlapping region is identical -> high similarity.
    assert res["ssim"] > 0.9
    assert any("shorter" in i for i in res["issues"])


def _rows_pattern(h: int, w: int = 300, period: int = 18) -> np.ndarray:
    """Text-like page: dark 'lines' on a light background + mild noise."""
    y = np.arange(h)
    base = np.full((h, w), 235.0)
    base[(y % period) < 3, :] = 60.0
    rng = np.random.default_rng(1)
    base = np.clip(base + rng.normal(0, 6, size=(h, w)), 0, 255)
    return np.repeat(base[:, :, None], 3, axis=2)


def test_tolerates_vertical_drift():
    """A faithful copy whose rows are offset vertically (re-render rounding) must
    still score high; a naive full-frame SSIM collapses on the same input."""
    h, w, shift = 800, 300, 12
    orig = _rows_pattern(h, w)
    gen = np.full_like(orig, 235.0)
    gen[shift:] = orig[: h - shift]            # same content, pushed down 12px
    res = compare(_png(orig), _png(gen))
    assert res["ssim"] > 0.9                   # drift absorbed (naive SSIM ~0.4)


def test_drift_alignment_does_not_rescue_different_content():
    """The bounded registration must not align genuinely different structure
    into a false match."""
    h, w = 800, 300
    rows = _rows_pattern(h, w)
    cols = np.transpose(rows, (1, 0, 2))[:h, :w]   # orthogonal line structure
    res = compare(_png(rows), _png(cols))
    assert res["ssim"] < 0.6
