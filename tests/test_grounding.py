"""Unit tests for grounding: overlay drawing, click resolution, post-hoc lookup."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from navigator.grounding import (
    GroundingError,
    distance_to_nearest,
    draw_som,
    label_at,
    resolve_click,
)
from navigator.schemas import Action, ActionType, BoundingBox, Interactable


def _item(label: int, x: float, y: float, w: float = 100, h: float = 20) -> Interactable:
    return Interactable(label=label, tag="a", box=BoundingBox(x=x, y=y, width=w, height=h))


def _blank_png(w: int = 1280, h: int = 800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class TestDrawSom:
    def test_returns_png_of_same_size(self) -> None:
        out = draw_som(_blank_png(), [_item(1, 10, 10), _item(2, 500, 300)])
        img = Image.open(io.BytesIO(out))
        assert img.size == (1280, 800)
        assert img.format == "PNG"

    def test_badge_is_drawn_near_element(self) -> None:
        out = draw_som(_blank_png(), [_item(1, 200, 200)])
        img = Image.open(io.BytesIO(out)).convert("RGB")
        # Badge sits just above the box's top-left corner; it should not be white.
        assert img.getpixel((203, 192)) != (255, 255, 255)
        # Far away pixels are untouched.
        assert img.getpixel((900, 700)) == (255, 255, 255)

    def test_badge_clamped_inside_image_at_top_edge(self) -> None:
        out = draw_som(_blank_png(), [_item(1, 0, 0)])
        img = Image.open(io.BytesIO(out)).convert("RGB")
        assert img.getpixel((3, 3)) != (255, 255, 255)

    def test_no_interactables_is_a_noop_copy(self) -> None:
        src = _blank_png()
        out = draw_som(src, [])
        assert Image.open(io.BytesIO(out)).tobytes() == Image.open(io.BytesIO(src)).tobytes()


class TestResolveClickSom:
    items = [_item(1, 100, 100), _item(2, 300, 400, w=50, h=50)]

    def test_label_maps_to_box_centre(self) -> None:
        a = Action(type=ActionType.CLICK, label=2)
        assert resolve_click(a, "som", self.items, (1280, 800), (1280, 800)) == (325, 425)

    def test_unknown_label_raises(self) -> None:
        a = Action(type=ActionType.CLICK, label=99)
        with pytest.raises(GroundingError, match="label 99"):
            resolve_click(a, "som", self.items, (1280, 800), (1280, 800))

    def test_missing_label_raises(self) -> None:
        a = Action(type=ActionType.CLICK, x=10, y=10)
        with pytest.raises(GroundingError, match="requires a label"):
            resolve_click(a, "som", self.items, (1280, 800), (1280, 800))


class TestResolveClickCoords:
    def test_identity_scale(self) -> None:
        a = Action(type=ActionType.CLICK, x=640, y=400)
        assert resolve_click(a, "coords", [], (1280, 800), (1280, 800)) == (640, 400)

    def test_downscaled_screenshot_is_rescaled(self) -> None:
        # A screenshot shrunk 2x by the API must map back onto the full viewport.
        a = Action(type=ActionType.CLICK, x=320, y=200)
        assert resolve_click(a, "coords", [], (640, 400), (1280, 800)) == (640, 400)

    def test_out_of_bounds_raises(self) -> None:
        a = Action(type=ActionType.CLICK, x=5000, y=10)
        with pytest.raises(GroundingError, match="outside"):
            resolve_click(a, "coords", [], (1280, 800), (1280, 800))

    def test_missing_coords_raises(self) -> None:
        a = Action(type=ActionType.CLICK, label=1)
        with pytest.raises(GroundingError, match="requires x and y"):
            resolve_click(a, "coords", [], (1280, 800), (1280, 800))

    def test_non_click_raises(self) -> None:
        a = Action(type=ActionType.SCROLL, direction="down")
        with pytest.raises(GroundingError):
            resolve_click(a, "coords", [], (1280, 800), (1280, 800))


class TestPostHocLookup:
    items = [
        _item(1, 0, 0, w=1280, h=60),  # a wide header bar
        _item(2, 10, 10, w=40, h=40),  # a small logo inside the header
        _item(3, 500, 500),
    ]

    def test_label_at_prefers_smallest_containing_box(self) -> None:
        assert label_at(20, 20, self.items) == 2
        assert label_at(600, 30, self.items) == 1

    def test_label_at_returns_none_when_missing(self) -> None:
        assert label_at(900, 700, self.items) is None

    def test_distance_to_nearest(self) -> None:
        assert distance_to_nearest(550, 510, self.items) == 0
        assert distance_to_nearest(550, 540, self.items) == pytest.approx(30)
        assert distance_to_nearest(0, 0, []) is None
