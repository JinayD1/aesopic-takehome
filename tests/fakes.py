"""Test doubles for the agent loop: a scripted model and an in-memory browser.

They let the replay tests exercise every branch of ``Navigator.run`` with no
network and no API key. The fake browser is a tiny state machine with a few
"pages"; the fake client replays a scripted list of actions.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from navigator.browser import VIEWPORT, BrowserSession
from navigator.llm import AssetsRead, Decision, ModelError, Read, VisionClient
from navigator.schemas import (
    Action,
    AssetRead,
    BoundingBox,
    Interactable,
    PageState,
    ReleaseInfo,
    Usage,
)


def _render(label: str, shade: int) -> bytes:
    img = Image.new("RGB", (VIEWPORT["width"], VIEWPORT["height"]), (shade, shade, shade))
    ImageDraw.Draw(img).text((20, 20), label, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class FakePage:
    url: str
    title: str
    shade: int
    interactables: list[Interactable]
    text: str = ""
    # label -> url the click navigates to
    links: dict[int, str] = field(default_factory=dict)


def _item(label: int, x: float, y: float, text: str = "") -> Interactable:
    return Interactable(
        label=label, tag="a", text=text, box=BoundingBox(x=x, y=y, width=120, height=24)
    )


HOME = "https://example.test/"
SEARCH = "https://example.test/search?q=openclaw"
REPO = "https://example.test/openclaw/openclaw"
RELEASES = "https://example.test/openclaw/openclaw/releases"

SITE: dict[str, FakePage] = {
    HOME: FakePage(HOME, "Home", 250, [_item(1, 1000, 20, "Search")], links={1: SEARCH}),
    SEARCH: FakePage(
        SEARCH,
        "Search",
        240,
        [_item(1, 300, 150, "openclaw/openclaw"), _item(2, 300, 300, "x/awesome-openclaw")],
        links={1: REPO},
    ),
    REPO: FakePage(
        REPO, "openclaw/openclaw", 230, [_item(1, 900, 400, "Releases")], links={1: RELEASES}
    ),
    RELEASES: FakePage(
        RELEASES,
        "Releases",
        220,
        [_item(1, 300, 200, "v2026.9.8")],
        text=(
            "Releases\nv2026.9.8 Latest\n77e703c\ngithub-actions[bot] released this 3 hours ago\n"
            "Assets 2\nopenclaw-macos.zip\nopenclaw-linux.tar.gz"
        ),
        links={},
    ),
}


class FakeBrowser(BrowserSession):
    """Minimal stand-in; never launches Playwright."""

    def __init__(self, site: dict[str, FakePage] | None = None) -> None:
        super().__init__(headless=True)
        self.site = site or SITE
        self.url = HOME
        self.scroll_y = 0.0
        self.clicks: list[tuple[float, float]] = []
        self.typed: list[str] = []
        self.started = False
        self.closed = False

    # lifecycle
    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    # observation
    @property
    def current(self) -> FakePage:
        return self.site[self.url]

    def goto(self, url: str) -> None:
        self.url = url

    def settle(self, idle_timeout_ms: int = 0, min_wait_ms: int = 0) -> None:
        pass

    def screenshot(self) -> bytes:
        return _render(f"{self.current.title} scroll={self.scroll_y}", self.current.shade)

    def state(self) -> PageState:
        return PageState(
            url=self.url,
            title=self.current.title,
            viewport_width=VIEWPORT["width"],
            viewport_height=VIEWPORT["height"],
            scroll_y=self.scroll_y,
            scroll_height=2000,
        )

    def scan_interactables(self) -> list[Interactable]:
        return list(self.current.interactables)

    def visible_text(self, max_chars: int = 20_000) -> str:
        return self.current.text

    def links_by_text(self, names: list[str]) -> dict[str, str]:
        return {n: f"https://example.test/download/{n}" for n in names if "openclaw" in n}

    # actions
    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))
        for item in self.current.interactables:
            if item.box.contains(x, y) and item.label in self.current.links:
                self.url = self.current.links[item.label]
                self.scroll_y = 0.0
                return

    def type_text(self, text: str, submit: bool = False) -> None:
        self.typed.append(text)

    def scroll(self, direction: str, amount: int = 600) -> None:
        self.scroll_y += amount if direction == "down" else -amount

    def press(self, key: str) -> None:
        pass

    def back(self) -> None:
        pass


class ScriptedClient(VisionClient):
    """Replays actions in order; raises ModelError on a ``None`` entry."""

    def __init__(
        self,
        actions: Sequence[Action | None],
        vision_read: ReleaseInfo | None = None,
        verified_read: ReleaseInfo | None = None,
    ) -> None:
        # Do not call super().__init__: no API client should be created.
        self.model = "fake-model"
        self._actions = list(actions)
        self._vision_read = vision_read or ReleaseInfo(
            repository="openclaw/openclaw",
            version="v2026.9.8",
            tag="v2026.9.8",
            commit="77e7O3c",
            author="github-actions[bot]",
        )
        self._verified_read = verified_read or self._vision_read.model_copy(
            update={"commit": "77e703c"}
        )
        self.decide_calls: list[str] = []
        self.asset_names: list[str] = ["openclaw-macos.zip", "openclaw-linux.tar.gz"]

    def decide(self, system: str, user_text: str, screenshot_png: bytes) -> Decision:
        self.decide_calls.append(user_text)
        if not self._actions:
            raise ModelError("script exhausted")
        nxt = self._actions.pop(0)
        if nxt is None:
            raise ModelError("scripted model failure")
        return Decision(
            action=nxt,
            usage=Usage(input_tokens=1000, output_tokens=50, api_calls=1),
            latency_s=0.01,
            raw_text="",
        )

    def read_release(self, screenshot_png: bytes) -> Read:
        return Read(release=self._vision_read, usage=Usage(api_calls=1), latency_s=0.01)

    def verify_release(self, vision_read: ReleaseInfo, page_text: str) -> Read:
        return Read(release=self._verified_read, usage=Usage(api_calls=1), latency_s=0.01)

    def read_assets(self, screenshot_png: bytes) -> AssetsRead:
        return AssetsRead(
            assets=AssetRead(names=list(self.asset_names), no_assets_visible=not self.asset_names),
            usage=Usage(api_calls=1),
            latency_s=0.01,
        )
