"""Grounding: turning the model's decision into a viewport coordinate.

Two strategies, selectable per run so they can be compared head to head:

* ``som``   - Set-of-Mark. The harness draws a numbered badge on every visible
  interactable (found by the generic scan in ``browser.py``) and the model
  answers with a badge number. We click the centre of that element's box.
* ``coords`` - the model answers with an (x, y) in screenshot pixel space and
  we scale it into viewport space. With a 1x device scale factor and no API
  resizing the scale is 1.0, but it is kept explicit so the assumption is
  visible and testable.
"""

from __future__ import annotations

import io
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from .schemas import Action, ActionType, Interactable

GroundingMode = Literal["som", "coords"]

# A small palette that stays legible on both light and dark page regions.
_PALETTE = [
    (220, 38, 38),  # red
    (37, 99, 235),  # blue
    (22, 163, 74),  # green
    (217, 119, 6),  # amber
    (147, 51, 234),  # purple
    (13, 148, 136),  # teal
]


class GroundingError(ValueError):
    """The action could not be grounded to a point on screen."""


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow without size kwarg
        return ImageFont.load_default()


def draw_som(png: bytes, interactables: list[Interactable]) -> bytes:
    """Return a copy of ``png`` with a numbered badge on every interactable.

    Badges sit at the top-left corner of each element's box, outside the box
    when there is room above it, so the label does not cover the element's
    own text. Boxes get a thin outline in the same colour.
    """
    image = Image.open(io.BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font(13)

    for item in interactables:
        color = _PALETTE[(item.label - 1) % len(_PALETTE)]
        b = item.box
        x0, y0, x1, y1 = b.x, b.y, b.x + b.width, b.y + b.height
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)

        text = str(item.label)
        tx0, ty0, tx1, ty1 = draw.textbbox((0, 0), text, font=font)
        tw, th = tx1 - tx0, ty1 - ty0
        pad = 3
        bw, bh = tw + 2 * pad, th + 2 * pad
        # Prefer above the box; fall back to inside the top-left corner.
        bx = max(0, min(x0, image.width - bw))
        by = y0 - bh if y0 - bh >= 0 else y0
        draw.rectangle([bx, by, bx + bw, by + bh], fill=color)
        draw.text((bx + pad - tx0, by + pad - ty0), text, fill=(255, 255, 255), font=font)

    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def resolve_click(
    action: Action,
    mode: GroundingMode,
    interactables: list[Interactable],
    screenshot_size: tuple[int, int],
    viewport_size: tuple[int, int],
) -> tuple[float, float]:
    """Map a ``click`` action onto viewport coordinates."""
    if action.type is not ActionType.CLICK:
        raise GroundingError(f"resolve_click called with {action.type}")

    if mode == "som":
        if action.label is None:
            raise GroundingError("click in som mode requires a label")
        for item in interactables:
            if item.label == action.label:
                return item.box.center
        raise GroundingError(f"label {action.label} is not on screen (1..{len(interactables)})")

    if action.x is None or action.y is None:
        raise GroundingError("click in coords mode requires x and y")
    sx = viewport_size[0] / screenshot_size[0]
    sy = viewport_size[1] / screenshot_size[1]
    vx, vy = action.x * sx, action.y * sy
    if not (0 <= vx <= viewport_size[0] and 0 <= vy <= viewport_size[1]):
        raise GroundingError(f"({action.x}, {action.y}) is outside the screenshot")
    return vx, vy


def label_at(x: float, y: float, interactables: list[Interactable]) -> int | None:
    """Which interactable contains the point? Smallest box wins on overlap.

    Post-hoc analysis only: tells the experiments whether a coordinate click
    actually landed on an interactive element, and which one.
    """
    hits = [i for i in interactables if i.box.contains(x, y)]
    if not hits:
        return None
    return min(hits, key=lambda i: i.box.width * i.box.height).label


def distance_to_nearest(x: float, y: float, interactables: list[Interactable]) -> float | None:
    """Euclidean distance from a point to the nearest interactable centre."""
    if not interactables:
        return None
    distances = [
        float(((cx - x) ** 2 + (cy - y) ** 2) ** 0.5)
        for cx, cy in (i.box.center for i in interactables)
    ]
    return min(distances)
