---
name: signal-push-uxlab
description: Build and prove the "push signal leads into HeyReach + Smartlead" UX in the Navreo signals tool (app/campaigns.html + app/server.py). One static orchestration loop — build the push UX, run 10 simulated user-testers of mixed ability, verify every tester lands ≥1 real lead in BOTH the live Smartlead campaign 3591996 AND the HeyReach list "Arna test", reset the leads between runs, score simplicity, iterate. Done when avg simplicity ≥8/10 AND all 10 testers succeed in both tools. Use when the user says "run the push UX lab", "bridge the push gap", "prove the signals push", or "/signal-push-uxlab".
---

# signal-push-uxlab

Bridge the final gap in the signals tool: a dead-simple UX that pushes leads found in a Signal Campaign into a HeyReach list and a Smartlead campaign. Prove it with 10 user-testers. Static loop, fixed done-rule.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by user 2026-07-04)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for the user's explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** max **4** full tester-rounds. Any single step retries **max 3** times. On cap-hit, stop and report the best result + what's still failing. Never silently exceed.

---

## THE GOAL

A user who found leads in a Signal Campaign can, in a few obvious clicks, send them into outreach — and they actually arrive.

- **Simplicity target:** average **≥ 8/10** across all 10 testers.
- **Landing target:** **every** tester pushes **≥ 1 real lead** into **both**:
  - Smartlead campaign **3591996** (https://app.smartlead.ai/app/email-campaign/3591996/analytics)
  - HeyReach list **"Arna test"**
- **Routing rule (user, 2026-07-05): EXCLUSIVE.** A lead with a verified email goes ONLY to Smartlead; a lead without goes ONLY to HeyReach — never both. So the landing target reads per tester: ≥1 of their leads lands in Smartlead AND ≥1 lands in HeyReach (different leads). Tester rounds capped at **3 testers** (user, 2026-07-05).
- **Cost guard:** when seeding the test signal campaign, always pick the signal/idea with the **fewest prospects** (a handful is enough — this is a UX test, not a volume test).

---

## THE GAP (why this exists)

`app/server.py` already stores a `destination` and stamps prospects `pushed_to` **in the local JSON only** (see `update_source`, ~line 883) — **no HTTP call to Smartlead or HeyReach is ever made.** The UI shows "✓ sent" but nothing lands. Step 1 makes the push real; Steps 2-6 prove it's simple.

**Integration facts (don't rediscover):**
- Keys live in `~/.navreo-keys.env` (`HEYREACH_API_KEY` present; Smartlead push via the `mcp__smartlead__*` tools or the Smartlead REST key). Server loads keys at `server.py:39`.
- HeyReach: **REST, not MCP**, for the backend. Use **AddLeadsToListV2** (never AddLeadToCampaign — it silent-fails). `lastName` silent-drops if malformed — send `firstName`+`lastName`+`linkedin_url` clean. Resolve the id of list **"Arna test"** at runtime.
- Smartlead: push to campaign **3591996** with `first_name`, `last_name`, `email`, `company_name`. Real backend cadence is **daily**, so the endpoint must be idempotent (don't double-add the same email/linkedin).
- The daily backend push is server-side; the UX only lets the user **arm** a destination + qualify leads.

---

## THE STEPS

### Step 1 — Build the push UX + wire it for real
Done-rule: a qualified lead in a signal campaign, when armed to a destination, actually appears in Smartlead 3591996 and in HeyReach "Arna test" via a real API call (verified once, by you, not a tester).
- Backend: replace the local-only `pushed_to` stamp with a real push — Smartlead add-lead + HeyReach AddLeadsToListV2. Idempotent on email / linkedin_url.
- Frontend (`app/campaigns.html`): make destination-arming + "push these" a single obvious action. No jargon. A non-technical user should not have to think.
- Verify yourself once end-to-end, then **reset** (see Step 5) so the testers start clean.

### Step 2 — Seed the test signal campaign (cheapest signal)
Done-rule: one signal campaign at `#cdraft-1` exists with a **small** set of real prospects (lowest-prospect idea available), destinations wired to Smartlead 3591996 + HeyReach "Arna test".
- Prefer a hiring signal with a thin/niche role, or whichever idea probes to the fewest prospects. Keep credits minimal.

### Step 3 — Run 10 user-testers (mixed technical ability)
Done-rule: 10 tester transcripts captured, each with a simplicity score /10 and a pass/fail on "did they push ≥1 lead".
- Personas span non-technical → power-user (e.g. cold-email VA, founder, ops manager, sceptical CMO, junior SDR, etc.).
- Each tester attempts the push **cold**, using only the UI. Record every point of confusion, misclick, hesitation, and their end simplicity score.
- Simulate faithfully — a confused persona must actually get stuck, not be rescued.

### Step 4 — Verify landings in BOTH tools (two separate checks)
Done-rule: for every tester, the lead they pushed is present in Smartlead 3591996 **and** in HeyReach "Arna test", confirmed by reading the live tools (not the app's own "✓ sent" label).
- Smartlead check + HeyReach check are **independent** — a pass needs both.

### Step 5 — Reset between every tester (and between rounds)
Done-rule: after each tester's verification, their lead is removed from Smartlead 3591996 and HeyReach "Arna test", so the next tester starts from empty and a fresh landing proves the flow really worked.
- Smartlead: delete the campaign lead. HeyReach: delete the lead from the list.
- Never skip — a stale lead makes the next result a false pass.

### Step 6 — Score, log, decide
Done-rule: this round's average simplicity + per-tester pass/fail written to `SIGNAL-PUSH-UXLAB-<date>.md` (what worked, what didn't, verbatim friction, the fix list).
- **If avg ≥ 8/10 AND all 10 landed in both tools → DONE.** Report and stop.
- **Else** → apply the top friction fixes to the UX, then loop back to Step 3 (Step 1/2 already pass → skip them). Respect the 4-round cap.

---

## THE DONE-RULE (single source of truth)

> Average simplicity across the 10 testers is **≥ 8/10**, **and** all 10 testers landed **≥ 1 real lead in Smartlead 3591996 AND in HeyReach "Arna test"**, verified live and reset afterward.

Anything less than both halves = not done. On the 4-round cap, stop and report the gap honestly — do not declare done.

---

## GUARDRAILS
- Cost: cheapest signal, minimal prospects, reset every run so credits/inboxes don't pile up.
- Honesty: verify landings in the **real** tools; the app's "✓ sent" is not proof.
- Idempotency: the daily backend push must not double-add — dedupe on email / linkedin_url.
- Scope: this skill only proves the push UX. It does not send outreach or activate sequences.
