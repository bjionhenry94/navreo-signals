---
name: tier1-live-ship
description: Static orchestration skill that implements the ACCEPTED tier-1 UX ideas into Navreo's
  LIVE signals tool without restructuring it — Overview becomes the campaign-insights surface
  (runs-dry nudge, positives-by-source, working/not-working/recommendations, dropdown gone), Sources
  gets an on-demand hiring-only "Suggest campaign ideas" button (monthly DM TAM, Dismiss/Generate-more,
  single Add dropdown that pulls DMs through the upload gate), the optimiser Why-dropdown gets the full
  replacement email + Approve (paste-ready, never API-saved), and recontact ships as a skill + served
  sibling-scan review page drafting a de-duplicated recontact. Built in the DEPLOY repo (~/navreo-signals),
  proven on a staging mirror, deployed only after Bjion signs off. One fixed step list, checkable
  done-rules, retry caps, Loop Training Mode toggle. Use when the user says "run the tier-1 live ship",
  "build the accepted ideas into the tool", "ship the tier-1 redesign", or "/tier1-live-ship".
---

# Tier-1 Live Ship

Ships the ideas Bjion accepted from the tier-1 UX lab (memory `tier1-uxlab-v2-rulings` + fired brief
2026-07-14) INTO the existing live tool. **No restructure**: every current page, tab, and nav item stays
exactly as-is (the three-tab redesign is explicitly rejected); the ideas are added into the named
surfaces. Static loop — fixed steps, done-rules, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before continuing. Before
starting a step, check its done-rule first — if it already passes, report "Step N already passes,
skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before
doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and
retry caps stay exactly the same — only the pauses go. **Exception: Step 9 (sign-off) pauses in BOTH
modes — it is the deploy gate and can never be skipped.**

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. On cap-hit: record
the step FAILED with the reason, continue if later steps don't depend on it, surface every FAILED step
in the final report. Never declare done on a cap-hit.

## 🔒 Hard gates (both modes, non-negotiable)

- **Repo gate:** all edits in the DEPLOY repo `~/navreo-signals` — NEVER the iCloud working-dir copy
  (memory `signals-deploy-repo`: iCloud REVERTS edits). The pushed server.py + Supabase are truth.
- **No-send gate:** no action in this loop may activate a campaign or send anything. Adds land as
  DRAFT / behind the QA-upload gate only. Verify at the destination that status stays draft/paused.
- **Smartlead sequence gate:** NEVER call any sequence-save API on an existing campaign — it resets
  variant IDs and wipes A/B history (memory `reference_smartlead_api_realities`). Approve = paste-ready
  copy only. Sub-sequence REBUILD from the God-template is allowed ONLY on a freshly created draft
  duplicate, never on the source campaign.
- **Suggestion gate:** suggested campaign ideas are HIRING-SIGNAL ONLY. Never suggest engagement
  campaigns (engagement may be offered as an addable source, never as an idea). No company counts,
  no novelty scores — monthly decision-maker TAM is the headline figure.
- **Credit budget:** idea generation = probe depth only (counts, not pulls), **≤50 provider credits per
  Suggest/Generate-more click, ≤150 per verification run**. Test "Add" = **≤25 DMs enriched**, on a TEST
  campaign only. Recontact drafting spends **0 credits** (existing Supabase data only). Ocean stays dead;
  `lilly-tam` is the sole mapping/list/DM skill. At 80% of budget: pause and report (ON) / stop and
  report (OFF).
- **Deploy gate:** deploy to navreo-signals.onrender.com ONLY after Step 9 sign-off. Live keys exist in
  `~/.navreo-keys.env` — staging runs against real READ-ONLY data; writes only to test campaign/draft rows.

## Goal

1. Overview (existing tab) = the campaign-insights surface: runs-dry top-up nudge, "Where your positives
   come from" per-source table, plain-English insights block (summary / working / not working /
   recommended changes / recommended optimisations — the lilly-optimiser analysis surfaced here), campaign
   dropdown removed, liked "send remaining" control untouched.
2. Sources (existing tab) = on-demand "Suggest campaign ideas" button → hiring-only cards with monthly DM
   TAM + Dismiss (persists) + "Generate more", each with ONE Add dropdown ("Add to campaign" / "Add to new
   campaign" draft-duplicate with God-template sub-sequence rebuild); Add immediately pulls DMs via
   lilly-tam and lands them behind the QA gate.
3. Optimiser Why-dropdown (notifications.html) = full replacement email (changed problem statement
   highlighted, icebreaker/offer/CTA intact) + Approve → paste-ready copy, no API save.
4. Recontact = Claude skill + served review page (qa-gate pattern): sibling auto-scan (lead-overlap OR
   similar name), five-bucket view, creates a DRAFT excluding in-progress + active-elsewhere.
5. List review confirmed: a lilly-tam-built list lands reviewably at its existing lists.html#<id> URL.
6. All proven on staging, signed off, re-proven live. Nothing else in the tool changed.

## Ground truth (from the 2026-07-13/14 lab audit — re-verify in Step 1 IN THE DEPLOY REPO; the audit
read the iCloud copy, so every line number below WILL drift)

- Deploy repo `~/navreo-signals/app/`: server.py, campaigns.html, lists.html, notifications.html,
  shell.js. Launch.json already has staging mirrors on it: `signals-mock` (:7913, DELIV_MOCK=1),
  `signals-nobackend` (:7914), `setter-dryrun` (:7957) — reuse one, never invent a new scheme.
- campaigns.html live path: `renderDraftCampaign(id)`, tabs `["overview","leads","sources"]` (iCloud
  ~L622; overview body ~L694-791). A dead `renderDetail` path exists (incl. tabCopy variant stats
  ~L2842-2873) — do not resurrect it.
- **Per-source outcome attribution: UNRESOLVED.** The lab audit of the iCloud copy found NO join from
  Smartlead/HeyReach outcomes back to source_id (velocityChart = found-counts only). The brief says it
  is reportedly tracked in the pushed repo. Step 1 MUST search `~/navreo-signals` server.py + Supabase
  (signal_leads.source_id, contact_history, replies, sent_messages, lead_variant_assignments) for real
  attribution. If genuinely absent: ship the UI on the best proxy (leads-by-source via
  signal_leads.source_id × campaign-level outcomes), label it as a proxy ON THE PAGE, flag true
  attribution as follow-up. Never silently present proxy numbers as attribution.
- notifications.html: lilly-optimiser Priority Report, `.ab-why` expander with the Section-7 variant
  table (iCloud ~L220-266) — the Why dropdown to extend.
- Remote-review precedent: `/qa-gate/<id>` pages served by app/server.py (lilly-upload-gate) — the
  pattern for the recontact review page.
- Supabase (fnykldftbkrccihdjayl): contact_history 1.1M rows, suppressions 73k, campaigns 778,
  replies 18.4k, sent_messages 24k, signal_leads.source_id, campaign_drafts. Sibling scan is fully
  computable from contact_history overlap + campaign-name similarity.
- Smartlead gotchas: API 200-with-ok:false happens (check bodies, not status); rate limit 200/min;
  sub-sequences never survive duplication (rebuild from God-template via API on new drafts only).
- Prototype references (visual + copy source): `tier1-uxlab-proto/` campaign.html (Overview/Sources v2),
  optimiser.html (Why framing, email preview, Approve), recontact.html (buckets); rulings in memory
  `tier1-uxlab-v2-rulings`. Adapt the design INTO the existing pages — do not port the 3-item rail.
- Unknowns for Step 1: which staging mirror config runs cleanly today; the God-template campaign id;
  a safe TEST campaign id for Add verification (ask Bjion at sign-off checkpoints if none exists);
  whether an idea-generation endpoint pattern (async job via app_jobs/NavreoJobs) fits Suggest-ideas.

## Steps

### Step 1 — Ground-truth in the deploy repo + baseline
Clone/pull `~/navreo-signals` fresh. Locate every surface named above with CURRENT line refs. Run the
staging mirror; load every existing page in a real browser and screenshot each (the regression baseline).
Resolve: per-source attribution (real vs proxy — this decides Step 2), God-template id, test campaign id.
- **Done-rule:** a written fact-sheet with (a) current file:line for overview/sources render fns, ab-why,
  qa-gate route; (b) attribution verdict REAL (query shown returning rows) or PROXY (search terms shown
  coming back empty); (c) staging mirror serving every page with zero console errors; (d) baseline
  screenshots saved for every existing page/tab.

### Step 2 — Backend: per-source outcomes + insights + ideas + recontact endpoints (server.py)
Add read endpoints: per-source outcome table (real or labelled proxy), insights block (surface the
lilly-optimiser-style analysis: summary/working/not-working/changes/optimisations), on-demand idea
generation (async job, hiring-only, monthly DM TAM via probe counts — NEVER fired on page load),
recontact sibling-scan + buckets + draft-create, Add-flow orchestration (DM pull → upload gate; draft
duplicate + God-template sub-sequence rebuild). All writes = drafts/gate only.
- **Done-rule:** each endpoint proven by curl on staging: positives-by-source numbers match an
  independent Supabase query; idea endpoint returns 0 calls until invoked and hiring-only cards with a
  DM/mo figure when invoked; recontact buckets sum to source totals and reconcile against
  contact_history/suppressions; Add-flow dry-run creates a draft with sub-sequences present and
  status ≠ active.

### Step 3 — Overview UI (campaigns.html, existing overview tab)
Nudge + positives-by-source table (+ proxy label if proxy) + insights block, dropdown removed, "send
remaining" untouched, everything else on the page unchanged.
- **Done-rule:** on staging in a real browser: all three blocks render on a real campaign, dropdown
  absent, page numbers MATCH the Step-2 independent query, zero console errors, leads+sources tabs
  unchanged vs baseline screenshots.

### Step 4 — Sources UI (campaigns.html, existing sources tab)
"Suggest campaign ideas" button → cards (hiring-only, ~N decision-makers/mo, no company count, no
novelty) + Dismiss (persists server-side) + "Generate more" + ONE Add button with dropdown (exactly
"Add to campaign" / "Add to new campaign"). Add triggers the Step-2 flow with progress via the existing
jobs sidebar.
- **Done-rule:** network log shows ZERO idea/provider calls on page load; click → only hiring cards;
  Dismiss survives reload; dropdown has exactly the two actions; on the TEST campaign, Add lands ≤25
  gated DMs at the destination with nothing sent, and Add-to-new-campaign yields a real Smartlead DRAFT
  with sub-sequences rebuilt and not activated.

### Step 5 — Optimiser Why (notifications.html)
Inside the existing .ab-why expander: full replacement email (changed problem statement highlighted,
icebreaker/offer/CTA visibly unchanged) + Approve → paste-ready copy + the manual-paste warning.
- **Done-rule:** on a real Priority-Report notification: expander shows the full email with highlight;
  Approve produces the paste-ready block; network log shows NO sequence-save call; rest of
  notifications.html unchanged vs baseline.

### Step 6 — Recontact skill + review page
Write the `lilly-recontact` skill (chat entry: "Build a recontact campaign from [campaign]") + the
served review page (qa-gate pattern): sibling auto-scan, buckets, include-repliers toggle, create-draft.
- **Done-rule:** on real campaign ids: sibling list matches an independent overlap/name query; buckets
  reconcile to contact_history/suppressions; created draft contains ONLY eligible people (spot-check 20
  against exclusion queries); draft sends nothing.

### Step 7 — List-upload verify (no build)
Build a small test list via lilly-tam (≤25 rows, inside budget) or reuse today's freshest pull.
- **Done-rule:** the list opens reviewably at its real `lists.html#<id>` URL in a browser.

### Step 8 — Staging regression + full verification sweep
Re-run the whole Verification stack (items 1-6 of the brief) on staging in one pass, against baseline.
- **Done-rule:** every existing page/tab/nav renders as baseline with zero console errors; all six
  verification items pass with evidence (screenshots + independent read-backs + network logs) collected
  into a sign-off pack.

### Step 9 — SIGN-OFF (pauses in both modes)
Present the sign-off pack to Bjion: staging URL, screenshots, numbers, any PROXY/FAILED flags.
- **Done-rule:** Bjion explicitly approves deploy. No approval = loop ends here, reported honestly.

### Step 10 — Deploy + live re-proof
Push the deploy repo; wait for Render; marker-grep the deployed artifact; re-run the browser sweep on
navreo-signals.onrender.com (live proof, smallest blast radius: read-only checks + the test campaign
only); reconcile deploy-repo↔iCloud copies per memory.
- **Done-rule:** live pages render the new surfaces with zero console errors; deployed artifact contains
  the marker; live positives numbers match Supabase; repos reconciled; final report issued.

## Final report (always, both modes)
Steps passed/skipped/FAILED; attribution verdict (REAL or PROXY, with the query/search evidence); credits
spent vs the ≤150 budget; test-campaign artifacts (draft ids, gated-lead counts, nothing-sent proof);
screenshots list; deploy commit + marker; anything deferred (e.g. true attribution follow-up).

## Hard don'ts
- Never edit the iCloud copy; never restructure pages/tabs/nav; never resurrect the dead renderDetail path.
- Never generate ideas on page load, precompute them, or suggest an engagement campaign.
- Never API-save sequences on an existing campaign; never activate or send from any action in this loop.
- Never present proxy attribution as real; the label ships on the page.
- Never exceed the credit caps, the retry caps, or skip Step 9; never report done while any done-rule fails.
