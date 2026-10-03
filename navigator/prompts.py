"""Prompts for the navigation and extraction models.

The system prompt is generic web-navigation guidance. Nothing in it names a
GitHub element, URL or layout; the task comes in through the goal text.
"""

from __future__ import annotations

from .grounding import GroundingMode

NAVIGATOR_SYSTEM = """\
You are a careful web-navigation agent. You see a screenshot of a browser \
viewport and decide ONE next action by calling the `browser_action` tool. \
You will be shown a new screenshot after every action.

Principles
- Read the page before acting. Confirm you are where you think you are by \
reading visible headings, URLs and labels in the screenshot.
- Prefer the most direct, human-like path: use the site's own search, links \
and buttons. Do not guess URLs.
- Take exactly one action per turn.
- If a banner, dialog or popup is in the way, dismiss it first.
- If the page did not change after your last action, do something different: \
scroll to reveal the target, press a key, or pick another element. Never \
repeat an action that already failed.
- When the goal names a specific item (for example an exact repository name), \
pick that exact item even if a similar one appears higher in a list. Sites \
redirect renamed or moved items: if you land on a page that is clearly the \
same project under a new name (same description, you arrived via its link), \
accept it and continue rather than going back.
- Call `done` as soon as the information the goal asks for is visible on \
screen. Do not keep clicking after that. Put a short plain-text summary of \
what is visible in `summary`.
- Call `abort` if the goal cannot be achieved (blocked, rate limited, item \
does not exist) and explain why in `summary`.
"""

SOM_INSTRUCTIONS = """\
Grounding mode: labelled elements. Every clickable or typeable element in the \
screenshot has a small coloured numbered badge at its top-left corner. To \
click or focus an element, give its badge number in `label`. Only numbers \
that appear in the screenshot are valid. To type, first click the input to \
focus it (or if it is already focused, type directly).
"""

COORDS_INSTRUCTIONS = """\
Grounding mode: pixel coordinates. The screenshot is {width}x{height} pixels. \
To click, give the `x` and `y` of the CENTRE of the target element in \
screenshot pixels, with (0, 0) at the top-left. Aim for the middle of the \
visible text or icon. To type, first click the input to focus it (or if it is \
already focused, type directly).
"""


def system_prompt(mode: GroundingMode, width: int, height: int) -> str:
    extra = (
        SOM_INSTRUCTIONS
        if mode == "som"
        else COORDS_INSTRUCTIONS.format(width=width, height=height)
    )
    return NAVIGATOR_SYSTEM + "\n" + extra


def repo_goal(repo: str, start_url: str = "https://github.com") -> str:
    """Goal text for the simple ``--repo owner/name`` interface."""
    owner, _, name = repo.partition("/")
    return (
        f"Starting from {start_url}, find the GitHub repository "
        f'"{repo}" (owner "{owner}", repository "{name}") by using the site search, '
        f"open that repository (or the repository it redirects to, if it has moved), "
        f'open its Releases section, and stop when the release marked "Latest" is on '
        f"screen with its details (version/tag, commit, author, date). If the top entry "
        f'is a pre-release, scroll or click until the one badged "Latest" is visible.'
    )


def prompt_goal(prompt: str, start_url: str) -> str:
    """Goal text for the free-form ``--prompt`` interface."""
    return (
        f"Starting from {start_url}, accomplish this request by navigating the site: "
        f"{prompt.strip()} Stop when the requested information is visible on screen."
    )


def step_user_text(
    goal: str,
    history: list[str],
    url: str,
    title: str,
    step_index: int,
    max_steps: int,
    last_page_changed: bool | None,
    stuck_hint: bool,
) -> str:
    """The text that accompanies each screenshot."""
    lines = [f"GOAL: {goal}", "", f"Step {step_index + 1} of at most {max_steps}."]
    lines.append(f"Current URL: {url}")
    lines.append(f"Page title: {title}")
    if history:
        lines.append("")
        lines.append("Actions so far (oldest first):")
        lines.extend(f"  {h}" for h in history)
    if last_page_changed is False:
        lines.append("")
        lines.append("NOTE: the page did NOT visibly change after your last action.")
    if stuck_hint:
        lines.append(
            "WARNING: several recent actions had no effect. You appear to be stuck. "
            "Try a different approach, or abort if the goal is unreachable."
        )
    lines.append("")
    lines.append("Decide the single next action.")
    return "\n".join(lines)


EXTRACT_SYSTEM = """\
You read a screenshot of a software project's release page and transcribe the \
details of the LATEST release into structured fields. "Latest" means the \
release the site badges as Latest (the newest stable release). If several \
releases are visible, pick the one with the Latest badge; a Pre-release badge \
disqualifies an entry unless nothing else is visible. Only report values you \
can actually see; leave a field null if it is not visible. Copy strings \
exactly as written, character for character. Do not infer, expand or \
normalise anything.
"""

EXTRACT_USER = """\
From this screenshot, extract the latest release:
- repository: the project's "owner/name" as displayed in the page header, if visible.
- version: the release title as displayed (often the same as the tag).
- tag: the git tag name.
- commit: the short commit hash shown near the tag, if visible.
- author: the username shown as having published the release.
- published_at: the date or relative time shown, exactly as written.
- is_prerelease: true if marked as pre-release, false if marked Latest, null if unclear.
- release_notes: the release notes text if visible (first ~1500 characters), else null.
- download_links: names of downloadable assets if listed, else an empty list.
"""

VERIFY_SYSTEM = """\
You verify a transcription made from a screenshot against the page's actual \
rendered text. The screenshot reading tells you WHICH release is the latest \
and roughly what its values are; the page text has the exact characters. For \
each field, if the page text contains a string that clearly corresponds to \
the screenshot reading but differs in characters (for example a misread hex \
digit), return the page-text version. If the screenshot reading is already \
present verbatim in the page text, keep it. If a field is not in the page \
text at all, keep the screenshot reading. Never invent values.
"""


def verify_user(vision_json: str, page_text: str) -> str:
    return (
        "Screenshot reading (JSON):\n"
        f"{vision_json}\n\n"
        "Rendered page text:\n"
        "-----\n"
        f"{page_text}\n"
        "-----\n\n"
        "Return the corrected release fields."
    )
