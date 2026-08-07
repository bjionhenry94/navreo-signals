---
name: campaign-optimise-cockpit
description: Static orchestration skill that builds ONE simplified "optimisation cockpit" — a stripped-back version of the campaign detail page (renderDraftCampaign in app/campaigns.html) that (1) pins the ONE optimisation you were handed so you never forget which campaign you're on, (2) shows the whole campaign via the same header + Overview/Messaging/Leads tabs so you have full context in one place, and (3) lets you mark that optimisation done in one click. It opens in the browser as a dashboard the moment the tool's "STEP 0 — Campaign Navreo-<id> …" handover prompt is pasted into a new chat. Built and scored as a prototype in app/prototypes/, verified by 5 non-technical founder/sales-leader personas at 9/10+, with a Loop Training Mode toggle (ON by default). Use when the user pastes a "Campaign Navreo-<id> … Smartlead campaign <id> … Stage everything for my approval" optimisation handover, or says "open the optimisation cockpit", "build the campaign optimise dashboard", "run the optimise cockpit", or "/campaign-optimise-cockpit".
---

# campaign-optimise-cockpit

Build **ONE** simple, beautiful "optimisation cockpit": a stripped-back view of the campaign detail page that reminds you which optimisation you're on, shows the whole campaign for context, and lets you tick it done — and pops open as a dashboard the instant the tool's handover prompt lands in a new chat.

Written for a non-technical founder. Every word on the page reads like a smart 16-year-old wrote it — no jargon, no tool names, no shop talk.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that **fail** their done-rule.
- Retry cap still applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

When the tool's handover prompt is pasted into a fresh chat, the browser **auto-opens a single dashboard** for that one campaign. On it you can, in one glance: (a) see **which optimisation** you're meant to do and why — pinned, plain-English, always visible; (b) see the **whole campaign** through the familiar header + Overview / Messaging / Leads tabs, so you have every bit of context in one place; and (c) hit **one button to mark it done**. Nothing else — no other campaigns' insights, no other optimisations, no clutter that makes you forget which job this is.

---

## GROUND TRUTH (verified anchors — the cockpit reuses what already exists)

- **The optimisation you were handed is already stored.** Each handover is an `optimiser_notifications` row keyed by `campaign_id`; the pasted "STEP 0 … Stage everything for my approval" text **is** that row's `claude_prompt`. Fetch the single row (with its prompt) via `GET /api/notifications/{id}`; find it for a campaign via `GET /api/notifications?campaign_id=<id>&status=new` (server.py:2697, 2722). That row's `id` is the **nid** you mark done.
- **Mark done already has a path.** `PATCH /api/notifications/{nid}` with `{"status":"actioned"}` → `update_notification_status` stamps `actioned_at` (server.py:2744, 18528–18544). Statuses: `new · acknowledged · actioned · dismissed · approved`. **"Done" = actioned.**
- **The detail view to mirror** is `renderDraftCampaign` in `app/campaigns.html`: header + a 3-tab nav — **Overview** (`:3411`), **Messaging** (`:3412`), **Leads** (`:3413`) — with panels at `:3417 / :3470 / :3483` and tab-switching at `:4630–4631`. Data comes from `/api/campaign-scorecard`, `/api/campaign-platform-leads`, `/api/campaign-repliers`.
- **Dashboard look = no sidebar.** `?chrome=none` (alias `?headless=1`) strips the app rail and Tasks chrome (shell.js:14, :784) — that is the clean, single-purpose dashboard frame.
- **Prototype home:** `app/prototypes/` — standalone, fixture-driven HTML, iterated then migrated into the live page (the house uxlab pattern).

---

## THE STEPS

### Step 0 — Read the optimisation you were handed (blocking gate)
Parse the pasted handover: the **campaign id** (from "Campaign Navreo-**<id>**" / "Smartlead campaign **<id>**"), the **campaign name**, the **one-line directive** (what to actually do), and the **context line** (sends / replies / positives %). Confirm the matching `optimiser_notifications` row (`campaign_id`, `status=new`) — its `claude_prompt` is the pasted text and its `id` is the **nid**.
- Done-rule: you can state the campaign id, a one-sentence plain-English version of the directive, the context numbers, and the nid. If no matching row exists, say so and treat the pasted text as the source of truth.

### Step 1 — Build ONE cockpit prototype
Create **`app/prototypes/optimise-cockpit-p1.html`** — standalone, fixture-driven, in the `?chrome=none` (no-sidebar) frame. It mirrors the real detail: a **read-only header** (campaign name + status + the headline stats) and the **same 3-tab view** — Overview / Messaging / Leads — that `renderDraftCampaign` shows, tabs switching client-side. Plain 16-year-old English throughout.
- **Keep the real per-tab content** — the tabs are how the founder gets full context. Messaging keeps the **Version performance** table (Email · Version · Sent · Replies · Positives · 1-per · Meetings) **and the read-only sequence viewer** (subjects/bodies with `{{variables}}`), exactly like the live view. The ONLY thing we strip is the Overview's *other* optimisations / insights / suggested-actions clutter — never legitimate tab detail.
- Done-rule: the prototype renders the header and all three tabs switch and show fixture content (Messaging shows the version table + sequence), with no app sidebar — confirmed in the browser (read_page / screenshot), never from source.

### Step 2 — Pin the "You're working on" reminder
A **sticky reminder** above the tabs: campaign name + the **one-line plain-English directive** + the context numbers (sends / replies / positives). This is the **only** optimisation anywhere on the page.
- **It must be minimisable.** A collapse control shrinks it to a slim one-line bar (kick + clamped job + expand chevron) so there's room to navigate the campaign; expanding restores it. Even collapsed, it still says which optimisation you're on.
- Done-rule: the reminder is visible on **every** tab, states **this exact** optimisation, **collapses/expands** on click, and **NO** other optimisation / insight / notification blocks appear anywhere on the page (that clutter is the whole thing we're removing).

### Step 3 — One-click "Mark done"
A single, obvious button: **"Mark this optimisation done."** In the prototype, clicking it flips the reminder to a ✓ **Done** state. Bake the live contract into the file as a comment: done → `PATCH /api/notifications/{nid}` `{"status":"actioned"}`.
- Done-rule: the button is present and unmistakable, flips to a clear Done state on click, and the live endpoint contract is documented in the file.

### Step 4 — Auto-open as a dashboard on paste (the prompt↔skill handshake)
Pasting the handover into a new chat must **open the browser to this cockpit for that campaign in one move** — no hunting. This only fires reliably if the handover prompt *tells* the agent to open it, so the two live in lock-step:
- **The copy-prompt builder embeds the trigger.** `app/campaigns.html` → `actionCardHTML()` → the `var prompt = "STEP 0 - before anything else… set-session-title …"` string now carries a **`STEP 1 - … run the campaign-optimise-cockpit skill for Smartlead campaign <id> …`** line. That embedded line is what makes the window open on paste. If you change the skill name or the open mechanism, update that builder string in the same change.
- **The live page is shipped.** `app/optimise.html?c=<campaign_id>` (served by the tool) is the real, data-driven cockpit — it reads `/api/notifications?campaign_id=<c>` (or `?id=<nid>`), picks the primary open optimisation, and renders the reminder + winning-version chart + Overview/Messaging/Leads live; mark-done PATCHes `/api/notifications/{id}` `status=actioned`. The copy-prompt STEP 1 opens exactly this URL. `app/prototypes/optimise-cockpit-p1.html` is the design reference only.
- Done-rule: pasting the tool-generated handover into a fresh chat lands the browser on `optimise.html?c=<id>` for the handed campaign with the reminder + tabs already hydrated — one action, no extra navigation.

### Step 5 — Score it with 5 non-technical reviewers (the gate)
Recruit/simulate **5 personas — non-technical founders and sales leaders** (not engineers). Each scores the cockpit 1–10 on **Actionable insights**, **Easy to digest**, and **Beauty of the design**, with one line of why.
- Done-rule: **mean ≥ 9.0 on each of the three axes** across the 5 reviewers, with **no single axis-score below 8**. If it misses, apply the fixes the reviewers named and re-score (retry cap). On cap-hit, record FAILED with the lowest axis + the fixes still owed.

---

## THE VERIFICATION (all against the actually-rendered cockpit, not the source)

1. Opens as a **no-sidebar dashboard** for the handed campaign in one action.
2. The **one optimisation** is pinned, plain-English, visible on every tab.
3. The **whole campaign** is there via header + Overview / Messaging / Leads — full context, one place.
4. **One-click Mark done** works (prototype flip; live `PATCH …status=actioned` contract documented).
5. **No other** optimisations / insights / campaigns clutter the page.
6. **5 non-technical reviewers** score **9/10+** (mean per axis, none below 8) on Actionable · Easy to digest · Beauty.

All six, or it isn't done.

---

## HOW TO RUN

1. Read the mode line above. If **ON** (default): do **Step 0 first**, then work one step at a time, stopping for approval after each; **skip** any step whose done-rule already passes. If **OFF**: run Step 0, then Steps 1–5 in order without pausing.
2. Verify every done-rule against the **cockpit as it actually renders in the browser** (read_page / screenshot) — never a source grep and never a green "success" label. Retry a step up to **3×** on failure, then mark FAILED and continue.
3. Final report: one line per step (0–5) — DONE / SKIPPED (already passed) / FAILED (reason) — plus the six verification ticks and the 5-reviewer scorecard.

## OVERALL DONE-RULE

- `app/prototypes/optimise-cockpit-p1.html` exists and renders as a no-sidebar dashboard: read-only header + Overview/Messaging/Leads tabs.
- The single handed optimisation is pinned and plain-English on every tab; **no** other optimisations/insights appear.
- One-click Mark done works in the prototype and the live `PATCH /api/notifications/{nid}` `{"status":"actioned"}` contract is documented.
- Firing the skill opens the browser straight to the cockpit for the handed campaign.
- 5 non-technical reviewers clear **9/10+** on all three axes (mean ≥9, none below 8).
