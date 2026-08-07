---
name: signal-launch-retro
description: Static orchestration skill that turns the painful 2026-07-27 signal-campaign
  launch day into a fix list and a smooth repeatable process. Audits the day's ~20 logged
  errors (pre-baked catalog inside, grouped by root cause), shortlists max 7 changes ranked
  by friction removed, explains the shortlist in plain English (explain-5 rules), writes the
  ONE smooth idea-to-live process spec with all gates up front, and proves it with a mock
  campaign launch scored by a simulated panel of 5 non-technical founders and sales leaders
  at 9/10+ for simplicity and ease of launch. Zero provider credits, nothing sends. Use when
  the user says "run the launch retro", "fix the launch process", "make launching campaigns
  smooth", or "/signal-launch-retro".
---

# signal-launch-retro

Launching the growth-hiring campaign took a full day of back-and-forth because of bugs,
collisions, stale docs and late gates. This loop turns that day into: an audit, a ranked
fix list, a plain-English explanation, ONE smooth process, and a panel-verified mock launch.

## ⚙️ LOOP TRAINING MODE  →  **ON** (default)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at every step and wait for my approval before continuing.
- Skip any step that already passes its done-rule (say so and move on).
- Only re-run steps that fail.
- Cap retries so it can't loop forever (see retry cap below).

**When OFF**
- Run autonomously, no pauses, but keep the done-rule checks and the retry cap.
- Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule;
the panel (Step 5) gets **max 4 full rounds**. On cap-hit, record FAILED with the reason,
continue where possible, surface every FAILED item in the final report. Never silently exceed.

## 🔒 Hard gates (both modes)

- **Zero provider credits.** The audit and the mock launch run on fixtures and the day's
  saved outputs. No TheirStack/Prospeo/AI Ark/Smartlead-write calls.
- **Nothing sends, nothing goes live, no live campaign or artifact is edited.**
- **Structural changes are PROPOSALS** until Bjion approves them in the hand-off. The only
  direct fixes this loop may make itself are factual doc corrections (e.g. the stale
  Prospeo enrichment shape in `lilly-tam/SKILL.md`) — each one listed in the report.

## THE GOAL

Launching signal or targeted-list campaigns happens much easier, with less back and forth
and fewer mistakes. **Verification bar: a simulated panel of 5 non-technical founders and
sales leaders scores the new proposed process 9/10+ for (a) simplicity and (b) ease of
launching a campaign, proven on a mock campaign walkthrough.** (Bjion's real panel follows
his pick; the simulated panel is the pre-filter.)

---

## PRE-BAKED INPUT — the 2026-07-27 error catalog

The audit does NOT need the chat transcript. This is the day's error log, grouped by root
cause. Corroborating records: `lilly-strategy/sessions/navreo-2026-07-27.md` (+ run.json),
`~/.claude/state/list_uploads.jsonl`, `~/.claude/state/campaign_registrations.jsonl`,
memory `campaign-register-automatic`.

**A. Provider contracts drifted or were never validated (cost: credits + hours)**
- A1 `engine.py probe` posts FLAT filters to AI Ark REST; they are silently ignored WHILE
  BILLING → two junk probes returned the whole 414M database as a "count". Still unfixed.
- A2 AI Ark `metricGrowth*` filters 400 on every combination (docs said "never validated").
- A3 TheirStack `company_industry_or` is not a valid param (silent null result).
- A4 Prospeo contract drift: `/email-finder` + `/linkedin-email-finder` now DEPRECATED,
  `bulk-enrich-person` rejects LinkedIn URLs; working path is `/enrich-person` with
  `data.linkedin_url`. `lilly-tam/SKILL.md` still documents the dead shape.
- A5 The Smartlead key in `~/.navreo-keys.env` is invalid; the real key only exists inside
  the mcp-remote process args, and the first extraction regex truncated it.
- A6 Smartlead sequences API rejected `delayInDays` (wants `delay_in_days`) and shell
  quoting broke the api_key param → two failed saves before the draft landed.

**B. Two sessions, one workspace (cost: confusion, overwritten work, duplicate builds)**
- B1 Both sessions republished the standing strategy artifact: three publish conflicts,
  foreign ideas merged onto the board, "what the chat says doesn't match the artifact".
- B2 A whole-list write from the other session clobbered this session's campaign_drafts
  row minutes after it was verified written.
- B3 Both sessions built near-duplicate campaigns off the same signal (4 drafts, same
  trigger family) — only a manual check proved overlap was ~1% and not a double-contact.
- B4 Three campaigns were created unregistered in the tool by the other session.

**C. Prototype looked real (cost: a full walkthrough lost)**
- C1 The wizard let Bjion complete the entire launch flow, approve, and believe a campaign
  existed. Nothing was created and his copy tweaks were saved nowhere retrievable.
- C2 Signal cards showed no concrete targeting until a targeting block was built mid-day.

**D. Rules lived in skills, so ad-hoc work escaped them (cost: guards firing late, dupes)**
- D1 List push to the tool wasn't part of the act of pulling → guard fired at turn end;
  also false-positived on a derivative CSV (lean copy of an already-uploaded fat list).
- D2 Campaign registration wasn't part of the act of creating → built mid-session; its v1
  had two bugs (key regex, macOS urllib SSL); manual + auto registration then produced
  TWO identically-named sources on one campaign ("50 found" vs "0 found" confusion).

**E. Gates discovered late, targeting arrived in four revisions (cost: rework loops)**
- E1 No sender mailboxes attached and no 2-minute video ready — discovered AFTER build.
- E2 Targeting standard arrived piecemeal across four corrections (34-role set, Account
  Executive out, 15 geos, verified niche ids, CEO/sales-leader ladder, company AND person
  location) — each one a re-probe and a republish. Intake never asked for standing defaults.
- E3 Oversized companies leaked through the size filter (a national newspaper in a 5-200
  list) — caught at report time, shipped by choice.

**F. Claude's own reporting errors (cost: trust)**
- F1 "These campaigns overlap heavily" was an unchecked guess; measured overlap was 1%.
- F2 Wrong ideas surface used at the start; a link mix-up mid-message; the finished draft
  "missing" from the campaign view because the default filter hides Drafts.

---

## THE STEPS

### Step 1 — Audit
Write `retro/ERRORS.md`: every catalog item above, one row each — what happened, root cause
class (A–F), cost (credits / minutes / trust), and the single change that would have
prevented it. Sweep the corroborating records for anything the catalog missed.
- **Done-rule:** every item has cause + cost + prevented-by; any newly found error is added,
  none removed; file exists.

### Step 2 — Shortlist the changes
Write `retro/CHANGES.md`: **max 7 changes**, ranked by friction removed per unit of build
effort. Each change names: the errors it kills (by id), the owner surface (skill / hook /
engine / tool page / working agreement), and whether it is build-now, propose, or done-today
(the two guards and `campaign_register.py` already shipped). Candidate seeds the auditor
must weigh, then keep or kill: single-writer rule for the tool's tables (B), one standing
targeting-defaults block in `clients/navreo.json` (E2), mailbox+asset preflight before any
spend (E1), provider contract smoke-probes + doc sync (A), "PROTOTYPE — nothing sends"
banner + edits-saved-somewhere for the wizard (C), draft-visibility fix on the campaigns
page (F2), probe-before-claim rule for any overlap/size assertion in chat (F1).
- **Done-rule:** ≤7 changes; every ERRORS.md row maps to ≥1 change or an explicit "accept";
  each change has owner + effort + errors-killed.

### Step 3 — Explain it in five
Deliver the shortlist in chat per explain-5 rules: under 150 words, zero jargon, decisions
first, and **exactly five bullets** — one per change that matters most.
- **Done-rule:** ≤150 words, 5 bullets, passes the jargon ban (no TAM/probe/enrich/webhook).

### Step 4 — The one smooth process
Write `retro/PROCESS.md`: the single path from "let's run this signal" to "campaign live",
with every gate moved to the FRONT: standing targeting defaults confirmed once, mailbox +
video/asset preflight, then pull → verify → copy → QA gate → auto-register + auto-list-push
(already automatic) → paused draft → human go. State what the user sees and decides at each
moment. **The user makes at most 3 decisions** (targeting confirm, copy approve, final go).
Name which automation exists today vs. is a build item from Step 2.
- **Done-rule:** ≤3 user decisions; every step names its owner (automation or person);
  every build item traces to a CHANGES.md entry; a dry mock walkthrough completes on paper.

### Step 5 — Mock-launch panel
Five simulated NON-TECHNICAL founders/sales leaders (fresh cast, impatient, allergic to
jargon) each "launch" a mock campaign following PROCESS.md exactly — fixtures only, zero
credits, nothing sends. Score /10 on simplicity and ease-of-launch, with a worst-moment
quote each. Under 9/10 average on either axis → fix PROCESS.md at the worst moments and
re-run (cap 4 rounds; over-simplification that hides a needed decision is also a defect).
- **Done-rule:** 5 scorecards × 2 axes, average ≥9 on both, no scorer below 8, quotes kept.

### Step 6 — Hand-off
One report to Bjion: per-step DONE/SKIPPED/FAILED, the 5-bullet explanation, links to the
three files, panel numbers, the doc fixes made directly, and the build-items list awaiting
his approval. Nothing beyond doc fixes is built without his yes.
- **Done-rule:** report delivered; session file appended; every FAILED item named honestly.

## OVERALL DONE-RULE

ERRORS.md covers the full catalog with causes; CHANGES.md has ≤7 owner-assigned changes
covering every error; the explain-5 landed in chat; PROCESS.md holds a ≤3-decision launch
path; the panel averages ≥9/10 on both axes with no scorer under 8 (or a capped FAILED-BAR
is reported honestly); zero credits spent; nothing sent, launched, or edited live. All of
it, or it isn't done.
