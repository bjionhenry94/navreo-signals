---
name: signals-launch-hardening
description: Static orchestration skill that makes the Navreo signals campaigns tab extremely easy to use and bug-free for HIRING (TheirStack) and CONTENT/ENGAGEMENT (Trigify) signals only — so a signal campaign can be launched (create → preview → push) with confidence. Five fixed, parallelizable steps, each with a checkable done-rule, plus a Loop Training Mode toggle (ON by default). Scope is deliberately confined to hiring + engagement signals; funding/news/other types are out of scope. Use when the user says "harden the signals tab", "make signal campaigns easy to launch", "run the signals launch hardening", or "/signals-launch-hardening".
---

# signals-launch-hardening

Make launching a **hiring** or **content/engagement** signal campaign in the signals tab effortless and stable. Static loop — the five steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them. **In scope: hiring (TheirStack) + engagement (Trigify) only.** Funding, news, and every other signal type are out of scope for this skill — do not touch them.

**Files:** `app/campaigns.html` (the tab UI + all wizard/push JS) · `app/server.py` (HTTP server, `/api/*`, pull/push/preview logic) · state in Supabase (`signal_sources`, `signal_leads`, `engagement_events`, `signals`, `companies`) with local `app/data/*.json` fallback.

**Live test targets (reuse, don't invent):** Smartlead campaign `3591996`, HeyReach list `"Arna test"`. Reset leads between test runs.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that **fail** their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all five steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

A non-technical user can **create → preview → push** a hiring or an engagement signal campaign in one sitting, trust the numbers they see, and never hit a silent failure. **Done means: the E2E smoke test (Step 5) passes for BOTH a hiring and an engagement signal — mixed-ability testers each land ≥1 real lead in the live Smartlead campaign AND HeyReach list, with an average simplicity score ≥ 8/10 and zero silent failures.**

**Conventions (reuse, don't reinvent):** sources save through `save_draft()` / `sb_sync_source()`; pushes route through `push_prospect()` (email-exclusive: verified email → Smartlead only, else → HeyReach only); previews go through `/api/preview/hiring` → `preview_hiring()`. Keep those seams. The app is stdlib + `certifi` — add no new dependencies.

**The five steps are parallelizable** — each owns a distinct surface (Step 2 = create UI, Step 3 = preview, Step 4 = push, Step 1 = the bounded defect list, Step 5 = the test harness). They can run at the same time; when two touch `campaigns.html`/`server.py`, coordinate on the named functions below rather than reformatting whole files.

---

## THE STEPS

### Step 1 — Kill the known defects (stability, bounded list)
Fix exactly these, not "all error handling everywhere":
- **Silent unsent push.** `push_prospect()` (server.py ~1622) falls back to *no routing* when a HeyReach list name isn't found (~1630, ~2658) yet the row can still read as sent. A push that doesn't land in a real tool must return `ok:false`, must **not** stamp `pr.pushed`, and the UI row must show a clear, recoverable error — never a ✓.
- **Opaque pull errors.** `pullProspects()` (campaigns.html ~1137) shows generic "Pull failed - server running?". Surface the actual server message/cause.
- **Silent filter mutation.** The precision self-heal (server.py ~2651) pops a starving `company_description_pattern_*` filter and re-probes without telling the user. Notify: "removed filter X to get results."
- **Accidental delete + RLS.** Deleting a draft/source must be confirmed and recoverable (restore path), and RLS must be ON for `campaign_drafts` and `signal_sources` (or a written, deliberate waiver). (Ref: signals beta audit.)
- **Dead code.** Remove the disabled `if (false) { … }` QA block (campaigns.html ~421).
- **Done-rule:** `grep` shows no push path that stamps `pushed`/renders sent on a failed/absent destination; deleting a draft prompts + is restorable; a forced pull error shows the real cause in the toast; a forced filter-pop emits a user-visible notice; `if (false)` block gone; RLS enabled on `campaign_drafts` + `signal_sources` (verified via Supabase) or waiver noted.

### Step 2 — One-screen guided CREATE wizard, unified hiring + engagement
Collapse `openSourceWizard()` (campaigns.html ~2151) so a user creates **either** a hiring or an engagement source from a single guided screen: pick type → sensible prefilled defaults (`prefillHiringRoles` / `prefillEngagement`) → **inline validation before you can save** → live count visible in-flow. Bring engagement to parity with hiring (same look, same "you're done" clarity). No dead-ends, no jargon (plain English per house style).
- **Done-rule:** a mixed-ability tester creates both a hiring **and** an engagement source without leaving the screen or getting stuck; required fields (titles/URLs, destination) are validated inline and block save when empty/invalid; POST `/api/sources` succeeds and the source appears; no step references a merge tag or field the flow didn't collect.

### Step 3 — Trustworthy preview / estimate for both types
Hiring already previews via `/api/preview/hiring` → `preview_hiring()` (prospects = companies × `DMS_PER_COMPANY` 1.6). Make it trustworthy and give engagement a pre-launch number too:
- Label clearly: **companies vs people**, and mark derived counts "≈ estimated".
- Add an expected-volume figure for **engagement** before launch (e.g. `leads_per_day` × cadence) so it isn't a black box.
- Regression-lock the known REST gotchas so preview never 500s: TheirStack UA block, keyword 401, identifier-slug. (Ref: preview accuracy work.)
- **Done-rule:** hiring preview returns jobs/companies/prospects with companies-vs-people labeled and "≈ estimated" on derived numbers; engagement shows an expected-volume estimate pre-launch; a regression test exercising the three gotchas passes (no 500); the estimate is within a stated tolerance of a real pull sample.

### Step 4 — Reliable, idempotent PUSH with a clear receipt
Harden `push_prospect()` / `push_to_smartlead()` (~1567) / `push_to_heyreach()` (~1588) and undo (`unpush_prospect()` ~1704):
- **Idempotent:** re-pushing the same lead must not create a second one — honour `pr.pushed` stamps and the providers' `duplicate_count` / `already_added` / `updatedLeadsCount`.
- **Suppression/dedupe** respected for both hiring- and engagement-sourced leads (don't burn a lead already contacted).
- **Receipt:** every push returns and surfaces `{ pushed, skipped_duplicate, failed }` in the UI — no silent drops.
- A failed push never stamps `pushed`; undo removes the lead from the real tool.
- **Done-rule:** pushing the same lead twice yields a duplicate/already-added result and **no** second lead in the tool; the UI shows a pushed/skipped/failed receipt; a simulated failed push leaves `pr.pushed` unset and shows an error; undo verifiably deletes from Smartlead/HeyReach.

### Step 5 — E2E smoke-test gate (the verification)
Stand up a repeatable test that proves Steps 1–4 hold. Simulated mixed-ability testers each run **create → preview → push** for BOTH a hiring and an engagement signal against the live test targets, then score simplicity.
- **Done-rule (the overall verification):** ≥ 6 testers each complete create→preview→push for **both** a hiring and an engagement source; ≥ 1 real lead lands in Smartlead campaign `3591996` **and** HeyReach list `"Arna test"` for each type; average simplicity **≥ 8/10**; leads reset between runs; **zero silent failures** observed. Any tester who can't finish, or any silent failure, = step FAILED.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, do one step at a time and stop for approval after each; skip any step whose done-rule already passes (say so). If **OFF**, run all five in order without pausing.
2. For each step: make the change, then check the done-rule — run the grep/Supabase/`curl`/preview assertions, and for Steps 4–5 hit the **live** Smartlead + HeyReach test targets, not a mock. Retry up to 3× on failure, then mark FAILED and continue.
3. Steps 4 and 5 push to live tools — in ON mode the pauses gate them; in OFF mode still confirm each done-rule passed and reset test leads afterward.

## OVERALL DONE-RULE

- Step 5 passes: both signal types, both tools, ≥8/10 simplicity, zero silent failures — the launch path is easy and stable.
- Steps 1–4 done-rules all pass (or are recorded FAILED with a reason).
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason).
