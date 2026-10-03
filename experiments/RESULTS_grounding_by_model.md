# Grounding by model

_Generated 2026-10-03T23:35+00:00; 120 runs across 2 model(s). Same harness, prompts, repositories and oracle for every cell._

| Model | Arm | Task success | Wrong-target clicks | Detour runs | Click error px, mean (max) | Steps median | Cost/run | Wall s median |
|---|---|---|---|---|---|---|---|---|
| claude-opus-5 | coords | 30/30 = 100% (95% CI 89%–100%) | 0/90 = 0% (95% CI 0%–4%) | 0/30 | 0.8 (2.0) | 5 | $0.153 | 39.5 |
| claude-opus-5 | som | 30/30 = 100% (95% CI 89%–100%) | 3/96 = 3% (95% CI 1%–9%) | 3/30 | 0.0 (0.0) | 5 | $0.158 | 43.0 |
| claude-sonnet-5 | coords | 30/30 = 100% (95% CI 89%–100%) | 0/90 = 0% (95% CI 0%–4%) | 0/30 | 1.1 (19.1) | 5 | $0.062 | 34.3 |
| claude-sonnet-5 | som | 27/30 = 90% (95% CI 74%–97%) | 3/122 = 2% (95% CI 1%–7%) | 14/30 | 0.0 (0.0) | 5 | $0.068 | 37.6 |

Per-model detail: `RESULTS_grounding.md` (Opus 5), `RESULTS_grounding_<model>.md` (others).
