---
name: hiring-roles-autogen
description: Upgrade the hiring wizard in the Navreo signals tool (app/campaigns.html + app/server.py) so step 1 auto-generates the "Roles they're hiring for" trigger list AND the "Who we email" decision-maker list from the client's ICP, with a "Generate more" button on each field. One static orchestration loop — build auto-generate, build generate-more, prove the preview net widens, then a panel of 5 simulated users must agree it is quicker and easier to ideate more roles and decision makers to target based on the client's ICP. Use when the user says "auto-generate hiring roles", "run the role autogen", "widen the hiring preview net", or "/hiring-roles-autogen".
---

# hiring-roles-autogen

Make the hiring wizard ideate FOR the user: open step 1 and the trigger roles + decision-maker roles are already filled from the client's ICP, with a one-click "Generate more" to widen the net. Static loop, fixed done-rule.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by user 2026-07-06)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for the user's explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** max **3** full panel-rounds. Any single step retries **max 3** times. On cap-hit, stop and report the best result + what's still failing. Never silently exceed.

---

## THE GOAL

Widen the net of hiring-signal previews by targeting more trigger roles and more decision makers — without the user having to think them up. The wizard should propose; the user should only prune.

- **Auto-generate target:** opening hiring step 1 inside a campaign shows **≥ 5 trigger roles** and **≥ 4 DM roles** generated from the client's ICP, zero typing.
- **Generate-more target:** each click appends **~10 fresh, non-duplicate** suggestions (user, 2026-07-06), never re-suggests anything previously declined, and skews toward the flavour of what was kept.
- **Learning:** a removed chip = declined, the list at "Find them" = kept; both persist per client and feed every later suggestion call.
- **Rollout target (user, 2026-07-06):** the same auto-fill + 🪄 Generate more + learning pattern on every setup wizard's ideation fields, not just hiring.
- **Net target:** a preview run with the generated set matches **more companies/people** than the old 2-role default on identical filters.
- **Panel target:** **5/5 simulated users agree** it is quicker and easier to ideate more roles and decision makers to target based on the client's ICP.

---

## THE ANCHORS (don't rediscover)

- Wizard markup: hiring branch of `drawSrc()` step 1, `app/campaigns.html` ~line 2135 — inputs `sw-titles` (trigger, defaults `"Head of Sales, VP Sales"`), `sw-dm` (decision makers, required), `sw-neg` (exclusions).
- ICP context: the campaign draft (`/api/campaign-drafts`) carries `name`, `goal`, `client_id`; the wizard knows its campaign via `sw.campaignId`. Generate from goal + client; if the draft has no goal, fall back to the campaign name and say so in the UI.
- Server already runs LLM prompts in `app/server.py` (e.g. the buyer-keyword prompts ~line 533) — add one small endpoint in the same style, e.g. `POST /api/role-suggest` returning `{trigger_roles: [], dm_titles: []}`. Trigger roles = what the company is HIRING; DM roles = who we EMAIL there. Never mix the two lists.

---

## THE STEPS

### Step 1 — Auto-generate on open
Done-rule: opening hiring step 1 on a campaign with ICP context shows ≥5 trigger roles + ≥4 DM roles pre-filled, each removable, with nothing typed.
- Endpoint first, then wire the wizard: on first draw of the hiring step, call it and fill both fields (chips or comma-list — match the wizard's existing look, plain English labels).
- User edits always win: never overwrite a field the user has touched; regenerate only on explicit click.

### Step 2 — "Generate more" on each field, with decline/keep learning
Done-rule: clicking 🪄 Generate more twice on each field appends ~10 new suggestions per click with zero duplicates against the field OR anything previously declined; removing a chip records a decline, advancing past step 1 records the kept list; both persist per client and reach the LLM on the next call. Field stays editable.
- Pass current chips + the client's declined history as the exclusion set; pass kept history as positive signal.
- Cap the visible list at ~40 per field so the wizard never becomes a wall.

### Step 3 — Roll out to every setup wizard
Done-rule: the same auto-fill + 🪄 + learning pattern works on each wizard's ideation fields — companies (buyer-type keywords), lookalike (ideal-company description), engagement (warm-lead roles + include topics). CSV has nothing to ideate — skip it. Hiring behaviour unchanged by the rollout.

### Step 4 — Prove the net widens
Done-rule: on the same countries/size/recency filters, a preview with the generated role set returns a match count ≥ the old `"Head of Sales, VP Sales"` default — verified with one real preview probe each, numbers logged.
- Preview is free (per the wizard's own promise) — but run exactly one probe per variant, no pagination.

### Step 5 — Panel of 5 simulated users
Done-rule: 5 tester transcripts captured; each tester, given a real client ICP (pick from Amplifyy / Arnic / Navreo drafts), walks the wizard cold and answers: "Was it quicker and easier to ideate more roles and decision makers to target based on the client's ICP?" — agree/disagree + friction notes + what they pruned.
- Personas span non-technical → power-user (VA, founder, ops manager, sceptical CMO, junior SDR).
- Simulate faithfully — a confused persona must actually get stuck, not be rescued.

### Step 6 — Score, log, decide
Done-rule: this round's panel verdicts + preview-net numbers written to `HIRING-ROLES-AUTOGEN-<date>.md` (verbatim friction, the fix list).
- **If 5/5 agree AND Steps 1-4 pass → DONE.** Report and stop.
- **Else** → apply the top friction fixes, then loop back to Step 5 (earlier steps that still pass → skip). Respect the 3-round cap.

---

## THE DONE-RULE (single source of truth)

> Step 1 auto-fills ≥5 trigger + ≥4 DM roles from the client's ICP, 🪄 Generate more appends ~10 unique suggestions on demand (declined history never resurfaces, and the pattern is live on all setup wizards), the generated set previews at least as wide a net as the old default, **and all 5 panel users agree it is quicker and easier to ideate more roles and decision makers to target based on the client's ICP.**

Anything less = not done. On the 3-round cap, stop and report the gap honestly — do not declare done.

---

## GUARDRAILS
- Two lists, two meanings: trigger roles (they're hiring) vs DM roles (we email). A suggestion landing in the wrong list is a Step 1/2 failure.
- Scope: the setup wizards only — the campaign wizard, Leads tab, and push flow stay untouched.
- Cost: previews only, one probe per variant, no lead pulls, no credits burned on enrichment.
- Honesty: net-widening is proven by real probe counts, not estimates.
