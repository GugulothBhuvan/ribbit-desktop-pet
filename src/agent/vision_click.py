"""Vision-click math: turn a vision model's point into a real screen click.

The model sees a DOWNSCALED screenshot of one monitor and returns a pixel in
that image. Mapping back to a clickable screen coordinate must undo the
downscale AND add the monitor's virtual-desktop offset — the same coordinate
math that made non-primary-monitor capture come back blank. Kept as pure
functions so the arithmetic is unit-tested rather than trusted.
"""
import re
import json
from typing import Optional, Tuple


def parse_point(llm_text: str) -> Optional[Tuple[int, int]]:
    """Extracts a point from the model's JSON, e.g. {"found":true,"x":320,"y":110}
    (or {"found":false}). Returns (x, y) in the model's image space, or None."""
    data = _extract_json(llm_text)
    if not isinstance(data, dict):
        return None
    if data.get("found") is False:
        return None
    try:
        x = int(round(float(data["x"])))
        y = int(round(float(data["y"])))
    except (KeyError, TypeError, ValueError):
        return None
    return x, y


def map_to_screen(px: int, py: int, image_w: int, image_h: int,
                  geom: Tuple[int, int, int, int]) -> Tuple[int, int]:
    """Maps a point in the downscaled image to an absolute screen coordinate.

    geom = (gx, gy, gw, gh): the captured monitor's virtual-desktop rect.
    image_w/image_h: size of the (downscaled) image the model actually saw.
    """
    gx, gy, gw, gh = geom
    if image_w <= 0 or image_h <= 0:
        return gx, gy
    sx = gx + px * (gw / image_w)
    sy = gy + py * (gh / image_h)
    # Clamp inside the monitor so a bad model point can't fling the cursor off it.
    sx = min(max(sx, gx), gx + gw - 1)
    sy = min(max(sy, gy), gy + gh - 1)
    return int(round(sx)), int(round(sy))


def downscaled_size(gw: int, gh: int, max_dim: int) -> Tuple[int, int]:
    """The size the screenshot is downscaled to before the model sees it
    (aspect-preserving, longest side == max_dim). Must match vision.process_capture."""
    scale = min(1.0, max_dim / max(gw, gh)) if max(gw, gh) > 0 else 1.0
    return max(1, round(gw * scale)), max(1, round(gh * scale))


def _extract_json(text: str):
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start:end + 1] if 0 <= start < end else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None
