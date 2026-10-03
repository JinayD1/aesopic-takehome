"""Turn results/*.jsonl into the experiment reports.

    uv run python -m experiments.analyze

Writes experiments/RESULTS_grounding.md and experiments/RESULTS_extraction.md.
Pure function of the JSONL files, so anyone can re-run it.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import EXP_DIR, RESULTS_DIR, fmt_rate, median, percentile, read_jsonl, wilson


def _rate(rows: list[dict[str, Any]], key: str) -> str:
    return fmt_rate(sum(1 for r in rows if r.get(key)), len(rows))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def _f(x: float, nd: int = 1) -> str:
    return "–" if x != x else f"{x:.{nd}f}"  # NaN check


# --------------------------------------------------------------------------- #
# Grounding
# --------------------------------------------------------------------------- #


def grounding_report(rows: list[dict[str, Any]]) -> str:
    arms = sorted({r["arm"] for r in rows})
    repos = sorted({r["repo"] for r in rows})
    by_arm = {a: [r for r in rows if r["arm"] == a] for a in arms}
    lines = [
        "# Experiment 1: Set-of-Mark vs pixel-coordinate grounding",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='minutes')} from "
        f"`results/grounding.jsonl` ({len(rows)} runs)._",
        "",
        "**Question.** Does labelling interactables with numbered badges (Set-of-Mark) "
        "navigate more reliably than asking the model for raw pixel coordinates?",
        "",
        "**Design.** Same model, prompt, viewport and goal text; only the grounding "
        "mode differs. Each run is a full navigation from github.com to the releases "
        "page followed by verified extraction. Scored against a frozen GitHub API "
        "snapshot (`oracle/`). Intervals are 95% Wilson.",
        "",
        "## Headline",
        "",
        "| Metric | " + " | ".join(arms) + " |",
        "|---|" + "---|" * len(arms),
    ]

    def row(label: str, fn: Any) -> str:
        return f"| {label} | " + " | ".join(fn(by_arm[a]) for a in arms) + " |"

    lines += [
        row("**Task success** (version + tag match oracle)", lambda rs: _rate(rs, "task_success")),
        row("Navigation success (reached /releases)", lambda rs: _rate(rs, "navigation_success")),
        row(
            "Steps, median (p90)",
            lambda rs: (
                f"{_f(median([r['steps'] for r in rs if r.get('steps')]), 0)} ({_f(percentile([r['steps'] for r in rs if r.get('steps')], 0.9), 0)})"
            ),
        ),
        row(
            "Misclick rate (clicks with no page change)",
            lambda rs: fmt_rate(
                sum(r.get("misclicks", 0) for r in rs), sum(r.get("clicks", 0) for r in rs)
            ),
        ),
        row(
            "Off-target clicks (landed on no interactable)",
            lambda rs: fmt_rate(
                sum(r.get("off_target_clicks", 0) for r in rs), sum(r.get("clicks", 0) for r in rs)
            ),
        ),
        row(
            "**Wrong-target clicks** (hit an element unrelated to the stated intent)",
            lambda rs: fmt_rate(
                sum(r.get("wrong_target_clicks", 0) for r in rs),
                sum(r.get("clicks", 0) for r in rs),
            ),
        ),
        row(
            "Runs with a detour (more than the 5-step minimum path)",
            lambda rs: fmt_rate(sum(1 for r in rs if r.get("detour")), len(rs)),
        ),
        row(
            "Invalid actions (bad label / out of bounds)",
            lambda rs: str(sum(r.get("invalid_clicks", 0) for r in rs)),
        ),
        row(
            "Mean click error to nearest interactable centre (px)",
            lambda rs: _f(
                _mean(
                    [
                        r["mean_click_error_px"]
                        for r in rs
                        if r.get("mean_click_error_px") is not None
                    ]
                )
            ),
        ),
        row(
            "Runs that misclicked or hit the wrong target but still succeeded",
            lambda rs: str(sum(1 for r in rs if r.get("recovered"))),
        ),
        row(
            "Cost per run, mean (USD)",
            lambda rs: _f(_mean([r["cost_usd"] for r in rs if r.get("cost_usd") is not None]), 3),
        ),
        row(
            "Wall time per run, median (s)",
            lambda rs: _f(
                median([r["wall_time_s"] for r in rs if r.get("wall_time_s") is not None])
            ),
        ),
        row(
            "Model latency per run, median (s)",
            lambda rs: _f(
                median([r["model_latency_s"] for r in rs if r.get("model_latency_s") is not None])
            ),
        ),
    ]

    lines += [
        "",
        "## By repository",
        "",
        "| Repo | Arm | Task success | Nav success | Steps (median) | Misclicks / clicks | Cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for repo in repos:
        for a in arms:
            rs = [r for r in rows if r["repo"] == repo and r["arm"] == a]
            if not rs:
                continue
            lines.append(
                f"| {repo} | {a} | {_rate(rs, 'task_success')} | {_rate(rs, 'navigation_success')} | "
                f"{_f(median([r['steps'] for r in rs if r.get('steps')]), 0)} | "
                f"{sum(r.get('misclicks', 0) for r in rs)} / {sum(r.get('clicks', 0) for r in rs)} | "
                f"${_f(_mean([r['cost_usd'] for r in rs if r.get('cost_usd') is not None]), 3)} |"
            )

    lines += ["", "## Outcomes by arm", ""]
    for a in arms:
        c = Counter(r.get("status", "?") for r in by_arm[a])
        lines.append(f"- **{a}**: " + ", ".join(f"{k} ×{v}" for k, v in c.most_common()))

    wrong = [r for r in rows if r.get("wrong_target_clicks")]
    lines += ["", "## Wrong-target clicks", ""]
    if not wrong:
        lines.append("None.")
    else:
        lines += ["| Arm | Repo | Run | What happened | Trace |", "|---|---|---|---|---|"]
        for r in sorted(wrong, key=lambda r: (r["arm"], r["repo"], r["run"])):
            for d in r.get("wrong_target_detail", []):
                lines.append(
                    f"| {r['arm']} | {r['repo']} | {r['run']} | {d.replace('|', '/')} | `{Path(r.get('trace_dir', '')).name}` |"
                )

    fails = [r for r in rows if not r.get("task_success")]
    lines += ["", "## Failed runs", ""]
    if not fails:
        lines.append("None.")
    else:
        lines += ["| Arm | Repo | Run | Status | Detail | Trace |", "|---|---|---|---|---|---|"]
        for r in sorted(fails, key=lambda r: (r["arm"], r["repo"], r["run"])):
            detail = (r.get("status_detail") or "")[:90].replace("|", "/")
            lines.append(
                f"| {r['arm']} | {r['repo']} | {r['run']} | {r.get('status')} | {detail} | `{r.get('trace_dir', '')}` |"
            )

    lines += [
        "",
        "## Decision rule (pre-registered in PLAN.md §7.3)",
        "",
        "Keep Set-of-Mark as default if its task-success rate is ≥ coords and its "
        "off-target/misclick rate is lower. If coords wins or ties on success *and* is "
        "cheaper, switch and document why.",
        "",
        "## Reading",
        "",
        "_Filled in by hand after the run; see OBSERVATIONS.md._",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def extraction_report(rows: list[dict[str, Any]]) -> str:
    arms = ["vision", "verified"]
    by_arm = {a: [r for r in rows if r["arm"] == a] for a in arms}
    n_samples = len({r["sample"] for r in rows})
    lines = [
        "# Experiment 2: vision-only extraction vs vision verified against page text",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='minutes')} from "
        f"`results/extraction.jsonl` ({n_samples} screenshots × "
        f"{len(by_arm['vision']) // max(n_samples, 1)} repetitions)._",
        "",
        "**Question.** How often does a vision model misread release fields from pixels, "
        "and does a second pass against the page's rendered text fix it without breaking "
        "correct answers?",
        "",
        "**Design.** Paired: both arms run on the same screenshot. 'verified' is the "
        "vision read plus one text-verification call. Scored per field against the "
        "frozen API oracle; author is normalised (`[bot]` suffix ignored), commit is "
        "a 7-char prefix match. Intervals are 95% Wilson.",
        "",
        "## Field accuracy",
        "",
        "| Field | vision | verified |",
        "|---|---|---|",
    ]
    for f in ("version", "tag", "commit", "author", "repository"):
        lines.append(
            f"| {f} | {_rate(by_arm['vision'], f'{f}_ok')} | {_rate(by_arm['verified'], f'{f}_ok')} |"
        )
    lines.append(
        f"| **whole record** (version+tag+commit+author) | {_rate(by_arm['vision'], 'record_ok')} | {_rate(by_arm['verified'], 'record_ok')} |"
    )

    lines += [
        "",
        "## Error character",
        "",
        "| Metric | vision | verified |",
        "|---|---|---|",
        f"| Commit char error rate, mean | {_f(_mean([r['commit_cer'] for r in by_arm['vision']]), 3)} | {_f(_mean([r['commit_cer'] for r in by_arm['verified']]), 3)} |",
        f"| Tag char error rate, mean | {_f(_mean([r['tag_cer'] for r in by_arm['vision']]), 3)} | {_f(_mean([r['tag_cer'] for r in by_arm['verified']]), 3)} |",
        f"| Latency per sample, median (s) | {_f(median([r['latency_s'] for r in by_arm['vision']]))} | {_f(median([r['latency_s'] for r in by_arm['verified']]))} |",
        f"| Cost per sample, mean (USD) | {_f(_mean([r['cost_usd'] for r in by_arm['vision']]), 4)} | {_f(_mean([r['cost_usd'] for r in by_arm['verified']]), 4)} |",
    ]

    ver = by_arm["verified"]
    n_corr = sum(r.get("n_corrections", 0) for r in ver)
    right = sum(r.get("corrections_right", 0) for r in ver)
    wrong = sum(r.get("corrections_wrong", 0) for r in ver)
    agree = sum(1 for r in ver if r.get("n_corrections", 0) == 0)
    lines += [
        "",
        "## What verification did",
        "",
        f"- Samples where vision and text agreed on every field: {fmt_rate(agree, len(ver))}",
        f"- Field corrections made: {n_corr}",
        f"- Corrections that produced the oracle value (precision): {fmt_rate(right, n_corr) if n_corr else 'n/a'}",
        f"- Corrections that broke a previously correct value: {wrong}",
    ]

    conf: Counter[str] = Counter()
    for r in by_arm["vision"]:
        if r.get("commit_ok") is False and r.get("commit_value"):
            conf[f"read `{r['commit_value']}`"] += 1
    if conf:
        lines += ["", "### Commit misreads (vision arm)", ""]
        lines += [f"- {k} ×{v}" for k, v in conf.most_common(15)]

    by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sample[r["sample"]].append(r)
    lines += [
        "",
        "## By sample",
        "",
        "| Sample | vision record ok | verified record ok | corrections |",
        "|---|---|---|---|",
    ]
    for sid, rs in sorted(by_sample.items()):
        v = [r for r in rs if r["arm"] == "vision"]
        t = [r for r in rs if r["arm"] == "verified"]
        lines.append(
            f"| `{sid}` | {sum(1 for r in v if r['record_ok'])}/{len(v)} | {sum(1 for r in t if r['record_ok'])}/{len(t)} | {sum(r.get('n_corrections', 0) for r in t)} |"
        )

    lines += [
        "",
        "## Decision rule (pre-registered in PLAN.md §7.3)",
        "",
        "Keep verification as default if it raises record accuracy and correction "
        "precision ≥ 0.9. If vision-only is already ≥ 95% on commit SHA, make "
        "verification opt-in and say so.",
        "",
        "## Reading",
        "",
        "_Filled in by hand after the run; see OBSERVATIONS.md._",
        "",
    ]
    return "\n".join(lines)


def model_comparison(all_rows: list[dict[str, Any]]) -> str:
    """One table: model x arm, the metrics that decide the grounding question."""
    models = sorted({r["model"] for r in all_rows})
    lines = [
        "# Grounding by model",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='minutes')}; "
        f"{len(all_rows)} runs across {len(models)} model(s). Same harness, prompts, "
        "repositories and oracle for every cell._",
        "",
        "| Model | Arm | Task success | Wrong-target clicks | Detour runs | Click error px, mean (max) | Steps median | Cost/run | Wall s median |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        for a in ("coords", "som"):
            rs = [r for r in all_rows if r["model"] == m and r["arm"] == a]
            if not rs:
                continue
            clicks = sum(r.get("clicks", 0) for r in rs)
            errs = [
                r["mean_click_error_px"] for r in rs if r.get("mean_click_error_px") is not None
            ]
            maxes = [r["max_click_error_px"] for r in rs if r.get("max_click_error_px") is not None]
            lines.append(
                f"| {m} | {a} | {_rate(rs, 'task_success')} | "
                f"{fmt_rate(sum(r.get('wrong_target_clicks', 0) for r in rs), clicks)} | "
                f"{sum(1 for r in rs if r.get('detour'))}/{len(rs)} | "
                f"{_f(_mean(errs))} ({_f(max(maxes)) if maxes else '–'}) | "
                f"{_f(median([r['steps'] for r in rs if r.get('steps')]), 0)} | "
                f"${_f(_mean([r['cost_usd'] for r in rs if r.get('cost_usd') is not None]), 3)} | "
                f"{_f(median([r['wall_time_s'] for r in rs if r.get('wall_time_s') is not None]))} |"
            )
    lines += [
        "",
        "Per-model detail: `RESULTS_grounding.md` (Opus 5), `RESULTS_grounding_<model>.md` (others).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    g = read_jsonl(RESULTS_DIR / "grounding.jsonl")
    e = read_jsonl(RESULTS_DIR / "extraction.jsonl")
    if g:
        (EXP_DIR / "RESULTS_grounding.md").write_text(grounding_report(g))
        print(f"wrote RESULTS_grounding.md ({len(g)} runs)")
    all_rows = list(g)
    for extra in sorted(RESULTS_DIR.glob("grounding_*.jsonl")):
        if extra.name.startswith("grounding_run") or "smoke" in extra.name:
            continue
        rows = read_jsonl(extra)
        if not rows:
            continue
        all_rows += rows
        name = extra.stem.replace("grounding_", "")
        (EXP_DIR / f"RESULTS_grounding_{name}.md").write_text(grounding_report(rows))
        print(f"wrote RESULTS_grounding_{name}.md ({len(rows)} runs)")
    if len({r["model"] for r in all_rows}) > 1:
        (EXP_DIR / "RESULTS_grounding_by_model.md").write_text(model_comparison(all_rows))
        print("wrote RESULTS_grounding_by_model.md")
    if e:
        (EXP_DIR / "RESULTS_extraction.md").write_text(extraction_report(e))
        print(f"wrote RESULTS_extraction.md ({len(e)} rows)")
    if not g and not e:
        print("no results yet")
    _ = wilson  # re-exported for notebooks
    return 0


if __name__ == "__main__":
    sys.exit(main())
