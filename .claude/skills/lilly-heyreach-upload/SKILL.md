---
name: lilly-heyreach-upload
description: "Upload leads to HeyReach lists and launch HeyReach LinkedIn outreach campaigns end-to-end via the REST API. Use this skill whenever the user wants to: push leads to HeyReach, create a HeyReach list, segment leads into tier-lists, upload prospects without emails to LinkedIn, launch or activate a HeyReach campaign, swap a campaign's source list, or trial a HeyReach campaign with a small sandbox list before going to production. Also use as the hand-off destination from `lilly-email-verification` or `lilly-tam` when the user agrees to push no-email-found prospects to LinkedIn. Trigger phrases: 'push to HeyReach', 'upload to HeyReach', 'create a HeyReach list', 'segment leads by tier in HeyReach', 'launch HeyReach campaign', 'swap HeyReach list', 'HeyReach trial run', 'push no-email leads to LinkedIn', 'send these to LinkedIn instead'."
---

# Lilly HeyReach Upload

## Purpose

Operate HeyReach (LinkedIn outreach platform) directly via REST API: create lists, push leads with custom personalisation fields, launch campaigns with proper merge variables, and run trial-then-production swap workflows. The HeyReach MCP server is unreliable (frequent timeouts, occasional disconnects); always default to the REST API.

This skill is the LinkedIn equivalent of `lilly-bot` (which handles Smartlead for email). Same general flow: prepare leads → personalise → push → trial → activate. The HeyReach specifics differ enough to warrant a dedicated skill.

---

## When to Use

Trigger whenever the user wants to:

- Push a CSV / lead list to a HeyReach list with custom fields
- Create new HeyReach lists (e.g. score-tier segmentation, per-vertical splits, trial sandbox)
- Launch a HeyReach campaign and configure it with merge variables
- Swap a campaign's source list (note: UI-only, no API for this)
- Run a small trial before production (the standard pre-launch validation pattern)

Also serves as the **hand-off destination** when:
- `lilly-email-verification` finishes and the user says "yes" to "push the no-email leads to LinkedIn"
- `lilly-tam` finishes and the user says "yes" to the same prompt
- Any other workflow lands a batch of LinkedIn-URLs-without-emails that the user wants to outreach via LinkedIn

---

## API setup

**Base URL:** `https://api.heyreach.io/api/public/`
**Auth header:** `X-API-KEY: <key>`
**Key location:** `~/.navreo-keys.env` as `HEYREACH_API_KEY` (read via `source ~/.navreo-keys.env` or direct `os.environ`)

**Verifying auth works (always start with this):**

```python
import json, os, ssl, urllib.request
ctx = ssl._create_unverified_context()  # mac Python urllib trips on cert verify; use curl OR this
req = urllib.request.Request(
    "https://api.heyreach.io/api/public/list/GetAll",
    data=json.dumps({"limit": 5, "offset": 0}).encode(),
    headers={"X-API-KEY": os.environ["HEYREACH_API_KEY"], "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
    print(json.loads(r.read())["items"])
```

If the key is missing from `~/.navreo-keys.env`, ask the user to add it (HeyReach Settings → API → Generate). Never accept a key inline in chat for permanent use — recommend they put it in the env file. If they paste it inline, use it transiently for the session and remind them to rotate after.

---

## Endpoints reference

| Action | Method | Path | Body / Notes |
|---|---|---|---|
| List all lists | POST | `/list/GetAll` | `{"limit": 20, "offset": 0}` |
| Get list by id | POST | `/list/GetById` | `{"listId": <id>}` |
| **Create empty list** | POST | `/list/CreateEmptyList` | `{"name": "...", "type": "USER_LIST"}` → returns `{id, name, ...}` |
| **Add leads to list (V2)** | POST | `/list/AddLeadsToListV2` | `{"listId": <id>, "leads": [...]}` — max 100 leads per call |
| Delete leads from list (by URL) | DELETE | `/list/DeleteLeadsFromListByProfileUrl` | `{"listId": <id>, "profileUrls": ["..."]}` — plural + DELETE method; the POST/singular variant 404s (live-tested 2026-07-05) |
| List all campaigns | POST | `/campaign/GetAll` | `{"limit": 20, "offset": 0}` |
| Get campaign by id | GET | `/campaign/GetById?campaignId=<id>` | — |
| Create campaign | POST | `/campaign/Create` | requires `LinkedInAccountIds` + name + sequence — typically configured in UI |
| Add leads to campaign | POST | `/campaign/AddLeadsToCampaign` | only works on NON-DRAFT campaigns; use list-based flow for DRAFT |
| Stop lead in campaign | POST | `/campaign/StopLeadInCampaign` | halts a lead mid-sequence |

**No endpoint exists for swapping a campaign's source list** — must be done in HeyReach UI (Edit Campaign → change `linkedInUserList`).

---

## Lead schema

```json
{
  "firstName": "Lissele",
  "lastName": "Pratt",
  "companyName": "Capitalixe",
  "profileUrl": "https://www.linkedin.com/in/lisselepratt",
  "position": "Founder",
  "customUserFields": [
    {"name": "Tool",      "value": "Lemlist"},
    {"name": "casestudy", "value": "BCA Research, Pegasystems and Arval"},
    {"name": "Why",       "value": "help you accelerate revenue from..."}
  ]
}
```

### Schema gotchas (every one of these has burned a real run)

1. **`lastName` must be non-empty.** If empty, the API silently drops the lead from `AddLeadsToListV2` (failedLeadsCount won't even count it; the response just reports one less added). **Fix:** before push, pad empty lastNames with `"."` or skip the lead.
2. **`profileUrl` is the unique key.** Re-pushing the same `profileUrl` = upsert; the V2 endpoint distinguishes adds vs updates in the response.
3. **`customUserFields[].name` must match `[A-Za-z0-9_]+`** — alphanumeric + underscore only. No spaces, no hyphens, no dots.
4. **Custom field names are case-sensitive** in copy. If you push `"Tool"`, `{{tool}}` will render empty. Match exactly.

### Merge variables in copy

- **Double braces required**: `{{Field}}`. Single braces (`{Field}`) render as literal text — the variable does NOT fire.
- **Standard fields** (always available, both formats accepted by HeyReach):
  - snake_case: `{{first_name}}`, `{{last_name}}`, `{{company_name}}`, `{{position}}`
  - camelCase: `{{firstName}}`, `{{lastName}}`, `{{companyName}}`, `{{position}}`
- **Custom fields**: exact case of `customUserFields[].name`.
- HeyReach has **no preview mode** in the UI for sent copy. The only safe way to validate render is the trial workflow below (push a small list, swap the campaign, activate, check the live render).

---

## Campaign-list relationship — the critical mental model

A HeyReach campaign is **bound to exactly one list** at creation time. When the campaign is activated, it pulls leads from that list and runs them through the sequence.

- **No API to swap a campaign's list.** Must be done manually in HeyReach UI.
- **DRAFT campaigns reject `AddLeadsToCampaign`** with `"You cannot add new leads to a draft campaign."` — so pre-activation, push to the LIST not the campaign.
- **Once the campaign is activated**, adding leads to the underlying list still works AND `AddLeadsToCampaign` becomes usable.

The natural workflow:

1. Create or identify the source list.
2. Push leads to the list (`AddLeadsToListV2`).
3. In HeyReach UI: create a campaign linked to this list, write sequence copy with `{{...}}` merge variables, set sender accounts.
4. Activate the campaign.

The trial workflow inserts a small sandbox list and a UI swap before step 4 — see SOP below.

---

## SOP — Launching a HeyReach campaign end-to-end

This is the canonical workflow. Adapt the front-end (lead source) but keep the back half (push → trial → swap → activate) consistent.

### Step 1 — Prepare the lead list

Input: a CSV or in-memory list of leads with at minimum:
- LinkedIn URL (the unique key)
- First name, last name, company name
- Title (becomes `position` field)

Optional but typical:
- Industry / company description (used for `{{casestudy}}` brand selection and `{{Why}}` inference)
- Country / region
- Score / tier (used for list segmentation)

### Step 2 — Generate personalisation fields (custom merge variables)

Most LinkedIn campaigns use 2-3 custom fields beyond `{{first_name}}` / `{{company_name}}`:

- **`{{Tool}}`** — when leads came from a tool's LinkedIn follower scrape (Boomerang exports, etc.), tag each lead with the tool name. Use a `LinkedIn URL → Tool` lookup table built from the source CSVs.
- **`{{casestudy}}`** — 3-brand name-drop tail (e.g. `"HubSpot, Clay and AlphaSense"`) picked from the Navreo 57-brand pool per lead, biased to the lead's target-account universe. See `lilly-personalisation` for the bucket-to-brand mapping and the per-lead triplet picker. The brand-name tail format fits the carrier sentence `"booked calls with {{casestudy}}"` — do NOT use the full Smartlead-style CaseStudy sentence here (it breaks grammar).
- **`{{Why}}`** — title-aware per-lead verb-phrase that completes `"showing how we'd {{Why}}"`. Generate via `lilly-personalisation`'s Why pattern. Spawn parallel sub-agents for >500 leads.

### Step 3 — Score-tier segmentation (if relevant)

When pushing a large batch (>1,000 leads), segment by score tier so each tier can be wired to its own campaign / copy variant. Default Navreo framework:

- **A+ (85+)** — `No-Email A+ (85+)`
- **A (70-84)** — `No-Email A (70-84)`
- **B (55-69)** — `No-Email B (55-69)`
- **D (20-39)** — useful as a "dummy / trial" pool because mis-renders burn the lowest-fit leads
- Below 20: don't push

Confirm tier strategy with the user before creating lists — they may want different splits (by industry, by Tool followed, etc.).

### Step 4 — Create the lists

Per tier:

```bash
curl -sk -X POST "https://api.heyreach.io/api/public/list/CreateEmptyList" \
  -H "X-API-KEY: $HEYREACH_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "No-Email A+ (85+)", "type": "USER_LIST"}'
```

Record the returned `id` per list — you'll need it for the push step.

### Step 5 — Push leads in batches of 100

Slice the lead list into 100-lead batches. For each:

```python
import json, os, ssl, urllib.request
ctx = ssl._create_unverified_context()
body = {"listId": <listId>, "leads": [<lead-objs>]}
req = urllib.request.Request(
    "https://api.heyreach.io/api/public/list/AddLeadsToListV2",
    data=json.dumps(body).encode(),
    headers={"X-API-KEY": os.environ["HEYREACH_API_KEY"], "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
    resp = json.loads(r.read())
# resp = {"addedLeadsCount": N, "updatedLeadsCount": M, "failedLeadsCount": F}
```

**Retry pattern:** wrap each call in 3 retries with backoff (2s, 4s, 6s) on `URLError` / `HTTPError(5xx)` / `TimeoutError`. The MCP server (when used) is flaky; even direct REST occasionally has transient blips.

**Batch-fail recovery:** when a 100-lead batch fails repeatedly, split it into 25-lead chunks and retry — this proved reliably faster in practice.

**Empty `lastName` audit:** before the push, scan for `lastName == ""` and pad with `"."`. Otherwise HeyReach silently drops those leads.

### Step 6 — Set up the campaign in HeyReach UI

(API can't fully orchestrate campaign creation — sequence copy and sender mapping live in the UI.)

In HeyReach:

1. Create a new campaign (or use an existing one).
2. Link it to the LIST you just populated.
3. Set the sender LinkedIn account(s).
4. Write the sequence copy with **double-braced** merge variables:

   ```
   Hey {{first_name}},

   Saw you were following {{Tool}} and figured you're running outbound at {{company_name}}.

   There's a lot of noise right now around what tools and tactics to use for go-to-market.

   I recorded a Loom for {{company_name}} showing how we'd {{Why}}.

   Want me to send it?
   ```

5. Echo this copy back to the user with each merge variable bolded and ask them to confirm before activation — there's no preview mode.

### Step 7 — Trial run (mandatory if >50 leads)

Never activate a campaign directly against the full list. The trial-swap pattern:

1. **Create a small "trial" list** with 10-20 representative leads (e.g. the D-tier dummy, or a hand-picked diverse slice across industries). Use this for the test run.
2. **In HeyReach UI:** swap the campaign's source list to the trial list.
3. **Activate the campaign.** The 10-20 trial DMs go out.
4. **Wait ~24h** and check:
   - Did messages render with custom fields populated, or did `{{Tool}}` / `{{Why}}` show up as literal text? (= field name mismatch or single-brace bug)
   - Did the LinkedIn account get any LinkedIn-side warnings / restrictions?
   - Are responses coherent? (= Why's grammar / tone is working)
5. **If render is broken**, fix at the source (custom field names in payload + copy variables) and re-push the affected leads via `AddLeadsToListV2` (the V2 endpoint upserts — re-push with corrected field is safe).
6. **If render is good**, swap the campaign back to the production list and let it run.

### Step 8 — Production swap and activation

In HeyReach UI: Edit Campaign → swap `linkedInUserList` from trial list → production list. The campaign continues with the new source.

If multiple tier lists (A+, A, B), either:
- **Sequentially**: run A+ first (highest fit), then A, then B — swap the list each time, monitor reply rates per tier
- **Parallel**: clone the campaign 3 times in UI, one per tier list, run them simultaneously with different copy variants if desired

---

## Hand-off pattern: receiving no-email leads from enrichment skills

When `lilly-email-verification` or `lilly-tam` completes with a "no-email-found" drop pile, the user is asked whether to push those to LinkedIn. If yes, this skill receives:

- A CSV / array of leads with at minimum: LinkedIn URL, first name, last name, company name, title
- Optionally: industry, description, country, score (if the enrichment was preceded by lead-scoring)

The skill then:

1. Asks for list-naming convention (e.g. `No-Email A+`, or just `<campaign-name> — LinkedIn fallback`)
2. Confirms whether to also segment by score tier (if scores are present)
3. Asks whether to generate `{{Why}}` and `{{casestudy}}` (recommended) or push without (faster but emails-1/2 render empty for those variables)
4. Generates per-lead Why via `lilly-personalisation` (parallel sub-agents for >500 leads)
5. Picks 3-brand triplets from the 57-brand pool for `{{casestudy}}`
6. Creates the list(s) via API
7. Pushes leads in 100-lead batches
8. Reports the final tally and reminds the user to:
   - Set up / link the campaign in HeyReach UI
   - Add merge variables to the copy (echo the corrected copy back)
   - Do a trial run before going to production

---

## Common pitfalls (every one of these has happened — read this list)

| Pitfall | Symptom | Fix |
|---|---|---|
| Single braces in copy (`{Tool}` instead of `{{Tool}}`) | Variable renders as literal text in sent message | Audit all copy for single braces; HeyReach has no preview to catch this |
| Wrong case in merge variable (`{{tool}}` vs `{{Tool}}`) | Variable renders empty | Match `customUserFields[].name` exactly, case-sensitive |
| Empty `lastName` on lead | Silently dropped from `AddLeadsToListV2` response | Pre-flight scan + pad with `"."` |
| Pushing to a DRAFT campaign via `AddLeadsToCampaign` | `"You cannot add new leads to a draft campaign."` | Push to the bound LIST instead; activate the campaign separately |
| `add_leads_to_list` (V1, no V2) suffix | Returns success but customUserFields aren't applied | Always use the V2 endpoint |
| MCP server unresponsive | `connector's server isn't responding` repeated timeouts | Switch to REST API via `~/.navreo-keys.env` HEYREACH_API_KEY |
| Python urllib SSL cert fail on Mac | `[SSL: CERTIFICATE_VERIFY_FAILED]` | Use `ssl._create_unverified_context()` or shell out to curl |
| 100-lead batch repeatedly times out | API returns 5xx or hangs | Split that batch into 4×25-lead chunks; almost always works |
| Trying to swap campaign list via API | All endpoints return 404 (UpdateCampaign, SetLinkedInUserList, etc.) | UI only — open campaign → Edit → swap linkedInUserList |
| API key visible in chat history | Security exposure | Use transient session env var; remind user to rotate after |

---

## Quick reference — full curl skeleton

```bash
export HEYREACH_API_KEY='...'

# 1) verify auth
curl -sk -X POST "https://api.heyreach.io/api/public/list/GetAll" \
  -H "X-API-KEY: $HEYREACH_API_KEY" -H "Content-Type: application/json" \
  -d '{"limit": 5, "offset": 0}'

# 2) create empty list
curl -sk -X POST "https://api.heyreach.io/api/public/list/CreateEmptyList" \
  -H "X-API-KEY: $HEYREACH_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "My New List", "type": "USER_LIST"}'

# 3) push 100 leads (Python; see Step 5 above for the full snippet with retry)

# 4) check campaign state
curl -sk -X GET "https://api.heyreach.io/api/public/campaign/GetById?campaignId=<id>" \
  -H "X-API-KEY: $HEYREACH_API_KEY"

# 5) (UI step) swap campaign's linkedInUserList → trial list → activate → validate → swap back
```

---

## Guardrails

1. **Never push to a campaign in DRAFT.** Push to its bound list instead.
2. **Always run a trial first for batches >50 leads.** Use a small sandbox list; validate render before swapping to production.
3. **Always confirm copy with merge variables back to the user** before activation. HeyReach has no preview mode.
4. **Always check the `lastName` field for empty values** before push.
5. **Use the REST API, not the MCP server** — MCP times out under load.
6. **`AddLeadsToListV2`, not V1.** V1 ignores custom fields.
7. **`profileUrl` is the unique key.** Re-pushing with corrected fields is safe — it upserts.
8. **No campaign-list swap via API.** Always direct the user to the HeyReach UI for that step.
9. **Treat the HeyReach API key like any other credential.** Read from `~/.navreo-keys.env`. If the user pastes it inline, use transiently and recommend rotation.
10. **When hand-off from `lilly-email-verification` or `lilly-tam`**, always ask explicitly before generating Why/casestudy — those add cost (LLM calls + time). The user may want the cheap path (push with just first_name + company_name) for an initial test.
