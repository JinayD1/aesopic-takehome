"""Second extraction pass: the release's downloadable assets.

Why a separate pass
-------------------
GitHub (and most release pages) collapse the asset list behind a disclosure.
Asking the navigator to expand it before saying ``done`` was measured to cost
five extra steps and to scroll the release header off-screen, so the core
fields came back null. One screenshot cannot hold both. So the core fields are
read first, from the screenshot at ``done``, and only then does this bounded
sub-task run: expand the list if needed, read the names, verify them against
the page text, and resolve each name to a real URL.

Everything here is site-agnostic: the sub-goal is prompt text, the name check
is "does this string appear in the rendered text", and URL resolution matches
an anchor by its visible text.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image

from . import prompts
from .browser import VIEWPORT, BrowserSession
from .grounding import GroundingError, GroundingMode, draw_som, resolve_click
from .llm import ModelError, VisionClient
from .schemas import ActionType, DownloadLink, Usage
from .trace import RunTrace

MAX_ASSET_STEPS = 4


@dataclass
class AssetsResult:
    links: list[DownloadLink] = field(default_factory=list)
    steps: int = 0
    usage: Usage = field(default_factory=Usage)
    errors: list[str] = field(default_factory=list)
    # names the model read that were not in the page text (dropped)
    unverified: list[str] = field(default_factory=list)
    none_visible: bool = False


def verify_names(names: list[str], page_text: str) -> tuple[list[str], list[str]]:
    """Keep names that appear verbatim (case-insensitive) in the rendered text."""
    haystack = page_text.lower()
    kept, dropped = [], []
    for n in names:
        n = n.strip()
        if n and n.lower() in haystack:
            kept.append(n)
        elif n:
            dropped.append(n)
    return kept, dropped


def collect_assets(
    client: VisionClient,
    browser: BrowserSession,
    trace: RunTrace,
    grounding: GroundingMode,
    log: Callable[[str], None],
) -> AssetsResult:
    result = AssetsResult()
    system = prompts.system_prompt(grounding, VIEWPORT["width"], VIEWPORT["height"])
    history: list[str] = []
    last_changed: bool | None = None

    for i in range(MAX_ASSET_STEPS):
        result.steps = i + 1
        before = browser.state()
        raw_png = browser.screenshot()
        interactables = browser.scan_interactables()
        shown = draw_som(raw_png, interactables) if grounding == "som" else raw_png
        trace.save_named_image(f"assets_step_{i + 1:02d}.png", shown)
        user_text = prompts.step_user_text(
            goal=prompts.ASSETS_GOAL,
            history=history,
            url=before.url,
            title=before.title,
            step_index=i,
            max_steps=MAX_ASSET_STEPS,
            last_page_changed=last_changed,
            stuck_hint=False,
        )
        try:
            decision = client.decide(system, user_text, shown)
        except ModelError as e:
            result.errors.append(f"assets step {i + 1}: {e}")
            break
        result.usage.add(decision.usage)
        action = decision.action
        trace.save_json(f"assets_step_{i + 1:02d}.json", action.model_dump(exclude_none=True))
        log(f"assets step {i + 1}: {action.type.value} {action.reason}")

        if action.type in (ActionType.DONE, ActionType.ABORT):
            result.none_visible = action.type is ActionType.ABORT
            break
        try:
            if action.type is ActionType.CLICK:
                size = Image.open(io.BytesIO(raw_png)).size
                x, y = resolve_click(
                    action, grounding, interactables, size, (VIEWPORT["width"], VIEWPORT["height"])
                )
                browser.click(x, y)
            elif action.type is ActionType.SCROLL:
                browser.scroll(action.direction or "down", action.amount or 600)
            elif action.type is ActionType.PRESS:
                browser.press(action.key or "End")
            elif action.type is ActionType.TYPE:
                browser.type_text(action.text or "", submit=action.submit)
            elif action.type is ActionType.BACK:
                browser.back()
        except GroundingError as e:
            result.errors.append(f"assets step {i + 1}: {e}")
            history.append(f"{i + 1}. {action.type.value} -> INVALID: {e}")
            continue
        after = browser.state()
        last_changed = after.url != before.url or abs(after.scroll_y - before.scroll_y) > 2
        history.append(
            f"{i + 1}. {action.type.value} ({action.reason}) -> "
            f"{'page changed' if last_changed else 'no visible change'}"
        )

    if result.none_visible:
        return result

    # Read the names from what is now on screen, then verify against the text.
    final_png = browser.screenshot()
    trace.save_named_image("assets_final.png", final_png)
    page_text = browser.visible_text()
    try:
        read = client.read_assets(final_png)
    except ModelError as e:
        result.errors.append(f"assets read: {e}")
        return result
    result.usage.add(read.usage)
    if read.assets.no_assets_visible:
        result.none_visible = True
        return result
    kept, dropped = verify_names(read.assets.names, page_text)
    result.unverified = dropped
    urls = browser.links_by_text(kept) if kept else {}
    result.links = [DownloadLink(name=n, url=urls.get(n)) for n in kept]
    return result
