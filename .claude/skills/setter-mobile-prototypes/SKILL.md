---
name: setter-mobile-prototypes
description: Static orchestration skill that builds 5 prototypes of a MOBILE version of the Appointment Setter (app/setter.html on navreo-signals.onrender.com), each a distinct one-thumb interaction model for the core on-the-go moment - an interested reply lands and Bjion responds in seconds from his phone. Prototypes are self-contained pages under app/prototypes/ with mock data (zero production writes, zero real sends), verified at mobile viewport, then judged by a simulated panel of 5 (3 appointment setters + 2 mobile UI designers) at an 8/10+ bar, deployed as phone-openable URLs for Bjion's real-thumb test. Use when the user says "run the setter mobile prototypes", "build the mobile setter", "mobile version of the setter", or "/setter-mobile-prototypes".
---

# Setter Mobile Prototypes

## Loop Training Mode — TOGGLE (flip this line to change behaviour)

**Loop Training Mode: ON** ← default. Change to `OFF` to run autonomously.

- **ON**: pause at the end of EVERY step and wait for Bjion's explicit approval before
  continuing. Skip any step whose done-rule already passes. Only re-run steps that fail.
- **OFF**: run all steps autonomously with no pauses, but still check every done-rule
  and respect the retry cap.
- **Retry cap (both modes)**: max **2 retries per step**. On the 3rd failure, HALT the
  loop and report exactly which done-rule failed and why. Never loop forever.

## Goal

When Bjion is on the go and an interested reply lands, he opens the setter on his
phone and responds in seconds: read the reply, glance at the thread, approve (or
quick-edit) the draft, sent. One thumb, no pinch-zooming a desktop layout, no fear of
fat-finger sends. Build **5 prototypes**, each a genuinely different mobile
interaction model, and prove them against a panel of the people who'd live in this
screen. Winner graduates to production only after Bjion's real-phone pick.

## Fixed context (read, don't re-derive)

- Source of truth is the git/Render repo `~/navreo-signals` (push to `main`
  auto-deploys). The iCloud copy is DEPRECATED — never edit it.
- Live app: `https://navreo-signals.onrender.com/app/setter.html`, behind the
  Supabase login gate (anonymous curl 302s to login; Bjion signs in once on his phone).
- Prototypes live at `app/prototypes/setter-mobile-p1.html` … `p5.html`:
  self-contained, inline mock reply data, render with zero API calls, and NEVER write
  to production, queue rows, or real sends.
- Setter behaviours every prototype must respect: Approve = send (edits teach on
  Approve, Undo toast); sub-sequence picked by the setter at Approve via chip gate,
  never suggested; Dismiss is instant/optimistic; one row per lead-thread; reply
  bodies render cleaned (no raw HTML tags); "No agent" rows still show.
- Visual language comes from the live setter itself: lift tokens (colours, type,
  spacing, pills) from `app/setter.html` so each prototype feels like the same
  product on a phone. Navreo conventions hold (no emoji in UI).
- Mobile verification viewport: browser pane at 375×812 (`resize_window` mobile
  preset). Rendered page is the only done-evidence.

## The five interaction models (pairwise distinct, not skins)

| # | Model | The idea |
|---|---|---|
| P1 | **Triage stack** | One reply at a time, full-screen card: their reply up top, your draft below. Swipe/tap verbs: approve, edit, dismiss, next. |
| P2 | **Chat thread** | The lead thread rendered messenger-style; the draft sits pre-filled in the composer. The most familiar mental model on a phone. |
| P3 | **Inbox + bottom sheet** | Today's list, mobile-adapted: reply rows with status pills; tap opens a bottom sheet with thread + draft + a thumb-pinned Approve bar. |
| P4 | **Notification-first** | Simulated push → a single approve-card screen (Send / Edit / Later) built for the sub-10-second moment, with a queue of pending cards behind it. |
| P5 | **One-thumb cockpit** | Thread + draft with every control in a fixed bottom action bar (Approve, Edit, Redraft, Sub-sequence, Dismiss) inside the thumb zone; hold-to-send safety. |

## Steps

### Step 1 — Baseline map
Read the live `app/setter.html` (repo copy) and the setter memory index. Write a
≤1-page note: the mobile job list (see interested reply fast → read thread → edit →
approve/send → dismiss → pick sub-sequence), the token sheet lifted from setter.html
CSS, and the behaviour invariants above restated.
**Done-rule**: note exists with token sheet + invariant list + the on-the-go scenario
written as one paragraph.

### Step 2 — Build P1–P5
Build the 5 pages in `~/navreo-signals/app/prototypes/` per the table, seeded with
6–8 realistic mock replies (mixed: interested, question, objection, ready-to-book).
Each must complete the full journey offline: open reply → read thread → edit draft →
approve → sent state (with Undo toast) → next reply; plus a dismiss and a
sub-sequence pick somewhere in the flow.
**Done-rule (per prototype)**: loads clean at 375×812 with zero console errors; full
journey completable by tapping; invariants respected; no network required to render;
zero production writes possible.

### Step 3 — Panel
Spawn 5 simulated panelists as subagents: **3 appointment setters** (live in reply
inboxes all day, impatient, on their feet) and **2 mobile UI designers** (thumb
zones, tap targets, error-proofing). Each walks all 5 prototypes at mobile viewport
against the scenario: *"You're between meetings. An interested reply just landed.
Lock screen → response sent — how fast, how few taps, how confident?"* Each scores
every prototype /10 across speed-to-send, one-thumb reachability, clarity/trust in
the draft + thread, and fat-finger safety — one overall score + a worst-moment quote.
**Done-rule**: 25 scorecards (5 panelists × 5 prototypes), each with a worst-moment
quote.

### Step 4 — Fix loop
Any prototype under **8/10 panel average** gets its worst-moments fixed and is
re-panelled (re-panel = a retry). Over-simplification that hides needed context is a
defect too.
**Done-rule**: ≥3 of the 5 prototypes at 8/10+ average, the recommended winner among
them. Cap-hit = FAILED-BAR with honest scores; never inflate.

### Step 5 — Deploy + hand-off
Push the 5 prototype files to `main` (additive only — stage exactly the 5 new files,
`git fetch` + ff-only merge first, confirm `git diff` shows nothing but the
prototypes; production setter untouched). Confirm the URLs respond, then deliver the
report in chat: the 5 phone-openable URLs, the scorecard table, the recommended
winner with one-line reasoning per prototype, and a graduation checklist (≤10 items)
for making the winner the production mobile experience of setter.html. Bjion
thumb-tests on his real phone and picks; nothing merges into production inside this
loop.
**Done-rule**: 5 live URLs + report with scorecard table + winner + checklist
delivered in chat.

## Done-rule (whole loop)

The loop is DONE when Step 4's bar is met (≥3 prototypes at 8/10+, winner included),
the 5 prototypes are live at phone-openable URLs, and Step 5's report is delivered.
`app/setter.html`, `setter.py`, `server.py`, and all production data stay untouched —
prototypes and report only.
