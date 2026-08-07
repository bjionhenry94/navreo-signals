---
name: signal-create-uxlab
description: Prove that CREATING a new signal campaign in the Navreo signals tool (app/campaigns.html + app/server.py) is simple enough for a non-technical user. One static orchestration loop — run a cold non-technical tester through creating one hiring, one LinkedIn-monitoring, and one intent campaign per round (briefs pre-baked), score each /10 for ease of use, verify the backend records were created as designed, clean up, iterate the creation UX. Done when the round averages ≥8/10 AND every task's campaign is correctly configured in the backend. Spend-minimised: no pulls, no Trigify provisioning, no enrichment. Use when the user says "run the creation UX lab", "test campaign creation", "/signal-create-uxlab".
---

# signal-create-uxlab

Make creating a new signal campaign dead simple. Test with cold non-technical users, verify the backend did what the UI claimed, iterate. Static loop, fixed done-rule, minimal spend.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by user 2026-07-05)

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

**Retry cap (both modes):** max **4** full rounds. Any single step retries **max 3** times. On cap-hit, stop and report the best result + what's still failing. Never declare done.

---

## THE GOAL

A non-technical user can take a plain-English brief ("companies hiring X", "people engaging with Y", "companies that just raised") and turn it into a correctly-configured signal campaign without help.

- **Simplicity target:** average **≥ 8/10** across the round's 3 creation tasks.
- **Designed-correctly target:** every task's campaign + source exists in the backend with the right mechanism and params (checked in files/API, never trusted from the UI).
- **Spend guard:** see below — creation only, no pulls, no provisioning.

## THE BRIEFS (rotate; one per category per round, never reuse across rounds)

Hiring: (H1) Amplifyy·retention-role hires (H2) Arnic·2+ SDR openings (H3) Navreo·AI-consultancy delivery hires (H4) WordBank·international-marketing hires.
Monitoring: (M1) Navreo·outbound-tool-founder engagers (M2) Amplifyy·Amazon-educator engagers (M3) Arnic·sales-ramp-content engagers (M4) Asteri·exit-content engagers.
Intent: (I1) Arnic·funded B2B software (I2) Navreo·new sales leader at agencies (I3) Navreo·dev agencies losing traffic (I4) Amplifyy·funded consumer brands.
Round 1 uses H1+M1+I1, round 2 H2+M2+I2, etc. Give the tester ONLY the plain-English brief, as a boss would text it.

## 💰 SPEND GUARD (hard rules, checked every round)

- Testers must NEVER click "Find people now", "Start monitoring", or any re-pull. The task ends at "campaign exists and is configured".
- NO Trigify provisioning (engagement configs saved unprovisioned), NO Prospeo/TheirStack pulls, NO email enrichment, NO pushes to Smartlead/HeyReach.
- Known leak 1: the Sources tab auto-pulls a bare single source on open — watch server logs for pull calls; if one fires, count it (bounded, ~1 credit) and note it in the report.
- Known leak 2: the "New campaign" AI-ideation path runs live strategy-map probes (credits). Testers should be steered by the BRIEF's wording, not told which buttons to press — but if the flow forces probes, accept max 1 ideation run per round and log it.
- Budget per round: ≤ 5 provider credits total. Blow the budget → stop the round, fix the leak first.

## HARNESS RULES (lessons already paid for — do not rediscover)

- Testers are subagents driving the preview browser. They click via `preview_eval` `element.click()` patterns with scrollIntoView — **never `preview_click`** (dispatches nothing; caused 4 false-failure rounds in the push lab).
- Preview server must be same-origin with the page (own `launch.json` entry, e.g. port 7902); after editing app files, cache-bust (`?v=`) once.
- Reload the browser + clear `sessionStorage` between testers. One tester at a time.
- A parallel session may be editing the same files: re-read before editing, never assume your last read is current, and treat "File has not been read yet" errors as external-change signals.

## THE STEPS

### Step 1 — Baseline round (3 creation tasks, cold tester)
Done-rule: one non-technical persona (fresh each round; e.g. office manager, bookkeeper, EA) has attempted all 3 tasks via UI only, each with an ease score /10, a task transcript of friction points, and a give-up flag.
- One brief per category from the rotation. The persona gets the brief verbatim plus the tool URL, nothing else.
- Simulate faithfully: a confused persona gets stuck, is not rescued, and may give up (valid data).

### Step 2 — Backend verification (never trust the UI)
Done-rule: for each task, `data/campaign_drafts.json` + `data/draft_sources.json` (or the APIs) show: a campaign draft exists; it has ≥1 source with the CORRECT mechanism (hiring / engagement / funding·exec_change·traffic_decline); the params match the brief (roles/keywords/geo for hiring; profile URLs+topics saved unprovisioned for engagement; the right intent filter for intent); and the spend guard held (no pulls beyond leak 1, no provisioning).
- A task "completed" by the tester but wrong in the backend = FAIL for that task, and is the most valuable finding of all.

### Step 3 — Cleanup (every round, no exceptions)
Done-rule: every campaign created this round is removed (Remove cascades sources; engagement deprovision is automatic on remove), and the campaign list matches its pre-round state. Real client campaigns untouched.

### Step 4 — Score, log, decide
Done-rule: round logged to `SIGNAL-CREATE-UXLAB-<date>.md` (scores, verbatim friction, backend pass/fail per task, spend events, fix list).
- **If avg ≥ 8/10 AND all 3 tasks backend-verified AND spend guard held → DONE.** Report and stop.
- **Else** → apply the top friction fixes to the creation UX (wizard copy, step order, defaults, jargon) — and REMOVE redundant or unused wizard features/elements outright (user rule 2026-07-05: fewer elements beats better labels; anything a tester never needed or was confused by is a removal candidate). Then loop to Step 1 with the next briefs in rotation. Respect the 4-round cap.

## THE DONE-RULE (single source of truth)

> One round where the 3 creation tasks average **≥ 8/10** for ease of use, **every** task's campaign is verified correctly configured in the backend, and the spend guard held — then cleaned up.

Anything less = not done. On cap-hit, report the gap honestly.

## GUARDRAILS
- Cost first: this lab proves CREATION, not data. If a check can be done from JSON files instead of a provider API, do that.
- Honesty: backend state beats UI claims; a pretty flow that writes wrong params is a failing flow.
- Scope: creation UX only. Push UX is already proven (signal-push-uxlab, 8.33/10). Don't re-test it.
- Cleanup is part of every round, not an afterthought — the tool is shared with live client campaigns.
