---
name: campaign-detail-optimise
description: Static orchestration skill that optimises the INDIVIDUAL campaign detail page — the renderDraftCampaign(id) view in app/campaigns.html (backed by app/server.py) of the Navreo signals tool, NOT the campaigns list. Four fixed changes — remove name editing, rebuild the Leads tab as a lazily-loaded columnar Supabase table (essential columns + icebreaker custom variable), hide the Manual/Autopilot toggle while keeping autopilot behaviour, make the destination read-only — each with a checkable done-rule verified LIVE on navreo-signals.onrender.com, plus a Loop Training Mode toggle. Use when the user says "run the campaign detail optimise", "optimise the campaign detail page", "do the four campaign-detail changes", or "/campaign-detail-optimise".
---

# campaign-detail-optimise

Optimise the **individual campaign detail page** (`renderDraftCampaign(id)` in `app/campaigns.html`, backed by `app/server.py`) — **not** the campaigns list. Four changes. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

**Ship-and-verify-LIVE law.** iCloud reverts local edits and interruptions count as redeploys, so treat every change as ship-then-verify on the deployed host **`navreo-signals.onrender.com`**. A local render, a source grep, or a green "success" label is NEVER done-evidence — the only proof is the live rendered DOM / live network panel / an independent Supabase count. Push each change to the deploy path Render builds from, wait for the redeploy, then verify on the live host.

Scope guard: leave the **Sources tab byte-for-byte unchanged** ("fine as designed"), and leave the **● Running / ⏸ Paused** toggle in place (not in scope).

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

---

## THE GOAL

On the **live deployed** campaign detail page: the name can't be edited; the header carries **no** Manual/Autopilot toggle and **no** destination picker (destination shown read-only); and the Leads tab is a **lazily-loaded columnar table** of that campaign's Supabase leads showing every essential column **plus** the icebreaker custom variable — with the daily-push autopilot behaviour **still working underneath**.

---

## STEP 0 — Reconcile ground truth BEFORE touching anything (blocking gate)

The screenshot's header chrome — the Smartlead platform badge, "Active"/"Draft" pills, the top destination dropdown, and a **"Start sending"** button — does **NOT** exist anywhere in the local repo (no `"Start sending"` string, no `unified.html`). The local campaign detail header instead renders two segmented toggles (**● Running / ⏸ Paused** at `campaigns.html:509`, **✋ Manual review / ⚡ Autopilot** at `:514`) plus the **✎ rename pencil** at `:494`.

- Confirm local `app/campaigns.html` is actually the source of the page the user sees: open `navreo-signals.onrender.com`, land on a campaign detail page, and match its live DOM against local `renderDraftCampaign`.
- **If the deployed build has drifted ahead of local** (live header shows chrome that local doesn't), STOP and reconcile against the **real deployed source first** — edit the source Render actually builds from, not a stale local copy. Do not edit blind.
- Done-rule: you have positively identified which source produces the live header, and the four line anchors below (`:494`, `:509/:514`, `608+`, `871`/`1014–1051`) map to real elements in **that** source. Record any drift found.

---

## THE STEPS

### Step 1 — Remove campaign-name editing
- Delete the **✎ pencil** button at `campaigns.html:494` and its `renameCampaign()` handler entry point (`:790`).
- `#camp-title` stays as **static, non-editable** text (keep the title; drop only the edit affordance).
- Done-rule (LIVE): on the deployed campaign detail page the title shows **no ✎ pencil** and clicking it does nothing / is not editable — verified in the live rendered DOM.

### Step 2 — Rebuild the Leads tab as a lazily-loaded columnar Supabase table
Source stays **Supabase**: `/api/leads?campaign_id=` → `_leads_for_sources()` / `signal_leads` (`server.py:2023`, column select `:2034`). Keep that; change the rendering and the loading.
- **Replace** the current card rows (`leadRowInner`, `:1060`, from `dtab==="leads"` at `:608` onward) with a **columnar table**.
- Columns = the **essential** fields **PLUS** the campaign's custom bespoke variable: name, title, company, website/domain, country, email, LinkedIn, sent/pending/skipped **status**, **pulled-at**, and the **icebreaker** column (that is the ONLY per-lead custom variable `signal_leads` stores).
- **"Only what's stored now" ruling.** Verified `signal_leads` schema: `id, source_id, full_name, title, company, domain, linkedin_url, country, icebreaker, status, pushed_to, pulled_at, email` — **no `vars` JSONB**. So render `icebreaker` as the custom-variable column and **ONLY render columns that are actually populated**. Do NOT add a schema column, do NOT invent or blank-pad variable columns, do NOT fabricate variables the copy references but Supabase doesn't hold.
- **Lazy-load (default, veto-able).** Today `/api/leads` returns every row in one SWR-cached call then paginates 10/page client-side. Change to **true incremental loading from Supabase**: add `offset`/`limit` paging to the leads endpoint and load the next page on scroll / "load more" (~50 rows/page), so a large campaign never pulls all rows at once.
- Done-rule (LIVE): the Leads tab renders a columnar table with the essential columns + the icebreaker column; **every displayed column is actually populated** from `signal_leads` and **no fabricated/empty custom-variable columns appear**; the browser **network panel shows paginated page fetches** (not one all-rows pull); and the visible row count reconciles to an **independent direct Supabase count** of `signal_leads` for that campaign's sources — table rows == DB count == the **"Leads (N)"** tab header.

### Step 3 — Hide the Manual/Autopilot toggle, KEEP the behaviour
Ruling: **hide UI, keep behaviour.**
- Remove the **✋ Manual review / ⚡ Autopilot** segmented toggle (`:514–518`) from the header.
- Do **NOT** remove the campaign-level autopilot field or its behaviour: `autopilot` is a `campaign_drafts.autopilot` flag (persisted via `/api/campaign-drafts`, `server.py:7560`) that gates `auto_push_new_leads` in the daily run (`server.py:6305`). That server path stays intact and keeps honouring the stored default.
- Done-rule (LIVE + server): header shows **no** Manual/Autopilot toggle in the live DOM; AND `campaign_drafts.autopilot` **still persists and still gates** `auto_push_new_leads` — confirmed by reading the unchanged server path AND checking the field **round-trips via `/api/campaign-drafts`**. Hiding the toggle changed **no** send behaviour.

### Step 4 — Make the destination read-only
The campaign-level destination picker (`destBar :871` + `pickDest`/`saveDest` `:1014–1051`, two clickable Smartlead/HeyReach brand chips opening a search popover) is redundant now that destination is set **per-source** (`server.py` sources/update `:1964`).
- Remove the **picker/popover interaction** so the destination is **displayed but not editable**.
- **KEEP** the destination **visible**, and KEEP the **"⚠ No destination set — nothing can be sent"** warning so send-routing gaps stay surfaced.
- Do **NOT** delete the backend destination field.
- Done-rule (LIVE): header shows the destination as **read-only** (no clickable chip, no popover opens on click) while remaining visible; the no-destination warning still fires when unset — verified in the live rendered DOM.

---

## THE VERIFICATION (all six, LIVE on navreo-signals.onrender.com — DOM/network/DB, not source, not a label)

1. Campaign title shows **no ✎ pencil** and is not editable.
2. Header shows **no Manual/Autopilot toggle** and **no clickable destination picker** — destination visible but read-only, and **Running/Paused still present**.
3. Autopilot preserved server-side — `campaign_drafts.autopilot` still persists and still gates `auto_push_new_leads` (unchanged server path read AND `/api/campaign-drafts` round-trip confirmed).
4. Leads tab is a columnar table with the essential columns **+ the icebreaker column**; every displayed column is actually populated; **no** fabricated/empty custom-variable columns.
5. Leads load **incrementally** — network panel shows paginated page fetches, not one all-rows pull — and visible row count reconciles to an **independent direct Supabase count** (table rows == DB count == "Leads (N)" header).
6. **Sources tab unchanged.**

All six verified live, or it isn't done.

---

## HOW TO RUN

1. Read the mode line above. If **ON** (default), do **Step 0 first**, then work one step at a time and stop for approval after each; skip any step whose LIVE done-rule already passes. If **OFF**, run Step 0 then all four in order without pausing.
2. For each step: make the edits in the **source Render actually builds from** (`campaigns.html`, and `server.py` for Step 2's paging), **push and let Render redeploy**, then check the done-rule against the **live host** — live rendered DOM (`read_page`/screenshot on `navreo-signals.onrender.com`), the live **network panel** for the paging check, and an **independent Supabase count** (`mcp__supabase__execute_sql`) for the row reconcile. Never accept a local render or a source grep as proof. Retry up to 3× on live-failure, then mark FAILED and continue.
3. Because interruptions = redeploys, re-confirm the live page after any interruption before calling a step done.

## OVERALL DONE-RULE

- All four changes are in place and each of the **six live verifications** passes on `navreo-signals.onrender.com`.
- Autopilot daily-push behaviour is intact server-side (Step 3 done-rule).
- Sources tab is byte-for-byte unchanged; Running/Paused toggle still present.
- Final report: one line per step (0–4) — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the six-check verification ticks.
