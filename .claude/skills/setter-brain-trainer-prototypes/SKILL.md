---
name: setter-brain-trainer-prototypes
description: Static orchestration skill that takes the existing AI-SDR training page (app/setter-train.html share-link experience) and builds 5 prototypes of a faster, simpler client-facing "train the agent's brain" flow — drag-and-drop files, free-form teaching, clarifying questions back, works both as a shareable web link AND as a Claude Artifact — then verifies each against a simulated panel of 5 CSM user-testers and 5 client testers. Web version is the priority; one prototype must be artifact-native. Use when the user says "run the brain trainer prototypes", "improve setter training", "build the AI-SDR training prototypes", or "/setter-brain-trainer-prototypes".
---

# Setter Brain-Trainer Prototypes

## Loop Training Mode — TOGGLE (flip this line to change behaviour)

**Loop Training Mode: ON** ← default. Change to `OFF` to run autonomously.

- **ON**: pause at the end of EVERY step and wait for Bjion's explicit approval before
  continuing. Skip any step whose done-rule already passes. Only re-run steps that fail.
- **OFF**: run all steps autonomously with no pauses, but still check every done-rule
  and respect the retry cap.
- **Retry cap (both modes)**: max **2 retries per step**. On the 3rd failure, HALT the
  loop and report exactly which done-rule failed and why. Never loop forever.

## Goal

Make training an AI-SDR on a company **quicker and simpler for the client**: they open
one link (web URL or Claude Artifact), drag in files, type what they know, answer the
clarifying questions the trainer asks back, and in **under 15 minutes** the agent can
answer ~90% of routine, simple replies on auto-pilot — on brand, correct on key
questions, and never brand-damaging. The AI-SDR is NOT meant to answer everything —
only the most commonly asked, routine questions.

## Fixed context (read, don't re-derive)

- Current experience: `app/setter-train.html` (~1,340 lines) — Q&A-batch quiz with a
  public `?share=<token>` mode (`_TRAIN_SHARE_GET` + public POSTs in `app/server.py`
  ~line 11508–13296; token verified by `setter.py` `verify_training_share`).
- What it LACKS today: drag-and-drop file upload, free-form "tell it stuff" input, and
  a clarifying-questions-back loop. Today's flow = Bjion pastes resources into Claude
  and routes them into the agent via Supabase manually. That is the pain to kill.
- New POST routes on the server must read `self._post_body`, never `rfile.read`.
- Working dir is iCloud-synced — after every file write, re-read the file to confirm
  the edit stuck (iCloud can revert edits).
- All UI uses the Navreo Design System (`~/.claude/skills/navreo-design-system/`).
- Artifacts have a strict CSP: fully self-contained, no external requests — an
  artifact prototype talks to the trainer via `window.claude` runtime, not fetch.

## Steps

### Step 1 — Baseline map
Read `app/setter-train.html` and the training routes in `app/server.py` / `setter.py`.
Write a ≤1-page baseline note: current share-link flow, where agent resources live in
Supabase, and the exact seams a new trainer plugs into (share-token verify, resource
write path).
**Done-rule**: baseline note exists and names the resource-write endpoint + token
verify function by name and line.

### Step 2 — 5 prototype concepts
Design exactly 5 distinct concepts. Every concept MUST include: (a) drag-and-drop
file intake, (b) free-form "tell it stuff" text input, (c) the trainer asking
clarifying questions back, (d) a done-state that shows the client what the agent can
now answer. At least 4 must run from the public web share link; exactly 1 must be
artifact-native (same brain, Claude Artifact shell). Concepts must differ in
interaction model (e.g. chat-first, checklist-first, interview wizard, drop-zone-first,
test-drive-first) — not skins of one idea.
**Done-rule**: 5 concepts written, each ≤10 lines, each ticking (a)–(d), interaction
models pairwise distinct, exactly 1 flagged artifact-native.

### Step 3 — Build the 5 prototypes
Build each as a standalone page under `app/prototypes/train-p1.html` … `train-p5.html`
(self-contained, reusing the existing `?share=` token endpoints where a live call is
needed, mock data where not — prototypes must NOT write to production agent
resources). Build the artifact-native one as an actual published Artifact (load
`artifact-design` first; Navreo Design System styling).
**Done-rule**: 5 files exist and each loads without console errors in the browser
pane; the artifact prototype has a live artifact URL.

### Step 4 — Live walkthrough
For each web prototype: open it in the browser pane and walk the full journey — drop
a file, type a fact, answer a clarifying question, reach the done-state. Rendered
page is the only done-evidence; screenshots for each.
**Done-rule**: all 5 walked end-to-end with no dead ends; screenshot per prototype.

### Step 5 — Panel verification
Spawn simulated testers as subagents: **5 CSMs** (score: simplicity, ease of sharing
with a client, confidence the trained bot answers 90% of routine replies on
auto-pilot) and **5 clients** (score: training takes <15 min, agent stays on brand,
answers key questions correctly, cannot damage the brand). Each tester reviews all 5
prototypes against the baseline and scores pass/fail per criterion with one sentence
of reasoning.
**Done-rule**: a prototype PASSES the panel if ≥4/5 CSMs and ≥4/5 clients pass it on
every criterion. At least one prototype must pass. If none pass, collect the top 3
failure reasons, fix ONLY the closest prototype, and re-panel (counts as a retry).

### Step 6 — Verdict + handover
Write the final report: ranked prototypes, the panel scorecard, the recommended
winner, and a concrete "graduate to production" checklist (what to wire into
`setter-train.html` / `server.py`, and what the artifact distribution flow looks
like). Recommend — do not ship to production inside this loop.
**Done-rule**: report delivered in chat with winner named, scorecard table included,
and graduation checklist ≤10 items.

## Done-rule (whole loop)

The loop is DONE when Step 5's panel has ≥1 passing prototype and Step 6's report is
delivered. Nothing in production (`setter-train.html`, `server.py`, Supabase agent
resources) may be modified by this loop — prototypes and report only.
