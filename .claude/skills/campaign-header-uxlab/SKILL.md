---
name: campaign-header-uxlab
description: Static orchestration skill that prototypes a brand-new header for the campaigns fleet view (navreo-signals.onrender.com/app/campaigns.html). Recons the live header, builds 5 minimal self-contained prototypes in the Navreo design system (app/prototypes/) — fleet snapshot up top, filter + navigate below, nothing removed — screenshots them with headless Chrome, then a 5-persona panel of non-technical founders and sales leaders scores every prototype until each earns 9/10+ from every panelist on actionable insights, easy to digest, AND beauty. Delivers gallery + scorecard for Bjion to pick a winner. Loop Training Mode baked in, default ON. Trigger: "run the campaign header lab", "prototype the campaigns header", "campaign header prototypes", "/campaign-header-uxlab".
---

# Campaign Header — UX Lab

One glance at the top of the campaigns page tells a non-technical founder how the whole
fleet is doing and where to click next. Static loop — fixed steps, checkable done-rules,
Loop Training Mode controls pauses.

## ⚙️ LOOP TRAINING MODE → **ON** (default)

Flip it by editing this one line (a runtime "training off" / "training on" in the
invoking message overrides it for that run only):

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at every step: announce what the step is about to do, and after it runs show
  the result and WAIT for Bjion's explicit approval before continuing.
- Before running a step, check its done-rule first. If it already passes, **skip it** —
  say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.
- "go / yes / continue" advances; anything else is revision feedback — apply it and
  re-run the step (Bjion-requested re-runs don't count against the cap).

**When OFF**
- Run all steps autonomously, no pauses.
- Keep every done-rule check, every skip, and the same retry cap. Report at the end,
  not between steps.

**Retry cap (both modes):** any single step runs **max 3** times against its done-rule,
and only the failing unit re-runs (a failing prototype, not all five). On cap-hit,
record FAILED with the reason, keep going where possible, and surface it in the final
report. Never silently exceed.

## THE GOAL

A simple, highly visual campaign header that lets a non-technical founder digest the
state of the fleet in seconds: the top stats first, then filter and navigate. Plain
words a 16-year-old would use. **If it needs explaining, it's already too complicated —
redesign it, don't caption it.**

## HARD INVARIANTS (all five prototypes)

- **Nothing removed.** Everything on today's header survives — restyled, merged or
  moved is fine; dropped is not. Baseline inventory (Step 1 re-checks live; live wins):
  fleet stats **Emails sent · Reply rate · Emails per positive · Meetings booked**, each
  with trend spark + vs-last-week delta · **Live** freshness + **Refresh** · **7d/14d/30d**
  presets · **search** · **Client** filter · **Status** filter · chips **All Priorities,
  Most meetings, Most positives, Most efficient, Most left to send, Biggest lists**.
- Navreo design system exactly: `app/navreo.css` tokens, Acid Grotesk display + DM Sans
  body, radius 12, **one orange element per screen**.
- ≤3 date presets, 30-day cap (standing analytics ruling).
- Minimal: no explainer sentences, no legends doing the design's job, no tooltip
  crutches. Detail on demand, never ambient.
- Plain English only — "replies", not "engagement". A word a 16-year-old wouldn't say
  doesn't ship.
- Real-feeling numbers cloned from the live page, so judges score something true.
- Prototypes are local files in the repo; this loop **never commits or pushes**.

## THE STEPS

### Step 1 — Ground
Read `~/navreo-signals/app/navreo.css` tokens + the header markup in
`app/campaigns.html`; open the live page and screenshot the current header. Write
`app/prototypes/campaign-header-inventory.md`: every control and stat in today's
header, one line each — the binding nothing-removed checklist.
- **Done-rule:** inventory file exists, covers every control visible in the live
  screenshot, and names the exact tokens/classes to reuse.

### Step 2 — Build 5 prototypes
`app/prototypes/campaign-header-p1..p5.html` + `campaign-header-index.html` (gallery
linking all five). Self-contained pages loading the live tokens (`@font-face` →
`../fonts/`): the new header at top, a few faint placeholder campaign cards below so it
reads in context. Five genuinely different information architectures — different bets
on "what a founder needs first" — not five skins of one layout.
- **Done-rule (per prototype):** every inventory line ticked · ≤1 orange element ·
  zero explainer text · every label passes the 16-year-old word test.

### Step 3 — Screenshot
Headless Chrome → `campaign-header-pN.png` beside each file, real desktop width.
- **Done-rule:** 5 crisp PNGs, fonts rendered, nothing clipped.

### Step 4 — Panel
5 parallel judge agents (fixed personas below) — each reads all 5 PNGs cold: no pitch,
no design notes. Strict JSON back: per prototype, 1–10 on
**(a) actionable insights** — "I know what to look at and what to click next" ·
**(b) easy to digest** — "I got it in 5 seconds" (any word a 16-year-old wouldn't use
caps this at 6) · **(c) beauty** — "I'd be proud if this were my product's front page."
Plus top fixes per prototype. Rubric anchor: 9+ = "I would ship this as-is."
Write the full grid to `app/prototypes/campaign-header-scorecard.md`.
- **Done-rule:** scorecard complete — 5 judges × 5 prototypes × 3 scores, top fixes
  captured.

### Step 5 — Verdict & revise
**PASS when every prototype scores 9+ on all three criteria from all 5 panelists.**
Otherwise: apply the top fixes to the failing prototypes only, re-screenshot those,
re-run Step 4 for those only (fresh judge contexts), update the scorecard.
- **Retry cap: 3 panel rounds total.** Still short after round 3 → stop, mark the
  stragglers FAILED, and deliver everything with the outstanding objections.

### Step 6 — Deliver
One closing message: the 5 screenshots · gallery path · scorecard table (prototype ×
criterion, rounds used) · one-line pitch per prototype · the panel's single favourite.
Bjion picks the winner. Shipping the winner into the live `campaigns.html` is a
separate follow-up task, not this loop.
- **Done-rule:** closing message contains all five parts.

## PANEL PERSONAS (fixed — one agent each, non-technical)

1. **Maya** — agency founder; checks the tool between client calls, no analytics
   background, wants the verdict not the data.
2. **Jack** — 55-year-old business owner; big obvious numbers, distrusts anything fiddly.
3. **Priya** — first-time SaaS founder; hates dashboards, loves being told what matters.
4. **Tom** — sales leader, phone-first; decides in 5 seconds or bounces.
5. **Sofia** — sales director, 30 seconds between meetings; only wants "what do I do next".
