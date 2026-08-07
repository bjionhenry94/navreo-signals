---
name: losing-versions-uxlab
description: Orchestration loop that redesigns the "Losing versions you can switch off now" card (the #vaw4 block on app/deliverability.html) into a picture-first insight a non-technical founder reads in seconds. Each flagged loser stops being a bare checkbox row and becomes a tiny data-visual that answers two things at a glance — how this version is performing VERSUS the winning version on the same step, and a one-click link to the actual campaign — while keeping the one-batch switch-off action fully working. Produces THREE minimal prototypes and is not done until 5 non-technical founders + sales leaders each score every prototype 9/10 on actionable insights, easy to digest, and beauty of design. Use when the user says "run the losing versions uxlab", "redesign the switch-off card", "build the losing-versions prototypes", or "/losing-versions-uxlab".
---

# Losing Versions UX Lab 🧪

> ## ⚙️ LOOP TRAINING MODE  =  **OFF**   (default is ON)
> Flip this one line to `OFF` to run autonomously with no pauses. Nothing else in this file changes.
>
> | Mode | Behaviour |
> |------|-----------|
> | **ON** (default) | Pause at **every step** and wait for my approval before continuing. **Skip** any step that already passes its done-rule. Only **re-run** steps that fail. Respect the retry cap. |
> | **OFF** | Run **autonomously**, no pauses. Still enforce **every done-rule** and the **retry cap**. |
>
> **Retry cap:** each step (and each prototype) may be attempted at most **3 times**. On the 3rd failure, STOP and report the blocker in plain English — never loop forever.
>
> _To change it later: edit the word `ON` above to `OFF` (or back). That's the only knob._

---

## 🎯 The Goal
Redesign the **"Losing versions you can switch off now"** card — the `#vaw4` block on `https://navreo-signals.onrender.com/app/deliverability.html` — from a list of bare checkbox rows into a **picture-first** card. A non-technical founder glances at each flagged loser and instantly gets two things:

1. **How is this version doing versus the rest?** Show the loser next to the **winning version on the same email step** — a tiny visual (bar, ring, or split) where it's obvious *this one is losing and by how much*. Never a number they have to decode.
2. **Take me to the campaign.** One obvious tap opens that campaign's Messaging tab (`#/c/<id>/messaging` on `campaigns.html`) so they can see it in full.

Everything else the card does today — pick some, confirm, switch them all off in one batch — **still works**. We are re-dressing the card into an insight, not rebuilding the plumbing.

**Two live truths this card MUST honour (added 2026-08-02, from Bjion at the wheel):**
- **Client-scoped.** The card follows the page's client filter (`state.client`). Switch to Amplifyy → only Amplifyy's flagged losers show (and its "versus the rest" is Amplifyy-only). Today the live `#vaw4` ignores the filter and shows every client's losers — that is a bug the redesign fixes. Each notification carries `client` / `client_id` to filter on. Per-client empty state: "No losing versions for <client> right now."
- **Freed traffic goes to the WINNER, not "the others".** Switching a loser off must push its distribution to the **best-performing version on that step** (the same winner the card names), not spread it proportionally across all siblings. The card copy + confirm modal say exactly where it goes ("Version D's 30% moves to Version C, your best"). The live server action must actually do this (`_disable_variant_pcts` → redistribute-to-winner, behind the same id-intact + post-verify save).

**Feel: minimal.** Less explanation, more intuitive design. *If it needs explaining, it's already too complicated.* Language a 16-year-old understands. No jargon.

Deliver **three distinct prototypes** of that card.

## 🔒 LOCKED — never break these (every prototype keeps them)
- **The switch-off action stays whole.** Select losers → confirm → one batch `POST /api/notifications/{nid}/execute {action:"disable_variant", confirm:"DISABLE"}`. The DISABLE confirm gate, the "last live version on its step is **refused**, never silently skipped" behaviour, and the id-intact save all survive. A pretty card that can't actually switch a version off is an **auto-fail**.
- **Every number is real.** Rows come from `GET /api/notifications?slim=1` filtered to the optimiser's disable calls. The loser's stats and the "versus the rest" comparison come from that payload's own `variants` array (all versions on the step) — or the campaign's `/api/cockpit/messaging?id=<cid>` where richer stats are needed. **Nothing invented.** No faked win-rates.
- **Honest empty + small sample.** No losers flagged → the calm "nothing to switch off" line stays. A version with too little volume to judge says **"too early"** — it is never dressed up as a confident loser.
- **The comparison is like-for-like.** "Versus the rest" means the **winning sibling on the SAME email step** (same audience, same position in the sequence). Never compare a loser against a different step or a different campaign.

## ✅ Must-haves (bake into all three)
1. **Two answers, no reading.** For each loser: (a) a visual of *this version vs the winning sibling* on the metric that matters (positive-reply rate first; sends as the base), and (b) an obvious link to the campaign. Both readable in one glance.
2. **Lower = losing, shown as a picture.** The losing version should *look* smaller/behind — a bar that's clearly shorter, a ring that's clearly emptier — so the eye lands on "this one's the problem" before any word is read.
3. **The batch action keeps its home.** Select + "Switch off selected (n)" + confirm modal remain, and read cleanly inside the new visual layout.
4. **Minimal.** One orange accent, generous space, no gradients/glass/emoji. A founder should feel calm, not audited.
5. **States handled:** empty (nothing flagged), loading, error (couldn't load calls → calm retry line), and "too early" per version.

**Data you can rely on** (per flagged loser, from `/api/notifications?slim=1`): `id` (nid), `campaign_id`, `campaign_name`, `title` (→ email step + version label via `Variant call: Email N Var X`), `suggested_action`, `status`, and `variants` — the array of **every version on that email step**, each with `email`, `variant`, `sent`, `positives`. The flagged loser is the one matching the title's step+label; the **winner** for "vs the rest" is the best-performing sibling in that same array. Where the array is thin, enrich from `/api/cockpit/messaging?id=<cid>`.

Design rules: **Navreo Design System** (`~/.claude/skills/navreo-design-system/`) — cream/ink, ONE orange accent, Acid Grotesk, **no emoji in the UI**. Plain simple English. Non-technical founders and sales leaders are the judges.

## 🏁 The Done-Rule (single source of truth)
**A panel of 5 non-technical founders + sales leaders each score every prototype 9/10 or higher** on THREE axes:
- **(a) Actionable insights** — I can see what's losing and I know what to do.
- **(b) Easy to digest** — I get it in seconds, no explaining needed.
- **(c) Beauty of the design** — clean, calm, premium.

3 prototypes × 5 judges × 3 axes = **45 scores. The loop is DONE only when all 45 ≥ 9.**
Any prototype with any axis-score < 9 fails; revise **only that prototype** and re-score it.
**Auto-fail, no scoring:** any prototype that loses the working switch-off action, fakes a comparison number, or compares against the wrong step. Fix and re-submit.

---

## 🪜 Steps (each has its own done-rule; skip any that already passes)

**1 · Baseline.** Read the live card: the `#vaw4` block in `app/deliverability.html` and a real `/api/notifications?slim=1` payload (authed Browser-pane DOM read — mint the `navreo_session` cookie; see memory `signals-live-verify-recipe`). Write down exactly what a founder sees today (bare checkbox rows: name, "Email N · Version X · campaign id", sent · pos) and the two things they CAN'T see today — the versus-the-rest comparison and a campaign link — plus which real flagged losers exist to hydrate the prototypes.
  - *Done-rule:* a written before-state naming every field the card shows today, confirmation of the data source + action endpoint, and ≥1 real flagged loser (with its `variants` array) captured to build against.

**2 · Name the two answers against real data.** For a real flagged loser, write the plain-English lines a founder should get: "Version C is winning replies 3-to-1 over Version D on Email 1 — switch D off" and "Open the campaign →". Confirm the winning sibling is on the **same email step**, and state the volume floor below which the honest label is "too early" not "loser".
  - *Done-rule:* both answers written in 16-year-old English for a real loser, winner-sibling confirmed same-step, small-sample floor stated.

**3 · Build the three prototypes.** Three genuinely distinct, minimal takes on the same card — vary the *pattern*, not the paint. For example:
  - **head-to-head bar** — each loser row becomes two short bars (loser vs winning sibling) on positive-rate; loser clearly shorter, campaign link on the right.
  - **loser card** — each loser is a small card: hero "losing by X" + a tiny split visual + "open campaign" + its checkbox; the batch bar sits under the stack.
  - **traffic-light list** — a tight list where each loser shows a red dot, a one-glance mini-bar vs the winner, and a chevron that opens the campaign; select-all + switch-off pinned at the base.

  Each keeps the LOCKED items and all must-haves, hydrated with the **real** flagged loser(s), with empty/loading/error/too-early states. Standalone previewable HTML at `app/prototypes/losing-versions-p1.html` … `-p3.html` (mock the fetch with a visible loading state; keep the real endpoint names in comments).
  - *Done-rule:* three prototypes render with no console errors; each shows loser-vs-winning-sibling as a visual + a working campaign link + the intact select/confirm/batch switch-off flow; none fakes a number or compares across steps.

**4 · Run the 5-judge panel.** Score each prototype with five personas (mix of non-technical founders + sales leaders — e.g. first-time founder, VP sales, agency operator, skeptical COO, brand-led founder) on the three axes, 1–10, with a one-line reason per axis per persona per prototype.
  - *Done-rule:* 45 scores recorded with reasons in the session file.

**5 · Revise the failures.** For any prototype with any axis-score < 9, apply the panel's reasons and re-score (Step 4) — that prototype only. Respect the retry cap (3 attempts per prototype).
  - *Done-rule:* all 45 scores ≥ 9.

**6 · Hand over.** One line + link per prototype, a one-line recommendation of the winner and why it best serves a non-technical founder, and confirmation the LOCKED items survive in all three. Live-verify anything claimed as shipped (DOM read on the live host, not screenshots). Save the session record + update memory (winner, score, any live commit). Per memory `updates-need-verified-link`, every update to Bjion carries a link I've confirmed loads on his machine.
  - *Done-rule:* three prototype links delivered; winner named; all 45 scores ≥ 9 stated; LOCKED items confirmed intact; session file + memory written.

---

## 🔁 Loop control (how the modes actually run)
```
for step in 1..6:
    if step already passes its done-rule:  SKIP  (say so, move on)
    else:
        attempt = 0
        while done-rule not met and attempt < 3:
            attempt += 1
            do the step
            if TRAINING MODE == ON:  pause → wait for my approval
        if still not passing after 3 attempts:  STOP + report the blocker
```
**Global finish = Step 6's done-rule holds AND all 45 panel scores ≥ 9 AND the switch-off action + real-data + same-step-comparison survive in all three prototypes.** Never declare done otherwise.

## 🧭 Runbook quick-reference
- **Card today:** `~/navreo-signals/app/deliverability.html`, block `#vaw4` (search `variant-action-wire P4`).
- **Prototypes:** `~/navreo-signals/app/prototypes/losing-versions-p{1..3}.html`.
- **Rows source:** `GET /api/notifications?slim=1` → keep `finding_type==="variant_call"` + `/disable/i` in `suggested_action` + `status!=="actioned"` + title matches `Variant call: Email N Var X`.
- **"Versus the rest":** the notification's own `variants` array (all versions on the step) → winner = best sibling; enrich from `/api/cockpit/messaging?id=<cid>` if thin.
- **Switch-off action (keep working):** `POST /api/notifications/{nid}/execute {action:"disable_variant", confirm:"DISABLE"}`; last-live version refused server-side.
- **Campaign link:** `#/c/<campaign_id>/messaging` on `campaigns.html` (bare `#/c/<id>` = Overview — see memory `campaigns-overview-hash-shape`).
- **Auth for live checks:** mint `navreo_session` cookie, poll `/api/version` (memory `signals-live-verify-recipe`).
