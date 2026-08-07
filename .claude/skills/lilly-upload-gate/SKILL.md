---
name: lilly-upload-gate
description: FORCED pre-upload QA gate for Smartlead list uploads. Every list push to a Smartlead campaign MUST run through this skill first — it runs email verification (ListMint for never-verified emails, MillionVerifier re-checks, AI-Ark/cache skips), variable-fill (FAIL <95%), variable normalisation, recontact/overlap sweep against Supabase contact_history + suppressions, a cross-campaign collision check (30-day window incl. live Smartlead lookup; follow-up campaigns count; Navreo↔Arnic overlap allowed), and a minimum-field schema check; surfaces the gate verdict IN THE CHAT (per-check PASS/FAIL summary + approve/override moment in the chat flow — the review page on the signals tool is the deep view, never a detour the user must hunt for; Bjion ruling 2026-07-26); blocks the upload while any un-overridden FAIL exists; and writes a Supabase audit record of every run (checks, results, overrides). After a successful upload the closing message ALWAYS links the campaign's Leads page and notes the upload record, with a partial-pool explanation when only part of the pool went up. Use whenever the user wants to upload/import/push a lead list or CSV into a Smartlead campaign, says "run the upload gate", "QA this list before upload", "gate this list", or "/lilly-upload-gate". ALSO the route for campaign TOP-UPS (consolidated launch flow, Bjion 2026-07-26): "this campaign is running dry", "top it up with fresh leads", "add more leads to [campaign]" — source the fresh rows first (the campaign's saved pool via Sources' pull-more when one exists, else lilly-tam with the campaign's targeting), then this gate runs IN THE CHAT and the closing message links the Leads page with the partial-pool explanation. Also the mandatory hand-off target BEFORE any add_leads_to_campaign call from any other workflow.
---

# Lilly Upload Gate — forced QA before any Smartlead list upload

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step only if
it doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

## ⚙ Check config — edit this block to add/remove checks or required fields

```yaml
CHECKS:                      # set false to disable a check; add new keys + a Step to add one
  schema: true               # Step 2 — minimum required fields per row
  normalisation: true        # Step 3 — clean names/companies
  variable_fill: true        # Step 4 — every {{variable}} in copy filled per lead
  spintax: true              # Step 4c — live sequence copy must carry spintax (every campaign)
  recontact: true            # Step 5 — contact_history + suppressions + positive-replier sweep (client-specific)
  email_verification: true   # Step 6 — MV deliverability (paid — runs last)
  list_audit: true           # Step 6b — composition score (sample ≤50), top-right badge; informational, never blocks

LIST_AUDIT_SAMPLE: 50        # rows sampled for the composition score

CHECKLIST: []                # optional manual confirmations in the sticky bar; if any
                             # are listed the gate holds at CONFIRM CHECKLIST until all
                             # are ticked (recorded with name). Empty by default.

REQUIRED_FIELDS:             # schema check: every row must have all of these
  - first_name
  - last_name
  - job_title
  - company_name
  - company_website
  - company_size
  - company_location
  - personal_location
  - data_source

VARIABLE_FILL_FAIL_BELOW: 95   # % — lilly-qa 5b rule: FAIL under this, WARN 95–99.9
SPINTAX_MIN_GROUPS_PER_BODY: 3 # Step 4c — each email body must carry ≥ this many spintax groups
MV_TTL_DAYS: 90                # skip MV if people.email_verified_at within this window
RETRY_CAP: 3

CROSS_CAMPAIGN_WINDOW_DAYS: 30   # Step 5.4 — sends/enrollments in another campaign within
                                 # this window count as a collision
CROSS_CLIENT_ALLOWED_PAIRS:      # collision pairs the user has ruled fine — no flag,
  - [navreo, arnic]              # dossier-noted only (Bjion, 2026-07-12)
```

## Goal

**A rep cannot push a list into Smartlead without this gate having run every enabled
check and either passed it or recorded an explicit user override for each flag.**
The run produces a per-check PASS / FAIL / OVERRIDDEN report (opened as a page in the
browser), blocks the upload while any un-overridden FAIL exists, and writes an audit
row so every upload is documented — including which campaigns each prospect was already
used in.

## Ground truth (verified 2026-07-10 — re-verify in Step 1)

- Keys auto-load from `~/.navreo-keys.env` (`MILLIONVERIFIER_API_KEY`, `SMARTLEAD_API_KEY`, Supabase).
- Supabase project `fnykldftbkrccihdjayl`; data helper `navreo_db.py` (see memory
  `project_supabase_data_layer`). `contact_history` ≈ 1.1M rows, email column is
  **citext** — match on plain equality, no lower(). Join `campaigns` on
  `smartlead_campaign_id` for campaign name + client. `suppressions` is a separate table
  — always sweep it too. `people.email_verified_at` + `email_verification` hold the
  verification cache; AI-Ark-sourced emails are pre-verified at source (BounceBan).
- MillionVerifier: `GET https://api.millionverifier.com/api/v3?api=$KEY&email=…`;
  1 credit per call flat; keep `ok`/`catch_all`, drop the rest; branch on the body's
  `error` field, not HTTP status.
- ListMint (proven live 2026-07-09, see `signals-verify-jobs-ship`): base
  `https://api.listmint.io/api/`; auth = `?api-key=` QUERY param (header form rejected);
  `POST /verify-emails?return=true` body `{"emails":[...]}` →
  `results[{email, result}]` with `valid | invalid | catch_all_valid |
  catch_all_invalid`; batches parallelise server-side. `LISTMINT_API_KEY` in
  `~/.navreo-keys.env`.
- Every real verifier call logs to the `provider_usage` ledger via
  `navreo_db.log_provider_usage("<listmint|millionverifier>", 1, endpoint=…,
  source_id="lilly-upload-gate")`.
- Smartlead `add_leads_to_campaign`: ONLY `email`, `first_name`, `last_name`,
  `phone_number` are top-level; everything else goes in `custom_fields` (key is
  `company_name`, NOT `company`). Always send **1 test lead first**, verify it landed,
  then batch. 200 req/min cap.
- Normalisation rules live in lilly-qa `references/lead-field-hygiene.md`; the
  acronym rule is memory `feedback_company_name_keep_acronyms_caps` (NASA/CPB stay caps).

## Steps

### Step 1 — Intake + config echo
Identify the input list (CSV path, pasted rows, or a Smartlead-bound export) and the
target campaign (id + name). Pull the campaign's live sequence copy and extract every
`{{variable}}` used across all steps/variants. Echo back: row count, target campaign,
the variable list, and the config block above (enabled checks + required fields), and
confirm scope with the user before anything runs (inclusions/exclusions are literal).
- **Done-rule:** you can state (a) the row count, (b) campaign id + name, (c) the exact
  set of `{{variables}}` in the live copy, (d) which checks are enabled, and the user
  has confirmed the scope.

### Step 2 — Schema check (min required fields)
For every row, verify every field in `REQUIRED_FIELDS` is present and non-junk (empty,
`N/A`, `-`, `Unknown` count as missing). Missing fields are **FLAGGED per row per
field** — never silently dropped, never silently passed. The user can explicitly
override ("proceed without company_size on these 12 rows"), and that override is
recorded verbatim in the audit record.
- **Done-rule:** a per-field fill table exists (field → filled / missing / % ) plus a
  named list of failing rows; check status is PASS (0 missing) or FAIL with the flag
  list ready for Step 7 override resolution.

### Step 3 — Normalisation check
Apply lilly-qa Step 5d hygiene rules to the list itself (pre-upload, so fixes are cheap):
- `first_name` proper-cased (`JOHN` → `John`), single token, no trailing whitespace.
- `company_name` cleaned: legal suffixes stripped (`Inc.`, `Ltd`, `GmbH`…), profession
  tails and auto-hyperlinking TLDs flagged, shouting fixed — **but ALL-CAPS acronyms
  (NASA, CPB, IBM) stay caps**. When in doubt whether a name is an acronym, flag it,
  don't guess.
- All values: trim whitespace, no em-dashes, no `{{` fragments inside values.
Propose the corrected values as a diff table; apply to the working copy of the list
only after user approval (Training Mode ON) or automatically (OFF), logging every
change made.
- **Done-rule:** zero remaining hygiene violations in the working list, or every
  remaining violation is on the flag list with a proposed fix; a change-log of
  applied normalisations exists.

### Step 4 — Variable-fill check
For every `{{variable}}` found in Step 1, verify every row has a non-empty value for
it (default fields covered by Step 2/3; this covers the custom ones — Icebreaker, Why,
CaseStudy, etc.). Also flag case-mismatched keys (`icebreaker` vs `Icebreaker`) —
Smartlead's lookup is case-sensitive, so those render blank.
- Thresholds (lilly-qa 5b): PASS ≥99.9% · WARN 95–99.9% · **FAIL <95%** per variable.
  WARNs are surfaced but don't block; FAILs block.
- **Done-rule:** per-variable fill % table exists; every variable is PASS, or is on
  the flag list with the exact rows that are empty/mismatched.

### Step 4c — Spintax check (live sequence copy — runs on EVERY campaign)
Cold copy without spintax is a deliverability risk: identical bodies across a batch
get pattern-matched into spam. This check reads the TARGET campaign's live sequence
(the same copy pulled in Step 1) and verifies every sending body actually rotates —
it is a property of the CAMPAIGN COPY, not the lead rows, so it runs once per upload
regardless of list contents.
- For every non-deleted variant of every step (subjects AND bodies), count spintax
  groups: a `{a|b|…}` alternation with at least one `|` and no nested `{}`. A
  variable like `{{first_name}}` is NOT a spintax group.
- **FAIL** any body with fewer than `SPINTAX_MIN_GROUPS_PER_BODY` groups; **WARN** a
  subject line with no spintax (subjects are shorter, so warn not block). Report a
  per-step/per-variant table (label → subject-spintax? → body group count → verdict).
- Watch the brace-collision trap: a spintax option ending in a merge variable
  produces `…{{first_name}}}` and Smartlead's parser rejects the whole save — flag any
  option whose last non-space chars are `}}` immediately followed by the spintax `}`
  (fix: end the option with punctuation/text before the closing brace).
- This is a copy fix, not a lead fix: resolve by editing the sequence in Smartlead
  (re-save) and re-reading it, or by an explicit per-flag override recorded in the
  audit. It never drops leads.
- **Done-rule:** every sending body has ≥ `SPINTAX_MIN_GROUPS_PER_BODY` spintax groups
  (or a recorded override); the per-variant spintax table exists; no brace-collision
  options remain.

### Step 5 — Recontact + suppression sweep (free, before paid checks)
One Supabase pass over the whole list (batch the emails, don't loop 1-by-1):
1. `contact_history` (citext email match) joined to `campaigns` on
   `smartlead_campaign_id` → for every hit: email, campaign name(s), client,
   `first_contacted_at`. This covers archived AND active sibling campaigns — the table
   is the full history, so the sweep is the full suppression set by construction.
2. `suppressions` table → any match is a hard flag (DNC/unsubscribed etc.).
3. **Positive-replier suppression (client-specific, added 2026-07-13):** `replies`
   where `category in ('Interested','Meeting Request','Information Request','Call Booked','Re: Interested')`,
   joined to `campaigns` to resolve the client, matched against THIS upload's client only
   (a positive to one client never blocks another client's list). Any hit = the person
   already said YES to this client — they must never re-enter cold outreach; they belong
   in the positive pipeline (Folk/subsequence). Default action is DROP, overridable only
   by the same explicit per-flag approval. Overlay `reply_category_corrections` when
   reading historical categories — the archive was miscategorised before 2026-07-10
   (categoriser-fix audit) and corrections land in that table.
   This check exists because the 2026-07 audit found 14+ genuine positive repliers who
   were cold re-emailed by later recontact builds while their tag wrongly said "no".
4. **Cross-campaign collision check (added 2026-07-12):** for every candidate email,
   find any send in `sent_messages` within `CROSS_CAMPAIGN_WINDOW_DAYS` OR any active
   enrollment in a DIFFERENT campaign than the upload target. Resolve each campaign's
   client from its **name prefix** ("Arnic –", "Amplifyy –", …), NOT
   `campaigns.client_id` — the registry defaults everything to `navreo` and cannot be
   trusted for this. Rules:
   - **Same-client collision → default DROP** (flagged, overridable per-flag like
     everything else).
   - **Follow-up/subsequence campaigns (e.g. "Interested Reply") COUNT as collisions**
     — a lead in an active follow-up flow is mid-conversation and must never be
     cold-loaded into another campaign (Bjion, 2026-07-12).
   - **Pairs in `CROSS_CLIENT_ALLOWED_PAIRS` (Navreo↔Arnic) are fine** — no flag,
     recorded in the dossier only. Any OTHER cross-client collision is flagged as a
     WARN requiring explicit confirmation (not auto-drop).
   - **Live Smartlead cross-check:** the Supabase sync lags up to a day, so rows that
     come back clean from Supabase are also checked live via Smartlead lead-by-email
     (`get_lead_by_email` → `lead_campaign_data`) for in-flight enrollments; respect
     the 200/min cap. Any live-only hit gets the same rules above.
   This check exists because the 2026-07-12 audit found 43 leads emailed by 2+
   campaigns inside 14 days (9 same-client duplicates paused by hand).
Output: a per-prospect contact dossier ("used in campaigns X, Y for client Z, first
contacted 2026-03-02"). Previously-contacted prospects are FLAGGED, not auto-dropped —
the user decides (same offer again = usually drop; new offer = maybe override), and the
dossier is written into the audit record either way. Suppression hits are flagged like
any other finding and are equally overridable — but only by the same explicit per-flag
approval, and the override lands in the audit record.
- **Done-rule:** every row has been checked against all four sources (contact history,
  suppressions, positive repliers for this client, cross-campaign collisions incl. the
  live Smartlead cross-check); counts reported (clean / previously-contacted /
  suppressed / positive-replier / colliding); each hit row carries its dossier.

### Step 6 — Email verification (paid — runs last, only on surviving rows)
Only rows not already dropped in Steps 2–5 get verified (don't spend credits on rows
that are dying anyway). Waterfall per row:
1. **Cache/AI-Ark skip:** look up the email in `people`. If `email_verification` in
   (`good`,`ok`,`valid`) AND `email_verified_at` within `MV_TTL_DAYS` — skip, no
   verifier call (AI-Ark rows land here automatically since they're stamped verified
   at source).
2. **No verification record at all** (email absent from `people`, or present with no
   `email_verified_at`) → **ListMint** (batch via `/verify-emails?return=true`). Keep
   `valid` / `catch_all_valid` (flag catch_all), FAIL `invalid` / `catch_all_invalid`.
3. **Stale record** (`email_verified_at` older than the TTL) → **MillionVerifier**
   re-check. Keep `ok`/`catch_all` (flag catch_all), FAIL `invalid`/`disposable`,
   flag `unknown`. Sleep ~0.1s between calls.
4. After every real verifier call (either provider): write the verdict back to
   `people` and log 1 credit to `provider_usage` with the matching provider name.
   Skipped rows log nothing.
- **Done-rule:** every surviving row has a verification verdict + source
  (`cache_ttl` / `ai_ark_preverified` / `listmint_valid` / `listmint_catch_all` /
  `listmint_bad` / `mv_ok` / `mv_catch_all` / `mv_bad`); provider_usage rows match
  the count of real verifier calls per provider exactly; bad rows are on the flag
  list.

### Step 6b — List audit (composition score)
Sample min(LIST_AUDIT_SAMPLE = 50, all) rows and classify each job title on-ICP vs off-ICP against the
client's brief (LLM-first, per `lilly-list-audit` function-bucket conventions). Embed
in the run JSON as `list_audit: {sampled, on_icp, score}` (score = % on-ICP).
Informational — the page badge shows a letter grade (A ≥90 · B ≥75 · C ≥60 · D ≥40 ·
F below; A/B green, C/D amber, F red) with the raw % underneath, and the score is
recorded in the audit row, but it never blocks on its own.
- **Done-rule:** `list_audit` is present in the run JSON with a score derived from
  real title classification of the sampled rows.

### Step 7 — Review page + in-page resolution (REMOTE on the signals tool)
The review lives on the signals tool, not a local server. Include `rows`,
`list_audit`, and `checklist` (from the config block) in the run JSON, then:
1. `POST https://navreo-signals.onrender.com/api/qa-gate/runs` with header
   `x-navreo-token: <token>` and body `{"run": <run json>, "list_id": <uuid|null>}`
   (token = `SIGNAL_PULL_TOKEN` from `~/.navreo-keys.env`, or derived
   `sha256(SUPABASE_SERVICE_ROLE_KEY + ":signal-pull-v1")[:40]` — same scheme as the
   cron endpoints). **`list_id` is required, never null**: if the list came from the
   signals Lists database use that id; otherwise SAVE the input list there first
   (insert into `lists` — name, client, source_skill: lilly-upload-gate, columns,
   row_count — plus one `list_rows` row per lead with `data` jsonb) and use the new
   id. This powers the review page's "View list" button and the list's **QA
   receipts** (Lists page → list menu → "QA receipts…").
2. `open` the returned URL (`/qa-gate/<id>`) — reps review behind the tool's normal
   login; runs + decisions persist in the Supabase table `qa_gate_runs`.
3. Poll `GET /api/qa-gate/<id>/state` (same token header) for the decisions log and
   the upload decision; `GET /api/qa-gate/<id>/rows` is the corrected upload list.
Server code: `app/qa_gate.py` + routes in `app/server.py` in the `navreo-signals`
repo (`~/navreo-signals`; mind the iCloud-copy reconcile rule). Fallback ONLY if
the tool is down: `scripts/serve_review.py <run_result.json> [port]` serves the
identical page locally (keep the two renderers in sync).
The page is rendered by `scripts/render_report.py` in the **Navreo signals design
system** (same tokens as `~/navreo-signals/app/navreo.css`: white bg, line-bordered
12px cards, DM Sans body + Acid Grotesk display, `.pill.g/.a/.r` status pills, `.tbl`
tables, stat tiles, one orange per screen = the Approve button). Don't hand-roll
report HTML — extend the renderer if the layout needs to change, so every run stays
consistent with the signals tool.
The page shows: gate status pill, stat tiles (rows / checks / flags open /
overridden), and one card per check with **PASS / FAIL / OVERRIDDEN**. Flag rows are
written in plain English — humanised issue text plus a green "→ suggested fix" chip
where one exists, never raw values, arrows-in-quotes, or JSON dumps. Flag tables
paginate (5 per page) so big lists stay readable.
The page carries: the **list-quality score top-right** (from Step 6b), a **sticky
routine-check strip** (live ✓/○ per check, plus any manual CHECKLIST confirmations
if configured — none by default), stat tiles, and one card per check.
**Every flag is resolvable ON the page — nobody hand-types lead data into a QA
page.** If a fix can't be automated, the realistic actions are drop or approve:
- **One-click fix** (`✓ Fix → Sarah`) where the correct value is already known
  (normalisation suggestions), plus a per-card **Fix all N** button. Bulk fix never
  clobbers a deliberate manual re-fix.
- **Drop lead / Drop N leads / Drop every flagged lead** (each with confirm) —
  removes lead(s) and resolves every flag on them; records which check triggered it.
- **Approve — one click, instant.** Every open flag has an Approve button that acts
  immediately (no reason field, no selection step); "Approve all N" per card and
  "Approve everything open" globally do the same in bulk. Each decision is recorded
  with name + timestamp — the flag itself documents what was waived.
**HARD EXCEPTION — email deliverability is verify-or-drop, NEVER approved.** Every
uploading lead must hold a real verified verdict (people-cache TTL, AI-Ark
pre-verified, or a live ListMint/MV check). Unverified or bouncing leads have no
approve control and the API rejects them. The card states it plainly — "⛔ The
upload is blocked until these leads are verified: <emails>" (echoed in the bulk
toolbar) — and offers two ways out: **"Copy chat prompt"** (puts a ready-made
request on the clipboard to paste into chat, which runs `lilly-email-verification`
and re-runs the gate), or drop the leads. Verification never runs from the page —
chat only. The gate stays BLOCKED until every uploading lead is verified.
Every decision requires a reviewer name (`by`) — the page prompts once, the API
rejects anonymous calls. Decisions persist to `<run>.decisions.json`
(`{action: fixed|dropped|overridden|verified|verify_run|confirmed, …, by, at}`) and
the page re-renders; a check flips to RESOLVED/OVERRIDDEN only when ALL its flags are
resolved; the gate goes BLOCKED → CONFIRM CHECKLIST → CLEARED (warning shown if 0
leads remain). Hint lines steer judgment: recontact rule of thumb (same offer or
<90 days → drop) and an icebreaker-recycle tip on variable-fill flags.
**The Upload button (top-right) is how the review ends.** A split button with two
modes:
1. **Approve & upload (default).** Refuses while any check is failing — returns the
   open counts, and the page scrolls to and highlights the first failing card. Only
   a fully cleared gate passes.
2. **Force upload.** Bypasses every remaining check (confirm dialog, recorded as
   `mode: forced` with name + gate state at the time). This is the break-glass path:
   **a broken gate must never stop a campaign from going live.** The audit row's
   verdict is set to `forced` so it's always visible after the fact.
The upload decision lands in `<run>.decisions.json` (`{action: "upload", mode:
approved|forced, gate_at_upload, by, at}`). Step 8 proceeds only once that decision
exists; read `<run>.decisions.json` for the audit record and **`GET /api/rows` for
the corrected upload list** (drops removed, fixes applied) — Step 8 uploads THAT
list, never the original. "Proceed anyway" in chat with nothing resolved is NOT an
approval. Silence is never consent.
- **Done-rule:** the review server is up and the page opened in the browser; every
  check is PASS, RESOLVED, or OVERRIDDEN per `<run>.decisions.json`; zero open FAIL
  flags remain; the corrected list from `/api/rows` is what proceeds to Step 8.

### Step 8 — Audit record, then upload
**Audit first, upload second — the upload is not allowed to start before the audit row
exists.**
1. Write one row to Supabase table `list_upload_qa_runs` (create it on first run:
   `id, run_at, campaign_id, campaign_name, list_source, rows_in, rows_uploaded,
   checks jsonb, overrides jsonb, recontact_hits jsonb, verdict, report_path`;
   verdict ∈ `pass | overridden | blocked | forced` — `forced` whenever the Upload
   button's force path was used).
   `checks` holds every check's status + headline numbers; `overrides` holds each
   override verbatim with the user's reason; `recontact_hits` holds the dossiers.
2. Upload via Smartlead `add_leads_to_campaign`: **1 test lead first**, fetch it back
   to confirm it landed with correct `custom_fields` (company_name key!), then batch
   the rest respecting the 200/min cap. Update the audit row with `rows_uploaded`.
- **Done-rule:** the `list_upload_qa_runs` row exists and its `verdict` is
  `pass`/`overridden`; the test lead is confirmed in the campaign; the batch count in
  Smartlead matches `rows_uploaded`; the audit row was written BEFORE the first
  add_leads call.

## Final report (always, both modes)
One summary: per-check PASS/FAIL/OVERRIDDEN, rows in → dropped per check → uploaded,
MV credits spent (with provider_usage confirmation), recontact hits with their campaign
history, every override + reason, the audit row id, and the report file path.

**The gate moment lives IN the chat (Bjion ruling 2026-07-26):** the per-check verdict
summary and the approve/override decision are presented in the chat flow itself — the
remote review page is the deep view for row-level work, linked from the chat, never a
required detour. The user should be able to read the verdict and say "go" without
leaving the conversation.

**Closing message after a successful upload (fixed shape, every run):**
> Uploaded **{rows_uploaded}** leads to **{campaign_name}**. A record of this upload
> has been logged — see the campaign's Leads page:
> https://navreo-signals.onrender.com/app/campaigns.html#/c/{campaign_id}/leads
> {if partial pool: "That's {rows_uploaded} of the {pool_total} people saved for this
> campaign — {remaining} are still available, and you can add them any time from the
> Sources tab on that campaign's page."}
> {if pool emptied: "That uses everyone saved for this campaign — I can find more people
> with the same targeting whenever you want to extend it."}
> Plain English rule (panel ruling 2026-07-26): user-facing lines say "people saved for
> this campaign", not "pool"; name the exact place ("the Sources tab on the campaign's
> page"), never a bare system noun.

## Hard don'ts
- **Never call `add_leads_to_campaign` (or any Smartlead lead-push) before every
  enabled check is PASS or explicitly OVERRIDDEN and the audit row is written.** This
  applies even when another skill hands off here mid-flow.
- Never treat "just upload it" as an override — approvals are per-flag (ticked or
  named), recorded in the audit with the reviewer's name. No flag can be skipped.
- Never approve an email-deliverability flag — unverified/bouncing leads are
  verified (page button or `lilly-email-verification` in chat) or dropped, full stop.
- Never silently drop or silently pass a row — every exclusion and every flag is in
  the report and the audit record.
- Never spend an MV credit on a cached/AI-Ark-verified email inside the TTL, and never
  make an MV call without its matching provider_usage row.
- Never put `company` in custom_fields (it's `company_name`); never skip the 1-test-lead
  probe.
- Never lowercase an ALL-CAPS acronym; never guess — flag ambiguous company names.
- Never exceed a retry cap or report done while any done-rule fails.
