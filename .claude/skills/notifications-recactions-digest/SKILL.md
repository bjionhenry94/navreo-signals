---
name: notifications-recactions-digest
description: Static orchestration skill for the Navreo signals tool — make the Recommended Actions section on notifications.html digestible for an account strategist. Collapses each card to a one-line verdict + one primary action with details behind an expander, adds a triage summary strip that groups the ~63 actions by type, shows per-campaign variant stats side-by-side, and surfaces which variants produced positive replies / meetings booked. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Done when a simulated account-strategist panel scores read-and-act ability 8/10+. Use when the user says "simplify the recommended actions", "run the notifications digest pass", "make the recommendations easier to read", or "/notifications-recactions-digest".
---

# Notifications: Recommended Actions Digest Pass

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

## Goal

An account strategist opens notifications.html → Recommended Actions and can, in under
a minute per campaign: (1) see WHAT to do in one line, (2) see WHY in one click, (3) see
the variants side-by-side with which ones actually produced positive replies / meetings,
(4) act. Nothing is deleted from the data model — this is a presentation + triage pass.

**Verification bar:** a simulated account-strategist panel scores the rebuilt section
**8/10 or higher** on "can I read this and know what to do?" (Step 6).

## The problem being fixed (from the user, 2026-07-10)

- Each card is a wall of 4-7 dense bullets; ~63 cards; the kill-threshold paragraph
  repeats verbatim on many cards. Too much to read, too much to weigh.
- Variant data is described in prose ("Bug A on Email 1 Var B: 0% distribution…")
  instead of shown side-by-side.
- No visibility into which variants led to positive replies or meetings booked.

## Ground truth (verify in Step 0, don't trust blindly)

- Data source: `app/build_notifications.py` Section 7 writes `recommended_action`
  rows (one block per campaign, `action_type` = kill_threshold_pivot / upload_leads /
  replace_variants / scale_winner / disable_loser / fix_distribution / run_list_audit /
  nearing_completion) to the `optimiser_notifications` Supabase table. Bullets arrive
  as pre-baked prose. Per-variant stats already exist upstream in
  `fetch_variant_stats()` (sent / reply / positive per seq_variant_id).
- UI: `app/notifications.html` renders the cards + action buttons (Pause / Copy Claude
  prompt / Open in Smartlead / Acknowledge / Mark actioned / Dismiss). Keep every
  existing button and its wiring — this pass changes layout, not behaviour.
- Working copy is `~/navreo-signals/` (git/Render); an iCloud copy also exists —
  diff-check the two after merging (memory: `signals-deploy-repo`). Local dev:
  `python3 app/server.py` → `http://localhost:7901/app/notifications.html`.
- Rerun-safety rule from build_notifications.py: upserts must never reset a CSM's
  acknowledged/actioned/dismissed state. Any new columns follow the same rule.

## Steps

### Step 0 — Re-verify ground truth
Read the current `notifications.html` card renderer and `build_notifications.py`
Section 7. Confirm where bullets, action_type, and variant stats live, and whether
positive replies can be attributed per variant (Smartlead `/statistics` rows carry
`seq_variant_id` + lead reply/positive flags; meetings booked = positive-reply
category / `call_booked` tag per lead, joinable to the variant that got the reply).
**Done-rule:** a short written map of (a) card render path, (b) variant-stats fields
available, (c) a YES/NO on per-variant positive attribution with the exact join. If
NO on (c), pause and ask the user (even in OFF mode) — don't fabricate attribution.

### Step 1 — Triage summary strip
Add a compact strip above the cards: total actions grouped by action_type with counts
("4 pivots · 9 upload leads · 3 fix distribution …"), each chip filtering the list on
click. High-priority-and-new floats to the top by default.
**Done-rule:** strip renders from live data, chips filter correctly, counts sum to the
section's action total (verified against the `63 actions` counter).

### Step 2 — One-line verdict cards
Rebuild each card as: **one bold verdict line** (imperative, ≤12 words, derived from
action_type, e.g. "Pause — kill threshold hit, ICP not working") + the single primary
button for that action_type + a "Why?" expander holding the current bullets. Repeated
boilerplate (the kill-threshold pivot paragraph, the Bug A explanation) is written ONCE
as a shared explainer the expander links to, not repeated per card. No bullet text is
deleted — it all lives behind the expander.
**Done-rule:** collapsed card = title line + stats line + verdict line + buttons only;
expanding shows everything the old card showed; boilerplate appears exactly once per
page.

### Step 3 — Variants side-by-side
Inside each card (collapsed section or shown on expand), a compact per-variant table:
Email step / Variant / Distribution % / Sent / Replies / Positives — one row per
variant, worst-vs-best visually flagged. The prose "Bug A … 0% distribution" bullets
become a flag on the affected row instead of paragraphs.
**Done-rule:** for a campaign with known variant stats, the table numbers match
Smartlead's variant statistics endpoint for that campaign, and 0%-distribution
variants are visibly flagged.

### Step 4 — Positive-outcome attribution per variant
Add Positives (and Meetings/call-booked where the data supports it, per Step 0's
answer) as columns in the Step 3 table, so the strategist sees which variant actually
produced results. Where attribution is genuinely unavailable, show "—" with a tooltip
saying why — never a guessed number.
**Done-rule:** for at least one campaign with ≥1 positive reply, the positive count
appears on the correct variant row and reconciles with the campaign's total positives.

### Step 5 — Local verification
Run the app locally, load notifications.html with real data, exercise: chip filtering,
expand/collapse, one of each action button (Acknowledge/Dismiss on a test row), reload
persistence of acknowledged state. Screenshot the before/after.
**Done-rule:** no console errors, all existing buttons still work, ack/dismiss state
survives rerun of build_notifications.py.

### Step 6 — Strategist panel score
Spawn 3 subagents (model: sonnet) role-played as account strategists of mixed
seniority. Each gets the rendered page content and must: state the top 3 actions they'd
take and why, then score 1-10 on "I could read this and act without asking questions".
**Done-rule:** average score ≥ 8/10 AND every panelist's top actions match what the
data actually says. If < 8, feed the specific complaints back into Steps 1-4 (counts
against those steps' retry caps) and re-panel.

### Step 7 — Ship
Commit in `~/navreo-signals/`, push to deploy, diff-check against the iCloud copy,
confirm the live page at navreo-signals.onrender.com renders the new section.
**Done-rule:** live page shows the digest layout; iCloud vs git diff is clean or
explained; final report lists each step PASS/FAIL with panel scores.

## Final report (always, both modes)

One table: step, status (PASS / SKIPPED-already-passing / FAILED+reason), retries used.
Plus the panel's average score and the before/after screenshots.
