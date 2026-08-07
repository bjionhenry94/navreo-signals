---
name: setter-inbox-trust-ship
description: Static orchestration skill that makes the Appointment Setter behave like a real
  inbox the owner trusts — kills the queue-load 501, auto-checks for new replies on every
  login, renders replies as clean multi-paragraph text with quoted history stripped (render
  AND classifier paths), shows the full thread past the 6-message cap, collapses the nested
  scrolls into one viewport-bled panel, adds reply/report timestamps and a did-they-reply
  indicator, surfaces an explicit "would this have auto-sent?" verdict with why-no-slots /
  why-not-sent, moves the filter dropdown under the search field, and always drafts for any
  reply that surfaces as actionable in the queue. One fixed step list, each step with a
  checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says
  "run the setter inbox fix", "make the setter a real inbox", "fix the setter formatting
  and 501", or "/setter-inbox-trust-ship".
---

# Setter Inbox Trust Ship

The owner doesn't trust the Appointment Setter: login shows stale data, a 501 kills the
queue, replies render as one flattened paragraph dragging the whole quoted thread along,
only 6 thread messages survive hydration, the panel has a scroll inside a scroll, and the
right panel never says whether autopilot would have fired or why no call times appeared.
Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

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
- **Sending:** nothing is ever sent to a real lead. All send-path testing uses
  `is_test` rows injected via `/api/setter/test/inject` only. The autopilot master
  switch stays **OFF** throughout — never flip it.
- **Data:** never rewrite stored `reply_body` / thread bodies in `setter_queue` — raw
  fidelity stays; all cleaning is render-time (frontend) or read-time (classifier
  input). Test rows are deleted/dismissed in the cleanup step; max **10** injected rows.
- **Scope:** do NOT touch Settings, the Agents drawer, Try-it, or any saved agent
  instructions. The always-draft policy is global decide/draft code, not brain edits.
- **Repo:** never commit the local `~/navreo-signals` working tree's pre-existing
  modified files (campaigns.html, notifications.html, server.py, unified.html — the
  in-progress tier1 work). Build on `origin/main` in a detached worktree; stage only
  `app/setter.py` + `app/setter.html` (+ any helper the fix provably needs).

## Goal

> On navreo-signals.onrender.com, a fresh login auto-checks and shows the newest replies;
> the queue loads with no 501 ever; each reply reads as clean multi-paragraph text with
> quoted history gone (list snippet, conversation pane, AND classifier input); full
> threads render past 6 messages; the centre panel is one scroll with viewport bleed
> matching the page's side margins; name-side reply timestamp, Teach-the-agent
> "reported X ago", and a did-they-reply indicator render; every row shows an explicit
> would-have-auto-sent yes/no plus why-no-slots and why-not-sent; the filter dropdown
> sits under the search field; and every actionable queue row carries a draft even when
> the agent is unsure. **All nine verified live in a real browser with injected fake
> data, test rows cleaned up after. All nine, or it isn't done.**

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- **Live source of truth is the git repo `~/navreo-signals`** (remote
  `github.com/bjionhenry94/navreo-signals`, branch `main`; Render auto-deploys on push).
  The iCloud copy (`…/Navreo/Claude/Navreo/app/…`) is DEPRECATED — never edit it, and
  iCloud reverts edits. As of 2026-07-15 the local checkout is **behind origin/main by
  17 commits with uncommitted local mods** (tier1 work) — use
  `git worktree add --detach <path> origin/main`, commit only setter files, push
  `HEAD:main`, `git worktree remove` (memory `reference_signals_deploy_repo`).
- Anchors in the **local repo copy** (origin/main will differ — re-anchor there):
  `clean_body` setter.py:203 (tags→single space, kills `<br>/<p>` paragraph breaks; no
  quoted-history strip), `decide()` setter.py:637 (master-switch-off collapses to
  `review` with prose-only reason, lines ~769-772 in iCloud copy; clear negatives
  short-circuit to `no_action` with **no draft**, ~659-676), `norm[-6:]` thread cap in
  `hydrate_lead` setter.py:1184, `route_queue_get` setter.py:2479 (returns only 200/500).
  Frontend: `cleanBody` twin ~setter.html:528, `.inbox-shell height:calc(100vh - 220px)`
  setter.html:47, `.inbox-right overflow-y:auto` :62, `.convo max-height:46vh;
  overflow-y:auto` :139, toolbar filters `#queueFilters`+`#clientFilterSel` :275-277,
  `dh-name` header ~:972, `howDecidedContentHtml` ~:1007, error surfaced by `showError`
  ("Couldn't load the queue: …") ~:654.
- **The string "501" appears nowhere in setter.py / server.py** — the 501 in the owner's
  screenshot comes from the deployed host/proxy layer on the queue GET, not app logic.
  UNKNOWN: exact trigger (Render cold-start? oversized response? proxy timeout?).
  Step 1 must reproduce it live and pin the cause before any fix is written.
- **Auth:** the app sits behind a Supabase login gate — anonymous curl of any /app page
  302s to login; the queue GET is auth-gated; you cannot mint a session cookie (memory
  `reference_setter_live_verify_auth`). Live UI verification goes through the user's
  already-authenticated real Chrome via **claude-in-chrome**. Deploy proof without auth:
  the poll log row in `app_activity_log`. UNKNOWN: whether `/api/setter/test/inject`
  (POST_ROUTES, setter.py:4651) is in `_AUTH_PUBLIC_POST` — resolve in Step 1; if gated,
  inject through the user's Chrome session (fetch from the page context).
- **Schema freeze:** adding a new key to a `setter_queue` row dict without a real DB
  column makes the whole PATCH die silently (memory
  `reference_setter_queue_schema_freeze_gotcha`). The would-have-auto-sent verdict must
  be computed at read/render time or returned in the queue payload — never persisted as
  a new column-less field.
- Tests exist and the last ship reported **669 green** — run them before deploy.
- Autopilot master switch is OFF; `decide()` already emits
  `"review", "…autopilot master switch is off"` when everything else passed — that
  exact reason string is the cheapest ground for the yes/no verdict.

## Steps

### Step 1 — Re-verify ground truth and reproduce the 501
Create the detached worktree from `origin/main`; re-anchor every Ground-truth line
number there. Resolve the two unknowns: (a) reproduce the queue-load 501 on the live
host through the user's Chrome (load the setter page, watch the network tab /
read_network_requests for the `/api/setter/queue` status) and pin the layer that emits
it; (b) determine whether `/api/setter/test/inject` is auth-public by reading
`_AUTH_PUBLIC_POST` in server.py and prove the working inject path with one live test row.
- **Done-rule:** (a) every anchor confirmed with fresh line numbers in the worktree;
  (b) the 501 observed live (or its trigger conclusively identified from Render logs /
  response headers) with the emitting layer named; (c) one `is_test` row exists in the
  live queue via the proven inject path. 501 non-reproduction after 3 varied attempts
  (cold start, big queue, rapid reloads) = record as "not reproduced" with evidence and
  proceed — the fix must then be defensive (retry + clear error surface) rather than
  causal.

### Step 2 — Backend fixes (setter.py in the worktree)
(1) `clean_body`: convert `<br>/<p>/<div>/</tr>`-class tags to newlines before the
generic tag strip, collapse only horizontal whitespace, and strip quoted history
("On … wrote:", leading-`>` blocks, `gmail_quote`/`OutlookMessageHeader` containers,
"-----Original Message-----") so the classifier reads only the lead's new message.
(2) `hydrate_lead`: raise the `norm[-6:]` cap so the full thread reaches the row (cap
generously, e.g. 50, to bound payload size). (3) Queue payload: compute
`would_auto_send` (bool) + `held_only_by_master_switch` + a structured
`no_slots_reason` at read time in `route_queue_get`/row serialisation — no new DB
column. (4) Always-draft: for every reply that lands in the queue as actionable
(anything surfaced needs_review or viewable with intent ≠ clear opt-out/DNC), generate
a draft even at low confidence; clear opt-outs keep their no-draft short-circuit.
(5) Auto-check support: ensure the poll endpoint exposes/returns last-checked time for
the UI. Run the test suite; add/adjust tests for 1-4.
- **Done-rule:** (a) unit test proves a Gmail-style HTML reply with quoted history →
  multi-paragraph clean text, quote gone; (b) test proves a >6-message history survives
  hydration in full; (c) test proves queue payload carries `would_auto_send` correctly
  in both master-switch states without any row PATCH gaining a new key; (d) test proves
  a low-confidence actionable reply gets a draft and a clear opt-out doesn't; (e) full
  suite green (≥ the prior 669, no skips added).

### Step 3 — Frontend fixes (setter.html in the worktree)
(1) Port the new `clean_body` behaviour to `cleanBody` (paragraph preservation via
newline-aware rendering + quoted-history strip) for list snippets and the conversation
pane — drafts still render as HTML untouched. (2) Layout: `.inbox-shell` fills the
viewport with top/bottom gutter equal to the page's side margins; exactly one scroll
per column (list, conversation, sidebar) — remove `.convo`'s inner
`max-height/overflow`. (3) Timestamps: lead's reply time beside `dh-name`, "reported X
ago" beside Teach-the-agent, and a did-they-reply indicator (post-send inbound state).
(4) Decision panel: extend `howDecidedContentHtml` with **Would this have auto-sent —
Yes/No**, the why-not (master switch / named failing check), and why-no-slots when call
times weren't proposed. (5) Move the status pills + client dropdown under/beside the
search field in the list column. (6) On page load, auto-fire the check (poll kick) and
render "last checked X ago" beside the manual button.
- **Done-rule:** page serves locally (or via deploy preview) with: (a) grep confirms no
  `.convo` overflow rule and the shell height formula changed; (b) `cleanBody` unit
  behaviour matches `clean_body` on the same fixture string; (c) the load path calls
  the poll kick unconditionally; (d) filter controls markup now lives inside
  `.inbox-left`. (Full visual proof is Step 5 — this rule only gates obvious breakage.)

### Step 4 — Deploy
Commit only setter files in the worktree with a descriptive message, push
`origin HEAD:main`, remove the worktree. Wait for Render; prove the deploy without auth
via the poll-log row in `app_activity_log` (new deploy = fresh boot entry) and a marker
grep of the deployed setter.html (deploy check only, not done-evidence).
- **Done-rule:** (a) push accepted, `origin/main` HEAD = the new commit; (b) live
  poll/boot log row timestamped after the push; (c) marker string from the new
  setter.html present on the live host; (d) local `~/navreo-signals` checkout's
  pre-existing uncommitted files untouched (`git status` unchanged from Step 1 snapshot).

### Step 5 — Live proof as a setter, then cleanup
Through the user's authenticated Chrome on navreo-signals.onrender.com, with ≤10
injected fake rows covering: an HTML reply with quoted history, a >6-message thread, a
low-confidence-but-actionable reply, a clear opt-out, and a would-have-auto-sent case.
Drive it day-to-day style: load, read, select, scroll the list for more, edit a draft,
regenerate — no Settings/Agents/Try-it. Verify the full nine-part bar (a)-(i) from the
Goal, screenshotting each. Then delete/dismiss every injected test row and confirm the
queue shows none.
- **Done-rule:** all nine checks (a)-(i) observed and screenshotted in the real
  browser: (a) no 501, list scroll never errors; (b) fresh load auto-checks, newest
  fake reply appears unclicked, "last checked X ago" visible; (c) quoted-history fake
  renders clean multi-paragraph in snippet AND pane, classifier input confirmed clean
  (from the row's classification rationale reading only the new message);
  (d) all >6 messages visible; (e) one scroll, matching bleed; (f) all three
  timestamp/reply indicators render; (g) would-auto-sent yes/no + why-no-slots +
  why-not-sent shown, no PATCH breakage (row actions still work); (h) filters under
  search; (i) low-confidence row carries a draft. Plus: zero `is_test` rows remain.
  Any missing letter = step FAILED with the letter named.

## Final report (always, both modes)

Steps passed / skipped / FAILED with reasons; the 501 root cause (or "not reproduced" +
defensive fix taken); commit hash + push time; test count before/after; the nine (a)-(i)
verdicts each with its screenshot path; injected row ids and proof of cleanup; anything
deferred. Never report done while any letter fails.

## Hard don'ts

- Never send anything to a real lead; never flip the autopilot master switch.
- Never touch Settings, Agents drawer, Try-it, or saved agent instructions.
- Never rewrite stored reply/thread bodies — cleaning is render/read-time only.
- Never add a new `setter_queue` row-dict key without a real DB column.
- Never edit the iCloud copy or the local checkout's in-progress files; build on
  `origin/main` in a detached worktree and stage setter files only.
- Never treat a grep of deployed JS, a 200 response, or the app's own success label as
  done-evidence — only the rendered page in the real authenticated browser counts.
- Never exceed a retry cap or declare done while any done-rule letter fails.
