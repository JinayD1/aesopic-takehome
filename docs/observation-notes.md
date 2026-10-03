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
