---
name: lilly-phone-finder
description: Find a verified MOBILE PHONE NUMBER for a CSV / list of people using a waterfall — BetterContact first (batched, up to 100 contacts per call), Prospeo as the fallback only for rows BetterContact misses. Takes a list with names + company/domain (and optionally LinkedIn / email), returns the same rows with a mobile, which provider found it, and the status. Use this skill whenever the user wants phone numbers for a list of people, wants to enrich leads with mobiles before a calling / SMS follow-up, wants to add phone numbers to a prospect or decision-maker CSV, or as the natural hand-off after lilly-tam / lilly-email-verification when they also want phones. Trigger phrases: 'find phone numbers for this list', 'get mobiles for these people', 'enrich this CSV with phone numbers', 'add phones to these leads', 'phone-enrich this list', 'BetterContact these', 'find their mobile / cell / direct dial', 'get me numbers for the decision makers'. BetterContact is always tried before Prospeo (the waterfall the user asked for). Never used for email finding (that is lilly-email-verification) — this is phones only.
---

# Lilly Phone Finder — verified mobiles via a BetterContact → Prospeo waterfall

Give it a CSV / list of people; it returns the same rows with a **verified mobile number**, found via a two-stage waterfall:

| Stage | Provider | When | Needs |
| --- | --- | --- | --- |
| 1 | **BetterContact** (always first) | every row | first + last name + (company **or** domain); LinkedIn helps |
| 2 | **Prospeo** (fallback) | only rows Stage 1 missed | a LinkedIn URL **or** an email |

BetterContact runs **batched** (up to 100 people per request, then polls until done), so a big list is a handful of API calls, not one-per-person. Only the people BetterContact could not find a number for fall through to Prospeo.

## Inputs
A CSV (or any list you can drop into a CSV) with, per person:
- **Name** — either `first_name` + `last_name`, or a single `name` column (auto-split).
- **Company** — a company name and/or a domain/website. BetterContact needs at least one.
- *(optional, improves hit rate)* **LinkedIn URL** and/or **Email**. Prospeo's fallback needs one of these, so rows with neither can only be served by BetterContact.

Column headers are matched case-insensitively with common aliases (e.g. `Company`, `company_name`, `organization` all map to company; `Website`, `domain`, `url` all map to domain; `LinkedIn URL`, `linkedin_profile` map to linkedin). You do **not** need to rename columns first.

## How to run
```bash
set -a; source ~/.navreo-keys.env; set +a
python3 ~/.claude/skills/lilly-phone-finder/scripts/find_phones.py <input.csv> [output.csv] [--no-prospeo]
```
- `output.csv` defaults to `<input>_phones.csv`.
- `--no-prospeo` runs BetterContact only (skip the fallback).

The output keeps every original column and adds three:
- **`mobile`** — the verified number (blank if none found).
- **`mobile_source`** — `BetterContact` or `Prospeo` (which stage found it).
- **`mobile_status`** — provider status (`valid` from BetterContact, `VERIFIED` from Prospeo).

The script prints a summary: how many numbers were found, the split between the two providers, and BetterContact credits consumed / remaining.

## Cost — confirm before a big run
BetterContact charges **per number found**, and phone enrichment is its premium data point: in testing it cost **~10 credits per mobile found** (no charge for a miss). At that rate the account's 20k credits is roughly 2,000 numbers.

So, before running a large list:
1. **Tell the user the rough max spend** (rows × ~10 credits) and get a go-ahead — this is a real, metered spend.
2. **Run a small sample first** (e.g. `head -n 20 list.csv > sample.csv`) to check the hit rate on their data before committing the full list.
3. `GET https://app.bettercontact.rocks/api/v2/account` (`X-API-Key`) returns `credits_left` at any time if you want to check the balance first.

## Communication style
Talk in plain English. Say "find mobile numbers", "how many we found", "credits used" — not "enrich", "waterfall stage", "API call", "hit rate". Lead with the result (X of Y people got a number), then where they came from, then the cost.

## Hand-offs
- Natural follow-on from **`lilly-tam`** (which outputs a CSV of decision makers with email + LinkedIn) when the user also wants phones — feed that CSV straight in.
- Pairs with **`lilly-email-verification`** (emails) — that skill does emails, this one does phones; run whichever the user needs, or both on the same list.
- For ongoing positive-reply phone lookups the same waterfall is wired inline into **`lilly-positive-reply-setup`** (`scripts/route_responses.py`); this skill is the standalone, list-driven version.

## Reference
- BetterContact: base `https://app.bettercontact.rocks/api/v2`, auth header `X-API-Key`. Async: `POST /async` with `{data:[…], enrich_email_address:false, enrich_phone_number:true}` returns a `request_id`; poll `GET /async/{request_id}` until `status:"terminated"`. Phone is `data[].contact_phone_number` (+ `contact_phone_number_status`, `contact_phone_number_cc`). Input `custom_fields.uuid` is echoed back per row, so batch results map cleanly to input rows. Up to 100 contacts per call. Account/credits: `GET /account`.
- Prospeo: `POST https://api.prospeo.io/enrich-person`, auth header `X-KEY`, body `{enrich_mobile:true, data:{linkedin_url|email: <value>}}`; verified number at `person.mobile.mobile` when `person.mobile.status == "VERIFIED"`.
- Keys: `BETTERCONTACT_API_KEY`, `PROSPEO_API_KEY` from `~/.navreo-keys.env`.

## Gotchas
- BetterContact needs a real first **and** last name plus a company — a row with only an email/LinkedIn skips Stage 1 and relies on Prospeo.
- The `Bash` tool does not source `~/.zshrc`, so always prepend `set -a; source ~/.navreo-keys.env; set +a` to load the keys.
- Phones only. This skill never finds or verifies emails — that is `lilly-email-verification`.
- Don't silently run a huge list — the per-number cost is real; confirm spend first.
