# aesopic-navigator

A vision-model-driven agent that opens github.com, searches for a repository,
clicks through to its Releases page and extracts the latest release as JSON.
No CSS selectors, no XPath: the model looks at screenshots and decides what to
click.

![demo](docs/demo.gif)

```bash
navigate --repo openclaw/openclaw
```

```json
{
  "repository": "openclaw/openclaw",
  "latest_release": {
    "version": "openclaw 2026.9.8",
    "tag": "v2026.9.8",
    "commit": "fc23bc8",
    "author": "github-actions",
    "published_at": "18 hours ago",
    "is_prerelease": false
  },
  "run": { "status": "success", "steps": 5, "cost_usd": 0.17, "wall_time_s": 71.5, "...": "..." }
}
```

## Setup

Requires Python ≥ 3.10, [uv](https://docs.astral.sh/uv/) and an Anthropic API key.

```bash
make setup                      # venv, deps, Chromium
cp .env.example .env            # then put ANTHROPIC_API_KEY=... in .env
make test                       # 51 tests, no network, no key needed
make demo                       # the take-home task -> sample_output.json
```

Without `make`: `uv venv && uv pip install -e ".[dev]" && .venv/bin/python -m playwright install chromium`.

## Usage

```bash
# simple interface
navigate --repo openclaw/openclaw

# natural-language interface
navigate --url https://github.com --prompt "search for openclaw and get the current release and related tags"

# any repository; bonus fields (notes, assets, date) are always included when visible
navigate --repo pallets/flask --out flask.json

# watch it
navigate --repo openclaw/openclaw --headed --slow-mo 300

# the alternatives kept for comparison
navigate --repo openclaw/openclaw --grounding coords      # raw pixel coordinates instead of labels
navigate --repo openclaw/openclaw --extraction vision     # skip text verification
navigate --repo openclaw/openclaw --model claude-sonnet-5 # cheaper model
```

JSON goes to stdout, progress to stderr, exit code 0 only on success. Every run
writes a trace to `runs/<timestamp>_<name>/`: the exact screenshot the model saw
at each step (`step_NN.png`, badges included), the raw screenshot, a JSON record
per decision, the final page and the page text used by the verifier.

## How it works

```
goal ─► screenshot ─► [generic scan of interactables → numbered badges] ─► model picks ONE action
                                                                                │
         ◄──────────── wait for navigation, detect page change, record ─────────┘
                                   (repeat ≤ 15 steps)
                                        │ done
                                        ▼
            vision read of the final page ─► verify strings against page text ─► JSON
```

- **Grounding (Set-of-Mark).** The harness runs one site-agnostic query for
  interactive content (`a[href]`, `button`, inputs, ARIA widget roles), keeps
  the visible, unoccluded ones, and draws a numbered badge on each. The model
  answers `click(14)`. It never sees element text in this mode; it reads the
  page from pixels and picks a number. The code knows nothing about GitHub.
  Pure pixel coordinates are available with `--grounding coords`.
  → [ADR 001](docs/adr/001-grounding-set-of-mark.md), [experiment](experiments/RESULTS_grounding.md)
- **Extraction.** Structured-output read of the final screenshot, then a second
  call that checks each string against the page's rendered text and reports any
  correction. Output includes whether the two agreed.
  → [ADR 002](docs/adr/002-extraction-verified-against-page-text.md)
- **Memory.** Each step is a single-turn request: system prompt + goal + a text
  history of prior actions and outcomes + the current screenshot. Cost is flat
  per step and the agent's memory is readable in the trace.
  → [ADR 003](docs/adr/003-action-schema-and-single-turn-memory.md)
- **Reliability.** Step budget, wall-clock timeout, page-change detection
  (URL/title/scroll plus a pixel diff), loop detection on ineffective actions,
  a "you appear stuck" hint, invalid actions fed back to the model, and any
  crash becomes a JSON error with a trace, never a stack trace.

### The `tag` field

The brief's sample output has `"tag": "77e703c"`, which is a short commit SHA.
GitHub's release card shows both the git tag and the commit. We return
`tag` (e.g. `v2026.9.8`) and `commit` (e.g. `fc23bc8`) separately.

## Testing

| Layer | Command | What it proves | Needs |
|---|---|---|---|
| Unit | `make test` | overlay geometry, click resolution incl. rescaling, loop signatures, pixel diff, URL parsing, vision-vs-text diffing | nothing |
| Replay | `make test` | the whole agent loop against a scripted model and fake browser: happy path, coordinate attribution, step budget, loop detection, stuck hint, abort, invalid label, model errors, browser crash, timeout | nothing |
| Live | `make test-live` | one real run scored against the GitHub API | network + key (~$0.20) |
| Experiment | `make experiment-grounding` | 60 scored navigations, Set-of-Mark vs coordinates | ~$11 |

CI runs lint, mypy (strict) and the first two layers on every push.

## Repository map

```
navigator/        the tool: browser.py, grounding.py, agent.py, llm.py, prompts.py, trace.py, cli.py
tests/            unit + replay (fakes.py) + opt-in live
experiments/      oracle snapshots, runners, analysis, RESULTS_*.md, traces of every scored run
docs/adr/         architecture decision records
docs/observation-notes.md   raw chronological notes from the build
OBSERVATIONS.md   the write-up: approach, what worked, what didn't, trade-offs, limitations
PLAN.md           the plan this was built from, including the pre-registered experiment design
sample_output.json
```

## Limitations

- **Reads the DOM generically.** Set-of-Mark needs a list of interactable
  boxes, and text verification needs `innerText`. A `<canvas>` app or a
  cross-origin iframe defeats both; `--grounding coords --extraction vision`
  is the fallback and is strictly pixel-based.
- **One viewport.** 1280×800 at 1x, chosen so the screenshot maps 1:1 onto the
  page and stays under the API's resize threshold. Smaller screens would push
  GitHub's Releases link (at y≈787) below the fold and cost a scroll.
- **GitHub bot detection** is not handled beyond a realistic user agent; a
  rate-limit page would end the run with `abort`.
- **Relative dates.** `published_at` is whatever the page shows ("18 hours ago").
- **Cost/latency.** ~$0.17 and ~50–70 s per run on Claude Opus 5.

See [OBSERVATIONS.md](OBSERVATIONS.md) for the full discussion.
