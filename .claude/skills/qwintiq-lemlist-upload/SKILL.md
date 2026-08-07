---
name: qwintiq-lemlist-upload
description: "Upload prospects to a Lemlist campaign end-to-end via the REST API. The multichannel (email + LinkedIn) replacement for the retired qwintiq-heyreach-upload. Use whenever you want to: push leads/prospects to a Lemlist campaign, import a list into Lemlist straight from Claude Code, add prospects found by any list-building process to a named campaign, send a list to email + LinkedIn outreach, or trial a small batch before a full upload. Also the hand-off destination from qwintiq-list-building once a list is built and enriched, and pairs with qwintiq-copywriter for the sequence copy and qwintiq-icebreaker for the per-lead icebreaker (run qwintiq-icebreaker to fill {{icebreaker}} on every lead BEFORE uploading). Trigger phrases: 'upload to Lemlist', 'push these to Lemlist', 'import leads into Lemlist', 'add prospects to the Lemlist campaign', 'send these to the campaign', 'upload my list to Lemlist', 'load the list into Lemlist'."
---

# Qwintiq Lemlist Upload

## Purpose

Push prospects into a Lemlist campaign directly from Claude Code via the Lemlist REST API: look up the target campaign by name, add each prospect as a lead (email and/or LinkedIn URL) with personalisation fields filled in (the `{{icebreaker}}` plus any custom variables), and verify they landed.

This **replaces `qwintiq-heyreach-upload`** now that Qwintiq sends **multichannel (email + LinkedIn)** through Lemlist instead of LinkedIn-only through HeyReach.

Pipeline: `qwintiq-list-building` builds and enriches the list → `qwintiq-copywriter` writes the sequence copy → `qwintiq-icebreaker` fills the per-lead `{{icebreaker}}` on every lead → **this skill** uploads the leads into the chosen Lemlist campaign. General flow: identify campaign → prepare leads (icebreakers filled) → confirm → trial → push → verify.

> Behaviour below was **verified live against the Qwintiq Lemlist account on 2026-06-17.**

---

## When to use

Trigger whenever you want to:

- Push a CSV / lead list / in-memory list of prospects into a Lemlist campaign
- Import the output of any list-building process (`qwintiq-list-building`, `qwintiq-signals`, a CSV) into a named campaign
- Add prospects with custom personalisation fields (icebreaker etc.)
- Trial a small batch before pushing the whole list

Also the **hand-off destination** when `qwintiq-list-building` finishes a list (built + enriched with emails and/or LinkedIn URLs) and the user wants those prospects in a campaign.

---

## API setup

**Base URL:** `https://api.lemlist.com/api`
**Auth:** HTTP **Basic** auth. Username **empty**, password = API key. The leading colon is non-negotiable.
- curl: `--user ":$LEMLIST_API_KEY"`
- header form: `Authorization: Basic <base64 of ":" + API_KEY>`
- **NOT bearer.**

> ⚠️ **CLOUDFLARE GOTCHA (will burn you):** Lemlist is behind Cloudflare, which **blocks the default Python/urllib user-agent** → you get `HTTP 403, body "error code: 1010"`. This is NOT an auth failure. **Always send a browser `User-Agent` header** (e.g. `Mozilla/5.0 ... Chrome/124.0 Safari/537.36`). With a real UA the same call returns 200.

**Key location:** `~/.navreo-keys.env` as `LEMLIST_API_KEY` (read via `set -a; source ~/.navreo-keys.env; set +a` so it's exported to subprocesses, or `os.environ`).

**Get the key:** the shared Qwintiq key is documented in the **Connecting Your Tools** portal doc; each team member adds it to their own `~/.navreo-keys.env` as `LEMLIST_API_KEY`. (To rotate: Lemlist → Settings → Integrations → Generate a new API key, then update the portal doc + env files.)

**Verify auth (always start here):**

```python
import base64, json, os, ssl, urllib.request
ctx = ssl._create_unverified_context()
key = os.environ["LEMLIST_API_KEY"]
auth = base64.b64encode(f":{key}".encode()).decode()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
req = urllib.request.Request(
    "https://api.lemlist.com/api/campaigns?limit=100&offset=0",
    headers={"Authorization": f"Basic {auth}", "User-Agent": UA, "Accept": "application/json"},
)
with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
    print([(c["_id"], c["name"], c.get("status")) for c in json.loads(r.read())])
```

---

## Endpoints reference (all verified)

| Action | Method | Path | Notes |
|---|---|---|---|
| List campaigns | GET | `/campaigns?limit=&offset=` | Returns array of `{_id, name, status}`. Map a **name → `cam_…` id** here. |
| **Add lead to campaign** | POST | `/campaigns/{campaignId}/leads/` | JSON body (below). Works on **draft** campaigns too (won't send until launched). Returns the created lead, echoing every field incl. custom vars, plus `_id`, `contactId`, `isPaused`. Query: `deduplicate`, `verifyEmail`, `findEmail`, `findPhone`, `linkedinEnrichment`. |
| List leads in a campaign | GET | `/campaigns/{campaignId}/leads` | Returns `[{_id, state, contactId}]` — **ids + state only**, not full fields. |
| Export leads (full fields) | GET | `/campaigns/{campaignId}/export/leads` | CSV. The **header row reveals the campaign's custom-variable columns** — handy to confirm which `{{vars}}` the copy expects. |
| Update a lead | PATCH | `/campaigns/{campaignId}/leads/{email OR leadId}` | Patch fields; can add an `email` to a no-email lead. |
| Unsubscribe a lead | DELETE | `/campaigns/{campaignId}/leads/{email}` | Plain DELETE only **unsubscribes** (stops sending); the lead **stays listed**. Needs an email. |
| **Hard-delete a lead** | DELETE | `/campaigns/{campaignId}/leads/{leadId}?action=remove` | True removal from the campaign. Works by **lead id** (`lea_…`), no email needed. The `action=remove` flag is what forces the hard delete; without it you only unsubscribe. (Verified live.) |

> **Single-lead GET by email or id returns an empty body — do not rely on it.** Read back via the POST/PATCH echo, the `/leads` list (ids+state), or `/export/leads` (full CSV).

---

## Lead schema

```json
{
  "email": "jane@acme.com",
  "firstName": "Jane",
  "lastName": "Doe",
  "companyName": "Acme",
  "jobTitle": "Head of Partnerships",
  "linkedinUrl": "https://www.linkedin.com/in/janedoe",
  "icebreaker": "Saw Acme just launched X, so wanted to reach out.",
  "companyAngle": "any custom variable, becomes {{companyAngle}}"
}
```

- **Email + LinkedIn (multichannel):** push **both** so the campaign can run its email steps AND LinkedIn steps against the same lead.
- **LinkedIn-only lead (no email): accepted as-is** — POST with `linkedinUrl` and no `email` returns 200. The LinkedIn steps run; email steps are skipped for that lead. (Optionally `?linkedinEnrichment=true&findEmail=true` to try to discover an email — costs credits, so only on request.)
- **Custom variables: any extra body key persists and renders as `{{thatKey}}`** (verified with `companyAngle`). `icebreaker` is the standard Qwintiq one.

### Merge variables in copy

- **Double braces required:** `{{firstName}}`. Single braces render as literal text.
- **Standard fields auto-map** from the lead body: `{{firstName}}`, `{{lastName}}`, `{{companyName}}`, `{{jobTitle}}`.
- **Custom fields:** exact key, e.g. `{{icebreaker}}`, `{{companyAngle}}`.

---

## Auto-launch — the critical mental model

Adding a lead is **not** the same as sending to it.

- A lead starts receiving the sequence only when the campaign is **running** AND in **auto-launch** mode. A **draft / paused** campaign holds added leads without sending (verified: adding to the draft `[test campaign]` did not send).
- **For any test:** add to a **draft/paused** campaign, or use a **dummy lead** on `example.com` / a fake LinkedIn URL, so nothing real is messaged. Confirm campaign state with the user first.

---

## Icebreakers — every lead needs one (run `qwintiq-icebreaker` first)

Qwintiq sequences open with a per-lead **`{{icebreaker}}`**, so a lead with an empty icebreaker ships a broken first line. **Before you upload, make sure every prospect has an `{{icebreaker}}`.**

- If the list does **not** already have a per-lead icebreaker, run **`qwintiq-icebreaker`** first. It loads the user's saved icebreaker setup (the angles to look for), reads each prospect's website / LinkedIn, and writes one line per person. If there is no saved setup yet, the user states one in about a minute the first time (it is then saved and reused on every later upload).
- If the list **already** has icebreakers (generated earlier or carried through the pipeline), map them into the `icebreaker` field as-is.
- Keep the two skills straight: **`qwintiq-copywriter`** writes the sequence copy that *contains* `{{icebreaker}}`; **`qwintiq-icebreaker`** writes the *per-lead value* that fills it.

So the order for every upload is: **build / enrich the list → run `qwintiq-icebreaker` to fill `{{icebreaker}}` → upload here.** Never push leads with a blank icebreaker into a campaign whose copy expects one.

---

## SOP — uploading a list into a Lemlist campaign

### Step 1 — Identify the target campaign
`GET /campaigns`, match the user's campaign **name** to its `cam_…` id and note its `status`. If several match, show them and ask. Echo the campaign name + id + status (draft/running) back and confirm before pushing.

### Step 2 — Prepare the leads
Map the list into lead objects: `email` (if present), `linkedinUrl`, `firstName`, `lastName`, `companyName`, `jobTitle`, `icebreaker`, plus any custom vars the copy uses. **The `icebreaker` value is the per-lead line from `qwintiq-icebreaker`** (run it first if the list has none, see "Icebreakers" above). If any lead has a blank `icebreaker` and the campaign copy uses `{{icebreaker}}`, stop and run `qwintiq-icebreaker` before pushing.

### Step 3 — Confirm before pushing
Show the user: campaign name + status, lead count, whether the campaign is **running with auto-launch (will send immediately)**, and any enrichment query params that cost credits. Wait for a clear go-ahead.

### Step 4 — Trial (mandatory)
Push **1–3 representative leads first**. Confirm via the POST echo that fields + custom vars came back populated. If you want a fuller check, pull `/export/leads` and eyeball the row.

### Step 5 — Push the rest
Loop **one POST per lead** (no bulk endpoint). Throttle to ~2–4 req/sec; retry on `429` (honour `Retry-After`) and `5xx` with backoff (2s, 4s, 6s). Use `?deduplicate=true` to avoid re-adding the same lead across campaigns. Track added / deduped / failed.

### Step 6 — Report
Give the tally, list any failures with reason, and remind the user whether the campaign is auto-launch (already sending) or whether they launch the added leads in the Lemlist UI.

---

## Guardrails

1. **Always send a browser `User-Agent`** or Cloudflare returns 403 / "error code: 1010".
2. **Basic auth with the leading colon** (`:KEY`). Bearer does not work.
3. **Read `LEMLIST_API_KEY` from `~/.navreo-keys.env`.** The shared Qwintiq key is also documented in the Connecting Your Tools portal doc (per Bjion's decision).
4. **Always trial 1–3 leads first** and confirm the echo before the full push.
5. **Never message a real prospect during a test** — draft/paused campaign or dummy lead, confirmed with the user.
6. **Confirm campaign name + id + status** back to the user before pushing.
7. **Auto-launch awareness:** added ≠ sending. Always tell the user which state the campaign is in.
8. **Push email AND LinkedIn URL** when both exist so multichannel works; a no-email lead is fine (LinkedIn-only).
9. **Double-braced merge variables**; custom-var keys must match the copy exactly (any extra body key works).
10. **Plain DELETE = unsubscribe; add `?action=remove` for a true hard-delete** (by `lea_…` id, no email needed). Verified live.
11. **Throttle + retry**; there is no bulk endpoint.
12. **Every lead needs an `{{icebreaker}}`.** If the campaign copy opens with `{{icebreaker}}`, run `qwintiq-icebreaker` to fill each lead's per-lead line BEFORE pushing. Never upload leads with a blank icebreaker into an icebreaker-expecting campaign.

---

## Qwintiq campaigns reference (as of 2026-06-17 — re-list to confirm)

Master templates the team duplicates (see the Launch-a-Campaign portal doc):

| Name | id |
|---|---|
| Email-Only (Template) | `cam_D9m8FmBAiX4F9kKch` |
| LinkedIn-Only (Template) | `cam_cfpoBckCkFQmTRA6K` |
| LinkedIn-to-Email (Template) | `cam_2NbHkmuKit5TTAtBa` |
| `[test campaign]` (draft, safe sandbox) | `cam_Tzse2WvvNxtb4y4fE` |

---

## Quick reference — curl (note the `-A` user-agent on every call)

```bash
set -a; source ~/.navreo-keys.env; set +a
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

# 1) verify auth + find campaign id by name
curl -sk -A "$UA" "https://api.lemlist.com/api/campaigns?limit=100" --user ":$LEMLIST_API_KEY"

# 2) add one lead (multichannel: email + LinkedIn) with an icebreaker + custom var
curl -sk -A "$UA" -X POST "https://api.lemlist.com/api/campaigns/cam_XXXX/leads/?deduplicate=true" \
  --user ":$LEMLIST_API_KEY" -H "Content-Type: application/json" \
  -d '{"email":"jane@acme.com","firstName":"Jane","lastName":"Doe","companyName":"Acme","jobTitle":"Head of Partnerships","linkedinUrl":"https://www.linkedin.com/in/janedoe","icebreaker":"Saw Acme just launched X, so wanted to reach out."}'

# 3) read the campaign's leads back (ids + state) / full CSV
curl -sk -A "$UA" "https://api.lemlist.com/api/campaigns/cam_XXXX/leads" --user ":$LEMLIST_API_KEY"
curl -sk -A "$UA" "https://api.lemlist.com/api/campaigns/cam_XXXX/export/leads" --user ":$LEMLIST_API_KEY"
```
