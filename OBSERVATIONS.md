# Observations

Two pages. The long version with every number and trace path is
[docs/observations-extended.md](docs/observations-extended.md); decisions are in
[docs/adr/](docs/adr/).

## Approach

An observe → think → act loop over a real Chromium page. Each step is a single
request: system prompt, the goal, a text history of prior actions and their
outcomes, and the current 1280×800 screenshot. The model returns exactly one
action through a strict tool schema (`click`, `type`, `scroll`, `press`,
`back`, `done`, `abort`). Clicks are grounded by pixel coordinates. When the
model says `done`, a structured-output vision read of the page is verified
against the page's rendered text, and the output records whether the two
agreed. No selectors or XPath anywhere; the only DOM access is a site-agnostic
`innerText` for the verifier and a generic interactable scan kept for tracing.

## Design decisions, and what decided them

**Grounding: coordinates, by experiment, against my prediction.** I built both
pixel coordinates and Set-of-Mark (numbered badges on every interactable; the
model answers with a number) and pre-registered the decision rule before any
run: keep Set-of-Mark only if it is at least as successful and has a lower
wrong-target rate. I expected it to win. 60 runs on Opus 5, three repositories,
scored against a frozen GitHub API snapshot:

| Model | Arm | Task success | Wrong-target clicks | Detour runs | Click error mean (max) | Cost/run |
|---|---|---|---|---|---|---|
| Opus 5 | coords | 30/30 | 0/90 | 0/30 | 0.8 px (2.0) | $0.153 |
| Opus 5 | som | 30/30 | 3/96 | 3/30 | — | $0.158 |
| Sonnet 5 | coords | 30/30 | 0/90 | 0/30 | 1.1 px (19.1) | $0.062 |
| Sonnet 5 | som | **27/30** | 3/122 | **14/30** | — | $0.068 |

Opus never missed an element centre by more than 2 px. Set-of-Mark's three
errors were all the same: the model wanted "Releases" and answered a
neighbouring badge number in a dense region. The rule said switch, so I did.
The obvious objection, that a smaller model would favour labels, was tested on
Sonnet 5 and was wrong in the other direction: coordinates stayed 30/30, while
Set-of-Mark lost three runs to a hallucinated badge "1009" repeated despite
explicit "not on screen" feedback. Reading a number is the fragile step;
pointing degrades gracefully. Side result: Sonnet 5 with coordinates is 100%
at 40% of the cost.

**Extraction: vision read, then verify against page text.** The graded fields
are 7-hex-char SHAs and version strings, exactly what vision misreads. The
verifier may only correct strings that exist in the rendered text and reports
every correction. It costs ~3.5× the base read. I designed a paired experiment
but spent the budget on grounding, where the outcome was uncertain; a 6-sample
smoke pass agreed on every field in both arms.

**No `goto`; single-turn memory.** A model that can type URLs skips the task.
Fresh single-turn steps keep cost flat and make the agent's memory a readable
list of lines in the trace.

## What didn't work

- **Asynchronous navigation.** GitHub navigates after a click via Turbo; the
  harness once checked the page before navigation began (false "no change"),
  and once ran JavaScript during teardown and crashed. Fix: wait up to 1.5 s
  for a URL change after any click or Enter, and retry `evaluate`.
- **Literal goals on renamed repositories.** `facebook/react` redirects to
  `react/react`. With "exactly named" in the goal, the model correctly rejected
  the redirect target and spent 11 steps and $0.31 hunting. Every click landed
  where intended; instruction-following was the failure. Prompt now accepts a
  redirect to the same project.
- **"Latest" is a semantic, not a position.** neovim lists a nightly
  pre-release first; both extraction arms transcribed it. No verifier can fix a
  wrong choice of release. Prompts now define latest as the Latest-badged entry.
- **My first experiment metric was wrong.** "Misclick = no page change" scored
  0% in both arms because every wrong badge click still navigated. The metric
  that matched manual review was wrong-target: no shared word between the
  model's reason and the element it hit, and the next action going back.
- **The assets bonus, twice.** First attempt: one sentence in the goal asking
  the agent to expand the collapsed Assets section. Result: a 10-step run whose
  final screenshot had scrolled tag and commit off-screen, so they came back
  null. One screenshot cannot hold both. Second attempt, kept: a separate
  bounded pass after the core fields are extracted, which expands the list,
  reads the names, drops any not present in the page text, and resolves URLs
  by link text. openclaw: 12 of 19 listed with real URLs, +3 steps, +$0.07;
  react: both source archives. Still partial: names below the fold are missed.
- **Loop detection was too eager** (three scrolls down a long page counted as
  a loop); a replay test caught it before any live run.

## Trade-offs and limitations

- One fixed viewport, 1280×800 at 1x, so screenshots map 1:1 and stay under the
  API's resize threshold. GitHub's Releases link sits at y≈787, right at the fold.
- Generic DOM reads for the verifier (`innerText`) and the optional Set-of-Mark
  mode; a `<canvas>` app or cross-origin iframe defeats both. `--extraction
  vision` makes a run pixel-only.
- `published_at` is the page's relative text ("18 hours ago"). Download links
  and release notes are what fits in one screenshot after expanding.
- No handling of rate-limit pages beyond a clean `abort`. Two models, three
  repositories, one day; intervals are in the reports.

## With another week

- Haiku 4.5 and a page with genuinely small targets, to find where coordinates
  break. Scroll-and-merge in the assets pass for long lists. The extraction
  experiment as designed. Attach the previous screenshot when an action had
  no effect.
- **Replay with verification.** The 120 committed traces are a memory of what
  worked. On a repeat task, replay the remembered actions and, after each one,
  ask a decision-only model such as TypeSafe's Jev a typed yes/no ("did this
  step land?") against the page's URL and visible text, which it answers with
  a calibrated probability in well under a second; call the vision model only
  when that probability is low, and discard the memory on the first miss.
  Cost drops from ~$0.15 to cents on the happy path while keeping the
  robustness to layout changes the brief asks for. The trap is treating a
  remembered path as authoritative: that is a hardcoded path by another name.
- **Fine-tuning on traces.** Every step is already a (screenshot, history,
  action, outcome) tuple with a scored result. With a few thousand such tuples
  across several sites, a small vision model could be fine-tuned for this
  action schema, trading per-call cost and latency for a dependency on one
  model. The scoring harness is what makes this viable: it labels which
  trajectories to learn from.

## Toward production

Three gaps the brief excluded but real consoles have. **Auth:** classify
login, MFA and session-expired screens as distinct states; resume from a
stored browser session, pause for a human on MFA, abort with a precise reason
otherwise; credentials never pass through the model or the trace.
**Anti-automation:** detect and cooperate, never evade: back off on rate
limits, hand CAPTCHAs to a human, use a persistent authorised browser profile,
and log every challenge as a metric. **Memory:** replay scored traces as
advisory hints verified per step, discarded on the first miss, so the happy
path gets cheap without rebuilding a scraper.
