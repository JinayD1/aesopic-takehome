"""Command-line entry point.

    navigate --repo openclaw/openclaw
    navigate --url https://github.com --prompt "search for openclaw and get the current release"

Prints one JSON document to stdout. Progress goes to stderr so the output can
be piped. Exit status is 0 only when the run succeeded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import prompts
from .agent import Navigator, NavigatorConfig
from .schemas import RunStatus


def _load_env() -> None:
    # Project root .env first, then cwd. Never fails if neither exists.
    for candidate in (Path(__file__).resolve().parents[1] / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="navigate",
        description="Vision-model-driven web navigator that extracts GitHub release info.",
    )
    task = p.add_argument_group("task")
    task.add_argument("--repo", help='Repository as "owner/name" (simple interface).')
    task.add_argument("--url", default="https://github.com", help="Starting URL.")
    task.add_argument("--prompt", help="Natural-language goal (flexible interface).")

    model = p.add_argument_group("model")
    model.add_argument(
        "--model",
        default=None,
        help=(
            "Anthropic model id. Default depends on --grounding: claude-sonnet-5 for coords "
            "(30/30 in the experiment at 40%% of the cost), claude-opus-5 for som "
            "(Sonnet lost 3/30 there). See ADR 001."
        ),
    )
    model.add_argument(
        "--grounding",
        choices=["som", "coords"],
        default="coords",
        help=(
            "How clicks are grounded: raw pixel coordinates (default, chosen by experiment) "
            "or Set-of-Mark numbered labels."
        ),
    )
    model.add_argument(
        "--extraction",
        choices=["verified", "vision"],
        default="verified",
        help="Extraction: vision read verified against page text (default), or vision only.",
    )

    run = p.add_argument_group("run")
    run.add_argument("--max-steps", type=int, default=15)
    run.add_argument("--timeout", type=float, default=300.0, help="Wall-clock seconds.")
    run.add_argument("--headed", action="store_true", help="Show the browser window.")
    run.add_argument("--slow-mo", type=int, default=0, help="Playwright slow_mo in ms.")
    run.add_argument("--trace-dir", type=Path, default=Path("runs"))
    run.add_argument("--out", type=Path, help="Also write the JSON result to this file.")
    run.add_argument(
        "--full",
        action="store_true",
        help="Print the full record: pre-verification vision read, token usage, timestamps.",
    )
    run.add_argument("--quiet", action="store_true", help="No progress on stderr.")
    run.add_argument(
        "--skip-assets",
        action="store_true",
        help="Skip the second pass that expands and reads the release's asset list.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = build_parser().parse_args(argv)

    if not args.repo and not args.prompt:
        print("error: provide --repo owner/name or --prompt 'what to do'", file=sys.stderr)
        return 2

    if args.repo:
        goal = prompts.repo_goal(args.repo, args.url)
        name_hint = args.repo
    else:
        goal = prompts.prompt_goal(args.prompt, args.url)
        name_hint = args.prompt
    if args.repo and args.prompt:
        goal = f"{goal} Additionally: {args.prompt.strip()}"

    def log(msg: str) -> None:
        if not args.quiet:
            print(f"[navigate] {msg}", file=sys.stderr)

    config = NavigatorConfig(
        model=args.model,
        grounding=args.grounding,
        extraction=args.extraction,
        max_steps=args.max_steps,
        timeout_s=args.timeout,
        headless=not args.headed,
        slow_mo_ms=args.slow_mo,
        assets=not args.skip_assets,
        trace_root=args.trace_dir,
    )
    result = Navigator(config, log=log).run(goal=goal, start_url=args.url, name_hint=name_hint)

    text = json.dumps(result.to_output(full=args.full), indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    log(
        f"{result.run.status.value} in {result.run.steps} steps, "
        f"{result.run.wall_time_s}s, ${result.run.cost_usd} -> {result.run.trace_dir}"
    )
    return 0 if result.run.status is RunStatus.SUCCESS else 1


if __name__ == "__main__":
    sys.exit(main())
