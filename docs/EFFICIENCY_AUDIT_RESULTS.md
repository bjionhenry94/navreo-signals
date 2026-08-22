# Navreo Signals — Efficiency Audit Results (2026-08-22)

Branch `audit/efficiency-2026-08-22`. Orchestrated by Sol (gpt-5.6), executed by Opus 4.8.
Method: reproducible harness (`scripts/bench_efficiency.py`) — warm p50/p95 + gzipped wire bytes,
local dev server, minted session cookie. Each fix measured before/after and Sol-adjudicated PASS.

## Root cause
The tool already has a mature stale-while-revalidate cache layer (`_SWRCache`), but several
read endpoints slipped through it and hit Supabase synchronously on **every** page load, and two
payloads shipped far more data than any consumer used. Same slowly-changing data was also being
held in two caches at once (prospects).

## Fixes shipped (all Sol-PASS)

| # | Change | Before | After | Commit |
|---|--------|--------|-------|--------|
| 1 | SWR-cache `/api/collisions` (300s) | p50 **2.38s** / p95 4.60s | **0.0008s** / 0.0018s | 7d61664 |
| 2 | Server-side `finding_type` filter for `/api/notifications` (deliverability.html) | 923 rows / **1.14 MB** | 144 rows / **161 KB** (−86%) | 7b25f73 |
| 3 | Strip duplicate `prospects` from `/api/sources` UI cache; re-attach on non-slim from canonical `read_drafts()` | cache held **19.6 MB** twice | cache **262 KB**; non-slim byte-identical | 63e82d5, 4ca5230 |
| 4 | SWR-cache `/api/pool-pulls` rows + `_client_cap_history` blob | pool-pulls **0.63s**, fleet-capacity **~1s** | **0.001s** / **0.0015s** warm | abf81db |

## Impact against the three goals
- **Reduce data surface**: `/api/notifications` −86% for deliverability; `prospects` (19.6 MB) now
  live in exactly one cache instead of two; non-slim `/api/sources` composed on demand.
- **Load speed**: the four endpoints that hit Supabase on every load now serve from cache in
  ~1 ms warm (2000–3000× on the collisions path). campaigns/deliverability/optimise page loads
  no longer block on these serial 1–5 s calls.
- **Stability / memory**: removed a documented ~19.6 MB duplicate from the 512 MB (OOM-prone)
  web instance; degraded-guards mean a Supabase outage is never cached; live job-progress overlay
  preserved on cached pool rows.

## Verification
`git log audit/efficiency-2026-08-22`; re-run `python3 scripts/bench_efficiency.py --label check`
against a local server (`NAVREO_NO_BG=1 DELIV_MOCK=1 python3 app/server.py 7901`).
Baselines: `docs/bench/baseline.{json,md}`, `docs/bench/after-*.{json,md}`.

## Not done / follow-ups (deeper, higher-risk — recommend separate PRs)
- Cold-start: `_pg_docs("sources")` still pulls 19.6 MB over the wire on first fill (17–22 s);
  eliminating that needs a projected/denormalised sources read (no nested `prospects` in the
  jsonb doc) or a materialized meta column — schema-touching, out of this audit's bounded scope.
- Front-end: the standalone pages inline all CSS/JS/markup (campaigns 483 KB raw / 150 KB gz).
  Extracting shared cacheable assets would cut repeat-visit parse/transfer but is a large,
  cross-page refactor.
- Monolith: `app/server.py` is 23 k lines; decomposition would help maintainability/stability
  but is not a load-speed lever on its own.
