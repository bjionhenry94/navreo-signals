---
name: setter-teach-link-simplify
description: Static orchestration skill that simplifies the Appointment Setter reply bar's teaching controls — replaces the "Teach the agent On/Off" toggle + "Add a lesson" button with ONE quiet underlined link "Remember this as a lesson" that opens the existing teach modal, edits made in the ~/navreo-signals deploy repo (iCloud copy is deprecated), pushed to Render, and proven on the LIVE page including a dummy-lesson persistence read-back with cleanup. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the teach link simplify", "simplify the setter teaching controls", "ship the remember-as-lesson link", or "/setter-teach-link-simplify".
---

# Setter Teach-Link Simplify

The "Your reply" action bar in the Setter inbox carries two teaching controls (an On/Off toggle + a button) that clutter the row. This loop collapses them to one quiet link — "Remember this as a lesson" — deploys it, and proves on the live host that a lesson saved through it actually sticks to the agent. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run without pauses

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

**Destructive-action gate (both modes, non-negotiable):** the only outward actions are
(a) ONE git push to `~/navreo-signals` `origin/main` (Render auto-deploys) — in Training
Mode ON, show the `git diff` and get approval before the push fires; and (b) ONE dummy
lesson ("TEST-DELETE-ME <timestamp>") saved against a **disposable/test agent only,
NEVER a real client agent's brain**, deleted again in the same step after read-back.
No lead is emailed, no campaign touched, no real agent's instructions modified. Nothing
else is ever deleted, sent, or spent.

## Goal

1. On the live deployed Setter inbox (`navreo-signals.onrender.com/app/setter.html`), a reply awaiting review shows a single quiet grey underlined link **"Remember this as a lesson"** beside "Your reply" — no On/Off toggle, no bright button — sitting calmly next to Approve / Regenerate / Dismiss.
2. Clicking it opens the existing teach modal, and a saved note verifiably persists into that agent's standing instructions (proven by independent read-back, then cleaned up).
3. Regenerate-with-feedback behaviour is untouched: feedback still teaches by default (`trainingModeOn()` defaults "on").

## Ground truth (verified 2026-07-15 — re-verify in Step 1, line numbers drift)

- **Source of truth is `~/navreo-signals`** (git, `github.com/bjionhenry94/navreo-signals`, branch `main`, Render auto-deploys on push). The iCloud copy `…/Navreo/Claude/Navreo/app/setter.html` is **DEPRECATED** (user directive 2026-07-07) — do NOT treat it as source. ⚠ HOWEVER: a session on 2026-07-15 already made a v1 of this edit **in the iCloud copy only** (label "Add a lesson", class `.teach-link`) — Step 1 must check whether `~/navreo-signals/app/setter.html` has it (likely NOT), and the final label is **"Remember this as a lesson"** either way.
- In the iCloud copy (repo file may differ — re-verify): `teachToggleHtml(row)` ~line 1400 renders the controls; called from `.composer-head` ~line 1175; toggle styles `.qc-training-tgl` ~line 193 / `.teach-tgl` ~line 182; teach modal `#teachAgentModalOverlay` ~line 390; wiring `teachBtn` → `openTeachAgentModal(agentId, rowId)` ~lines 1456–1457 and ~2183; action buttons `composerActionsHtml` ~line 1363. `trainingModeOn()` ~line 1376 defaults "on".
- Safe-deploy procedure (memory `signals-deploy-repo`): `git fetch` + `git merge --ff-only origin/main` FIRST, apply the edit surgically onto the FF'd file, `git diff` to confirm only the intended hunk, stage explicitly (never `git add -A`), push. Then copy the now-superset file back into iCloud and `diff -q` to confirm.
- Live auth: pages are 302-gated. Mint `navreo_session` yourself — `SUPABASE_SERVICE_ROLE_KEY` IS in `~/.navreo-keys.env` (export-style lines; grep with `export ` prefix). Recipe (verified live 2026-07-15): `secret = sha256(SRK + ":navreo-session-v1")`, payload `email|now+86400` (⚠ the +86400 expiry gotcha — don't mint with a past expiry), token = `b64url(payload).hexhmac`. Cookie: `navreo_session=<tok>`. Any email works.
- Deploy proof without auth: Render deploy visible via `git push` landing + the `/api/setter/poll` cron (~5 min) logging to `app_activity_log` (Supabase `fnykldftbkrccihdjayl`); but for THIS change the marker-grep of the deployed HTML (with cookie) is the direct proof.
- Agent instructions read-back path: Agents view in the UI, or the agent record via the setter API/Supabase — **unknown which table/field holds instructions; Step 1 resolves this** (likely `setter_agents`-style table; check `server.py` teach/save endpoint handler).
- Disposable agent: **unknown whether a test agent exists; Step 1 resolves this.** If none, create one named "TEST agent — delete me" via the existing agent-create path, and delete it in Step 5 cleanup.

## Steps

### Step 1 — Re-verify ground truth in the deploy repo
In `~/navreo-signals`: `git fetch` + `git merge --ff-only origin/main`. Locate `teachToggleHtml`, the composer-head call site, the toggle styles, the modal, and the wiring in `app/setter.html` (line numbers WILL differ from the iCloud copy). Check whether any version of the teach-link edit is already present. In `server.py`, find the teach-save endpoint and the table/field where agent instructions live. Determine whether a disposable/test agent exists. Confirm the SRK is readable from `~/.navreo-keys.env` and mint a `navreo_session` cookie that gets a 200 (not 302) on `/app/setter.html`.
- **Done-rule:** (a) repo is fast-forwarded clean to origin/main; (b) every code location above is confirmed with current line numbers; (c) the instructions storage table/field is named; (d) a minted cookie returns HTTP 200 on the live `/app/setter.html`; (e) test-agent existence is answered (found or "will create").

### Step 2 — Make the edit in the repo
In `~/navreo-signals/app/setter.html`: rewrite `teachToggleHtml(row)` to return, when `row.agent_id` exists, ONLY `<button class="teach-link" id="teachAgentBtn" …>Remember this as a lesson</button>` (keeping `data-id`/`data-agent-id` and the existing modal wiring untouched), and empty string otherwise. Remove the On/Off toggle markup and the now-orphaned `.qc-training-tgl` and `.teach-tgl` CSS blocks. Add the `.teach-link` style: grey (`var(--ink-3)`), underlined with `var(--line-2)`, orange (`var(--orange-700)`) on hover, no border/background, 12px. **Do NOT touch** the modal markup, `openTeachAgentModal`, the save endpoint, `trainingModeOn`/`feedbackPlaceholder`/`composerFeedbackHtml`, or any other composer action.
- **Done-rule:** (a) `grep -n "Remember this as a lesson" app/setter.html` hits exactly once, inside `teachToggleHtml`; (b) `grep -n "Teach the agent\|qc-training-tgl\|teach-tgl" app/setter.html` returns only the modal's `<h3>Teach the agent</h3>` heading and comments — no composer-bar markup or CSS selectors; (c) `.teach-link` CSS block exists; (d) `git diff` shows changes ONLY in the `teachToggleHtml` function, the CSS block, and comments — no other hunks.

### Step 3 — Deploy
Stage `app/setter.html` explicitly, commit, push to `origin/main`. **Training Mode ON: show the diff and pause for approval before the push.** Wait for Render to redeploy, then with the minted cookie `curl` the live `/app/setter.html` and marker-grep it.
- **Done-rule:** (a) push accepted on `origin/main`; (b) live HTML (fetched with cookie, HTTP 200) contains "Remember this as a lesson" and contains NO `qc-training-tgl`/`teach-tgl` selectors; retry by waiting (Render deploys take minutes) — a stale grep within 10 minutes of push is a wait, not a failure.

### Step 4 — Live browser proof of the simplified bar
In the browser with the minted cookie, open the live Setter inbox, open a reply detail row that has an `agent_id` (use the test agent's row if real rows would be disturbed — read-only viewing is safe either way). Confirm the action bar renders exactly one quiet underlined "Remember this as a lesson" link beside "Your reply", no toggle, alongside Approve / Regenerate / Dismiss. Screenshot it.
- **Done-rule:** (a) `read_page` of the live detail view shows the link text and NO "Teach the agent … On/Off" control; (b) a screenshot of the rendered bar is captured and shared.

### Step 5 — Dummy-lesson persistence read-back + cleanup
On the live page, on a **disposable/test agent only** (create "TEST agent — delete me" first if Step 1 found none): click the link, type the dummy lesson `TEST-DELETE-ME <timestamp>`, save. Then INDEPENDENTLY read the agent's instructions back — from the Agents view or the agent record in Supabase (the table/field named in Step 1), **never the modal's own success behaviour** — and confirm the dummy text is present. Then delete the dummy lesson (and the test agent if this loop created it) and read back again to confirm it's gone.
- **Done-rule:** (a) the dummy string appears in the agent's stored instructions via independent read-back; (b) after cleanup the same read-back no longer contains it; (c) no real client agent's instructions were modified at any point (assert the agent id used is the test agent's).

### Step 6 — Reconcile the iCloud copy
Copy the now-superset repo `app/setter.html` back over the iCloud copy so the deprecated working copy stops being stale (this also supersedes the earlier iCloud-only "Add a lesson" edit). Confirm no unique iCloud lines are lost first: `diff repo iCloud` — the earlier session's edit is the only expected iCloud-side difference and is intentionally replaced.
- **Done-rule:** `diff -q ~/navreo-signals/app/setter.html "<iCloud>/app/setter.html"` reports no difference.

## Final report (always, both modes)

One summary listing: each step PASSED / SKIPPED (already passing) / FAILED with reason; the commit hash pushed and the Render deploy confirmation; the live screenshot of the simplified bar; the dummy-lesson read-back evidence (agent id, stored-instructions excerpt before and after cleanup); confirmation the iCloud copy matches the repo; anything deferred.

## Hard don'ts

- Never edit the iCloud copy as source — all edits happen in `~/navreo-signals`; iCloud only receives the copy-back in Step 6.
- Never push without the ff-only merge first, and never `git add -A` — stage `app/setter.html` explicitly.
- Never save the dummy lesson to a real client agent, and never leave the dummy lesson (or a loop-created test agent) behind — cleanup is part of Step 5's done-rule.
- Never touch the teach modal's markup, the save endpoint, the agent-brain merge logic, `trainingModeOn`/`feedbackPlaceholder`/`composerFeedbackHtml`, or any composer action other than the teach controls.
- Never trust the modal's own success behaviour as persistence proof — independent read-back from the stored instructions or it doesn't count.
- Never declare done from a grep of local files — the live rendered page (Step 4) and live read-back (Step 5) are the only acceptable end proof (user ruling: rendered page = only done-evidence for UI).
- Never enter a password anywhere — auth is the self-minted `navreo_session` cookie only.
- Never exceed a retry cap or report done while any done-rule fails.
