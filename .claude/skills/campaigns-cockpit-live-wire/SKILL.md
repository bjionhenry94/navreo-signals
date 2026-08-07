---
name: campaigns-cockpit-live-wire
description: Static orchestration skill that completes the campaigns section at navreo-signals.onrender.com/app/campaigns.html and moves the Lilly Optimizer fully OUTSIDE Claude. The cockpit page stops being a static hydrated artifact copy and becomes the live home, every Navreo campaign row opens an internal page (like #/arnic) with Overview / Leads / Sources / Messaging tabs wired to real data, and NO row ever auto-links to Smartlead. Claude stays the brain only, each morning it crunches insights into the Supabase campaign_insights cache and the app renders them; the /lilly-optimiser routine is repointed so its deliverable is this page, not the artifact. Navreo campaigns only for now. Fixed step list, per-step LIVE done-rules, retry caps, Loop Training Mode toggle (ON by default). Certified by a 5-expert UX panel scoring 9/10+ on navigation and factual data. Use when the user says "run the cockpit live wire", "finish the campaigns page", "wire up the campaign tabs", "make the Lilly Optimizer external to Claude", "stop campaigns linking to Smartlead", or "/campaigns-cockpit-live-wire".
---

> **SUPERSEDE NOTE (2026-08-02, platform-wide-stabilise):** app/campaigns-classic.html was REMOVED from the repo and live site (it 404s). Any step or done-rule below that expects it to serve/render is historical — skip or adapt it; the campaigns cockpit at app/campaigns.html is the only campaigns page.

# campaigns-cockpit-live-wire

Complete **`/app/campaigns.html`** on the live Navreo signals tool so it is the real, self-standing Lilly Optimizer home:

1. **Every** Navreo campaign row opens an **internal** campaign page (hash-routed, like `#/arnic`), never Smartlead. The old "rows without a page link out to Smartlead" behaviour is **overruled by Bjion** and must be removed.
2. All four tabs on every campaign page (**Overview / Leads / Sources / Messaging**) are wired to real data and work.
3. The page reads from the app's own auth-gated endpoints backed by the standing Supabase cache (`campaign_insights` and the synced tables). **Claude remains the AI layer only**: each morning it crunches and writes the cache; the app renders what Claude wrote. The brain never moves into the app.
4. The `/lilly-optimiser` routine is repointed: its deliverable becomes this page's URL, not the artifact. No more artifact republish.

Deploy model: all edits live in the git/Render repo **`~/navreo-signals`** (branch `main`); Render auto-deploys on push (~1 min for HTML-only). The iCloud copy is deprecated, never edit it. `app/campaigns-classic.html` is the preserved old console, **never touch or delete it**.

**Ship-and-verify-LIVE law.** The only proof is the rendered page on `navreo-signals.onrender.com`. The Supabase auth gate 302-redirects every anonymous request (even nonexistent paths), so anonymous curl proves nothing. Verify pages in Bjion's authenticated Chrome (claude-in-chrome) and verify endpoints with an authed same-origin fetch or authed curl. A local render or a source grep is never done-evidence.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** (say so) and move on.
- Only (re-)run steps that fail their done-rule.
- The retry cap still applies. Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule (Step 5's panel gets its own cap of **5 fix rounds**). On cap-hit: stop that step, record it FAILED with the reason, keep going, surface it in the final report. Never silently exceed.

---

## THE GOAL

On the live host, Bjion can open `https://navreo-signals.onrender.com/app/campaigns.html#/`, click through **all** Navreo campaigns, and see correct insights: every row opens its own internal campaign page, every tab works, no click ever bounces him to Smartlead uninvited. Each morning Claude crunches the data and the page shows it fresh, with no artifact in the loop. A panel of 5 UX experts scores the experience **9/10 or higher, all five**, purely on (a) navigating the experience and (b) the data shown being factually correct.

---

## STANDING TRUTH LAWS (the panel judges on these; bake them into every surface)

- ONE SOURCE, ONE WINDOW per comparable surface; where two counters coexist, print the "different counter, not a contradiction" note.
- Every printed ratio must back-solve exactly from the two numbers beside it; round correctly (50.48 → 50, not 51).
- Status tiles foot exactly to totals.
- Variant-statistics counts reset on sequence re-save: label those windows "since relaunch".
- "Unanswered" counts exclude Setter-dismissed and count setter-sent as answered.
- Say "version", never "variant", in the UI. No em dashes anywhere.
- Times render browser-local with the timezone named, never bare UTC.
- HARD RULE: every campaign row is a single full-area click target to its page (stretched-link overlay; interactive controls inside a row must raise z-index and mark `data-no-nav`).

---

## THE STEPS

### Step 0 - Pin ground truth and scope (blocking gate)
- Confirm `~/navreo-signals` is clean, on `main`, up to date with `origin/main`.
- Enumerate the in-scope campaign set: **Navreo campaigns only**. Gotcha: Byteplus, PushGroup, Olivia Duncan, WantMoreLeads, Arnic and DiscoLike campaigns sit in the main workspace with `client_id=navreo`; only the NAME reveals them. Default: keep what the cockpit already shows (incl. `#/arnic`, Bjion's named exemplar); when Training Mode is ON, confirm any inclusion/exclusion calls with Bjion before building.
- Map the current page: every row → its click behaviour (internal page vs Smartlead link vs dead), every tab per campaign page → wired or static-snapshot.
- Done-rule: repo clean on `main`, plus a written inventory (scope list, row-behaviour map, tab map) shared before any edit.

### Step 1 - Serve the data: app endpoints over the standing cache
- Add auth-gated endpoints in `server.py` (never add them to `_AUTH_PUBLIC_GET`; any new POST/PATCH reads `self._post_body`, never `rfile.read`). Suggested shape:
  - `GET /api/cockpit/campaigns` - the list: per-campaign stats, verdict, teaser (from `campaign_insights` live + unexpired rows plus synced Smartlead stats).
  - `GET /api/cockpit/campaign/{id}` - Overview payload: insights (status='live' AND `expires_at > now()`, minus the caller's `insight_dismissals`), stats, track-record entries.
  - `GET /api/cockpit/campaign/{id}/messaging` / `/sources` / `/leads` - per-tab payloads (Messaging from variant-statistics with since-relaunch labels; Sources from `list_pull_campaigns`; Leads from the synced tables).
- Respect the Supabase 8-second statement_timeout: keep every query sargable and single-pass. Paginate Smartlead pulls knowing a mid-page rate-limit error reads as end-of-list; stop only on an empty list.
- Done-rule: each endpoint returns correct JSON via **authed** curl/fetch on the live host, and the numbers back-solve against Smartlead/Supabase for 3 spot-checked campaigns plus the book scope.

### Step 2 - Rewire the page: live data, internal routing, working tabs
- Replace the cockpit's embedded static data with fetches to the Step 1 endpoints. Keep the certified look, the light/dark toggle, the performance graph, and the widget grammar (chart marks `#E8590C`; `#FF4D00` stays reserved).
- **Every** in-scope campaign row routes to an internal hash page with the four tabs; remove every row-level Smartlead auto-link. An explicit, labelled "Open in Smartlead" button on a detail page is fine; a row click never is.
- Keep hash routing with working back/forward and the full-row click-target HARD RULE. Add a "Data as of" stamp (browser-local time, timezone named).
- Do not touch `campaigns-classic.html`. Additive, never replace.
- Done-rule (LIVE, authed browser): clicking **10 randomly picked rows** (including ones that had no bespoke page before) opens internal pages whose four tabs all render non-empty, correct data; **zero** rows navigate to Smartlead; back/forward works.

### Step 3 - Repoint the Lilly Optimizer routine
- Edit `~/.claude/skills/lilly-optimiser/SKILL.md`: the Cockpit contract's deliverable becomes **`https://navreo-signals.onrender.com/app/campaigns.html#/`**. Run shape becomes: expiry sweep → fingerprint/cache check → analyse stale scopes → upsert `campaign_insights` → **verify the live page renders the fresh cache (authed)** → hand over one short line + the page link (`open` the page URL, skip when headless). Remove the artifact republish and artifact auto-launch entirely; keep every cache, fingerprint, freshness, supersede, cap and expiry rule unchanged. Keep the artifact URL only as a historical note.
- Stand up the daily morning crunch: a scheduled headless `/lilly-optimiser` run (proposed 07:00 CEST; when Training Mode is ON, confirm the exact time with Bjion). The run only writes the cache; the page picks it up by itself.
- Done-rule: the contract text names the campaigns page URL and contains no artifact-republish instruction, and the scheduled task exists with a confirmed next-run time.

### Step 4 - Fresh-crunch proof, end to end
- Run the updated `/lilly-optimiser` once for real: sweep expired rows, regenerate stale scopes, write today's cache rows.
- Done-rule (LIVE, authed browser): the live page shows today's regenerated insights (new timestamps/fingerprints visible via the endpoints), the "Data as of" stamp reads today, screenshots taken.

### Step 5 - The panel (the required verification)
- Convene **5 independent UX-expert subagents** with distinct personas. They score ONLY two criteria, /10 each, merged to one score per expert:
  1. **Navigation**: can they traverse the whole experience: every Navreo campaign reachable from the list, tabs switch, back/forward works, no dead ends, no surprise external links.
  2. **Factual correctness**: numbers on screen back-solve and match independently pulled Smartlead/Supabase values (each expert spot-checks different campaigns).
- Feed the panel LIVE rendered evidence (authed screenshots/DOM captures plus the independently pulled numbers), never source code alone.
- Fix round: address every finding, redeploy, re-verify Steps 1-4 done-rules still pass, re-panel. **Cap: 5 rounds.** On cap-hit, report the best score and the open findings.
- Done-rule: all five experts score **9/10 or higher** in the same round.

---

## ROLLBACK (one move each)

- Page/endpoints: `git revert` the ship commits in `~/navreo-signals`, push `main`. `campaigns-classic.html` is untouched throughout and remains the manual fallback.
- Routine: restore the previous `lilly-optimiser` contract from the skills repo's git history; the artifact still exists at its old URL.

## HOW TO RUN

1. Read the mode line above. If **ON** (default): do **Step 0 first**, then one step at a time, stopping for approval after each; skip any step whose done-rule already passes. If **OFF**: run Steps 0 to 5 in order without pausing.
2. Ship each change to `~/navreo-signals`, push `main`, wait out the Render redeploy, then verify the done-rule against the **live host**, authed. Retry up to the cap, then mark FAILED and continue.
3. Interruptions count as redeploys: re-confirm the live page after any interruption before calling a step done.

## OVERALL DONE-RULE

- Live `/app/campaigns.html#/`: every Navreo campaign navigable to an internal page, all four tabs live and correct, zero row-level Smartlead links, data refreshed by the morning Claude crunch through the Supabase cache with no artifact involved.
- `/lilly-optimiser` contract points at the page; the daily scheduled run exists.
- All five panel experts scored 9/10+ on navigation and factual correctness in one round.
- `campaigns-classic.html` untouched; auth model unchanged; no secrets or data committed.
- Final report: one line per step (0 to 5), each DONE / SKIPPED (already passed) / FAILED (with reason), plus the panel scores.
