---
name: tier1-live-restore
description: Static orchestration skill that restores the three missing UI features
  (campaign create/reconnect, Overview-tab insights, Sources-tab campaign-idea cards)
  to the live signals tool — by committing the never-pushed tier1-live-ship worktree
  edits in the deploy repo, reconciling the 17 setter commits it is behind, pushing
  (= Render deploy), and proving each feature live with a logged-in screenshot. One
  fixed step list, each step with a checkable done-rule, retry caps, and a Loop
  Training Mode toggle. Use when the user says "run the tier1 live restore", "ship
  the missing UI features", "the insights/sources cards aren't live", or
  "/tier1-live-restore".
---

> **SUPERSEDE NOTE (2026-08-02, platform-wide-stabilise):** app/campaigns-classic.html was REMOVED from the repo and live site (it 404s). Any step or done-rule below that expects it to serve/render is historical — skip or adapt it; the campaigns cockpit at app/campaigns.html is the only campaigns page.

# Tier-1 Live Restore

Three shipped-in-spirit features never reached the live site: they exist only as uncommitted
working-tree edits in the deploy repo, never committed, never pushed — so Render never built
them. This skill confirms that cause per-feature, reconciles the stale worktree with the 17
live setter commits it's behind, ships the ENTIRE uncommitted batch (user ruling, 2026-07-15),
and proves all three features render for a logged-in user. Static loop — fixed steps, each has
a done-rule, Training Mode controls the pauses.

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

**Destructive-action gate (both modes, non-negotiable):** the only outward action this
skill ever takes is **one `git push` to `origin/main` of the deploy repo** — and push =
live deploy. Never force-push, never rewrite published history, never drop or reorder any
of the 17 setter commits. In Training Mode ON, additionally show the full `git log` of
what will be pushed and get approval before the push fires. The iCloud copy of the app
(`…/Navreo/Claude/Navreo/app/` — sync-conflict names like "Mobile Bjion campaigns.html";
memory: iCloud REVERTS edits) is **never** edited, pulled from, committed, or pushed.

## Goal

1. Each of the three features has a one-sentence proven root cause with file evidence.
2. `origin/main` contains the full uncommitted batch AND all 17 setter commits — nothing rolled back.
3. Render rebuilt green; live host serves the feature markers and the new endpoints answer.
4. Logged in on `navreo-signals.onrender.com`: Overview insights block, Sources campaign-idea
   cards, and create/reconnect controls all render — one screenshot each.

> All four, verified live, or it isn't done. On a cap-hit, stop and report the gap honestly.

## Ground truth (verified 2026-07-15 — re-verify in Step 1, everything here drifts)

- **Deploy repo:** `/Users/bjionhenry/navreo-signals` → `github.com/bjionhenry94/navreo-signals`.
  Render service `navreo-signals` (`startCommand: python app/server.py`) auto-deploys
  `origin/main`. Live host: `navreo-signals.onrender.com`. Push = deploy.
- **Root cause (confirm per-feature):** all three features are UNCOMMITTED worktree edits —
  2,025 lines: `app/server.py` +1,325, `app/notifications.html` +355, `app/campaigns.html`
  +257, `app/unified.html` +192. Diff comment tag: `tier1-live-ship`. Key markers:
  `hydrateOverviewInsights` (Overview insights), `goToSourcesTab` (Sources cards),
  `/api/campaign-insights` (new backend). Create/reconnect = `campaigns-platform-mirror`
  base (deployed at `249d321`) + these uncommitted extensions.
- **Stale worktree:** local HEAD `4489825` is a **strict ancestor** of `origin/main`
  `0e0fea5`, 17 commits behind — all 17 are live setter commits (Jul 14–15). The setter
  commits almost certainly touch `server.py`, so a stash-pop conflict there is EXPECTED.
- **Untracked files in the worktree:** `app/recontact.py`, `app/migrations/`,
  `app/deliverability-proto.html`, `app/deliverability-tab-proto.js`, `.claude/`.
  **Default (user may veto):** ship any untracked file the shipped code imports/serves
  (Step 1 proves this with grep — e.g. `import recontact` in server.py); keep `.claude/`
  and `*-proto*` local.
- **Login wall:** campaigns/overview/sources pages are auth-gated; no mintable session
  cookie exists (memory: `setter-live-verify-auth`). **The user supplies a session cookie
  or test login before Step 6** — request it at Step 6, not earlier.
- **Second copy hazard:** this session's iCloud cwd holds a stale app copy. Deploy repo is
  the ONLY source of truth.
- **Unknowns Step 1 must resolve:** exact test-suite invocation (last known green: "669
  tests"); whether `migrations/` are auto-applied on boot or manual; current
  behind-count/tip hashes (more setter commits may have landed).

## Steps

### Step 1 — Re-verify ground truth and map the batch
In `/Users/bjionhenry/navreo-signals`: `git fetch`, re-read `git status -sb`, behind-count,
tip hashes, `git diff --stat HEAD`. Record the 17+ setter hashes to a list (the roll-back
guard checks THIS list later). Grep the worktree `server.py` for imports/serves of each
untracked file to fix the ship-set. Find the test suite invocation and run it once on the
current worktree for a baseline.
- **Done-rule:** (a) fresh behind-count + setter-hash list recorded; (b) per-feature marker
  grep shows `hydrateOverviewInsights`, `goToSourcesTab`, `/api/campaign-insights`, and the
  reconnect controls present in the worktree but absent/partial in `origin/main` (the three
  root-cause sentences, with file evidence); (c) ship-set decided with the grep evidence;
  (d) baseline test result recorded (pass OR pre-existing failures listed).

### Step 2 — Reconcile with origin/main
`git stash push -u` (include the ship-set untracked files), `git pull --ff-only`, `git stash
pop`, resolve conflicts — expected in `server.py`; resolution rule: **keep both** feature
sets (incoming setter code AND the tier1 additions), never discard either side. Re-run the
test suite after resolution.
- **Done-rule:** (a) `git status -sb` shows 0 behind; (b) every recorded setter hash still in
  `git log` (grep each — all present or the step FAILS); (c) tier1 markers still present in
  the reconciled worktree; (d) test suite ≥ baseline (no new failures). Max 3 resolution
  attempts; on cap-hit, restore the stash safely and report FAILED — never leave the stash
  dropped.

### Step 3 — Commit and push (THE GATE)
One commit of the ship-set with a message naming the three features and the root cause.
Training Mode ON: show `git log origin/main..HEAD` + `git show --stat` and wait for approval.
Then `git push origin main` — no force.
- **Done-rule:** push accepted; `git log origin/main` (after re-fetch) contains the new
  commit AND every recorded setter hash; local worktree clean apart from the deliberately
  unshipped files (`.claude/`, `*-proto*`).

### Step 4 — Deploy proof (read from the destination)
Wait for Render's new build to go live (poll the live host, not local state). Then fetch
`https://navreo-signals.onrender.com/app/campaigns.html` (or its served JS) and grep for
`hydrateOverviewInsights` and `goToSourcesTab`.
- **Done-rule:** (a) new Render build green / boot ledger shows the new boot; (b) both
  markers present in the live-served artifact; (c) a pre-push fetch of the same artifact
  LACKED the markers (proves the change landed, not a stale cache).

### Step 5 — Backend proof
Probe the new endpoints on the live host (e.g. `/api/campaign-insights`) unauthenticated.
- **Done-rule:** each new endpoint returns a non-404 (401/redirect-to-login counts as
  alive — auth-gated is expected; 404/500 fails the rule).

### Step 6 — Live UI proof (needs the user's login)
Ask the user for the session cookie / test login NOW. Log in on
`navreo-signals.onrender.com`, open a Smartlead campaign: Overview tab → insights block
(runs-dry nudge / positives-by-source / working-not-working card); Sources tab →
campaign-idea cards; campaigns home → create + reconnect controls. Screenshot each.
- **Done-rule:** three screenshots of the RENDERED logged-in pages, each showing its
  feature (rendered page is the only acceptable UI done-evidence — a grep of deployed JS
  is a deploy check, not a done check), and zero feature-related console errors on those
  tabs. If the user can't supply a login, this step is FAILED-BLOCKED, not skipped-as-done.

### Step 7 — No-false-pass sweep
Confirm nothing was committed/pushed from the iCloud copy (`git log --stat` of the pushed
commit shows only deploy-repo paths), the deploy-repo worktree is clean, and the stash is
empty (nothing marooned).
- **Done-rule:** all three checks pass, stated with the commands run.

## Final report (always, both modes)

One summary: per-step pass/skip/FAILED; the three root-cause sentences; commit hash pushed;
setter-hash roll-back check result (N/N present); Render build id; the three screenshot
paths; ship-set vs left-local file lists; any FAILED step with its gap. Never report done
while any done-rule fails.

## Hard don'ts

- Never touch the iCloud app copy — not to read-as-source, edit, commit, or push.
- Never force-push, rewrite history, or drop/reorder a setter commit; the hash-list check is
  the law.
- Never push without the Training-Mode approval pause (while ON).
- Never resolve a `server.py` conflict by discarding either the setter side or the tier1 side.
- Never declare a feature live off a grep of deployed JS — Step 6's rendered screenshots are
  the only UI done-evidence.
- Never ship `.claude/` or `*-proto*` files unless the user explicitly overrides the default.
- Never exceed a retry cap or report done while any done-rule fails; cap-hits are FAILED
  with the gap.
