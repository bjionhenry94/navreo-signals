---
name: lilly-strategy-wizard-lab
description: Static orchestration skill that turns the lilly-strategy menu artifact into an interactive launch experience — builds 5 clickable artifact prototypes, each walking a non-technical user from the idea menu to a launch-ready campaign entirely INSIDE the artifact (pick idea → confirm targeting → approve offer → watch the AI's build steps happen in plain English → QA → launch-ready), like a simple setup wizard. Uses ONLY mock/simulated data and processes — zero provider credits burned; this lab is about user experience, not real builds. Each prototype must pass a simulated panel of 5 non-technical sales leaders/founders at 9/10 for simplicity before it reaches Bjion. Use when the user says "run the strategy wizard lab", "build the interactive launch prototypes", "make the menu artifact interactive", or "/lilly-strategy-wizard-lab".
---

# lilly-strategy-wizard-lab

Make launching a campaign from the menu artifact feel like a simple setup wizard. Build **5 prototypes**, each a self-contained interactive artifact taking the user start → launch-ready with every AI step visible but never complicated. Static loop — fixed steps, checkable done-rules, Loop Training Mode controls pauses.

**Hard rule: NO real credits.** Every number, lead, probe, QA check and build stage is mocked or replayed from data already paid for (today's session files). If a step would call a paid provider, it's out of scope — simulate it.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, record FAILED with the reason, keep going where possible, surface it in the final report. Never silently exceed.

---

## THE GOAL

A non-technical sales leader opens one artifact and: sees a top-level view of every campaign idea → picks one → is walked step-by-step to launch-ready without leaving the page. They watch each thing the AI does (sizing, dedup, copy, QA) narrated in plain English, approve at most 3 human moments (targeting · offer · final sign-off — the idea-to-launch gates), and end at "launch-ready" feeling it was simple. **Verification bar: 5 non-technical sales leaders/founders launch a campaign through the artifact and score 9/10 for simplicity.**

---

## THE JOURNEY (identical content in all 5 prototypes; only the interaction model differs)

1. **Menu** — idea cards with net decision makers + offer (real numbers from `lilly-strategy/sessions/navreo-2026-07-16-*.md`).
2. **Gate 1 · Targeting** — confirm who it's for (pre-filled, one tap to accept, editable).
3. **Gate 2 · Offer** — see the example email, approve or tweak the offer line.
4. **Build (simulated, visible)** — stages animate in sequence with plain-English narration and real-shaped mock results: "Sizing the audience… 1,596 found", "Removing people we contacted recently… 709 left", "Checking emails… 265 valid", "Writing your emails… 3 variants", "Quality check… passed". Each stage shows WHAT the AI is doing in one sentence, never how.
5. **Gate 3 · Sign-off** — launch-ready pack (lead count, email preview, QA badge) + one big approve.
6. **Launch-ready state** — clear "done" moment; nothing actually sends.

Rules: Navreo Design System throughout (cream/ink/one-orange, Acid Grotesk data-URI, no emoji); ≤3 decisions total; every screen answers "where am I, what's happening, what do I do next"; jargon-free (no "TAM", "enrich", "DM" — say "people we can reach", "finding emails").

---

## THE FIVE PROTOTYPES (one artifact each, distinct interaction models)

| # | Model | The feel |
|---|---|---|
| P1 | **Stepper wizard** | One question per screen, dots for progress, big Next. Classic setup-wizard. |
| P2 | **Guided chat** | The AI narrates in a message stream; user answers with tap-buttons. Feels like texting an operator. |
| P3 | **Flip-card board** | The live menu board; picking a card flips it into a build timeline that fills stage-by-stage in place. Menu and progress share one screen. |
| P4 | **Flight plan** | One page, left-rail stages, centre canvas updates per stage; approvals are the only orange buttons. Boarding-pass energy. |
| P5 | **Approval deck** | Each stage is a full-screen card you approve/swipe through; a spine at top shows the stack filling. |

---

## THE STEPS

### Step 1 — Shared spec + mock dataset
- Write `wizard-lab/spec.md` (the journey above, copy for every stage narration, the 3 gates) and `wizard-lab/mockdata.js` (idea cards with today's REAL menu numbers, fake-but-realistic leads/emails for previews, staged timings). Mark every fake element "illustrative".
- Done-rule: both files exist; zero provider calls anywhere in the plan; narration lines pass the jargon ban (grep: no TAM/enrich/DM/ICP strings user-visible).

### Step 2 — Build P1-P5
- Build each prototype as ONE self-contained HTML file (inline JS/CSS, Acid Grotesk data-URI, mockdata inlined), publish each as its own artifact (5 separate URLs, stable favicons).
- Done-rule (per prototype): loads with no console errors; full journey menu → launch-ready completable by clicking alone; exactly 3 approval moments; every build stage visibly narrated; browser-verified (rendered screenshots of menu, one mid-build stage, launch-ready).

### Step 3 — Panel: 5 simulated non-technical users
- Five personas (agency founder, cleaning-company owner, VP sales, recruiter MD, e-comm founder — non-technical, impatient, jargon-averse). Each persona "walks" every prototype via the browser (click-through) and scores /10 on: knew-where-I-was, knew-what-was-happening, effort, confidence at the end. Simplicity score = mean.
- Done-rule: every prototype has 5 persona scorecards with a one-line worst-moment quote each.

### Step 4 — Fix loop
- Any prototype below **9/10 average** gets its worst-moments fixed and re-panelled (this consumes the retry cap; on cap-hit mark FAILED-BAR with scores shown honestly).
- Done-rule: ≥3 prototypes at 9/10+, none shipped below 8 without a FAILED-BAR flag.

### Step 5 — Hand-off gallery
- One summary artifact (Navreo DS): the 5 prototypes ranked with scores, links, a one-line "what this model does best", and a recommendation for which model (or hybrid) becomes the REAL integrated menu.
- Done-rule: gallery artifact live; chat summary lists the 5 URLs + scores + recommendation; session file `lilly-strategy/sessions/wizard-lab-<date>.md` written.

---

## OVERALL DONE-RULE

- 5 interactive prototype artifacts live, each completing menu → launch-ready by clicks alone, 3 approvals max, all AI steps visibly narrated, zero real credits spent.
- Panel scores recorded; ≥3 prototypes at the 9/10 bar; gallery + recommendation delivered.
- Bjion's real verification (5 actual sales leaders/founders scoring 9/10) happens after his pick — the simulated panel is the pre-filter, not the proof.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (reason).
