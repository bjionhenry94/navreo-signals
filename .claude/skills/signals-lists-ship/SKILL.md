---
name: signals-lists-ship
description: Static orchestration skill that moves prospect lists off individual laptops into Supabase and ships a read-only "Lists" page in the Navreo Signals tool (navreo-signals.onrender.com). Builds the lists/list_rows schema, a shared list_upload.py helper, /api/lists endpoints, a Clay-style read-only grid (search, filter, sort, hide/show columns, offset + limit), a folder browser (client folder + one optional sub-folder, AI-assigned from the brief), then wires the auto-upload step into every list-producing skill (tam-mapper, DM-finder v1/v2, list builders, TheirStack/Trigify processing). Done when 5 simulated GTMEs of differing abilities score ≥8/10 across 5 common use-cases. One fixed step list, checkable done-rules, retry cap, Loop Training Mode toggle. Use when the user says "ship the Lists page", "run the lists cloud migration", "move lists to Supabase", or "/signals-lists-ship".
---

# signals-lists-ship

Move prospect lists off individual machines into Supabase, and give the whole team a **Lists** page in the Signals tool to find, view, and organise them. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Repos: **`~/navreo-signals`** is the git/Render deploy repo — work there (`app/server.py`, `app/shell.js`, new `app/lists.html`). The iCloud copy is NOT the deploy target; diff-check it after merging (see [[reference_signals_deploy_repo]]). Shared helper lives at `~/.claude/skills/_shared/list_upload.py`. Supabase project: `fnykldftbkrccihdjayl`. Live app: `https://navreo-signals.onrender.com/app/`.

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

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going (unless a later step hard-depends on it — then stop and report), and surface it in the final report. Never silently exceed.

---

## THE GOAL

No prospect list should ever live only on one person's laptop. Every list pulled by a list-building skill is **automatically uploaded to Supabase** at the end of the run, the skill **prints a link** to it, and the team can browse it on a new **Lists** page in the Signals sidebar — a read-only, Clay-style table with search / filter / sort / hide-show columns / start-row (default 0) / row-limit (default 500), organised into client folders that the AI assigns automatically from the campaign brief.

Hard rules baked into the design:
- **Sheets are only created by Claude skills.** The UI has no "new sheet" button — ever. Users CAN create folders, move sheets between folders, favourite, search.
- **Folder depth is exactly two**: `Client / [optional theme]` (e.g. `Amplifyy / Beauty`). Never deeper.
- **Cell data is read-only** in the UI. View-state controls only.
- **This is part of the wider push** to keep all prospect data in the central Supabase layer ([[project_supabase_data_layer]]) — reuse its conventions, don't fork them.

---

## THE STEPS

### Step 1 — Supabase schema
Create three tables (via `mcp__supabase__apply_migration`):
- `list_folders` — `id, client text not null, name text, parent_id uuid null` (parent must itself have `parent_id null` → enforces 2-level max via constraint or trigger).
- `lists` — `id, name, client, folder_id → list_folders, source_skill, owner, brief_context text, row_count int, columns jsonb, favourite bool default false, access text default 'Edit', created_at, last_opened_at, last_opened_by`.
- `list_rows` — `id, list_id → lists on delete cascade, row_num int, data jsonb`. Index on `(list_id, row_num)`.
- **Enable RLS on all three** (service-role bypasses; the beta audit caught RLS off before — [[project_signals_beta_audit_findings]]).
- Done-rule: `list_tables` shows all three with RLS enabled; a smoke insert → select → delete via service role succeeds.

### Step 2 — Shared uploader `~/.claude/skills/_shared/list_upload.py`
One helper every skill calls. Signature: `upload_list(csv_path, name, client, folder=None, source_skill=..., brief_context=...)`.
- Creates/finds the client folder (and optional sub-folder) in `list_folders`, inserts the `lists` row, chunk-inserts `list_rows` (500/batch via Supabase REST, keys from `~/.navreo-keys.env`).
- Stores the CSV's header order in `lists.columns` so the grid renders columns in pull order.
- **Prints and returns the link**: `https://navreo-signals.onrender.com/app/lists.html#<list_id>`.
- Idempotent: re-running with the same `name+client` same-day **replaces that list's rows only** — scoped `DELETE ... WHERE list_id = X`, never table-wide ([[project_signals_wholetable_replace_dataloss_fix]]).
- Done-rule: CLI test uploads a sample CSV (~50 rows), prints the link, and `GET /rest/v1/list_rows?list_id=eq.<id>&limit=3` returns the rows; re-running it does not duplicate rows or touch other lists.

### Step 3 — Server endpoints (`app/server.py`)
Follow the existing `do_GET` `if path ==` pattern:
- `GET /api/lists` → folders tree + list metadata (name, client, favourite, created_at, last_opened, owner, access, row_count).
- `GET /api/lists/rows?id=&offset=0&limit=500&search=&sort=&dir=&filters=` → paged rows. Server-side search/sort/filter over `data` jsonb so 26k-row lists stay fast.
- `POST /api/lists/folder` (create), `POST /api/lists/move` (sheet → folder), `POST /api/lists/favourite`, `POST /api/lists/touch` (stamps last_opened_at/by).
- **No endpoint writes cell data.** No create-sheet endpoint.
- Done-rule: `curl` each endpoint locally — lists returns the smoke list from Step 2; rows respects `offset=0&limit=500` defaults, `search=` narrows, `sort=` orders; a POST to a non-existent cell-write route 404s.

### Step 4 — Lists page: file browser (`app/lists.html` + nav)
- Add `lists.html` to `NAV` + `ICONS` in `app/shell.js` — sidebar entry **"Lists"**, visible on every page.
- File-browser view matching the reference screenshot, columns: **Name · Favorite · Clients · Created at · Last opened by me · Owner · Access** ("Clients" replaces "Tags", auto-filled from `lists.client`).
- Folders render as expandable rows; **+ New Folder** button exists; sheets can be **moved** into folders (client → one sub-level max); **no + New sheet control anywhere**; search box over names.
- Done-rule: `preview_snapshot` shows the browser with the smoke list under its client folder, all seven columns, a New-Folder control, and zero new-sheet affordances; the Lists rail icon shows on `index/campaigns/mailboxes/notifications` pages too.

### Step 5 — Lists page: read-only grid viewer
Opening a sheet (`lists.html#<id>`) shows the Clay-style grid:
- **Search** (across all columns) · **Filter** (per-column) · **Sort** (click header) · **Hide/show columns** (`n/N columns` picker) · **Starting row** (default 0) · **Row limit** (default 500) · row-count chip (`X/Y rows`).
- **Share link** button on every sheet — copies the sheet's URL (`https://navreo-signals.onrender.com/app/lists.html#<id>`) to the clipboard with a "copied" confirmation, so anyone can paste it to the team.
- Cells are read-only — no editing affordance at all. Opening stamps `POST /api/lists/touch`.
- Done-rule: against the smoke list, `preview_snapshot` + interactions verify each of the six view controls does what it says (search narrows, sort flips, a hidden column disappears, offset/limit change the visible slice), the Share-link button puts the correct URL on the clipboard, with no console errors.

### Step 6 — Wire auto-upload into the list-producing skills
Add one final "**Cloud upload (mandatory)**" step to each SKILL.md in the roster:
> Before finishing, upload the final list via `_shared/list_upload.py` — client from the brief, sub-folder = the campaign theme if the brief names one (e.g. Amplifyy/Beauty), else none — and show the returned lists.html link to the user.

Roster: `lilly-tam`, `lilly-tam`, `lilly-tam`, `lilly-ocean-tam-builder`, `lilly-tam`, `lilly-tam`, `lilly-theirstack-data-processing`, `lilly-trigify-data-processing`, `qwintiq-list-building`.
- Folder assignment is by the AI from the brief — named client → that client's folder; internal/Navreo pull → `Navreo`; never invent a third level.
- Done-rule: `grep -l "list_upload" ~/.claude/skills/{roster}/SKILL.md` hits all nine; each names the client-folder rule. (The publish-skill hook will push each edit — let it.)

### Step 7 — Deploy + repo hygiene
- Commit `~/navreo-signals` and push to Render; wait for the deploy to go healthy (`/healthz`).
- Done-rule: `https://navreo-signals.onrender.com/app/lists.html` renders live with the smoke list; the Lists icon is live in the sidebar; then diff-check the iCloud copy against the deploy repo and reconcile.

### Step 8 — GTME panel verification (the acceptance gate)
Simulate a panel of **5 GTMEs of differing abilities** (new-joiner → power user), each attempting the 5 most common team use-cases:
1. Find and open a list a colleague pulled last week for a named client (colleague OOO).
2. After a fresh tam-mapper/DM-finder run, follow the printed link straight to the sheet.
3. Filter + sort a big list to a segment (e.g. one title + one country) and read off the count.
4. Check whether a specific company/person already appears on an existing list (search).
5. Create a client sub-folder and move a sheet into it.
- Each simulated tester scores ease-of-use /10 per use-case, with a stated reason for anything <8. Run via fresh-eyes subagents against the **live** URL, not your own builder's knowledge. Never use `preview_click` for the UX sims ([[project_signals_push_ux]]) — drive them through snapshots + real interactions.
- On any avg <8: fix the named friction, redeploy, re-run the failing tester×use-case pairs only. Retry cap applies to this loop too (3 fix-rounds max).
- Done-rule: **panel average ≥8/10 on every one of the 5 use-cases**, and all 5 testers completed all 5 tasks.

---

## HOW TO RUN

**Model routing:** the main loop (Fable 5) does orchestration, judgment, and done-rule verdicts. All execution work — writing the helper, server endpoints, UI, skill edits, and the GTME tester sims — is delegated to subagents with `model: 'sonnet'` (Sonnet 5).

1. Read the mode line above. If **ON**, work one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all eight in order without pausing.
2. Steps 1–2 are Supabase + helper work; 3–5 are `~/navreo-signals` app work (verify locally via preview against `http://localhost:7901/app/lists.html` before deploying); 6 is skill-file edits; 7–8 run against the live Render URL.
3. Check each step's done-rule exactly as written (SQL checks, curl asserts, greps, snapshots). Retry up to 3× on failure, then mark FAILED and continue — except Steps 1–3, which later steps hard-depend on: a cap-hit there stops the run.

## OVERALL DONE-RULE

- A list pulled by any roster skill lands in Supabase automatically and the user is shown a working `lists.html#<id>` link.
- The live Lists page shows every uploaded list in the right client folder with the seven browser columns, and the grid supports search / filter / sort / hide-show / offset(0) / limit(500), fully read-only, no sheet creation.
- GTME panel: **avg ≥8/10 on all 5 use-cases**.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — plus the panel scorecard.
