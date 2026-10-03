"""Assemble a run's annotated step screenshots into an animated GIF.

    python -m navigator.tools.trace_gif runs/<trace-dir> docs/demo.gif

Each frame is the screenshot the model saw (badges included in SoM mode)
with a caption strip showing the step number and the model's stated reason.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CAPTION_H = 44


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def build(trace_dir: Path, out: Path, scale: float = 0.6, frame_ms: int = 1800) -> None:
    steps = sorted(trace_dir.glob("step_*.json"))
    frames: list[Image.Image] = []
    font = _font(16)
    for step_path in steps:
        step = json.loads(step_path.read_text())
        png = trace_dir / f"step_{step['index'] + 1:02d}.png"
        if not png.is_file():
            continue
        img = Image.open(png).convert("RGB")
        w, h = int(img.width * scale), int(img.height * scale)
        img = img.resize((w, h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (w, h + CAPTION_H), (24, 24, 27))
        canvas.paste(img, (0, 0))
        a = step["action"]
        target = f" #{a['label']}" if a.get("label") is not None else ""
        if a.get("x") is not None:
            target = f" ({a['x']:.0f},{a['y']:.0f})"
        caption = f"step {step['index'] + 1}: {a['type']}{target}  -  {a.get('reason', '')}"
        ImageDraw.Draw(canvas).text((12, h + 12), caption[:110], fill=(250, 250, 250), font=font)
        frames.append(canvas)
    final = trace_dir / "final.png"
    if final.is_file():
        img = Image.open(final).convert("RGB")
        w, h = int(img.width * scale), int(img.height * scale)
        img = img.resize((w, h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (w, h + CAPTION_H), (24, 24, 27))
        canvas.paste(img, (0, 0))
        ImageDraw.Draw(canvas).text(
            (12, h + 12),
            "extraction: structured read of this page",
            fill=(250, 250, 250),
            font=font,
        )
        frames.append(canvas)
    if not frames:
        raise SystemExit(f"no frames in {trace_dir}")
    out.parent.mkdir(parents=True, exist_ok=True)
    durations = [frame_ms] * len(frames)
    durations[-1] = frame_ms * 2
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"wrote {out} ({len(frames)} frames, {out.stat().st_size // 1024} KB)")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    build(Path(args[0]), Path(args[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
