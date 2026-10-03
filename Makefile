.PHONY: setup test test-live lint demo demo-headed experiment-grounding analyze gif clean

PY := .venv/bin/python
NAV := .venv/bin/navigate

setup:            ## create venv, install deps and Chromium
	uv venv -q
	uv pip install -q -e ".[dev]"
	$(PY) -m playwright install chromium

test:             ## unit + replay tests (no network, no API key)
	.venv/bin/pytest -q

test-live:        ## one real run against GitHub + Anthropic, scored against the API
	.venv/bin/pytest -q -m live

lint:             ## ruff + mypy
	.venv/bin/ruff check navigator tests experiments
	.venv/bin/ruff format --check navigator tests experiments
	.venv/bin/mypy navigator tests experiments

demo:             ## the take-home task
	$(NAV) --repo openclaw/openclaw --out sample_output.json

demo-headed:      ## same, with a visible browser
	$(NAV) --repo openclaw/openclaw --headed --slow-mo 300

experiment-grounding:  ## Set-of-Mark vs coordinates (costs money; see PLAN.md §7)
	$(PY) -m experiments.run_grounding --runs 10 --parallel 3

analyze:          ## regenerate experiments/RESULTS_*.md from results/*.jsonl
	$(PY) -m experiments.analyze

gif:              ## build docs/demo.gif from the newest trace under runs/
	$(PY) -m navigator.tools.trace_gif $$(ls -td runs/2026* | head -1) docs/demo.gif

clean:
	rm -rf runs/ .pytest_cache .mypy_cache .ruff_cache
