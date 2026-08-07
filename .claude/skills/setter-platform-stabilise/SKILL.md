---
name: setter-platform-stabilise
description: Static orchestration skill that stabilises the Appointment Setter (app/setter.html + app/setter.py in ~/navreo-signals, live at navreo-signals.onrender.com/app/setter.html) against the full 2026-08-01 owner bug list — send/queue 502s, slow conversation history (pre-cache to Supabase on reply landing), one-click Not qualified, Sent-without-follow-up tray misses, meetings over-count (Call booked only), categoriser mislabels, adjustable+persistent sidebar, follow-up tray auto-advance, regen first-click blank, definite send confirmation, instant recategorise, copy-email button, timezone surfaced in drafts, duplicate-send hard block, client-workspace history, and setter clients auto-added at onboarding — then a front-end + back-end tester panel must score the surface 9/10+ on Stability, Data validity, and Code efficiency before the loop can close. Every fix is verified in the LIVE UI. Supersedes setter-stability-loop. Trigger with "/setter-platform-stabilise", "run the setter stabilise loop", or "continue the setter platform loop".
---

# Setter Platform Stabilise

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

Stabilise the Appointment Setter platform: remove redundant code, improve
efficiency, and kill the full owner bug list — no 502s on send or refresh, a
send that always confirms or clearly fails (never silently doubles), instant
Supabase-cached conversation history on every workspace, honest category and
meeting counts, a sidebar and follow-up tray that behave, and setter client
wiring that happens automatically at onboarding — held to a 9/10+ tester bar
on Stability, Data validity, and Code efficiency.

## Hard safety rails (apply to every step, no exceptions)

- **NEVER send to real positive prospects.** Test send paths with `is_test`
  rows only; check `row.status` before ANY Smartlead write. The ONLY permitted
  live send: a **"Not interested"** prospect may be replied to with a plain
  **"Ok, no worries."** — nothing else, no other categories.
- Repo: `~/navreo-signals`. Live verify: mint a `navreo_session` cookie, poll
  `/api/version` until the deploy lands (memory: signals-live-verify-recipe).
- The web instance is a 512MB Render starter — heavy sweeps belong in crons,
  never in-process on web (memory: web-instance-oom-crashloop).
- Setter queue row ids are NOT stable across re-intake — key everything by
  `lead_email` + `message_id`, captured at render time.
- **Every fix is verified in the LIVE UI** (owner ruling 2026-07-30): drive
  the actual setter page in a browser. API-probe evidence alone never closes a
  step.

## Steps

Key files: `app/setter.py` (~10.2k lines), `app/setter.html` (~4.9k lines),
`/api/setter/*` dispatch in `app/server.py`. Each step = audit → fix → verify
against its done-rule. Prefer deleting redundant code over adding new code.

**1. Audit pass (read-only).** Reproduce every issue below without sending
anything: minted-session API probes, live UI walk-through, Render logs,
`server_boot_ledger`. *Done-rule: each issue has a root-cause hypothesis
pinned to file:line, or "cannot reproduce" with evidence.*

**2. Send pipeline — no 502s, definite outcome, confirmation.** Covers three
owner reports: "Couldn't send the reply: Request failed (502)"; "sometimes I
send and don't know if it actually sent"; "confirmation the email sent would
be useful". Audit `/api/setter/queue/action` send/send_followup and the
202-job async path end to end (timeout budget near setter.py:1637). Every
send must end in exactly one of: a visible SENT confirmation (with recipient
+ subject) or a clear retryable error — never silence, never a dead 502.
*Done-rule: 20 consecutive `is_test` sends show the confirmation state with
zero 502s; a forced failure shows a retry, not silence; the live UI shows a
sent-confirmation on a real "Ok, no worries." send to a Not-interested row.*

**3. Duplicate-send hard block.** Owner report: clicking Submit sometimes
re-renders the OLD first generation, and clicking again sent two emails.
Two fixes, both required: (a) the stale-generation re-render after submit
(client state must move to the in-flight/sent view immediately, and a
completed regen must never resurrect a previous draft); (b) a server-side
idempotency gate — **two outbound sends to the same `lead_email` within 10
minutes are rejected** with a clear "already sent moments ago" message, no
matter what the client does. Enforce at the API layer, not just the UI.
*Done-rule: double-clicking Submit on an `is_test` row produces exactly one
outbound job; a scripted second send to the same lead inside 10 min returns
the rejection; the old-draft re-render no longer reproduces.*

**4. Queue-refresh 502s.** "Couldn't refresh the queue: Request failed
(502)" is regular. The queue is a memoized single-flighted gzip corpus
(`queue_response`) — audit boot-burst behaviour and memory headroom; refresh
must serve stale-while-revalidate rather than 502. *Done-rule: 30 consecutive
live refreshes (including one straight after a deploy restart) return 200 or
explicitly-stale data, never a 502.*

**5. Conversation history pre-cache.** History hydrates live from Smartlead
on open (`hydrate_lead`, setter.py:1853) — too slow. As soon as a reply
lands (poll/webhook intake), persist the FULL conversation history to
Supabase; thread reads serve Supabase-first with live hydrate only as
fallback/refresh. Key by `lead_email` + `message_id`. *Done-rule: opening a
conversation renders history from cache in under 1s on live; a fresh inbound
reply's history is in Supabase within one poll cycle.*

**6. Client-workspace conversation history.** History doesn't work on client
conversations — the known thread-hydration gap from the all-workspaces
federation (memory: setter-all-workspaces-federation). Extend step 5's cache
+ hydrate to every workspace via the per-workspace Smartlead key. *Done-rule:
a client-workspace row (Amplifyy/Arnic/Grout etc.) opens with full history in
the live UI.*

**7. Category actions — one-click, instant, honest tray.** Three owner
reports in one surface (`route_queue_recategorise` + the category control in
setter.html): (a) a single-click **"Not qualified"** button in the
change-lead-category section — no dropdown digging; (b) recategorising to Not
qualified must remove the row from the queue view INSTANTLY, no repeat
needed; (c) the "Sent without follow-up" tray must include replies whose
follow-up choice was "None" at send time — 'none' is a mark, not a removal
(audit `_followup_category_ok` / `subsequence_decision` filtering in
setter.py ~5318–5490 for the dropped case). *Done-rule: one click marks a
row Not qualified and it leaves the visible queue without a reload; a test
row sent with decision "none" appears in the tray; explicit Dismiss is the
only non-category action that removes it.*

**8. Meetings = Call booked only.** Meetings-held is over-reported. Every
surface that counts meetings (setter stats, analytics hub, weekly digests,
client windows in `app/server.py`) counts a meeting ONLY when the lead
category is **"Call booked"** — no other category, no heuristic. *Done-rule:
a repo grep finds no meeting count sourced from any other category, and live
analytics totals drop to the Call-booked-only number.*

**9. Categoriser accuracy.** People are being mislabelled as "Meeting
Request" and similar. Audit the categoriser chain — the Make webhook
categoriser output, the Smartlead-categoriser veto (setter.py ~304, ~1024–
1074), and uncategorised intake (~3169) — and tighten the rules/prompt so a
reply is only "Meeting Request" when it actually asks for a meeting. Build a
labelled fixture set from real archived replies (read-only) to measure
against. *Done-rule: on a ≥20-reply labelled fixture set the categoriser
scores ≥90% with zero false "Meeting Request" labels, and the fixture set is
committed as a regression test.*

**10. Sidebar — adjustable and remembered.** The conversation-list sidebar
must be user-resizable (drag handle), and its state — width AND
minimised/collapsed — must persist across refresh (localStorage; the
existing mobile-detail handling near setter.html:2123 must keep working).
*Done-rule: resize + minimise, hard-refresh, and the live UI restores both
exactly.*

**11. Follow-up tray — advance, don't bounce.** Processing someone in the
follow-up tray makes the UI jump around after send. On send/dismiss the tray
must progress smoothly to the next person in the queue — no scroll jump, no
list re-shuffle under the cursor. *Done-rule: processing 3 consecutive
`is_test` tray rows lands focus on the next row each time with no visible
bounce in the live UI.*

**12. Regenerate first-click blank.** First Regenerate often completes but
renders nothing; a second click shows it. Audit `doRedraft`
(setter.html:3367) and the blank-draft path noted near setter.html:3846 —
the completed regen must always render its result. *Done-rule: 10
consecutive first-click regens on live rows each render a draft, zero blanks.*

**13. Copy-email affordance.** One-click copy of the recipient's email
address from the conversation/lead sidebar (copy icon + "Copied" feedback).
*Done-rule: the button copies the exact address to the clipboard in the live
UI.*

**14. Timezone surfaced in drafts.** When the lead's timezone is known
(`guess_timezone`, setter.py:541), the draft must either suggest a concrete
time in THEIR timezone or the draft context must state why it didn't (e.g.
low confidence). No more silently ignoring a known tz. *Done-rule: a redraft
of a scheduling-type test reply with a known tz proposes a time localised to
it, and a no-tz row shows the stated reason instead.*

**15. Setter clients auto-onboard.** Adding new clients into the setter must
be part of onboarding, not manual. Extend the `/onboard-client` skill so
onboarding a client wires the setter too (workspace row, agent/campaign
assignment via the `/api/setter/*` admin routes the lilly-appointment-setter
skill already uses) — zero code edits per new client (memory:
client-workspace-labels-one-source). *Done-rule: onboard-client's SKILL.md
contains the setter wiring step, and a dry-run against the demo client shows
the setter picking the client up with no manual edit.*

**16. Redundancy sweep.** With all fixes green: remove dead code paths,
duplicated helpers, and superseded branches touched by this loop in
setter.py/setter.html; keep behaviour identical. *Done-rule:
`app/test_setter.py` green, net negative or neutral line count for the sweep
commit, and steps 2–15's cheap checks still pass.*

**17. Re-audit + live UI verification.** Re-run step 1 end to end on the
deployed build, attempting to recreate every original symptom in the LIVE UI
— tray advances, history opens instantly (client workspaces too), one-click
Not qualified files and disappears, sends confirm, doubles are blocked.
*Done-rule: no symptom reproduces; each has a one-line "tried X, saw Y in
the UI" proof.*

**18. Tester panel + optimise to 9/10.** Spawn a panel — 2 front-end testers
(setter.html: rendering, perceived speed, UX) and 3 back-end testers
(setter.py/server.py: memory, concurrency, query efficiency, data
correctness) — each independently scoring **Stability**, **Data validity**,
and **Code efficiency** 1–10 with specific findings. Apply the
highest-impact findings, re-vote, repeat within the retry cap until **every
tester scores every dimension ≥ 9**. *Done-rule: 5/5 testers at 9+ on all
three dimensions, with steps 2–17 still green.*

## Done rule (whole loop)

All eighteen step done-rules pass on the LIVE deployed tool, the panel vote
is 5×(≥9/10 on all three dimensions), `app/test_setter.py` is green, and the
work is committed and pushed. Then report: what changed, per-issue proof, the
panel scores, and anything deliberately left open — with a browser link
confirmed to load (memory: updates-need-verified-link).
