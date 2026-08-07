# Acting on the audit (removing / restoring leads)

This skill is **read-only by design**. It tells you what is in a campaign; it does not change it.
Pruning a live campaign's leads is destructive and easy to get wrong, so it is kept as a separate,
deliberate decision rather than an automated phase.

If you do decide to remove off-ICP leads, the rules below are the ones learned the hard way in
production. Treat them as mandatory. (If Navreo later wants this automated, build it from here.)

## Before you remove anything

- **Confirm scope with the user in literal terms.** "Remove the off-ICP leads" is ambiguous: the
  off-ICP set includes the `OTHER-LEADERSHIP` bucket (bare Director / Partner / Growth titles) that
  may contain real owners or sales leaders with truncated titles. Split confidently-wrong functions
  (Creative, Marketing, Account, Ops, Tech, HR, Finance, Legal) from the ambiguous bucket and let
  the user pick which to remove.
- **Back up FULL records first.** Export every to-be-removed lead with ALL fields, including
  `custom_fields` (Icebreaker, Why, CaseStudy, Title, etc.). Deletion is only recoverable from this
  backup, and a plain re-add WITHOUT the custom fields silently loses all personalization.
- **Reply-guard.** Never remove a lead that has engaged. Skip any lead whose `lead_category_id` is
  set (Interested, Info Request, OOO, etc.), so no live conversation is cut.

## Removing (DELETE)

- Endpoint: `DELETE /campaigns/{campaign_id}/leads/{lead_id}` (returns HTTP 200 `success`). The id is
  the global lead id (`lead.id`).
- **Test-delete ONE lead first** and confirm `total_leads` dropped by exactly 1 before any bulk run.
- **Pagination races:** do NOT pull the campaign for analysis while a bulk delete is running on it.
  As leads are removed, offsets shift and you will skip or double-read leads. Dedupe by lead id, and
  re-pull cleanly AFTER the delete finishes to verify.
- Expect a few percent of deletes to fail on the shared 200/min rate limit. Do not trust the live
  counters; recompute failures by re-pulling and intersecting the intended-set against what is still
  present, then retry those at lower concurrency.

## Restoring (ADD) and its two silent traps

- Endpoint: `POST /campaigns/{campaign_id}/leads` with `{ "lead_list": [...], "settings": {...} }`,
  max 100 leads per call, custom_fields reattached from the backup.
- **Trap 1, async upload:** the response `upload_count` is "accepted", not "landed". The campaign
  total often does not move immediately and the response may show `total_leads: 0`. NEVER trust the
  response alone. Verify a restore by re-pulling the campaign and checking the emails are actually
  present.
- **Trap 2, the dedup flag is reversed from intuition:** `ignore_duplicate_leads_in_other_campaign:
  true` means "SKIP any lead that already exists in another campaign". Navreo leads frequently live
  in several campaigns at once, so `true` silently skips them and nothing restores. Set it to
  **`false`** to actually re-add a lead that exists elsewhere.

## Verify, always

After any mutation, the source of truth is a fresh re-pull (lead count and email-presence), not the
API's success payload. This skill's `audit_campaign.py` re-pull logic is a fine way to verify.
