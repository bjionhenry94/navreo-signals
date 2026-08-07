---
name: setter-trainer-hybrid
description: Static orchestration skill that merges the three winning ideas from the brain-trainer prototype lab into ONE hybrid AI-SDR trainer — Trainer-Artifact-style chat (top left), Test-Drive drafted responses the AI-SDR would actually send, and an Onboarding-Conversation-style live readiness score — where every instruction update makes the trainer ask the relevant questions it still cannot answer. Verified by simulating the full training against 5 random businesses and iterating until clients score 9/10+ for ease of use and CSMs score 9/10+ on the bot answering 90% of routine messages. Use when the user says "build the hybrid trainer", "run the trainer hybrid lab", "merge the trainer prototypes", or "/setter-trainer-hybrid".
---

# Setter Trainer Hybrid — chat + test-drive + readiness

## Loop Training Mode — TOGGLE (flip this line to change behaviour)

**Loop Training Mode: ON** ← default. Change to `OFF` to run autonomously.

- **ON**: pause at the end of EVERY step and wait for Bjion's explicit approval before
  continuing. Skip any step whose done-rule already passes. Only re-run steps that fail.
- **OFF**: run all steps autonomously with no pauses, but still check every done-rule
  and respect the retry cap.
- **Retry cap (both modes)**: max **3 attempts per step** (initial + 2 retries), and
  Step 4's simulate-and-iterate loop is capped at **4 iteration rounds**. On exhaustion,
  HALT and report exactly which done-rule failed, the latest scores, and why. Never
  loop forever.

## Goal

One trainer experience a client finishes in **under 15 minutes**, and it is
**chat-only** (Bjion ruling 2026-07-18): the conversation IS the whole interface.
What the chat adds over a plain chatbot is drafted replies shown IN the thread —
after every teach, the trainer posts "here is what Maya will now send when asked X"
as an inline draft bubble with Approve / Fix buttons, so the client sees Maya in
action and keeps iterating as they go. A readiness score stays pinned on top. The
trainer FISHES: every knowledge update triggers the next question for the biggest
remaining hole, and the experience NEVER stalls — there is always exactly one open
question or one pending approval in front of the client until **100% of the clear
and obvious questions** are approved. 100%, not 90-something, is the finish line.
The AI-SDR is NOT meant to answer everything — routine and simple only.

## Fixed context (read, don't re-derive)

- Source prototypes (all in `app/prototypes/`): `train-p4.html` = Test Drive card
  mechanics (panel-certified 5/5+5/5 after 4 fixes — hidden gate removed, no
  hardcoded SaaS filler, booking starts weak, rail gives match/no-match feedback);
  `train-p5.html` = artifact chat + topic checklist; `train-p2.html` = readiness bar
  + one-question-at-a-time cadence. Reuse their code, do not reinvent.
- Known killer from the lab: **loose keyword topic-mapping** put client answers under
  the wrong question in P2/P5 and failed every client tester. The hybrid must bind
  each clarifying question to its specific draft card, so an answer can never land on
  the wrong reply. Free-form chat statements that match no card must get explicit
  feedback (P4's rail-note pattern), never a silent guess.
- Chat drives, cards show: the chat asks ONE question at a time, chosen from
  whichever card is weakest; answering redrafts that card visibly and the readiness
  score moves at the same moment, so cause and effect is obvious.
- Readiness = share of the anticipated common questions whose draft the client has
  approved (not a vibes percentage). 90%+ and all cards approved = done-state:
  the approved replies listed, plus "routine replies only, anything unusual still
  comes to you."
- Drag-and-drop is FIRST-CLASS (Bjion ruling 2026-07-18): clients train by dropping
  attachments and resources, not just typing. Text files (.txt/.md/.csv) are read as
  knowledge. Everything else (PDF/DOCX/decks/images) is never fake-read AND never a
  dead end: the file becomes a sendable RESOURCE bound to a reply.
- Resources sent to LEADS are URLS, never email attachments (Bjion ruling
  2026-07-18): uploading a file trains Maya, but before a resource can appear in a
  reply the trainer MUST ask the client for the URL where it lives (site, Drive,
  Notion) and put THAT link in the draft. No URL supplied = the file stays
  training-only and the reply says nothing about it. Linked resources appear in the
  draft bubble, the recap, and the brain file with their URLs.
- Build rules proven in the lab: single self-contained file, zero external requests,
  Navreo tokens (cream/ink/ONE orange, Acid Grotesk display via data URI for the
  artifact build), `<meta charset="utf-8">`, no emoji, NO em-dashes anywhere, drop
  handlers must accept synthetic DataTransfer drops, `.txt/.md/.csv` read via
  FileReader. Working dir is iCloud-synced: re-read after every write.
- Ship two builds of the SAME experience: `app/prototypes/train-hybrid.html` (web)
  and a published Claude Artifact (favicon 🧠, redeploy same file path to keep URL).

## Steps

### Step 1 — Build the hybrid (chat-only)
Build `app/prototypes/train-hybrid.html` as a single chat column: welcome + first
question on load; drop zone + composer always available; pinned readiness bar. The
6 anticipated common questions live INSIDE the thread as draft bubbles: whenever a
teach lands (answer, file, fix), the trainer posts the redrafted reply inline with
Approve / Fix it buttons in the bubble. Question engine rules: exactly one open ask
at any moment; answering, skipping, filing or approving ALWAYS triggers the next
ask; skipped questions requeue at the end; when everything is drafted but not
approved, the trainer re-presents each pending draft for approval — no dead air,
ever. Readiness = share of the 6 obvious questions approved, and the shares sum to
**100%**; done-state fires only at 100%.
**Done-rule**: file exists, loads with zero console errors, and a scripted journey
(drop 1 file, type 1 fact, answer chat questions, approve all drafts inline)
reaches the done-state at exactly 100% with every final answer traceable to the
client's own input (no placeholder, no filler, no wrong-card answer), and at no
point in the journey is there neither an open question nor a pending approval
in the thread.

### Step 2 — Publish the artifact build
Strip wrapper tags, embed the Acid Grotesk data URI, publish as a Claude Artifact.
**Done-rule**: artifact URL live; web and artifact builds byte-equivalent except the
font/wrapper differences.

### Step 3 — Live walkthrough
Walk the full journey in the browser pane on the web build: file drop, typed fact,
at least 3 chat answers, one direct Fix it, done-state. Screenshot start, mid, done.
**Done-rule**: journey completes with no dead end; the readiness score visibly moves
on every teach action; screenshots captured.

### Step 4 — Simulate 5 random businesses and iterate to 9/10
Pick 5 random, deliberately different businesses (e.g. regional accountancy firm,
D2C skincare brand, industrial pump manufacturer, IT-managed-services provider,
commercial cleaning company). For each, spawn a simulated CLIENT persona who trains
the hybrid using that business's real-world facts (pricing style, booking habits,
objections), then a simulated CSM who inspects the resulting trained pack against
that business's 10 most common routine replies. Each scores 1-10: client on ease of
use (under-15-min, no confusion, answers stay in their words), CSM on confidence the
bot answers 90% of easy messages correctly and on-brand.
**Done-rule**: average client score 9.0+ AND average CSM score 9.0+ across all 5
businesses, with no single score below 8. If missed: collect the concrete failure
reasons, fix the hybrid (Step 1 file + republish Step 2), re-run ONLY the failed
simulations. Max 4 iteration rounds.

### Step 5 — Verdict + handover
Report: final scores table (5 businesses x 2 panels), what changed each iteration,
the two links (web + artifact), and a ≤10-item checklist for wiring the hybrid into
production `setter-train.html` share mode (seed cards from the agent's real reply
categories, write approvals into `setter_agents` via `_save_training`, LLM
classification instead of keywords, resume state, share-link minting).
**Done-rule**: report delivered in chat with the scores table, both links, and the
checklist; production untouched.

## Done-rule (whole loop)

DONE when Step 4's bar (9/10+ both panels, no score below 8) is met and Step 5's
report is delivered. This loop never modifies production (`setter-train.html`,
`server.py`, Supabase agent resources) — prototype files, artifact, and report only.
