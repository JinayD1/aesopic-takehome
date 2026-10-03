# Running observation notes

Raw, chronological notes taken during the build. Condensed into OBSERVATIONS.md
at the end. Each entry: what happened, why it matters.

## 2026-10-03

- **Sample output's `tag` is a commit SHA.** The brief's example has
  `"tag": "77e703c"`, which is a 7-char hex, i.e. the short commit shown next to
  the tag on the release card. We output `tag`, `commit` and `version` as separate
  fields and document the mapping.
- **Author on the page vs the API differ.** Page shows `github-actions`; the REST
  API says `github-actions[bot]`. Scoring against the API must normalise this or it
  will count a correct read as wrong.
- **Annotated tags.** `GET /git/ref/tags/v2026.9.8` returns a *tag object*
  (b1c1c6d), not the commit. The release page shows the dereferenced commit
  (fc23bc8). The experiment oracle must dereference annotated tags.
- **GitHub search has decoys.** "openclaw" returns `openclaw/openclaw` first today,
  but also `VoltAgent/awesome-openclaw-skills`, `hesamsheikh/awesome-openclaw-usecases`,
  `mengjian-github/openclaw101`. The goal text names the exact repo; the model
  picked the right one in every run so far (SoM and coords).
- **Removed `goto` from the action set.** A model that can type a URL will jump to
  `/releases` directly and skip the flow the task is about. Replaced with `back`.
- **Single-turn steps instead of a growing transcript.** Each step = system prompt
  + goal + text history + current screenshot. Cost is flat per step and the
  agent's memory is literally the history text in the trace.
- **Loop detection bug caught by replay test.** Counting *every* repeated action
  flagged "scroll down x3 on a long page" as a loop. Now only ineffective actions
  (no page change) count.
- **Async navigation race (real bug, found live).** GitHub navigates with Turbo
  after a click; the harness checked the page before navigation began and once
  ran JS during teardown (`Execution context was destroyed`). In the headed demo
  this showed up as the model clicking Releases twice: the first click worked
  but was reported as "no visible change". Fix: after click/Enter, wait up to
  1.5 s for a URL change, and retry `evaluate` once if the context was destroyed.
  The model's self-recovery (re-click after "no visible change") worked before
  the fix, which is a nice robustness datapoint.
- **First live numbers (Opus 5, SoM):** 5 steps, 71.5 s, $0.17, 7 API calls,
  vision read and page text agreed on all fields. Coords mode: 5 steps, 50.5 s,
  $0.17; all three clicks landed on the intended element (post-hoc attribution
  labels 8, 15, 81). Releases link sits at y≈787 of an 800 px viewport, i.e.
  right at the fold; a slightly smaller viewport would push it off-screen and
  force a scroll.
- **Strict tool schema gotcha.** `{"type": ["string","null"], "enum": [...]}` is
  rejected under `strict: true`; use `anyOf` with a null branch.
- **Workspace-scoped API keys.** Org keys not scoped to a workspace need the
  `anthropic-workspace-id` header; the client reads `ANTHROPIC_WORKSPACE_ID`.
- **Renamed repositories (real failure, found live).** `facebook/react` now
  301-redirects to `react/react`. With the goal saying "exactly named
  facebook/react", the model landed on react/react, correctly observed the name
  mismatch, hit `back`, and spent 11 more steps hunting for a repo that no longer
  exists under that name, then aborted at the step budget ($0.31). Literal
  instruction-following was the failure mode, not grounding: every click landed
  where intended. Fix: the system prompt now says redirected/renamed items are
  acceptable when it is clearly the same project, and the goal text no longer
  says "exactly named".
- **Search overlay trap.** While GitHub's search dialog is open, the occlusion
  filter correctly labels only the dialog's elements. The model then tried to
  click a sidebar link *behind* the dialog, emitting a click with no label ->
  GroundingError fed back as INVALID. Escape should close the dialog; worth a
  closer look if it recurs in the experiments.
- **"Latest" is a semantic, not a position.** On neovim's releases page the top
  entry is the nightly *pre-release*; the release GitHub badges "Latest" (0.12.5)
  is second and off-screen. Both extraction arms transcribed the nightly build,
  so both were "wrong" against the API, which excludes pre-releases from
  `/releases/latest`. No amount of text verification fixes a wrong *choice* of
  release. Fix: the goal and extraction prompts now define latest as the entry
  badged "Latest" and tell the navigator to scroll/click if the top entry is a
  pre-release. The fixture stays in the extraction set as a known-hard case.
- **Verification is ~3.5x the extraction cost** on the smoke run ($0.077 vs
  $0.022 per sample): the page text is ~5K tokens and the call runs at high
  effort. Worth trimming the text to the visible region if cost matters.
