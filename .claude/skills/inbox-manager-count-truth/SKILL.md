---
name: inbox-manager-count-truth
description: >-
  Orchestration skill that makes every mailbox/domain count on the Inbox & Domain
  Manager (the deliverability warm-up manager — Below reply floor / Not warming /
  In warm-up / Needs reconnect tabs + Overview) TRUE: it audits the backend
  payload, reconciles it against what a live browser actually shows, fixes the
  frontend derivation until they agree, and re-verifies live per tab and per
  scenario. Use whenever the manager's numbers look inconsistent — a header total
  that doesn't equal the visible rows, a tab badge that disagrees with the row
  count, "sends paused (N)" larger than the domain's mbx count, a 30-domains×52
  vs 1262 style mismatch, or any "the numbers on this page don't add up" report.
  Trigger phrases: "the counts are wrong on the deliverability page", "audit the
  mailbox numbers", "the warm-up totals don't match", "make the inbox manager
  counts accurate", "/inbox-manager-count-truth".
---

# Inbox & Domain Manager — Count Truth

A static, run-until-done loop that makes every number on the deliverability
manager reconcile: **backend payload → derived display → live browser**, on
every tab and every scenario. Read it top-to-bottom once; then run it.

---

## ⚙️ Loop Training Mode — TOGGLE (read this first)

```
LOOP_TRAINING_MODE = OFF       # ON (default) = supervised · OFF = autonomous
```

Flip the value above to switch modes. Nothing else changes.

**When ON (default):**
- Pause at the end of **every step** and wait for Bjion's approval before moving on.
- **Skip** any step whose done-check already passes — don't re-run passing work.
- **Only re-run** the steps that fail.
- Respect the retry cap below — never loop forever.

**When OFF:**
- Run **autonomously**, no pauses, straight through the steps.
- Still run **every done-check** and still respect the **retry cap**. Autonomy
  removes the pauses, not the checks.

**Retry cap (both modes):** per step **≤ 3** attempts; whole loop **≤ 2** full
passes of Steps 1–5. If a step still fails after its cap, **STOP** and report the
exact tab + invariant that won't reconcile. Do not keep trying.

---

## 🎯 Goal

Improve the accuracy of what the manager shows. Every count a person sees in a
**live browser** — on each tab and in every scenario — must be reproducible from
the backend payload, and no two on-screen numbers may contradict each other.
Fix in the backend/derivation, then prove it on the front end. Not done until
backend and live front end agree.

---

## 🗺️ Scope map (the real anchors — don't rediscover these)

**Page:** `app/deliverability.html` → loads `app/deliverability-tab.js`
**Prod:** `https://navreo-signals.onrender.com/app/deliverability.html`
**Repo:** `~/navreo-signals`

**Backend / source of truth (two layers):**
- **Payload** — `/api/deliverability/_bundle` (proxy in `app/server.py` → the
  *external* audit service; needs `DELIV_AUDIT_AUTH`). Locally the deterministic
  stand-in is **`app/mock_deliv.py`** — use it to fabricate edge scenarios.
  The audit repo itself is NOT local — you cannot edit it. `restN`/restore data
  also comes from the native `/api/restore-plan`.
- **Derivation** — the display numbers are computed in `app/deliverability-tab.js`:

| What's shown | Where it's built (`deliverability-tab.js`) |
|---|---|
| Tab badges (Below reply floor / Not warming / In warm-up / Needs reconnect) | `mgrFlowCounts(D)` ≈ L4112, from `A.inboxRows.filter(...)` L1067–1069 |
| Tab keys ↔ labels | `floor` / `notwarming` / `inwarmup` / `reconnect` ≈ L3842 |
| Header `D domain(s) · M mailbox(es)` | L4320 (`doms.length` + `mbxTotal`) |
| `mbxTotal` | L4301 |
| "mailbox detail limited to the first 2,000" note | `flowTruncated(flow)` → `truncNote` L4296 |
| "None of these **N** are sending" copy | L4355 (must use the SAME `mbxTotal`) |
| Per-row `· N mbx` | `boxN` L4230 / `_domBoxes` L4372 |
| `sends paused (N)` | `restN` L4226 |

**The 2,000-row trap (this is usually the bug):** `S.A.inboxRows` (mailbox-level)
is capped at the first 2,000 rows, but *every domain is still listed*. So a
header total summed from the capped rows will not equal the sum of the per-domain
badges when a domain-level field feeds those badges. That is the classic
`30 domains × 52 = 1560 ≠ 1262` contradiction. One field must feed both, or the
partial total must be labelled as partial. Never mix.

---

## ✅ The invariants (the done-rule, per tab)

Run these for **each** manager tab — `floor`, `notwarming`, `inwarmup`,
`reconnect` — **and** the Overview:

- **INV-1** Tab badge = number of domain rows that tab actually renders = count derived from the payload for that `kind`.
- **INV-2** Header `D domain(s)` = number of rendered rows = the tab badge.
- **INV-3** Header `M mailbox(es)` = Σ of every visible row's `· N mbx`. If the 2,000 detail cap is in effect, the header MUST label the figure partial and MUST NOT present a silently-contradicting fleet sum. Choose one and stick to it: either (a) a true domain-level fleet total that *also* feeds the per-row counts, or (b) the capped sum, explicitly labelled.
- **INV-4** Every row: `sends paused (M)` has **M ≤ N** (row's mbx count), and both come from the same payload.
- **INV-5** The "None of these **N** are sending" copy uses the exact same `mbxTotal` as the header.
- **INV-6** Buckets are mutually exclusive — a domain/mailbox sits in exactly one of floor/notwarming/inwarmup/reconnect; no double-count.
- **INV-7** Overview fleet totals reconcile with the manager tabs (Overview = whole fleet; tabs = subsets that must not exceed it).

A tab **passes** only when INV-1…7 all hold **in a live browser**, not just in code.

---

## 🔁 Steps (the loop)

Each step has its own done-check so Loop Training Mode can skip passing steps.

**Step 0 — Pick the surface.**
For editing + deterministic edge cases: run local (`./run-signals-dev.sh`) with
`app/mock_deliv.py`. For final truth: the prod live bundle. *Done-check:* server
up, `deliverability.html` loads, one manager tab renders.

**Step 1 — Capture BACKEND truth.**
For every tab, pull from the payload: domain count, each domain's mailbox count,
each domain's paused count, fleet mailbox total, and the truncation flag. Write
them down. *Done-check:* a truth table exists for all four tabs + Overview.

**Step 2 — Capture FRONTEND rendered.**
In a live browser, on each tab read: tab badge, header `D domain(s) · M mailbox(es)`,
every visible row's `· N mbx` and `sends paused (M)`, and the cap copy. *Done-check:*
rendered numbers recorded for all four tabs + Overview.

**Step 3 — Reconcile.**
Run INV-1…7 across every tab. List each violation as `tab · field · expected vs shown`.
*Done-check:* zero violations, or a written violation list.

**Step 4 — Fix (backend/derivation).**
For each violation, correct the derivation at the anchor above (`mgrFlowCounts`,
`mbxTotal` L4301, header L4320, per-row `boxN`/`_domBoxes`, `restN`, cap copy L4355)
or the `/api/deliverability` proxy in `app/server.py`. Rule: **one source per number**,
honest truncation labels. Fix root cause, not the string. *Done-check:* every
violation's cause is addressed in code.

**Step 5 — Re-verify LIVE (the real gate).**
Reload the live browser, re-read every number on every tab, re-run INV-1…7. Then
exercise these scenarios via `app/mock_deliv.py` and confirm each stays consistent:
(a) truncation > 2,000 rows, (b) a domain with < the usual mbx count, (c) a fully
paused domain, (d) a recovered domain, (e) an empty tab (0 domains), (f) a
reconnect-only fleet. *Done-check:* every tab × every scenario → zero violations,
observed in a live browser.

**Step 6 — Ship + confirm prod.**
Commit; deploy; re-check the prod live browser. ⚠️ Keep heavy work in crons, not
in-process — the web instance is a 512 MB starter and OOM-crash-loops on big
in-process sweeps. *Done-check:* prod live browser shows reconciled numbers on
all tabs.

---

## 🏁 Done-rule

Done only when, on the **live** front end, for **every** manager tab (Below reply
floor / Not warming / In warm-up / Needs reconnect) **and** the Overview, and
across **every** scenario in Step 5:

> every displayed count is reproducible from the backend payload, and no two
> on-screen numbers contradict each other (badge ↔ rows ↔ header domains ↔
> header mailboxes ↔ per-row sum ↔ paused ≤ total ↔ cap copy).

Backend change made, front end reflects it, both agree in a real browser. If any
tab/scenario still fails after the retry cap — stop and report which invariant on
which tab won't reconcile.

---

## Live-verify recipe (how to actually look)

The page is login-gated (`navreo_session` cookie). Verify against the running
server — mint the session cookie and poll `/api/version` to confirm the deploy is
live before reading numbers (see the *signals live-verify* memory). Adding
`?chrome=none` hides the sidebar rail if you want a clean read. Prefer reading
numbers with the browser tools' `read_page`/`get_page_text` over screenshots so
the counts are exact text, not pixels.
