# Observations

What was built, what decided each design choice, what broke, and what I would
do next. Decisions are recorded in [docs/adr/](docs/adr/); the raw build log is
[docs/observation-notes.md](docs/observation-notes.md); every number below has
a trace under `experiments/traces/` or `runs/`.

## Approach

An observe → think → act loop over a real Chromium page. Each step is one
single-turn request: system prompt, the goal, a text history of prior actions
and their measured outcomes, and the current 1280×800 screenshot. The model
returns exactly one action through a strict tool schema (`click`, `type`,
`scroll`, `press`, `back`, `done`, `abort`). Clicks are grounded by pixel
coordinates. When the model says `done`, a structured-output vision read of the
page is verified against the page's rendered text, and the output records
whether the two agreed and what was corrected. A second, bounded pass then
collects the release's downloadable assets. No selectors or XPath anywhere; the
only DOM access is a site-agnostic `innerText` for the verifier, a generic
"link whose visible text says X" lookup for asset URLs, and a generic
interactable scan kept for tracing.

## Design decisions, and what decided them

**Grounding: coordinates, by experiment, against my prediction.** I built both
pixel coordinates and Set-of-Mark (numbered badges on every interactable; the
model answers with a number) and pre-registered the decision rule before any
run: keep Set-of-Mark only if it is at least as successful and has a lower
wrong-target rate. I expected it to win. 60 runs on Opus 5, three repositories,
ten runs each, scored against a GitHub API snapshot frozen before the first
run. Then the same design on Sonnet 5.

| Model | Arm | Task success | Wrong-target clicks | Detour runs | Click error mean (max) | Cost/run |
|---|---|---|---|---|---|---|
| Opus 5 | coords | 30/30 | 0/90 | 0/30 | 0.8 px (2.0) | $0.153 |
| Opus 5 | som | 30/30 | 3/96 | 3/30 | — | $0.158 |
| Sonnet 5 | coords | 30/30 | 0/90 | 0/30 | 1.1 px (19.1) | $0.062 |
| Sonnet 5 | som | **27/30** | 3/122 | **14/30** | — | $0.068 |

Opus never missed an element centre by more than 2 px. Set-of-Mark's three
errors were all the same mistake: the model wanted "Releases", in GitHub's
dense right sidebar, and answered a neighbouring badge number. The rule said
switch, so I did. The obvious objection, that a smaller model would favour
labels, was tested on Sonnet 5 and was wrong in the other direction:
coordinates stayed 30/30, while Set-of-Mark lost three runs to a hallucinated
badge "1009" repeated despite explicit "not on screen" feedback. Reading a
number is a symbolic step that fails outright; pointing degrades gracefully,
since a few pixels off is still inside a 24 px link. Side result: Sonnet 5 with
coordinates is 100% at 40% of the cost. Caveat: one site, two models, one day,
large well-spaced targets. A page of tiny icon buttons could still favour labels.

**The first experiment metric was wrong.** I had defined a misclick as "click,
no page change". That scored 0% in both arms, because every wrong badge click
still navigated somewhere. What matched a manual review of the traces was
*wrong-target*: no content word shared between the model's stated reason and
the element it hit, and the next action going back. The metric and a
`--rescore` mode that recomputes it from traces are in the repo.

**Extraction: vision read, then verify against page text.** The graded fields
are 7-hex-char SHAs and version strings, exactly what vision misreads. The
verifier may only correct strings that exist in the rendered text, and every
correction is reported in the output. It costs ~3.5× the base read. I designed
a paired experiment for it but spent the budget on grounding, where the
outcome was uncertain; a 6-sample smoke pass agreed on every core field in
both arms. The one measured case where verification changed the answer came
from the release notes, not the core fields: in two openclaw runs the vision
read misspelled four contributor handles (`@obvivus` for `@obviyus`,
`@scottbuang` for `@scotthuang`) and truncated the thanks list at 15 of 21
names. The verifier restored all of them, but the output still said `agree`,
because only core fields were diffed. It now diffs the notes too and reports
`notes_corrected` with a word-level change summary.

**No `goto`; single-turn memory.** A model that can type URLs skips the
search → repository → releases task entirely, so `goto` was removed and
`back` kept for recovery. Each step is a fresh request. The agent's memory is
a list of lines like `3. click (open the openclaw repository) -> page
changed`, where the outcome is measured by the harness from URL, title,
scroll and a pixel diff, never reported by the model. The goal is restated
every step. Cost stays flat, and the model cannot carry a false belief forward
except through its one-sentence `reason`. The cost of this design is that the
model cannot look back at a previous screenshot; URL, title and the outcome
line have been enough on every run so far.

**Relation to existing tools.** browser-use and Skyvern pick actions from a
DOM-derived element list, which is Set-of-Mark with text instead of badges;
Skyvern adds a planner and a per-step validator. Magnitude argues for pure
vision. My result sits between them: here, pointing at pixels beat picking
from a list, and the list's failure mode was reading the number, not finding
the element. A planner-validator layer would help most on longer tasks.

## The assets problem

The brief lists download links as a bonus field. GitHub collapses the asset
list behind an "Assets (N)" disclosure below the release notes, so on the
screenshot where the model says `done`, the list is usually closed and
`download_links` comes back empty. This took two attempts.

**Attempt one: a sentence in the goal.** I added "expand the collapsed Assets
section before you stop" to the navigation goal. The run succeeded by its own
account, and the output was wrong in a way the verifier could not catch:

| | Core-only run | Goal with "expand Assets" |
|---|---|---|
| Steps | 5 | 10 (five of them scrolls) |
| Cost | $0.15 | $0.32 |
| `tag`, `commit`, `author`, `published_at` | all correct | all **null** |
| `download_links` | 0 | 7 |
| Verification outcome | agree | **agree** |

The trace shows why. The model scrolled down to find the section, scrolled up
to re-check the Latest badge, scrolled down again to expand the list, and
called `done` with the screenshot positioned on the asset list. The release
header with the tag and commit was above the viewport. The vision read
returned null for those fields because they genuinely were not visible, and
the verifier, which may only correct a value that was read, had nothing to
correct. So the output reported `agree` with four graded fields missing. One
1280×800 screenshot cannot hold both the release header and a 17-file asset
list, and a single `done` forces the model to choose which one to show. Any
prompt wording that asks for both is asking for the impossible, and the
failure is silent.

**Attempt two, kept: a separate bounded pass.** The core fields are extracted
first, from the screenshot at `done`, exactly as before. Only after that does
an assets sub-task run on the same page:

1. A sub-goal in generic words ("find this release's list of downloadable
   files, often a collapsed section with a count; expand it if needed; scroll
   until the names are visible") drives the same action loop with a hard
   budget of 4 steps. `abort` is the clean answer when a release has no files.
2. A structured-output read lists the file names visible in the new screenshot.
3. Every name is checked verbatim against the page's rendered text. A name the
   model read that is not in the text is dropped and reported as unverified,
   so a hallucinated filename cannot reach the output.
4. Each surviving name is resolved to a URL by finding the link whose visible
   text equals it. That is "the link that says X", not a selector, and it is
   the only way to get a real `href` without inventing one.

`--skip-assets` turns the pass off. Six live openclaw runs after the change
all gave the same result: core fields unchanged and correct, 12 of the 19
listed assets with real download URLs, 3 extra steps (two scrolls and `done`;
GitHub had the list already open), about +$0.07 and +15 s. On react the model
noticed the list was already expanded and returned both source archives in
2 steps. No name was dropped by verification in any run. Still partial: the 7
openclaw entries below the fold are missed, and the fix is a scroll-and-merge
loop in the pass, which I have not built.

The general lesson is the one I would carry to any vision agent: when a task
has two things that cannot share a screenshot, split it into phases that each
own a screenshot and a budget, and extract the graded fields before doing
anything that moves the page. Verification protects against misreading what
is on screen; it cannot protect against the wrong thing being on screen.

## What else didn't work

- **Asynchronous navigation.** GitHub navigates after a click via Turbo. The
  harness once checked the page before navigation began and reported a false
  "no change", and once ran JavaScript during teardown and crashed. Fix: after
  any action that can navigate, wait up to 1.5 s for the URL to change, and
  retry `evaluate` once. "Page settled" is not a single event on a modern site.
- **Literal goals on renamed repositories.** `facebook/react` redirects to
  `react/react`. With "exactly named" in the goal, the model correctly
  rejected the redirect target and spent 11 steps and $0.31 hunting for a name
  that no longer exists. Every click landed where intended;
  instruction-following was the failure. The prompt now accepts a redirect to
  the same project.
- **"Latest" is a semantic, not a position.** neovim lists a nightly
  pre-release first; both extraction arms transcribed it. No verifier can fix
  a wrong choice of release. The prompts now define latest as the
  Latest-badged entry, and the fixture stays as a known-hard case.
- **Loop detection was too eager.** Three scrolls down a long page counted as
  a loop. A replay test caught it before any live run; now only actions that
  produce no page change count.
- **The API oracle needed care.** `/git/ref/tags/<tag>` returns an annotated
  tag object, not the commit the page shows, and the API says
  `github-actions[bot]` where the page says `github-actions`. Without
  dereferencing and normalising, every openclaw run would have scored wrong
  on two fields.
- **Strict tool schemas reject `enum` with a nullable type list.** Use `anyOf`
  with a null branch. Found on the first live call.

## Trade-offs and limitations

- **One fixed viewport.** 1280×800 at 1x keeps the screenshot under the API's
  resize threshold so coordinates map 1:1. GitHub's Releases link sits at
  y≈787, right at the fold.
- **Generic DOM reads vs pure vision.** The verifier reads `innerText`, the
  asset pass reads link text, and the opt-in Set-of-Mark mode reads boxes.
  None knows anything about GitHub, but a `<canvas>` app or cross-origin
  iframe defeats all three. `--extraction vision` makes a run pixel-only.
- **What fits on screen.** `published_at` is the page's relative text
  ("18 hours ago"). Release notes and download links are what the final
  screenshots hold.
- **Cost.** ~$0.15 and ~40 s per run on Opus 5 for the core fields, plus
  ~$0.07 and ~15 s for assets. Sonnet 5 with coordinates measured 30/30 at
  $0.06 and is the better production default; Opus stays the default here
  because the experiment and sample output were produced with it.
- No handling of rate-limit or abuse pages beyond a clean `abort`. Two models,
  three repositories, one day; the intervals in the reports are wide.

## With another week

- **Where coordinates break.** Haiku 4.5, and a page with genuinely small
  targets. Scroll-and-merge in the assets pass. The extraction experiment as
  designed. Feed back the text of the element actually clicked and the
  resulting URL in each history line, so the model's memory is grounded in
  what happened rather than what it intended.
- **Replay with verification.** The 120 committed traces are a memory of what
  worked. On a repeat task, replay the remembered actions and, after each one,
  ask a decision-only model such as TypeSafe's Jev a typed yes/no ("did this
  step land?") against the page's URL and visible text; call the vision model
  only when its calibrated probability is low, and discard the memory on the
  first miss. The happy path drops from ~$0.15 to cents while keeping the
  robustness to layout changes the brief asks for. The trap is treating a
  remembered path as authoritative: that is a hardcoded path by another name.
- **Fine-tuning on traces.** Every step is already a (screenshot, history,
  action, outcome) tuple with a scored result. With a few thousand across
  several sites, a small vision model could be fine-tuned for this action
  schema; the scoring harness labels which trajectories to learn from.
- **Toward production.** *Auth:* classify login, MFA and session-expired
  screens as distinct states; resume from a stored browser session, pause for
  a human on MFA, abort with a precise reason otherwise; credentials never
  pass through the model or the trace. *Anti-automation:* detect and
  cooperate, never evade: back off on rate limits, hand CAPTCHAs to a human,
  use a persistent authorised browser profile, log every challenge as a
  metric.
