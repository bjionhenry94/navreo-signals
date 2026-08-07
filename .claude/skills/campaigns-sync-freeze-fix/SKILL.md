---
name: campaigns-sync-freeze-fix
description: >
  Static orchestration skill that diagnoses and fixes the Navreo signals tool
  (navreo-signals.onrender.com) when it STOPS PICKING UP NEW CAMPAIGNS created in
  Smartlead — the campaigns list goes stale and newly-created campaigns never
  appear. Root class: the unified campaigns list is a federated SWR cache
  (navreo Smartlead + every client Smartlead workspace + HeyReach), and any ONE
  source erroring used to mark the WHOLE payload "degraded", which _SWRCache
  then refuses to cache — so the list froze on its last-good snapshot forever.
  This surfaced right after the multi-workspace rollout (more Smartlead calls →
  the shared 200/min budget gets brushed → a transient non-list response from
  ONE workspace froze everything). One fixed step list, per-step done-rules, a
  retry cap, and a Loop Training Mode toggle (ON by default). Use when the user
  says "the tool isn't picking up new campaigns", "new Smartlead campaigns
  aren't showing in the tool", "the campaigns list is stale/frozen", "campaigns
  page is missing the ones I just made", "run the campaigns freeze fix", or
  "/campaigns-sync-freeze-fix".
---

# campaigns-sync-freeze-fix

The tool stopped showing campaigns you just made in Smartlead. This skill finds
why, fixes it so it can't recur, and proves a brand-new campaign now appears.

## Loop Training Mode — the toggle (flip it here)

```
LOOP_TRAINING_MODE: ON      ← flip to OFF to run autonomously
RETRY_CAP: 3                ← attempts per step, BOTH modes
```

**When ON (default):** pause at EVERY step and wait for Bjion's approval before
continuing. Before running a step, check its done-rule first — if it ALREADY
passes, say so, show the evidence, and skip it. Only re-run steps that fail.
Retries are capped so it can't loop forever.

**When OFF:** run every step autonomously, no pauses — but keep every done-rule
check and the retry cap exactly as above.

**Both modes:** a step that still fails its done-rule after `RETRY_CAP` attempts
HALTS the loop with a plain-English report of what failed, what was tried, and
the exact evidence. Never mark a step done without its done-rule passing. Never
silently skip a step that fails.

## The goal (overall done-rule)

DONE when, on the LIVE host with real data, a campaign created in Smartlead
appears in the tool's campaigns list (immediately on a manual refresh, and
within the ~10-min cache TTL on a normal load) — AND the fix is structural, so
one erroring source (a Smartlead rate-limit on any workspace, or a HeyReach
outage) can no longer freeze or blank the list.

## What the bug actually is (read this first — it's the whole diagnosis)

- The campaigns page reads `GET /api/campaigns-unified` → `_compute_campaigns_unified()`
  in `app/server.py`. That function fetches campaigns **live** per source:
  navreo Smartlead (env key) + each enabled client workspace (its own key) +
  HeyReach, then merges them.
- The result is wrapped in a `_SWRCache` (`_CAMPAIGNS_UNIFIED_SWR`, 600 s TTL).
  `_SWRCache` serves a stored payload, and on staleness kicks a background
  recompute — **but it refuses to STORE any payload `is_degraded()` flags.**
- The break: `is_degraded` used to be `smartlead_error OR heyreach_error`, and
  the compute set `heyreach_error` / `smartlead_error` whenever ANY sub-fetch
  returned a non-list (a HeyReach 401, or a Smartlead **429 rate-limit** —
  `http_json` has no retry and hands the 429 body back as a dict, not a list).
  So one bad sub-fetch → degraded payload → never cached → the list serves its
  **stale last-good snapshot forever**, and campaigns created after that point
  never show up.
- Why it started with multi-workspace: each compute now makes N Smartlead
  `/campaigns` calls instead of 1, and the scorecard sweep loops every
  workspace too — far more pressure on the shared 200/min budget, so a
  freezing non-list response became common.
- The fix (mirrors `_store_outreach_payload`, which already protects the
  destinations picker the same way): each source resolves to FRESH-on-success
  or its OWN last-good-on-failure; `is_degraded` trips ONLY when navreo has no
  rows and no cached copy; a `/campaigns` non-list is retried once. No single
  transient sub-fetch failure can freeze the list again.

## Where things live

- **Deploy repo (the ONLY place to edit):** `~/navreo-signals` (git → Render
  auto-deploys on push to `main`). The iCloud copy under
  `…/Navreo/Claude/Navreo` is deprecated — never edit it for a deploy.
- **The code:** `app/server.py` → `_compute_campaigns_unified`,
  `_CAMPAIGNS_UNIFIED_SWR`, `_CU_LAST_GOOD`, `_sl_campaigns_for_ws`, `ws_key`,
  `ws_enabled`. Sibling with the SAME pattern (already resilient via its sync
  loop, so lower risk): `_compute_outreach_destinations` /
  `_OUTREACH_DESTS_SWR` — check it if the destinations PICKER freezes too.
- **Supabase:** project `fnykldftbkrccihdjayl`. `workspaces` (id, api_key,
  status, campaign_filter), `sync_progress` (per workspace+day; `last_error`
  reveals account-wide Smartlead rate-limiting). The `campaigns` table is the
  daily BACKUP mirror — it deliberately drops drafts and <500-send campaigns,
  so it is NOT the list's source and its staleness is EXPECTED (don't chase it).
- **Keys:** `~/.navreo-keys.env` — `SMARTLEAD_API_KEY` (navreo),
  `HEYREACH_API_KEY`, `<CLIENT>_SMARTLEAD_API_KEY`. NB the local HeyReach key
  can be stale even when the Render one works — test the source that the SERVER
  actually uses, not just the local key (see Step 2).

## Standing laws (bind every step)

- **Verify on the LIVE host, headless.** The app is login-gated (`/api/version`
  and `/api/campaigns-unified` 401 anonymously). Mint a session cookie:
  `cookie = base64url("bjion@navreo.ai|<exp>") + "." + HMAC_SHA256(sha256(SUPABASE_SERVICE_ROLE_KEY + ":navreo-session-v1"), payload)`
  then `curl -H "Cookie: navreo_session=<cookie>"`. Use **curl, not urllib**
  (macOS cert issue). `/healthz` is the only unauthenticated route.
- **Safe deploy, never clobber.** `~/navreo-signals` often has uncommitted WIP
  and can sit behind `origin/main` (parallel sessions). Do NOT push from a dirty
  tree. Work in a **fresh worktree at `origin/main`**
  (`git worktree add -b fix/… <path> origin/main`), edit there, `git add` the
  file explicitly (never `git add -A`), `git diff` must show only the intended
  hunks, `git push origin HEAD:main` (fast-forward). Leave the main working
  tree's WIP untouched.
- **Deploy lag:** the served bundle trails `/api/version` by ~1 min. Confirm the
  new commit AND real behaviour, not the version alone.
- **Smartlead:** 200 req/min shared budget; a 429 returns a JSON error body, not
  a list. Never save sequences. Client calls use the CLIENT key; navreo uses the
  env key.
- **Additive, never replace.** The list must never shrink for an existing
  source. The only acceptable "empty source" is one that genuinely has no rows
  and no cached copy.

## Steps

### Step 0 — Preflight (clean base + reachability)
**Do:** Confirm `/healthz` = 200. In `~/navreo-signals`: `git fetch`; create a
throwaway worktree at `origin/main` for any edits (do not touch the main working
tree). Confirm `~/.navreo-keys.env` has `SMARTLEAD_API_KEY` and
`SUPABASE_SERVICE_ROLE_KEY`. Mint the session cookie and confirm
`GET /api/version` returns 200 with a commit.
**Done-rule:** `/healthz` 200, cookie works (version 200 + commit hash recorded),
worktree at `origin/main` exists.

### Step 1 — Reproduce: what is the tool missing?
**Do:** Pull the live navreo campaigns straight from Smartlead
(`GET https://server.smartlead.ai/api/v1/campaigns?api_key=<navreo key>`) and note
the newest few by id/created_at. Pull the tool's list
(`GET /api/campaigns-unified`) and diff: which live campaign ids are absent from
`rows`? Record `smartlead_synced_at`, `smartlead_count`, `heyreach_count`,
`smartlead_error`, `heyreach_error`, `workspace_errors`.
**Done-rule:** either a concrete list of live campaign ids missing from the tool
(freeze confirmed — proceed), OR every recent live campaign is present and the
payload is fresh (no freeze — record that and jump to Step 5 to prove it).

### Step 2 — Identify the failing source
**Do:** Test each source the SERVER uses, live: navreo `/campaigns`, every
enabled client workspace's `/campaigns` (keys from `workspaces` table /
`~/.navreo-keys.env`), and HeyReach `POST /campaign/GetAll` with `X-API-KEY`.
Cross-check `sync_progress.last_error` for account-wide Smartlead rate-limiting.
Read `is_degraded` on `_CAMPAIGNS_UNIFIED_SWR` and confirm whether a set
`*_error` is what's blocking caching.
**Done-rule:** the failing source(s) named with evidence (HTTP code + body), AND
the poisoning path confirmed (a `*_error` field is tripping `is_degraded`, so
_SWRCache won't cache the fresh recompute). If NO source currently errors, the
freeze was a past transient — still apply Step 3 (structural fix) so it can't
recur.

### Step 3 — Apply the resilience fix (per-source last-good)
**Do:** In the worktree's `app/server.py`, ensure `_compute_campaigns_unified`
resolves EACH source to fresh-on-success or its own last-good-on-failure
(`_CU_LAST_GOOD`), retries a transient non-list once (`_sl_campaigns_for_ws`),
and sets `smartlead_error` (the only degrade trigger) ONLY when navreo has no
rows and no cached copy. `is_degraded` = `bool(p.get("smartlead_error"))` only —
never on `heyreach_error` or `workspace_errors`. Keep HeyReach's last-good so
its campaigns don't blink out. `python3 -m py_compile app/server.py`.
**Done-rule:** compiles clean; a dry logic check shows a navreo-429 cycle AND a
HeyReach-down cycle each still yield a CACHEABLE payload containing the fresh
navreo campaigns; only "navreo has nothing at all" degrades. `git diff` touches
only the campaigns-unified block.

### Step 4 — Deploy (safe-deploy)
**Do:** From the worktree: `git add app/server.py` (explicit), review `git diff`,
commit with a clear message, `git push origin HEAD:main`. Wait for Render.
**Done-rule:** `GET /api/version` = the new commit AND the app is up
(`/healthz` 200, boot clean). Deploy-lag law: also confirm real behaviour in
Step 5, not the version alone.

### Step 5 — Verify with a REAL new campaign (the task's verification)
**Do:** Create a clearly-labelled probe draft in Smartlead
(`POST /campaigns/create`, name e.g. `zzz-sync-probe-<timestamp>`). Force a fresh
tool compute (`GET /api/campaigns-unified?refresh=true`) and confirm the probe's
id appears in `rows`. Then DELETE the probe (`DELETE /campaigns/<id>`) and
confirm it's gone from Smartlead. (Equally valid: use the newest genuine
campaigns from Step 1 as the test case and skip creating/deleting a probe.)
**Done-rule:** the probe (or a genuine just-created campaign) is present in the
live tool payload, and any probe created here is deleted afterwards (zero
residue). State the TTL honestly: immediate on refresh, ≤10 min on normal load.

### Step 6 — Wrap
**Do:** Report the confirmed failing source, the structural fix, and the
before/after (missing-ids → now-present). Flag any follow-up that's a credential,
not code — e.g. if a client or HeyReach key is genuinely expired, it must be
refreshed in the Render env + `~/.navreo-keys.env` (the fix stops it freezing the
list, but that source's campaigns stay absent until its key is fixed). Write/
update the ship memory + MEMORY.md.
**Done-rule:** report delivered with evidence; any credential follow-up named
explicitly; memory updated.

## Notes
- The Supabase `campaigns` mirror lagging (e.g. newest created weeks ago) is a
  RED HERRING — it's the backup sync, which drops drafts and <500-send
  campaigns by design. The list source is the live `_compute_campaigns_unified`,
  not that table.
- If the destinations PICKER (header dropdown) also freezes, the same fix goes
  in `_compute_outreach_destinations` / `_OUTREACH_DESTS_SWR` — but it already
  has a resilient background sync loop, so check it before assuming.
