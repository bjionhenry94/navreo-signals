---
name: smooth-campaign-launch
description: "One-command launcher for Navreo campaigns, built after the 27 Jul 2026 session logged 23 failures in a single launch day. Takes one sentence of targeting and delivers loaded, verified, honestly named DRAFTED campaigns with at most three touches from the user (approve the card, approve the price, receive the links). Bakes in the validated provider contract (Prospeo growth filter needs timeframe_month, custom headcount ranges, masked-email reveal shape, Smartlead duplicate truncation fix, sequence-save field asymmetries, ListMint flow, exact-count list banking) so no call shape is ever guessed again. Use whenever the user wants to launch, build, or load a signal or targeted-list campaign: 'launch a campaign', 'build a campaign from [audience]', 'smooth launch', '/smooth-campaign-launch'. Never sends email; campaigns always end DRAFTED."
---

# Smooth Campaign Launch

## LOOP TRAINING MODE: **OFF**    ← flip this line to ON to pause at every step (Bjion, 2026-07-27)

- **ON:** pause at EVERY numbered step below, show the result, wait for approval before
  continuing. Skip any step that already passes its done-rule. Re-run only steps that
  fail. Maximum 2 retries per step, then stop and report the gap.
- **OFF:** run with no pauses, but keep every done-rule check, the 2-retry cap, and
  both hard gates below.

## Hard gates (apply in BOTH modes, cannot be flipped off)

1. **Price gate.** Not one credit is spent until the user approves one price line.
2. **Send gate.** Campaigns are built DRAFTED and stay DRAFTED. This skill never
   launches sending, ever. Launching is the user's hand on the Smartlead button.

## Goal

One sentence of targeting in, working links to loaded, verified, honestly named
DRAFTED campaigns out, with less than five minutes of the user's attention and zero
surprise numbers.

## The three touches (all the user ever sees when Training Mode is OFF)

1. **The Card.** The audience in plain words, the type (SIGNAL or FIXED LIST), the
   size and title tiers, and which campaign the copy comes from. Approve or edit.
2. **The Price.** One line: "X credits buys about Y sendable people. Z credits left
   after." Approve or resize.
3. **The Handover.** Campaign links, what was spent, what refreshes and what does
   not, what to do next. Always ends with one line reminding the user that Loop
   Training Mode is ON and can be flipped OFF at the top of this file once they
   trust the run.

Everything below is machinery between those touches.

---

## The steps

| # | Step | Done-rule (checked before moving on) |
|---|------|--------------------------------------|
| 1 | **Card.** DRAFT the whole card FROM the user's sentence, filling every field yourself (type = SIGNAL or FIXED LIST, verticals, geo, size+title tiers, extra filters, copy-source campaign, Navreo-own only, how many campaigns) from memory, the client profile, and history. The user never fills a form: they read the card and say yes or edit. | Card approved (ON) or complete and self-consistent (OFF). The type on this card names everything downstream. |
| 2 | **Probe.** 1-credit page-1 probes for each query. Any filter not yet in the contract below gets a differential check: same base, extreme threshold, count must move. | Every count is probe-confirmed and every filter demonstrably bites. |
| 3 | **Price.** Compute sendable from real rules (people not companies; suppression = past positives and do-not-contact only; email availability read from the probe sample) and present ONE line. **HARD GATE.** | User approved the spend. If a later measurement moves the price more than 10%, come back to this gate. |
| 4 | **Pull and bank.** Single worker, ~1 second per page, resumable, rate-limit matched on substring. Then push the full-fidelity list to the Lists tool. | Tool count (count=exact header, never max row number) equals the deduped pull exactly, and one row spot-renders with name, title, company, email. |
| 5 | **Clean.** Dedupe by person. Count every row, no sample extrapolations. Subtract only named things: past positives, do-not-contact, no-email-possible, already-in-this-campaign. | One table from **found** to **sendable**, every subtraction named, all counted on real rows. |
| 6 | **Reveal and verify.** Reveal masked emails ONLY for rows that will be uploaded. ListMint the results, keep `valid` and `catch_all_valid`, drop the rest. | Every row headed for upload has a verified address. Reveal and pass rates reported as two numbers. |
| 7 | **Build.** Duplicate the copy-source campaign, then RE-SAVE its full sequence from source (the duplicate endpoint silently truncates variants). Rename honestly: the Card's type appears in the name. Confirm DRAFTED. | Variant counts equal the source, step for step. Name says FIXED LIST or SIGNAL truthfully. Status is DRAFTED. |
| 8 | **Load.** One test lead first, verify it landed, then batches with duplicate-blocking ON. Fill icebreakers (skip_angles per house rule when the source is a signal). Run the upload gate; verdict in chat. | Gate passes, Smartlead lead count equals expected minus its own blocks, no merge field left empty. |
| 9 | **Handover.** Closing card: links, spend, credits left, and the refresh story (FIXED LIST: burns down, re-pull when dry. SIGNAL: refresh cadence). Fix the source records in the tool to match (no Live toggle on a fixed list). Update the board once, from this session only. | User holds working links and every surface (campaign name, board, list, source record) tells the same story. |

## One-number language (non-negotiable)

Only two numbers are ever shown to the user: **found** and **sendable**. Everything
between them is a named subtraction in one table. "Duplicate" means same email
address, nothing else. A number from a sample always carries the word *estimate*,
and no estimate survives once real rows exist.

## Honest naming (non-negotiable)

**FIXED LIST** = pulled once, burns down, never refills itself.
**SIGNAL** = an event feed (job posts, engagement) that refreshes on a cadence.
The Card's type sets the campaign name, the board vector, and the source record.
A pulled list is never called a signal, anywhere, including inside the tool.

## One driver (non-negotiable)

This run owns its campaigns, its list, and its board update. If another session is
touching the same surfaces, stop and ask the user which session drives. Never
merge-war a shared artifact, and never run two copies of a write step at once.

---

## Provider contract (validated live 2026-07-27, trust it, never re-derive)

**Prospeo /search-person**
- `company_headcount_growth` REQUIRES `timeframe_month`:
  `{"timeframe_month": 6, "min": 1, "max": null}`. Without it the filter silently
  does nothing and you get the unfiltered pool.
- `company_headcount_custom` `{"min": 5, "max": 20}` gives exact staff ranges.
- `company_type.business_model` takes an ARRAY: `["b2b","b2b2c"]`.
- `company_keywords.exclude` requires an include list. Standalone exclusion goes
  through `company_industry.exclude` ("Staffing and Recruiting", "Human Resources
  Services", "Executive Search Services"; ampersand spellings are invalid).
- Filter NAMES validate loudly, inner SHAPES fail silently. Differential-probe any
  new filter before trusting it. Batch enum errors name only the FIRST invalid
  value, so validate enum values one at a time.
- Search returns emails MASKED. Revealing costs 1 credit each via
  `/bulk-enrich-person`: `{"only_verified_email": true, "data":
  [{"identifier": "<your own label>", "linkedin_url": "<url>"}]}`. `identifier` is
  YOUR tracking string, not the lookup key.
- Rate limits: ONE worker, about 1 second per page. The error is the literal string
  "Rate limit exceeded"; match substrings, back off, resume from disk.
- `INVALID_FILTERS` and `NO_RESULTS` responses are free; use them for shape checks.

**Smartlead**
- `POST /campaigns/{id}/duplicate` works but TRUNCATES step variants. Always
  re-save the sequence from source after duplicating, then verify counts.
- Sequence WRITE shape differs from read: `seq_variants` (not `sequence_variants`),
  `seq_delay_details.delay_in_days` (not `delayInDays`), and
  `variant_distribution_type` is required.
- Leads: only email, first_name, last_name, phone_number top-level; the rest in
  `custom_fields` (key `company_name`, not `company`). Always 1 test lead first.
  `ignore_duplicate_leads_in_other_campaign: false` blocks cross-campaign dupes.
- Client campaigns (ValSoft, Arnic, Amplifyy, Byteplus, INSEAD, Olivia Duncan,
  ThunderBird, Qwintiq) are NEVER copy sources or benchmarks for Navreo. Navreo-own
  campaigns carry the `Navreo |` prefix.
- The API rate-limits bursts; pace calls and back off on non-JSON responses.

**ListMint**
- `POST https://api.listmint.io/api/verify-emails?return=true&api-key=<key>`
  (query-param auth), body `{"emails": [...]}`. Keep `valid` and
  `catch_all_valid`. Occasional 502s: retry with backoff, resume from disk.

**Lists tool (Supabase)**
- Insert in batches of at most 150, payload passed as a FILE (argv has a length
  limit). Verify with `Prefer: count=exact`, never max(row_num). Before any
  re-insert, DELETE in chunks and confirm the count is 0, or you will double the
  list. One writer at a time.

## Failure protocol

Two retries per step with backoff, then STOP and report FAILED with the exact gap
and what it would take to close it. Never continue past a failed done-rule. Never
re-run a passing step. Never let two copies of a write step run concurrently.

## Done-rule for the whole run

The user holds working links to DRAFTED campaigns whose names, lead counts, list
records, source records, and board cards all say the same thing, plus one line of
spend and one line of what refreshes. Nothing has sent.
