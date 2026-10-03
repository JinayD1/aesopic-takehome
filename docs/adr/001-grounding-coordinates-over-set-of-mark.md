# ADR 001: Ground clicks with pixel coordinates; keep Set-of-Mark behind a flag

**Status:** accepted (2026-10-03). Supersedes the plan's provisional choice of
Set-of-Mark as default (PLAN.md §5, decision 2).

## Context

Grounding is how "click the Releases link" becomes something Playwright can
execute. It is where browser agents usually fail. Two approaches were built so
they could be compared on equal terms:

| | Pixel coordinates | Set-of-Mark (SoM) |
|---|---|---|
| What the model sees | the raw screenshot | the screenshot with a numbered badge on every visible interactable, found by one site-agnostic DOM query |
| What the model answers | `click(x, y)` | `click(label)` |
| What can go wrong | aims a few pixels off a small target | reads the wrong badge number in a dense region; depends on the DOM existing |
| DOM dependence | none | generic scan (no site-specific selectors) |

Going in, the expectation was that SoM would be more reliable: picking a number
should be easier than estimating a point, especially for 14 px-tall text links.

## The experiment

Pre-registered in PLAN.md §7.1 with the decision rule in §7.3 *before* any run:

> Keep SoM as default if its task-success rate is ≥ coords and its wrong-target
> rate is lower. If coords wins or ties on success and is cheaper, switch.

2 arms × 3 repositories (`openclaw/openclaw`, `react/react`, `pallets/flask`)
× 10 runs = 60 full navigations on Claude Opus 5, scored against a frozen
GitHub API snapshot. Full report: `experiments/RESULTS_grounding.md`.

| Metric | coords | som |
|---|---|---|
| Task success | 30/30 (95% CI 89–100%) | 30/30 (95% CI 89–100%) |
| Steps, median (p90) | 5 (5) | 5 (5) |
| Wrong-target clicks | 0/90 | 3/96 (3%, CI 1–9%) |
| Runs with a detour | 0/30 | 3/30 |
| Mean click error to element centre | 0.8 px (max 2 px) | 0 by construction |
| Cost per run | $0.153 | $0.158 |
| Wall time, median | 39.5 s | 43.0 s |

## What the data showed

1. **Opus 5 localises to within 2 px on a 1x screenshot.** Over 90 coordinate
   clicks the largest distance from an element centre was 2.0 px. The
   assumed weakness of coordinate grounding did not materialise at this
   viewport with this model.
2. **SoM introduced a failure mode coordinates cannot have.** In all three
   detours the model intended "Releases" but answered a neighbouring badge
   (94 when Releases was 92; 82 when it was 86). GitHub's sidebar Releases
   badge sits level with file-list rows, so numerically adjacent badges are
   visually interleaved. The click went to a random file link, the page
   changed, and the model recovered via the repo header in two extra steps.
3. **The first metric missed it.** "Misclick = click with no page change" was
   0% in both arms, because the wrong click *did* navigate. The metric that
   matched manual review was *wrong-target*: no content word shared between
   the model's stated reason and the text of the element actually hit, and
   the model's next action going back.

## Decision

Follow the pre-registered rule: **pixel coordinates are the default**;
Set-of-Mark stays fully implemented behind `--grounding som`.

Cost and time differences are inside noise and did not drive this. The
wrong-target difference (0 vs 3) is small in absolute terms, but it is the
only observed error in 186 clicks and it is structural: badge misreads get
more likely as pages get denser, while coordinate error got no worse on the
densest page in the set.

## What this does not show

- One site, one model, one day. GitHub's targets are large and well spaced.
- SoM's expected advantage was never exercised: tiny targets, or a model that
  localises worse than Opus 5 (Haiku 4.5 would be the obvious test).
- Three events is a thin base for a rate; the CI on SoM's wrong-target rate
  is 1–9%.

If any of those conditions change, re-run `make experiment-grounding` with
the relevant `--model` or repositories; the harness, oracle and scoring are
unchanged by this decision.

## Consequences

- `NavigatorConfig.grounding` and the CLI default to `coords`.
- Navigation no longer reads the DOM at all by default; the generic scan still
  runs for the trace (so post-hoc click attribution and the wrong-target metric
  keep working) but nothing from it reaches the model.
- The README's "reads the DOM" caveat shrinks to the extraction verifier.
- The plan document keeps its original (wrong) prediction, struck through,
  so the record of what was expected versus found stays visible.
