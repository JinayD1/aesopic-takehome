# Aesopic Take-Home: Vision-Driven GitHub Navigator — Plan

## 0. What the task actually is

Build a CLI that drives a real browser, uses a vision model to *look* at the page and decide
what to do next, and ends with structured JSON about the latest release of a GitHub repo.
No hardcoded CSS selectors or XPath. Graded more on design decisions, edge cases, testing,
and honest reflection than on perfection.

Ground truth today (via GitHub API, used only as a test oracle, never in the product path):

| Field | Value |
|---|---|
| repo | openclaw/openclaw (391k stars) |
| latest tag | v2026.9.8 |
| published | 2026-10-03T03:21Z |
| author | github-actions[bot] |
| assets | 17 |

Notes on the sample output in the PDF: `"tag": "77e703c"` is a **short commit SHA**, not a
tag name. GitHub's release card shows both the tag (left sidebar) and the commit SHA. We will
output `tag`, `commit`, and `version` separately and explain the ambiguity in the README.
`"author": "steipete"` was presumably true when the PDF was written; today the releaser is a
bot. Our tool should report whatever the page shows.

Search for "openclaw" returns decoys: `VoltAgent/awesome-openclaw-skills`,
`hesamsheikh/awesome-openclaw-usecases`, `mengjian-github/openclaw101`. Repo
disambiguation is a real edge case, not a hypothetical one.

---

## 1. How a vision agent works (the mental model)

Every browser vision agent is the same loop:

```
goal ──► [observe] screenshot (+ optional structured hints)
              │
              ▼
         [think]   vision model: "given goal + history + what I see, what's the next action?"
              │
              ▼
         [act]     harness executes: click(x,y) / type(text) / scroll / press(key) / goto(url) / done(result)
              │
              ▼
         wait for page to settle ──► loop (until done, step budget, or stuck)
```

Three things decide accuracy:

1. **Grounding** — turning "click the Releases link" into something the harness can execute.
   This is where most failures live.
2. **State / memory** — the model needs to know what it already did so it doesn't loop
   (e.g. re-clicking search, re-scrolling).
3. **Verification** — checking that an action had the intended effect (URL changed, page
   title changed, element appeared) before moving on.

### Grounding alternatives

| Approach | How | Pros | Cons |
|---|---|---|---|
| **A. Pure pixel coordinates** | Model returns `(x, y)` from the screenshot. This is what Anthropic's computer-use tool does. | "Purest" vision. Zero DOM dependence. Works on canvas/iframes. | Coordinate precision degrades with image downscaling; small links (release tag, commit SHA) are easy to miss by a few pixels. Needs careful screenshot→viewport scaling. |
| **B. Set-of-Mark (SoM)** | Harness finds *all* interactive elements generically (`a, button, input, [role=...]`), draws numbered boxes on the screenshot, model answers "click #14". | Big accuracy win. Model picks a label, not a pixel. Still no page-specific selectors. | Uses the DOM generically. Must argue in README that "generic interactable scan" ≠ "hardcoded selector". Visual clutter on dense pages (GitHub search results). |
| **C. Hybrid: screenshot + accessibility tree text** | Send screenshot *and* a text list of `[idx] role "name"` for visible interactables. Model picks idx. | Model reads exact text (SHAs, tags) from the a11y tree, not pixels. Robust to visual ambiguity. Used by browser-use, Stagehand-style tools. | More tokens per step. Reviewer may see it as "less vision". |
| **D. Text-only a11y tree** | No screenshot. | Cheapest, fastest. | Fails the "use vision models" requirement. Useful only as a baseline for the observations doc. |

**Recommendation:** implement **B (SoM) as the default** and **A (pure coordinates) behind
a `--grounding coords` flag**. Both are legitimately vision-driven; shipping both gives a
real comparison for the observations doc (success rate, steps, cost), which is exactly what
the "critical thinking" criterion rewards. C is a possible stretch if time allows.

### Extraction alternatives (the last step)

| Approach | Pros | Cons |
|---|---|---|
| **Vision-only read** of the release page screenshot → structured output | Pure. | Models misread 7-char hex SHAs and version strings from pixels. Hallucination risk on exactly the fields we're graded on. |
| **Vision + visible page text** (`document.body.innerText` of the release card region, no selectors) → structured output | Exact strings. Model uses the screenshot to know *which* text is the latest release, the text to transcribe it. | Slightly less "pure". |
| **Vision read, then verify against page text** | Best of both. Report confidence + whether the two agreed. | Extra step. |

**Recommendation:** vision read first, then a verification pass against the page's visible
text. If they disagree, trust the text and flag it in the output (`"verification":
"mismatch"`). Document the measured disagreement rate.

---

## 2. Architecture

```
aesopic-navigator/
├── navigate.py            # CLI entrypoint (argparse)
├── navigator/
│   ├── agent.py           # observe→think→act loop, step budget, loop detection
│   ├── browser.py         # Playwright wrapper: goto, screenshot, click, type, scroll, press, settle()
│   ├── grounding.py       # SoM overlay (generic interactable scan + numbered boxes) / coords scaling
│   ├── llm.py             # Anthropic client, tool defs, structured-output extraction, retries
│   ├── schemas.py         # pydantic: Action, StepRecord, ReleaseInfo, RunResult
│   ├── prompts.py         # system prompt + goal templates
│   └── trace.py           # per-run folder: step_N.png, step_N.json, run.json, cost summary
├── tests/
│   ├── test_action_parsing.py     # unit: tool-call → Action, bad inputs
│   ├── test_grounding.py          # unit: overlay math, coordinate scaling
│   ├── test_replay.py             # recorded screenshots → deterministic expectations (mock model)
│   ├── test_live_smoke.py         # @slow: real run against openclaw, compares to GitHub API oracle
│   └── fixtures/
├── traces/                # committed example runs (evidence of validation)
├── sample_output.json
├── README.md
├── OBSERVATIONS.md
└── pyproject.toml  (uv)
```

### Action schema (custom tools, not the built-in computer-use tool)

```
click(target)          # target = label id (SoM) or {x,y} (coords)
type(text, submit)     # into the focused element; submit=True presses Enter
scroll(direction, amount)
press(key)
goto(url)              # allowed; the model may navigate directly if it knows the URL
done(result)           # terminal; result is free-form; extraction is a separate structured call
abort(reason)          # terminal; e.g. rate-limited, repo not found
```

Why custom tools over Anthropic's built-in computer-use tool:
- Explicit, small schema → trivial to unit test and to explain in the README.
- Portable across providers (easy to add an OpenAI backend behind a flag if we want a
  model comparison).
- The built-in tool assumes a desktop; we're in a browser and want `goto`/`done`.

### Model

- Default: `claude-opus-5`, adaptive thinking, `output_config.effort = "medium"` for
  navigation steps (fast, cheap), `"high"` for the final extraction.
- `--model` flag so Sonnet 5 / Haiku 4.5 can be compared in the observations doc.
- Server-side refusal fallback enabled per current SDK guidance.
- Final extraction via structured outputs (`output_config.format`) into the `ReleaseInfo`
  pydantic schema, so the JSON is always well-formed.

Cost envelope: ~1,500 tokens per screenshot, ~10 steps, plus prompt → well under $0.50/run
on Opus 5. Note it in the README.

### Reliability features (the "edge case handling" criterion)

- **Step budget** (`--max-steps`, default 15) and **wall-clock timeout**.
- **Loop detection**: same action on same URL 3× → inject a "you appear stuck" message, then abort.
- **Post-action verification**: after `click`, record URL/title delta. After "click the repo",
  assert URL path matches `/{owner}/{repo}` — URL checks are not selectors.
- **Page settle**: wait for network-idle with a cap; GitHub is SPA-ish (Turbo) and URL
  changes without full loads.
- **Overlay/popup handling**: cookie/sign-up banners — the model sees them and dismisses
  them; keep them in the prompt as an expected case.
- **Rate limiting / 429 / abuse page**: detect by title/text, back off once, then abort cleanly
  with a JSON error object (never a stack trace).
- **Anthropic API errors**: typed retry chain (rate limit, 5xx, connection) with jitter.
- **Headless vs headed**: `--headed` for debugging; default headless. Real UA string to avoid
  bot heuristics.
- **Screenshot scaling**: fixed viewport (e.g. 1280×900), scale to model-friendly size,
  keep the scale factor for coordinate mode.
- **Graceful partial output**: if extraction partially fails, emit what we have with `null`s
  and an `errors[]` array.

### CLI surface

```
python navigate.py --repo openclaw/openclaw
python navigate.py --url https://github.com --prompt "search for openclaw and get the current release and related tags"
python navigate.py --repo facebook/react --prompt "list the key features of the latest release"   # bonus
flags: --model --grounding {som,coords} --max-steps --headed --trace-dir --out --verify-with-api
```

`--repo` is sugar: it builds the same natural-language goal, so there is one agent, not two.

### Output

```json
{
  "repository": "openclaw/openclaw",
  "latest_release": {
    "version": "v2026.9.8",
    "tag": "v2026.9.8",
    "commit": "abc1234",
    "author": "github-actions[bot]",
    "published_at": "2026-10-03",
    "release_notes": "...",          // bonus
    "download_links": ["..."]        // bonus
  },
  "run": { "steps": 9, "model": "claude-opus-5", "grounding": "som",
           "input_tokens": ..., "output_tokens": ..., "cost_usd": ...,
           "verification": "agree|mismatch|skipped", "trace_dir": "traces/2026-10-03T.." }
}
```

---

## 3. Testing approach

1. **Unit** (no network, no API): action parsing, overlay geometry, coordinate scaling,
   loop detector, URL assertions.
2. **Replay** (no API): recorded screenshots + a scripted fake model → asserts the harness
   executes the right Playwright calls. Proves the loop mechanics independently of the model.
3. **Live smoke** (API + network, marked slow): full run on openclaw; compare `version`/`tag`
   against GitHub REST API. Run N=5–10 times per grounding mode and record success rate.
4. **Scenario tests**: wrong-repo decoy (goal = "awesome-openclaw-skills" to prove it
   doesn't just pick the first result), a repo with no releases (expect clean abort), a repo
   with a pre-release as newest (does "Latest" badge win?), a second repo (react) for the
   generality bonus.
5. **Chaos**: `--max-steps 3` → verify graceful abort JSON; kill network mid-run.

The traces from (3) and (4) are committed as evidence.

---

## 4. Build phases (fits 4–6 h)

| Phase | What | ~Time |
|---|---|---|
| 1 | Scaffold: uv project, Playwright install, browser wrapper, screenshot → file | 30 min |
| 2 | Agent loop with coords grounding + custom tools, hard-coded goal, trace dir | 60 min |
| 3 | SoM grounding, structured extraction with text verification | 60 min |
| 4 | Reliability: step budget, loop detection, settle, errors → JSON | 45 min |
| 5 | Tests: unit + replay + live smoke with API oracle, run comparisons | 60 min |
| 6 | README, OBSERVATIONS.md, sample_output.json, bonus flags | 45 min |

---

## 5. Decisions made (2026-10-03)

| # | Decision | Choice | Alternative kept for experiment |
|---|---|---|---|
| 1 | Language | Python 3.10 + Playwright + uv + pydantic + anthropic SDK | — |
| 2 | Grounding | ~~Set-of-Mark~~ **Pixel coordinates** (switched 2026-10-03 by the §7.1 experiment and the §7.3 rule) | Set-of-Mark via `--grounding som` |
| 3 | Extraction | Vision read, then verify against visible page text | Vision-only via `--extraction vision` |
| 4 | Provider | Anthropic only; `--model` flag for Opus 5 / Sonnet 5 / Haiku 4.5 comparison | — |

Decisions 2 and 3 are provisional until the experiments in §7 run. If the data says
otherwise, we switch the default and say so in the ADR.

## 6. Open items / assumptions to document

- Need an `ANTHROPIC_API_KEY` in the environment (none set right now).
- "tag" in the sample output is a commit SHA; we output both and say so.
- GitHub may change search ranking; the agent must choose by exact name, not position.
- The repo is public and unauthenticated; headless Chromium may occasionally hit GitHub's
  abuse detection. We handle it, and report it in observations if it happens.

---

## 7. Experiments (run after the build; results feed the ADRs and OBSERVATIONS.md)

Shared rules for both experiments:

- **Frozen oracle.** Fetch the GitHub REST API once at experiment start, save
  `experiments/oracle/<repo>.json` with a timestamp. openclaw released *today*; a new release
  mid-experiment would otherwise corrupt the scoring.
- **Same model, same prompt, same viewport** across arms. Only the variable under test changes.
- **Every run writes one JSONL row** (`experiments/results/<exp>.jsonl`) with arm, repo,
  seed/run index, all metrics below, cost, latency, and the trace dir.
- **Report uncertainty.** N is small, so success rates get 95% Wilson confidence intervals.
  We say "SoM 9/10 vs coords 6/10, intervals overlap" rather than "SoM is 50% better".
- **Analysis is a script**, `experiments/analyze.py`, that emits the markdown tables and the
  charts pasted into OBSERVATIONS.md. Anyone can re-run it.

### 7.1 Grounding: Set-of-Mark vs pure coordinates

**Design.** 2 arms × 3 repos × 10 runs = 60 full navigation runs. Repos chosen to vary
difficulty: `openclaw/openclaw` (decoy-heavy search), `facebook/react` (dense releases page,
long notes), one small repo with few releases. Est. cost ≈ 60 × $0.30 ≈ $18 on Opus 5.
Optional third arm if budget allows: coords at 2× device-pixel-ratio, to show the downscaling
effect directly.

| Metric | Definition | Why it matters |
|---|---|---|
| **Task success** (primary) | Final `version` and `tag` match the frozen oracle | The only thing the grader ultimately sees |
| **Navigation success** | Agent reached URL path `/{owner}/{repo}/releases` | Isolates grounding from extraction errors |
| **Steps to completion** | Count of actions; report median and p90 vs the 5-step minimum path | Efficiency; wasted steps = wasted cost and latency |
| **Misclick rate** | Clicks after which URL, title, and focused element are all unchanged | Direct measure of grounding precision |
| **Wrong-target rate** | Click landed inside a *different* interactable's box than the one the model named in its `reason` field (post-hoc, using the same generic scan as a measuring tool) | Distinguishes "missed" from "hit the wrong thing", the latter derails runs |
| **Click error (px)** | Coords arm only: distance from the click point to the center of the nearest interactable | Quantifies the precision argument from §1 |
| **Recovery rate** | Share of misclicks followed by eventual task success | Does the loop self-correct? |
| **Abort rate by cause** | step budget / loop detected / rate limited / model error | Edge-case handling evidence |
| **Cost per run** | Input + output tokens → USD | SoM adds overlay pixels; coords may add retries |
| **Latency** | Wall-clock per step and per run | Practical deployability |

### 7.2 Extraction: vision-only vs vision + text verification

**Design.** Paired: both extractors run on the *same* final-page screenshot, so the comparison
is not confounded by navigation variance. Inputs: the final screenshots from every successful
7.1 run (≈50) plus 5 hand-captured releases pages with awkward shapes (pre-release on top,
20+ assets, no releases, long notes pushing fields off-screen, dark-mode). Each extractor runs
3× per screenshot. Cost is small (one or two calls per sample).

| Metric | Definition | Why it matters |
|---|---|---|
| **Field accuracy** (primary) | Exact match vs oracle, per field: version, tag, commit SHA, author, published date | Shows *which* fields vision misreads |
| **Record accuracy** | All required fields correct in one output | The grader's view |
| **Character error rate** | Normalized edit distance on SHA and version | Shows the *nature* of errors (single-char confusions vs hallucinated values) |
| **Confusion table** | Which characters got swapped (0/D, 1/l, 8/B …) | Concrete, memorable evidence for the write-up |
| **Hallucination rate** | Non-null value emitted for a field that is not visible in the screenshot | Honesty of the extractor |
| **Correction precision** (verify arm) | Of the fields the text check changed, share that became correct | A verifier that "fixes" right answers is worse than none |
| **Agreement rate** (verify arm) | Share of samples where vision and text agreed on every field | How often the second step is even needed |
| **Extra cost / latency** | Tokens and seconds added by the verification call | The price of the accuracy |

### 7.3 Decision rule, stated up front

- Grounding: keep SoM as default if its task-success rate is ≥ coords and its wrong-target
  rate is lower. If coords wins or ties on success *and* is cheaper, switch and document why.
- Extraction: keep verification if it raises record accuracy and correction precision ≥ 0.9.
  If vision-only is already ≥ 95% on SHA, say so and make verification opt-in.

Pre-registering the rule is itself a talking point: we decided how to decide before seeing data.

---

## 8. Standing out: commit history and submission polish

### 8.1 Git workflow

- `git init` before writing the first line of code. Linear history on `main`, one logical
  change per commit, Conventional Commits prefixes (`feat:`, `test:`, `docs:`, `exp:`).
  Target ≈ 25–35 commits across the build, roughly one every 10–15 minutes of real work.
- Commit bodies say *why*, not just what. Example:
  `feat(grounding): add Set-of-Mark overlay` + body explaining the generic interactable scan
  and why labels beat coordinates.
- Tags at milestones: `v0.1-loop-works`, `v0.2-som`, `v0.3-extraction`, `v1.0-submission`.
- Real timestamps only. No backdating, no squashing into one "initial commit".
- AI-assistant attribution: the brief explicitly allows AI tools, so commits keep a
  `Co-Authored-By: Claude` trailer. Transparent, and it matches what they said they value.

### 8.2 Repository artifacts that reviewers notice

| Artifact | What it signals |
|---|---|
| `docs/adr/001-grounding.md`, `002-extraction.md`, `003-action-schema.md` | Architecture Decision Records: context, options, decision, consequences, with the experiment numbers pasted in |
| `OBSERVATIONS.md` with charts + a "what didn't work" section showing real failure screenshots | Honest reflection, the criterion they underlined |
| `traces/` with annotated SoM screenshots from real runs, and a GIF of one run at the top of the README | Visual proof it works; makes the README skimmable |
| `experiments/` with oracle snapshots, raw JSONL, `analyze.py`, and a "reproduce" section | Data-driven decisions, reproducible |
| GitHub Actions CI running unit + replay tests on every push (no API key needed) | Engineering discipline; green badge in README |
| `ruff` + `mypy --strict` clean, type hints throughout, pydantic models | Code quality |
| `Makefile` / `uv run` tasks: `make test`, `make test-live`, `make experiment`, `make demo` | Low-friction setup, the "clear run instructions" requirement |
| `.env.example`, cost line printed at the end of every run | Operational awareness |
| README "Limitations" and "With another week" sections | Critical thinking without overclaiming |
| Bonus flags working: `--repo facebook/react`, natural-language `--prompt`, release notes / assets / dates in output | Goes beyond must-haves without bloating the core |

### 8.3 Things to avoid

- Over-engineering the abstraction layer (no plugin systems, no provider registry).
- A 2,000-word README. Keep it under one screen plus links to ADRs and OBSERVATIONS.
- Claiming reliability numbers we did not measure.
