# ADR 002: Extract with a vision read, then verify against the page's rendered text

**Status:** accepted (2026-10-03)

## Context

The final step turns the releases page into JSON. The graded fields are exactly
the ones a vision model is worst at transcribing from pixels: a 7-character hex
commit SHA in a small monospace font, and version strings where `0`/`O`,
`1`/`l`, `8`/`B` confusions are plausible. A single wrong character is a wrong
answer.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A. Vision-only.** Screenshot → structured output. | Purest reading of "use vision models". One call. | Transcription errors on SHAs and versions go straight into the output. No way to know when it happened. |
| **B. Vision read, then verify against page text.** Same read, then a second call that sees the read *and* `document.body.innerText`, and returns corrected fields plus what changed. | Exact characters come from the rendered text; the screenshot still decides *which* release is the latest and where fields are. Every correction is recorded, so the output says whether the two sources agreed. | One extra call. `innerText` of the whole page is ~5K tokens; the verify call costs ~3.5× the vision read. Reads the DOM (generically). |
| **C. Text-only.** `innerText` → structured output, no screenshot. | Cheapest, exact. | Not a vision approach; fails the brief. Loses the "which one is Latest" judgement that layout and badges provide. |

## Decision

**B.** The screenshot remains the source of judgement (which entry is the
latest, whether it is a pre-release); the text is only a spell-checker for the
strings the screenshot identified. The verifier is instructed never to invent
values and to keep the vision value when the text has nothing matching.

The vision-only path stays behind `--extraction vision` so the comparison can be
re-run at any time.

## Why not run the full extraction experiment

The pre-registered design (PLAN.md §7.2, git history) was a paired comparison on ~60
screenshots × 3 repetitions. We ran a 6-sample smoke pass and chose to spend the
budget on the grounding experiment instead, because the mechanism here is not in
doubt: text verification can only *add* exactness for strings the page renders,
and the question is cost, not whether it helps. The smoke numbers:

| | vision | verified |
|---|---|---|
| whole record correct | 5/6 | 5/6 |
| vision and text agreed on every field | — | 6/6 |
| cost per sample | $0.022 | $0.077 |

The one miss was the same in both arms and was not a transcription error: on
neovim's page the top entry is a nightly pre-release, and both arms transcribed
it instead of the entry badged "Latest". Verification cannot fix a wrong
*choice* of release. That led to the prompt change in commit `7c9ec25`
(define "latest" as the Latest-badged entry).

## Consequences

- Output carries `run.verification` (`agree` / `corrected` / `skipped`)
  and a per-field `corrections` list. Consumers can see when vision was wrong.
- Extraction costs roughly $0.10 per run instead of $0.02. Acceptable for a
  one-off tool; for volume, trim `innerText` to the region around the release
  card or drop effort to `medium` on the verify call.
- The honest caveat for the README: on a `<canvas>` page or a cross-origin
  iframe there is no `innerText`, and the tool silently degrades to vision-only.
