---
name: setter-redraft-pill-refresh
description: Static orchestration skill that fixes the Appointment Setter's stale decision
  pill after a redraft — a successful POST /api/setter/queue/redraft regenerates the draft
  but never re-runs lint_draft/decide, so the inbox pill keeps the ORIGINAL decision_reason
  (e.g. "No draft was produced." next to a good regenerated draft). The fix re-runs the
  lint + decision gate inside the redraft route, clamps auto_send to review (a redraft
  NEVER sends), mirrors the pipeline on a no_action verdict, and persists fresh
  decision/decision_reason within the setter_queue schema-freeze; proven live with a
  test-injected row and Supabase read-back. One fixed step list, each step with a
  checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says
  "run the setter redraft pill fix", "the pill is stale after regenerate", "redraft keeps
  the old decision reason", or "/setter-redraft-pill-refresh".
---

# Setter redraft pill refresh

The redraft route rebuilds the draft but leaves the row's verdict frozen, so the inbox list
lies: a row whose first draft failed keeps showing "No draft was produced." beside a perfectly
good regenerated draft. This loop makes a successful redraft re-run the same lint + decision
gate the live pipeline uses and persist the fresh verdict, without ever sending. Static loop —
fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gates (both modes, non-negotiable):**
- **Sends:** a redraft NEVER sends an email (owner ruling 2026-07-16). If decide() returns
  auto_send, clamp to decision `"review"` with a plain-English "ready — approve to send"
  style reason. Never claim a message was sent. Live testing uses ONLY `is_test` rows
  (POST /api/setter/test/inject) — is_test rows never reach Smartlead.
- **Injections:** max **3** test-row injections on the live host, ids recorded as they're
  created.
- **Deletes:** the only rows ever deleted are the test rows THIS loop injected, by recorded
  id. In Training Mode ON, show the id(s) and get approval before the delete fires.
- **Repo:** work ONLY in ~/navreo-signals (NEVER the iCloud copy — it reverts edits).
  `git push` = deploy to Render. Parallel deploy-repo sessions commit each other's WIP:
  check `git status` first and commit only this loop's files.

## Goal

> After any successful redraft, the inbox row's pill reflects the regenerated draft's fresh
> lint + decision verdict instead of the stale original, with no redraft ever sending.
> Done bar = the six-check verification in Step 7, **all six or it isn't done**, verified on
> the deployed Render host and cleaned up afterward. On the round cap, stop and report the
> gap honestly — do not declare done.

## Ground truth (verified 2026-07-16 — re-verify in Step 1, line numbers drift)

- `route_queue_redraft` — app/setter.py:3680. Patch built ~:3783 is
  `{"draft_subject", "draft_body", "slots"}` + `classification`/`first_outbound`/`timezone`
  only when it freshly classified. It never touches `decision`/`decision_reason` — the bug.
- `lint_draft(html, ctx)` — setter.py:577, returns `(ok, reason)`; empty draft →
  `"No draft was produced."`. `decide(classification, agent, ctx)` — setter.py:670, returns
  `(decision, reason)`, decision ∈ {auto_send, review, no_action}.
- Pipeline's ctx assembly to copy — setter.py:~2496–2532. Lint ctx keys: subject, first_name,
  needs_resource_link, slot_status, slot_links, slot_labels, instructions, booking_link,
  thread_text, slots_fallback, needs_availability_ask. Decision ctx keys: red_flag_hits
  (lex hits), category, first_touch, slot_status, slots_fallback, timezone, tz_confident,
  lint_ok, lint_reason, body_len, hydrated, answered_since_reply, autopilot_enabled,
  same_day_ask, first_outbound_present, needs_availability_ask.
- **Schema-freeze column list** = the canonical row dict at setter.py:2270. `decision`,
  `decision_reason`, `status`, `draft_subject`, `draft_body`, `slots`, `classification`,
  `timezone`, `first_outbound` are all real columns. `lint_ok`/`lint_reason` are NOT —
  never patch them (a key without a column makes the PATCH die silently).
- `_apply_patch` — setter.py:1852; PATCHes `QUEUE_TABLE` and invalidates the KPI cache when
  `"status"` is in the patch (so a no_action flip needs no extra cache work).
- Frontend: HOLD_REASON_KEYWORDS map setter.html:~993; pill rendered at ~:1058 (only when
  `status === "needs_review"`); `doRedraft` ~:1565 and `doDraftAnyway` ~:1591 both call the
  same endpoint then `loadQueue()`, so the backend fix refreshes the pill with no frontend
  change — EXCEPT the no_action message in Step 3.
- Pipeline behaviour to mirror on no_action (setter.py:~2534): draft nulled, status
  `"no_action"`.
- `route_test_inject` sits right after the redraft route (~:3795); POST
  /api/setter/test/inject requires `campaign_id`.
- Live access: mint a `navreo_session` cookie from the SRK in `~/.navreo-keys.env`
  (memory: `reference_signals_session_cookie_mint`). Deploy proof = the live host's
  boot/poll ledger, never "I pushed" (memory: `reference_setter_live_verify_auth`).
- New POST routes read `self._post_body`, never rfile.read (memory:
  `reference_http_server_post_body_drain`) — the redraft route already exists, this only
  matters if handler plumbing is touched.
- **Unknowns for Step 1:** exact live host URL; exact `QUEUE_TABLE` name for the Supabase
  read-back; whether test/inject accepts a custom reply body (to shape the test verdict);
  the helper names for lex red-flag hits / hydrated / answered_since_reply and whether they
  are callable with only the stored row (no live thread re-read).

## Steps

### Step 1 — Re-verify ground truth
Re-confirm every Ground-truth bullet against the current code in ~/navreo-signals (lines
drift), and resolve the recorded unknowns: live host URL, QUEUE_TABLE name, test-inject
payload shape, and how each decision-ctx field can be computed inside the redraft route from
the stored row alone.
- **Done-rule:** every bullet re-confirmed or corrected with current `file:line`, and all
  four unknowns resolved with a concrete answer written into the working notes.

### Step 2 — Backend: re-run the gate inside the redraft route
After the redraft's proofread in `route_queue_redraft`, assemble the lint ctx and decision
ctx exactly as the pipeline does (reuse the same helpers — never a hand-rolled
approximation), run `lint_draft` then `decide`, and add the fresh `decision` +
`decision_reason` to the SAME `_apply_patch`. Rulings (owner, 2026-07-16): **auto_send
clamps to `"review"`** with a "ready — approve to send" style reason (the keyword map's
fallback truncation handles unmapped wording); **no_action mirrors the pipeline** — null
`draft_subject`/`draft_body` and set `status` to `"no_action"` in the patch. Every patched
key must exist in the canonical row dict at setter.py:2270.
- **Done-rule:** (a) the patch dict includes `decision` and `decision_reason`;
  (b) `grep` proves every patched key appears in the canonical row dict; (c) the clamp
  branch is unreachable-to-send — no `_send_reply` call anywhere in the redraft route;
  (d) the no_action branch nulls the draft and sets status; (e) `python -c "import
  app.setter"` (or the repo's equivalent syntax check) passes.

### Step 3 — Frontend: explain an empty Draft-anyway
Consequence of the no_action mirror: a "Draft anyway" click whose re-verdict is still
no_action keeps NO draft. `doDraftAnyway` must then say why nothing appeared (e.g. surface
the returned row's fresh `decision_reason` via the existing note/error surface) instead of
silently doing nothing. No other frontend change — `loadQueue()` already refreshes the pill.
- **Done-rule:** reading `doDraftAnyway` shows a user-visible message fires whenever the
  response row has no `draft_body`, quoting the fresh `decision_reason`.

### Step 4 — Deploy
Check `git status` for other sessions' WIP, commit ONLY this loop's files, push to deploy.
- **Done-rule:** the live host's boot/poll ledger shows the pushed commit running —
  "I pushed" never counts.

### Step 5 — Live proof: inject, redraft, read back
On the deployed host (navreo_session cookie minted from `~/.navreo-keys.env`): inject a test
row (POST /api/setter/test/inject, `is_test`, max 3 total), record its id and
`decision_reason`, POST /api/setter/queue/redraft for it, then read the row back **directly
from the Supabase setter_queue REST API** — never trust the endpoint's own response.
- **Done-rule:** the Supabase read-back shows `decision_reason` re-computed to match the
  fresh verdict (different from, or freshly consistent with, the regenerated draft's
  lint+decide outcome — not the pre-redraft string when the verdict changed).

### Step 6 — Live proof: pill + clamp
(a) Open the live setter inbox in a real browser and confirm the rendered pill for the test
row shows the updated verdict — a grep of deployed JS never counts as UI proof.
(b) Clamp proof from the same Supabase read-back: `status` is not `auto_sent`, `sent_at` is
null, and the test lead has no new sent message.
- **Done-rule:** (a) browser-rendered evidence (screenshot) of the updated pill;
  (b) read-back fields confirm nothing sent. Both, or the step fails.

### Step 7 — Cleanup + composite done bar
Delete the injected test row(s) by recorded id (gated in Training Mode ON), then confirm
with a final Supabase read-back returning zero rows for those ids. Then walk the full
six-check bar: (1) code proof (patch keys vs canonical columns), (2) deploy proof (ledger),
(3) data proof (Supabase read-back), (4) UI proof (rendered pill), (5) clamp proof
(no send), (6) cleanup (zero rows).
- **Done-rule:** all six checks pass, each evidenced by its own artifact. **All 6, or it
  isn't done.**

## Final report (always, both modes)

One summary listing: each step passed / skipped / FAILED with reason; the commit hash
deployed; the injected row id(s), their before/after `decision_reason` strings, and the
final verdict per row; the screenshot path for the pill proof; the cleanup read-back result;
injections used (n/3); anything deferred. Never report done while any done-rule fails.

## Hard don'ts

- Never send from the redraft path — auto_send always clamps to review; never call
  `_send_reply` from `route_queue_redraft`.
- Never patch a key that isn't a column in the canonical row dict at setter.py:2270
  (`lint_ok`/`lint_reason` especially) — the PATCH dies silently.
- Never touch the iCloud copy of the repo; ~/navreo-signals only.
- Never trust the app's own success labels — data proof is the Supabase read-back, UI proof
  is the rendered browser page, deploy proof is the live ledger.
- Never exceed 3 test injections, and never delete anything except the rows this loop
  injected, by recorded id.
- Never hand-roll the lint/decision ctx — reuse the pipeline's own helpers so the redraft
  verdict can't drift from the live gate.
- Never exceed a retry cap or declare done while any of the six checks fails.
