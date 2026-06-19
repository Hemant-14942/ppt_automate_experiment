"""
Crop a rectangular region out of a rendered PDF page image.

Used by the interactive "Diagrams & Formulas" review: the extractor reports a
diagram's bounding box as PERCENTAGES of the page, and this helper turns that
box into an actual cropped PNG the frontend can preview (and later phases can
embed into a slide).

Bounding boxes from Gemini are approximate, so a small padding is added around
the box to avoid clipping labels/axis ticks at the edges of a diagram.
"""
from __future__ import annotations

import io
import base64
from typing import Optional


def crop_page_region(
    page_base64: str,
    bbox: Optional[dict],
    pad_percent: float = 2.5,
) -> bytes:
    """
    Crop `bbox` (a {"x","y","w","h"} dict in 0-100 percentages) from the page.

    Returns PNG bytes. If `bbox` is missing/empty or degenerate, returns the
    full page so the caller always gets a usable image rather than an error.
    """
    from PIL import Image  # local import — PIL is only needed on this path

    raw = base64.b64decode(page_base64)
    img = Image.open(io.BytesIO(raw))
    W, H = img.size

    def _full() -> bytes:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    if not bbox:
        return _full()

    try:
        bx = float(bbox.get("x", 0))
        by = float(bbox.get("y", 0))
        bw = float(bbox.get("w", 0))
        bh = float(bbox.get("h", 0))
    except (TypeError, ValueError):
        return _full()

    if bw <= 0 or bh <= 0:
        return _full()

    # Apply padding, then clamp to the page.
    x1 = max(0.0, (bx - pad_percent)) / 100.0 * W
    y1 = max(0.0, (by - pad_percent)) / 100.0 * H
    x2 = min(100.0, (bx + bw + pad_percent)) / 100.0 * W
    y2 = min(100.0, (by + bh + pad_percent)) / 100.0 * H

    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    if x2 <= x1 or y2 <= y1:
        return _full()

    crop = img.crop((x1, y1, x2, y2))
    buf = io.BytesIO()
    crop.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
