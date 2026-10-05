# Experiment 1: Set-of-Mark vs pixel-coordinate grounding

_Generated 2026-10-03T23:35+00:00 from `results/grounding.jsonl` (60 runs)._

**Question.** Does labelling interactables with numbered badges (Set-of-Mark) navigate more reliably than asking the model for raw pixel coordinates?

**Design.** Same model, prompt, viewport and goal text; only the grounding mode differs. Each run is a full navigation from github.com to the releases page followed by verified extraction. Scored against a frozen GitHub API snapshot (`oracle/`). Intervals are 95% Wilson.

## Headline

| Metric | coords | som |
|---|---|---|
| **Task success** (version + tag match oracle) | 30/30 = 100% (95% CI 89%–100%) | 27/30 = 90% (95% CI 74%–97%) |
| Navigation success (reached /releases) | 30/30 = 100% (95% CI 89%–100%) | 27/30 = 90% (95% CI 74%–97%) |
| Steps, median (p90) | 5 (5) | 5 (7) |
| Misclick rate (clicks with no page change) | 0/90 = 0% (95% CI 0%–4%) | 31/122 = 25% (95% CI 19%–34%) |
| Off-target clicks (landed on no interactable) | 0/90 = 0% (95% CI 0%–4%) | 0/122 = 0% (95% CI 0%–3%) |
| **Wrong-target clicks** (hit an element unrelated to the stated intent) | 0/90 = 0% (95% CI 0%–4%) | 3/122 = 2% (95% CI 1%–7%) |
| Runs with a detour (more than the 5-step minimum path) | 0/30 = 0% (95% CI 0%–11%) | 14/30 = 47% (95% CI 30%–64%) |
| Invalid actions (bad label / out of bounds) | 0 | 31 |
| Mean click error to nearest interactable centre (px) | 1.1 | 0.0 |
| Runs that misclicked or hit the wrong target but still succeeded | 0 | 11 |
| Cost per run, mean (USD) | 0.062 | 0.068 |
| Wall time per run, median (s) | 34.3 | 37.6 |
| Model latency per run, median (s) | 14.7 | 17.4 |

## By repository

| Repo | Arm | Task success | Nav success | Steps (median) | Misclicks / clicks | Cost |
|---|---|---|---|---|---|---|
| openclaw/openclaw | coords | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.071 |
| openclaw/openclaw | som | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 6 | 12 / 45 | $0.081 |
| pallets/flask | coords | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.055 |
| pallets/flask | som | 9/10 = 90% (95% CI 60%–98%) | 9/10 = 90% (95% CI 60%–98%) | 5 | 5 / 34 | $0.055 |
| react/react | coords | 10/10 = 100% (95% CI 72%–100%) | 10/10 = 100% (95% CI 72%–100%) | 5 | 0 / 30 | $0.061 |
| react/react | som | 8/10 = 80% (95% CI 49%–94%) | 8/10 = 80% (95% CI 49%–94%) | 6 | 14 / 43 | $0.068 |

## Outcomes by arm

- **coords**: success ×30
- **som**: success ×27, loop_detected ×3

## Wrong-target clicks

| Arm | Repo | Run | What happened | Trace |
|---|---|---|---|---|
| som | openclaw/openclaw | 1 | step 7: wanted 'Click Releases link to open the Releases section' hit label 82 'fix(doctor): quarantine an unusable agen' | `20261003T232332_openclaw-openclaw-01` |
| som | openclaw/openclaw | 5 | step 1: wanted 'Open site search to find the repository' hit label 9 'Sign in' | `20261003T232823_openclaw-openclaw-05` |
| som | react/react | 7 | step 1: wanted 'Open the site search to find the react/react repos' hit label 9 'Sign in' | `20261003T233116_react-react-07` |

## Failed runs

| Arm | Repo | Run | Status | Detail | Trace |
|---|---|---|---|---|---|
| som | pallets/flask | 2 | loop_detected | repeated '7. click #1009 (Click on Releases link to view the latest release details.) -> I | `/Users/jinay/Documents/aesopic-takehome/experiments/traces/grounding-claude-sonnet-5/som/20261003T232525_pallets-flask-02` |
| som | react/react | 2 | loop_detected | repeated '7. click #1009 (Click on Releases section to view latest release details.) -> IN | `/Users/jinay/Documents/aesopic-takehome/experiments/traces/grounding-claude-sonnet-5/som/20261003T232455_react-react-02` |
| som | react/react | 8 | loop_detected | repeated '6. click #1009 (Click on Releases section to view latest release details) -> INV | `/Users/jinay/Documents/aesopic-takehome/experiments/traces/grounding-claude-sonnet-5/som/20261003T233241_react-react-08` |

## Decision rule (pre-registered in PLAN.md §7.3, kept in git history)

Keep Set-of-Mark as default if its task-success rate is ≥ coords and its off-target/misclick rate is lower. If coords wins or ties on success *and* is cheaper, switch and document why.

## Reading

_Filled in by hand after the run; see OBSERVATIONS.md._
