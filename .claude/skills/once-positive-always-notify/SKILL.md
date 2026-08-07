---
name: once-positive-always-notify
description: Static orchestration skill that closes the notification hole proven by the Gabriel Benmergui miss (2026-07-20) — a lead categorised Interested replied again on the subsequence, got flipped to Not Interested, and NO Slack alert ever fired, so the thread silently vanished mid-conversation. Ships a once-positive-always-notify guarantee — any new reply from a lead with ANY prior positive category (Supabase replies history) alerts internally within minutes, whatever the new category, on whatever campaign or subsequence it lands. Diagnoses the miss on the live pipeline first, fixes at the layer the evidence picks (app-side safety net on the replies archive by default), and proves it with capped mock replays including never-positive→negative staying silent. One fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle (ON by default). Use when the user says "run the once-positive notify fix", "a previously interested lead replied and we never got notified", "fix positive-thread notifications", or "/once-positive-always-notify".
---

# Once Positive, Always Notify

On 2026-07-20, gabriel@silver.dev (campaign **"Navreo - Recruitment - Claude Code offer - Soft"**) was categorised **Interested Reply** at 12:33 EDT and pushed to the "Interested Reply" subsequence. Bjion replied. Gabriel replied back that evening ("Thanks for the follow-up… I'll keep you in mind"), his category flipped to **Not Interested**, and **no notification of any kind fired**. Bjion was mid-conversation and never learned the thread had ended — the lead just vanished from view.

The structural hole: every alert in the pipeline keys off the reply's category **at processing time** (routeA announces fresh positives; routeB's 🚨 requires the existing category to still be positive). A lead's positive **history** is consulted nowhere. So the exact class of reply Bjion most needs to see — a previously-interested lead saying no, asking to stop, or going sideways — is the class guaranteed to be silent.

**The guarantee this skill ships:** any new reply from a lead who has EVER had a positive category produces exactly one internal Slack alert, within minutes, naming the original positive context and the new category — regardless of the new category and regardless of which campaign or subsequence the reply lands on.

## ⚙ Loop Training Mode: **OFF**   ← running autonomously. Flip this ONE line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for Bjion's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go. One OFF-mode extra: Step 6's backfill of historical missed alerts is REPORT-ONLY (no backfill posts without explicit approval).

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

## Safety gates (both modes, non-negotiable)

- **Slack blast radius:** max **4** mock alert posts total, internal channels only (#interested-replies `C096Q9LHQGZ` or its thread), each tagged as a test in-thread. Client channels get NOTHING — client-channel alerts for this class are a deliberate scope-out (standing ruling); surface as a question, never build unasked.
- **No Smartlead category writes from mocks.** Mocks enter at the fix's own entry point (synthetic `replies` rows), never by replaying an uncategorised lead through the full categoriser. Any real lead touched: read its category before and after — must be unchanged. Remember Smartlead 200s unknown emails, so a synthetic-lead "success" through a Smartlead-hydrating path proves nothing.
- **Setter product untouched.** No change to Setter queue/intake/draft/send behaviour, pills, autopilot, or the master switch; `ensure_webhooks` stays a no-op. The reply-sync/pipeline code is fair game even where it lives in `setter.py` — the boundary is product behaviour, and Step 6 proves queue + pill counts unchanged.
- **Categoriser reuse law (Bjion ruling 2026-07-15):** GPT categorisation stays in Make 9251436. Never re-implement categorisation in the app. This skill adds a notification guarantee, not a categoriser.
- **Funnel not widened:** a never-positive lead's negative reply must stay silent — verified by mock, not assumed.

## Goal — THE DONE-RULE (single source of truth)

> A new reply from an ever-positive lead alerts **exactly once** in #interested-replies with the original positive context + new category, proven by mocks read back from Slack and Supabase (never success labels): (1) previously-positive → negative alerts; (2) previously-positive → positive alerts once, not twice; (3) never-positive → negative stays silent; (4) the same reply delivered twice alerts once. The alert path is fail-closed and retryable (a durable alert-marker stamped only after Slack accepts, unmarked rows retried by cron) so archive-without-Slack can never go permanently silent again. The Gabriel case, re-driven, produces the alert the original event missed. Setter behaviour byte-for-byte unchanged. All of it, or it isn't done.

## Ground truth (as of 2026-07-22 — RE-VERIFY in Step 1, this path changes)

- **The path:** Smartlead reply → (a) workspace webhook `4135325` and (b) `/api/cron/reply-sync` backstop (pg_cron `reply-sync-tick` every 3 min) → Make **9251436** hook `https://hook.eu2.make.com/6mda3nqyrtm8u4x9ihilymra4z70aaug`. routeA (per-campaign "no existing category" gate) → GPT → POST `/category` → Slack for positives; routeB (existing category in positive set `1,2,5,78386,83039,83731,86207,125938`) → 🚨 internal re-reply alert, gated on `61.data.inserted = true`; routeC = lookup-fail alert. Positives also POST hook `4001002` → Make **8946472** → client cards. Archive = Supabase `replies` (project `fnykldftbkrccihdjayl`), dedup key `smartlead_message_id = "{email_lead_id}-{last_reply_time}"`.
- **Candidate mechanisms for the Gabriel miss, in suspicion order:** (1) subsequence reply processed under the per-campaign gate → routeA → fresh categorisation straight to Not Interested → Slack skipped (positives-only) — the known subsequence silent-drop class in its negative form; (2) category already flipped before processing → routeB gate false → silence; (3) the follow-up never reached the categoriser at all (check `replies` + hook logs; reply-sync permanently skips already-archived rows — the archive-without-Slack class).
- **The durable ever-positive record:** prior `replies` rows for the same lead email (workspace-scoped) with a positive category. The Setter reads this table — synthetic mock rows must use a non-`navreo` workspace value so they can never enter the real Setter queue (confirm the Setter filters by workspace in Step 1).
- **Access:** all keys in `~/.navreo-keys.env` (Smartlead, Supabase + `SUPABASE_ACCESS_TOKEN`, `MAKE_API_TOKEN`, `SIGNAL_PULL_TOKEN`). Make zone eu2, team 536258; hook logs at `/hooks/{id}/logs/{logId}` expose full inbound payloads — that is how lag/misses get proven. App = `~/navreo-signals` **deploy repo** (never the iCloud copy; iCloud reverts edits) → live at navreo-signals.onrender.com.
- **Standing gotchas:** every MCP deploy of edge function `ingest` resets `verify_jwt=true` → must PATCH it false after EVERY deploy or Make's token calls 401 and archiving dies. Make filters: outer=OR, inner=AND; `statusCode = 200` guards everywhere; `ifempty(x;"")=""` never raw truthiness; snapshot blueprint before PATCH; fresh-GET read-back after. Schema-freeze law: writes with a key that has no matching column die silently — add columns first.

## Steps

### Step 1 — Trace the Gabriel miss end-to-end (read-only)
Pull his rows from `replies` (the 12:33 Interested reply AND the evening follow-up — is the follow-up archived, and with what category/timestamps?). Pull the Make executions and hook logs for both events; establish which route fired, or that nothing fired. Re-fetch the 9251436 blueprint and confirm the route gates named above against what is actually deployed — never assert a filter from memory. Name the miss mechanism against the three candidates (invent a fourth only if the evidence forces it). Snapshot baselines: Setter queue + pill counts, `replies` schema/columns, and confirm the Setter's workspace filtering for mock isolation.
- **Done-rule:** (a) both Gabriel events located (or their absence proven) with row ids / execution ids / hook-log ids cited; (b) the miss has ONE named, evidenced mechanism; (c) the generalised hole stated in one sentence; (d) baselines recorded. FAILED if any gate or filter is asserted from this file rather than the fetched blueprint.

### Step 2 — Design the ever-positive check (surface, then lock)
Default design, veto-able: an app-side safety net at the point every reply provably passes — the `replies` archive. On each new row (hooked into the reply-sync path or a sibling 3-min sweep): if the lead email (workspace-scoped) has ANY earlier positive-category row AND this row carries no alert-marker → post to #interested-replies ("🔁 Previously-interested lead replied — now categorised {X}" + lead, company, campaign + subsequence, original positive date, snippet, Smartlead link) → stamp the marker only after Slack accepts. Unmarked rows retried next tick (fail-closed, retryable). To avoid double-alerting the still-positive class routeB already covers: default scope = fire when the new category is NOT in the positive set, and verify by mock that routeB really fires for the still-positive case; if routeB proves flaky, widen this check to all ever-positive re-replies and retire routeB with Bjion's sign-off. Alert ledger doubles as the platform record (marker column or log row keyed by `smartlead_message_id`).
- **Done-rule:** design written down covering: layer + trigger point, exact ever-positive predicate, marker/retry semantics, alert copy, the routeB overlap decision, and any schema change. Training ON: approved by Bjion. It re-implements no categorisation and touches no Setter product behaviour.

### Step 3 — Build it
Apply any schema change first (schema-freeze law), then the code. Local tests must cover the four Goal scenarios as unit cases plus: marker stamped only on Slack success; unmarked row retried; workspace scoping (a positive history in another workspace does not trigger).
- **Done-rule:** local test run passes all four Goal scenarios + the three extras, and the full existing test suite still passes (`settle_background_reads()` before asserting seeded reads, per house test law).

### Step 4 — Deploy
Push the deploy repo, wait for Render, verify a unique marker in the deployed asset (deploy check, not done-evidence). If the `ingest` edge function was touched: redeploy, immediately PATCH `verify_jwt=false`, and prove Make's token call still 200s. If a Make scenario was patched: snapshot → PATCH → fresh-GET diff shows exactly the intended change → still ACTIVE.
- **Done-rule:** live host serves the new code; `verify_jwt` confirmed false (if touched); any patched scenario ACTIVE with a clean read-back diff; zero collateral diff anywhere.

### Step 5 — Mock verification on live (the Verification)
Max 4 posts, announced first in Training ON, all read back from Slack + Supabase — never from the app's or Make's success labels. (a) **The Gabriel replay:** re-drive his real archived follow-up through the new check → the alert he never got posts, naming Interested→Not Interested (this one real post closes the original incident). (b) **Prev-positive → negative** synthetic (non-navreo workspace, `is_test`-style flagged): exactly one alert. (c) **Prev-positive → positive** synthetic: exactly one alert total across the new check + routeB, not two. (d) **Never-positive → negative** synthetic: zero posts in the window, read back. Then re-run the check twice over the same synthetic row: still one alert (marker holds). Confirm any real lead's Smartlead category unchanged, delete/flag all synthetic rows, and confirm none ever appeared in the Setter queue.
- **Done-rule:** all four outcomes evidenced with Slack permalinks / zero-post windows + row ids; dedupe re-run holds; ≤4 posts; zero client-channel posts; zero Smartlead category writes; synthetics cleaned; Setter queue clean of them.

### Step 6 — Sweep the recent window + prove the Setter untouched
Query the last 14 days for other Gabriels: replies from ever-positive leads with no alert on record. Deliver the list (lead, campaign, dates, new category). Backfill alerts only with explicit approval — Training OFF means report-only. Re-check Setter queue + pill counts against the Step 1 baseline. Write the final report.
- **Done-rule:** sweep table delivered with a named count (not "several"); backfill state explicit (done-with-approval or reported-only); Setter numbers match baseline; final report written.

## Final report (always, both modes)

One summary: per-step PASS / SKIPPED / FAILED with retry counts; the named miss mechanism with its evidence; the design as locked (layer, predicate, routeB decision); commit SHA + deploy proof (+ `verify_jwt` state if touched); each mock with its Slack permalink or zero-post window and latency; the sweep count and what was backfilled vs reported; Setter baseline vs after. Name the numbers and channels — "notifications fixed" alone is not a report.

## Hard don'ts

- Never gate the new alert on the CURRENT category being positive — the entire point is the ever-positive history.
- Never exceed 4 mock posts, post to a client channel, or let a mock write a Smartlead category.
- Never re-implement GPT categorisation in the app, and never change Setter product behaviour (queue/draft/send/pills/autopilot/master switch).
- Never stamp the alert-marker before Slack accepts, and never build the alert fire-and-forget — unmarked rows must retry.
- Never diagnose from this file's ground truth alone — re-fetch blueprints, hook logs, and live rows.
- Never edit the iCloud copy or call a local grep done-evidence — the deployed host and read-back Slack posts are.
- Never deploy `ingest` without re-PATCHing `verify_jwt=false`, and never PATCH a Make scenario without snapshot + fresh-GET read-back.
- Never let a synthetic row reach the real Setter queue or survive the run.
- Never exceed a retry cap or report done while any Goal scenario fails — a cap-hit is FAILED with the gap named.
