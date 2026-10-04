"""Unit tests for the agent's pure helpers: history text, loop signatures, diffs."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from navigator.agent import (
    _describe,
    _pixel_change_ratio,
    _signature,
    diff_release,
    normalise_repo,
    notes_change_summary,
    repo_from_url,
)
from navigator.schemas import Action, ActionType, ReleaseInfo


def _png(draw_box: bool) -> bytes:
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    if draw_box:
        ImageDraw.Draw(img).rectangle([0, 0, 100, 100], fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestDescribe:
    def test_click_with_label(self) -> None:
        a = Action(type=ActionType.CLICK, label=15, reason="open the repo")
        assert _describe(2, a, True, None) == "3. click #15 (open the repo) -> page changed"

    def test_click_with_coords(self) -> None:
        a = Action(type=ActionType.CLICK, x=10.0, y=20.0)
        assert _describe(0, a, False, None) == "1. click (10.0, 20.0) -> no visible change"

    def test_type_with_submit(self) -> None:
        a = Action(type=ActionType.TYPE, text="openclaw", submit=True)
        assert _describe(0, a, True, None) == '1. type "openclaw" + Enter -> page changed'

    def test_invalid_action_shows_error(self) -> None:
        a = Action(type=ActionType.CLICK, label=99)
        assert _describe(4, a, None, "label 99 is not on screen").endswith(
            "INVALID: label 99 is not on screen"
        )


class TestSignature:
    def test_same_click_same_url_is_same_signature(self) -> None:
        a = Action(type=ActionType.CLICK, label=3, reason="first try")
        b = Action(type=ActionType.CLICK, label=3, reason="second try")
        assert _signature(a, "https://x") == _signature(b, "https://x")

    def test_url_changes_signature(self) -> None:
        a = Action(type=ActionType.CLICK, label=3)
        assert _signature(a, "https://x") != _signature(a, "https://y")

    def test_nearby_coords_collapse(self) -> None:
        a = Action(type=ActionType.CLICK, x=100, y=200)
        b = Action(type=ActionType.CLICK, x=103, y=198)
        assert _signature(a, "u") == _signature(b, "u")


class TestPixelChange:
    def test_identical_is_zero(self) -> None:
        assert _pixel_change_ratio(_png(False), _png(False)) == 0

    def test_half_black_is_half(self) -> None:
        ratio = _pixel_change_ratio(_png(False), _png(True))
        assert 0.45 < ratio < 0.55

    def test_size_mismatch_counts_as_changed(self) -> None:
        small = io.BytesIO()
        Image.new("RGB", (10, 10)).save(small, format="PNG")
        assert _pixel_change_ratio(_png(False), small.getvalue()) == 1.0


class TestRepoFromUrl:
    def test_repo_page(self) -> None:
        assert repo_from_url("https://github.com/openclaw/openclaw") == "openclaw/openclaw"

    def test_releases_page(self) -> None:
        assert repo_from_url("https://github.com/openclaw/openclaw/releases") == (
            "openclaw/openclaw"
        )

    def test_search_page_is_not_a_repo(self) -> None:
        assert repo_from_url("https://github.com/search?q=openclaw") is None

    def test_homepage(self) -> None:
        assert repo_from_url("https://github.com/") is None


class TestDiffRelease:
    def test_no_difference(self) -> None:
        a = ReleaseInfo(version="v1", tag="v1", commit="abc1234")
        assert diff_release(a, a.model_copy()) == []

    def test_corrected_commit(self) -> None:
        vision = ReleaseInfo(tag="v1", commit="77e7O3c")  # letter O misread
        text = ReleaseInfo(tag="v1", commit="77e703c")
        diffs = diff_release(vision, text)
        assert len(diffs) == 1
        assert diffs[0].field == "commit"
        assert diffs[0].vision_value == "77e7O3c"
        assert diffs[0].text_value == "77e703c"

    def test_empty_and_none_are_equal(self) -> None:
        assert diff_release(ReleaseInfo(author=""), ReleaseInfo(author=None)) == []

    def test_release_notes_not_compared(self) -> None:
        a = ReleaseInfo(release_notes="long text A")
        b = ReleaseInfo(release_notes="long text B")
        assert diff_release(a, b) == []


class TestNormaliseRepo:
    def test_strips_spaces_around_slash(self) -> None:
        assert normalise_repo("react / react") == "react/react"

    def test_plain_passthrough(self) -> None:
        assert normalise_repo("openclaw/openclaw") == "openclaw/openclaw"

    def test_empty_is_none(self) -> None:
        assert normalise_repo("") is None
        assert normalise_repo(None) is None


class TestVerifyAssetNames:
    def test_keeps_names_present_in_text(self) -> None:
        from navigator.assets import verify_names

        kept, dropped = verify_names(["App.dmg", "ghost.zip", " App.dmg "], "Assets\napp.dmg\n")
        assert kept == ["App.dmg", "App.dmg"]
        assert dropped == ["ghost.zip"]

    def test_empty(self) -> None:
        from navigator.assets import verify_names

        assert verify_names([], "anything") == ([], [])


class TestNotesChangeSummary:
    def test_identical_is_none(self) -> None:
        assert notes_change_summary("a b c", "a b c") is None

    def test_misread_handles_are_counted(self) -> None:
        vision = "Thanks @obvivus @scottbuang"
        verified = "Thanks @obviyus @scotthuang @steipete"
        assert notes_change_summary(vision, verified) == (
            "2 words replaced, 3 words added, 3 -> 4 words"
        )

    def test_none_inputs(self) -> None:
        assert notes_change_summary(None, None) is None
        assert notes_change_summary(None, "x") == "0 words replaced, 1 words added, 0 -> 1 words"
