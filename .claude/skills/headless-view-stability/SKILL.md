---
name: headless-view-stability
description: Static orchestration skill that hardens the HEADLESS / SIDEBARLESS campaign view used by the Optimisations Workflow — the ?chrome=none campaigns board (app/campaigns.html + app/shell.js in ~/navreo-signals) and the optimise.html cockpit, live at navreo-signals.onrender.com. Fixes four owner-reported workflow issues — controls that depend on opening a new tab (impossible inside the Claude browser pane), campaign copy shown with raw spintax instead of a readable resolved version, a "Copy prompt" that falls back to a pop-up instead of instant clipboard, and the paste-a-prompt → auto-open-that-campaign chain needing a code review — then runs a 5-expert front-end/back-end efficiency panel that must vote the touched code 9/10+ before the loop can close. Every done-rule is verified on the LIVE UI with zero permanent actions (no leads deleted, nothing sent). Includes a Loop Training Mode toggle (ON by default). Use when the user says "run the headless view stability loop", "fix the optimisations workflow view", "the sidebarless page is buggy", or "/headless-view-stability". NOT the campaigns LIST bugs (campaigns-view-stability), NOT the detail-page bugs (campaign-detail-stability), NOT building the cockpit (campaign-optimise-cockpit).
---

# headless-view-stability

Harden the **headless campaign view** — the surface the Optimisations Workflow actually lives in: `app/campaigns.html?chrome=none` (+ hash deep-links `?chrome=none#/c/<id>`) and `app/optimise.html?c=<id>`, headless mode implemented in `app/shell.js` (`isHeadless()` :14, rail suppression :52). Repo `~/navreo-signals`, live at `navreo-signals.onrender.com`. Four fixed workflow fixes, one expert-panel quality gate. Static loop — fixed steps, each with a done-rule, Loop Training Mode controls pausing.

**The one constraint that shapes everything:** this view renders inside the Claude browser pane, which **cannot open new tabs**. Anything that relies on `target="_blank"` / `window.open` dead-clicks there. Prefer fluid in-page patterns (slide-overs, drawers, hash routes) or a click-to-copy link.

**Ship-and-verify-LIVE law.** iCloud reverts local edits and interruptions count as redeploys — treat every change as ship-then-verify on the live host. A local render, a source grep, or a green label is NEVER done-evidence; the only proof is the live rendered DOM / network panel. Push to the path Render builds from, wait for the redeploy (poll `/api/version`; mint the `navreo_session` cookie — sha256 of `SUPABASE_SERVICE_ROLE_KEY + ":navreo-session-v1"` from `~/.navreo-keys.env` — to pass the login gate), then verify live.

**No-permanent-actions law (audit & verify).** Never delete leads, never send messages, never write to Smartlead. Dismiss/ack/mark-done on a real optimisation IS a state change — exercise those only on a row you immediately revert, or on the demo/test client. Check `row.status` before anything near a send path.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for Bjion's explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that **fail** their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule (the panel gate in Step 5 caps at **3** optimise→re-vote rounds). On cap-hit, stop that step, record it FAILED with the reason and best result reached, keep going, surface it in the final report. Never silently exceed.

---

## THE GOAL

Working a campaign through the headless view is fast and unsurprising: no control silently does nothing because it wanted a new tab; campaign copy always appears as readable, spintax-free text first; "Copy prompt" puts the prompt on the clipboard instantly with no pop-up; and pasting a tool-generated prompt into a fresh chat reliably opens that exact campaign's page beside the chat — with the touched code voted **9/10+** by a five-expert efficiency panel.

---

## STEP 0 — Read-only audit + recreate (blocking)

Reproduce each issue on the **live** headless view before touching code, then attempt to re-create it a second time to confirm it isn't a one-off — all under the no-permanent-actions law.

- Open `navreo-signals.onrender.com/app/campaigns.html?chrome=none` and `app/optimise.html?c=<a real id>` in the browser pane. For each of the four issues below, record REPRO (with DOM read / screenshot / console evidence) or CANNOT-REPRO, twice.
- Known code anchors to check against the deployed build: new-tab escapes at `campaigns.html:3137`, `:3411`, `:3478` and `optimise.html:267` ("Open in Smartlead"); copy-prompt button `:3142`, handler `:4858–4904` with its `fallbackPopover` (the pop-up path — likely what fires inside the Claude pane, where `navigator.clipboard` is often denied); prompt builder STEP 0/STEP 1 string `:3066–3069`; sequence copy render paths (Messaging tab viewer + optimise.html) — confirm whether raw spintax `{a|b}` reaches the DOM.
- Also sweep generally: console errors, dead clicks, layout breaks at pane width — anything that slows the workflow gets recorded as a finding for Step 5's panel.
- Done-rule: all four issues have a twice-attempted repro verdict with live evidence, the anchors map to the source Render actually builds from, and any extra findings are written down.

---

## THE STEPS

### Step 1 — Nothing depends on a new tab
- In headless mode (`document.documentElement.classList.contains("headless")`), no control may rely on `target="_blank"` / `window.open`. External destinations (the Smartlead links) degrade to a click-to-copy affordance ("Link copied — open it in your own browser") or an in-page slide-over; internal destinations become hash routes / drawers. Normal-chrome behaviour for the team's real browsers stays as-is.
- Done-rule (LIVE): in the browser pane, clicking every formerly-`_blank` control in the headless board and cockpit produces a visible, useful result — zero dead clicks; audited with a DOM sweep showing no headless-active `_blank`/`window.open` path left.

### Step 2 — Copy reads human-first (no raw spintax)
- Wherever the headless view renders campaign copy (Messaging sequence viewer, optimise.html), show a **spintax-resolved version by default** (first branch of every `{a|b|c}`), with the raw spintax available behind a secondary toggle — never the other way round.
- Standing chat rule, baked here because the skill IS the workflow: after a "Copy prompt" handover is pasted into a chat, any copy Claude shows or writes for the campaign is presented **non-spintax first**; the spintax version follows only if it's actually needed for Smartlead.
- Done-rule (LIVE): open the copy of a campaign whose sequence contains spintax — the default rendering contains no `{…|…}` braces; the raw version is reachable but secondary.

### Step 3 — "Copy prompt" is instant, never a pop-up
- One click on "Copy prompt for Claude" → prompt on the clipboard + a brief inline "Copied ✓" flash on the button itself. Replace the `fallbackPopover` path with a silent fallback (hidden textarea + `execCommand("copy")`, per the existing helper at `:4480`) so even where `navigator.clipboard` is denied — the Claude pane — no pop-up ever appears.
- Done-rule (LIVE): in the browser pane, click "Copy prompt" — the button flashes Copied, no popover/modal/new element beyond the flash appears, and the clipboard (or the selection fallback) demonstrably holds the full prompt.

### Step 4 — Paste-a-prompt auto-opens the campaign (review the existing code)
- This is reported working — the job is a **code review + live confirmation**, not a rebuild. The chain: `actionCardHTML()`'s prompt string (`:3066–3069`, "STEP 1 - open my optimisation cockpit… ") must point at the real cockpit URL for that campaign; deep-links must keep `?chrome=none` **before** the `#` hash (per the /navreo-campaigns skill contract); the opened page must hydrate that campaign with no extra navigation.
- Fix any drift found (wrong URL shape, stale skill name in the embedded STEP line, hash-order bugs). If you change the mechanism, update the builder string and the /navreo-campaigns skill in the same change — they live in lock-step.
- Done-rule (LIVE): copy a real prompt from the live board, simulate the paste in a fresh context — the referenced URL opens directly to that campaign, headless, hydrated, in one move.

### Step 5 — Five-expert efficiency panel (quality gate)
- Convene **5 experts** (3 front-end, 2 back-end) as parallel subagents. Each independently audits the code touched by Steps 1–4 plus the headless plumbing around it (`shell.js` headless mode, the copy/clipboard helpers, the prompt builder) for efficiency, correctness, and maintainability, returning a **score /10** with top issues. Feed them Step 0's extra findings too.
- If any expert scores **< 9**: apply the highest-value fixes, redeploy, re-verify Steps 1–4 still pass live, re-vote. Max **3** optimise→re-vote rounds.
- Done-rule: **all five experts score ≥ 9/10** on the final vote, with the four live done-rules still passing after the last optimisation.

---

## THE VERIFICATION (all LIVE on navreo-signals.onrender.com — DOM/network evidence, not source, not a label)

1. Zero dead clicks in the browser pane; no headless-active new-tab dependency remains.
2. Spintax never renders by default; resolved copy first, raw behind a toggle.
3. "Copy prompt" = instant clipboard + inline flash; no pop-up in the pane.
4. A real copied prompt opens its exact campaign, headless and hydrated, in one move.
5. Panel verdict: five experts, all ≥ 9/10, recorded with scores.

All five verified live, or it isn't done.

---

## HOW TO RUN

1. Read the mode line above. If **ON** (default), do Step 0 first, then one step at a time with a stop for approval after each; skip any step whose LIVE done-rule already passes. If **OFF**, run Step 0 then Steps 1–5 in order without pausing.
2. For each step: edit the source Render builds from (`app/campaigns.html`, `app/optimise.html`, `app/shell.js`; `app/server.py` only if truly needed), push, wait for the redeploy (`/api/version`), then check the done-rule against the live host with `read_page` / screenshot / console / network. Retry up to 3× on live-failure, then mark FAILED and continue.
3. Interruptions = redeploys: re-confirm the live page after any interruption before calling a step done.

## OVERALL DONE-RULE

- All four fixes in place, the panel at 9/10+ across all five voters, and each of the **five live verifications** passing on `navreo-signals.onrender.com`.
- No permanent actions at any point: no leads deleted, nothing sent, no un-reverted dismiss/ack/done on real client data.
- Final report: one line per step (0–5) — DONE / SKIPPED (already passed) / FAILED (reason + retries used) — plus the five verification ticks and the five panel scores.
