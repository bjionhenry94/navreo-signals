---
name: lilly-recontact
description: Build a recontact campaign from one or more finished/archived campaigns without double-contacting anyone. Say "Build a recontact campaign from [campaign]" and Lilly nets the audience (finished in the source, not suppressed/DNC, not active in any other live campaign) and builds a paused DRAFT. Two routes to the same de-duplicated audience - INLINE by default for a single clean source campaign (net directly against Supabase suppressions + contact_history and build the Smartlead draft right in chat, no login-gated page), and a UI hand-off to the signals tool's five-bucket review page ONLY when there are multiple potential sibling campaigns to eyeball. A recontact REPLACES its predecessor generation and never runs alongside it - the skill names the ACTIVE siblings of the same audience and pauses the one being replaced, because two live generations email the same people twice no matter how clean each one looks on its own. Netting also excludes anyone sent to in the last 30 days. Draft only, nothing sends. Trigger on: "build a recontact campaign from X", "recontact the people from X", "re-approach [campaign]", "rebuild a recontact from these campaigns", "/lilly-recontact".
---

# Lilly Recontact

Turns "recontact the people from [campaign]" into a reviewed, de-duplicated DRAFT campaign. Two
routes to the same de-duplicated audience:

- **Inline (default for a single source campaign with no real sibling ambiguity).** Do the whole
  thing in chat: net the audience directly against Supabase (`suppressions` + `contact_history`
  active-elsewhere) and build the paused Smartlead campaign here. Faster, no login-gated page, no
  signals token needed. This is the right call whenever the user just says "recontact campaign X"
  and there aren't multiple overlapping siblings to reason about. **Proven 2026-07-23 on campaign
  3274582 → 3709470 (1,139 finished pool → 1,021 eligible).**
- **UI hand-off (only when there are multiple potential siblings).** When the scan surfaces several
  overlapping campaigns and the user needs to eyeball which to fold in, hand off to the signals
  tool's review page where the five buckets are visual and selectable. Use this route when the
  sibling picture is genuinely ambiguous, or when the app session is the only way to auth.

Pick the route up front. If in doubt and it's one clean source campaign, go inline.

## Hard rules
- **⛔ A recontact REPLACES its predecessor; it never runs alongside it.** Every recontact is
  a new generation of an audience that already has one. Two live generations = the same
  people emailed twice, and no netting rule catches it because each campaign is
  individually clean — the duplication lives in the pair. Name the ACTIVE siblings, say
  which one the new campaign replaces, and pause/archive it. Leaving it running is the
  user's explicit call, never the silent default. Detail + the detector query in Flow A
  step 3.5; it applies to Flow B identically (do it after the scan, before `create`).
  This is the rule whose absence caused the 2026-07 duplicate outreach: eleven stacked
  groups, three live Salesloft-follower generations, 611 people in two Followers Recovered
  campaigns at once, and areiter@cloudtask.com in eighteen campaigns.
- **Draft only. Nothing this skill does may activate a campaign or send anything.**
- Eligibility maths is the server's (single source of truth): Eligible = finished in the source
  campaign(s) AND not active in ANY live campaign AND not suppressed/DNC; "replied before" excluded
  by default (user can flip the toggle on the page).
- Never rebuild the buckets by hand in chat; read them from the API so chat and page always agree.

## Endpoints (live host: https://navreo-signals.onrender.com; staging: the local mirror)
- `GET /api/recontact/scan?campaign_id=<smartlead id>` → sibling candidates with
  `{campaign_id,name,status,finished,in_progress,overlap_count,match_reason}`.
- `POST /api/recontact/buckets {campaign_ids:[], include_repliers}` → the five buckets + sample;
  buckets always sum to total contacted.
- `POST /api/recontact/create {campaign_ids, include_repliers, name}` → creates the draft
  (campaign_drafts row + one INACTIVE recontact source holding the eligible people) → `{id, eligible}`.
- Review page (login-gated): `GET /recontact/<run-id>` — self-bootstraps the run row on first visit.
  All API calls need the normal app session (or `x-navreo-token` for machine calls).

## Flow A — Inline (default, single source campaign)

Everything here is Smartlead REST + Supabase MCP; no signals token, no login-gated page.

1. **Resolve the campaign** → Smartlead id.
2. **Pull the source pool.** Export the source campaign's leads:
   `GET https://server.smartlead.ai/api/v1/campaigns/<id>/leads-export?api_key=<SMARTLEAD_API_KEY>`
   (CSV). Pool = rows with `status = COMPLETED`, `reply_count = 0`, `is_unsubscribed = false`,
   valid email. (Finished + no reply; BLOCKED/bounced rows drop out here, so the pool is
   empirically deliverable.)
3. **Net against Supabase (the same sources the server uses).** Stage the pool emails in a temp
   table, then subtract:
   - `suppressions` (any match = hard drop, DNC/unsub).
   - `contact_history` where `smartlead_campaign_id <> <source>` AND
     `status in ('INPROGRESS','STARTED','PAUSED')` = active in another live campaign.
   - **`sent_messages` within the last 30 days from ANY campaign other than the source**
     = recently-emailed. ⚠️ This rule is the one that was missing and it is the one that
     matters most. The other two only catch people who are *currently* enrolled; a prior
     generation of the same audience is `COMPLETED`, so it sails straight through. That is
     how areiter@cloudtask.com got hit by the Jan, April AND June Salesloft-follower
     recontacts and replied "You already send me this dude!" (2026-07-24).
     **30 days is Bjion's ruling (2026-07-25) — do not raise it.** Recorded so nobody
     re-litigates it: over 270 days of `sent_messages` the gap between two campaigns
     emailing the same person was 0-30d for 1,199 leads, 30-60d for 322, 60-89d for 209,
     then thin. So 30 days catches ~63% of re-contacts and re-approaching someone last
     emailed 31-90 days ago is deliberately allowed. Beyond 30 days a re-approach counts
     as a fresh attempt, not an accident.
   - **ever-positive repliers for this client** (`replies` overlaid with
     `reply_category_corrections`) — they belong in the positive pipeline, never cold again.
   Get the small **exclusion** set (suppressed ∪ active-elsewhere ∪ recently-emailed ∪
   ever-positive) back and subtract locally from the CSV to keep full lead detail.
   Eligible = pool − exclusions. Report the buckets (pool / suppressed / active-elsewhere /
   recently-emailed / ever-positive / eligible) and confirm they reconcile.
   **Same-client only** — a lead active in a DIFFERENT client's campaign is not a collision
   and must not be excluded (MEMORY: feedback_collision_same_client_only).
   **Net against a post-sync read, then live-confirm the survivors.** `contact_history`
   lags Smartlead by up to a day, so a stale read both invents exclusions and misses real
   ones. Confirm survivors via Smartlead before the draft is built.
3.5. **⛔ RETIRE THE PREDECESSOR — the step whose absence caused all of this.**
   A recontact is a NEW GENERATION of an audience that already has one. If the previous
   generation is left ACTIVE, both send to the same people and every netting rule above is
   irrelevant, because each campaign is individually clean — the duplication lives in the
   pair. On 2026-07-25 this had produced eleven stacked groups, including THREE live
   Salesloft-follower generations (April + June + July) and *Followers Recovered* running
   beside *Followers Recovered - [July]* with 611 people in both.
   So, before the draft is built:
   - **Find the siblings.** Same audience, different generation = same campaign-name stem
     once generation markers are stripped (`Recontact (June):`, `Reconnect:`, `New `,
     `2.0`, trailing `[July]` / `[May 2026]` / `[EVEN]`). Supabase has this:
     `select * from jsonb_array_elements(collision_stacked_generations())` — or
     `collision_campaign_stem(name)` to test one name. Same-client only.
   - **Name every ACTIVE sibling in chat with its send + positives/1k**, and say which one
     the new campaign replaces.
   - **Pause or archive the predecessor** (`update_campaign_status` → `PAUSED`, and prefer
     pausing over deleting — reversible). If the user wants it left running, that is their
     call and it gets recorded, but it is never the silent default.
   - Sub-sequences ("Interested Reply", "Meeting Request") are NOT siblings — never touch
     them; a lead mid-conversation there is by design.
   - **Done-rule:** at go-live, `collision_stacked_generations()` returns no group
     containing the new campaign. If it does, the recontact is not finished.

4. **Build the paused campaign here:** `create_campaign` → `update_campaign_schedule` +
   `update_campaign_settings` (house defaults; note `track_settings` on this endpoint wants
   `DONT_TRACK_EMAIL_OPEN` / `DONT_TRACK_LINK_CLICK`) → save the sequence via the REST
   `POST /campaigns/<id>/sequences` (see `lilly-bot`). New campaigns land as `DRAFTED` with no
   mailboxes, so nothing can send.
5. **Upload gate is still MANDATORY before leads.** Hand to `lilly-upload-gate`. For a recontact of
   already-delivered leads the substantive checks are variable-fill (copy usually only uses
   `{{first_name}}` + `{{company_name}}`) and the recontact/suppression sweep (already done in
   step 3). Write the `list_upload_qa_runs` audit row BEFORE the first add-leads call. If the
   remote review page can't auth (no signals token), run the checks inline and record the audit
   row + overrides in Supabase directly — never skip the audit row.
6. **Upload:** 1 test lead → verify → batch the rest (chunks ~100, respect 200/min).
7. **Report + next steps:** campaign id, eligible count, DRAFTED status, and that mailboxes +
   go-live are a deliberate later step (usually a Notion "set live" task via `add-task-to-notion`).

## Flow B — UI hand-off (multiple potential siblings only)
1. **Resolve the campaign.** Name → Smartlead id via the `campaigns` Supabase table or the campaigns
   list endpoint. Ambiguous name → show the top matches, ask once.
2a. **Retire the predecessor** — the Hard rule above, applied here before `create`. Run
   `select * from jsonb_array_elements(collision_stacked_generations())`, name every ACTIVE
   sibling of this audience with its send + positives/1k, and pause/archive the one the new
   campaign replaces. Done-rule: that query returns no group containing the new campaign.
2. **Scan.** `GET /api/recontact/scan`. Present the siblings in one compact table (name, status,
   finished, in progress, overlap, why it matched). Default selection = all; the user can name
   exclusions in chat.
3. **Buckets.** `POST /api/recontact/buckets` with the selected ids. Report the five numbers in
   plain English and confirm they sum to the total. Ask one question only if the user might want
   past repliers included (default: excluded).
4. **Hand off to the page** for the visual check: mint a short run id (e.g. `rc-<date>-<4 hex>`),
   give the user `https://navreo-signals.onrender.com/recontact/<run-id>` and tell them the same
   scan/buckets/create controls live there. If the user says "just create it", skip the page and:
5. **Create.** `POST /api/recontact/create` with a clear name ("Recontact: <source name> - <month year>").
   Report: draft id, eligible count, and the reminder that the draft holds an inactive source, is
   bound to no destination, and sends nothing until copy + shell + launch happen deliberately.
6. **Open the campaign in the tool (Bjion ruling 2026-07-26, every build):** after create, open
   `https://navreo-signals.onrender.com/app/campaigns.html#/c/<draft-id>` in the chat's
   browser pane so the user SEES the draft ready to go — the recontact has no UI of its own, but
   it always ends with the campaign visible in the tool.
   **Closing message is plain English (panel ruling 2026-07-26):** never "eligible after
   netting" — say what happened: *"<N> people from the old campaign are clear to re-approach —
   I've excluded everyone who opted out, replied positively, was emailed in the last 30 days,
   or is in another live campaign."* The predecessor pause was agreed at step 3.5, so the
   closing references it as the agreed plan ("and as agreed, the April version is now paused so
   the two never overlap"), never as a surprise. End with the single next step: *"Next: want me
   to write the copy for it?"*
7. Suggest the natural next steps: shell via chat ("Spin up a campaign shell for..."), copy via
   `lilly-copywriter`.

Note: the signals endpoints need the normal app session or `x-navreo-token` (= `SIGNAL_PULL_TOKEN`,
server-side only). If that token isn't available locally, prefer Flow A.

## Verification habits (every run)
- Buckets sum check: eligible + in_progress + active_elsewhere + suppressed + replied == total; if
  not, stop and report rather than proceeding.
- After create: read the draft back (`campaign_drafts` + its source) and confirm prospects count ==
  eligible count before declaring done.

## Known limits (2026-07-14)
- Scan runs 4-12s per campaign (bounded, capped at 10 candidates).
- The create endpoint does not yet persist the draft's display name reliably and lacks an in-flight
  guard against double-clicks (both flagged in the tier1-live-ship sign-off pack).
