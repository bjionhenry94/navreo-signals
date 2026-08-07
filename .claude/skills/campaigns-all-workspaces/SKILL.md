---
name: campaigns-all-workspaces
description: Static orchestration skill that makes the Campaigns section at navreo-signals.onrender.com/app/campaigns.html show EVERY campaign from EVERY workspace under the tool's management (navreo + every client Smartlead workspace), not just Navreo's, and folds that same all-workspaces set into the daily optimisation routine so client campaigns get optimised too. Federates the scorecard inventory + the crunch across server.ws_enabled(), labels each row with its owning workspace, and reconciles tool-vs-platform by id per workspace. Fixed steps, per-step LIVE done-rules, retry cap, Loop Training Mode toggle (ON by default). Use when the user says "campaigns only show Navreo", "client campaigns are missing from the campaigns tab", "show all workspaces in campaigns", "run campaigns-all-workspaces", or "/campaigns-all-workspaces".
---

> **SUPERSEDE NOTE (2026-08-02, platform-wide-stabilise):** app/campaigns-classic.html was REMOVED from the repo and live site (it 404s). Any step or done-rule below that expects it to serve/render is historical — skip or adapt it; the campaigns cockpit at app/campaigns.html is the only campaigns page.

# campaigns-all-workspaces

## LOOP TRAINING MODE — TOGGLE HERE

```
LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous
MAX_RETRIES_PER_STEP = 3
```

Flip the one line above to change modes. Announce the active mode in the first line of every run.

**When ON (default)**
- Pause at the end of **every** step and wait for Bjion's explicit approval before starting the next.
- Before running a step, check its done-rule **first**. If it already passes, **skip the step**, say so in one line, and move on.
- Only (re-)run steps that fail their done-rule.
- The retry cap still applies. Never loop a step forever.

**When OFF**
- Run every step autonomously, no pauses.
- Still check every done-rule, still honour the retry cap. Report once at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule. On cap-hit: stop that step, record it FAILED with the reason and retry count, continue to the next step, and surface it in the final report. Never silently exceed the cap.

---

## THE GOAL

Every campaign in every workspace the tool manages is managed from the Campaigns section: it renders as a row on `https://navreo-signals.onrender.com/app/campaigns.html`, tagged with its owning workspace, or it sits in a **named, stated** exclusion bucket (ARCHIVED / DRAFTED). And the **same** all-workspaces set is what the daily optimisation routine iterates — so client campaigns are optimised, not just Navreo's. No campaign is invisible or un-optimised just because it belongs to a client workspace.

Repo: `~/navreo-signals`, branch `main`, Render auto-deploys on push. Managed workspaces = `server.ws_enabled()` (currently navreo, asteri, krg, grout — **read it live, never hardcode**).

## WHERE THIS PICKS UP (do not re-derive)

`[[campaigns-all-visible]]` already fixed the *insight-gated* bug: `app/campaigns.html` now builds its row set from `campaign_scorecard` (the inventory), LEFT-joining insights, with a coverage guard. That work assumed a **single workspace** (Navreo's Smartlead key). This skill extends that same architecture to **all** workspaces. Read `[[campaigns-all-visible]]` before touching `campaigns.html` — its gotchas (the second hardcoded `tiers` list, the `name` copy bug, the 150-id live-status cap, prune-only-off-a-non-empty-list) all still apply, now multiplied per workspace.

The federation pattern to copy is `[[inbox-manager-all-workspaces]]`: mirror rows out of the per-workspace feed server-side, stamp `workspace` on every row, label with `workspaces.display_label` (`[[client-workspace-labels-one-source]]` — one source feeds all seams, a new workspace needs no code edit), and keep Navreo rows byte-for-byte unchanged (additive only).

## STANDING LAWS

- **Additive, never replace.** Navreo rows stay exactly as they are; client rows are added on top. Do not touch `app/campaigns-classic.html`. Confirm any removal with Bjion first.
- **Deploy source:** `~/navreo-signals`, `main`, Render auto-deploys on push. The iCloud copy is deprecated and reverts edits — never edit it.
- **Per-workspace keys only.** Any Smartlead read or write for a client row MUST route through `ws_key(workspace)`, never the env `SMARTLEAD_API_KEY`. A grep must prove no code path reaches a Smartlead call with the env key for a `workspace != navreo` row. This is the single most important guardrail — a wrong-key write hits the wrong client's account.
- **NEVER send to real prospects** (`[[never-send-to-real-prospects]]`). The optimisation routine tunes campaign *settings/copy*; it must never trigger a send. Any Smartlead write checks the row's workspace + status first.
- **Grout is pre-launch** (`[[grout-workspace-added]]`): its 120 boxes are warming and its campaigns may be empty/draft. An empty Grout inventory is **correct**, not a failure. Optimisation must not act on a pre-launch workspace's campaigns.
- **LIVE-verify or it is not done.** Only the rendered page on `navreo-signals.onrender.com` counts. Anonymous curl proves nothing (auth gate 302s). Verify with a minted `navreo_session` cookie per `[[signals-live-verify-recipe]]` and read the DOM, not screenshots.
- A campaign with no insight renders as an **honest** row: real stats, workspace label, no invented verdict.
- No em dashes in UI copy. Times render browser-local with the timezone named.

---

## THE STEPS

Each step is finished only when its LIVE done-rule passes.

### Step 0 — Pin ground truth, per workspace
- `~/navreo-signals` clean, on `main`, level with `origin/main`.
- Read `server.ws_enabled()` live. For **each** enabled workspace, pull its Smartlead campaign inventory with `ws_key(workspace)` and record a count by status (ACTIVE / PAUSED / DRAFTED / ARCHIVED). This is the "before" per-workspace matrix.
- Read the current live `campaigns.html` (authed DOM) and record how many rows render **per workspace** today. Expected finding: only Navreo rows render. That gap is the artifact, not a failure.
- **Done-rule:** repo clean on `main`; a written before-matrix listing every enabled workspace with its Smartlead campaign counts and its current rendered-row count.

### Step 1 — Federate the scorecard sync across workspaces
- Find the inventory sync (`_scorecard_sync_all()` in `app/server.py`). Confirm whether it iterates `ws_enabled()` or only pulls Navreo's key. If single-workspace, extend it to loop every enabled workspace, calling `GET /campaigns` with that workspace's `ws_key`, and stamp `workspace` on every `campaign_scorecard` row it upserts.
- Keep the existing pace and batched upserts. One bad campaign or one failing workspace must never abort the whole cycle — record the failure and continue.
- Prune only off a **non-empty** list, **scoped per workspace** (a workspace whose pull errored must not have its rows pruned — a rate-limit error reads as end-of-list and would wipe that client's inventory).
- **Done-rule:** after one sync cycle, `campaign_scorecard` contains workspace-stamped rows for **every** enabled workspace, and each workspace's count matches its independent Smartlead `GET /campaigns` count. A campaign created today in a client workspace appears within one cycle.

### Step 2 — Make the list workspace-aware
- In `app/campaigns.html`: the row set already comes from the scorecard (per `[[campaigns-all-visible]]`). Remove any implicit Navreo-only filter so rows from all workspaces render. Each row shows its workspace label via the one-source `display_label` (`[[client-workspace-labels-one-source]]`).
- Re-check the **second** gate `[[campaigns-all-visible]]` flagged (the hardcoded `tiers` list in `renderRows()`) — make sure it does not silently drop client rows.
- The 150-id `/api/cockpit/live-status` cap is now shared across more campaigns: spend it on running campaigns first (across all workspaces), fall back to synced status for the rest.
- **Done-rule:** authed DOM read of live `campaigns.html` renders rows for every enabled workspace, each carrying its workspace label; total rendered rows equal the render set size (non-ARCHIVED) summed across workspaces; all pre-existing Navreo rows unchanged (same count as a Navreo-only control).

### Step 3 — Workspace filter + coverage guard
- Add a workspace filter/segment to the page (All / per-workspace), reusing the existing client/status filter pattern. Default view shows all workspaces.
- Extend the coverage line (from `[[campaigns-all-visible]]`) to read **per workspace**: e.g. "navreo 1,053 tracked · asteri 40 · krg 22 · grout 0 · 0 unaccounted for". Unaccounted-for > 0 in any workspace renders as a visible warning, never a silent pass.
- **Done-rule:** the workspace filter shows exactly the independent per-workspace set for each selection; the coverage line renders live with correct per-workspace numbers and reads 0 unaccounted for in every workspace.

### Step 4 — Fold all workspaces into the daily optimisation routine
- Find the daily optimisation / morning crunch scope list (the routine that feeds `campaign_insights` / drives `[[lilly-optimiser]]`). Repoint it so its scope is driven by the **all-workspaces scorecard** (every ACTIVE campaign in every enabled workspace), not a Navreo-only list.
- Every optimisation read/write for a client campaign routes through `ws_key(workspace)`. Pre-launch workspaces (Grout) are skipped with a stated reason. No optimisation step may trigger a send (`[[never-send-to-real-prospects]]`).
- If volume forces a cap on how many campaigns crunch per day, the cap must be **stated on the page**, never silent, and must not starve any one workspace.
- **Done-rule:** a routine run produces fresh `campaign_insights` (or the crunch's output) for ACTIVE campaigns in **more than one** workspace, each written against the correct workspace key; a grep confirms no client optimisation path uses the env key; Grout is skipped with a logged reason.

### Step 5 — Ship and LIVE-verify
- Commit, push `main`, poll `/api/version` until Render serves the new build (`[[signals-live-verify-recipe]]`).
- Verify on the live host with a minted-cookie authed DOM read — not a local render, not a source grep.
- **Done-rule:** live `campaigns.html` shows campaigns from every enabled workspace with correct labels and stats; the per-workspace coverage line reads 0 unaccounted for; the optimisation routine's next scheduled/triggered run covers all workspaces.

---

## THE FINAL DONE-RULE — cross-platform reconciliation, per workspace

The loop is done only when the tool and the platforms reconcile **by id, for every enabled workspace**:

1. **Platform A, Smartlead:** for each workspace in `ws_enabled()`, pull every campaign with `ws_key(workspace)`. Set A(ws) = all ids.
2. **Platform B, the tool:** authed DOM read of live `campaigns.html` + `/api/campaign-scorecard`, grouped by workspace label. Set B(ws) = rendered ids.
3. For each workspace compute `A(ws) \ B(ws)` and `B(ws) \ A(ws)`.

**PASS requires, for every enabled workspace:**
- `A(ws) \ B(ws)` contains only ids in a stated exclusion bucket (ARCHIVED / DRAFTED) and **zero** ACTIVE campaigns.
- `B(ws) \ A(ws)` is empty — the tool never invents a campaign the platform lacks, and never mislabels one workspace's campaign as another's.
- For 3 campaigns spot-checked at random from each workspace, sent / replied / positives in the tool match that workspace's Smartlead `/analytics` exactly.
- The daily optimisation routine's scope, read live, contains ACTIVE campaigns from every non-pre-launch workspace.

Print the reconciliation as a per-workspace table: workspace, total in Smartlead, total rendered, excluded-by-bucket (bucket named), unaccounted-for, and whether it's in the optimisation scope. **Unaccounted-for must be 0 in every workspace.** Anything else is a FAIL, no matter how good the page looks.

---

## FINAL REPORT (always, both modes)

- The before/after per-workspace matrix: Smartlead counts, rendered rows, in-optimisation-scope.
- The per-workspace reconciliation table above.
- Every step: PASSED / SKIPPED (already passing) / FAILED with reason and retry count.
- Commits pushed, with sha.
- Confirmation, in plain English and by workspace name, that client campaigns now both render and get optimised — never a bare "done".
