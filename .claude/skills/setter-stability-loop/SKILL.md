---
name: setter-stability-loop
description: One orchestration loop that audits, repairs, and verifies the six setter stability/UX issues (send 502s, slow conversation history, one-click Not-qualified, Sent-without-follow-up tray misses, queue-refresh 502s, meetings over-count), then runs a 5-expert panel and optimises until the code is voted 9/10+. Trigger with "/setter-stability-loop", "run the setter stability loop", or "continue the setter loop".
---

# Setter Stability Loop

## ⚙️ LOOP TRAINING MODE — currently: **OFF**

> **Flip this by editing the line above to OFF.**
>
> - **ON** — pause at EVERY step and wait for Bjion's approval in chat before
>   continuing. Skip any step that already passes its done-rule (say so, don't
>   re-run it). Only re-run steps that FAIL their done-rule. Retry cap: **3
>   attempts per step** — on the 3rd failure, stop, report what was tried, and
>   wait for instructions. Never loop past the cap.
> - **OFF** — run all steps autonomously with no pauses. The done-rule checks
>   and the 3-retry cap still apply exactly as above; on a cap-out, stop the
>   whole loop and report.

## Goal

Make the setter section stable and fast: no 502s on send or queue refresh,
instant conversation history, one-click Not-qualified, a follow-up tray that
never misses a sent-without-follow-up reply, and meetings counted only when
they're real — then hold the code to a 9/10+ bar from a 5-expert panel.

## Hard safety rails (apply to every step, no exceptions)

- **NEVER send to real prospects.** Test send paths with `is_test` rows only;
  check `row.status` before ANY Smartlead write.
- The ONLY permitted live send: temporarily allow a **"Not interested"**
  prospect into the queue and reply with a plain **"No worries"** — nothing
  else, no other categories, and restore the gate afterwards.
- Repo: `~/navreo-signals`. Live verify: mint a `navreo_session` cookie, poll
  `/api/version` until the deploy lands (see memory: signals-live-verify-recipe).
- The web instance is a 512MB Render starter — never add heavy in-process
  sweeps to the web process; batch work belongs in crons.

## Steps

Each step = audit → fix → verify against its done-rule. Work in
`~/navreo-signals`; key files are `app/setter.py`, `app/setter.html`, and the
`/api/setter/*` dispatch in `app/server.py`.

**1. Audit pass (read-only).** Reproduce all six issues without sending
anything: hit the live endpoints with a minted session, read server logs
(`server_boot_ledger`, Render logs), and trace each symptom to a code path.
*Done-rule: each of the six issues has a written root-cause hypothesis pinned
to file:line, or is marked "cannot reproduce" with evidence.*

**2. Send 502s.** "Couldn't send the reply: Request failed (502)" on
`/api/setter/queue/action` (`send`/`send_followup`). Known-open suspect:
hydrate-burst 502 / OOM pressure on the 512MB instance. Fix must make sends
either succeed or fail with a real, retryable error — check the async job path
(202-job sends) end to end.
*Done-rule: 20 consecutive test-mode sends (`is_test` rows) complete with zero
502s, and a forced-failure send surfaces a clear retry, not a dead 502.*

**3. Pre-cache conversation history.** History is hydrated live from Smartlead
on open (`route_thread_get`/`hydrate_lead`) — too slow. Change intake so that
as soon as a reply lands (poll/webhook), the full conversation history is
persisted to Supabase, and `route_thread_get` serves from Supabase first with
live hydrate only as fallback/refresh. Remember: setter queue row ids are NOT
stable across re-intake — key history by email + message_id.
*Done-rule: opening a conversation renders history from cache in under 1s on
live, and a fresh inbound reply appears in Supabase within one poll cycle.*

**4. One-click "Not qualified".** In the change-lead-category section, add a
single-click button that sets the lead to "Not qualified" — no dropdown
digging. Respect the recategorise path's follow-up-tray side effects
(`route_queue_recategorise`).
*Done-rule: one click on a queue row marks it Not qualified, the UI reflects it
without a full reload, and the row correctly leaves any follow-up trays.*

**5. "Sent without follow-up" tray misses.** Replies sent with follow-up
choice "None" must STILL appear in the tray (owner ruling 2026-07-22: 'none' is
a mark, not a removal — but the user reports these rows never show). Audit the
tray query around `_followup_category_ok` and the `subsequence_decision`
filter in `app/setter.py` (~5318–5490) for the case that drops none-at-send
rows.
*Done-rule: a test row sent with decision "none" appears in the tray, and an
explicit Dismiss is the only non-category action that removes it.*

**6. Queue-refresh 502s.** "Couldn't refresh the queue: Request failed (502)"
on `/api/setter/queue`. The queue is a memoized single-flighted ~6MB gzip
corpus (`queue_response`) — audit boot-burst behaviour, memory headroom, and
whether refresh can serve stale-while-revalidate instead of 502ing.
*Done-rule: 30 consecutive queue refreshes against live (including one
immediately after a deploy restart) return 200 — or degrade to explicitly
stale data, never a 502.*

**7. Meetings = Call booked only.** Meetings-held is over-reporting. Every
surface that counts meetings (analytics hub, weekly digests, client windows,
setter stats in `app/server.py`) must count a meeting ONLY when the lead
category is **"Call booked"** — no other category, no heuristic.
*Done-rule: a grep across the repo finds no meeting count sourced from any
other category, and live analytics totals visibly drop to the Call-booked-only
number.*

**8. Re-audit (verification).** Re-run the step-1 audit end to end on the
deployed fix, attempting to recreate every original symptom. No sends to
active prospects — only the "Not interested"/"No worries" allowance from the
safety rails, and only if a live send test is genuinely required.
**Every fix must be verified in the LIVE UI** (owner ruling 2026-07-30): drive
the actual setter page in a browser — tray rows visible, conversation opens
fast, Not-qualified button files the lead, send flow completes without an
error banner. API-probe evidence alone NEVER closes a step; if it isn't seen
working in the live UI, the task is not done.
*Done-rule: none of the six symptoms reproduce in the live UI; each has a
one-line "tried X, saw Y in the UI" proof.*

**9. Expert panel + optimise.** Spawn a panel of 5 agents — 2 front-end
(setter.html: rendering, perceived speed, UX), 3 back-end (setter.py/server.py:
memory, concurrency, query efficiency) — each independently scoring the setter
code 1–10 with specific findings. Apply their highest-impact findings, then
re-vote. Repeat (within the retry cap) until **every** expert votes 9/10 or
higher.
*Done-rule: 5/5 votes ≥ 9, and every applied optimisation kept steps 2–8's
done-rules green (re-check the cheap ones).*

## Done rule (whole loop)

All nine step done-rules pass on the LIVE deployed tool, the panel vote is
5×(≥9/10), tests (`app/test_setter.py`) are green, and the work is committed
and pushed. Then report: what changed, per-issue proof, panel scores, and
anything deliberately left open.
