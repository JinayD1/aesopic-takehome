# ADR 001: Ground clicks with pixel coordinates; keep Set-of-Mark behind a flag

**Status:** accepted (2026-10-03), replicated on a second model the same day. Supersedes the plan's provisional choice of
Set-of-Mark as default (PLAN.md §5, decision 2; the plan is kept in git history).

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

Pre-registered in PLAN.md §7.1 (git history) with the decision rule in §7.3 *before* any run:

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

## Replication on a smaller model (Sonnet 5, same day)

The obvious objection was that coordinates won only because Opus 5 localises
so well, and that a smaller model would favour labels. We ran the identical
60-run design on Claude Sonnet 5 (`experiments/RESULTS_grounding_sonnet.md`,
cross-model table in `RESULTS_grounding_by_model.md`):

| Model | Arm | Task success | Wrong-target | Detour runs | Click error mean (max) | Cost/run | Wall s |
|---|---|---|---|---|---|---|---|
| Opus 5 | coords | 30/30 | 0/90 | 0/30 | 0.8 px (2.0) | $0.153 | 39.5 |
| Opus 5 | som | 30/30 | 3/96 | 3/30 | — | $0.158 | 43.0 |
| Sonnet 5 | coords | 30/30 | 0/90 | 0/30 | 1.1 px (19.1) | $0.062 | 34.3 |
| Sonnet 5 | som | **27/30** | 3/122 | **14/30** | — | $0.068 | 37.6 |

The hypothesis was not supported. Sonnet's coordinate clicks stayed inside
their targets on every one of 90 clicks (one landed 19 px from a centre, at
the edge of the Releases link, still inside it). Set-of-Mark got *worse*: three
runs were ended by loop detection after the model asked three times for badge
**1009**, a number not on screen, ignoring the harness's "label 1009 is not on
screen (1..95)" feedback each time; and 14 of 30 runs took detours, including
two where it clicked "Sign in" (badge 9) when it wanted search (badge 8).

Reading: badge-number reading is the weaker skill on the smaller model, not
pointing. Set-of-Mark adds a symbolic step (read a number, emit that number)
that can fail outright, while coordinate estimation degrades gracefully: a
few pixels off is still inside a 24 px-tall link.

A side result worth more than the grounding question for a production tool:
Sonnet 5 with coordinates hit 100% at 40% of the cost and 13% less wall time.

## What this does not show

- One site, two models, one day. GitHub's targets are large and well spaced;
  a page of 10 px icon buttons could still favour labels.
- Haiku 4.5 is untested. The harness is unchanged by this decision:
  `make experiment-grounding` with `--model claude-haiku-4-5` runs it.
- Three and three events are thin bases for rates; the intervals are in the
  reports.

## Consequences

- `NavigatorConfig.grounding` and the CLI default to `coords`.
- The default model follows the grounding mode (`default_model` in
  `navigator/llm.py`): Sonnet 5 with coordinates, where it matched Opus 5 at
  30/30 for 40% of the cost, and Opus 5 with Set-of-Mark, where Sonnet 5 lost
  3/30 runs to hallucinated badge numbers. `--model` overrides either.
- Navigation no longer reads the DOM at all by default; the generic scan still
  runs for the trace (so post-hoc click attribution and the wrong-target metric
  keep working) but nothing from it reaches the model.
- The README's "reads the DOM" caveat shrinks to the extraction verifier.
- The plan document keeps its original (wrong) prediction, struck through,
  so the record of what was expected versus found stays visible.
