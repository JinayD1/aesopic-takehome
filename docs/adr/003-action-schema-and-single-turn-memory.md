# ADR 003: Custom action tool and single-turn steps with explicit text history

**Status:** accepted (2026-10-03)

## Context

Two independent choices shape every call to the model: *what actions it can
express* and *what it remembers between steps*.

## Decision 1: a small custom `browser_action` tool

Options were Anthropic's built-in computer-use tool, or our own tool schema.

We chose our own: `click`, `type`, `scroll`, `press`, `back`, `done`, `abort`,
with a `reason` string on every action. Reasons:

- The schema is tiny and strict, so action parsing is unit-testable and every
  invalid action is a typed error we can feed back to the model instead of a crash.
- It is provider-neutral. Swapping in another vision model is a change to one
  file, not to the action vocabulary.
- The built-in tool assumes a desktop (mouse coordinates, screenshots of a
  screen). We wanted `done` and `abort` as first-class terminal actions and a
  grounding mode (`label`) the built-in tool does not have.
- **`goto` was deliberately removed.** An early draft had it. A model that can
  type a URL will jump straight to `/<owner>/<repo>/releases` and skip the
  search → repo → releases flow the task is about. `back` was kept for recovery.

The model's `reason` doubles as data: it goes into the history text, the trace,
and the experiment's wrong-target analysis.

## Decision 2: single-turn steps, memory as explicit text

Options were (a) a growing multi-turn transcript with every screenshot and tool
result, or (b) one fresh request per step containing the system prompt, the
goal, a text list of prior actions and their outcomes, and the current
screenshot.

We chose **(b)**:

- Cost is flat per step (~3–4K input tokens) instead of growing with every
  screenshot. A 15-step run stays under $0.25.
- The agent's memory is literally a list of lines like
  `3. click #15 (open the openclaw/openclaw repository) -> page changed`.
  It is written to the trace, it is what the replay tests assert on, and a
  reviewer can read exactly what the model "knew" at each step.
- The harness can inject facts the model cannot see in a screenshot: that the
  page did not change after the last action, or that it appears to be stuck.
- No thinking-block replay rules to get right across turns.

What we gave up: the model cannot look back at a *previous* screenshot. In
practice the URL, title and outcome line per step have been enough; if it were
not, the fix is to attach the previous screenshot too, not to switch to a
transcript.

## Consequences

- `navigator/llm.py` has one `decide()` call shape; prompt caching covers the
  system prompt and tool definition across steps.
- Loop detection and the stuck hint are implemented in the harness over the
  same history, so they are deterministic and tested without a model.
