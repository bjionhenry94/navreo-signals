---
description: Optimise campaigns in Smartlead
---

## The Cockpit contract (runs FIRST, every /lilly-optimiser invocation)

**Scope exception — variant swaps are chat-only (Bjion ruling 2026-07-26):** a pure
"replace/swap the failing email variants in [campaign]" ask is NOT a cockpit run. It
produces the replacement variants as paste-ready copy in the chat (lilly-copywriter voice
rules apply) — no cache sweep, no page auto-launch, no UI. The cockpit contract below
governs insight/optimisation runs.
**Finish the job (panel ruling 2026-07-26):** after presenting the replacements, OFFER to
apply the swap: *"Want me to save these into Smartlead for you? Heads up — saving the
sequence resets the per-variant stats, so if you want to keep the old numbers, edit in the
Smartlead UI instead (lilly-bot's variant rules apply either way)."* Never leave "now you
paste it" as the unstated ending. And write variant names out in full — "variants A and C
stay live", never shorthand like "A/C".

The deliverable of every run is the LIVE campaigns page on the Navreo signals tool: **https://navreo-signals.onrender.com/app/campaigns.html#/** . The page renders the Supabase cache directly (via the app's `/api/cockpit/*` endpoints), so the run's ONLY job is to refresh the cache: sweep, fingerprint, regenerate stale scopes, upsert `campaign_insights`. No artifact republish, ever (the old artifact `1c7161d8` is retired history, shipped as this page on 23 Jul 2026, commits ae44e82 + c0e99ad). Chat stays a short door: no insight lists, no summaries, no offers or questions in chat. One short line + the page link, nothing else. Then AUTO-LAUNCH it: run `open "https://navreo-signals.onrender.com/app/campaigns.html#/"` via Bash so it opens in Bjion's browser without a click (skip the `open` in headless/scheduled runs with no browser).

Row-pill option: a campaign verdict payload may carry a short `pill` field (2 to 4 words, e.g. "Past the kill line"); the page shows it on the row where the status pill sits. Without it the page falls back to the tag label. Tag vocabulary is exactly `decision | watch | fine`.

**Architecture: two layers.**
- DATA LAYER = Supabase (project fnykldftbkrccihdjayl). Already-synced tables (campaigns, replies, sent_messages, optimiser_notifications, list_pull_campaigns...) are the cache and the record. Insights are cached in `campaign_insights` (scope = 'book' or a Smartlead campaign id; payload = widget-grammar JSON; unique live row per scope+insight_key) with per-user dismissals in `insight_dismissals`.
- AI LAYER = this Claude session. Claude reads the data layer, runs the analysis in this skill, writes the insight rows back, and republishes the artifact. The brainpower NEVER moves into the app; the app and artifact only render what Claude wrote.

**Cache and freshness rules (stop overlapping insights across users).**
1. Before analysing a scope, read its live rows from `campaign_insights` and compute the scope's current data_fingerprint: campaign scope = md5 of (lifetime sent, replies, positives, bounce, latest optimiser_notifications.created_at for that campaign); book scope = md5 of (workspace weekly positives, unanswered-positives count, campaign count).
2. REUSE the cached insights untouched when the live set is under 24 hours old AND the fingerprint matches. Regenerate ONLY scopes that are stale (>24h) or whose fingerprint changed. A second user running the same day gets the cache, not a re-derivation.
3. Regeneration SUPERSEDES: mark the scope's old live rows status='superseded' (set superseded_at), insert the new set. Insights never stack.
4. Minimality caps: max 4 live insights per campaign scope, max 6 for book scope. Fewer is better; a healthy campaign can carry a single 'verdict' row.
5. Dismissals are PER USER: a row in `insight_dismissals` (insight_id, user_key) hides that insight for that user only. Never delete the insight for everyone because one user dismissed it. When rendering for a known user, filter their dismissals out; the artifact's own device-local dismiss states stay as-is.
6. Every insight payload follows the cockpit widget grammar (tag, visual data, one bold line, one act line, owner) with one-source one-window numbers that back-solve exactly. No em dashes anywhere.
7. AUTO-EXPIRY: obviously out-of-date insights remove themselves, no dismissal needed. Every insight row carries `expires_at` (default 7 days; set SHORTER when the claim is time-boxed, e.g. "list runs dry this week" = 3 days, a weekly-window stat = until the window rolls). Every run starts with the sweep: `update campaign_insights set status='expired', superseded_at=now() where status='live' and expires_at < now();` and fingerprint-changed scopes supersede their whole live set on regeneration (an insight whose underlying condition no longer holds never survives a run). Renderers (artifact and app) must filter to status='live' AND expires_at > now().

---

## THE SPECIFICITY CONTRACT (binding on every `act` line, no exceptions)

Bjion's ruling, 26 Jul 2026: *"The optimisations are repetitive, they don't feel specific."* Measured that day: **98 live cards, 16 distinct act lines. 21 campaigns shared one identical headline. Not one act line named a variant or carried a number.**

The `bold` line was already campaign-specific. The `act` line had collapsed into one canned phrase per `kind`, so every card in a kind read identically. That is the defect this contract closes.

**The swap test defines a failure.** Paste an act line onto a different campaign in the book. If it still reads as true, it is generic and must be rewritten. "Replace the weakest copy" passes the swap test on 70 campaigns, so it fails this contract.

Every `act` line must satisfy all five:

- **S1 Names the thing.** Point at a specific object in THAT campaign: variant label (`Var B`), sequence step (`Email 2`), a quoted subject or first-line fragment of 3 to 6 words, the named persona/segment, or the mailbox/domain. "The weakest copy" fails. "Var B's 'quick one about hiring' angle" passes.
- **S2 Says what changes, not how to type it.** The headline states the substantive change: which angle dies, what replaces it, what it gets tested against. Editing **mechanics** (draft in chat, paste by hand, never via the API, use the Smartlead UI) are real rules but they are NOT the recommendation. They belong in `note` (rendered inside `Why?`) and in the handed Claude prompt. They never occupy the headline.
- **S3 Carries one number only this campaign has.** Not the threshold (800, 1,500, 15,000). This campaign's own figure: this variant's sends and positives, this step's reply rate, the leads left in this list.
- **S4 Distinct verb.** Across one full refresh, no opening verb may be used by more than 30% of cards. Vary the verb to the actual act: swap, retire, split, reload, hold, pivot, audit, promote.
- **S5 Passes the swap test.** Re-read it against a sibling campaign. Still true anywhere? Rewrite it.

### Act-line templates (slots are mandatory, and only that campaign can fill them)

Compose from the campaign's own data. A template with an unfilled slot is not shippable; go and fetch the datum instead of dropping the slot.

| kind | shape | filled example |
|---|---|---|
| `verdict` (performing) | Hold {Var/step} at {ratio} per positive, refill at {leads left}. | Hold Var A at 1,022 per positive, refill before the last 1,900 leads. |
| `verdict` (failing) | Retire the {quoted angle} angle: {sent} sends, {pos} positives. | Retire the "presentation design partner" angle: 5,138 sends, 0 positives. |
| `copy` / variants | Swap {Var} on {Email N}, its {quoted angle} is at {sent}/{pos}. | Swap Var B on Email 1, its "buyers for you?" line is at 2,400 sends, 0 positives. |
| `lifecycle` | Reload {persona} leads, {leads} loaded and {completion}% through. | Reload SEO agency leads, 15,802 loaded and 100% through. |
| `list-audit` | Audit the {persona} list: {reply_rate}% replies on {sent} sends. | Audit the SEO agency list: 0.9% replies on 32,700 sends. |
| `kill` | Pivot off {persona} at {ratio} per positive across {sent} sends. | Pivot off SaaS sales leaders at 5,018 per positive across 10,035 sends. |

### Worked before/after, from the real 26 Jul cards

1. **Campaign 3651763 (Reconnect 2.0: Amplifyy).** Before: *"Rewrite the offer. Draft in chat, paste into Smartlead by hand."* (9 campaigns shared it; S1, S2, S3 all fail). After: *"Retire the presentation-design angle: 5,138 sends, zero positives at 45% through."*
2. **Campaign 3317530 (Navreo SEO & GEO Agencies).** Before: *"Run /lilly-list-audit on this campaign, check deliverability in parallel."* (21 campaigns shared it). After: *"Audit the SEO agency list: 0.9% replies on 32,700 sends."* The skill name moves into `note`.
3. **Any performing campaign.** Before: *"Leave it running. Keep the list topped up."* (16 campaigns shared it). After: *"Hold Var A at 1,022 per positive, refill before the last 1,900 leads."*

### S6 Never name a variant the data cannot judge (Bjion ruling, 26 Jul 2026)

Specificity must never be bought with a claim the numbers do not carry. The first run of this contract shipped *"Cut Email 1 from four openers to the one that has replied: 11,774 sends, 2 positives"* on campaign 3507270. Bjion: **"what does this even mean?"** Three failures in one line:

1. **Wrong actor.** A variant does not reply, a lead does. The sentence did not parse.
2. **Unjudgeable evidence.** The "winner" it pointed at was Var B on **138 sends** with 1 positive. The judging bar is 800 sends. One positive on 138 sends is noise.
3. **Two windows in one sentence.** It welded a campaign-level figure (11,774 sends, 2 positives) to a variant-level recommendation built from 482 attributed sends, 4% of the campaign.

So, binding:

- **Never name a winner or loser variant that is under the 800-send bar.** If no variant clears it, say so and make the recommendation at campaign level.
- **Never mix scopes in one line.** A sentence about a variant carries that variant's sends and positives. A sentence about the campaign carries the campaign's. Check the numbers back-solve to the same window before shipping.
- **Check attribution coverage.** When variant-attributed sends are a small fraction of campaign sends (a rebuilt sequence orphans its history), the variant table cannot support any call. Say the copy needs rebuilding at campaign level rather than inventing a winner.
- **Name the actor.** Variants get swapped, disabled or rewritten. Leads reply. Never write a variant as the thing that replied.

An act line that is vague but true beats one that is specific and unsupported. The point of the contract is to stop generic recommendations, never to manufacture confidence.

### To fill the slots you must fetch variant data

The old payloads carried campaign-level `stats` only, which is exactly why act lines could not name a variant. When generating a campaign scope, also pull `get_campaign_variant_statistics` and `get_campaign_sequences` for that campaign (cheap, one call each) and carry `variant` into the payload: `{label, seq_number, sent, positives, angle}` for the variant the card is about. `build_notifications.py` already computes this shape in `build_campaign_findings`; reuse its vocabulary (`Email {seq} Var {label}`) so both surfaces read alike.

**Self-check before upsert.** After composing a scope's cards, compare every act line against the other act lines in the same run. Any byte-identical pair, or any pair sharing their first four words, is a contract failure: rewrite both before writing to Supabase. Also confirm zero em dashes in the whole payload (11 payloads carried them on 26 Jul).

---

**Run shape:** (0) run the expiry sweep, (1) fingerprint + cache check per scope, (2) run the analysis below ONLY for stale scopes, (3) upsert `campaign_insights` with per-insight expires_at, (4) verify the live page picked it up: authed GET `https://navreo-signals.onrender.com/api/cockpit/insights` returns the fresh `generated_at` (mint the session cookie with `server._mint_session` from the repo if needed), (5) auto-launch the page (`open "https://navreo-signals.onrender.com/app/campaigns.html#/"`; skip when headless) and hand over in chat with one short line + the page link, nothing else. The web app reads the same tables through `/api/cockpit/*`; there is no separate publish step.

---

## Core Metric

**Emails Sent per Positive Response** (lower = better)

- Primary: `total_emails_sent / positive_replies`
- Tiebreaker: Call Booked count (always check alongside primary metric)

**Positive Response Categories** - only these count:
- Interested
- Call Booked
- Meeting Request
- Information Request

**Data accuracy rules:**
- The campaign-level positive count from `smartlead_analytics_campaign_overall_stats` is the source of truth. Variant-level totals must never exceed it.
- Do NOT count "Information Requested" (with a "d") - the actual Smartlead category is "Information Request".
- Email 2 positives belong to Email 2, NOT to any Email 1 variant. Never attribute an Email 2 positive back to an Email 1 variant. Each sequence step's positives are independent.
- When aggregating by variant, use the `seq_variant_id` field. Records with a null variant ID belong to inline Email 2/3 steps. Count those separately as "Email 2" (or "Email 3").
- Email 2 should appear as its own row in the variant analysis table, just like any other variant. It is not grouped under Email 1.
- If a performing campaign has no actionable recommendations (all variants are KEEP or too early, and no clear winner/loser), skip it from the variant analysis section entirely.

All other categories (Not Interested, Do Not Contact, Out Of Office, Wrong Person, etc.) are NOT positive.

---

## Guardrails

- NEVER use em-dashes in any copy. Use commas, full stops, or line breaks instead.
- NEVER delete a variant. Disable only. Deleted variants lose historical data.
- Sequence edits on existing campaigns are ALLOWED via API (updated 2026-08-02 — supersedes the old hard block), but ONLY with the ID-intact recipe AND an explicit user go-ahead first (state the change, confirm ids will be carried, wait for the yes). A save that omits ANY variant's id permanently orphans that variant's history with NO recovery (proven destructively 2026-08-02); ids carried = history preserved (proven by controlled before/after + founder confirmation).
- **HOW — the ID-intact save, exactly:**
  1. `get_campaign_sequences` (or `GET /api/v1/campaigns/{id}/sequences`) FRESH, immediately before the save — never from a stale fetch.
  2. Build the POST body as `{"sequences": [...]}` by translating three names from the GET: wrap steps in `sequences` (PLURAL — singular 400s), `sequence_variants` → `seq_variants`, `seq_delay_details.delayInDays` → `delay_in_days`. Everything else copies verbatim. PLUS on every variant-carrying sequence: `"variant_distribution_type": "MANUAL_PERCENTAGE"` and per-variant `is_deleted` — omitting the type flips the step to EQUAL mode (all variants re-enabled even split; live bite 2026-08-02).
  3. Echo every step `id` and every variant `id` back UNCHANGED; edit only the field you're changing. New variant = the only object without an `id`. Disable = keep the id, set `variant_distribution_percentage: 0` (remaining active variants sum to 100). Omitting an existing variant DELETES it and orphans its history forever — never omit without "YES DELETE THAT".
  4. POST via `save_campaign_sequences` (or the REST endpoint). Returned step ids must match what you sent.
  5. Verify or it didn't happen: re-GET and confirm every pre-existing variant kept its EXACT id, then `get_campaign_variant_statistics` still shows the prior sent/reply history on those same ids. On a 429 (200 req/min account cap) wait ~70s and retry — never skip the verify.
  Worked payload example: `lilly-bot` → "Save sequence endpoint (REST) — THE ID-INTACT RECIPE".
  6. **Prefer the platform door (2026-08-02):** disable/enable/scale/even-split/add-challenger/apply-fix all exist as tool endpoints (`/api/campaigns/{id}/variant-action`, `/add-variant`, `/api/notifications/{id}/apply-fix`) that route through the server's `save_sequence_ids_intact` — id guard + post-verify enforced server-side. Use them when acting on a tool insight; hand-rolled saves are for edits those doors don't cover.
- NEVER delete or overwrite copy of a previously live campaign without double verification ("YES I APPROVE THAT" from CSM).
- NEVER pause or stop a campaign without CSM approval.
- NEVER use `{{sender_name}}` or `{{sender_title}}`. Always use `%signature%` for the sign-off block.
- All new variant copy must be presented for CSM approval before going live.
- New copy must match the existing template structure: same length, CTA style, personalisation tokens, format. Only the problem/pain-point or offer changes.

---

## Campaign Assessment: Step 1 - Priority Report

When the user triggers the optimiser, generate the Campaign Optimisation Priority Report.

### Data Collection

**ALL WORKSPACES (not just Navreo).** The crunch covers every workspace under the tool's management, not only Navreo's Smartlead. Read the enabled workspaces live from the tool (`GET /api/workspaces`, or `server.ws_enabled()` in the repo) and run the collection below **once per enabled workspace, using that workspace's own Smartlead key** (`server.ws_key(workspace)` — the raw key never leaves the server; the MCP process env key is Navreo's only). A campaign's `campaign_insights.scope` is its Smartlead id, which is globally unique across accounts, so client insights never collide with Navreo's. Guardrails: (a) never call a client workspace's Smartlead with Navreo's key or vice-versa; (b) the crunch READS and WRITES insights only — it must NEVER trigger a send, pause, or any lead-level write (see `[[never-send-to-real-prospects]]`); (c) skip pre-launch workspaces (e.g. Grout) with a logged reason — an empty inventory is correct, not a failure; (d) one workspace failing (bad key, rate limit) records the error and continues to the next, never aborts the run. The fastest candidate source is the federated `campaign_scorecard` cache (already every workspace, stamped with `workspace`, carrying live sent + status) — select ACTIVE + 1,500-sent candidates from it, then do the per-variant deep dives below with the owning workspace's key.

1. For each enabled workspace, call `smartlead_list_campaigns` (with that workspace's key) to get its campaigns.
2. Filter to campaigns with status `ACTIVE` only. Exclude paused, archived, stopped, or draft.
3. Call `smartlead_analytics_campaign_overall_stats` with `start_date=2025-01-01`, `end_date={today}`, `full_data=true` to get campaign-level performance.
4. Cross-reference: keep only ACTIVE campaigns with **1,500+ emails sent**.
5. Calculate **Sent/Positive** ratio for each campaign.
6. Sort by ratio descending (worst first; zero-positive campaigns at the top sorted by sent desc).
7. For each qualifying campaign, call `smartlead_list_leads_by_campaign` with `limit=1` to get `total_leads` for completion %.
8. For ALL campaigns in both tiers (needing optimisation AND performing), call `smartlead_get_campaign_sequence` to get variant-level data.
9. For performing campaigns, call `smartlead_get_campaign_statistics` to get variant-level positive reply attribution.

### Campaign Completion Percentage

Calculate as: `emails_sent / (total_leads_in_campaign * 2) * 100`.

Each prospect receives 2 emails (Email 1 + Email 2), so a fully completed campaign = total_leads × 2 emails sent. For example: 5,000 prospects and 7,500 emails sent = 75% complete.

Use `total_leads` from `smartlead_list_leads_by_campaign` (NOT `unique_lead_count` from analytics).

### Formatting Rules

- Campaign names MUST be hyperlinked using `[Campaign Name](https://app.smartlead.ai/app/email-campaign/{campaign_id}/analytics)` EVERYWHERE they appear - tables, drill downs, action items, any mention. No exceptions.
- **Markdown table safety**: Hyperlinks inside table cells MUST NOT contain unescaped pipe characters or line breaks. Shorten campaign display names if needed so links don't bleed into adjacent columns. When building a table row, always verify each `|` cell delimiter is present and that the link's closing `)` comes BEFORE the next `|`. Write tables one row at a time, never interpolate campaign links from variables that might contain extra `|` or `]` characters.
- Use "Email 1", "Email 2" etc. Never "Seq 1" or "Seq 2".
- Summarise variant angles in plain English. Never paste raw HTML or spintax.
- **Disabled variant rule** — skip from all tables and analysis. A variant is disabled if: `is_deleted: true`, OR `variant_distribution_percentage: 0` AND the variant has at least 1 send (it was active, then intentionally turned off). Disabled variants are only referenced in Step 2 deep dives under "Previously Tested". Do NOT treat a variant with 0% distribution and 0 sends as disabled — that is a configuration bug (see Section 6).
- **Monitor-phase variants are excluded from the entire report.** A variant is in the *monitor phase* until it reaches 800 emails sent: too early to judge either way. Do not list it in any section, including the Variant Analysis (Section 4). There is no Monitoring section. One deliberate exception: the **campaign-level failure rule** in Section 4 (Variant Analysis), where a campaign with 1,500+ sent and zero positives flags all of its active variants (early ones included) because the whole campaign is failing.

### Report Structure

The report has 7 sections in this order. Actionable sections come first. Variants still in the monitor phase (under 800 emails sent, too early to judge) are excluded from every section per the monitor-phase rule above.

#### Section 1: Campaigns Needing Optimisation

Campaigns where at least one variant has 800+ sent with 0 positives (or < 1 positive per 800), OR campaign-level sent/positive > 1,500. These have actionable problems right now.

```
### Campaigns Needing Optimisation
| # | Campaign | Sent | Positive | Sent/Pos |
```

#### Section 2: Performing Campaigns

Campaigns with sent/positive <= 1,500.

```
### Performing Campaigns
| # | Campaign | Sent | Positive | Sent/Pos |
```

#### Section 3: Campaign Lifecycle

Separate table. ONLY show campaigns at 40%+ completion. Two statuses:
- 40-94%: "Upload more leads"
- 95%+: "Nearing completion"

```
### Campaign Lifecycle
| Campaign | Sent | Leads | Completion | Status |
```

#### Section 4: Variant Analysis

The single home for ALL variant-level findings, covering both campaigns needing optimisation AND performing campaigns. There is no separate "Variants Needing Replacement" section: a variant recommendation is pointless without the campaign's wider context, so every variant finding lives here with that context attached.

**Completion gate:** ONLY include campaigns under 60% completion. At 60%+ the remaining audience is too small for variant changes to pay off, so omit the campaign from this section entirely (it still appears in Sections 1/2 and the Lifecycle table).

**SKIP any campaign with no actionable variant finding** (all shown variants KEEP, no clear winner/loser, no failing Email 2). Only include a campaign when there is something to do.

For each included campaign, show all active variants that have reached 800 emails sent, with their individual sent/positive data. Omit monitor-phase variants (under 800 sent). Identify:
- **REPLACE**: a variant with 800+ sent and zero positives (or < 1 positive per 800 sent).
- **Campaign-level failure rule**: if a campaign has 1,500+ sent with zero positives at campaign level, flag ALL its active variants, even those under 800, because the whole campaign is failing. When every variant is sub-800, present this at campaign level ("whole offer failing") rather than listing each tiny variant.
- **Clear winner**: a variant materially outperforming the others. Scale it, build new variants on its angle, disable the losers.
- **Clear loser**: a variant with 800+ sent and 0 positives while siblings perform. Disable.
- **Email 2**: if Email 2 has 800+ sent with 0 positives, flag it for a rewrite. If Email 2 is OUTperforming Email 1, flag the flip for the CSM.

Do NOT show disabled variants. Do NOT include campaigns whose only finding is "too close to call" or "too early across all variants."

**Every campaign block MUST carry campaign context and progress in its header**, in this exact shape (sent, positives, completion %). **Every variant table MUST include a Sent/Pos column** (emails sent per positive for that variant; lower is better). Show `∞` when the variant has 0 positives.

```
### Variant Analysis
**[Campaign Name](link)** (16,758 sent, 12 pos, 45% complete)
| Email | Variant | Sent | Positive | Sent/Pos | Angle | Recommendation |
```

If a campaign's positives came entirely from Email 2 (Email 1 variants all at 0), note that under the table.

#### Section 5: Low Reply Rate Flags

Check the reply rate for each campaign: `replied / sent * 100`. Use the `replied` and `sent` fields from `smartlead_analytics_campaign_overall_stats` (the same data source used for the campaign tables). Do NOT try to count replies from the per-lead stats endpoint - it's unreliable.

Only show campaigns where the reply rate is UNDER 1%. Campaigns at or above 1% are healthy and don't need to appear here.

A reply rate under 1% has two common root causes, and the CSM should rule out both:
1. **Wrong recipients**: the people enrolled don't match the intended ICP, so even delivered emails get ignored. Check this first.
2. **Deliverability**: emails landing in spam, poor sender reputation, domain or warmup issues.

For every campaign in this section, recommend the CSM run a **lead list audit** (`lilly-list-audit`) on the campaign to confirm the enrolled leads are actually the persona the campaign was built for. It pulls every lead, classifies each title by function, and reports how much of the list is on-ICP vs off-ICP. An off-ICP list explains a sub-1% reply rate on its own; a clean, on-target list points the finger at deliverability instead.

```
### Low Reply Rate Flags - Campaigns with reply rate under 1%
| Campaign | Sent | Unique Replies | Reply Rate |
```

Underneath the table, note the recommended next step: run `lilly-list-audit` on each flagged campaign to confirm the right people are enrolled, and check deliverability (spam placement, sender reputation, warmup) in parallel. Each flagged campaign also gets an action block in Section 7.

Place this section after the Variant Analysis and before the Variant Distribution Flags.

#### Section 6: Variant Distribution Flags

For every active qualifying campaign (1,500+ sent), check each variant for the following two bug patterns:

**Bug A — 0% distribution, 0 sends:** The variant has never received any traffic and is set to 0% distribution. This means the distribution was never configured correctly from the start. The variant was likely added but the traffic split was not set up in the UI.

**Bug B — >0% distribution, 0 sends:** The variant is set to receive traffic but has received none despite the campaign actively sending. This means the variant is broken in the UI — it appears active but sends are not being attributed to it.

**Not a bug — 0% distribution, >0 sends:** The variant was running, then intentionally turned off by setting distribution to 0%. Treat as disabled (see Formatting Rules above). Do not flag.

Only include campaigns that have at least one Bug A or Bug B variant.

```
### Variant Distribution Flags
| Campaign | Email | Variant | Distribution | Sends | Bug Type | Notes |
```

The Notes column should describe the variant's angle in plain English. Underneath the table, note the fix: go into the campaign in the Smartlead UI and manually set the correct traffic split so every intended variant has a non-zero share.

Place this section after the Low Reply Rate Flags and before the Recommended Actions.

#### Section 7: Recommended Actions

Organised **campaign by campaign** — one block per campaign that has an action. This makes Section 7 the direct input to task creation (one Notion task per block).

**Block format:**

Number each block sequentially across the entire section (1, 2, 3...), regardless of priority tier. This makes individual actions easy to reference by number.

```
**[N]. [Campaign Name](link)** — [Client] | [sent] sent, [pos] pos, [comp]% complete
[Priority: High / Medium / Low]

- [Action 1 for this campaign]
- [Action 2 for this campaign — if multiple apply]
```

**Priority rules:**
- High: 0 positives past 800+ sends per variant, kill threshold reached, both variants failing
- Medium: clear winner to scale, clear loser to disable, distribution bug to fix, reply rate under 1% (run a lead list audit + check deliverability)
- Low: lifecycle only (upload leads, nearing completion)

**Ordering:** High priority campaigns first, then Medium, then Low (lifecycle). Within each priority tier, order by sent count descending (largest campaigns first).

**Lifecycle campaigns** (upload more leads / nearing completion) still appear as blocks at the end — keep them brief, one action line each.

**Low reply rate campaigns** (Section 5, reply rate under 1%) get a block too, even with no variant-level finding. Action line: run a lead list audit (`lilly-list-audit`) to confirm the enrolled leads match the intended persona, and check deliverability (spam placement, sender reputation, warmup) in parallel.

Every campaign name must be hyperlinked. No action type grouping across campaigns.

### Report Delivery

**The cockpit artifact IS the report. Never post the 7-section report (or any section of it) in chat.** The full analysis feeds `campaign_insights` and the artifact; keep a copy of the analysis data in the session scratchpad as the run record. Chat delivery on every manual run: one short line + the clear artifact link, auto-launched with `open` (per the Cockpit contract above).

When running as an automated scheduled task, the order is:
1. Republish the artifact (skip `open` — headless) and hand over in chat with one short line + the artifact link.
2. Create the Notion page (Daily Delivery Reports database, data source ID `62792b65-eff7-42e9-8b1c-a5bf8ef39f17`) with: Reports = today's date (YYYY-MM-DD), Status = "Not action", Actioned By = blank. Page content = the full 7-section report (Notion is the archival record; chat never is).
3. Add the Notion page URL to the same short handover line.

### After the handover
Say nothing more. Do NOT append offers, questions, or next-step menus to the handover. Drill-ins (Step 2) and Notion task creation fire only when Bjion replies with a campaign name or asks for tasks.

---

## Campaign Assessment: Step 2 - Variant Drill Down

When the user selects a campaign, generate a detailed variant-level analysis.

### Data Collection
1. Call `smartlead_get_campaign_sequence` for the selected campaign.
2. Call `smartlead_get_campaign_statistics` to get per-lead send data.
3. Aggregate by `seq_variant_id`: sent, replies, positive replies, bounced.
4. Check `lead_category` for positive reply attribution.
5. Calculate Sent/Positive ratio per variant.
6. Apply the 800 threshold.

### Handling Disabled Variants
- Skip from the performance table.
- Note under "Previously Tested" so the user knows what angles were tried.

### Report Format

```
## {Campaign Name}
**Campaign ID:** {id} | **Status:** Active | **{positive} positive replies from {sent} sent**

### Variant Performance
| Email | Variant | Sent | Replies | Positive | Sent/Pos | Status |
|-------|---------|------|---------|----------|----------|--------|

### What's Currently Running
(Plain English summary of each active variant's angle)

### Previously Tested (Disabled)
(Plain English summary of disabled variants)

### Reply Breakdown
(Category counts: Not Interested, OOO, Wrong Person, etc.)

### Recommendation
(Flag REPLACE variants, note what's been tried, suggest next steps)
```

### Status Labels
- **REPLACE**: 800+ sent, < 1 positive per 800.
- **KEEP**: Performing above threshold.

### After presenting
Ask the user if they want to:
1. Draft new offers/angles for flagged variants
2. Drill into another campaign
3. Return to the priority report

---

## Drafting New Copy

NEVER draft new offers or angles unless:
1. You understand WHO the campaign is targeting (audience, industry, role).
2. You have reviewed WHAT has already been tested and failed (disabled variants + current underperformers).

If the user asks for new copy, confirm you have both pieces of context first.

---

## Phase 1 - Offer Discovery

Goal: Identify an offer angle that resonates.

1. Launch 4 offer angle variants at equal 25% distribution.
2. Each variant must reach 800 emails sent before it can be judged.
3. A variant has failed if it reaches 800 emails sent with zero positive responses.

**Decision tree after 800 emails per variant:**

- No variant has a positive: offer isn't working. Ask CSM for ICP context, ideate 4 new offer angles, repeat Phase 1. *Passive nudge: when all 4 variants fail at 800, surface `/lilly-strategy <client-slug>` in the recommendation so the CSM can ideate fresh mechanisms (not just offer angles within the same mechanism) if they want.*
- Exactly 1 variant has positives: winner found. Move to Phase 2.
- Multiple variants have positives: continue to 1,500 emails per variant. Pick winner by best emails-per-positive ratio. Tiebreak by Call Booked count. If still equal, keep both active and let calls decide.

---

## Phase 2 - Problem/Pain-Point Testing (80/20 Cycle)

Goal: Continuously improve performance by testing new problem angles.

- Incumbent: 80% distribution (current best performer)
- Challenger: 20% distribution (new problem/pain-point never tested with this offer)
- Same offer, same template. Only the problem/pain-point changes.

Run until challenger reaches 800 emails sent, then:

- Challenger fails (0 positives): disable it, create new challenger with untested problem.
- Challenger underperforms or matches incumbent: keep incumbent, disable challenger, create new challenger.
- Challenger noticeably outperforms: challenger becomes new incumbent at 80%, disable old incumbent, create new challenger.

Only test problems that haven't been tried with the current offer. Track all previously tested problems.

---

## Email 2 (Follow-Up) Analysis

Email 2 must be analysed independently. It has its own sent volume and can fail on its own merits.

- Same 800-email failure threshold applies.
- If Email 2 has 800+ sent with zero positives, the follow-up copy has failed and needs rewriting.
- Always report Email 2 performance separately in the analysis output.

**Email 2 Flip Rule:** If Email 2 is clearly outperforming Email 1:
1. Flag to CSM (unusual since Email 2 typically underperforms).
2. Recommend flipping: Email 2 offer becomes new Email 1.
3. Write fresh Email 2. If original Email 1 was hard CTA, new Email 2 is soft CTA (and vice versa).
4. Await CSM approval before executing.

---

## Response Pattern Analysis

Run every optimisation cycle when requested.

Always present a breakdown of at least 10 positive responders (or all if fewer than 10). For each include:
- Name, company/domain, job title (if available)
- Which variant and sequence step they responded to
- Response category

If more than 10 positive responders exist, show first 10 and ask: "There are X more positive responders. Would you like me to show the full list?"

Analyse:
1. Job roles of positive responders. Any consistent patterns?
2. Company types of positive responders. Any patterns in industry or size?
3. Do responders match the original campaign targeting?

If responders don't match original targeting, recommend segmenting by persona/company type and await CSM approval before creating new campaigns.

---

## Campaign Kill Threshold

If 15,000+ emails sent and overall ratio is still 2,500+ emails per positive:
1. Flag to CSM that this ICP likely isn't working.
2. Recommend a pivot (new ICP, adjusted targeting, or different channel).
3. Await CSM decision. Do not act autonomously.

In Section 7 (Recommended Actions), append a one-line passive nudge for any kill-threshold campaign: *"Consider `/lilly-strategy <client-slug>` to ideate replacement angles."* Do not auto-fire `/lilly-strategy` — the CSM invokes it manually if they want fresh ideation.

---

## Workflow (Every Optimisation Cycle)

1. Pull campaign analytics for all variants and both sequence steps.
2. Determine phase (Phase 1 or Phase 2).
3. Apply the relevant decision tree.
4. Analyse Email 2 independently.
5. Run response pattern analysis.
6. Check kill threshold if 15K+ sent.
7. Present all findings and recommendations to CSM.
8. Await approval before executing any changes.
9. Refresh the Analytics hub book insights (section below) so the page ships the run's numbers.

---

## Analytics hub book insights (messaging + who-replies)

The Analytics page (https://navreo-signals.onrender.com/app/deliverability.html —
shipped 2026-07-27, the P3 "Funnel" hub with the deliverability to-do embedded)
renders two extra BOOK-scope rows from `campaign_insights` that this skill owns:

- `insight_key='messaging'` — fleet-wide opening-lines league.
  `payload.stats.lines = [[subject_label, reply_pct, sends], …]` (top 4), plus the
  usual bold/act/note. The page's "Opening lines — what gets replies" card renders it.
- `insight_key='who-replies'` — job-title mix of the last 30 days' positive repliers.
  `payload.stats = {n, buckets: [[label, count], …]}`. The page's "Who actually
  replies?" lane renders it.

**Generation is automatic**: the daily cron (`pg_cron → POST /api/cron/pull-all`)
calls `_analytics_hub_insights_refresh()` in `app/server.py` after every pull —
mechanical aggregation from Smartlead variant counters + the reply archive, with
the standard contract (fingerprint reuse under 24h, supersede-not-stack, 7-day
`expires_at`, one live row per scope+key). The page never depends on someone
remembering to run anything.

**On a cockpit run**: force a fresh pair with
`POST /api/analytics-hub/refresh-insights` (any authed session; `{}` body), then —
if the run's analysis argues for sharper act lines than the mechanical ones —
supersede the rows with your own, same keys, same payload shape, specificity
contract applies. Never stack a second live row on either key.

## New Variant Copy Rules

1. Match existing template: same length, structure, personalisation tokens, CTA style.
2. Change only the problem/pain-point (Phase 2) or offer angle (Phase 1).
3. Use `%signature%` for sign-off. Never use `{{sender_name}}` or `{{sender_title}}`.
4. No em-dashes anywhere in copy.
5. Present draft to CSM for approval. Only publish after confirmed.

---

## Response Breakdown — On-Demand Segment Analysis

Run when the user asks for a **"response breakdown"**, **"segment analysis"**, **"who is responding to campaign X"**, or **"breakdown of positives for [campaign]"**. This produces a segment-level view of every positive responder on a given campaign so the CSM can decide which segments to double down on, spin off, or investigate.

### When to run

On-demand only, not part of the default priority report. Trigger phrases include:
- "Give me a response breakdown for [campaign]"
- "Show me the positives on [campaign]"
- "Who's responded positively to [campaign]?"
- "Segment analysis for [campaign]"

Also run automatically when the CSM is deciding whether to spin off a new campaign from an existing one, or when diagnosing why a campaign's positives aren't matching the nominal ICP.

### Why the MCP is NOT sufficient

The Smartlead MCP tools are unreliable for this task:
- `smartlead_get_campaign_statistics` caps at the 500 most-recent sends. Positives from older sends (e.g. replies that arrived days after the email was sent) are invisible.
- `smartlead_list_leads_by_campaign` paginates at 100 leads max. A 15K-lead campaign needs 153 calls.
- `smartlead_fetch_lead_message_history`, `smartlead_fetch_lead_by_email`, and `smartlead_fetch_lead_categories` all error out on every call.
- Filtering leads by `lead_category_id` in the MCP lead-list endpoint does NOT surface actual positive responders. It returns categorised leads from any source (including stale imports or auto-classifications), not master-inbox positives.

**Always use the direct Smartlead REST API for this workflow.**

### Data source

- Base URL: `https://server.smartlead.ai/api/v1`
- Auth: `?api_key={SMARTLEAD_API_KEY}` query param on every request
- API key: read from the running MCP server process env with `ps eww <pid>` (the smartlead-mcp-server process has `SMARTLEAD_API_KEY=...` in its environment). If not found there, ask the CSM.

### Workflow

1. **Confirm campaign scope.** Ask the CSM: campaign name or ID, and window (default: lifetime; alternative: last 7 days, last 30 days).
2. **Paginate stats to find positives.** Call `GET /campaigns/{id}/statistics?offset=N&limit=1000` for `N` in `[0, 1000, 2000, ..., total_stats]`. The `total_stats` field in the first response tells you how many rows to expect.
3. **Filter rows** where `lead_category` matches exactly one of: `Interested`, `Meeting Request`, `Information Request`, `Call Booked`. Use exact equality, not substring match (`Not Interested` would match `Interested` as a substring).
4. **Dedupe by email.** A lead can appear on multiple rows (one per sequence step). Keep the row with the greatest `reply_time`.
5. **Verify count matches analytics.** The deduped lifetime count must equal `positive_replied` from `smartlead_analytics_campaign_overall_stats` for the same campaign. If it doesn't, you've mis-paginated or mis-filtered — fix it before continuing.
6. **Scope to window** if requested: filter by `reply_time` within the window.
7. **Fetch lead details** per responder: `GET /leads/?email={email}`. Each record contains:
   - `first_name`, `last_name`, `email`, `id` (lead_id)
   - `company_name`, `website`
   - `location` (may be blank)
   - `linkedin_profile`
   - `custom_fields.Title` (the job title)
   - `custom_fields.Headcount` (the company size)
8. **Load the enrichment cache** at `.claude/skills/lilly-optimiser/cache/leads.json` (keyed by email). Any responder already in the cache skips web lookup.
9. **Enrich industry for new emails only.** `WebFetch` on the company's homepage, prompt: "What industry is this company in? What do they do? One short sentence and an industry classification." Fall back to `WebSearch` if the page returns no meaningful content (Wix builder junk, JS-only pages, etc.).
10. **Write back to cache.** Append new entries with `industry_source: "web"`. Always read the cache file first before writing.
11. **Build the report** (format below) and post in chat.

### Bucket mapping

Smartlead's positive categories bucket into three warmth tiers for segment analysis:

| Smartlead category | Bucket for this report |
|---|---|
| Interested | Interested (positive) |
| Information Request | Interested (positive) |
| Meeting Request | Warmer |
| Call Booked | Warmest |

### Asterisk convention

Any field sourced via `WebFetch`/`WebSearch` (rather than Smartlead) gets a trailing `*` in the report. This applies to:
- `industry` — always web-sourced (Smartlead doesn't store it)
- `size_band` / `headcount` — only web-sourced when the lead's `custom_fields.Headcount` is blank
- `location` — only web-sourced when the lead's `location` is blank

### Report structure

```
# Response Breakdown — {Campaign Name}

**Campaign:** [link]
**Window:** {lifetime | last X days}
**Positives:** N (matches Smartlead positive_replied: N)
**Legend:** * = field from web lookup

## The N responders (most recent first)

| # | Bucket | Name | Title | Company | Industry | Size | Geography | Replied | Thread |

## Segment breakdown

### By industry
(Table with counts and named responders per segment)

### By bucket × industry
(Cross-tab showing which segments drive the warmest responses)

### By title cluster
(VP+ / Director / Other)

### By company size
(Headcount bands)

### By geography
(Regions)

## Recommendations
(Numbered, action-oriented: spin off sub-campaigns, refine ICP, backfill missing data)

## Data lineage
(Endpoints used, filters applied, cache hits/misses)
```

### Guardrails for this workflow

- **Do not invent leads.** Every responder in the report must come from the paginated `/campaigns/{id}/statistics` response and be resolvable via `/leads/?email=X`. If the sanity check at step 5 fails, stop and flag the discrepancy to the CSM rather than proceeding with partial data.
- **Always include thread links.** Format: `https://app.smartlead.ai/app/master-inbox/{campaign_id}?lead_id={lead_id}`. If the CSM reports this URL pattern doesn't work in their account, ask once and update the cache / skill to the correct format.
- **Mark web-sourced fields.** Never present web-enriched data as if it came from Smartlead.
- **Cache industry enrichments.** A daily rerun should only web-fetch emails that weren't already in the cache. `_meta.last_updated` gets bumped on every write.
- **Never delete or overwrite the cache wholesale** without explicit CSM approval. Append / merge only.

### After the report

Ask the CSM:
1. Does any segment warrant a dedicated sub-campaign? If yes, offer to draft a Notion task in the Client Tasks database with the ICP definition and source strategy.
2. Does any segment suggest a copy / offer adjustment on the existing campaign?
3. Is there a blank-location or blank-headcount problem that warrants a one-time enrichment pass on the source list?

---

## Task Creation — Post-Report (Priority Report only)

Only when Bjion asks for tasks (the handover carries no offers). When he does, confirm scope and due date with:

> "Also — want me to create Notion tasks for the [N] actionable items in Section 7? Each task gets: campaign stats, client context, every angle tried so far, the recommendation, and a pre-made Claude Code prompt you can paste in to immediately draft new copy or action the fix. Due date default is [today + 2 working days, e.g. 2026-06-04] — say a different date if you want one."

If the CSM confirms (or gives a different date), create one Notion task per Section 7 action item. This includes lifecycle items (Upload more leads, Nearing completion) — every task gets the full 5-section body regardless of action type.

### What counts as a task-worthy action

Create a task for every Section 7 action item, including:
- Replace failing variants (REPLACE recommendation)
- Scale winner / disable loser
- Fix distribution bug
- Run a lead list audit (reply rate under 1%, verify the right people are enrolled)
- Kill threshold campaigns (mechanism pivot needed)
- Replace or reconsider a mechanism entirely
- Upload more leads (lifecycle — performing campaigns running low)
- Nearing completion (lifecycle — decision needed on closing or refilling)

All tasks get the full 5-section body. The only difference is Section 5:
- Copy/config/strategy tasks: Section 5 is a pre-made Claude Code prompt (see template below)
- Upload/lifecycle tasks: Section 5 is lead-source and upload context instead (what signal/audience to source from, required custom variables, upload instructions)
- Lead list audit tasks: Section 5 is a `/lilly-list-audit` prompt with the campaign id and the intended persona/ICP to check the enrolled leads against (e.g. `/lilly-list-audit` then "Audit campaign {id}; intended ICP is {persona + vertical + size}; report on-ICP vs off-ICP and flag what's leaking").

### Task title format

`[Action verb] - [Short campaign name] ({campaign_id})` — max 80 chars, no em-dashes.

The campaign ID must always appear at the end of the title in parentheses. This lets anyone open the campaign directly from the task name without navigating to the body.

Examples:
- `Replace Email 1 variants - Arnic SaaS Sales Leaders 50-1K (3396124)`
- `Scale winner to 80% - SEO & GEO Agencies Email 1 (3317530)`
- `Disable losers + add challenger - Exporters Recontact May (3278906)`
- `Fix distribution bug - Navreo CEO Clay Email 1 (3285033)`
- `Kill threshold pivot - New Reconnect Navreo SaaS Hard (3324615)`

### Client mapping (infer from campaign name)

| Campaign name contains | Client tag |
|---|---|
| "Arnic" | Arnic |
| "Amplifyy" | Amplifyy |
| "Navreo" (no other client keyword) | Navreo |
| "Alpine" or "Property Management" | Navreo (secondary) |
| "Olivia Duncan" | Olivia Duncan |
| "PestCo" | PestCo |
| "Corporate Development" / "Valsoft" | Valsoft |

### Notion task body (5 sections)

Create each task as a Notion page in the Client Tasks database (`data_source_id = 2776e755-98d9-806a-88af-000b091e215e`). Set `Status = "Not started"` and `Priority` based on urgency:
- High: kill threshold campaigns, both-variants-failing (REPLACE all)
- Medium: scale winner, disable loser, distribution bug, lead list audit (reply rate under 1%)
- Low: monitor-phase items

Write the page body in Notion markdown with these 5 sections:

---

**1. Campaign Context**

```
Campaign: [Name] ([link])
Client: [Client name]
Date: [today]
Sent: [X,XXX] | Positives: [N] | Ratio: [X,XXX] | Completion: [XX]%
Target: [infer from campaign name — e.g. "SaaS Sales Leaders (Director+) at 51-200 employee SaaS companies"]
```

---

**2. Client Context**

Pull from the table below. Write 3-5 bullet points covering: what the client does, who they target, their offer, and any hard constraints.

| Client | Key context |
|---|---|
| Navreo | Done-for-you outbound pipeline building on pay-per-lead. ICP: VP/Head/Director Sales at software dev agencies, AI transformation firms, digital transformation firms, 51-200 employees. Template: icebreaker + GTM noise + personalised video CTA + pay-per-lead or guarantee. |
| Arnic | Sales enablement content and onboarding systems for SaaS sales teams. Best persona: Heads of Sales at 100-200 employee SaaS companies. Always say "sales onboarding" / "sales content" explicitly. Case study = GitLab + Meta together with all numbers in every mention. Renewal urgency as of May 2026. |
| Amplifyy | Amazon brand growth agency (DFY Amazon channel management). ICP: companies already selling on Amazon. Never say "commission" — always "performance basis". Never stack lead magnet + gift card in same email. Persona pivoted to Head of E-commerce. |
| Alpine / Navreo secondary | Property management vertical. Limited context — note this in the task. |
| Olivia Duncan | Interior design vertical. High-performing campaign (ratio ~234). |

---

**3. What's been tried**

Split into two sub-sections:

**3a. Across all [Client] campaigns:**

Pull all variants that have run in OTHER campaigns for the same client (use the session's analytics and seq_cache). For each other client campaign, list:
- Campaign name + link + overall stats (sent, pos, ratio)
- Each Email 1 variant: angle in plain English, sent, pos — or "too early (under 800 sends)" if not yet conclusive
- Flag with **CROSS-CAMPAIGN FLAG** if any angle in another campaign is the same as (or very similar to) an angle currently running or being recommended in THIS campaign

Note: skip Navreo-branded campaigns that used Navreo's own outbound copy on Navreo's behalf (e.g. "Navreo - Arnic List" campaigns). Those are Navreo prospecting campaigns, not the client's campaigns.

**3b. In this campaign ([Campaign Name]):**

List every variant that has run in THIS campaign, including disabled/0%-distribution ones.

Format:
```
Email 1:
- Var A ([X] sent, [N] pos): [angle in plain English — 1 sentence]
- Var B ([X] sent, [N] pos): [angle] [DISABLED] if is_deleted=true or 0% distribution
...

Email 2:
- Var A ([X] sent, [N] pos): [angle]
...

Pattern: [1-2 sentences on what the failing angles have in common — e.g. "Both Email 1 variants framed the problem as a rep adoption issue. Neither landed."]
```

For kill-threshold campaigns, also note the mechanism: "The current mechanism across this campaign is [X — e.g. personalised video + GTM noise]. This has been running at [X,XXX] sends/positive for [N,NNN] sends total."

---

**4. Recommendation**

Copy the exact recommended action from Section 7, verbatim. Then add the constraint reminder:

> Reminder: NEVER use any sequence API tool to modify existing campaigns. All copy changes go via the Smartlead UI — draft copy here, CSM pastes it in manually.

---

**5. Pre-made Claude Code prompt (copy/config/strategy tasks) OR Lead upload context (lifecycle tasks)**

**For copy, config, and strategy tasks:** Write a complete, self-contained Claude Code briefing — structured data written for Claude to consume, not prose for the CSM to read. The CSM pastes it into a fresh Claude Code session and Claude immediately has everything it needs to action the recommendation without back-and-forth.

**For upload/lifecycle tasks:** Replace the Claude Code prompt with a lead-source and upload context block covering: (1) what signal or audience to source new leads from, (2) which list-building skill to use, (3) any required custom variables that must be populated before upload (e.g. `{{Tool}}`, `{{CaseStudy}}`), and (4) any configuration checks needed in the Smartlead UI before uploading (e.g. distribution settings, variant status).

The prompt must be in a code block. It must include all context from sections 1-4 so it stands alone. Write it as labelled fields and structured lists, not narrative paragraphs.

**MANDATORY — no-build scope line (every Section 5 block, every task type).** The pasted Claude Code session is only ever for pulling data, mapping the TAM, and drafting copy or angles. It must never build or change anything live; the actual build is handed to someone else (the GTME). Begin every Section 5 block — the copy/config/strategy prompt, the upload/lifecycle context block, and the lead-list-audit prompt alike — with this exact constraint, placed immediately after the opening skill line and before anything else:

> SCOPE - DATA AND DRAFTING ONLY, DO NOT BUILD:
> This task is for pulling data, mapping the TAM, and drafting copy or angles only. Do NOT build or change anything live: no creating or editing campaigns, no pushing or enriching leads, no uploading or moving lists, no touching sequences, variants, or automations. The actual build is assigned to someone else (the GTME). Produce the draft, data, or TAM map ready to hand off, then stop.

**Template (adapt per action type):**

```
/lilly-copywriter

SCOPE - DATA AND DRAFTING ONLY, DO NOT BUILD:
This task is for pulling data, mapping the TAM, and drafting copy or angles only. Do NOT build or change anything live: no creating or editing campaigns, no pushing or enriching leads, no uploading or moving lists, no touching sequences, variants, or automations. The actual build is assigned to someone else (the GTME). Produce the draft, data, or TAM map ready to hand off, then stop.

BRIEFING: [action type — e.g. "replace both failing Email 1 variants"]

CLIENT: [name]
OFFER: [one-line description of what the client does / sells]
PERSONA: [role + vertical + size. Best converting: X-Y employees.]

ACTIVE CAMPAIGN: [name]
URL: [https://app.smartlead.ai/app/email-campaign/{id}/analytics]
STATUS: [X,XXX sent, N positives, XX% complete. Campaign-level failure / Ratio X,XXX.]

FAILED VARIANTS (Email 1, cleared 800+ sends):
- Var A ([X] sent, N pos): [angle in one sentence]
- Var B ([X] sent, N pos): [angle in one sentence]

[DISABLED VARIANTS (tested, turned off):]
[- Var X ([X] sent, N pos): [angle] [DISABLED]]

[CROSS-CAMPAIGN FLAG: If any angle in this campaign is also running in another campaign for the same client, flag it here with the other campaign's name, ID, and current stats. Example: "Var B above (adoption 1-pager) is also live as Var E in [Campaign Name] (ID XXXXXXX, [X] sent). Monitor closely — this angle has already failed at scale."]

BANNED ANGLES — confirmed non-resonant with this persona:
- [angle / framing that has failed — one line each]
- [...]

CLIENT COPY RULES — non-negotiable:
1. [Rule 1]
2. [Rule 2]
[... pull from client context table]

TEMPLATE FORMAT — must match exactly:
- Open with [{{Icebreaker}} / {{ArnicIcebreaker}} / etc.]
- Body length: [short — under 100 words / standard]
- CTA: [hard call / video send / soft CTA]
- Sign-off: %signature%
- No em-dashes anywhere

TASK:
[REPLACE: "Draft [N] new Email 1 variants. Each must use a completely different core pain point from the failed angles above. Match the template format exactly. Name the [client's] function explicitly ([e.g. 'sales onboarding', 'sales content'])."]

[SCALE: "Email 1 Variant [X] is the winner at [ratio] sends/positive. Draft 1 new challenger variant at 20% distribution. Different problem angle from anything tried. Same template."]

[DISABLE + CHALLENGER: "Variants [A, B] need disabling (2x worse ratio than C/D). Variants [C, D] are joint winners running 50/50. Draft 1 new challenger at 20% — different angle from anything tried."]

[KILL THRESHOLD: "This campaign has hit the kill threshold ([X,XXX]+ sends, ratio [X,XXX]). The current mechanism — [describe it] — isn't converting. Ideate 3-5 fresh mechanisms for [ICP]: different hook, offer framing, signal, or CTA style. Not just new variants of the same angle."]
```

### Creating the tasks

Use `notion-create-pages` with `data_source_id = 2776e755-98d9-806a-88af-000b091e215e`. Required properties:

```json
{
  "Name": "[task title]",
  "Client ": "[client name — trailing space in property key]",
  "Status": "Not started",
  "Priority": "[High / Medium / Low]",
  "date:Due Date:start": "[YYYY-MM-DD]",
  "date:Due Date:is_datetime": 0
}
```

Put the full 5-section body in `content`. The pre-made prompt MUST be in a triple-backtick code block so it's easy to copy.

If multiple tasks share the same client and due date, batch them in a single `notion-create-pages` call (it accepts an array).

After creating, confirm: task count, client tags, due date, and each Notion URL.
