---
name: version-performance-uxlab
description: Orchestration loop that rebuilds the "Version performance" section of a campaign detail page (app/campaigns.html, Messaging tab — the live-from-Smartlead per-version table) into a picture-first hub a non-technical founder reads in seconds. Answers four jobs with visuals, not a table: which version books the most calls (tracing the email-1 variant a person saw even when the booking lands on email 2), which version needs the fewest sends per positive / per meeting (meetings matter most), positive & P+ reply-rate, and sends per version. Produces FIVE distinct prototypes. Per-version comparison on sends / positive-rate / meetings is LOCKED — it survives every prototype. Meetings-belong-to-the-step honesty is LOCKED — no faked variant-level attribution. Runs a 5-judge panel of non-technical founders + sales leaders and is not done until every prototype scores 9/10+ on actionable, easy-to-digest, and beautiful. Use when the user says "run the version performance uxlab", "rebuild the version performance section", "build the five version-performance prototypes", or "/version-performance-uxlab".
---

# Version Performance UX Lab 🧪

> ## ⚙️ LOOP TRAINING MODE  =  **ON**   (default)
> Flip this one line to `OFF` to run autonomously with no pauses. Nothing else changes.
>
> | Mode | Behaviour |
> |------|-----------|
> | **ON** (default) | Pause at **every step** and wait for the user's approval before continuing. **Skip** any step that already passes its done-rule. Only **re-run** steps that fail. Respect the retry cap. |
> | **OFF** | Run **autonomously**, no pauses. Still enforce **every done-rule** and the **retry cap**. |
>
> **Retry cap:** each step (and each prototype) may be attempted at most **3 times**. On the 3rd failure, STOP and report the blocker — never loop forever.

---

## The Goal
Rebuild the **Version performance** section — the Messaging tab's live-from-Smartlead per-version table on `https://navreo-signals.onrender.com/app/campaigns.html` (`#/c/<id>/messaging`) — into a **picture-first** hub. A non-technical founder opens it and, in seconds and with almost no reading, answers four questions:

1. **Which version is booking the calls?** Meetings are the prize. When a booking lands on a later email, still show the **email-1 version that person saw** — never a blank.
2. **Which version works hardest for the least?** Fewest **sends per positive** and fewest **sends per meeting** (meetings weigh most).
3. **How warm is each version?** **Positive** and **P+** reply-rate, side by side.
4. **How much did each version send?** Plain sends per version — the base every rate sits on.

Every answer is a **visual** (bar, ring, funnel, sparkline), not a number the user has to interpret. **If a metric needs a paragraph to explain, it is already too complicated — cut it or draw it.** Language a 16-year-old understands. No jargon.

Deliver **five distinct prototypes** of that section.

## LOCKED — do not change (every prototype keeps these)
- **Per-version comparison stays.** Every version remains comparable, version-against-version, on at least **sends, positive reply-rate, and meetings**. You may re-present these; you may not remove them or make comparison harder.
- **Meetings-belong-to-the-step honesty stays.** Smartlead attributes a booking to the email *step*, never to a variant. So:
  - You may attribute a meeting to a **version** ONLY by tracing the **actual version that lead was sent** (e.g. the email-1 variant a person saw before booking off email 2). That trace is real per-lead data.
  - If that trace isn't available, show meetings at the **step** with one honest line — never split a step's meetings across its versions by guesswork. A beautiful chart that invents variant-level attribution is an **auto-fail**.
- **Live-from-Smartlead truth stays.** Every number is the platform's own (`/api/cockpit/messaging`). Nothing invented. The "counters reset when a sequence is re-saved: read as since relaunch" caveat survives somewhere honest.

Anything else in the section is fair game.

## Must-haves (bake into every prototype)
1. **A verdict before the numbers.** Lead with a plain-English read — "Version B books the most calls: 6 meetings, and it needs the fewest sends to get one" — not a table the user decodes.
2. **Meetings are the hero.** The meetings answer carries the most visual weight and comes first. Efficiency is framed as **"sends to book one call"** and **"sends to earn one positive"** — a picture where *lower = better*, shown honestly (the code already reads `<300` sent as "early").
3. **The four jobs each have an obvious home** on screen — book-rate, efficiency, warmth (positive & P+), volume — none buried.
4. **Honest small sample.** A version with too little volume says **"too early"** instead of crowning a fake winner.
5. **Empty + error states.** Smartlead unreachable falls back to the daily mirror **calmly** (the UI already does this); no spinner-forever; a version with no data reads calm, not broken.
6. **Insight-card grammar** where a card is used: hero number + a chart + one caption + one action + a "why?" disclosure.

**Data you can rely on** (per version, from `/api/cockpit/messaging`): `step`, `label` (A / B / inline), `sent`, `replies`, `positives` (= Smartlead's "interested" mark), `bounces`; plus `meetings.by_step`, `meetings.total`, `meetings.unattributed`. **P+** = the hotter tier of positives (Call Booked / Meeting Request) from the reply archive — honour it only where the data honestly supports it (step-level, or per-lead-traced), otherwise show plain positive-rate and say so.

Design rules: **Navreo Design System** (`~/.claude/skills/navreo-design-system/`) — cream/ink, ONE orange accent, Acid Grotesk, **no emoji in the UI**. Plain simple English throughout. Non-technical founders and sales leaders are the judges.

## The Done-Rule (single source of truth)
**A panel of 5 non-technical founders + sales leaders each score every prototype 9/10 or higher** on THREE axes:
**(a) Actionable insights** — I know what's working and what to do next.
**(b) Easy to digest** — I get it in seconds, no explaining needed.
**(c) Beauty of the design** — it looks clean and premium.
- 5 prototypes × 5 judges × 3 axes = **75 scores. The loop is DONE only when all 75 ≥ 9.**
- Any prototype with any axis-score < 9 fails; revise **only that prototype** and re-score it.
- **Auto-fail, no scoring:** any prototype that loses per-version comparison, fakes variant-level meeting attribution, or invents numbers. Fix and re-submit.

---

## Steps (each has its own done-rule; skip if already passing)

**Step 1 — Capture the baseline.**
Pick a **real campaign that actually demonstrates all four jobs**: ≥2 versions on email 1 **and** ≥1 booked meeting (so the book-rate + trace jobs are real, not hypothetical). Read its live DOM (Browser pane, authed — mint the HMAC `navreo_session` cookie; DOM reads, not screenshots) of `#/c/<id>/messaging` and the `/api/cockpit/messaging?id=<id>` payload. Write down: every per-version field shown, how meetings render today (step-level, with the dot for repeat steps), what the founder must currently work out in their head to reach each of the four answers.
_Done-rule:_ a written before-state naming every per-version metric, the current meeting-rendering rule, the data source, and the specific mental work today's table offloads onto the user — plus the chosen campaign id and why it demonstrates all four jobs.

**Step 2 — Name the four answers against real data.**
Using this campaign's actual numbers, write the plain-English answer a founder should get for each job: which version books the most calls (and the email-1 version each booked lead saw, or an honest step-level statement if the trace is unavailable), which version is most efficient (sends per positive, sends per meeting), each version's positive & P+ reply-rate, and each version's sends. State the volume floor below which a verdict is not honest.
_Done-rule:_ the four answers exist in plain 16-year-old English for the real campaign, plus a stated small-sample floor and an explicit note on whether variant-level meeting attribution is traced or shown at the step.

**Step 3 — Build the five prototypes.**
Five genuinely distinct approaches to the same section — vary the *pattern*, not the paint. For example:
- **verdict-first** — one headline ruling on top ("B books the most calls, for the fewest sends"), versions underneath as visual evidence;
- **race track** — versions as horizontal bars racing on the metric the founder picks (meetings by default), worst pinned last with its "too early / losing" tag;
- **efficiency dial** — a ring per version for "sends to book one call" and "sends to earn one positive", tightest ring = winner;
- **book-rate funnel** — sent → positive → P+ → meeting per version, showing where each one leaks, with the email-1 trace feeding the meeting node;
- **head-to-head** — two versions side by side, winner/loser called on all four jobs, swap either side.

Every prototype keeps the LOCKED items, honours the must-haves, and handles empty / error / small-sample. Deliver as standalone previewable HTML hydrated with this campaign's **real** numbers, at `app/prototypes/version-performance-p1.html` … `-p5.html` (mock any fetch with a visible loading state).
_Done-rule:_ five prototypes render with no console errors; each keeps per-version comparison on sends / positive-rate / meetings; each answers all four jobs on screen with visuals; none fakes variant-level meeting attribution.

**Step 4 — Run the 5-judge panel.**
Score each prototype with five personas (mix of non-technical founders and sales leaders) on the three axes, 1–10 each. Capture the number + a one-line reason per axis per persona per prototype.
_Done-rule:_ 75 scores recorded with reasons.

**Step 5 — Revise the failures.**
For any prototype with any axis-score < 9, apply the panel's reasons and re-score (Step 4) — that prototype only. Respect the retry cap (3 attempts per prototype).
_Done-rule:_ all 75 scores ≥ 9.

**Step 6 — Hand over.**
One line + link per prototype, plus a one-line recommendation of the winner and why it best serves the four jobs for a non-technical founder. Live-verify anything claimed as shipped (DOM reads on the live host, not screenshots). Nothing is "done" until Step 5's done-rule holds.
_Done-rule:_ five prototype links delivered; winner named; all 75 scores ≥ 9 stated; LOCKED items confirmed intact in all five (comparison kept, no faked attribution, no invented numbers).

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
            if TRAINING MODE == ON:  pause → wait for approval
        if still not passing after 3 attempts:  STOP + report blocker
```
Global finish = **Step 6 done-rule holds AND all 75 panel scores ≥ 9 AND per-version comparison + meeting-honesty + live-truth survive in all five prototypes.** Never declare done otherwise.
