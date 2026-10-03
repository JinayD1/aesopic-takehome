"""Experiment 1: Set-of-Mark vs pixel-coordinate grounding.

    uv run python -m experiments.run_grounding --runs 10 --repos openclaw/openclaw react/react pallets/flask

Each (arm, repo, run) is one full navigation. Results append to
results/grounding.jsonl, one row per run, and the script is resumable:
completed (arm, repo, run) triples are skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from navigator import prompts
from navigator.agent import Navigator, NavigatorConfig
from navigator.grounding import distance_to_nearest
from navigator.schemas import Interactable, RunResult, RunStatus

from .common import (
    RESULTS_DIR,
    TRACES_DIR,
    append_jsonl,
    field_correct,
    load_or_fetch_oracle,
    read_jsonl,
)

ARMS = ("som", "coords")
DEFAULT_REPOS = ("openclaw/openclaw", "react/react", "pallets/flask")


def _step_records(trace_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(trace_dir.glob("step_*.json"))]


def click_metrics(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run click statistics derived from the trace."""
    clicks = [s for s in steps if s["action"]["type"] == "click"]
    misclicks = [s for s in clicks if s.get("page_changed") is False]
    off_target = [s for s in clicks if s.get("clicked_at") and s.get("clicked_label") is None]
    invalid = [s for s in clicks if s.get("error")]
    errors_px: list[float] = []
    for s in clicks:
        at = s.get("clicked_at")
        if not at:
            continue
        items = [Interactable.model_validate(i) for i in s.get("interactables", [])]
        d = distance_to_nearest(at[0], at[1], items)
        if d is not None:
            errors_px.append(d)
    return {
        "clicks": len(clicks),
        "misclicks": len(misclicks),
        "off_target_clicks": len(off_target),
        "invalid_clicks": len(invalid),
        "mean_click_error_px": (sum(errors_px) / len(errors_px)) if errors_px else None,
        "max_click_error_px": max(errors_px) if errors_px else None,
    }


def score_run(result: RunResult, oracle: dict[str, Any], trace_dir: Path) -> dict[str, Any]:
    rel = result.latest_release
    nav_ok = "/releases" in (result.run.status_detail or "") or any(
        "/releases" in (s.get("after") or {}).get("url", "") for s in _step_records(trace_dir)
    )
    version_ok = field_correct("version", rel.version if rel else None, oracle)
    tag_ok = field_correct("tag", rel.tag if rel else None, oracle)
    commit_ok = field_correct("commit", rel.commit if rel else None, oracle)
    author_ok = field_correct("author", rel.author if rel else None, oracle)
    steps = _step_records(trace_dir)
    cm = click_metrics(steps)
    return {
        "task_success": bool(result.run.status is RunStatus.SUCCESS and version_ok and tag_ok),
        "navigation_success": bool(nav_ok),
        "status": result.run.status.value,
        "status_detail": result.run.status_detail,
        "steps": result.run.steps,
        "version_ok": version_ok,
        "tag_ok": tag_ok,
        "commit_ok": commit_ok,
        "author_ok": author_ok,
        "recovered": bool(cm["misclicks"] > 0 and result.run.status is RunStatus.SUCCESS),
        **cm,
        "model_latency_s": round(sum(s.get("model_latency_s", 0.0) for s in steps), 1),
        "wall_time_s": result.run.wall_time_s,
        "cost_usd": result.run.cost_usd,
        "input_tokens": result.run.usage.input_tokens,
        "output_tokens": result.run.usage.output_tokens,
        "verification": result.extraction.verification.value if result.extraction else None,
        "n_corrections": len(result.extraction.corrections) if result.extraction else None,
        "trace_dir": str(trace_dir),
    }


def one_run(arm: str, repo: str, run: int, model: str, max_steps: int) -> dict[str, Any]:
    oracle = load_or_fetch_oracle(repo)
    cfg = NavigatorConfig(
        model=model,
        grounding=arm,  # type: ignore[arg-type]
        extraction="verified",
        max_steps=max_steps,
        trace_root=TRACES_DIR / "grounding" / arm,
    )
    goal = prompts.repo_goal(repo)
    result = Navigator(cfg).run(goal, "https://github.com", f"{repo}-{run:02d}")
    row = {"experiment": "grounding", "arm": arm, "repo": repo, "run": run, "model": model}
    row.update(score_run(result, oracle, Path(result.run.trace_dir)))
    return row


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    p.add_argument("--repos", nargs="+", default=list(DEFAULT_REPOS))
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--model", default="claude-opus-5")
    p.add_argument("--max-steps", type=int, default=15)
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--out", type=Path, default=RESULTS_DIR / "grounding.jsonl")
    args = p.parse_args(argv)

    for repo in args.repos:
        o = load_or_fetch_oracle(repo)
        print(f"oracle {repo}: {o['repository']} {o['tag']} {o['commit_short']} {o['author']}")

    done = {(r["arm"], r["repo"], r["run"]) for r in read_jsonl(args.out)}
    todo = [
        (arm, repo, i)
        for i in range(args.runs)
        for repo in args.repos
        for arm in args.arms
        if (arm, repo, i) not in done
    ]
    print(f"{len(done)} rows already done, {len(todo)} to run, parallel={args.parallel}")

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(one_run, arm, repo, i, args.model, args.max_steps): (arm, repo, i)
            for arm, repo, i in todo
        }
        for fut in as_completed(futures):
            arm, repo, i = futures[fut]
            try:
                row = fut.result()
            except Exception as e:  # noqa: BLE001 - record and keep going
                row = {
                    "experiment": "grounding",
                    "arm": arm,
                    "repo": repo,
                    "run": i,
                    "model": args.model,
                    "task_success": False,
                    "navigation_success": False,
                    "status": "harness_error",
                    "status_detail": f"{type(e).__name__}: {e}",
                }
            append_jsonl(args.out, row)
            print(
                f"[{arm:6}] {repo:20} run {i:02d}: {row['status']:>22} "
                f"steps={row.get('steps')} ok={row['task_success']} ${row.get('cost_usd')}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
