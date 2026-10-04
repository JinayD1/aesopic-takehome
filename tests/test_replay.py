"""Replay tests: drive the whole agent loop with a scripted model and fake browser.

These prove the harness mechanics (execution, page-change detection, loop
detection, step budget, error handling, extraction wiring, trace output)
independently of any real model behaviour.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from navigator.agent import Navigator, NavigatorConfig
from navigator.schemas import Action, ActionType, RunStatus, VerificationOutcome

from .fakes import HOME, RELEASES, SITE, FakeBrowser, ScriptedClient

CLICK = ActionType.CLICK


def _nav(tmp_path: Path, client: ScriptedClient, browser: FakeBrowser, **cfg: object) -> Navigator:
    # The scripted happy path clicks by label, so these tests run in Set-of-Mark
    # mode unless a test says otherwise; coordinate mode has its own class below.
    cfg.setdefault("grounding", "som")
    cfg.setdefault("assets", False)  # the assets pass has its own tests below
    config = NavigatorConfig(trace_root=tmp_path, **cfg)  # type: ignore[arg-type]
    return Navigator(config, client=client, browser_factory=lambda: browser)


HAPPY_PATH = [
    Action(type=CLICK, label=1, reason="open search"),
    Action(type=CLICK, label=1, reason="open the exact repo"),
    Action(type=CLICK, label=1, reason="open releases"),
    Action(type=ActionType.DONE, summary="latest release visible"),
]


class TestHappyPath:
    def test_reaches_releases_and_extracts(self, tmp_path: Path) -> None:
        browser, client = FakeBrowser(), ScriptedClient(list(HAPPY_PATH))
        result = _nav(tmp_path, client, browser).run("goal", HOME, "t")

        assert result.run.status is RunStatus.SUCCESS
        assert result.run.steps == 4
        assert browser.url == RELEASES
        assert result.repository == "openclaw/openclaw"
        assert result.latest_release is not None
        assert result.latest_release.commit == "77e703c"  # corrected by verification
        assert result.extraction is not None
        assert result.extraction.verification is VerificationOutcome.CORRECTED
        assert [c.field for c in result.extraction.corrections] == ["commit"]
        assert browser.closed

    def test_vision_only_extraction_skips_verification(self, tmp_path: Path) -> None:
        browser, client = FakeBrowser(), ScriptedClient(list(HAPPY_PATH))
        result = _nav(tmp_path, client, browser, extraction="vision").run("goal", HOME, "t")
        assert result.extraction is not None
        assert result.extraction.verification is VerificationOutcome.SKIPPED
        assert result.latest_release is not None
        assert result.latest_release.commit == "77e7O3c"  # uncorrected

    def test_history_is_fed_back_to_the_model(self, tmp_path: Path) -> None:
        browser, client = FakeBrowser(), ScriptedClient(list(HAPPY_PATH))
        _nav(tmp_path, client, browser).run("find it", HOME, "t")
        last_prompt = client.decide_calls[-1]
        assert "GOAL: find it" in last_prompt
        assert "1. click #1 (open search) -> page changed" in last_prompt
        assert "3. click #1 (open releases) -> page changed" in last_prompt

    def test_trace_directory_has_everything(self, tmp_path: Path) -> None:
        browser, client = FakeBrowser(), ScriptedClient(list(HAPPY_PATH))
        result = _nav(tmp_path, client, browser).run("goal", HOME, "t")
        trace = Path(result.run.trace_dir)
        names = sorted(p.name for p in trace.iterdir())
        assert "run.json" in names
        assert "final.png" in names
        assert "page_text.txt" in names
        assert "step_01.png" in names and "step_01.raw.png" in names
        assert "step_04.json" in names
        step1 = json.loads((trace / "step_01.json").read_text())
        assert step1["action"]["type"] == "click"
        assert step1["clicked_label"] == 1
        assert step1["page_changed"] is True


class TestCoordinateMode:
    def test_coords_click_lands_and_is_attributed(self, tmp_path: Path) -> None:
        # Search link on HOME is at x=1000..1120, y=20..44 -> aim at its centre.
        actions = [
            Action(type=CLICK, x=1060, y=32, reason="search"),
            Action(type=ActionType.DONE, summary="ok"),
        ]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser, grounding="coords").run("g", HOME, "t")
        assert browser.clicks == [(1060, 32)]
        step1 = json.loads((Path(result.run.trace_dir) / "step_01.json").read_text())
        assert step1["clicked_label"] == 1  # post-hoc attribution still works

    def test_coords_miss_is_recorded_as_no_change(self, tmp_path: Path) -> None:
        actions = [
            Action(type=CLICK, x=50, y=700, reason="miss"),
            Action(type=ActionType.DONE, summary="ok"),
        ]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser, grounding="coords").run("g", HOME, "t")
        step1 = json.loads((Path(result.run.trace_dir) / "step_01.json").read_text())
        assert step1["clicked_label"] is None
        assert step1["page_changed"] is False
        assert "no visible change" in client.decide_calls[1]


class TestFailureModes:
    def test_step_budget_exhausted(self, tmp_path: Path) -> None:
        actions = [Action(type=ActionType.SCROLL, direction="down")] * 10
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser, max_steps=3).run("g", HOME, "t")
        assert result.run.status is RunStatus.STEP_BUDGET
        assert result.run.steps == 3
        assert result.latest_release is None

    def test_loop_detected_on_repeated_action(self, tmp_path: Path) -> None:
        # Clicking empty space on the same page, three times in a row.
        actions = [Action(type=CLICK, label=1)] * 6
        site_no_links = {HOME: dataclasses.replace(SITE[HOME], links={})}
        browser = FakeBrowser(site_no_links)
        result = _nav(tmp_path, ScriptedClient(actions), browser).run("g", HOME, "t")
        assert result.run.status is RunStatus.LOOP_DETECTED
        assert result.run.steps == 3

    def test_stuck_hint_appears_after_two_noops(self, tmp_path: Path) -> None:
        actions = [Action(type=ActionType.PRESS, key="Escape")] * 4
        browser, client = FakeBrowser(), ScriptedClient(actions)
        _nav(tmp_path, client, browser, max_steps=4).run("g", HOME, "t")
        assert "WARNING" not in client.decide_calls[1]
        assert "WARNING" in client.decide_calls[2]

    def test_abort_is_reported(self, tmp_path: Path) -> None:
        actions = [Action(type=ActionType.ABORT, summary="rate limited")]
        result = _nav(tmp_path, ScriptedClient(actions), FakeBrowser()).run("g", HOME, "t")
        assert result.run.status is RunStatus.ABORTED
        assert result.run.status_detail == "rate limited"

    def test_invalid_label_is_fed_back_not_fatal(self, tmp_path: Path) -> None:
        actions = [
            Action(type=CLICK, label=42, reason="bad label"),
            Action(type=ActionType.DONE, summary="ok"),
        ]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser).run("g", HOME, "t")
        assert result.run.status is RunStatus.SUCCESS
        assert any("label 42" in e for e in result.errors)
        assert "INVALID: label 42" in client.decide_calls[1]

    def test_single_model_error_is_tolerated(self, tmp_path: Path) -> None:
        actions: list[Action | None] = [None, *HAPPY_PATH]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser).run("g", HOME, "t")
        assert result.run.status is RunStatus.SUCCESS
        assert len(result.errors) == 1

    def test_consecutive_model_errors_end_the_run(self, tmp_path: Path) -> None:
        actions: list[Action | None] = [None, None, *HAPPY_PATH]
        result = _nav(tmp_path, ScriptedClient(actions), FakeBrowser()).run("g", HOME, "t")
        assert result.run.status is RunStatus.ERROR

    def test_browser_exception_becomes_json_error(self, tmp_path: Path) -> None:
        class Exploding(FakeBrowser):
            def screenshot(self) -> bytes:
                raise RuntimeError("browser crashed")

        browser = Exploding()
        result = _nav(tmp_path, ScriptedClient(list(HAPPY_PATH)), browser).run("g", HOME, "t")
        assert result.run.status is RunStatus.ERROR
        assert "browser crashed" in (result.run.status_detail or "")
        assert browser.closed
        assert Path(result.run.trace_dir, "run.json").is_file()

    def test_timeout(self, tmp_path: Path) -> None:
        browser, client = FakeBrowser(), ScriptedClient(list(HAPPY_PATH))
        result = _nav(tmp_path, client, browser, timeout_s=0.0).run("g", HOME, "t")
        assert result.run.status is RunStatus.TIMEOUT
        assert result.run.steps == 0


class TestAssetsPass:
    """The second extraction pass runs after the core fields are safe."""

    def test_assets_collected_and_verified(self, tmp_path: Path) -> None:
        # After the main loop's `done`, the assets pass asks for actions again:
        # one click to expand, then done.
        actions = [
            *HAPPY_PATH,
            Action(type=CLICK, label=1, reason="expand assets"),
            Action(type=ActionType.DONE, summary="file names visible"),
        ]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        # One hallucinated name that is not in the page text must be dropped.
        client.asset_names = ["openclaw-macos.zip", "openclaw-linux.tar.gz", "ghost.dmg"]
        result = _nav(tmp_path, client, browser, assets=True).run("goal", HOME, "t")

        assert result.run.status is RunStatus.SUCCESS
        assert result.latest_release is not None
        assert result.latest_release.commit == "77e703c"  # core fields untouched
        names = [d.name for d in result.latest_release.download_links]
        assert names == ["openclaw-macos.zip", "openclaw-linux.tar.gz"]
        assert result.latest_release.download_links[0].url == (
            "https://example.test/download/openclaw-macos.zip"
        )
        assert result.run.assets_steps == 2
        trace = Path(result.run.trace_dir)
        assert (trace / "assets_step_01.png").is_file()
        assert (trace / "assets_final.png").is_file()
        # The assets sub-goal, not the main goal, drove those steps.
        assert "downloadable files" in client.decide_calls[-1]

    def test_no_assets_visible_is_clean(self, tmp_path: Path) -> None:
        actions = [*HAPPY_PATH, Action(type=ActionType.ABORT, summary="no assets listed")]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser, assets=True).run("goal", HOME, "t")
        assert result.run.status is RunStatus.SUCCESS
        assert result.latest_release is not None
        assert result.latest_release.download_links == []
        assert result.errors == []

    def test_assets_pass_is_bounded(self, tmp_path: Path) -> None:
        # A model that never says done is cut off after MAX_ASSET_STEPS.
        actions = [*HAPPY_PATH, *([Action(type=ActionType.SCROLL, direction="down")] * 10)]
        browser, client = FakeBrowser(), ScriptedClient(actions)
        result = _nav(tmp_path, client, browser, assets=True).run("goal", HOME, "t")
        assert result.run.status is RunStatus.SUCCESS
        assert result.run.assets_steps == 4

    def test_skip_flag(self, tmp_path: Path) -> None:
        browser, client = FakeBrowser(), ScriptedClient(list(HAPPY_PATH))
        result = _nav(tmp_path, client, browser, assets=False).run("goal", HOME, "t")
        assert result.run.assets_steps == 0
        assert len(client.decide_calls) == 4
