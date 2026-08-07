---
name: strategy-session-share
description: Orchestration skill that makes the lilly-strategy board a session-scoped campaign whiteboard with a client-shareable permalink. Every new chat session gets its OWN run (no more one-global-run clobbering between sessions), the GTME drives all edits through chat with the dashboard reacting live, and each run mints a permalink the GTME can send a client — the client opens it without logging in, can edit the COPY only (saves + reflects back to the GTME), and never sees the Build button. Runs a fixed goal → steps → done-rule loop with a Loop Training Mode toggle (pause-for-approval vs autonomous). Use when asked to make strategy runs session-specific, add the client share link, stop sessions overwriting each other's boards, or when someone says "run the strategy session share loop".
---

# Strategy Session + Share Loop

A static, pre-baked loop for turning the strategy board from one shared global run into per-session whiteboards with a client permalink. Read it top to bottom once; it does not change between runs.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip this one word to change how the whole loop runs. Default is **ON**.

**When ON (default — training):**
- **Pause at every step.** Do the step, show the result, then STOP and wait for my explicit approval before moving on.
- **Skip any step that already passes its done-rule.** Check the done-rule first; if it's already green, say so and move on. Don't redo finished work.
- **Only re-run steps that fail.** If a step's done-rule fails, fix and re-run that step only, not the whole loop.
- **Retry cap: 3.** Max 3 attempts on any one step. After 3 fails, STOP and surface the blocker in plain English. Never loop forever.

**When OFF (autonomous):**
- **No pauses.** Run every step start to finish without waiting for approval.
- **Keep the done-rule checks.** Every step is still gated on its done-rule; a failed done-rule still blocks progress.
- **Keep the retry cap (3).** Same 3-attempts-then-stop rule. Autonomous ≠ infinite.

> To change it later: edit the line above to `→ OFF` (or back to `→ ON`). Nothing else in this file needs touching.

---

## 🎯 Goal

Make it easier to **save, manage and share** campaign-idea boards:

1. **Session-scoped runs.** The board is a campaign whiteboard for ONE set of ideas. Today `/api/strategy/run` stores a single global run (`campaign_insights` scope=`strategy`, insight_key=`wizard_run`, latest live row wins) — every publish clobbers the last session's board. Instead: every new lilly-strategy session mints a fresh `run_id` and publishes to it; older runs stay saved and re-openable, untainted by later sessions. Chat stays the steering wheel (targeting edits, copy, icebreakers, right up to just-before-pull); the dashboard is exactly that — an interactive dashboard that reacts.
2. **Client share permalink.** Each run mints a stable share URL the GTME sends the client. The client opens it WITHOUT logging in, sees the same presentation, and can edit the **copy only** — their edits save and reflect back to the GTME's view. The client NEVER sees the Build button or any GTME-only controls (build/checks/pull machinery).

## 🔒 Design contract (keep / drop — never violate)

**KEEP:** the existing board UI and 5-stage flow for the GTME (Targeting · Copy · Icebreaker · Build · Live) · the 5s poll + chat-mirror focus behaviour · the engine-field stripping on GET (`pull_spec`/`probe`/`netting` never reach any page) · the login gate for the GTME view · the `campaign_insights` storage pattern (scope/insight_key/payload/status supersede-chain) · lilly-strategy's publish flow (validate → POST → welcome message).

**DROP:** the one-global-run model. No new session may ever overwrite another session's board.

**THE MODEL (follow the house patterns, don't invent):**
- **Run identity:** `insight_key = "wizard_run:<run_id>"` rows (same table, same supersede-chain per run). `run_id` = short slug `<client>-<YYYYMMDD>-<4char>`. `GET /api/strategy/run?id=<run_id>` returns that run; **bare GET keeps returning the newest run so the existing board and old links don't break**. POST requires `run_id` in the payload (server falls back to legacy key if absent, warning in response).
- **Board URL:** `strategy.html#/r/<run_id>` — the page reads the hash and polls with `?id=`. Bare `strategy.html` = newest run (back-compat).
- **Share link:** copy the PROVEN setter-training pattern (`?share=<token>` allowlist bypassing the login gate, token verified server-side). Token = HMAC over `run_id` with the existing `_auth_secret()`; share URL = `strategy.html#/r/<run_id>?share=<token>`. The shared GET is read-only EXCEPT one new endpoint: `POST /api/strategy/copy-edit` `{run_id, ideaId, field, value, share}` — accepts ONLY copy fields (`pain`/`moment`/`videoAngle`/`offer` + email-version overrides), validates the token, writes a superseding run row, stamps `edited_by:"client"`.
- **Client mode = capability flags, not CSS hiding:** when the page loads via `?share=`, it renders with `mode:"client"` — Build/checks/Live tabs and every GTME action NOT in the DOM (not just hidden). Copy fields become editable-in-place with a save that POSTs copy-edit. GTME's open board picks the change up on its next poll (the run row superseded → memo busted, same as today).
- **Session-specificity in lilly-strategy:** the skill's Phase 5 "Launch the board" step mints the run_id ONCE per chat session, publishes/re-publishes to it all session, and the welcome message + `open`/SendUserFile all use the `#/r/<run_id>` URL. A NEW session NEVER reuses a previous run_id (resuming an old board is an explicit ask: "open the <client> board from <date>").
- **Focus signals** become per-run too (`wizard_focus:<run_id>`), so one session's chat-mirror never steers another session's open board.

**GOTCHAS (design around, learned the hard way):**
- Edit `~/navreo-signals/app/strategy.html` DIRECTLY — it has DIVERGED from lilly-strategy/wizard-template.html; `build_live.py` reverts live UI (memory `strategy-html-diverged-from-template`, the Start-button regression).
- The web instance is a 512MB Render starter — no heavy loops in-process (memory `web-instance-oom-crashloop`). The per-run memo must stay a small dict (cap memoized runs, e.g. 8 LRU).
- `campaign_insights.data_fingerprint` is NOT NULL; `expires_at` defaults +7 days — set 2036 like the existing writes.
- `/api/version` is 401 without a cookie on Render — check status codes when verifying deploys.
- Never claim the board updated on a non-ok POST; verify by GET after every write.

---

## 🪜 Steps (each has its own done-rule — that's what Loop Training Mode gates on)

**1 · Frame.** Read `strategy_run_get/post`, `strategy_focus_post`, the login-gate + `_TRAIN_SHARE_GET` share pattern in `~/navreo-signals/app/server.py`, and strategy.html's poll/render code. Write the exact API contract (endpoints, params, token scheme, client-mode flag) and the strategy.html changes list.
  - *Done-rule:* contract written down covering: keyed GET/POST, back-compat bare GET, share-token mint+verify, copy-edit endpoint + allowed fields, client-mode rendering, per-run focus.

**2 · Server.** Implement in `app/server.py`: keyed run storage + LRU memo, `?id=` GET, run_id POST, share-token mint endpoint (GTME-only: `POST /api/strategy/share {run_id}` → `{url}`), share-gated GET, `POST /api/strategy/copy-edit` (copy fields only, token-verified, supersede-write, `edited_by:"client"`).
  - *Done-rule:* local server test proves — two runs stored under different ids without clobbering; bare GET returns newest; keyed GET returns the right one; copy-edit with a valid token changes ONLY the copy field and stamps `edited_by`; copy-edit with a bad token / non-copy field is rejected; login gate still blocks un-shared paths.

**3 · Board.** Edit `app/strategy.html` DIRECTLY: hash-route `#/r/<run_id>` → keyed poll; `?share=` → client mode (Build/checks/Live and all GTME actions absent from the DOM; copy fields editable-in-place with save → copy-edit POST; a soft "your edits are saved for your team" confirmation). GTME view unchanged otherwise; a client edit appears on the GTME's board within one poll.
  - *Done-rule:* headless/DOM verification — GTME URL renders full board for its run_id; share URL renders client mode with zero Build/GTME controls in the DOM; a copy-edit round-trips (client saves → keyed GET shows new value + `edited_by:"client"`).

**4 · Skill wiring.** Update `lilly-strategy/SKILL.md` Phase 5 + welcome message: mint run_id once per session (never reuse), publish to it, all links/open/SendUserFile use `#/r/<run_id>`, per-run focus key, and a "Share with your client" line in the welcome block (how the GTME asks chat for the permalink). Engine README notes run_id in run.json.
  - *Done-rule:* SKILL.md + README updated; a dry-read of Phase 5 shows no path that publishes without a run_id and no cross-session reuse.

**5 · GTME panel (roleplay).** 5 simulated GTMEs each run a fresh session: create ideas → tell chat targeting/copy/icebreaker changes → dashboard reacts (verify by keyed GET after each chat edit) → reach ready-to-share → mint the permalink. Each confirms their board was never touched by another's session and rates the flow /10.
  - *Done-rule:* all 5 complete the journey with zero cross-session interference, share links minted, all rate ≥9/10.

**6 · Founder panel (roleplay).** 5 simulated non-technical founders each open a share link in the live UI: see the presentation, edit copy, save; the paired GTME confirms seeing the change on their board. Each founder confirms NO Build button (or any build/pull control) was present, rates clarity /10.
  - *Done-rule (THE BAR):* all 5 founders — copy edit saved + GTME-confirmed reflected, zero build controls in their DOM, ≥9/10. Below the bar → fix → re-run the failing panel only (retry cap 3).

**7 · Ship + record.** Commit + push `~/navreo-signals` (server + board; surgical diffs only), verify live on Render (keyed GET, share flow, copy-edit round-trip on prod), commit skill/README changes to the skills repo, write the session file + memory (run-id scheme, share-token scheme, endpoints, commits).
  - *Done-rule:* prod verified end-to-end (two live runs co-existing, share link works logged-out, copy-edit reflects), both repos pushed, session file + memory written.

---

## ✅ Overall done-rule

Done when, ON PROD: every new lilly-strategy session publishes to its own run (old boards intact and re-openable), the GTME drives the board entirely from chat with the dashboard reacting, each run has a permalink a logged-out client can open to edit copy only (saving + reflecting back to the GTME, with no Build button in their DOM) — AND both roleplay panels (5 GTMEs, 5 founders) pass at ≥9/10 as specified in steps 5-6. Anything less is not done; anything past 3 failed attempts on a step stops and reports the blocker.

## 🧭 Runbook quick-reference
- Server: `~/navreo-signals/app/server.py` — `strategy_run_get` ~1903, `strategy_run_post` ~1968, `strategy_focus_post` ~1943, login gate + `_TRAIN_SHARE_GET` ~17140/18280 (the share pattern to copy)
- Board: `~/navreo-signals/app/strategy.html` (edit DIRECTLY — never build_live from the template)
- Storage: Supabase `campaign_insights` (scope=`strategy`), supersede-chain per insight_key; fingerprint NOT NULL, expires 2036
- Auth/token: `_auth_secret()` / `_mint_session` in server.py; cookie recipe in memory `signals-live-verify-recipe`
- Skill to wire: `~/.claude/skills/lilly-strategy/SKILL.md` (Phase 5 → "Launch the board") + `engine/README.md`
- Sessions: `~/.claude/skills/strategy-session-share/sessions/<date>.md`
