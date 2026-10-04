"""The observe -> think -> act loop, plus the extraction phase.

The loop is deliberately small. Everything that makes it robust lives in a
handful of named mechanisms so they can be tested and discussed on their own:

* step budget and wall-clock timeout
* page-change detection (URL, title, scroll, and a pixel diff of the viewport)
* loop detection (same ineffective action on the same URL three times)
* a "stuck" hint injected into the prompt after repeated no-op actions
* grounding errors fed back to the model instead of crashing the run
"""

from __future__ import annotations

import io
import time
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from PIL import Image, ImageChops

from . import prompts
from .assets import collect_assets
from .browser import VIEWPORT, BrowserSession
from .grounding import GroundingError, GroundingMode, draw_som, label_at, resolve_click
from .llm import ModelError, VisionClient, cost_usd
from .schemas import (
    Action,
    ActionType,
    Extraction,
    FieldCorrection,
    PageState,
    ReleaseInfo,
    RunMeta,
    RunResult,
    RunStatus,
    StepRecord,
    Usage,
    VerificationOutcome,
)
from .trace import RunTrace

ExtractionMode = Literal["verified", "vision"]

# Fraction of viewport pixels that must differ for a screenshot to count as "changed".
_PIXEL_CHANGE_THRESHOLD = 0.005
_LOOP_REPEATS = 3
_STUCK_AFTER = 2
_MAX_CONSECUTIVE_MODEL_ERRORS = 2


@dataclass
class NavigatorConfig:
    model: str = "claude-opus-5"
    grounding: GroundingMode = "coords"
    extraction: ExtractionMode = "verified"
    max_steps: int = 15
    timeout_s: float = 300.0
    headless: bool = True
    slow_mo_ms: int = 0
    assets: bool = True
    trace_root: Path = field(default_factory=lambda: Path("runs"))


BrowserFactory = Callable[[], BrowserSession]


def _pixel_change_ratio(before_png: bytes, after_png: bytes) -> float:
    a = Image.open(io.BytesIO(before_png)).convert("L")
    b = Image.open(io.BytesIO(after_png)).convert("L")
    if a.size != b.size:
        return 1.0
    histogram = ImageChops.difference(a, b).histogram()
    changed = sum(histogram[25:])  # pixels whose luminance moved by more than ~10%
    return changed / (a.size[0] * a.size[1])


def _describe(index: int, action: Action, changed: bool | None, error: str | None) -> str:
    t = action.type
    if t is ActionType.CLICK:
        target = f"#{action.label}" if action.label is not None else f"({action.x}, {action.y})"
        what = f"click {target}"
    elif t is ActionType.TYPE:
        what = f'type "{action.text}"' + (" + Enter" if action.submit else "")
    elif t is ActionType.SCROLL:
        what = f"scroll {action.direction or 'down'}"
    elif t is ActionType.PRESS:
        what = f"press {action.key}"
    else:
        what = t.value
    reason = f" ({action.reason.strip()})" if action.reason else ""
    if error:
        outcome = f"INVALID: {error}"
    elif changed is None:
        outcome = ""
    else:
        outcome = "page changed" if changed else "no visible change"
    return f"{index + 1}. {what}{reason} -> {outcome}".rstrip(" ->")


def _signature(action: Action, url: str) -> tuple[object, ...]:
    return (
        action.type.value,
        action.label,
        None if action.x is None else round(action.x / 10),
        None if action.y is None else round(action.y / 10),
        action.text,
        action.key,
        action.direction,
        url,
    )


def repo_from_url(url: str) -> str | None:
    """owner/name from a GitHub-style URL path, or None. URL parsing, not DOM."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 2 and "." not in parts[0]:
        return f"{parts[0]}/{parts[1]}"
    return None


def normalise_repo(text: str | None) -> str | None:
    """'react / react' (as rendered in a page header) -> 'react/react'."""
    if not text:
        return None
    return "/".join(part.strip() for part in text.split("/")).strip() or None


_COMPARED_FIELDS = ("repository", "version", "tag", "commit", "author", "published_at")


def diff_release(vision: ReleaseInfo, verified: ReleaseInfo) -> list[FieldCorrection]:
    out: list[FieldCorrection] = []
    for name in _COMPARED_FIELDS:
        a, b = getattr(vision, name), getattr(verified, name)
        if (a or None) != (b or None):
            out.append(FieldCorrection(field=name, vision_value=a, text_value=b))
    return out


def notes_change_summary(vision: str | None, verified: str | None) -> str | None:
    """Word-level summary of how verification changed the free-text notes.

    Notes are not listed as a per-field correction because they are long; this
    says how many words changed so the output never reports 'agree' when the
    verifier rewrote part of the text.
    """
    a = (vision or "").split()
    b = (verified or "").split()
    if a == b:
        return None
    sa, sb = set(a), set(b)
    replaced = len(sa - sb)
    added = len(sb - sa)
    return f"{replaced} words replaced, {added} words added, {len(a)} -> {len(b)} words"


def extract_release(
    client: VisionClient, png: bytes, page_text: str, mode: ExtractionMode
) -> tuple[ReleaseInfo, Extraction, Usage]:
    """Return (the release to report, the audit trail, token usage)."""
    usage = Usage()
    vision = client.read_release(png)
    usage.add(vision.usage)
    if mode == "vision":
        return (
            vision.release,
            Extraction(vision_read=vision.release, verification=VerificationOutcome.SKIPPED),
            usage,
        )
    verified = client.verify_release(vision.release, page_text)
    usage.add(verified.usage)
    corrections = diff_release(vision.release, verified.release)
    notes_change = notes_change_summary(
        vision.release.release_notes, verified.release.release_notes
    )
    outcome = (
        VerificationOutcome.CORRECTED if corrections or notes_change else VerificationOutcome.AGREE
    )
    return (
        verified.release,
        Extraction(
            vision_read=vision.release,
            verification=outcome,
            corrections=corrections,
            notes_corrected=notes_change is not None,
            notes_change=notes_change,
        ),
        usage,
    )


class Navigator:
    def __init__(
        self,
        config: NavigatorConfig,
        client: VisionClient | None = None,
        browser_factory: BrowserFactory | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.client = client or VisionClient(model=config.model)
        self._browser_factory = browser_factory or (
            lambda: BrowserSession(headless=config.headless, slow_mo_ms=config.slow_mo_ms)
        )
        self._log = log or (lambda _msg: None)

    # ------------------------------------------------------------------ #

    def run(self, goal: str, start_url: str, name_hint: str) -> RunResult:
        cfg = self.config
        trace = RunTrace(cfg.trace_root, name_hint)
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        system = prompts.system_prompt(cfg.grounding, VIEWPORT["width"], VIEWPORT["height"])

        usage = Usage()
        errors: list[str] = []
        history: list[str] = []
        status = RunStatus.STEP_BUDGET
        status_detail: str | None = None
        steps = 0
        assets_steps = 0
        extraction: Extraction | None = None
        release: ReleaseInfo | None = None
        final_url: str | None = None

        browser = self._browser_factory()
        try:
            browser.start()
            browser.goto(start_url)
            self._log(f"opened {start_url}")

            last_changed: bool | None = None
            no_change_streak = 0
            model_error_streak = 0
            signatures: Counter[tuple[object, ...]] = Counter()

            for i in range(cfg.max_steps):
                if time.perf_counter() - started > cfg.timeout_s:
                    status, status_detail = RunStatus.TIMEOUT, f"exceeded {cfg.timeout_s:.0f}s"
                    break
                steps = i + 1

                # -- observe
                before = browser.state()
                raw_png = browser.screenshot()
                interactables = browser.scan_interactables()
                shown_png = draw_som(raw_png, interactables) if cfg.grounding == "som" else raw_png
                shown_path = trace.save_step_image(i, shown_png)
                if cfg.grounding == "som":
                    trace.save_step_image(i, raw_png, raw=True)

                user_text = prompts.step_user_text(
                    goal=goal,
                    history=history,
                    url=before.url,
                    title=before.title,
                    step_index=i,
                    max_steps=cfg.max_steps,
                    last_page_changed=last_changed,
                    stuck_hint=no_change_streak >= _STUCK_AFTER,
                )

                # -- think
                try:
                    decision = self.client.decide(system, user_text, shown_png)
                except ModelError as e:
                    model_error_streak += 1
                    errors.append(f"step {i + 1}: {e}")
                    history.append(f"{i + 1}. (no valid action returned by the model)")
                    self._log(f"step {i + 1}: model error: {e}")
                    if model_error_streak >= _MAX_CONSECUTIVE_MODEL_ERRORS:
                        status, status_detail = RunStatus.ERROR, str(e)
                        break
                    continue
                model_error_streak = 0
                usage.add(decision.usage)
                action = decision.action
                record = StepRecord(
                    index=i,
                    before=before,
                    action=action,
                    screenshot_path=str(shown_path),
                    interactables=interactables,
                    model_latency_s=decision.latency_s,
                    usage=decision.usage,
                )
                self._log(f"step {i + 1}: {action.type.value} {action.reason}")

                # -- terminal actions
                if action.type is ActionType.DONE:
                    status, status_detail = RunStatus.SUCCESS, action.summary
                    trace.save_step(record)
                    break
                if action.type is ActionType.ABORT:
                    status, status_detail = RunStatus.ABORTED, action.summary
                    trace.save_step(record)
                    break

                # -- act
                step_error: str | None = None
                try:
                    self._execute(browser, action, raw_png, record)
                except GroundingError as e:
                    step_error = str(e)
                    record.error = step_error
                    errors.append(f"step {i + 1}: {step_error}")

                after = browser.state()
                after_png = browser.screenshot()
                changed = (
                    after.url != before.url
                    or after.title != before.title
                    or abs(after.scroll_y - before.scroll_y) > 2
                    or _pixel_change_ratio(raw_png, after_png) > _PIXEL_CHANGE_THRESHOLD
                )
                record.after = after
                record.page_changed = changed
                trace.save_step(record)

                history.append(_describe(i, action, changed, step_error))
                last_changed = None if step_error else changed
                no_change_streak = 0 if changed else no_change_streak + 1

                # Only ineffective actions count toward a loop: scrolling a long
                # page five times is progress, clicking a dead spot three times is not.
                if not changed:
                    sig = _signature(action, before.url)
                    signatures[sig] += 1
                    if signatures[sig] >= _LOOP_REPEATS:
                        status = RunStatus.LOOP_DETECTED
                        status_detail = f"repeated {history[-1]!r} {_LOOP_REPEATS} times"
                        break

            final_url = browser.state().url

            # -- extraction
            if status is RunStatus.SUCCESS:
                final_png = browser.screenshot()
                trace.save_final_image(final_png)
                page_text = browser.visible_text()
                trace.save_page_text(page_text)
                try:
                    release, extraction, ex_usage = extract_release(
                        self.client, final_png, page_text, cfg.extraction
                    )
                    usage.add(ex_usage)
                    self._log(f"extraction: {extraction.verification.value}")
                except ModelError as e:
                    errors.append(f"extraction: {e}")
                    status, status_detail = RunStatus.ERROR, f"extraction failed: {e}"

            # -- assets: a separate bounded pass so it can never cost the core fields
            if status is RunStatus.SUCCESS and release is not None and cfg.assets:
                assets = collect_assets(self.client, browser, trace, cfg.grounding, self._log)
                usage.add(assets.usage)
                assets_steps = assets.steps
                errors.extend(assets.errors)
                release.download_links = assets.links
                self._log(
                    f"assets: {len(assets.links)} links in {assets.steps} steps"
                    + (
                        f", {len(assets.unverified)} unverified names dropped"
                        if assets.unverified
                        else ""
                    )
                    + (", none visible" if assets.none_visible else "")
                )

        except Exception as e:  # noqa: BLE001 - we want a JSON result, not a stack trace
            status, status_detail = RunStatus.ERROR, f"{type(e).__name__}: {e}"
            errors.append(traceback.format_exc(limit=3))
            self._log(f"error: {e}")
        finally:
            browser.close()

        if release is not None:
            release.repository = normalise_repo(release.repository)
        # The URL is exact; the header text is what the model read off pixels.
        repository = (repo_from_url(final_url) if final_url else None) or (
            release.repository if release else None
        )
        result = RunResult(
            repository=repository,
            latest_release=release,
            extraction=extraction,
            run=RunMeta(
                model=cfg.model,
                grounding=cfg.grounding,
                extraction=cfg.extraction,
                steps=steps,
                assets_steps=assets_steps,
                status=status,
                status_detail=status_detail,
                usage=usage,
                cost_usd=round(cost_usd(cfg.model, usage), 4),
                wall_time_s=round(time.perf_counter() - started, 1),
                trace_dir=str(trace.dir),
                started_at=started_at,
            ),
            errors=errors,
        )
        trace.save_run(result)
        return result

    # ------------------------------------------------------------------ #

    def _execute(
        self,
        browser: BrowserSession,
        action: Action,
        raw_png: bytes,
        record: StepRecord,
    ) -> None:
        cfg = self.config
        if action.type is ActionType.CLICK:
            size = Image.open(io.BytesIO(raw_png)).size
            x, y = resolve_click(
                action,
                cfg.grounding,
                record.interactables,
                screenshot_size=size,
                viewport_size=(VIEWPORT["width"], VIEWPORT["height"]),
            )
            record.clicked_at = (x, y)
            record.clicked_label = label_at(x, y, record.interactables)
            browser.click(x, y)
        elif action.type is ActionType.TYPE:
            browser.type_text(action.text or "", submit=action.submit)
        elif action.type is ActionType.SCROLL:
            browser.scroll(action.direction or "down", action.amount or 600)
        elif action.type is ActionType.PRESS:
            browser.press(action.key or "Enter")
        elif action.type is ActionType.BACK:
            browser.back()


def state_summary(state: PageState) -> str:
    return f"{state.url} | {state.title}"
