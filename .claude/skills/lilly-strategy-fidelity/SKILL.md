---
name: lilly-strategy-fidelity
description: "One-sitting orchestration loop that makes lilly-strategy copy predictable and consistent: locks the fixed email templates (no inventing), makes edits surgical (one field changes, nothing else, diff shown), rewrites targeting descriptions to PITCH the idea, fixes + live-UI-verifies the versions delete button, adds a final cohesion/grammar sweep, drops the P.S line on Look-a-like, and bans industry callouts in hiring-signal copy — then proves it all by duplicating an existing session and putting old-vs-new in front of a 5-judge panel. Trigger: '/lilly-strategy-fidelity', 'run the fidelity loop', 'fix the strategy copywriter', 'make the templates predictable', 'the copywriter keeps inventing stuff', 'the copy feels stitched together'."
---

# Lilly Strategy Fidelity — make the copywriter predictable

## ⚙️ LOOP TRAINING MODE — the toggle (flip it here)

**TRAINING_MODE: ON**

- **ON (default):** pause at EVERY step and wait for Bjion's approval before continuing.
  Before running a step, test its done-rule first — if it already passes, say so and SKIP it.
  Re-run only steps whose done-rule FAILS. Retry cap: **2 re-runs per step** — after the
  2nd failed retry, stop the loop and report what's blocking instead of looping again.
- **OFF:** run every step autonomously, no pauses. Keep the done-rule check before and
  after each step, keep skip-if-already-passing, keep the same 2-retry cap.
- A chat override for one run ("go, training off" / "training on") beats the value above.
  To change the default, edit the TRAINING_MODE line — nothing else needs touching.

## Goal

Strategy-run copy comes out of the FIXED templates every time, an edit changes only the
thing that was asked, and the board's version controls actually work — proven by a 5-judge
old-vs-new panel on a duplicated real session. No more guessing what changed.

## Ground rules (apply to every step)

- **Read-modify-write, always** (memory: strategy-board-read-modify-write): GET the live
  run, patch ONLY the delta, POST back. Never re-POST a rebuilt run over a live board.
- **Duplicates get a fresh run_id** (`<client>-<YYYYMMDD>-<4 rand>`); the original board
  is never touched by this loop.
- **Board verification happens on the DEPLOYED board in the Claude Browser** — never a
  local server (lilly-strategy hard rule). Every report to Bjion carries a link I
  confirmed loads first (memory: updates-need-verified-link).
- A step "fails" when its done-rule fails after the step ran. Count re-runs per step;
  cap 2, then halt and report.

## The steps

### 1 — Template lock (stop the inventing)
Anchors: /lilly-copywriter "REQUIRED OUTPUT STRUCTURE" (Email 1a Service Pitch, 1b One
Sentence Punch), Look-a-like fixed template (lilly-strategy Vector 6), fixed openers
(Vectors 4/5), server truth `app/navreo_voice.py`.
Action: write a hard **TEMPLATE FIDELITY** rule into lilly-strategy Phase 2c: every
version = exactly ONE named template shape; only the bracketed slots get written;
scaffolding stays verbatim; no new sections, no reordering, no invented shapes; each
version on the run carries its template name.
Done-rule: on a test idea, 4 versions each match their declared template line-for-line
outside the slots.

### 2 — Surgical edits (stop the silent changes)
Action: write the **edit-one-thing law** into lilly-strategy's chat-edit loop: an edit
touches ONLY the named field of the named version — every other byte of the run stays
byte-identical (read-modify-write enforces this). Every edit is answered with a one-line
diff receipt in chat: `changed: <where> · "<before>" → "<after>" · nothing else touched`.
Done-rule: run one edit on a duplicated run; JSON diff of before/after shows exactly one
changed field, and the diff receipt was posted.

### 3 — Targeting description pitches the idea
Action: the idea description on the Targeting page = two sentences that SELL, not
describe: `Targeting [who] at [companies showing the signal]. This works because [why
that signal means they need the offer right now].` Write the shape into the targeting-
block guidance and re-write the descriptions on the test board to match.
Done-rule: every idea on the test board shows the two-sentence pitch shape on its
Targeting page (checked by reading the live UI, not the JSON).

### 4 — Versions delete button (fix + live verify)
Action: find the versions delete control + handler in `~/navreo-signals/app/strategy.html`,
fix why the delete doesn't stick (handler / persistence / re-render), deploy, then on the
LIVE board delete a version on the duplicated run.
Done-rule: the version is gone after the click AND still gone after a full page reload —
persistence, not just DOM. (Live-UI verification is mandatory — Bjion asked for it.)

### 5 — Cohesion sweep (stop the stitching)
Action: add a mandatory **final read-through pass** to Phase 2c: after the sections are
assembled (icebreaker → pain → offer → CTA → sign-off), read each version top-to-bottom
as ONE message from one person; fix grammar joins, dangling references, and typos
("Can I sent it over?"); each sentence must follow from the one before it, not sit in
its own box.
Done-rule: sweep log exists for the test run — every version read, flaws found + fixed
listed (or "clean"), and no version ships with a grammar error.

### 6 — Look-a-like: no P.S line
Action: remove `P.S - [risk reversal]` from the Vector 6 fixed template and its worked
example; add the Look-a-like exception to the "every version carries a P.S" rule; carve
the engine validator so lookalike ideas PASS without a P.S and FLAG one that sneaks back
in (predictable = the template is exact, both ways).
Done-rule: duplicated run's lookalike idea has 4 versions, zero P.S lines, and
`engine.py validate` passes.

### 7 — Hiring/job-role copy: no industry callouts
Action: write the rule into Vector 2 + Phase 2c: hiring-signal audiences are pulled by
ROLE, not industry (~90% of pulls carry no industry filter), so copy and openers never
name a specific industry/vertical UNLESS the idea's pull_spec actually filters industry.
Role-anchored language instead: "teams hiring SDRs", never "SaaS companies hiring SDRs".
Done-rule: on the test run, no hiring-signal version or opener contains an industry noun
where its pull_spec has no industry filter.

### 8 — Preview shows different versions (diversity)
Action: in `~/navreo-signals/app/strategy.html`, the Preview tab must rotate versions
across the preview people (person i shows version i mod N, with a "Version B" tag),
never version A for all five. Deploy with step 4.
Done-rule: on the live board, tapping through the preview people shows at least two
DIFFERENT versions of email 1, each labelled.

### 9 — Copy is editable in the Preview
Action: each previewed email gets an Edit control that flips the resolved view to the
raw template (tokens visible) and saves through `POST /api/strategy/copy-edit` with the
Copy tab's exact field grammar (`seq:<step>:<version>`) — one field, nothing else.
Deploy with step 4.
Done-rule: on the live board, edit an email from the Preview tab, save, reload — the
edit persisted to that one version and the resolved preview shows it.

### 10 — Prove it: duplicate, re-run, panel of 5
Action: take a real existing session run (latest board by default), duplicate it to a NEW
run_id, re-produce its copy + targeting under rules 1–9, POST the duplicate board. Then
spawn **5 independent judge subagents**, blind to each other, each scoring:
(a) **changes followed** — the fixes above, each PASS/FAIL on the new board;
(b) **quality** — old vs new copy + strategic ideas, side by side: is the new one better?
Fund the judges on a paid model (subagents inherit the session model; a metered/free
tier will die mid-run — learned 2026-08-05). Done-rule (the loop's overall done):
**≥4/5 judges confirm all changes followed AND ≥4/5 judge new ≥ old on quality.** On a
fail: fix the flagged step (counts against that step's retry cap), re-panel ONCE.

## Done

All 10 done-rules green. Close with: what changed where (file:line per fix), the
duplicated board's keyed link (opened + confirmed in the Claude Browser first), and the
panel scores. In ON mode every pause message is: step name → done-rule result → what
happens next, and nothing runs until Bjion says go.
