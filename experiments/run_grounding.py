"""Experiment 1: Set-of-Mark vs pixel-coordinate grounding.

    uv run python -m experiments.run_grounding --runs 10 --repos openclaw/openclaw react/react pallets/flask

Each (arm, repo, run) is one full navigation. Results append to
results/grounding.jsonl, one row per run, and the script is resumable:
completed (arm, repo, run) triples are skipped.
"""

from __future__ import annotations

import argparse
import json
import re
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


_STOP = {
    "the",
    "this",
    "that",
    "open",
    "click",
    "link",
    "button",
    "page",
    "section",
    "from",
    "into",
    "with",
    "repository",
    "repo",
    "sidebar",
    "find",
    "view",
    "main",
    "box",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOP}


def is_wrong_target(step: dict[str, Any], next_step: dict[str, Any] | None) -> bool:
    """Did the click land somewhere the model did not intend?

    Two conditions, both required, to keep false positives out:
    1. the model's `reason` shares no content word with the text of the element
       the click actually hit (so "open the search box" -> "Search or jump to"
       is fine);
    2. the model treated it as a mistake: its next action went back, or
       returned to the URL it was on before this click.
    """
    label = step.get("clicked_label")
    if label is None or next_step is None:
        return False
    hit = next((i for i in step.get("interactables", []) if i["label"] == label), None)
    if not hit or not hit.get("text"):
        return False
    if _words(step["action"].get("reason", "")) & _words(hit["text"]):
        return False
    went_back = next_step["action"]["type"] == "back"
    returned = (next_step.get("after") or {}).get("url") == step["before"]["url"]
    return bool(went_back or returned)


def click_metrics(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run click statistics derived from the trace."""
    clicks = [s for s in steps if s["action"]["type"] == "click"]
    misclicks = [s for s in clicks if s.get("page_changed") is False]
    off_target = [s for s in clicks if s.get("clicked_at") and s.get("clicked_label") is None]
    wrong_target = [
        s
        for i, s in enumerate(steps)
        if s["action"]["type"] == "click"
        and is_wrong_target(s, steps[i + 1] if i + 1 < len(steps) else None)
    ]
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
        "wrong_target_clicks": len(wrong_target),
        "wrong_target_detail": [
            f"step {s['index'] + 1}: wanted '{s['action'].get('reason', '')[:50]}' hit label "
            f"{s['clicked_label']} '{next(i['text'] for i in s['interactables'] if i['label'] == s['clicked_label'])[:40]}'"
            for s in wrong_target
        ],
        "invalid_clicks": len(invalid),
        "detour": len(steps) > 5,
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
        "recovered": bool(
            (cm["misclicks"] > 0 or cm["wrong_target_clicks"] > 0)
            and result.run.status is RunStatus.SUCCESS
        ),
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
        # Opus 5 (the original run) keeps grounding/<arm>; other models get their own tree.
        trace_root=TRACES_DIR / ("grounding" if model == "claude-opus-5" else f"grounding-{model}") / arm,
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
    p.add_argument(
        "--rescore",
        action="store_true",
        help="Recompute trace-derived metrics for existing rows (no API calls) and exit.",
    )
    args = p.parse_args(argv)

    if args.rescore:
        rows = read_jsonl(args.out)
        for row in rows:
            td = Path(row.get("trace_dir", ""))
            if td.is_dir():
                cm = click_metrics(_step_records(td))
                row.update(cm)
                row["recovered"] = bool(
                    (cm["misclicks"] > 0 or cm["wrong_target_clicks"] > 0)
                    and row.get("status") == "success"
                )
        args.out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
        print(f"rescored {len(rows)} rows")
        return 0

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
