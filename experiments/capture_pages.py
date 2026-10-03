"""Capture awkward release pages as fixed extraction samples.

These are *experiment fixtures*, not the product: we navigate straight to a
releases URL to get a screenshot + page text + oracle for pages whose shape
is unusual (pre-release on top, many assets, long notes, dark mode, no
releases). The navigator itself never does this.

    uv run python -m experiments.capture_pages
"""

from __future__ import annotations

import json
import sys

from navigator.browser import BrowserSession

from .common import PAGES_DIR, fetch_oracle

# name -> (repo, color_scheme)
CAPTURES: dict[str, tuple[str, str]] = {
    "openclaw-light": ("openclaw/openclaw", "light"),
    "openclaw-dark": ("openclaw/openclaw", "dark"),
    "react-long-notes": ("react/react", "light"),
    "flask": ("pallets/flask", "light"),
    "ollama-many-assets": ("ollama/ollama", "light"),
    "neovim-prerelease": ("neovim/neovim", "light"),
}


def capture(name: str, repo: str, scheme: str) -> None:
    out = PAGES_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    oracle = fetch_oracle(repo)
    (out / "oracle.json").write_text(json.dumps(oracle, indent=2))
    session = BrowserSession(headless=True)
    session.start()
    try:
        # Override colour scheme for the dark-mode fixture.
        session.page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
        session.goto(f"https://github.com/{oracle['repository']}/releases")
        (out / "final.png").write_bytes(session.screenshot())
        (out / "page_text.txt").write_text(session.visible_text())
    finally:
        session.close()
    print(f"captured {name}: {oracle['repository']} {oracle['tag']} ({scheme})")


def main() -> int:
    for name, (repo, scheme) in CAPTURES.items():
        if (PAGES_DIR / name / "final.png").is_file():
            print(f"skip {name} (exists)")
            continue
        try:
            capture(name, repo, scheme)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {name}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
