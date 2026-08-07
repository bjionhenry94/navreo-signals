# wizard-launch-lab — fix spec (Step 1) · 2026-07-27

Source of problems: `/Users/bjionhenry/Downloads/Lilly-strategy.pdf` (3 pages; p1 = problems over
a board screenshot, p2 = current emails page showing the unsendable paragraph, p3 = the tool's
"Who should they be hiring?" chip modal = the wanted targeting pattern).

Base file: fresh copy of `~/.claude/skills/lilly-strategy/wizard-template.html` per prototype,
hydrated by `engine.py hydrate` with `lab-run.json` (this session's 4 ideas, NO carry), then
appended override blocks. The template itself is never edited. Zero provider calls anywhere.

## The five fixes, as tests

| # | Requirement | Test (run in the browser on each prototype) |
|---|---|---|
| F1 | Menu shows ONLY this session's ideas; running campaigns live on a separate "Already running" shelf | Fresh load: `#idea-list` fresh cards = exactly 4; shelf section exists, contains the cleaning campaign with live status; shelf card is not part of the fresh menu styling and does not open the build flow |
| F2 | Exact targeting visible the moment an idea opens | Open each idea: role/tool chips inside the first workspace screen, fully above the fold at 1280×720, zero scroll, zero toggles |
| F3 | Every line inside a mail frame is sendable | JS lint: collect every `.mail-body` innerText across versions + follow-up; zero case-insensitive hits on the banned list below; and `peerProofLine` never appears in any body |
| F4 | Back on every screen; state survives | Every workspace phase ≥ preview shows a visible Back control; walk preview→targeting→emails→opener→sign-off, Back to board, reopen: same phase, same edits, builds never re-run |
| F5 | Targeting edits do something | Remove a chip: headline re-checks (brief working state) then lands on a lower number, rail number matches, "estimate · double-checked free before launch" caption appears; re-add: number returns to the probe-confirmed figure |

## F3 banned-phrase list (case-insensitive, mail bodies only) — 12 entries

signal · trigger · this list · mechanism · campaign · audience · probe · our record ·
winners table · tier · self-refreshing · decision makers

Root cause in the base template: `variantsFor` splices `idea.peerProofLine` (board-facing
evidence) into Versions A and B. Fix: the lab `variantsFor` never reads `peerProofLine`; proof is
the standing sendable line ("We've booked calls for 50+ firms doing exactly this, and it's driven
$15M+ in pipeline along the way."). `pain`/`moment` fields in the fixture are written to the
reader, never about the reader-as-audience.

## F5 chip editor (pattern copied from PDF p3)

Two groups: **"Roles they're hiring for (the trigger)"** (stack idea: "Tools they run";
new-leader idea: "Who counts as new") and **"Who we email at these companies"**.
Per group: removable chips (×), an `add a role…` input with +, and **Generate more** (pulls 2-3
pre-written suggestions from the fixture pool, each with its own count; never invents live).
Rules: a group's last chip cannot be removed; added custom chips get a deterministic estimated
count and an "estimate" mark; trigger-group edits re-count the headline (sum of active chip
counts, 500ms working state, count-up animation); who-we-email edits update the who-line only.
Recount caption, always: "estimate · double-checked free before launch".

## Word budgets (outside mail frames) + language

Card at rest ≤12 words · any workspace screen ≤40 words at rest · any label ≤5 words.
16-year-old language; jargon ban stands (say "people we can reach", "opener", "double-checked";
never TAM/DM/enrich/ICP). No em-dashes in user-visible copy. Never hide the decision cue
(minimalist-lab lesson): the next action is always visible without opening anything.

## Navigation map (F4)

Back from: preview→board (deselect) · targeting→preview · building→board (build continues in
background, rail shows it) · emails→targeting · opener→emails · sign-off→opener · launch-ready→
sign-off. Revisits never re-run completed builds: `runBuild` skips stages already done and jumps
straight to the phase's gate.

## The three treatments (all share every fix above)

- **L1 Chips do the work** — the preview IS the targeting gate: headline number left, chip
  editor right, facts collapsed to one line each; one orange button ("Looks right, write my
  emails") approves targeting and starts the build.
- **L2 One decision per screen** — a fixed step header (Who · Words · Opener · Go as dots),
  one decision rendered per screen, big Next, Back always in the same spot; rail unchanged.
- **L3 Launch runway** — every rail card carries a 4-stop runway (who · words · opener · go)
  that fills as the campaign progresses; tapping a filled/current stop jumps there; the board
  reads as "how far is each campaign from launch-ready".

## Fixture

`launch-fixture.js` = `LAB` data (per-idea chip counts summing exactly to the probe-confirmed
net, generate-more pools, who-we-email chips, shelf entry for the live cleaning campaign
Smartlead #3651763) + shared override code (BASE capture, sendable `variantsFor`, chip editor,
shelf renderer, Back header, runBuild revisit guard). Treatment deltas live in `build.py`.
All numbers replay `lilly-strategy/sessions/navreo-2026-07-27-run.json` - already paid for.
