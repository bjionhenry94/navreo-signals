---
name: lilly-positive-reply-setup
description: One-time setup that onboards a client into positive-reply reporting (a positive reply posts a card + threaded mobile to their Slack channel and logs a row to their Notion leads page). Works in TWO modes. MODE A (default, Navreo's own Smartlead workspace) wires a client whose campaigns run in Navreo's Smartlead: it adds the `make` bot to their `#[client]-navreo` Slack channel, ensures their portal's "All Campaign Responses" database, fills their Active Clients row, and appends a per-client route to the live Folk pipeline `8946472` (card + leads-page row + BetterContact→Prospeo phone). MODE B (the client runs their OWN Smartlead workspace) is triggered when the user SUPPLIES A SMARTLEAD API KEY: it builds a dedicated, self-contained Make scenario for that workspace (AI reply categoriser + positive routing) via scripts/build_external_scenario.py, then registers the reply webhook on the client's campaigns via scripts/register_client_webhook.py using their key. SETUP ONLY, once per client. Use whenever the user wants to: set up / onboard a client for positive-reply reporting, "set up reporting for [client]", "onboard [client] into reporting", "wire up [client] for responses", or "[client] has their own Smartlead, here's the API key, set up the reporting / create the Make scenario". Trigger phrases: 'set up reporting for [client]', 'onboard [client] into reporting', 'set up positive-reply reporting with this Smartlead API key', 'create the Make scenario for [client]'s workspace'.
---

# Lilly Positive-Reply Reporting — Setup (onboard a client)

Run this **once per client** to wire them into positive-reply reporting: when a campaign gets a positive reply (Interested / Meeting Request / Information Request / Call Booked) the lead is logged to the client's Notion **leads page** and a **card** (their reply, the email we sent, a "View all your leads" link) posts to their **Slack channel**, with the prospect's **verified mobile threaded underneath** (BetterContact first, Prospeo fallback).

There are **two modes** — pick based on whose Smartlead the campaigns run in:

| | **Mode A — Navreo's Smartlead** (default) | **Mode B — client's OWN Smartlead** |
| --- | --- | --- |
| When | Campaigns live in Navreo's workspace | User supplies the **client's Smartlead API key** |
| Categorising | Already done by the live `smartlead-reply_categoriser-Navreo` | Built into the new scenario (its own AI categoriser) |
| Routing | Add a route to the live Folk pipeline `8946472` | Build a **new dedicated Make scenario** for that workspace |
| Webhook | Already feeding Navreo's account | Skill **registers it on the client's campaigns** via their key |

Both modes share Steps 1–3 (Slack channel, responses database). They differ at Step 4+.

## Inputs
- The client's **name** (e.g. "Arnic").
- The client's **portal page** + **Active Clients row** (find via Notion search if not given).
- **Mode B only:** the client's **Smartlead API key**.

## Steps 1–3 (both modes)

### 1. Add the routing bot to the client's Slack channel
- Use the client's **existing** `#[client]-navreo` Slack channel. Find its **Channel ID** with `slack_search_channels` (starts with `C`). Don't create a separate `-notifications` channel.
- The Make bot **`make`** (`U07T2STMDBP`) must be a member or posts fail with `channel_not_found`. Confirm with `slack_list_channel_members` (`include_bots:true`). If absent, ask the user to run **`/invite @make`** in that channel (works even where external-people invites are blocked; the "Add an App" tab is often greyed out on Slack Connect channels). The bot can't add itself.

### 2. Ensure the responses database
- Open the client's portal page (`notion-fetch`). Look for an inline database titled **All Campaign Responses** (or "... for [Client]"). New portals from the `{Client Name} | Client Portal` template already include it.
- **If present:** copy its **Database ID** (page-style id in `<database url=.../p/<ID>>`) and its `collection://` data-source id.
- **If missing:** create with `notion-create-database` (parent = portal page):
  - Title `All Campaign Responses for [Client]`; schema: `CREATE TABLE ("Lead-Name" TITLE, "Full-Reply" RICH_TEXT, "Company Name" RICH_TEXT, "Email" EMAIL, "Website" URL, "LinkedIn URL" URL, "Campaign Name" RICH_TEXT, "Time of Reply" DATE, "First Email Sent" RICH_TEXT, "Select" SELECT('Interested':green), "Status" SELECT('1. Not responded':gray, '2. Responded':yellow, '3. Meeting-Ready':blue, '4. Meeting-Booked':green, '5. No response (after 14 days)':orange))` (Status is a numbered Select so board columns sort in pipeline order).
  - Add 3 views (`notion-create-view`): board **Lead Stage** (`GROUP BY "Status"`, `FILTER "Select" = "Interested"`), table **All Responses** (`GROUP BY "Select"`), calendar **By Date** (`CALENDAR BY "Time of Reply"`). Set inline; move below Project Files / Useful Guides if desired.

### 3. Confirm Slack channel + DB ids captured
Hold the **Slack Channel ID** (Step 1) and **Responses DB ID** (Step 2) for the mode-specific step.

---

## Mode A — campaigns in Navreo's Smartlead (default)

Categorising + the account webhook already exist. You only **add a route** to the live Folk pipeline.

### A4. Fetch the Smartlead Client ID (hygiene)
```bash
set -a; source ~/.navreo-keys.env; set +a
python3 ~/.claude/skills/lilly-positive-reply-setup/scripts/get_smartlead_client.py "<client name>"
```
Routing keys on the **campaign name containing the client's name** (not client_id), so ensure their campaigns carry the name.

### A5. Add the client's route to the Folk pipeline `8946472`
Navreo-workspace positive routing lives in **`8946472`** (`SmartLead Positive Reply (Navreo) → Folk + HeyReach`). Append one route (the user never touches Make):
- `scenarios_get` `8946472` → take its `blueprint`.
- In the BasicRouter (`flow[2].routes`), **copy an existing client route block** — Amplifyy (module ids `60,61,62` + BetterContact `80,81,82` + onerror `63,64,65,66,83,84`) or Arnic (`70,71,72,90,91,92` + onerror `73,74,75,76,93,94`) — and change only: the filter (`campaign_name` **contains** the client's name), the Slack `channel` (Step 1), the card's `*Client:*` label + `View all your leads` URL (`https://www.notion.so/<Step 2 DB id>`), and the `notion:createAPage` `database` (Step 2 DB id). Give every new module a unique id (e.g. `100+`). Keep the card → Notion → BetterContact(submit/`util:FunctionSleep` 240s/get) → phone order and all `onerror` guards.
- `validate_blueprint_schema` → `scenarios_update` `8946472` → `scenarios_activate` (an update deactivates it).

### A6. Fill the Active Clients row
On the client's **Active Clients** row (`notion-update-page` `update_properties`): **Smartlead Client ID** (A4), **Responses DB ID** (Step 2), **Slack Channel ID** (Step 1), **Route Responses** = `__YES__`.

---

## Mode B — client runs their OWN Smartlead (you supply the API key)

Builds a **dedicated, self-contained Make scenario** for the client's workspace (its own AI categoriser + positive routing) and registers the webhook on their campaigns. The categoriser AI prompt is preserved byte-for-byte from `scripts/external_scenario_template.json` (the verified Navreo categoriser).

### B4. Create the Make trigger hook
`hooks_create` (teamId `536258`, name `smartlead-<client>-replies`, typeName `gateway-webhook`, `data: {"headers": false, "method": false, "stringify": false}`). Capture the returned **hook id** + **url** (`https://hook.eu2.make.com/<udid>`).

### B5. Build + create the scenario
```bash
set -a; source ~/.navreo-keys.env; set +a
python3 ~/.claude/skills/lilly-positive-reply-setup/scripts/build_external_scenario.py \
  --client "<Client>" --api-key "<CLIENT_SMARTLEAD_KEY>" \
  --slack <Step1 channel> --notion-db <Step2 DB id> --hook <B4 hook id> --out /tmp/ext_bp.json
```
Then `validate_blueprint_schema` (read `/tmp/ext_bp.json`) → `scenarios_create` (teamId `536258`, `scheduling {"type":"immediately","maximum_runs_per_minute":60}`, `blueprint` = the file) → `scenarios_activate`. It uses Navreo's Slack/Notion/OpenAI/Prospeo/BetterContact connections; only the Smartlead calls use the client's key (embedded in the scenario).

### B6. Register the webhook on the client's campaigns
```bash
python3 ~/.claude/skills/lilly-positive-reply-setup/scripts/register_client_webhook.py "<CLIENT_SMARTLEAD_KEY>" "<B4 hook url>"
```
Adds an `EMAIL_REPLY` webhook to every ACTIVE campaign in their workspace. Re-run after they launch new campaigns (webhooks are per-campaign). `--dry-run` lists campaigns without changing anything.

### B7. Record it
Fill the client's Active Clients row (Responses DB ID, Slack Channel ID, Route Responses = `__YES__`) and note **Mode B + scenario id**. **Do NOT store the raw Smartlead API key in Notion or git** — it lives only inside the Make scenario (same as Navreo's other embedded keys).

---

### Final step (both modes): Report
Summarise: bot confirmed in the channel (ID), responses DB (created/existing, ID), and — Mode A: route added to `8946472`; Mode B: scenario created + activated (id) + webhook registered on N campaigns. Optionally offer the one-time backfill (below).

### (Optional, one-time) Backfill existing positives
```bash
set -a; source ~/.navreo-keys.env; set +a
python3 ~/.claude/skills/lilly-positive-reply-setup/scripts/route_responses.py /tmp/lcr_config.json /tmp/lcr_out
```
`/tmp/lcr_config.json` = `{"clients":[{"name","smartlead_client_id","responses_db_id","slack_channel_id","leads_db_url","existing_emails":[...]}]}`. For each item in `/tmp/lcr_out/<client>.json`: `notion-create-pages` (parent = responses-DB collection), then `slack_send_message` (card), then a threaded `slack_send_message` for the phone if present. Dedupes against `existing_emails`. For a Mode B client, set `SMARTLEAD_API_KEY` to that client's key for this run.

## Reference
- Active Clients data source: `2616e75598d98022b3a7fde57d29ad14` (collection `2616e755-98d9-800c-9997-000bf51dafcd`). Portal template: `2616e75598d980b0a581e0fddcaaba8e`.
- Mode A routing pipeline: **`8946472`** `SmartLead Positive Reply (Navreo) → Folk + HeyReach` (hook `4001002`). Categoriser: **`9251436`** ` smartlead-reply_categoriser-Navreo` (hook `4135325`) — both now run the BetterContact→Prospeo phone waterfall.
- Connections: Slack `9254394`, Notion `11521245`, OpenAI `11622594`. Internal alerts channel `C07TTLZKU56`.
- Current Mode-A clients: Arnic = client `366437`, channel `C0AHFEHV188` (#arnic-navreo), DB `2ec3333429d54ebf9a5dba33f1402561`. Amplifyy = client `429350`, channel `C0AV6J0MFPS` (#amplifyy-navreo), DB `342a5f09137b4af780a003eb19542ff0`.
- Keys: `SMARTLEAD_API_KEY`, `BETTERCONTACT_API_KEY`, `PROSPEO_API_KEY` from `~/.navreo-keys.env`. BetterContact: base `https://app.bettercontact.rocks/api/v2`, header `X-API-Key`, async (`POST /async` → poll `GET /async/{id}` until `status:"terminated"`; phone at `data[].contact_phone_number`).
- Phone in the live scenarios = `util:FunctionSleep` 240s after a BetterContact submit, then prefer BetterContact's number else the Prospeo verified mobile. The standalone scenario `9412546` was retired (folded into `8946472`).

## Gotchas
- Client channels are **Slack Connect**. `make` (`U07T2STMDBP`) must be `/invite`-d in or posts fail `channel_not_found`; the "Add an App" tab is usually blocked on shared channels.
- **Notion URL fields reject an empty string** (the URL value must be a non-empty string or null). Map Website/LinkedIn as a **plain reference** (`{{1.lead_data.website}}` / `{{29.data.website}}`), NEVER an `if(...; "")` formula. Make omits an empty *reference* (fine), but a formula that evaluates to `""` is sent, and Notion rejects `""` → the whole row write fails for any lead with no website/LinkedIn, firing the `onerror` alert to `C07TTLZKU56`. Notion accepts bare domains as-is, so no `https://` prefixing is needed. (A `if(...; "")` formula caused exactly this outage; reverted to plain references across `8946472` + `9414775` + `build_external_scenario.py` on 2026-06-21.)
- Editing a live scenario: always `validate_blueprint_schema` first, preserve every existing route/module (work from a fresh `scenarios_get`), and re-`scenarios_activate` after the update.
- Never post a junk/test card into a client channel — the Slack MCP has no delete. Test Mode B against a sandbox channel + the portal **template** DB if needed.
- **Mode B:** never store the client's Smartlead API key in Notion or git. Webhooks are per-campaign — re-run `register_client_webhook.py` after new campaigns launch.
- Never re-enable Maildoso warmup or touch unrelated settings.
