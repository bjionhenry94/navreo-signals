# Common Mechanical Fixes

Fixes that can be applied automatically without user judgement. Each entry has a before/after pattern. The analyser flags these; the fix layer applies them when in mode 2 or 3.

## Apostrophe standardisation

**Default direction**: straight (`'`) for plain-text rendering safety. Override only if the user explicitly asks for curly.

| Find | Replace |
|---|---|
| `'` (U+2019, curly apostrophe) | `'` (U+0027) |
| `'` (U+2018, curly opening) | `'` (U+0027) |
| `"` (U+201C) | `"` (U+0022) |
| `"` (U+201D) | `"` (U+0022) |
| `—` (U+2014, em-dash) | ` - ` (space-hyphen-space) — but only if not inside a known intentional pattern |

## Stray whitespace

| Find | Replace |
|---|---|
| `{{Icebreaker}}&nbsp;` | `{{Icebreaker}}` |
| `{{Icebreaker-2}}&nbsp;` | `{{Icebreaker-2}}` |
| `&nbsp;%signature%` | `%signature%` |
| ` %signature%` (leading space) | `%signature%` |

## P.S. formatting

| Find | Replace |
|---|---|
| `P.S - ` | `P.S. ` |
| `P.S. - ` | `P.S. ` |
| `P.S -` | `P.S.` |
| `P.S. -` | `P.S.` |
| `P.S, ` | `P.S., ` |

## Common typos (from prior runs)

| Find | Replace |
|---|---|
| `Alternatively if ` | `Alternatively, if ` |
| `which would hold-back` | `that would hold back` |
| `sales-teams` (when used as plural noun) | `sales teams` |

## NOT mechanical (require user input)

These are flagged but never auto-applied:

- Subject line A/B diversification (need to know which variant gets which subject)
- Adding/removing P.S. across variants
- Adding/removing `{{Icebreaker}}` to a variant that's missing it
- Awkward sentence rewrites (multiple correct rewrites possible)
- Step 1 first-touch delay change (1 → 0)
- Removing deleted variants from the database (only achievable in UI)
- Inline `style=` cleanup (may be intentional in some setups)

## How to apply

In mode 2: output a section called "Mechanical fixes applied" with a before/after summary, plus paste-ready corrected copy.

In mode 3: ask the user for an explicit go-ahead first if the campaign has real send history, then build the `save_campaign_sequences` payload with mechanical fixes applied — from a FRESH fetch, with every step `id` and variant `id` echoed back unchanged (dropping an id permanently orphans that variant's stats). Translate GET→POST names: wrap in `{"sequences":[...]}` (plural), `sequence_variants`→`seq_variants`, `delayInDays`→`delay_in_days`. Full recipe + worked payload: SKILL.md Step 10 and `lilly-bot` → "THE ID-INTACT RECIPE". After save attempt:
- If save succeeded: re-fetch and confirm changes stuck AND every pre-existing variant kept its exact `id`. Run a fresh QA pass to verify nothing was damaged.
- If save returned 400 (or other error): tell the user, fall back to mode 2 output.

**Always re-fetch after a save attempt.** Never trust that the save did what you intended without verifying.
