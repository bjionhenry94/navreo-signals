---
name: campaign-overview-hub-uxlab
description: Orchestration loop that redesigns the campaign Overview tab (app/campaigns.html, hash #/c/3421811 — the bare hash IS Overview) into a simple, highly-visual "central hub" a non-technical founder reads in seconds to see what is and isn't working and book more meetings. Builds 5 minimal prototypes in the live Navreo design system (app/prototypes/overview-hub-p1..p5.html), screenshots them with headless Chrome, and scores them with a 5-persona panel of non-technical founders and sales leaders until EVERY prototype earns 9/10+ from all five on all three axes: actionable insights, easy to digest, beauty of the design. Trigger: "run the overview hub uxlab", "overview hub prototypes", "redesign the overview tab", "/campaign-overview-hub-uxlab".
---

# Campaign Overview Hub — UX Lab 🧪

## ⚙️ LOOP TRAINING MODE = **ON**  (default)

Flip this one line to `OFF` for autonomous runs. Nothing else changes. A runtime
instruction in the invoking message ("training off" / "training on") overrides this
default for that run only.

| Mode | Behaviour |
|------|-----------|
| **ON** *(default)* | Pause at **every step** and wait for Bjion's approval before continuing. **Skip** any step that already passes its done-rule. Only **re-run** the steps that fail. The retry cap still applies — the loop can never run forever. |
| **OFF** | Run **autonomously**, no pauses. Still enforce **every done-rule** and the **retry cap** exactly as written. |

**Retry cap:** each step may be attempted at most **3 times**. On the 3rd failure, STOP and report the blocker — never loop forever. Panel rounds are capped at **3** (see Step 5).

---

## The Goal

Turn the Overview tab of the campaign detail page — `https://navreo-signals.onrender.com/app/campaigns.html#/c/3421811` — into a **central hub**: a simple, highly-visual page where a **non-technical founder** can, in seconds, see **what's working, what isn't, and the one thing to do next** so they book more meetings.

Deliver **five distinct, minimal prototypes** of that experience.

**North star:** less explanation, more intuitive design. If it needs explaining, it's already too complicated. Language a 16-year-old understands. A picture beats a paragraph beats a table.

## LOCKED — do not change (every prototype keeps these)

1. **The order of information stays** — glance → whole picture → suggested actions → warm-reply receipts. Same top-to-bottom sequence.
2. **The same sections stay** — no section is dropped; none is added.
3. **The insight-widget design stays** — the `nvzCard` widgets inside "The whole picture" keep their current visual design. You may change what surrounds them; you may not restyle the widgets themselves.
4. **The Suggested actions section stays** — the `actionCardHTML` action cards keep their look and behaviour. Re-frame around them; don't rebuild them.

Anything else is fair game.

## FREE TO CHANGE (this is where the work is)

- **The "campaign at a glance" card** — redesign it. Today it's a two-panel tile grid ("Results so far" | "Who we're working"). Make it a *picture* of the campaign a founder gets at a glance: charts, bars, rings, a one-line verdict — not a raw number grid.
- **"The whole picture" prose** — today it's a wordy block (teaser headline + a reconciliation footnote + a drift footnote). **Cut it to near-zero words.** Keep the insight widgets; strip the paragraphs. The lifetime-vs-window reconciliation ("a different counter, not a contradiction") is *true and must survive*, but it belongs behind a tooltip/disclosure — never as an inline paragraph.

## Must-haves (bake into every prototype)

1. **A plain-English verdict before any number** — "Nothing's landing yet — time to change the opener," in 16-year-old words, not a table to interpret.
2. **Highly visual** — the glance reads as a chart/bar/ring, not a grid of digits. A founder should *feel* the story before reading it.
3. **One next move, not a menu** — the single thing to do next is obvious (it lives in Suggested actions; the glance should point at it).
4. **Honest small-sample / empty states** — 0 positives at 0.9% reads calmly and truthfully ("too early / not landing"), never as a broken-looking blank or a fake win.
5. **Reconciliation behind disclosure** — the two counters (lifetime vs the recent window) are reconciled in a tooltip/expander, never inline prose.
6. **No jargon, no emoji in the UI** — cream/ink, ONE orange accent, Acid Grotesk display + DM Sans body, radius 12. Navreo Design System (`~/.claude/skills/navreo-design-system/`, tokens in `app/navreo.css`).

## Fixture data (this campaign, #/c/3421811 — KRG)

Prototypes hydrate with these real numbers so the panel judges the true page.

- **Recent window ("whole picture" today):** 7,038 sends · 63 replies · **0 positives** · **0.9%** reply rate.
- **Variants:** Variant A 1,880 sends, empty · Variant B 1,873 sends, empty. Both run the **same subject line as the Hard twin** → one angle tested twice, not two angles once.
- **List progress:** 51.2% worked · **6,720 sends still to come** → the strongest reason to change the opener *now* rather than let it finish.
- **Ownership:** KRG's own Smartlead account → Bjion's call with the client; the edit happens in KRG's UI (no in-tool send).
- **Two counters, not a contradiction:** the glance shows **campaign-lifetime** totals; the window above is a newer, narrower Smartlead sync. Reconcile behind disclosure only.
- **Lifetime "glance" totals:** pull live at Step 1 (campaign-detail payload for 3421811) and write them into the fixture before building — the tile numbers must be the real lifetime ones, not the window's.

---

## Steps (each has its own done-rule; skip any that already passes)

**Step 1 — Ground.**
Read `app/navreo.css` tokens and the Overview markup in `app/campaigns.html` (the `renderCampaignPage` overview block, ~lines 3440–3490). Pull the live lifetime "glance" numbers for campaign 3421811 (mint the HMAC `navreo_session` cookie; campaign-detail payload, not a screenshot).
_Done-rule:_ can name the exact tokens/classes to reuse (`.ov-card` `.card-title` `.card-subtitle` `.perf-tile` `.perf-num` `.perf-label` `.ovm-split`, the `nvzCard` insight widget, `actionCardHTML` suggested actions, one-orange-per-screen rule, fonts from `../fonts/`) AND the real lifetime glance numbers are written into the fixture.

**Step 2 — Build the five prototypes.**
`app/prototypes/overview-hub-p1..p5.html` + an `overview-hub-index.html` linking them. Self-contained pages that load the live tokens (`@font-face` → `../fonts/`), hydrated with the fixture. Five genuinely different information architectures for the same tab — vary the *pattern*, not the paint. For example:
- **verdict-ring** — one big health ring + a plain verdict on top, evidence below;
- **traffic-light** — red/amber/green read on each thing that matters, worst pinned first;
- **story-strip** — a left-to-right funnel a founder reads like a sentence (sent → replies → positives → meetings);
- **two-questions** — "How's it going?" then "What do I do?", nothing else above the fold;
- **scoreboard** — the campaign as a sports scoreboard: the number that matters huge, the rest quiet.

Every prototype keeps the four LOCKED items, honours the must-haves, redesigns the glance, and cuts "the whole picture" to near-zero words.
_Done-rule:_ 5 files render with no console errors; section **order and set preserved**; insight widgets + Suggested-actions section intact and unrestyled; glance redesigned as a visual; whole-picture prose ≤ one short line; every fixture number present; reconciliation behind disclosure; ≤1 orange element per screen.

**Step 3 — Screenshot.**
Headless Chrome → `overview-hub-pN.png` beside each file (desktop width).
_Done-rule:_ 5 crisp PNGs, fonts rendered, nothing clipped.

**Step 4 — Run the 5-persona panel.**
Five parallel agents, fixed personas below (non-technical founders + sales leaders). Each reads all 5 PNGs + HTML and returns strict JSON: per prototype, 1–10 on **(a) actionable insights, (b) easy to digest, (c) beauty of the design**, plus the top fix per prototype. Rubric anchor: **9+ = "I'd use this to run my campaign — ship it as-is."**
_Done-rule:_ 5 prototypes × 5 personas × 3 axes = **75 scores** recorded, each with a one-line reason.

**Step 5 — Verdict & revise.**
**PASS when all 75 scores ≥ 9** (every prototype ≥9 on all three axes from all five personas). For any prototype with any axis < 9, apply that panel's top fixes to *that prototype only*, re-screenshot (Step 3), re-score (Step 4). **Retry cap: 3 panel rounds total.** If still short after round 3, STOP and deliver the best prototypes plus the outstanding objections — never loop forever.
_Done-rule:_ all 75 scores ≥ 9, **or** 3 rounds spent and the shortfall reported.

**Step 6 — Deliver.**
One line + link per prototype, the winner named with why it best serves the goal, and the full 75-score table. Shipping the winner into `campaigns.html` is a **separate follow-up task, not this loop.**
_Done-rule:_ 5 prototype links delivered; winner named; 75-score table shown; LOCKED items confirmed intact in all five.

---

## Panel personas (fixed — one agent each, all non-technical)

1. **Maya** — bootstrapped SaaS founder, no cold-email background; opens the tab between meetings and wants "is this working, yes or no?"
2. **Tom** — VP of Sales; lives for pipeline and meetings booked; will not read a paragraph.
3. **Priya** — agency owner running client campaigns; needs to screenshot the page straight into a client update and have it make sense.
4. **Jordan** — first-time founder; if any word needs a glossary, the prototype fails on "easy to digest."
5. **Sam** — sales leader, numbers-driven but time-poor; wants the single thing to fix, obvious.

## The Done-Rule (single source of truth)

**Every one of the 5 prototypes scores 9/10 or higher from all 5 personas on all 3 axes — actionable insights, easy to digest, beauty of the design. 75 scores, all ≥ 9.**
Any prototype with any axis < 9 fails; revise only that prototype and re-score it. **Auto-fail, no scoring:** any prototype that drops a section, reorders the sections, restyles the insight widgets, or rebuilds the Suggested-actions cards — fix and re-submit.

---

## Loop control (how the modes actually run)

```
for step in 1..6:
    if step already passes its done-rule:  SKIP
    else:
        attempt = 0
        while not done-rule and attempt < 3:
            attempt += 1
            do the step
            if LOOP_TRAINING_MODE == ON:  pause → wait for Bjion's approval
        if still not passing after 3 attempts:  STOP + report the blocker
```

Global finish = **Step 6's done-rule holds AND all 75 panel scores ≥ 9 AND all four LOCKED items survive in all five prototypes.** Never declare done otherwise.
