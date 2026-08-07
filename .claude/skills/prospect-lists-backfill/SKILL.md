---
name: prospect-lists-backfill
description: Static orchestration skill that sweeps the Navreo project for prospect-list CSVs built with Prospeo or AI-ARK, uploads them to the team Lists cloud store (Supabase lists/list_rows/list_folders behind lists.html) organised per client and project folder, then runs a mock scheduled pull to prove the data is retrievable. Has a Loop Training Mode toggle (ON by default) that pauses at every step for user approval. Trigger on "backfill the prospect lists", "upload my prospect lists to the cloud store", "sync campaign lists for the team", "/prospect-lists-backfill".
---

# Prospect Lists Backfill

## ⚙️ LOOP TRAINING MODE — the toggle

```
LOOP_TRAINING_MODE: OFF        ← flip to ON to pause at every step for approval
```

**This is the first thing to read on every run.** The value above is the setting; edit this file to change it.

**When ON (default):**
- PAUSE at the end of every step. Show the step's result and the done-rule verdict, then WAIT for the user's approval before starting the next step. Never continue on your own.
- SKIP any step whose done-rule already passes before the step runs (say so: "Step N already passes — skipping").
- Only RE-RUN steps that FAIL their done-rule. Never re-run a passing step.
- Retry cap: **3 attempts per step**. After the 3rd failure, stop, report what failed and why, and ask the user how to proceed. Never loop past the cap.

**When OFF:**
- Run all steps start to finish with no pauses and no approval requests.
- Keep every done-rule check and the same skip-if-already-passing behaviour.
- Keep the 3-attempt retry cap. On a 3rd failure, halt the run and report — do not continue to later steps that depend on the failed one.

---

## Goal

Every prospect-list CSV in the Navreo project that originated from **Prospeo** or **AI-ARK** is uploaded to the team Lists cloud store (https://navreo-signals.onrender.com/app/lists.html), organised into the right **client** and **project sub-folder**, and provably retrievable by a scheduled pull.

## Fixed inputs (do not re-derive)

| Thing | Value |
|---|---|
| Project root | `/Users/bjionhenry/Library/Mobile Documents/com~apple~CloudDocs/Bjion [2023]/Navreo/Claude/Navreo` |
| Uploader | `python3 ~/.claude/skills/_shared/list_upload.py <csv> --name <n> --client <c> --folder <f> --source-skill prospect-lists-backfill` |
| Keys | `~/.navreo-keys.env` (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY — loaded by the uploader itself) |
| Manifest (state file) | `~/.claude/skills/prospect-lists-backfill/manifest.json` |
| Cloud store tables | `lists`, `list_rows`, `list_folders` in Supabase project `fnykldftbkrccihdjayl` |

The uploader is upsert-by-(name, client): re-running a row replaces the list's rows instead of duplicating the list. That is what makes every step of this skill safe to re-run.

## Client map (static)

Match by filename/directory keywords, case-insensitive. First match wins; anything unmatched → client `Navreo`, folder `Unsorted` (flag it for the user in Training Mode).

| Keyword in path | Client | Folder |
|---|---|---|
| amplifyy, amazon | Amplifyy | (project dir name or list theme) |
| applift, mobile-app, d2c-app | AppLift | " |
| asteri, pestco, valsoft | Asteri Partners | " |
| arnic | Arnic | " |
| boomerang | Boomerang | " |
| qwintiq | Qwintiq | " |
| wordbank | WordBank | " |
| sihl, picofilm, okan | Sihl | " |
| heygrand, grand | HeyGrand | " |
| krg | KRG Advisors | " |
| interdependence | Interdependence | " |
| navreo, msp-tam, freight, exporters, cold-outreach, podcast | Navreo | " |

Folder = the containing directory name if the CSV lives in a dated project dir (e.g. `PestCo-TAM-2026-04-28`), else a short theme from the filename (e.g. `Recontact 2026-06`).

## Steps

Run in order. Each step has ONE done-rule; check it before (skip-if-passing) and after (pass/fail) the step.

### Step 1 — Inventory & classify
Scan the project root recursively for `*.csv` (exclude `node_modules`, `app/data`, backups/audit dirs). For each CSV, decide **origin**: read the header + a couple of rows and look for Prospeo/AI-ARK fingerprints (columns like `email_status`/`prospeo`-style enrichment fields, AI-ARK export columns, `source` columns naming the provider) plus filename hints (`prospeo`, `ai-ark`, `aiark`, TAM/DM-finder output names like `qualified.csv`, `*-DMs-*`, `*_ready_for_upload*`). Classify each file as `prospect_list` (Prospeo or AI-ARK origin, is a list of companies or people for outreach) or `skip` (audits, exclusion/suppression lists, campaign backups, mockups, non-list artifacts). Assign client + folder from the Client map. Write the result to the manifest as `{path, origin, client, folder, list_name, status: "pending"|"skip", reason}`.

**Done-rule:** `manifest.json` exists, covers every CSV found in the scan, and every entry has a non-empty `status`, and every `pending` entry has `client`, `folder`, and `list_name`.

*(Training Mode: present the manifest as a per-client summary table — counts + any `Unsorted` flags — for approval before Step 2.)*

### Step 2 — Upload
For every manifest entry with `status: "pending"`, run the uploader with that entry's name/client/folder. On success, set `status: "uploaded"` and store the returned `lists.html#<id>` link and row count in the entry. On per-file failure, record the error and leave it `pending` (per-file retries count toward this step's retry cap — a re-run of Step 2 only touches files still `pending`).

**Done-rule:** zero manifest entries remain `pending`; every non-skip entry has `status: "uploaded"` with a stored link and row count.

### Step 3 — Organise check
Query Supabase (`list_folders` + `lists`) and verify: every uploaded list sits in a folder whose `client` matches the manifest, no list landed at another client's root, and folder nesting is ≤ 2 levels (root → theme). Fix any misplacement by re-running the uploader for that entry (upsert corrects folder).

**Done-rule:** a `lists` query grouped by client returns every manifest list under its intended client + folder, with row_count > 0 on each.

### Step 4 — Mock scheduled pull (verification)
Simulate what a scheduled team consumer would do — no cron is created; this is a one-shot mock. Write a tiny throwaway script (scratchpad, not the repo) that, using only the PostgREST endpoints and the keys file: (1) lists all folders and lists per client, (2) for **3 sampled lists per client** (or all, if fewer) pulls `list_rows` and checks the fetched row count equals the list's `row_count`, and (3) prints a per-client PASS/FAIL table. Run it twice, a fresh process each time, to prove the pull is repeatable.

**Done-rule:** both mock runs print PASS for every sampled list (fetched rows == recorded row_count, zero HTTP errors).

### Step 5 — Report
Produce the final summary: per-client table of lists uploaded (name, folder, rows, link), files skipped and why, anything left in `Unsorted`, and the mock-pull verdict. In Training Mode this is the last approval gate; either way, end by giving the user the lists.html URL.

**Done-rule:** the report has been shown to the user and every earlier step's done-rule still passes.

## Hard rules

- **Additive only.** Never delete or rename source CSVs. The only DELETE the run may cause is the uploader's own `list_id=eq.<id>`-scoped row replacement.
- **Never widen a DELETE.** If any Supabase delete lacks an `eq.` scope, abort the run (see MEMORY: whole-table-replace data-loss fix).
- Exclusion/suppression lists, mailbox audits, and campaign backups are **not** prospect lists — always `skip`.
- No new cron jobs, no schedule registration. Step 4 is a mock, one-shot.
- Manifest is the single source of truth for resume: a re-run starts by re-checking done-rules against it, not by re-scanning from scratch (unless the user asks for a fresh scan).

## Done (whole skill)

All five step done-rules pass in one pass over the manifest. Say so in one line, give the lists.html link, and stop.
