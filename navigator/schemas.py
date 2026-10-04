"""Typed data models shared across the navigator.

Everything the agent observes, decides, or emits is a pydantic model so that
the trace on disk, the tests, and the final JSON output all share one schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Observations
# --------------------------------------------------------------------------- #


class BoundingBox(BaseModel):
    """Viewport-space rectangle in CSS pixels."""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height


class Interactable(BaseModel):
    """One clickable/typeable element found by the generic DOM scan.

    The scan is deliberately page-agnostic: it looks for anchors, buttons,
    inputs and ARIA roles, never for anything GitHub-specific. ``text`` is
    kept for post-hoc analysis (did the click land on what the model meant?)
    and is NOT shown to the model in Set-of-Mark mode.
    """

    label: int
    tag: str
    role: str | None = None
    text: str = ""
    box: BoundingBox


class PageState(BaseModel):
    """What the harness knows about the page at observation time."""

    url: str
    title: str
    viewport_width: int
    viewport_height: int
    scroll_y: float = 0.0
    scroll_height: float = 0.0


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    PRESS = "press"
    BACK = "back"
    DONE = "done"
    ABORT = "abort"


class Action(BaseModel):
    """A single decision from the vision model, already validated.

    Exactly one grounding field is used for ``click``: ``label`` in
    Set-of-Mark mode or ``x``/``y`` in coordinate mode. ``reason`` is the
    model's one-line justification; it feeds loop detection and the
    wrong-target analysis in the experiments.
    """

    type: ActionType
    reason: str = ""
    # click (SoM)
    label: int | None = None
    # click (coords) - in *screenshot* pixel space; grounding scales to viewport
    x: float | None = None
    y: float | None = None
    # type
    text: str | None = None
    submit: bool = False
    # scroll
    direction: Literal["up", "down"] | None = None
    amount: int | None = None
    # press
    key: str | None = None
    # done / abort
    summary: str | None = None


# --------------------------------------------------------------------------- #
# Extraction output
# --------------------------------------------------------------------------- #


class DownloadLink(BaseModel):
    name: str
    url: str | None = None


class AssetRead(BaseModel):
    """What the model sees in the asset list; verified against page text afterwards."""

    names: list[str] = Field(default_factory=list)
    no_assets_visible: bool = False


class ReleaseInfo(BaseModel):
    """Structured description of the latest release as read from the page.

    ``version`` is the human-facing release title (often equal to the tag),
    ``tag`` is the git tag, ``commit`` is the short SHA shown next to the tag.
    The take-home's sample output calls the SHA "tag"; we expose both so the
    consumer can pick, and we say so in the README.
    """

    repository: str | None = None
    version: str | None = None
    tag: str | None = None
    commit: str | None = None
    author: str | None = None
    published_at: str | None = None
    is_prerelease: bool | None = None
    release_notes: str | None = None
    download_links: list[DownloadLink] = Field(default_factory=list)


class VerificationOutcome(str, Enum):
    AGREE = "agree"
    CORRECTED = "corrected"
    SKIPPED = "skipped"


class FieldCorrection(BaseModel):
    field: str
    vision_value: str | None
    text_value: str | None


class Extraction(BaseModel):
    """Result of the extraction step, including what verification changed."""

    release: ReleaseInfo
    vision_read: ReleaseInfo
    verification: VerificationOutcome
    corrections: list[FieldCorrection] = Field(default_factory=list)
    # release_notes is free text, so it is summarised rather than listed as a correction
    notes_corrected: bool = False
    notes_change: str | None = None


# --------------------------------------------------------------------------- #
# Run bookkeeping
# --------------------------------------------------------------------------- #


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    api_calls: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.api_calls += other.api_calls


class StepRecord(BaseModel):
    """Everything about one observe-think-act iteration, persisted to the trace."""

    index: int
    before: PageState
    action: Action
    after: PageState | None = None
    screenshot_path: str
    interactables: list[Interactable] = Field(default_factory=list)
    # viewport coords the harness actually clicked, if any
    clicked_at: tuple[float, float] | None = None
    # label of the interactable whose box contains clicked_at (post-hoc)
    clicked_label: int | None = None
    page_changed: bool | None = None
    model_latency_s: float = 0.0
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None


class RunStatus(str, Enum):
    SUCCESS = "success"
    ABORTED = "aborted"
    STEP_BUDGET = "step_budget_exhausted"
    LOOP_DETECTED = "loop_detected"
    TIMEOUT = "timeout"
    ERROR = "error"


class RunMeta(BaseModel):
    model: str
    grounding: Literal["som", "coords"]
    extraction: Literal["verified", "vision"]
    steps: int
    assets_steps: int = 0
    status: RunStatus
    status_detail: str | None = None
    usage: Usage
    cost_usd: float
    wall_time_s: float
    trace_dir: str
    started_at: str


class RunResult(BaseModel):
    """The JSON the CLI prints."""

    repository: str | None
    latest_release: ReleaseInfo | None
    extraction: Extraction | None = None
    run: RunMeta
    errors: list[str] = Field(default_factory=list)
