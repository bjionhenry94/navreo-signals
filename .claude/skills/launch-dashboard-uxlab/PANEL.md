# launch-dashboard-uxlab — panel record (2026-07-27)

Loop Training Mode: **OFF** (Bjion flipped it before the run). Ran autonomously, done-rules and retry cap enforced.

**Outcome: CAP-HIT WITHOUT 9.0. Bar NOT met. Winner picked on merit, not shipped.**

## Result

| Prototype | Direction | Final score (actionable / digest / beauty) |
|---|---|---|
| **p5 Mission control** | tiles: hero state + stage rail | **8.5 / 8.6 / 8.4 = 8.50** ← winner |
| p1 Pipeline stepper | rows: 5-segment track | 6.6 / 6.0 / 6.8 = 6.47 |
| p2 Progress ring | radial per campaign | 5.8 / 5.4 / 7.0 = 6.07 |
| p4 Launch lanes | kanban columns | 5.6 / 6.2 / 5.6 = 5.80 |
| p3 Live stream | present-tense feed | 5.0 / 5.8 / 5.0 = 5.27 |

p5 led every round and won unanimously across all 20 personas. Gap to second: ~2.0.

## p5 across the four rounds

| Round | Actionable | Digest | Beauty | Total |
|---|---|---|---|---|
| 1 (build) | 7.8 | 8.4 | 8.0 | 8.07 |
| 2 (count + receipt + grid) | 8.4 | 8.8 | 8.4 | **8.53** |
| 3 (next/when + ready strip + milestone) | 8.0 | 8.8 | 8.6 | 8.47 |
| 4 (honest switch + labelled receipt + measure) | 8.5 | 8.6 | 8.4 | 8.50 |

Every round traded: R2 was the biggest jump; R3 regressed actionable (dishonest switch, unlabelled receipt, lost measure); R4 recovered actionable (+0.5) but paid ~0.2 each on digest and beauty by adding a fifth text row and an `Open ›` that wraps long names at 375px.

## Defects found and fixed during the run (real, not cosmetic)

- **`p3` had no doctype** → rendered in quirks mode. Added doctype/html/head/body.
- **Dishonest control (R3→R4):** the board-level Switch-on read plain "Switched on" on a client-facing page — a client could believe 8,424 emails had sent. Now "Switched on · preview", honest aria-label, and `live()`'s nonsense "nothing sent · 0 sent" → "nothing sent yet". Footer: "nothing sends from this page".
- **"Icebreaker" broke layout** in three prototypes (mid-word break at 375px, ellipsis, hard clip) → renamed **"First line"** in the fixture: fixes all three and drops agency jargon.
- **Two disagreeing progress numbers** was the panel-wide failure mode (p2's ring drawn at 29% with "45%" in its centre; p4's lane position vs card bar; p1's 45% next to 29%). p5 is the only direction whose picture and numbers agree.
- **Vendor name** "Smartlead" removed from client-facing text → "ready to send".

## Blockers to 9.0 (what the last panel says is left)

1. **Highest impact:** replace `"45% of this step"` with a countable number where one exists (`592 of 925 found` on Targeting — already in the fixture) and show nothing where there is no honest denominator ("45% of writing an email" is invented). Moves all three axes: real number, three tiles lose a row, tiles shrink.
2. Drop `Open ›` from tiles, put the chevron beside the name (matches the strip); recovers ~45px and un-wraps "Managed IT providers" at 375px.
3. No "waiting on you" state — a delegator must read all five tiles to learn there is nothing to do.
4. The only interactive control (the ready strip's switch) is the last element, ~3 screens down at 375px.
5. Light mode hard-coded on load; no `prefers-color-scheme` respect.
6. Structural: tile is `role="button"` containing five real `<button>` children — invalid nesting, 24 tab stops. Fix before this is real.

## Not merged

Per the skill, the winner merges into the live board (`wizard-template.html` → wizard-lab `build_live.py`) ONLY on Bjion's explicit pick. Nothing was merged.

## Files

`~/navreo-signals/app/prototypes/launch-dashboard-{index,p1..p5}.html`, `launch-dashboard-base.css`, `launch-dashboard-fixture.js`.
