# Observations (extended)

_The two-page version submitted as the observations document is `../OBSERVATIONS.md`; this is the full record._

What I built, what the data says, what broke, and what I would do next.
Numbers come from `experiments/RESULTS_grounding.md` (60 scored runs) and the
run traces under `experiments/traces/`; nothing here is estimated.

## 1. Approach in one paragraph

An observe → think → act loop over a real Chromium page. Each step sends the
model one screenshot plus a text history of what it already did and asks for
exactly one action through a strict tool schema. Clicks are grounded by pixel
coordinates on a fixed 1280×800 screenshot; the alternative, Set-of-Mark
(numbered badges on every interactable, model answers with a number), is fully
built and was the planned default until a pre-registered 60-run experiment
said otherwise. When the model says `done`, a structured-output vision read of
the final page is verified against the page's rendered text. Both design
choices keep the alternative behind a flag.

## 2. Design decisions, and what decided them

### Grounding: pixel coordinates, decided by experiment, against my prediction

I built both. My prediction, written into the plan before any run, was that
Set-of-Mark (numbered badges, model answers with a number) would beat raw
coordinates because picking a label is easier than estimating a point on a
14 px link. I also pre-registered the rule for choosing: keep Set-of-Mark only
if it is at least as successful *and* has a lower wrong-target rate.

The data said otherwise (§3). Coordinates became the default; Set-of-Mark is
`--grounding som`. ADR 001 has the full reasoning and the caveats.

### Extraction: vision read verified against page text

The misread risk is concentrated in exactly the graded fields: 7-hex-char
commit SHAs and version strings. A second call that sees the vision read and
`innerText` and may only *correct* strings that exist in the text gives exact
characters while the screenshot still decides which release is the latest. The
cost is real: the verify call is ~3.5× the vision read because the page text
is ~5K tokens. The full paired experiment was designed (PLAN.md §7.2) but not
run; a 6-sample smoke pass agreed on every field in both arms, and the only
miss was a wrong *choice* of release that no verifier could fix (§4). The
budget went to the grounding question instead, where the outcome was
genuinely uncertain. ADR 002 has the detail.

### No `goto`, single-turn memory, custom tool

A model that can type URLs skips the task. Each step is a fresh single-turn
request with an explicit text history, so cost is flat and the agent's memory
is readable in the trace. ADR 003.

## 3. Experiment: Set-of-Mark vs pixel coordinates

60 full navigations on Claude Opus 5: 2 grounding modes × 3 repositories
(`openclaw/openclaw`, `react/react`, `pallets/flask`) × 10 runs, scored against
a GitHub API snapshot frozen before the first run. Everything else held equal.
Full report with per-repo tables and every wrong-target click listed:
`experiments/RESULTS_grounding.md`. Raw rows: `experiments/results/grounding.jsonl`.
Every run's step-by-step JSON is committed under `experiments/traces/`.

| Metric | coords | som |
|---|---|---|
| **Task success** (version + tag match the API) | 30/30 (95% CI 89–100%) | 30/30 (95% CI 89–100%) |
| Steps, median (p90) | 5 (5) | 5 (5) |
| Misclicks (click, no page change) | 0/90 | 0/96 |
| **Wrong-target clicks** | 0/90 | 3/96 = 3% (CI 1–9%) |
| Runs with a detour beyond the 5-step minimum | 0/30 | 3/30 |
| Mean distance from click to element centre | 0.8 px (max 2.0) | 0 by construction |
| Cost per run, mean | $0.153 | $0.158 |
| Wall time, median | 39.5 s | 43.0 s |

**Reading.** Three things I did not expect.

1. *Coordinates were essentially perfect.* Over 90 clicks the model never
   missed an element centre by more than 2 px. At a 1x, 1280×800 screenshot
   that stays under the API's resize threshold, Opus 5's localisation is not
   the bottleneck I planned around.
2. *Set-of-Mark has its own error, and it is structural.* All three detours
   were the same mistake: the model wanted "Releases", which sits in GitHub's
   right sidebar level with the file list, and answered a neighbouring badge
   number (94 for 92, 82 for 86). The click went to a random file link. It
   recovered every time via the repository header, at two extra steps and
   about $0.04. Denser pages make badge misreads *more* likely; they did not
   make coordinate error worse on the densest page in the set.
3. *My first metric was wrong.* I had defined a misclick as "click, no page
   change". That was 0% in both arms, because every wrong badge click still
   navigated. What matched a manual review of the traces was *wrong-target*:
   no content word shared between the model's stated reason and the text of
   the element it hit, and the model's next action going back. The first
   version of that heuristic flagged every search-box click (a stop-word bug);
   the two-condition version matches the hand review exactly. The metric and
   the `--rescore` mode that recomputes it from traces are in the repo.

**Decision.** By the pre-registered rule, coordinates win: tie on success,
fewer wrong targets, and marginally cheaper. I switched the default and left
the plan's original prediction struck through rather than rewritten.

**Replication on Sonnet 5.** The natural objection was that coordinates only
won because Opus 5 points so precisely, and a smaller model would favour
labels. Same 60-run design, same oracle, Sonnet 5:

| Model | Arm | Task success | Wrong-target | Detours | Click error mean (max) | Cost/run |
|---|---|---|---|---|---|---|
| Opus 5 | coords | 30/30 | 0/90 | 0/30 | 0.8 px (2.0) | $0.153 |
| Opus 5 | som | 30/30 | 3/96 | 3/30 | — | $0.158 |
| Sonnet 5 | coords | 30/30 | 0/90 | 0/30 | 1.1 px (19.1) | $0.062 |
| Sonnet 5 | som | **27/30** | 3/122 | **14/30** | — | $0.068 |

The objection was wrong in the other direction. Sonnet's pointing stayed
inside the target on all 90 clicks. Its badge reading got worse: three runs
ended in loop detection after it asked three times for badge **1009**, which
was not on screen, ignoring the harness's explicit "not on screen (1..95)"
feedback; 14 of 30 runs detoured. Reading a number and emitting it is a
symbolic step that fails outright; pointing degrades gracefully, since a few
pixels off is still inside a 24 px link. The loop detector did its job in all
three failures: each ended at step 6 or 7 rather than at the 15-step budget.

Cheapest headline from the whole project: Sonnet 5 with coordinates was
30/30 at 40% of Opus's cost.

**What this does not show.** One site, two models, one day, with large and
well-spaced targets. A page of tiny icon buttons could still favour labels.
Haiku 4.5 is untested; the harness runs it with one flag.

## 4. What didn't work, and what it taught me

Every item here came from a real run, is in the commit history, and has a trace.

- **GitHub navigates asynchronously, and my harness didn't wait.** After a
  correct click on Releases, the harness checked the page before Turbo had
  started navigating and reported "no visible change". In the headed demo the
  model simply clicked again and recovered, which was reassuring, but a
  coordinate-mode run then crashed with `Execution context was destroyed`
  because `evaluate` ran during teardown. Fix: after any action that can
  navigate, wait up to 1.5 s for the URL to change, and retry `evaluate` once.
  Lesson: "page settled" is not a single event on a modern site.
- **Literal goals fail on renamed repositories.** `facebook/react` now
  redirects to `react/react`. With the goal saying "exactly named
  facebook/react", the model landed on the right repo, correctly observed the
  name mismatch, went back, and spent 11 more steps and $0.31 hunting for a
  repo that no longer exists under that name. Every click in that run landed
  where intended; the failure was instruction-following, not grounding. Fix:
  the prompt now accepts a redirect to the same project.
- **"Latest" is a semantic, not a position.** On neovim's releases page the
  top entry is a nightly pre-release; the release GitHub badges "Latest" is
  second and below the fold. Both extraction arms transcribed the nightly
  build. The API's `/releases/latest` excludes pre-releases, so both were
  scored wrong. Fix: the goal and extraction prompts now define latest as the
  Latest-badged entry, and the navigator is told to scroll past a pre-release.
  The fixture stays in the repo as a known-hard case.
- **Loop detection was too eager.** Counting every repeated action flagged
  "scroll down three times on a long page" as a loop. A replay test caught it
  before any live run did. Now only actions that produce no page change count.
- **Strict tool schemas reject `enum` + nullable `type` lists.** Use `anyOf`
  with a null branch. Found on the very first live call.
- **The API oracle needs care.** `/git/ref/tags/<tag>` returns an annotated
  *tag object*, not the commit the page shows; and the API says
  `github-actions[bot]` where the page says `github-actions`. Without
  dereferencing and normalising, every openclaw run would have been scored as
  wrong on two fields.

## 5. Trade-offs I knowingly made

- **Generic DOM reads vs "pure" vision.** The extraction verifier reads
  `innerText`, and Set-of-Mark (now opt-in) reads interactable boxes. Neither
  knows anything about GitHub and both work unchanged on any site, but neither
  works on a `<canvas>` app or inside a cross-origin iframe. Navigation is
  pixel-only by default after the experiment; `--extraction vision` makes the
  whole run pixel-only.
- **One fixed viewport.** 1280×800 at 1x keeps the screenshot under the API's
  resize threshold so coordinates map 1:1. GitHub's Releases link sits at
  y≈787, right at the fold; a smaller viewport would force a scroll on every run.
- **Cost over cleverness.** ~$0.15 and ~40 s per run on Opus 5. Sonnet 5 with
  coordinates measured 30/30 at $0.06 and 34 s, so it is the better production
  default; Opus stays the default here only because it is what the main
  experiment and the sample output were produced with.
- **Single-turn steps.** The model cannot look back at a previous screenshot.
  URL, title and the outcome line per step have been enough in every run so far.

## 6. Limitations

- Headless Chromium with a realistic UA; no handling of GitHub's rate-limit or
  abuse pages beyond `abort`.
- `published_at` is whatever the page renders ("18 hours ago"), not an ISO date.
- Release notes are captured only as far as they are visible in the final
  screenshot; download links come from the visible asset list, which GitHub
  collapses by default.
- The experiments ran on two models and three repositories on one day.
  Intervals are wide; see §3 for exactly how wide.

## 7. What I would do with another week

1. Haiku 4.5 on the grounding experiment, and a page with genuinely small
   targets, to find where coordinates finally break. Then the extraction
   experiment as designed.
2. Attach the previous screenshot when the last action had no effect, so the
   model can see what changed rather than being told.
3. Trim the verifier's input to the text near the release card to cut its cost.
4. A `--site` profile system is the wrong direction; instead, test on two
   non-GitHub sites to see which assumptions are actually GitHub-shaped.
5. Record the agent's `reason` against the clicked element's text in every
   run to compute a true wrong-target rate automatically.
