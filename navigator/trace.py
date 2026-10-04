"""Per-run trace directory: every screenshot, decision and outcome on disk.

A run is only debuggable, and only usable as experiment data, if what the
model saw and what it decided are both preserved. The layout is flat so a
human can browse it:

    runs/20261003T183000_openclaw-openclaw/
        step_01.png            # exactly what the model saw (badges included in SoM mode)
        step_01.raw.png        # un-annotated screenshot (SoM mode only)
        step_01.json           # StepRecord
        final.png              # screenshot used for extraction
        page_text.txt          # visible text used by the verifier
        run.json               # RunResult
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .schemas import RunResult, StepRecord


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "run"


class RunTrace:
    def __init__(self, root: Path, name_hint: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.dir = root / f"{stamp}_{_slug(name_hint)}"
        self.dir.mkdir(parents=True, exist_ok=True)

    def step_image_path(self, index: int, raw: bool = False) -> Path:
        suffix = ".raw.png" if raw else ".png"
        return self.dir / f"step_{index + 1:02d}{suffix}"

    def save_step_image(self, index: int, png: bytes, raw: bool = False) -> Path:
        path = self.step_image_path(index, raw=raw)
        path.write_bytes(png)
        return path

    def save_step(self, record: StepRecord) -> None:
        path = self.dir / f"step_{record.index + 1:02d}.json"
        path.write_text(record.model_dump_json(indent=2))

    def save_named_image(self, name: str, png: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(png)
        return path

    def save_final_image(self, png: bytes) -> Path:
        path = self.dir / "final.png"
        path.write_bytes(png)
        return path

    def save_page_text(self, text: str) -> None:
        (self.dir / "page_text.txt").write_text(text)

    def save_run(self, result: RunResult) -> None:
        (self.dir / "run.json").write_text(result.model_dump_json(indent=2))

    def save_json(self, name: str, data: object) -> None:
        (self.dir / name).write_text(json.dumps(data, indent=2, default=str))
