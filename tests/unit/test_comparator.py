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
