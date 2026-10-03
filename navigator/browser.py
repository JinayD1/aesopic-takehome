"""Thin Playwright wrapper exposing only what a vision agent needs.

Design notes
------------
* Fixed 1280x800 viewport at device_scale_factor=1. The screenshot is then
  1.02 megapixels, under the Claude API's ~1.15 MP resize threshold, so the
  image the model sees has the same pixel grid as the viewport. Coordinate
  grounding depends on that 1:1 mapping.
* No page-specific selectors anywhere. ``scan_interactables`` uses only the
  HTML spec's notion of interactive content (anchors, buttons, form fields,
  ARIA widget roles). It would return the same kind of list on any website.
* Actions are executed by geometry (``mouse.click(x, y)``), never via element
  handles, so the model's choice is the only thing deciding what gets clicked.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .schemas import BoundingBox, Interactable, PageState

VIEWPORT = {"width": 1280, "height": 800}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# Generic interactive-content query. Nothing here knows about GitHub.
_INTERACTABLE_SELECTOR = ", ".join(
    [
        "a[href]",
        "button",
        "input:not([type=hidden])",
        "select",
        "textarea",
        "summary",
        "[role=button]",
        "[role=link]",
        "[role=tab]",
        "[role=menuitem]",
        "[role=menuitemradio]",
        "[role=menuitemcheckbox]",
        "[role=option]",
        "[role=checkbox]",
        "[role=radio]",
        "[role=switch]",
        "[role=combobox]",
        "[role=searchbox]",
        "[role=textbox]",
        "[onclick]",
        "[contenteditable=true]",
    ]
)

_SCAN_JS = """
(selector) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(selector)) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (r.bottom < 0 || r.right < 0 || r.top > vh || r.left > vw) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
    if (el.disabled) continue;
    // Occlusion test: the element (or a descendant) must be what the user
    // would actually hit at its visible centre.
    const cx = Math.max(0, Math.min(vw - 1, r.left + r.width / 2));
    const cy = Math.max(0, Math.min(vh - 1, r.top + r.height / 2));
    const hit = document.elementFromPoint(cx, cy);
    if (!hit || !(el === hit || el.contains(hit))) continue;
    // Dedupe identical boxes (e.g. an <a> wrapping a <button> of the same size).
    const key = [r.left, r.top, r.width, r.height].map(Math.round).join(',');
    if (seen.has(key)) continue;
    seen.add(key);
    const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder')
                  || el.getAttribute('title') || el.value || '').trim().replace(/\\s+/g, ' ');
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role'),
      text: text.slice(0, 120),
      box: { x: r.left, y: r.top, width: r.width, height: r.height },
    });
  }
  return out;
}
"""

_STATE_JS = """
() => ({
  scroll_y: window.scrollY,
  scroll_height: document.documentElement.scrollHeight,
})
"""


class BrowserSession:
    """Owns one Chromium page for the lifetime of a run."""

    def __init__(self, headless: bool = True, slow_mo_ms: int = 0) -> None:
        self._headless = headless
        self._slow_mo_ms = slow_mo_ms
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, slow_mo=self._slow_mo_ms)
        self._context = self._browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=1,
            user_agent=USER_AGENT,
            locale="en-US",
            color_scheme="light",
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(15_000)

    def close(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                with contextlib.suppress(Exception):
                    closer.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()

    def __enter__(self) -> BrowserSession:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def page(self) -> Page:
        assert self._page is not None, "BrowserSession not started"
        return self._page

    # -- observation -------------------------------------------------------

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.settle()

    def settle(self, idle_timeout_ms: int = 4_000, min_wait_ms: int = 400) -> None:
        """Wait for the page to stop changing, with a hard cap.

        GitHub uses Turbo-style navigation, so URL changes don't always fire a
        full load event. We wait for network idle up to a cap and never block
        the agent on it: a slow third-party beacon should not stall a run.
        """
        with contextlib.suppress(Exception):
            self.page.wait_for_load_state("networkidle", timeout=idle_timeout_ms)
        self.page.wait_for_timeout(min_wait_ms)

    def screenshot(self) -> bytes:
        return self.page.screenshot(type="png", full_page=False)

    def state(self) -> PageState:
        extra: dict[str, Any] = self.page.evaluate(_STATE_JS)
        return PageState(
            url=self.page.url,
            title=self.page.title(),
            viewport_width=VIEWPORT["width"],
            viewport_height=VIEWPORT["height"],
            scroll_y=float(extra.get("scroll_y", 0)),
            scroll_height=float(extra.get("scroll_height", 0)),
        )

    def scan_interactables(self) -> list[Interactable]:
        """Generic scan of visible interactive elements, labelled 1..N top-to-bottom."""
        raw: list[dict[str, Any]] = self.page.evaluate(_SCAN_JS, _INTERACTABLE_SELECTOR)
        raw.sort(key=lambda r: (round(r["box"]["y"] / 8), r["box"]["x"]))
        return [
            Interactable(
                label=i + 1,
                tag=r["tag"],
                role=r.get("role"),
                text=r.get("text", ""),
                box=BoundingBox(**r["box"]),
            )
            for i, r in enumerate(raw)
        ]

    def visible_text(self, max_chars: int = 20_000) -> str:
        """The page's rendered text, as a screen reader would see it.

        Used only by the extraction verifier. It is the whole body's innerText;
        no selectors, no knowledge of where GitHub puts anything.
        """
        text: str = self.page.evaluate("() => document.body.innerText")
        return text[:max_chars]

    # -- actions -----------------------------------------------------------

    def click(self, x: float, y: float) -> None:
        self.page.mouse.click(x, y)
        self.settle()

    def type_text(self, text: str, submit: bool = False) -> None:
        self.page.keyboard.type(text, delay=20)
        if submit:
            self.page.keyboard.press("Enter")
        self.settle()

    def scroll(self, direction: str, amount: int = 600) -> None:
        dy = amount if direction == "down" else -amount
        self.page.mouse.wheel(0, dy)
        self.page.wait_for_timeout(300)

    def press(self, key: str) -> None:
        self.page.keyboard.press(key)
        self.settle()


@contextlib.contextmanager
def open_browser(headless: bool = True, slow_mo_ms: int = 0) -> Iterator[BrowserSession]:
    session = BrowserSession(headless=headless, slow_mo_ms=slow_mo_ms)
    session.start()
    try:
        yield session
    finally:
        session.close()
