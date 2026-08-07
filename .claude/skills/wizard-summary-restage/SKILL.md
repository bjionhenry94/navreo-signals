---
name: wizard-summary-restage
description: Restage the strategy-board wizard (Targeting → Icebreaker → Copy → Summary → Live) — move the pre-launch checks from Build to Live with done/pending progress, turn Build into a real-prospect Summary preview (5 ICP-qualified prospects, fully resolved emails, cycle-through), build 5 minimal Summary prototypes, panel-score them with 5 non-technical founders/sales leaders to 9/10 on all three axes, ship the winner into live strategy.html, and hand Bjion a verified link. Trigger phrases - "run the wizard summary restage", "restage the wizard", "continue the summary stage loop", "/wizard-summary-restage".
---

# Wizard Summary Restage — Orchestration Skill

## ⚙ LOOP TRAINING MODE: **OFF**   ← flip this line to ON to pause for approval at every step
- **ON:** pause at EVERY step and wait for Bjion's approval before continuing.
  Skip any step that already passes its done-rule. Only re-run steps that fail.
- **OFF:** run all steps end-to-end with no pauses, but keep every done-rule
  check and the retry cap.
- **Retry cap (both modes): 3 attempts per step.** On the 3rd failure, stop the
  loop and report exactly what failed and why — never loop forever.

## Goal
The wizard becomes a simple campaign **visualiser** that helps a non-technical
founder stage their idea. Stage order: **Targeting → Icebreaker → Copy →
Summary → Live**. Summary shows what up-to-5 real, ICP-qualified prospects
would actually receive (merge fields resolved from the mapping — never raw
`%signature%`/spintax). Live shows anyone it's shared with every pre-launch
check and what's already done. Language a 16-year-old understands. If a page
needs explaining, it's already too complicated.

## Ground truth (read before Step 1)
- ALL edits go in `~/navreo-signals/app/strategy.html` directly. **NEVER**
  build_live from wizard-template — it's stale and clobbers the live UI.
- The wizard machinery: `TABS` (~line 152), `CHECKS` (~154–162),
  `panelHTML()` (~line 224). Sidebar `.im-track` has 5 dots — keep exactly
  5 stages.
- Prototypes go in `~/navreo-signals/app/prototypes/summary-stage-p*.html`.
- Display-only: never write to Smartlead, never touch real send paths.
- Verify pages via mock-login on local signals; `?chrome=none` hides the rail.

## Steps

**S1 — Restage the tabs.** In `TABS`: swap Copy/Icebreaker so order is
Targeting, Icebreaker, Copy, Summary, Live. Rename the `build` tab label to
"Summary" (keep the `build` key so nothing else breaks).
*Done-rule:* page loads, pills read Targeting · Icebreaker · Copy · Summary ·
Live, clicking each renders without console errors.

**S2 — Move the checks to Live.** Delete the checklist from the old Build
panel. Rebuild the Live panel as the shared pre-launch view: every `CHECKS`
item plus "Signature added" and "ABC spell check", each with a done ✓ or
pending ○ state so anyone the page is shared with sees what we plan to do and
what's already done. Keep the not-live-yet banner and the plain-English tone.
*Done-rule:* Live shows all checks with visible done/pending states; a
16-year-old could read it cold; no explanatory paragraph needed.

**S3 — Summary data.** Give Summary real prospect previews: up to 5 prospects
per idea sourced from the idea's mapped lead data (Supabase cache /
contact_history / the run's list — whatever the mapping already holds),
qualified to sit as close to the described ICP as possible. Each preview =
the campaign email with EVERY merge field resolved for that person (name,
company, icebreaker, signature — no `%vars%`, no spintax). Cap at 5. If no
mapped data exists yet for an idea, fall back to clearly-representative
sample prospects — never a blank page.
*Done-rule:* for a real run, Summary returns ≤5 resolved previews per idea
and zero unresolved merge tokens appear in any rendered email.

**S4 — Five minimal prototypes.** Build 5 Summary-page prototypes at
`app/prototypes/summary-stage-p1..p5.html`, each pairing the targeting
summary with the resolved-email preview and a way to cycle through the ≤5
prospects. Minimal design: less explanation, more intuitive layout; distinct
approaches (e.g. inbox-style, card flip, side-by-side who+what, single hero
letter, filmstrip). House design system.
*Done-rule:* 5 prototypes open locally, all cycle through prospects, none
relies on a paragraph of instructions.

**S5 — Panel verify.** Score every prototype with 5 simulated non-technical
founders / sales leaders on: actionable insights, easy to digest, beauty of
design. *Done-rule:* at least one prototype scores **9/10 on all three axes
from all five panellists**. If none passes, take the top scorer, fix the
named weaknesses, re-score (counts toward the retry cap).

**S6 — Ship the winner.** Fold the winning Summary design into live
`strategy.html`'s Summary panel (direct edit, matching house CSS), commit,
push, confirm deploy via /api/version poll.
*Done-rule:* production strategy.html renders the new Summary + restaged
tabs + Live checks with no console errors.

**S7 — Verified hand-off.** Load the live board myself (mock-login locally
AND the production URL), confirm every stage renders, then report to Bjion
with the confirmed link, the panel scores, and one plain-English paragraph on
what changed. *Done-rule:* the link I send is one I watched load.

## Done (whole loop)
S1–S7 all pass their done-rules, the winning prototype hit 9/10 × 3 axes × 5
panellists, and Bjion has a verified live link. Then stop — no extra polish
passes.
