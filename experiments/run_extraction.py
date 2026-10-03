"""Experiment 2: vision-only extraction vs vision read verified against page text.

Paired design: both arms run on the *same* screenshot. Samples come from
(a) the final screenshots of successful grounding runs and (b) hand-captured
awkward pages under experiments/pages/<name>/ (final.png, page_text.txt,
oracle.json; see capture_pages.py).

    uv run python -m experiments.run_extraction --reps 3

One JSONL row per (sample, rep, arm). Resumable.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from navigator.agent import diff_release
from navigator.llm import VisionClient, cost_usd
from navigator.schemas import ReleaseInfo

from .common import (
    PAGES_DIR,
    RESULTS_DIR,
    TRACES_DIR,
    append_jsonl,
    char_error_rate,
    field_correct,
    load_or_fetch_oracle,
    read_jsonl,
)

FIELDS = ("repository", "version", "tag", "commit", "author")


def collect_samples(include_traces: bool = True) -> list[dict[str, Any]]:
    """Each sample: id, png path, page_text path, oracle dict, visible flags."""
    samples: list[dict[str, Any]] = []
    for d in sorted(PAGES_DIR.glob("*/")) if PAGES_DIR.is_dir() else []:
        if (d / "final.png").is_file() and (d / "oracle.json").is_file():
            samples.append(
                {
                    "id": f"page:{d.name}",
                    "png": d / "final.png",
                    "text": d / "page_text.txt",
                    "oracle": json.loads((d / "oracle.json").read_text()),
                    "source": "captured",
                }
            )
    if include_traces:
        for run_json in sorted((TRACES_DIR / "grounding").glob("*/*/run.json")):
            run = json.loads(run_json.read_text())
            if run["run"]["status"] != "success" or not run.get("repository"):
                continue
            d = run_json.parent
            if not (d / "final.png").is_file():
                continue
            samples.append(
                {
                    "id": f"trace:{d.parent.name}/{d.name}",
                    "png": d / "final.png",
                    "text": d / "page_text.txt",
                    "oracle": load_or_fetch_oracle(run["repository"]),
                    "source": "trace",
                }
            )
    return samples


def score_release(rel: ReleaseInfo, oracle: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in FIELDS:
        out[f"{f}_ok"] = field_correct(f, getattr(rel, f), oracle)
    out["record_ok"] = all(out[f"{f}_ok"] for f in ("version", "tag", "commit", "author"))
    out["commit_cer"] = char_error_rate(rel.commit, oracle["commit_short"])
    out["tag_cer"] = char_error_rate(rel.tag, oracle["tag"])
    out["commit_value"] = rel.commit
    out["tag_value"] = rel.tag
    out["author_value"] = rel.author
    out["version_value"] = rel.version
    return out


def one_sample(sample: dict[str, Any], rep: int, model: str) -> list[dict[str, Any]]:
    client = VisionClient(model=model)
    png = Path(sample["png"]).read_bytes()
    text = Path(sample["text"]).read_text() if Path(sample["text"]).is_file() else ""
    oracle = sample["oracle"]
    base = {
        "experiment": "extraction",
        "sample": sample["id"],
        "source": sample["source"],
        "rep": rep,
        "model": model,
        "repo": oracle["repository"],
    }

    vision = client.read_release(png)
    v_row = {
        **base,
        "arm": "vision",
        **score_release(vision.release, oracle),
        "latency_s": round(vision.latency_s, 1),
        "cost_usd": round(cost_usd(model, vision.usage), 4),
    }

    verified = client.verify_release(vision.release, text)
    corrections = diff_release(vision.release, verified.release)
    good = sum(1 for c in corrections if field_correct(c.field, c.text_value, oracle))
    bad = sum(
        1
        for c in corrections
        if field_correct(c.field, c.vision_value, oracle)
        and not field_correct(c.field, c.text_value, oracle)
    )
    t_row = {
        **base,
        "arm": "verified",
        **score_release(verified.release, oracle),
        "latency_s": round(vision.latency_s + verified.latency_s, 1),
        "cost_usd": round(cost_usd(model, vision.usage) + cost_usd(model, verified.usage), 4),
        "n_corrections": len(corrections),
        "corrections_right": good,
        "corrections_wrong": bad,
        "corrections": [c.model_dump() for c in corrections],
    }
    return [v_row, t_row]


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--model", default="claude-opus-5")
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--no-traces", action="store_true", help="Only use hand-captured pages.")
    p.add_argument("--out", type=Path, default=RESULTS_DIR / "extraction.jsonl")
    args = p.parse_args(argv)

    samples = collect_samples(include_traces=not args.no_traces)
    done = {(r["sample"], r["rep"]) for r in read_jsonl(args.out) if r["arm"] == "verified"}
    todo = [(s, rep) for rep in range(args.reps) for s in samples if (s["id"], rep) not in done]
    print(f"{len(samples)} samples, {len(done)} (sample, rep) pairs done, {len(todo)} to run")

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(one_sample, s, rep, args.model): (s["id"], rep) for s, rep in todo}
        for fut in as_completed(futures):
            sid, rep = futures[fut]
            try:
                rows = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  {sid} rep {rep}: ERROR {type(e).__name__}: {e}", flush=True)
                continue
            for row in rows:
                append_jsonl(args.out, row)
            v, t = rows
            print(
                f"  {sid:55} rep {rep}: vision record_ok={v['record_ok']} "
                f"commit={v['commit_value']} | verified record_ok={t['record_ok']} "
                f"corrections={t['n_corrections']}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
