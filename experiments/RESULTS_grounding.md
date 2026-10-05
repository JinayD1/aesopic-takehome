# Experiment 1: Set-of-Mark vs pixel-coordinate grounding

_Generated 2026-10-03T23:35+00:00 from `results/grounding.jsonl` (60 runs)._

**Question.** Does labelling interactables with numbered badges (Set-of-Mark) navigate more reliably than asking the model for raw pixel coordinates?

**Design.** Same model, prompt, viewport and goal text; only the grounding mode differs. Each run is a full navigation from github.com to the releases page followed by verified extraction. Scored against a frozen GitHub API snapshot (`oracle/`). Intervals are 95% Wilson.

## Headline

| Metric | coords | som |
|---|---|---|
| **Task success** (version + tag match oracle) | 30/30 = 100% (95% CI 89%–100%) | 30/30 = 100% (95% CI 89%–100%) |
| Navigation success (reached /releases) | 30/30 = 100% (95% CI 89%–100%) | 30/30 = 100% (95% CI 89%–100%) |
| Steps, median (p90) | 5 (5) | 5 (5) |
| Misclick rate (clicks with no page change) | 0/90 = 0% (95% CI 0%–4%) | 0/96 = 0% (95% CI 0%–4%) |
| Off-target clicks (landed on no interactable) | 0/90 = 0% (95% CI 0%–4%) | 0/96 = 0% (95% CI 0%–4%) |
| **Wrong-target clicks** (hit an element unrelated to the stated intent) | 0/90 = 0% (95% CI 0%–4%) | 3/96 = 3% (95% CI 1%–9%) |
| Runs with a detour (more than the 5-step minimum path) | 0/30 = 0% (95% CI 0%–11%) | 3/30 = 10% (95% CI 3%–26%) |
| Invalid actions (bad label / out of bounds) | 0 | 0 |
| Mean click error to nearest interactable centre (px) | 0.8 | 0.0 |
| Runs that misclicked or hit the wrong target but still succeeded | 0 | 3 |
| Cost per run, mean (USD) | 0.153 | 0.158 |
| Wall time per run, median (s) | 39.5 | 43.0 |
| Model latency per run, median (s) | 19.1 | 19.6 |

## By repository

| Repo | Arm | Task success | Nav success | Steps (median) | Misclicks / clicks | Cost |
|---|---|---|---|---|---|---|
| openclaw/openclaw | coords | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.170 |
| openclaw/openclaw | som | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 32 | $0.173 |
| pallets/flask | coords | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.140 |
| pallets/flask | som | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.144 |
| react/react | coords | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.149 |
| react/react | som | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 34 | $0.157 |

## Outcomes by arm

- **coords**: success ×30
- **som**: success ×30

## Wrong-target clicks

| Arm | Repo | Run | What happened | Trace |
|---|---|---|---|---|
| som | openclaw/openclaw | 1 | step 4: wanted 'Open the Releases section' hit label 82 'deploy' | `20261003T223211_openclaw-openclaw-01` |
| som | react/react | 0 | step 4: wanted 'Open Releases section via the Releases link in sid' hit label 94 'Add run prettier commit to .git-blame-ig' | `20261003T223049_react-react-00` |
| som | react/react | 8 | step 4: wanted 'Open the Releases section (133 releases) link' hit label 94 'Add run prettier commit to .git-blame-ig' | `20261003T224218_react-react-08` |

## Failed runs

None.

## Decision rule (pre-registered in PLAN.md §7.3, kept in git history)

Keep Set-of-Mark as default if its task-success rate is ≥ coords and its off-target/misclick rate is lower. If coords wins or ties on success *and* is cheaper, switch and document why.

## Reading

_Filled in by hand after the run; see OBSERVATIONS.md._
