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
- **Grounding experiment result (60 runs, Opus 5).** Both arms 30/30 task
  success, median 5 steps. Coordinate clicks landed within 0.8 px (mean) of
  element centres; max error over 90 clicks was 2 px. Set-of-Mark produced 3
  wrong-target clicks out of 96 (3%): in all three the model wanted "Releases"
  but answered a nearby badge number (94 vs 92; 82 vs 86) in the dense region
  where the sidebar's Releases badge sits among file-list rows. Each was
  recovered in two extra steps. Coords: 0/90. Cost $0.153 vs $0.158, wall time
  39.5 s vs 43.0 s. Pre-registered rule (PLAN.md §7.3) says: tie on success and
  cheaper -> switch default to coords. The hypothesis that SoM would be more
  accurate was wrong for this model on this site. Caveats: one site, large
  well-spaced targets, one model; SoM's expected advantage (tiny targets,
  weaker localisers) was never exercised.
- **Metric lesson.** "Misclick = no page change" missed every real SoM error,
  because the wrong click *did* navigate. The useful metric was wrong-target:
  no word overlap between the model's reason and the hit element's text, AND
  the model's next action went back. First version without the second
  condition flagged every search-box click (stop-word bug); the two-condition
  version matches manual review exactly.
- **Sonnet 5 replication (60 runs).** Coords 30/30, mean error 1.1 px, one
  19 px click still inside the Releases box. SoM 27/30: 3 loop_detected runs
  where the model asked for badge "1009" three times despite INVALID feedback
  naming the valid range; 14/30 detours; 2 "Sign in" (9) for search (8). The
  "smaller model prefers labels" hypothesis is not supported; the symbolic
  read-a-number step is the fragile part. Sonnet coords: $0.062, 34 s.
- **Assets bonus, tried and reverted.** Adding "expand the collapsed Assets
  section before you stop" to the goal made a 10-step, $0.32 run (five scrolls)
  and the final screenshot was scrolled to the asset list, so tag and commit
  were off-screen and extracted as null. One screenshot cannot hold both the
  header and 17 assets. Doing this properly needs a second extraction pass on
  a second screenshot (or a full-page capture), not a prompt line. Reverted;
  `download_links` stays empty unless assets happen to be visible.
- **Assets, second attempt (kept).** Separate bounded pass after core
  extraction: sub-goal "expand the Assets section", <=4 steps, structured read
  of names, names verified against page text, URLs resolved by matching anchor
  visible text. openclaw: 12/19 listed (17 uploads + 2 source archives) with real download URLs (+3 steps, +$0.07,
  core fields untouched, verification agree). react: 2 source archives, model
  noticed the list was already open. 7 openclaw entries missed below the fold.
- **Verification earned its keep, in the notes.** Two openclaw runs: vision
  misspelled 4 handles and truncated the thanks list at 15/21; verifier fixed
  all of it from page text. Output said "agree" because release_notes was not
  in the diffed fields. Added notes_corrected + a word-level change summary;
  outcome is now "corrected" when notes change.
