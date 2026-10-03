# Observations

What I built, what the data says, what broke, and what I would do next.
Numbers come from `experiments/RESULTS_grounding.md` (60 scored runs) and the
run traces under `experiments/traces/`; nothing here is estimated.

## 1. Approach in one paragraph

An observe → think → act loop over a real Chromium page. Each step sends the
model one screenshot plus a text history of what it already did and asks for
exactly one action through a strict tool schema. Clicks are grounded with
Set-of-Mark: the harness finds interactive elements with a single
site-agnostic query, draws a numbered badge on each, and the model answers with
a number. When the model says `done`, a structured-output vision read of the
final page is verified against the page's rendered text. Both design choices
have the alternative kept behind a flag, and the grounding choice was decided
by a pre-registered experiment rather than by intuition.

## 2. Design decisions, and what decided them

### Grounding: Set-of-Mark over raw coordinates

_(Filled from the experiment; see §3.)_

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

_(Headline table and reading pasted from `experiments/RESULTS_grounding.md`
after the run.)_

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

- **Generic DOM scan vs "pure" vision.** Set-of-Mark reads the DOM to find
  boxes, and verification reads `innerText`. Neither knows anything about
  GitHub, and both would work unchanged on any site, but neither works on a
  `<canvas>` app or inside a cross-origin iframe. The pure-pixel path
  (`--grounding coords --extraction vision`) exists for that case and is
  measurably less reliable.
- **One fixed viewport.** 1280×800 at 1x keeps the screenshot under the API's
  resize threshold so coordinates map 1:1. GitHub's Releases link sits at
  y≈787, right at the fold; a smaller viewport would force a scroll on every run.
- **Cost over cleverness.** ~$0.17 and ~50–70 s per run on Opus 5. Sonnet 5
  would roughly halve both; I did not measure its success rate.
- **Single-turn steps.** The model cannot look back at a previous screenshot.
  URL, title and the outcome line per step have been enough in every run so far.

## 6. Limitations

- Headless Chromium with a realistic UA; no handling of GitHub's rate-limit or
  abuse pages beyond `abort`.
- `published_at` is whatever the page renders ("18 hours ago"), not an ISO date.
- Release notes are captured only as far as they are visible in the final
  screenshot; download links come from the visible asset list, which GitHub
  collapses by default.
- The experiment ran on one model (Opus 5) and three repositories on one day.
  Intervals are wide; see §3 for exactly how wide.

## 7. What I would do with another week

1. Run the extraction experiment as designed, and a model sweep (Opus 5 /
   Sonnet 5 / Haiku 4.5) on the grounding task, since cost per *successful*
   run is the number that matters.
2. Attach the previous screenshot when the last action had no effect, so the
   model can see what changed rather than being told.
3. Trim the verifier's input to the text near the release card to cut its cost.
4. A `--site` profile system is the wrong direction; instead, test on two
   non-GitHub sites to see which assumptions are actually GitHub-shaped.
5. Record the agent's `reason` against the clicked element's text in every
   run to compute a true wrong-target rate automatically.
