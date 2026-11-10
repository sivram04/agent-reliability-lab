# Design: Investigation Docket

The dashboard (`src/arl/ui/static/`) presents every test run as an air-accident-style investigation file:
verdict first, then probable causes with evidence, recommendations, and the recorder transcript. Recorded from
the built world.

## Principles
- Verdict, then why, then evidence. One dominant number or sentence per page.
- States are printed marks (stamps), never faded rows. Skipped or untested never looks like passed.
- Orange means failure, evidence or regression, and nothing else. Green means passed.
- Every finding sits beside its proof: the exact attack, the reply, leaked strings marked.

## Tokens (`app.css :root`, dark under `[data-theme="dark"]` and `prefers-color-scheme`)
| Role | Light | Dark |
|---|---|---|
| paper / paper-2 | #f6f7f5 / #eceeeb | #0f1214 / #171b1e |
| ink / ink-2 / ink-3 | #14171a / #4a5159 / #626970 | #e8eaeb / #b4bac0 / #8f979e |
| rule / rule-strong | #c5cacd / #14171a | #2c3236 / #e8eaeb |
| orange (marks, large) / orange-text (small) / wash | #ff5a1f / #b8400f / #ffe7dc | #ff6a33 / #ff8a5c / #3a1a0d |
| pass / pass-wash | #2f7d4f / #dff0e5 | #63c48d / #10291b |
| amber (flaky) | #8a5a00 | #f0b44a |

## Type
- Display: DIN-style (`Bahnschrift`, `DIN Alternate`, `DIN 2014`, then condensed sans). Headings 600; the verdict
  700 at `clamp(2.6rem, 7vw, 5.4rem)`, tracking -0.03em.
- Text: system UI stack, 15px, 1.55.
- Mono: only transcripts, IDs, scenario names and data cells (`ui-monospace`, Cascadia Mono, SF Mono).
- Labels (table heads, speakers, stamps): display face, 11px, uppercase, +0.08em tracking.
- Open decision: no web font ships yet (offline, no downloads). Outside Windows and macOS the DIN voice falls
  back to a system sans; self-hosting an OFL DIN-style woff2 is the fix.

## Components
- **Rules:** every line 1px (`--rule`, section heads `--rule-strong`); no radius, no shadows, no cards.
- **Stamp** (`.stamp.{fail,pass,untested,na,flaky,high,medium,low,src}`): bordered uppercase label; fail and flaky
  sit slightly rotated; high is filled. The stamp landing is the page's one animation.
- **Verdict** (`.verdict`): specimen-scale sentence with the count in orange (green when clean), summary
  sentence, stamps, and the pass rate with a ruled 95% interval instrument (0, 50, 100 ticks, end caps).
- **Probable cause** (`.cause`): rank numeral, severity stamp, title, why, evidence lines (ATTACK / REPLY with
  `mark.leak`), FIX line, affected scenario links.
- **Ruled table** with `.bar` (passed share green; weak categories tint the missing share orange).
- **Coverage**: 8 capability cells (hatched when not tested), OWASP LLM and agentic lists with counts or
  UNTESTED / N/A stamps.
- **Recorder** (`.recorder`, `.event`): 2px vertical rail; events USER, TOOL (fault stamp), AGENT (duration bar
  proportional to real time), CRASH; then checks.
- **Filters**: segmented ruled buttons, pressed state inverted (ink on paper).

## Layout
- Content max 1240px, gutter `clamp(16px, 4vw, 48px)`; sticky masthead with a 1px rule.
- Under 860px: single columns, coverage 4 across, recorder 2 columns. Under 600px the nav moves to its own row
  under logo and theme toggle; under 520px evidence and checks stack.
- Browser surfaces themed: selection, focus ring (2px orange), scrollbar colours, underline offset, tabular numerals.
