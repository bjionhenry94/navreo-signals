---
name: engine-room-mailboxes-tab
description: One-shot orchestration loop that moves the "Engine room" (mailbox & domain manager) out of the Analytics tab into its own sidebar "Mailboxes" tab in the navreo-signals tool, sets the Campaigns icon to a paper plane and the Mailboxes icon to an envelope, and verifies the old Analytics page no longer loads or expects any engine-room/deliverability-manager data (frontend + backend). Trigger phrases - "move the engine room to its own tab", "mailboxes tab", "run the engine-room tab loop", "/engine-room-mailboxes-tab".
---

# Engine Room → Mailboxes tab

## LOOP TRAINING MODE — the toggle (read this first)

```
LOOP_TRAINING_MODE: OFF       ← flip to ON to pause at every step for approval
```

**When ON (default):** pause at EVERY step below and wait for Bjion's explicit
approval in chat before continuing. Before pausing, run the step's done-rule:
if it already passes, say so, SKIP the step, and move to the next pause. Only
re-run steps that fail their done-rule. Never re-run a passing step.

**When OFF:** run all steps end-to-end with no pauses, but still run every
done-rule check and still respect the retry cap.

**Retry cap (both modes):** max **3 attempts per step**. On the 3rd failure,
STOP the loop, report exactly what failed and what was tried, and wait for
Bjion. Never loop forever.

To flip the toggle: edit the `LOOP_TRAINING_MODE:` line above and save.

## Goal

Deliverability insights get their own front door. The whole-fleet mailbox &
domain manager ("Engine room") leaves the Analytics page and becomes a
first-class sidebar tab called **Mailboxes** (envelope icon, like Smartlead's
"Sender Accounts"). Campaigns gets a **paper plane** icon. The Analytics page
is left clean: it keeps its own hub data but no longer loads, mounts, or
prefetches anything that only the engine room used.

## Ground truth (recon already done — do not re-derive)

Repo: `~/navreo-signals` (deploys to https://navreo-signals.onrender.com via git push to Render).

- **Engine room block**: `app/deliverability.html` — the `<details id="dlv-embed-fold">`
  fold (~line 510) with `#dlv-embed-slot`, plus the deferred-mount script
  (~lines 638-660: `window.DLV_EMBED = true`, `<script src="deliverability-tab.js">`,
  the `mountEngine()` idle/toggle/2.5s loader), plus the "client view folds
  shut" logic near ~line 2417.
- **Engine renderer**: `app/deliverability-tab.js` — exposes `window.renderDeliverability()`,
  mounts into `#dlv-embed-slot` when `window.DLV_EMBED` is set. Its endpoints:
  `/api/deliverability/*` proxy (`_bundle`, `_audit`), `/api/mailbox-settings-audit`,
  `/api/restore-plan`, `/api/restore-live`, plus shared reads it may reuse via
  `window.__ahFetch` (`/api/deliverability-trends`, `/api/signals/daily`,
  `/api/cockpit/insights`).
- **CAREFUL — shared endpoint**: the analytics hub ITSELF uses
  `/api/deliverability/_audit` (deliverability.html ~line 2580, `AUDIT` for hub
  cards). That call STAYS on the Analytics page. "No longer expecting
  deliverability data" means engine-room-ONLY calls, not this one.
- **Sidebar**: `app/shell.js` — `ICONS` map (~line 36) + `NAV` array (~line 44).
  Campaigns currently `ic8("send")` → `icons/send.png`. `icons/mail.png`
  (envelope) already exists. `ic8("name")` defaults to `.png`.
- **Backend gate**: pages are static files behind a default-ON login gate
  (`server.py` ~17324, `_AUTH_PUBLIC_GET` whitelist ~17339). A new
  `mailboxes.html` is automatically login-gated — do NOT whitelist it.
- **Headless rule**: any page with `?chrome=none` must hide the rail (shell.js
  handles this globally — just use `renderRail()`).
- **Tests**: `app/test_deliverability_flows.py` may assert the embed lives on
  deliverability.html — update assertions, don't delete coverage.
- **Live-verify recipe** (memory `signals-live-verify-recipe`): git push, poll
  `/api/version` until the new commit serves, then mock-login (mint
  `navreo_session` cookie) and load pages in the browser pane.

## Steps

### Step 1 — Baseline snapshot
Record (a) the exact engine-room block boundaries in deliverability.html,
(b) current `NAV`/`ICONS` in shell.js, (c) `git log -1 --oneline` and a clean
`git status` in ~/navreo-signals. Stash nothing; if the tree is dirty with
unrelated work, STOP and ask (parallel-session commit contamination has bitten
before — memory `analytics-speed-accuracy-shipped`).
**Done-rule:** boundaries + baseline commit written into the loop's session
notes; working tree clean or Bjion has ruled on the dirt.

### Step 2 — Create `app/mailboxes.html`
New page, same shell as siblings (loads `shell.js`, `restore-reconcile.js`,
`navreo.css`; `renderRail("mailboxes")`). Sets `window.DLV_EMBED = true`,
includes `deliverability-tab.js`, provides `#dlv-embed-slot` (NO `<details>`
fold — the manager IS the page, mount `renderDeliverability()` immediately on
DOMContentLoaded, no idle deferral). Page `<h1>`/title: "Mailboxes". Keep the
"Engine room" wording as a subtitle so ops recognise it.
**Done-rule:** file exists; a local serve (`python3 app/server.py` or the
mock-login flow) renders the manager with live data and zero console errors.

### Step 3 — Sidebar: new tab + icons
In `shell.js`: add `["mailboxes.html", "mailboxes", "Mailboxes"]` to `NAV`
(place it after Campaigns, mirroring Smartlead's Campaigns → Sender Accounts
order); add `ICONS.mailboxes = ic8("mail", "lg")` (envelope). Campaigns must
render a **paper plane**: eyeball `icons/send.png` — if it is already a paper
plane, no change; if not, add a paper-plane PNG from the same Icons8
"Windows 10" set as `icons/paper-plane.png` and point `ICONS.campaigns` at it.
**Done-rule:** every page's rail shows 5 items (Campaigns ✈, Lists, Analytics,
Mailboxes ✉, Setter) + Settings; active-state highlights correctly on
mailboxes.html; `?chrome=none` still strips the rail.

### Step 4 — Strip the engine room out of Analytics (frontend)
In `deliverability.html`: remove the `<details id="dlv-embed-fold">` block, the
deferred-mount script, `window.DLV_EMBED`, and the `deliverability-tab.js`
include; remove the client-view fold-shut logic (~2417) and any comments that
promise the manager is "inline below". In its place leave ONE quiet line:
`Mailbox & domain health has moved → <a href="mailboxes.html">Mailboxes</a>`.
KEEP the hub's own `/api/deliverability/_audit` read and all hub cards.
**Done-rule:** load Analytics with the network tab open — ZERO requests to
`/api/deliverability/_bundle`, `/api/mailbox-settings-audit`,
`/api/restore-plan`, `/api/restore-live`; no console errors; hub cards all
still render with live numbers; `grep -c "DLV_EMBED\|dlv-embed\|deliverability-tab.js"
app/deliverability.html` returns 0.

### Step 5 — Backend sanity
Confirm in `server.py`: (a) `mailboxes.html` is NOT in `_AUTH_PUBLIC_GET`
(gated by default — verify an unauthenticated GET redirects to login);
(b) all engine-room endpoints (`/api/deliverability/*`, `/api/mailbox-settings-audit`,
`/api/restore-plan`, `/api/restore-live`) are page-agnostic and untouched;
(c) grep server.py for `deliverability.html` comments/references that now lie
(e.g. "app/deliverability.html" section headers describing the embed) and fix
the ones that mislead — comments only, no behaviour changes.
**Done-rule:** unauthenticated GET `/app/mailboxes.html` → login redirect;
authenticated GET → 200; no server code change beyond comments.

### Step 6 — Tests
Update `app/test_deliverability_flows.py` (and any other test greping for
`dlv-embed`/`DLV_EMBED` in deliverability.html) to assert the NEW truth: embed
markers absent from deliverability.html, present in mailboxes.html. Run the
suite the repo actually trusts (`python3 app/test_deliverability_flows.py`
directly — memory: pytest lies for this repo).
**Done-rule:** the deliverability-flow tests pass; no other test in app/
regresses (run the neighbours that touch deliverability/shell).

### Step 7 — Ship + live verify + hand over
Commit (one commit, message names the move), push, poll `/api/version` until
the new commit is live. Mock-login and verify IN THE BROWSER PANE:
(1) `/app/mailboxes.html` renders the full manager with live fleet data;
(2) `/app/deliverability.html` renders the hub, engine room gone, moved-link
present, no engine-room network calls; (3) rail icons: Campaigns = paper
plane, Mailboxes = envelope, active states right. Screenshot both pages. Then
hand Bjion the VERIFIED links (memory `updates-need-verified-link`: never an
unverified link) with a 3-line plain-English summary.
**Done-rule:** both live URLs confirmed rendering on the deployed commit;
screenshots taken; links + summary delivered in chat.

## Loop done-rule (the whole loop is finished when…)

All of the following are true on the LIVE deployed site:
1. Sidebar has a Mailboxes tab (envelope) rendering the complete engine-room
   manager as its own page, login-gated.
2. Campaigns tab shows a paper plane.
3. Analytics (`deliverability.html`) contains no engine-room markup, script,
   or engine-room-only network call — frontend AND backend references
   updated — while every analytics-hub card still shows live numbers.
4. Tests encoding the new layout pass.
5. Bjion has received verified live links + screenshots.

## Guardrails

- NEVER touch Smartlead sends or lead rows — this is pure UI/plumbing
  (memory `never-send-to-real-prospects` still applies globally).
- Do not "improve" the engine room's internals while moving it — verbatim
  relocation. One loop, one concern.
- Do not build deliverability.html from any template — edit the live file
  directly (memory `strategy-html-diverged-from-template` class of bug).
- If a step's done-rule fails 3×, stop and report — no silent scope creep.
