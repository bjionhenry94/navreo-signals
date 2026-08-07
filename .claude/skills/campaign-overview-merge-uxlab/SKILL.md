---
name: campaign-overview-merge-uxlab
description: Merge the campaign Overview tab's "Everyone's status" and "Live performance" cards into ONE visual, easy-to-digest, actionable section. Builds 5 prototype variants in the live Navreo design system (app/prototypes/), screenshots them with headless Chrome, and scores them with a 5-persona account-strategist panel until one variant earns 9/10+ from every panelist on BOTH digestibility and actionability. Trigger: "merge the overview status and performance cards", "overview merge prototypes", "overview merge uxlab", "/campaign-overview-merge-uxlab".
---

# Campaign Overview Merge — UX Lab

## Loop Training Mode

**LOOP_TRAINING_MODE: ON** ← the toggle. Flip to OFF for autonomous runs. A runtime
instruction in the invoking message ("training off" / "training on") overrides this
default for that run only.

- **ON** — pause at every step below and wait for Bjion's approval before continuing.
  Skip any step whose done-check already passes. Re-run only the steps that fail.
  Retry caps still apply — the loop can never run forever.
- **OFF** — run all steps end-to-end with no pauses. Keep every done-check and every
  retry cap exactly as written.

## Goal

One merged "status + performance" section for the campaign Overview tab
(`app/campaigns.html`, hash `#/c/<id>` — the bare hash IS Overview), replacing the two
stacked cards, more visual and easier to act on than either original.

## Fixture data (the spec — prototypes use these exact numbers)

- Status partition, foots exactly to **12,405 in the contact record**:
  Started 5,356 · Finished the sequence 3,952 · Being worked 2,811 · Paused 198 · Blocked 88.
- Two counters, not a contradiction: contact record 12,405 vs Smartlead platform
  audience 12,310. Must be explained via progressive disclosure (tooltip/expander),
  never an inline paragraph.
- Campaign-to-date (show the sync line; positives = Smartlead's "interested" mark):
  Leads 12,310 · Emails sent 12,374 · Replies 187 (1.51%) · Positive replies 14 ·
  Bounced 121 (1%) · Meetings 2 · **Sends per positive 1 per 884 — healthy under 1,500**
  (the only stated benchmark; don't invent others).

## Steps

1. **Ground** — read `app/navreo.css` tokens + the Overview markup in
   `app/campaigns.html`. Done-check: can name the exact tokens/classes to reuse
   (`.card` `.pill` `.sc-tile` `.num-hero` `.bar-track` `.freshness`, Acid Grotesk
   display + DM Sans body, radius 12, one-orange-per-screen rule).
2. **Build 5 variants** — `app/prototypes/overview-merge-p1..p5.html` + an index page.
   Self-contained pages loading the live tokens (`@font-face` → `../fonts/`). Each
   variant merges BOTH cards into ONE section with a genuinely different information
   architecture (not five skins of one layout). Done-check: 5 files, every fixture
   number present, reconciliation note behind disclosure, ≤1 orange element each.
3. **Screenshot** — headless Chrome → `overview-merge-pN.png` beside each file.
   Done-check: 5 crisp PNGs, fonts rendered, nothing clipped.
4. **Panel** — 5 parallel account-strategist agents (fixed personas below). Each reads
   all 5 PNGs + HTML and returns strict JSON: per variant, 1–10 for (a) easy to digest
   (b) actionable, plus top fixes. Rubric anchor: 9+ = "I would ship this as-is."
5. **Verdict & revise** — PASS when ≥1 variant scores ≥9 on BOTH dimensions from ALL 5
   panelists. Otherwise apply every top fix to the leading variants, re-screenshot,
   re-run step 4. **Retry cap: 3 panel rounds total.** If still short after round 3,
   stop and deliver the best variant plus the outstanding objections.
6. **Deliver** — winner PNG + all variants + panel score table + ship recommendation.
   Shipping the winner into `campaigns.html` is a separate follow-up task, not this loop.

## Panel personas (fixed — one agent each)

1. **Priya** — senior strategist, 30 seconds before a client call; scans for the verdict.
2. **Marcus** — data sceptic; hunts ambiguity and numbers that don't reconcile.
3. **Sofia** — junior account manager; needs "what do I do next" spelled out.
4. **Dan** — deliverability lead; bounce / blocked / paused front of mind.
5. **Amara** — client storyteller; would screenshot this straight into a client deck.

## Retry caps

Panel rounds: 3 max. Build/screenshot fixes: 2 retries per step. On any cap: stop,
report the best result, what's still failing, and the panel's remaining objections.
