---
name: reply-slack-notification-audit
description: Static orchestration skill that audits the whole reply→Slack notification path and fixes it — why positive replies (Amplifyy especially) reach the Appointment Setter but produce NO Slack alert, and why re-replies from already-interested leads alert inconsistently or get mislabelled "New Positive Response". Reconciles the Supabase `replies` archive against what actually posted in each Slack channel, root-causes every miss, patches the Make scenarios (9251436 categoriser + 8946472 client card), then proves the fix with capped dummy replays. The Setter is working and must not change. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "audit the reply system", "we're not getting Slack notifications for positive replies", "the Amplifyy replies never hit Slack", "interested leads replying again don't alert", "fix the reply notifications", or "/reply-slack-notification-audit".
---

# Reply → Slack notifications: audit and fix

Replies are routing into the Appointment Setter correctly (`navreo-signals.onrender.com/app/setter.html`). That half works and stays exactly as it is. The broken half is the **notification** half: positive replies are not reliably posting to Slack, and re-replies from leads already tagged interested alert inconsistently. This skill audits the whole path, root-causes every miss against the live archive, fixes the Make scenarios, and proves it with capped dummy replays. Static loop — fixed steps, each with a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for Bjion's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record the step as FAILED with the reason, continue to the next step if it doesn't depend on the failed one, and surface every FAILED step in the final report. Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Blast-radius gate (both modes, non-negotiable):** every Slack post this skill causes is a real message in a real channel, and every categoriser replay can re-tag a real lead in Smartlead. **Cap: max 5 dummy replays total across the whole run.** Replays only use leads whose category is ALREADY positive (routeB is alert-only and never re-tags, per `feedback_additive_never_replace`) or a lead Bjion explicitly nominates as a test. Never replay an uncategorised live lead just to see what happens.

## Goal

> Every positive reply that lands in the Supabase `replies` archive also produces exactly ONE Slack alert, in the correct channel, within minutes — and a reply from a lead already tagged interested is labelled as a re-reply (🔁 / 🚨), never re-announced as new. Proven by: a reconciliation showing zero unexplained archive-vs-Slack gaps over the audit window, a named root cause for every Amplifyy miss found, and capped dummy replays that land visibly in the right channel with the right header. The Setter's behaviour is byte-for-byte unchanged. Anything less = not done. On a retry cap-hit, stop and report the gap honestly.

## Ground truth (as of 2026-07-16 — re-verify in Step 1, this path has changed repeatedly)

**The path:** Smartlead reply → (a) workspace webhook hook `4135325` → Make **9251436** (categoriser) *and* (b) the `/api/cron/reply-sync` backstop (pg_cron every 3 min, commit `dbe5165`) pulling master-inbox → same hook. 9251436: GET `/leads/?email=` (module 29) → router 50 → **routeA** (module 2 gate: "no existing category *for this campaign*") → GPT categorise → POST `/category` → Slack module 33; **routeB** (module 51) = lead's existing category for this campaign is positive-sentiment (`1,2,5,78386,83039,83731,86207,125938`) → "🚨 HIGH PRIORITY — Interested lead replied again", alert-only; **routeC** (module 70) = `29.statusCode` ≠ 200 → ⚠️ alert, so a bad lookup is never a silent drop. Positives also POST hook `4001002` → Make **8946472** → the client-facing card, module **60** = Amplifyy (`C0AV6J0MFPS`), module **70** = Arnic.

**Channels:** `#interested-replies` `C096Q9LHQGZ` (Navreo's own, `client_id` null) · `#client-interested-replies` `C0B96LNPWDB` · Amplifyy `C0AV6J0MFPS`.

**Three known silent-drop classes — check each explicitly, they are the prime suspects:**
1. **Archive-without-Slack.** The reply-sync cron skips anything already in `replies` (`skipped_archived`, dedup key `smartlead_message_id = "{email_lead_id}-{last_reply_time}"`). So if a reply got archived but its Slack module errored or was filtered out, **nothing ever retries it** — it is permanently silent. This exactly fits "routed to the Setter fine, no Slack".
2. **Subsequence-campaign re-reply mislabel.** Smartlead spawns follow-up campaigns ("Interested Reply" 3477410, "Meeting Request" 3477411) when a lead goes Interested. In the *spawned* campaign the lead has NO category, so module 2's per-campaign gate passes → routeA fires → the lead is announced as brand new even though it is a continuing conversation. 8946472's own re-reply guard (reply-count from `1.history`, added 2026-07-15) is the only thing catching this on the client cards, and it was never confirmed against a real event.
3. **Filter/expression fragility.** `29.statusCode = 200` guards must be on every routeB condition and routeA's module-2 filter (a 429 body is a truthy *string* and `map()` throws on non-arrays → "Failed to evaluate filter" → deactivation). Null-vs-populated checks must use `ifempty(x;"")=""`, never raw `if(x;…)` truthiness (this broke channel routing twice on 2026-07-15). Filter JSON: **outer array = OR, inner array = AND** — `[[a],[b]]` is a gate that always passes.

**Access:** `MAKE_API_TOKEN` + Smartlead + Supabase keys in `~/.navreo-keys.env`. Make zone eu2, team 536258. Make MCP if connected, else raw REST (`GET /api/v2/scenarios/{id}/blueprint`, `PATCH /api/v2/scenarios/{id}?confirmed=true` with `{blueprint:<stringified>}`). Slack channel history via the Slack MCP (`slack_read_channel`). Make webhook-queue retention = 3 days; reactivating a scenario inside retention **auto-replays** queued webhooks — never also backfill manually or you double-post.

## Steps

### Step 1 — Re-verify the live path and pick the audit window
Re-fetch both blueprints (9251436, 8946472) and confirm every module id, filter, gate expression, and channel expression above against what is actually deployed — do not trust the ground-truth section. Check each scenario is ACTIVE and read its recent execution history for errors/deactivations. Confirm the reply-sync cron is scheduled and running. With Bjion, fix the audit window (default: last 14 days).
- **Done-rule:** (a) both blueprints fetched and every named module/filter/channel expression confirmed-or-corrected in writing; (b) both scenarios confirmed active, with any error or auto-deactivation in the window listed with timestamps; (c) reply-sync cron confirmed scheduled and ticking; (d) window agreed. FAILED if any expression is asserted from memory rather than the fetched blueprint.

### Step 2 — Reconcile the archive against Slack (this is the audit)
For the window, pull every positive-category reply from Supabase `replies`. Pull the actual message history of `C096Q9LHQGZ`, `C0B96LNPWDB` and `C0AV6J0MFPS`. Match archive rows to Slack posts by lead email + reply time. Produce three buckets: **alerted once** (correct), **never alerted** (the bug), **alerted in the wrong channel or with the wrong header** (new-vs-re-reply mislabel, or client-vs-internal misroute). Then isolate the Amplifyy subset — Bjion's specific report — and for each Amplifyy miss pull its Make execution (or absence of one) and its campaign's `client_id` and subsequence status.
- **Done-rule:** (a) a per-reply table exists covering the whole window with every row assigned to exactly one bucket; (b) the never-alerted and mislabelled counts are named numbers, not "several"; (c) every Amplifyy miss is listed individually with lead email, campaign id + name, `client_id`, reply time, whether a Make execution exists, and whether the row was archived-without-Slack; (d) alert latency (reply time → Slack time) reported for the alerted bucket, so "on time" is measured not assumed. FAILED if any bucket is estimated rather than counted.

### Step 3 — Root-cause every miss class
Assign each never-alerted and mislabelled reply to a named cause — test it against the three known classes first (archive-without-Slack, subsequence re-reply mislabel, filter/expression fragility), and only invent a fourth class if the evidence forces it. For each class, prove it: the Make execution that errored, the filter that evaluated false, the gate expression that swallowed it, or the archive row with no execution at all. Separately answer Bjion's second complaint directly — *why is re-reply alerting inconsistent* — naming the exact condition that differs between a re-reply that alerts and one that doesn't.
- **Done-rule:** (a) every miss maps to a named, evidenced cause with the specific execution/filter/row cited; (b) no miss is left "unexplained" (if one genuinely is, it is called out as an open item, not quietly bucketed); (c) the re-reply inconsistency has a stated mechanism, not a hypothesis; (d) the causes are ranked by how many replies each accounts for. FAILED if any cause is asserted without an execution, filter, or row cited.

### Step 4 — Fix, one cause at a time
Patch the Make scenarios for each cause found, smallest change first. Re-fetch and diff after every PATCH. Apply the standing rules: `statusCode = 200` guards on gate filters, `ifempty(x;"")=""` for null-vs-populated, `[[a,b]]` for AND. If a cause is archive-without-Slack, the fix must make the notification path *retryable* rather than assuming the first attempt worked — surface the design choice to Bjion before building it, since that one may need app-side work (`~/navreo-signals`, deploy repo only, never the iCloud copy). Touch nothing in the Setter path.
- **Done-rule:** (a) every ranked cause from Step 3 has either a landed patch or an explicit, agreed deferral; (b) each PATCH verified by re-fetch + diff showing exactly the intended change and nothing else; (c) both scenarios still ACTIVE and error-free after patching; (d) any app-side change is committed and pushed to `main` in `~/navreo-signals` and confirmed live on the deployed host, not local. FAILED if a scenario is left deactivated or a diff shows collateral change.

### Step 5 — Dummy tests (capped at 5, real Slack posts)
Replay real events through the hooks to prove each fixed class, using only already-positive leads (routeB is alert-only) or a Bjion-nominated test lead. Cover, at minimum: one **new** positive → correct channel with the new-positive header; one **re-reply** from an already-interested lead → re-reply header (🚨 internally / 🔁 on the client card), not "New Positive Response"; one **subsequence-campaign** reply (the 3477410/3477411 class) → right channel, right header. Announce each replay to Bjion before firing it and count it against the cap of 5.
- **Done-rule:** (a) each replay's Slack post located in the channel with its header, channel id, and latency recorded; (b) the re-reply case demonstrably does NOT say "New Positive Response"; (c) the subsequence case lands in the channel its `client_id` dictates; (d) each replayed lead's Smartlead category confirmed unchanged where the path was meant to be alert-only; (e) total replays ≤ 5. FAILED if any replay's outcome is inferred from a Make execution rather than seen in Slack.

### Step 6 — Prove the gap is closed + Setter untouched
Re-run the Step-2 reconciliation over a fresh short window (or the replayed events) and show zero unexplained never-alerted rows. Then prove the Setter is unaffected: its queue and pill counts on the live host are what they were before this run.
- **Done-rule:** (a) fresh reconciliation shows every positive archive row has exactly one correctly-headed Slack post, or each exception is named and explained; (b) no duplicate Slack posts introduced (check the double-Slack failure mode explicitly); (c) live Setter queue + pill counts match the pre-run baseline taken in Step 1. FAILED if the Setter's numbers moved or any duplicate alert appeared.

## Final report (always, both modes)

One summary: each step passed / skipped / FAILED with reason. The audit numbers — window, positives archived, alerted once, never alerted, mislabelled, and the Amplifyy subset broken out by cause. Each root cause with its evidence and how many replies it explains. Every Make PATCH (scenario, module, before → after) and any commit id + deployed confirmation. Each dummy replay with its channel, header, and latency. The closed-gap reconciliation and the Setter-unchanged proof. Name the actual numbers and channels — "notifications fixed" alone is not a report.

## Hard don'ts

- **Never change the Setter.** Its routing works. No `setter.py` intake/poll/queue changes, no re-adding campaign-level webhooks (that diversion killed Slack alerts once already — the Setter is pull-only, `ensure_webhooks` stays a no-op).
- Never exceed 5 dummy replays, and never replay an uncategorised live lead — a replay can re-tag a real lead in Smartlead.
- Never reactivate a scenario that has been down inside the 3-day webhook retention *and* backfill manually — reactivation auto-replays the queue and you will double-post.
- Never use raw `if(x;…)` truthiness on a null-prone Smartlead field — use `ifempty(x;"")=""`. Never drop a `statusCode = 200` guard. Never write a gate as `[[a],[b]]` when you mean AND.
- Never assert a module id, filter, or channel expression from memory or from this file — re-fetch the blueprint.
- Never declare a replay successful from a Make execution's status; the alert must be seen in the Slack channel.
- Never edit the iCloud copy of navreo-signals or declare done from a local change — only the pushed, redeployed host is live.
- Never bucket a miss as "unexplained" to make the numbers close; surface it as an open item.
- Never exceed a retry cap or report done while any done-rule fails; a cap-hit is reported as FAILED with the gap.
