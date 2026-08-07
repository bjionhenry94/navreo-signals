---
name: list-autopush
description: Push ANY pulled prospect list into the Navreo signals-tool Lists page (navreo-signals.onrender.com/app/lists.html) — full-fidelity, company-upserted, browser-verified. Use whenever a pull has produced rows: an ad-hoc TheirStack / Prospeo / AI Ark / Ocean / TheirStack+Prospeo call from a script, a CSV a skill just built, a list someone hands you, or when the list-autopush-guard Stop hook blocks a turn saying a list was never pushed. Trigger phrases "push the list", "upload this list", "push it to the tool", "put that in Lists", "/list-autopush", or the guard's BLOCKED message. Not a list BUILDER — it never pulls or scores; it takes rows that already exist and lands them in the tool.
---

# list-autopush

**One job: rows that exist locally must exist in the tool before the turn ends.**

The standing rule ([[feedback_any_pull_uploads_to_tool]], restated by Bjion 2026-07-17):
whenever a list is pulled, it gets pushed to the tool. No exceptions, no "this one was
just a sample", no "it was only 10 rows".

## Why this skill exists

The auto-upload rule shipped in [[project_signals_lists_cloud_store]] was codified as a
closing step *inside* the 9 list-producing skills. So it was silently bypassed by any
**ad-hoc pull** — hitting the provider APIs directly from a python heredoc, which is a
normal and often correct way to work. The rule lived in the skills; it belongs to the
*act of pulling*.

This skill is the one correct implementation. The `list-autopush-guard` **Stop hook**
(`~/.claude/hooks/list-autopush-guard.sh`) is the enforcement: it blocks the end of any
turn that leaves an un-uploaded prospect CSV on disk. Skill = how, hook = never forgets.

## When it fires

- The guard blocked your turn. Do this now, not next turn.
- You just pulled rows from any provider, however you pulled them.
- A CSV of prospects exists and has no Lists link.

**Do NOT use for:** scoring, verification, TAM sizing, or building a list. Those are
[[reference_skill_lilly_tam]] / [[reference_skill_lilly_lead_score]]. This only lands rows.

---

## THE STEPS

### Step 1 — Full fidelity, not what you showed in chat
Per [[feedback_full_fidelity_list_uploads]]: **show lean, upload fat.** We pay providers
for rich rows and were throwing the richness away.

- Re-read the raw provider payloads. Do not upload the trimmed table you printed.
  A TheirStack `company_object` is ~45 fields; a Prospeo `person` carries `job_history`,
  `skills`, `location`, `headline`.
- Every row carries `source` (e.g. `theirstack+prospeo`) and `shape_tag` — the exact
  filter shape that found it. `shape_tag` is free entity-typing and powers the
  "search our own database first" idea. Example:
  `theirstack:jobs.search|eng_titles|job_country=US|hc=11-200|company_type=direct_employer`
- Flatten lists/dicts to JSON strings so they survive CSV.

**Done-rule:** column count is materially larger than the lean table you showed the user.

### Step 2 — Upload
```python
import sys; sys.path.insert(0, '/Users/bjionhenry/.claude/skills/_shared')
import list_upload
link = list_upload.upload_list(
    csv_path='<full-fidelity>.csv',
    name='<what it is, human-readable>',
    client='navreo',              # a PROSPECT's list is still client='navreo'
    folder='<prospect or theme>', # folder depth is capped at 2 by a DB trigger
    source_skill='ad-hoc (theirstack jobs.search + prospeo search-person)',
    brief_context='<why this exists, who asked, what it proves>',
    owner='bjion',
)
```
- Upsert is by **(name, client)** — re-running replaces that list's rows only. Safe to re-run.
- It writes an **upload receipt** to `~/.claude/state/list_uploads.jsonl` (keyed by CSV
  content hash). That receipt is what stops the guard re-blocking. Never hand-write one
  to silence the guard.

**Done-rule:** a `lists.html#<id>` link is returned.

### Step 3 — Upsert the companies
The rule is not just the list; the central directory has to fill up too.
```python
sys.path.insert(0, '/Users/bjionhenry/.claude/skills/_shared'); import navreo_db
navreo_db.upsert_company(navreo_db.canonical_domain(dom),
    name=..., description=..., industry=..., employee_count=...,
    employee_range=..., country=..., city=..., linkedin_url=...)
```
`companies` columns are exactly: `domain, name, description, industry, employee_count,
employee_range, country, state, city, linkedin_url` (+ timestamps). Anything else errors.

**Done-rule:** one upsert per unique domain, all returning non-None.

### Step 4 — Browser-verify (the only done-evidence)
Per [[feedback_browser_verify_before_done]]: a 200 from the uploader is **not** evidence.
Open the returned link and look at it.

**Trap that will fool you:** `lists.html` renders **two `<thead>` rows** — the file
browser's 7-column header AND the grid's real header. `document.querySelectorAll('thead th')`
flattens both and offsets every index by 7, which makes correct data look catastrophically
misaligned. Scope to the second row:
```js
const hr = [...document.querySelectorAll('thead tr')][1];
```
Body rows carry 2 leading cells (checkbox + row number) before the data columns.

**Done-rule:** a screenshot showing the right row count with names/emails aligned.

### Step 5 — Report the link
Give the user the `lists.html#<id>` link in your reply. A list they cannot click is a
list they will assume does not exist.

---

## Guard rails

- **Never** delete or hand-edit `~/.claude/state/list_uploads.jsonl` to quiet the guard.
- If the guard flags a file that genuinely is not a prospect list (a derivative export, a
  metrics CSV), say so plainly in your reply and stop again — the guard does not re-block
  a second time (`stop_hook_active`). Do not fake a receipt.
- The guard **fails open**: any crash allows the stop. If you suspect it is silently
  dead, test it directly:
  ```bash
  echo '{"cwd":"<dir>","stop_hook_active":false}' | ~/.claude/hooks/list-autopush-guard.sh; echo "exit=$?"
  ```
  Exit **2** = blocking correctly. Exit 0 with un-uploaded prospect CSVs present = broken.
  (It shipped broken once: a trailing `|| exit 0` swallowed python's exit-2 and turned
  every block into an allow. Verify the exit code, never just that the script runs.)
