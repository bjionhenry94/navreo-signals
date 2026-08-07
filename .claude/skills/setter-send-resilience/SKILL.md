---
name: setter-send-resilience
description: Static orchestration skill that fixes the Appointment Setter's "Couldn't send
  the reply - email_stats_id must be a string" 400 (rows land in Needs-review with a NULL
  email_stats_id because hydration never matched the synthetic reply-sync message_id, and
  _send_reply posts that NULL straight to Smartlead), and makes hand-edited drafts survive
  any failure by auto-saving every edit to the row instead of holding it in a browser-memory
  map. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop
  Training Mode toggle. Use when the user says "run the setter send fix", "email_stats_id
  must be a string", "the setter won't send", "my draft edits get lost", or
  "/setter-send-resilience".
---

# Setter: sends that don't 400, edits that can't be lost

Two defects, one victim. Clicking Approve on a real Needs-review row returns
`{'statusCode': 400, 'message': '"email_stats_id" must be a string'}`, and the hand-edited
draft that produced it lives only in a JavaScript object — so a refresh, a tab close, or a
navigation after the error throws the edit away. Fix the send, then make the edit
un-losable. Static loop — fixed steps, each has a done-rule, Training Mode controls the
pauses.

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

**Destructive-action gate (both modes, non-negotiable):** this skill **never clicks Approve
and never sends anything to a lead.** Step 6 hands the send back to the owner and stops.
No row is deleted; no status is hand-edited in the database. The only writes are code
commits and, in Step 5, `draft_body` auto-saves on rows the owner is already editing.

## Goal

> A reviewer can edit a draft and click Approve on any real Needs-review row without a
> 400, and if a send ever does fail, **the edit is still there** — on the row, after a
> refresh, not just in browser memory.
>
> Concretely: (1) no send request ever carries a non-string `email_stats_id`; rows missing
> one re-hydrate at send time and persist what they find, and a row that genuinely cannot
> resolve one says so in plain English instead of relaying Smartlead's Joi error; and
> (2) every keystroke in the draft composer is debounce-saved to `setter_queue.draft_body`,
> so a failed send, a reload, or a closed tab loses nothing.

## Ground truth (verified 2026-07-16 — re-verify in Step 1, line numbers drift)

- **Live source is the deploy repo `~/navreo-signals`** (verified at commit `6047e19`);
  push = deploy. The iCloud copy under `Bjion [2023]/Navreo/Claude/Navreo` **diverges and
  reverts edits — never edit it as the fix**; reconcile it after deploy (memory:
  `signals-deploy-repo`, `setter-live-verify-auth`).
- **The 400 is a NULL, not a type mismatch.** `setter_queue.email_stats_id` is `text`
  (`app/setter_migration.sql:24`). `_send_reply()` (repo `app/setter.py:1911`) builds
  `body["email_stats_id"] = row.get("email_stats_id")` at ~1931 and posts it to
  `/campaigns/{id}/reply-email-thread`. When the row's value is NULL, Joi rejects
  `null` with `"email_stats_id" must be a string`. There is **no pre-send guard and no
  re-hydrate** on that path.
- **Live counts (2026-07-16, Supabase `setter_queue`):** 30 of 93 `needs_review` rows have
  a NULL `email_stats_id` — 24 are `is_test` (harmless: test rows never reach Smartlead)
  and **6 are real and will 400 on Approve**: ids `1081, 1080, 1071, 1069, 1068, 852`.
  Id `852` is `delder@aaopticalco.com` (campaign 3642625) — the row in the owner's
  screenshot. Re-run the query in Step 1; the set drifts with every poll.
- **Why they're NULL — CONFIRMED 2026-07-16 (an earlier synthetic-key theory was WRONG;
  kept here so nobody re-derives it).** The cause is **transient Smartlead API failure at
  intake**. The rows' own `error` column reads `Couldn't load the Smartlead thread
  (HTTPError).` and `(TimeoutError).` — `server.py:213 http_json` re-raises `HTTPError`
  when the error body isn't JSON, timeouts propagate from `urlopen`, and `hydrate_lead`'s
  outer `except Exception` turns both into that string. Nothing ever retries, so the row
  keeps a NULL `email_stats_id` forever while still looking sendable.
  The discarded theory: that the reply-sync synthetic key `{email_lead_id}-{last_reply_time}`
  fails `hydrate_lead`'s target match (`app/setter.py:1296`). **It cannot be the cause** —
  the very next line falls back to `target = replies[-1]`, so a key miss still resolves.
  Also note the leading number in that key is the **lead_id, not the stats_id**; a real
  `stats_id` is a UUID (`5109630a-c5fc-4fd2-a0fd-3c726d66e41c`).
- **Recovery is just a retry.** Probed live 2026-07-16: all six rows re-hydrated fine on a
  second attempt, returning a UUID `stats_id` (str) and the `lead_id`. Re-hydrating at send
  time is therefore sufficient — no new data source is needed.
- **Both intake paths swallow it differently.** Agentless intake (~`app/setter.py:2194`)
  hydrates best-effort and lets failure pass silently, leaving NULL + `needs_review`.
  The agented path (~`app/setter.py:2330`) sets `needs_review` and writes `herr` to
  `error`. Either way the row reaches the reviewer looking sendable.
- **Edits are browser-memory only.** `app/setter.html:508` `const EDITED_DRAFTS = {}`;
  written on `input` at ~1591; re-applied after refresh by `reapplyEditedDraft()` (~1597);
  deleted after a successful send (~1664) and redraft (~1688). Nothing writes it to the
  server. `doSend()` (~1603) sends it as `body_override`; on failure `_send_reply` patches
  `{status, error}` and **never persists the body**.
- **No draft-save endpoint exists.** `app/setter.py:6807-6822` registers `/api/setter/queue`,
  `/api/setter/queue/action`, `/api/setter/queue/redraft`. Prefer adding a **`save_draft`
  action to the existing `route_queue_action`** (`app/setter.py:4113`) over a new route —
  it sidesteps the POST-body-drain gotcha entirely (memory: `reference_http_server_post_body_drain`).
- **Schema freeze is real:** a row-dict key with no matching column makes the PATCH die
  silently (memory: `reference_setter_queue_schema_freeze_gotcha`). `draft_body` exists;
  anything new does not.
- The 502 in the second screenshot is **`/queue/redraft`, a different endpoint** — out of
  scope unless Step 1 finds it still reproducing (see Step 7).

## Steps

### Step 1 — Re-verify the ground truth
Re-read the cited lines in `~/navreo-signals/app/setter.py` and `setter.html` (numbers
drift). Re-run the census against live Supabase:
```sql
select id, is_test, lead_email, smartlead_campaign_id, message_id, smartlead_lead_id, error
from setter_queue
where email_stats_id is null and status = 'needs_review' and is_test is not true
order by created_at desc;
```
**Done-rule:** the real-row list is in hand, and every ground-truth claim above is either
re-confirmed at a current line number or corrected in writing. If the NULL set is empty
and no `error` mentions hydration, STOP and report — the bug is not reproducing.

### Step 2 — Prove the cause before changing anything
For one failing row (prefer id `852`), fetch the Smartlead thread the same way
`hydrate_lead()` does and compare the row's `message_id` against every message's `stats_id`
and `message_id`. Establish: does the synthetic key match nothing, and is the real
`stats_id` recoverable by another key (lead email + `replied_at` timestamp)?
**Done-rule:** a written statement naming why hydration failed for that row and whether a
correct `stats_id` is recoverable from Smartlead — evidence, not inference. Read-only step.

### Step 3 — Fix the send path (`app/setter.py`)
In `_send_reply()`, before building the body: if `row["email_stats_id"]` is missing, re-run
the resolution proven in Step 2, and on success **persist it to the row** so the next send
is cheap. Coerce to `str()` whichever way it arrives. If it still can't be resolved, do not
call Smartlead — return `{"ok": False}` with a plain-English error the reviewer can act on
("Couldn't match this reply to the Smartlead thread, so it can't be replied to from here"),
never Smartlead's raw Joi text. Keep the existing rule that a failure lands as
`needs_review` and never raises.
**Done-rule:** no code path can post a non-string `email_stats_id`; the unresolvable case
returns a human error; a targeted test run under `SETTER_DRY_RUN=1` covers resolved,
recovered, and unresolvable.

### Step 4 — Backfill the known-bad rows
Using the Step 2 resolution, fill `email_stats_id` for the real rows found in Step 1.
Best-effort per row; a row that can't resolve keeps its NULL and is listed in the report.
Leave `is_test` rows alone — they never reach Smartlead.
**Done-rule:** every real row from Step 1 either has a non-null `email_stats_id` or an
explicit written reason it can't. This step writes only `email_stats_id` — no status changes.

### Step 5 — Auto-save every draft edit
Server: add a `save_draft` action to `route_queue_action` (`app/setter.py:4113`) that
patches `draft_body` (and `draft_subject` when sent) on the row. Refuse it on rows already
`sent`/`auto_sent`, mirroring the existing send guard. Touch **no other columns** — schema
freeze.
Frontend (`app/setter.html`): on the composer's `input` handler (~1591), keep the existing
`EDITED_DRAFTS` write for instant re-render, and add a **debounced (~800ms) POST** of
`save_draft`. Show a quiet saved/saving state near the composer; never block typing; never
toast on success. Clear `EDITED_DRAFTS[id]` only after the row's persisted `draft_body`
matches — a failed send must leave the edit intact both in memory and on the row.
**Done-rule:** typing in a draft, waiting for the save state, then hard-reloading the page
shows the edited text still there — verified in the browser on the live host, not asserted
from code (memory: `feedback_browser_verify_before_done`).

### Step 6 — Deploy and verify on the live host, then hand the send back
Commit and push (push = deploy). Wait for the deploy to land (`shell.js` `Last-Modified`
is the deploy signal, memory: `project_setter_perf_loadspeed_ship`). On the live host,
walk the whole flow: open a real Needs-review row, edit the draft, reload, confirm the edit
survived. Then **stop and prompt the owner to click Approve themselves** — that click is
the verification the brief asks for, and this skill never sends.
**Done-rule:** the live host serves the new build, the reload-survives-edit check passes in
the browser, and the owner has been prompted — in these words or close to them:
*"Fix is live and your draft edit survives a reload. Try sending to <lead> again now and
tell me what you see."* The skill does not declare success until the owner reports back.

### Step 7 — Report
Report in plain English: what the 400 actually was, what now happens instead, how many rows
were backfilled, what auto-save does, every FAILED or capped step, and whether the
`/queue/redraft` 502 reproduced (if it did, name it as follow-up work — do not fix it here).
**Done-rule:** the report names the owner's send outcome from Step 6, or says plainly that
it is still pending.

## Never do
- Never edit the iCloud copy as the fix — it reverts.
- Never click Approve, never send to a lead, never fake a send to prove the fix.
- Never invent an `email_stats_id`, or pass one Smartlead didn't give you.
- Never widen scope to the redraft 502, the categoriser, or the poll.
- Never declare done on a retry-cap hit, or without the browser-verified reload check.
