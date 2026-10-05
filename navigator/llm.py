"""Anthropic client wrapper: one call per navigation step, two for extraction.

Each navigation step is a *single-turn* request: system prompt, a text block
with the goal and the action history, and the current screenshot. We do not
keep a growing multi-turn transcript. That keeps cost flat per step, keeps the
agent's memory explicit (the history text is written to the trace), and
avoids replaying thinking blocks across turns.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic.types import (
    ImageBlockParam,
    Message,
    TextBlockParam,
    ToolChoiceAutoParam,
    ToolParam,
)
from pydantic import ValidationError

from . import prompts
from .schemas import Action, AssetRead, ReleaseInfo, Usage

DEFAULT_MODEL = "claude-opus-5"

# Default model per grounding mode, from the 120-run grounding experiment (ADR 001):
# with coordinates Sonnet 5 matched Opus 5 at 30/30 for 40% of the cost; with
# Set-of-Mark Sonnet 5 lost 3/30 runs to hallucinated badge numbers, Opus 5 none.
DEFAULT_MODEL_BY_GROUNDING: dict[str, str] = {
    "coords": "claude-sonnet-5",
    "som": "claude-opus-5",
}


def default_model(grounding: str) -> str:
    return DEFAULT_MODEL_BY_GROUNDING.get(grounding, DEFAULT_MODEL)


# USD per million tokens: (input, output, cache_read, cache_write)
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
}

# Haiku 4.5 predates adaptive thinking and the effort parameter.
_LEGACY_THINKING_MODELS = {"claude-haiku-4-5"}

BROWSER_ACTION_TOOL: ToolParam = {
    "name": "browser_action",
    "description": (
        "Perform exactly one browser action. Use `click` to click or focus an element, "
        "`type` to type into the focused element (set submit=true to press Enter after), "
        "`scroll` to scroll the page, `press` for a single key such as Enter or Escape, "
        "`back` to go to the previous page, `done` when the goal's information is visible, "
        "`abort` when the goal is impossible."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["click", "type", "scroll", "press", "back", "done", "abort"],
            },
            "reason": {
                "type": "string",
                "description": "One sentence: what you are clicking/typing and why.",
            },
            "label": {
                "type": ["integer", "null"],
                "description": "click (labelled mode): the badge number of the target element.",
            },
            "x": {
                "type": ["number", "null"],
                "description": "click (coordinate mode): x of the target centre in screenshot px.",
            },
            "y": {
                "type": ["number", "null"],
                "description": "click (coordinate mode): y of the target centre in screenshot px.",
            },
            "text": {"type": ["string", "null"], "description": "type: the text to type."},
            "submit": {
                "type": ["boolean", "null"],
                "description": "type: press Enter after typing.",
            },
            "direction": {
                "anyOf": [{"type": "string", "enum": ["up", "down"]}, {"type": "null"}],
                "description": "scroll: direction.",
            },
            "amount": {
                "type": ["integer", "null"],
                "description": "scroll: pixels, default 600.",
            },
            "key": {"type": ["string", "null"], "description": "press: key name, e.g. Enter."},
            "summary": {
                "type": ["string", "null"],
                "description": "done/abort: what is visible, or why the goal is unreachable.",
            },
        },
        "required": [
            "type",
            "reason",
            "label",
            "x",
            "y",
            "text",
            "submit",
            "direction",
            "amount",
            "key",
            "summary",
        ],
        "additionalProperties": False,
    },
}


class ModelError(RuntimeError):
    """The model returned something we could not turn into an action."""


@dataclass
class Decision:
    action: Action
    usage: Usage
    latency_s: float
    raw_text: str


@dataclass
class Read:
    release: ReleaseInfo
    usage: Usage
    latency_s: float


@dataclass
class AssetsRead:
    assets: AssetRead
    usage: Usage
    latency_s: float


def _usage(msg: Message) -> Usage:
    u = msg.usage
    return Usage(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_input_tokens=u.cache_read_input_tokens or 0,
        cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        api_calls=1,
    )


def cost_usd(model: str, usage: Usage) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    inp, out, cread, cwrite = rates
    return (
        usage.input_tokens * inp
        + usage.output_tokens * out
        + usage.cache_read_input_tokens * cread
        + usage.cache_creation_input_tokens * cwrite
    ) / 1_000_000


def _image_block(png: bytes) -> ImageBlockParam:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png).decode("ascii"),
        },
    }


def _text_block(text: str) -> TextBlockParam:
    return {"type": "text", "text": text}


class VisionClient:
    def __init__(self, model: str = DEFAULT_MODEL, timeout_s: float = 120.0) -> None:
        self.model = model
        # Keys that are not scoped to a workspace must name one per request.
        headers: dict[str, str] = {}
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        if workspace:
            headers["anthropic-workspace-id"] = workspace
        self._client = anthropic.Anthropic(
            timeout=timeout_s, max_retries=3, default_headers=headers or None
        )

    # -- request shaping ---------------------------------------------------

    def _thinking_kwargs(self, effort: str) -> dict[str, Any]:
        if self.model in _LEGACY_THINKING_MODELS:
            return {}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }

    # -- navigation --------------------------------------------------------

    def decide(self, system: str, user_text: str, screenshot_png: bytes) -> Decision:
        """Ask for the next action given the current screenshot."""
        t0 = time.perf_counter()
        system_blocks: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        tool_choice: ToolChoiceAutoParam = {"type": "auto", "disable_parallel_tool_use": True}
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_blocks,
            tools=[BROWSER_ACTION_TOOL],
            tool_choice=tool_choice,
            messages=[
                {
                    "role": "user",
                    "content": [_image_block(screenshot_png), _text_block(user_text)],
                }
            ],
            **self._thinking_kwargs("medium"),
        )
        latency = time.perf_counter() - t0

        if response.stop_reason == "refusal":
            raise ModelError("model refused the request")

        text_parts = [b.text for b in response.content if b.type == "text"]
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            raise ModelError(
                "model returned no browser_action call; text was: " + " ".join(text_parts)[:300]
            )
        raw = tool_uses[0].input
        if not isinstance(raw, dict):
            raise ModelError(f"unexpected tool input type {type(raw).__name__}")
        cleaned = {k: v for k, v in raw.items() if v is not None}
        try:
            action = Action.model_validate(cleaned)
        except ValidationError as e:
            raise ModelError(f"invalid action {cleaned!r}: {e}") from e

        return Decision(
            action=action,
            usage=_usage(response),
            latency_s=latency,
            raw_text=" ".join(text_parts),
        )

    # -- extraction --------------------------------------------------------

    def read_release(self, screenshot_png: bytes) -> Read:
        """Vision-only structured read of the latest release from a screenshot."""
        t0 = time.perf_counter()
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=4096,
            system=prompts.EXTRACT_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        _image_block(screenshot_png),
                        _text_block(prompts.EXTRACT_USER),
                    ],
                }
            ],
            output_format=ReleaseInfo,
            **self._thinking_kwargs("high"),
        )
        latency = time.perf_counter() - t0
        if response.stop_reason == "refusal":
            raise ModelError("model refused the extraction request")
        parsed = response.parsed_output
        if parsed is None:
            raise ModelError("extraction returned no parsed output")
        return Read(release=parsed, usage=_usage(response), latency_s=latency)

    def verify_release(self, vision_read: ReleaseInfo, page_text: str) -> Read:
        """Correct a vision read against the page's rendered text."""
        t0 = time.perf_counter()
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=4096,
            system=prompts.VERIFY_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": prompts.verify_user(
                        json.dumps(vision_read.model_dump(), indent=2), page_text
                    ),
                }
            ],
            output_format=ReleaseInfo,
            **self._thinking_kwargs("high"),
        )
        latency = time.perf_counter() - t0
        if response.stop_reason == "refusal":
            raise ModelError("model refused the verification request")
        parsed = response.parsed_output
        if parsed is None:
            raise ModelError("verification returned no parsed output")
        return Read(release=parsed, usage=_usage(response), latency_s=latency)

    def read_assets(self, screenshot_png: bytes) -> AssetsRead:
        """Structured read of the visible asset file names."""
        t0 = time.perf_counter()
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=2048,
            system=prompts.ASSETS_EXTRACT_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        _image_block(screenshot_png),
                        _text_block(prompts.ASSETS_EXTRACT_USER),
                    ],
                }
            ],
            output_format=AssetRead,
            **self._thinking_kwargs("medium"),
        )
        latency = time.perf_counter() - t0
        if response.stop_reason == "refusal":
            raise ModelError("model refused the assets request")
        parsed = response.parsed_output
        if parsed is None:
            raise ModelError("assets read returned no parsed output")
        return AssetsRead(assets=parsed, usage=_usage(response), latency_s=latency)
