---
name: signals-list-resume
description: Static orchestration skill that gives GTMEs resumable "Saved Pulls" in the Navreo Signals Lists page — freeze a big targeting brief once, pull a fraction (a tranche) now to test, then return weeks later from the Lists section and pull the remainder into new campaigns, picking up exactly where they left off with ZERO re-pull and near-zero wasted credits. Builds a `list_pulls` table (brief + exact filter JSON + total TAM + saved cursor + pulled-count + credit ledger + lock), an append-mode tranche-pull engine, and a Resume affordance on lists.html, then pre-seeds the Navreo Exporters brief as Saved Pull #1 (consolidating the existing loose exporter lists) so it can never be forgotten. Proven by 5 simulated GTMEs of differing ability scoring ≥8/10 on BOTH ease-of-use and credit-wastage reduction. One fixed step list, checkable done-rules, retry cap, Loop Training Mode toggle. Use when the user says "pull a fraction now, resume later", "make the list resumable", "tranche pull", "pick up where I left off", "save this brief so I don't forget it", or "/signals-list-resume".
---

# signals-list-resume

Let a GTME freeze a targeting brief as a **Saved Pull**, take a **tranche** (e.g. 3,500) now to test, and come back later from the **Lists** page to pull more — never re-pulling a row, never needing the Claude chat that created it. Static loop: the steps are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Deploy repo: **`~/navreo-signals`** (git/Render) — work there (`app/server.py`, `app/lists.html`, `app/shell.js`). The iCloud copy is NOT the deploy target and silently reverts edits — never edit it (see [[reference_signals_deploy_repo]]). Shared uploader: `~/.claude/skills/_shared/list_upload.py`. Spend ledger + cache: `~/.claude/skills/_shared/navreo_db.py`. Supabase: `fnykldftbkrccihdjayl`. Live: `https://navreo-signals.onrender.com/app/lists.html`. Extends [[reference_skill_signals_lists_ship]].

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap still applies. Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it FAILED with the reason, keep going (unless a later step hard-depends on it → stop and report), surface it in the final report. Never silently exceed.

---

## THE GOAL

A GTME pulls a slice of a big list today, tests it, and — with no memory of how it was built — returns to the **Lists** page next month, sees exactly what the list is and how far it got, and pulls the next slice into a fresh campaign in a couple of clicks. The brief travels **with** the list; the cursor guarantees you never re-fetch (or re-pay for) a row from an earlier tranche.

Hard rules baked into the design:
- **A Saved Pull is created only by a Claude skill.** GTMEs resume, they don't author targeting. The UI's only write actions are: Pull next tranche, change tranche size, open brief.
- **Never re-fetch an earlier tranche's rows** (cursor guarantee = truly 0 credits on re-pull). Within a tranche, already-contacted rows are excluded at the *query* level where the list is bounded, and the rest dropped post-fetch — a small, logged overlap tax, never a silent double-charge. (Honest: providers bill per row *fetched*, so we cannot make suppression 100% pre-spend; we minimise it, we don't pretend it's zero.)
- **Manual pulls only, never auto** — copy the shipped ListMint verify-job pattern (durable rows + a Resume button; auto-resume was removed precisely to stop duplicate/wasted-credit runs).
- Reuse the central Supabase layer ([[project_supabase_data_layer]]); don't fork it.

---

## KEY DESIGN (the resumable object)

A **Saved Pull** (`list_pulls` row) freezes a brief so it can be resumed:

| Field | Purpose |
|---|---|
| `provider` + `filter_json` | the exact query (Ocean/Prospeo/AI Ark), replayable verbatim |
| `total_tam` + `tam_asof` | probe-confirmed ceiling + the date it was measured (so "remaining" drift is visible) |
| `cursor` + `cursor_sortkeys` | Ocean `search_after` token **and** the last row's sort-key values, so position can be re-derived if the opaque token goes stale weeks later |
| `pulled_count` | rows taken so far → progress = pulled/total |
| `locked_by` + `locked_at` + `version` | concurrency guard — one pull at a time |
| `credit_ledger` | per-tranche summary {tranche_no, rows, credits, campaign, at} for the UI |
| `brief_md` | the human story: goal, targeting, funnel, rationale — mirrored to `lists.brief_context` |

**Resume = replay `filter_json` from `cursor`, take the next N survivors, advance `cursor`+`pulled_count` atomically.** Guardrail refuses any tranche > `total_tam − pulled_count`.

## GROUNDING — reuse, don't reinvent (confirmed against `~/navreo-signals`)

- **Cursor per provider:** Ocean `search_after` (what Exporters uses — a sort-key cursor, resume-stable; store the sort-key values too as a fallback), Prospeo `page`, AI Ark `pageable.offset` **capped at page ≤950 / offset ~10K** (a resume can never pass it — surface "provider depth cap reached" instead of erroring).
- **Uploader must APPEND idempotently, not replace.** `list_upload.py` currently deletes-then-reinserts rows on upsert-by-name (`~:217-226`) — using it as-is would **wipe the prior tranche**. Add an insert-only `append=True` path that: continues `row_num` from `max(row_num)+1`, does `row_count += inserted` (never `= len(rows)`), and is **idempotent** — a unique index on `(list_id, canonical_domain)` + upsert-on-conflict-do-nothing so a crash-retry re-inserts 0. Wrap the append **and** the cursor/pulled_count advance in **one DB transaction** so a mid-tranche crash rolls back cleanly and never re-charges. Hard prerequisite for Step 3.
- **Canonical spend ledger:** `navreo_db.log_provider_usage(provider, credits, endpoint=, source_id='signals-list-resume')` → `provider_usage`. `list_pulls.credit_ledger` is only the UI summary.
- **30-day cache** (`navreo_db.get_enrichment`) already makes a repeat of the same company free — check before spending.
- **Endpoints:** `GET /api/list_pulls`, `POST /api/list_pulls/<id>/pull` following the `LISTS_POST_ROUTES` real-HTTP-status pattern (`server.py:3052-3060`), with a row lock (`SELECT … FOR UPDATE`) so concurrent pulls serialise. Distinct from the ephemeral `/api/sources/pull`.

---

## THE STEPS

### Step 1 — Schema (`list_pulls`)
`apply_migration`: `list_pulls` — `id uuid pk, list_id uuid → lists, name, client, provider text, filter_json jsonb, total_tam int, tam_asof date, cursor jsonb, cursor_sortkeys jsonb, pulled_count int default 0, tranche_size int default 3500, status text default 'active', locked_by text, locked_at timestamptz, version int default 0, credit_ledger jsonb default '[]', brief_md text, created_at, updated_at, last_pulled_at, last_pulled_by`. **RLS on** (beta audit caught RLS-off — [[project_signals_beta_audit_findings]]).
- **Done-rule:** `list_tables` shows `list_pulls` with RLS on; smoke insert → select → delete via service role succeeds.

### Step 2 — Seed Saved Pull #1 = Navreo Exporters (and consolidate the loose lists)
Insert the locked Exporters brief (`~/Desktop/navreo-exporters-pull/reference/exporters-tam-CORRECTED.md`): `provider='ocean'`, `filter_json`=WIDE-1, `total_tam=17497`, `tam_asof=2026-07-11`, `cursor=null`, `pulled_count=0`, `brief_md`=goal + targeting table (geo tiers **spelled out to explicit country lists**, size, DM rule) + funnel + the 3 exclusion layers. Create `lists` row + folder `Navreo / Exporters`. **Fold in the two existing loose exporter lists** ("Exporters Never-Replied Recontact" 9,094; "Exporters Combined Enriched (AI-ARK)" 7,871) — they carry only a filesystem-path `brief_context`: attach them under this Saved Pull as prior tranches (or link + supersede), so a cold GTME sees ONE object with a real brief, not three orphans.
- **Done-rule:** the Lists page shows **"Navreo — Exporters (Tier 1+2 + Asia −China)"** at **0 / 17,497**, brief readable, prior exporter lists linked under it, **[Pull next tranche]** visible.

### Step 3 — Tranche engine (`POST /api/list_pulls/<id>/pull`)
Under a row lock: replay `filter_json` from `cursor` → take next `tranche_size` rows → drop suppression + already-pulled (dedupe on canonical domain; pass the bounded already-contacted domain set as provider `excludeDomains` so they aren't fetched at all; cache-check before any paid export) → `upload_list(..., append=True)` to the master list → **atomically** advance `cursor`+`cursor_sortkeys`+`pulled_count` and bump `version` → append `credit_ledger` + `log_provider_usage`. On a stale-cursor error, re-derive position from `cursor_sortkeys`. `campaign_id` routes the tranche to Smartlead via [[reference_skill_lilly_upload_gate]].
- **Done-rule:** pull 3,500 → `pulled_count`=3,500, cursor at next unseen row; a **second** pull returns **0-overlap** rows; **pull twice → row-count GROWS (not resets)**; a **concurrent** second pull gets 409, not a double-charge; a **crash-retry mid-tranche re-inserts 0 rows and re-charges 0** (idempotent); ledger credits ≈ net-new rows.

### Step 4 — Resume UI on `lists.html`
Discovery: a pinned **"Saved Pulls"** section above the folder tree (badge on resumable lists — never lost in the flat grid). Acting: when a Saved Pull is opened, the resume controls render as a **full-width inline banner across the top of the list, with the company grid below** (chosen over a right sidebar, Bjion 2026-07-11) — it stacks gracefully on narrow screens, so no separate sidebar/mobile-rail behaviour is needed. Use **"batch"** in every user-facing label (not "tranche"/"TAM"/"cursor"). The banner shows: brief panel, **progress bar** with a plain-English caption ("Batch of 3,500 · 3,500 of 17,497 pulled · 13,997 left"), **batch history** — each row links to its Smartlead campaign, shows gate result ("3,200/3,500 passed"), the small **overlap-tax credits** spent, and a one-line **performance rollup** ("Batch 1: 2.1% positive reply", sourced from the existing Smartlead→Supabase sync so a returning GTME can judge if more is worth pulling) — and **[Pull next batch] [Batch size] [Open brief]**. Pull opens a **required** modal: choose/create the Smartlead campaign + confirm "N rows → Campaign X"; the button **disables while a pull is in flight**. Batch-size field **auto-clamps its max to `remaining`** and pre-fills it; an optional **"keep pulling until none left"** toggle chains capped batches under one typed confirm. Cells read-only.
- **Done-rule:** a GTME, with **no chat context**, finds the Exporters pull in the Saved Pulls section, understands it from the brief alone, sees how the last batch performed, and fires the next batch into a chosen campaign without hand-editing numbers or hitting an error.

### Step 5 — Credit-waste guardrails
Block a tranche > `remaining` (auto-clamp, don't error). Re-pull of an already-pulled range spends **0** (cursor + excludeDomains + cache). Hard ceiling: any tranche whose **live credit-cost preview** exceeds **2,000 credits** requires a typed confirmation; `tranche_size` capped ≤5,000. Show the cost preview before the Pull click.
- **Done-rule:** re-pull spends 0; over-`remaining` is clamped not errored; a >2,000-credit tranche demands typed confirm; the preview shows credits before spend.

### Step 6 — Prove it (5 simulated GTMEs, differing ability)
5 simulated GTME testers (`model:sonnet`) run the 4 journeys: (a) first tranche + upload; (b) abandon; (c) return **cold** and reconstruct intent from the Lists page only; (d) pull remainder into a NEW campaign. Probe concurrency, overshoot, re-pull, cold legibility. Score each 1-10 on **ease** and **credit-wastage**; fix top frictions; re-test.
- **Done-rule:** average **≥8/10 on BOTH** across all 5 AND all 5 succeed at cold-resume (c) with 0 wasted credits. Iterate (retry cap 3 rounds).

---

## DONE-RULE (whole skill)
Steps 1-5 pass **and** Step 6 lands avg ≥8/10 on ease **and** credit-wastage across all 5 GTMEs. Report the score table, frictions fixed, and the link to the seeded Exporters pull.
