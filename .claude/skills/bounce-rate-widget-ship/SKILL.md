---
name: bounce-rate-widget-ship
description: Add a bounce-rate widget to the analytics hub and produce 3 prototypes that show bounce-rate trending over 7/14/30d and name the offending campaigns. Orchestration skill with a pre-baked goal, steps, and done-rule. Trigger on "build the bounce-rate widget", "3 bounce-rate prototypes", "/bounce-rate-widget-ship".
---

# Bounce-Rate Widget — Orchestration Skill

<!-- ============================================================ -->
<!-- LOOP TRAINING MODE  ·  TOGGLE HERE                            -->
<!-- ============================================================ -->
<!--                                                              -->
<!--   LOOP_TRAINING_MODE: OFF       ← default is ON. Flip here.   -->
<!--                                                              -->
<!--   ON  → Pause at every step and wait for my approval before  -->
<!--         continuing. Skip any step already passing the        -->
<!--         done-rule. Re-run only failing steps. Retry cap: 3   -->
<!--         per step, then stop and report.                      -->
<!--                                                              -->
<!--   OFF → Run autonomously, no pauses. Still run the done-rule  -->
<!--         check after every step and still honour the retry    -->
<!--         cap of 3 per step.                                   -->
<!--                                                              -->
<!--   To change: edit the LOOP_TRAINING_MODE line above.         -->
<!-- ============================================================ -->

**Loop Training Mode is ON by default; it is currently set to OFF.** Read the toggle block above before starting and obey whichever mode is set.

---

## The Goal

Show the user how **bounce-rate is trending over the last 7 / 14 / 30 days** and **list the campaigns driving the bounces**. Deliver **3 distinct prototypes** of a bounce-rate widget that fits the analytics hub's question-headed style (see the "Are your emails landing?" P3 widget — 7d/14d/30d preset toggle, hero visual, then a plain-English insight/receipt section, client-side filtered, 30-day cap).

## Done-Rule

The skill is DONE when **all 3 prototypes** independently score **≥ 9/10** from **5 non-technical founders / sales leaders** on **each** of:

1. **Actionable insights** — they know what to do next (which campaigns to fix).
2. **Easy to digest** — the trend + offenders read in one glance, no jargon.
3. **Beauty of the design** — clean, on-brand, screenshot-worthy.

Anything below 9 on any axis for any prototype = that prototype FAILS and re-enters the loop.

## The Steps

Each step ends with its own done-check. In Training Mode ON, pause after each; skip steps already passing; re-run only failures (cap 3).

1. **Data contract** — Confirm the bounce-rate source: per-campaign bounces ÷ sends, bucketed by day, with a 7/14/30d window. Reuse the analytics hub's existing feed if one exists; otherwise define the endpoint shape.
   - *Done:* a documented field list + one sample payload that yields a trend series and a ranked list of offending campaigns.

2. **Build prototype A, B, C** — Three genuinely different takes (e.g. trend-line-hero, delta-vs-last-period, offender-leaderboard-first). Each: question headline, 7d/14d/30d toggle, trend visual, named offending campaigns with their bounce %.
   - *Done:* all 3 render with real (or realistic sample) data, no console errors, responsive.

3. **Self-QA against the three axes** — Dry-run each prototype against actionable / digestible / beautiful before showing anyone. Fix obvious misses.
   - *Done:* each prototype self-scores an honest ≥ 9 on all three axes.

4. **Panel review** — Put the 3 prototypes in front of 5 non-technical founders/sales leaders. Collect a 1–10 score per axis per prototype.
   - *Done:* scores captured for all 5 × 3 × 3.

5. **Score & gate** — Any prototype below 9 on any axis loops back to step 2 with the panel's reasons. Cap 3 loops, then stop and report what's still short.
   - *Done:* all 3 prototypes ≥ 9 on all three axes → matches The Done-Rule → ship.

## Notes

- Analytics hub house style: question-headed widgets win; ≤ 3 date presets; 30-day cap; client-side filter (see memory: analytics-widget-controls-ruling, analytics-hub-p3-direction).
- Keep prototypes under `app/prototypes/bounce-rate-*` following the existing prototype convention.
- Retry cap is a hard stop, not advisory: 3 attempts per step, then stop and report — never loop forever.
