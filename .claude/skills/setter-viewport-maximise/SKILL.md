---
name: setter-viewport-maximise
description: Static orchestration skill that makes the Navreo signals app use the full
  screen — removes the app-wide 1280px width cap in navreo.css and rebuilds the Setter
  tab's middle pane so the threaded conversation fills all vertical space (no 46vh cap),
  opens scrolled to the newest reply, and keeps the composer visible without page scroll.
  Ships to the live Render app and proves it in the rendered browser at multiple
  breakpoints. One fixed step list, each step with a checkable done-rule, retry caps, and
  a Loop Training Mode toggle. Use when the user says "run the viewport maximise", "fix
  the setter whitespace", "make the app full-width", or "/setter-viewport-maximise".
---

# Setter Viewport Maximise

The Setter tab wastes the screen: the whole app is capped at 1280px wide, and the
conversation box is capped at 46vh, so on a real monitor the middle pane floats in white
space and the thread uses half its column. This loop removes the app-wide width cap
(user, 2026-07-12: "the whole app should be responsive. It shouldn't be like a 1280 cap
anyway"), makes the Setter conversation fill the vertical space between header and
composer, and proves — in a rendered browser, live — that the thread opens at the newest
reply with the suggested reply visible. Static loop: fixed steps, each with a done-rule,
Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
**Whole-loop round cap: max 3 fix→deploy→verify rounds.** On cap-hit: record the step as
FAILED with the reason, continue to the next step if it doesn't depend on the failed one,
and surface every FAILED step in the final report. Never silently exceed the cap. Never
declare the skill done on a cap-hit.

**Ship gate (both modes, non-negotiable):** the only writes to live are git pushes to
`~/navreo-signals` `main` touching **only `app/navreo.css` and `app/setter.html`**
(user, 2026-07-12: push autonomously approved — CSS-only, easy revert). Stage files
explicitly by name, never `git add -A`; confirm `git diff --cached --stat` lists only
those two files and no secrets/data (`.gitignore` protects `*.env`, `app/data/*.json`).
Any other file needing a change = stop and report, don't ship it.

## Goal

When done, all of this is user-visibly true on the live app:

1. No tab is width-capped: `.main`'s `max-width: 1280px` is gone and content breathes to
   the window with sane padding.
2. On the Setter tab at a 1440px-wide window: the inbox shell spans **≥95% of viewport
   width**; the conversation column fills **all vertical space** between the pane header
   and the "Your reply" composer (no 46vh cap); the composer is visible **without page
   scroll**; the thread opens **scrolled to the newest reply** with the fade hint
   appearing only when older content is above (user, 2026-07-12: done bar = "Fill width
   + height").
3. Every other tab (index, campaigns, lists, deliverability, notifications, setter-grade)
   renders without horizontal scroll, layout breakage, or new console errors at 1440px
   and at the 1200px / 900px breakpoints.

## Ground truth (verified 2026-07-12 — re-verify in Step 1, line numbers drift)

- **Source of truth is `~/navreo-signals`** (git, `github.com/bjionhenry94/navreo-signals`,
  branch `main`, Render auto-deploys on push). The iCloud copy under
  `…/Navreo/Claude/Navreo/app/` is DEPRECATED — never edit it (memory
  `reference_signals_deploy_repo`). Repo was in sync with origin/main on 2026-07-12.
- **Width cap:** `app/navreo.css:109` —
  `.main { flex: 1; min-width: 0; padding: 28px 38px 80px; max-width: 1280px; }`.
  Shared by every tab.
- **Setter shell:** `app/setter.html:39-42` — `.inbox-shell` height
  `calc(100vh - 220px)`, `min-height: 460px`. Left list 340px, right pane
  `.inbox-right { flex: 1; overflow-y: auto; padding: 22px 26px 40px }` (line 56), lead
  sidebar 280px (line 61).
- **Conversation cap:** `app/setter.html:129` — `.convo { max-height: 46vh; overflow-y:
  auto; … }`. A SEPARATE `max-height: 46vh` on `.lead-panel` inside the ≤1200px media
  query (line 90) is the tablet lead-panel rule — leave it alone.
- **Scroll-to-bottom already shipped:** `app/setter.html:988-999` sets
  `convoEl.scrollTop = convoEl.scrollHeight` on render and toggles `.convo-fade` opacity
  when `scrollTop > 8`. Commit `df87103`. Keep this behaviour; the loop only changes the
  sizing around it.
- **Breakpoints:** ≤1200px wraps the lead panel below; ≤900px stacks list/detail with a
  mobile back button (`app/setter.html:87-101`).
- **Live verify needs auth:** anonymous curl of
  `https://navreo-signals.onrender.com/app/setter.html` returns **302 → login** (proven
  2026-07-12). The only self-serve verify path is the user's logged-in real Chrome via
  **claude-in-chrome** (`list_connected_browsers` → `navigate` → screenshot /
  `javascript_tool`). Entering the login password is prohibited. Test rows exist behind
  the "Show test items" toggle on the Setter tab — use those for a selected-lead view.
- **Unknown (resolve in Step 1):** whether `python app/server.py` renders locally without
  the Supabase login gate — if yes, use local preview for fast iteration before pushing;
  if no, iterate against code + deploy and verify live only.

## Steps

### Step 1 — Re-verify ground truth
In `~/navreo-signals`: `git fetch` + `git merge --ff-only origin/main`, then
`git rev-list --left-right --count HEAD...origin/main` must show `0 0`. Confirm every
Ground-truth bullet (grep the exact selectors and the `scrollTop` line; line numbers may
drift — record the fresh ones). Resolve the local-preview unknown. Confirm
claude-in-chrome is connected and the user's Chrome session reaches
`https://navreo-signals.onrender.com/app/setter.html` without a login wall. Capture the
**BEFORE evidence** at a 1440px-wide window: screenshot of the Setter tab with a test
lead selected, plus `javascript_tool` measurements of `.inbox-shell` width /
`window.innerWidth`, `.convo` rendered height, and whether the composer is in the
viewport.
- **Done-rule:** (a) repo fast-forwarded, counts `0 0`; (b) every selector found with
  fresh line numbers; (c) local-preview question answered yes/no with evidence; (d)
  BEFORE screenshot + the three measured numbers captured.

### Step 2 — Remove the app-wide width cap
In `app/navreo.css`, drop `max-width: 1280px` from `.main` (keep `flex: 1; min-width: 0`
and comfortable padding — widen the horizontal padding slightly if content slams the
window edge, e.g. `clamp(24px, 3vw, 48px)`; that judgment is baked here, no mid-run
question). Touch nothing else in the file.
- **Done-rule:** `grep -n "max-width: 1280px" app/navreo.css` returns nothing, and
  `git diff app/navreo.css` shows ONLY the `.main` hunk.

### Step 3 — Make the Setter middle pane fill the screen
In `app/setter.html`: restructure `.inbox-right` as a flex column
(`display: flex; flex-direction: column`) whose children are the fixed-height header
block, the conversation, and the composer. Give `.convo` `flex: 1 1 auto; min-height: 0`
and **remove its `max-height: 46vh`** so it absorbs all free vertical space; the
composer sits below it, always visible. Keep `overflow-y: auto` on `.convo`, keep the
scroll-to-bottom + fade logic untouched, keep `.inbox-shell`'s viewport-height sizing
(adjust the `- 220px` offset only if Step 6 measures dead space above/below the shell).
Do NOT touch the ≤1200px `.lead-panel` 46vh rule or the ≤900px stacking rules except as
needed to keep them rendering (at ≤900px a `max-height` fallback on `.convo` is
acceptable since the shell goes `height: auto` there — bake that fallback in).
- **Done-rule:** (a) `grep -n "max-height: 46vh" app/setter.html` matches ONLY the
  `.lead-panel` media-query line; (b) the `scrollTop = convoEl.scrollHeight` line and
  `.convo-fade` logic are still present verbatim; (c) `git diff app/setter.html` contains
  only CSS/structure hunks — no behaviour (JS data-flow) changes.

### Step 4 — Local render sanity (only if Step 1 proved local preview works)
Serve locally, load setter.html at 1440px in the Browser pane, select a test row, and
check the Goal-2 geometry before spending a deploy cycle. If local preview is gated,
skip and record "skipped — no local preview".
- **Done-rule:** local page meets Goal 2's four geometry checks, or the step is recorded
  as skipped-with-reason.

### Step 5 — Deploy
Stage `app/navreo.css` and `app/setter.html` by name, commit, push to `main`. Wait for
Render to go live (poll until the deploy settles; anonymous 302 is normal). Per the ship
gate: `git diff --cached --stat` must list only those two files.
- **Done-rule:** the commit is on `origin/main` (`git log origin/main -1` shows it), and
  the live app serves the new build — proven in Step 6's rendered page, not by grep alone.

### Step 6 — Live proof in the rendered browser (the only done-evidence)
Via claude-in-chrome on the live app, with a test lead selected on the Setter tab:
1. **1440px:** screenshot + `javascript_tool` measurements proving all four Goal-2
   checks: shell width ≥95% of `window.innerWidth`; `.convo` height fills the pane (no
   46vh ceiling — measured height > 0.6 × pane height on a tall window); composer
   `getBoundingClientRect()` fully inside the viewport with no page scroll; and
   `convoEl.scrollTop + convoEl.clientHeight === convoEl.scrollHeight` on open (newest
   reply visible), fade hidden at bottom and appearing after scrolling up.
2. **Breakpoint sweep:** resize to ~1920px, 1200px, and 900px — screenshot each; no
   horizontal scrollbar (`document.documentElement.scrollWidth <=
   window.innerWidth`), layout intact.
3. **Other tabs:** index, campaigns, lists, deliverability, notifications, setter-grade
   at 1440px — screenshot each, no horizontal scroll, and `read_console_messages
   onlyErrors` shows **zero new errors** on every page loaded.
4. **Reload mid-state:** reload setter.html with a lead selected — the convo still opens
   scrolled to the newest reply.
Any failed check → fix in the repo and re-enter at Step 5 (counts against the 3-round
cap).
- **Done-rule:** all four sub-checks pass with screenshots + measured numbers recorded;
  zero console errors attributable to this change across all pages swept.

## Final report (always, both modes)

One summary listing: steps passed/skipped/FAILED with reasons; the BEFORE vs AFTER
numbers (shell width % of viewport, convo rendered height in px, composer-visible
yes/no, scroll-at-bottom yes/no); the commit sha shipped; the list of tabs and widths
swept with per-page console-error counts; file paths of every screenshot; and anything
deferred. On the round cap: report FAILED with the exact gap — never "done".

## Hard don'ts

- Never edit the iCloud copy (`…/Navreo/Claude/Navreo/app/…`) — deprecated; repo only.
- Never call it done from a grep of deployed files or the app's own success state — the
  rendered browser page with measured geometry is the only done-evidence (memory
  `feedback_browser_verify_before_done`).
- Never enter the app's login credentials anywhere — live verification goes through the
  user's already-authenticated Chrome only.
- Never `git add -A`; never commit files other than `app/navreo.css` and
  `app/setter.html`; never push with secrets or `app/data/*` staged.
- Never remove or alter the scroll-to-bottom / fade-hint behaviour (setter.html
  ~988-999) — this loop resizes around it.
- Never touch the ≤1200px `.lead-panel` 46vh rule or setter behaviour JS (data flow,
  approve/regenerate/dismiss) — sizing and layout only.
- Never exceed a retry cap or the 3-round cap, and never report done while any done-rule
  fails.
