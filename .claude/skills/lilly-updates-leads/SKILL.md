---
name: lilly-updates-leads
description: "Update, normalise, and fix lead data (especially company names) inside Smartlead campaigns. Use this skill whenever the user wants to clean up leads, fix company names, normalise lead fields, update lead records from a CSV, or bulk-edit lead data in Smartlead. Trigger whenever the user mentions updating leads, fixing company names, normalising data, cleaning up a CSV for Smartlead, or pushing corrected lead info — even if they don't explicitly name this skill."
---

# Lilly Updates Leads in SmartLead

## Purpose

Clean up, normalise, and update lead-level data inside Smartlead — particularly company names that are missing, contain junk (pipe descriptions, locations, old brand names), or have incorrect capitalisation.

---

## Critical API Knowledge

### The MCP `update_lead_by_id` tool DOES NOT WORK

The Smartlead MCP tool `smartlead_update_lead_by_id` returns a **404 error** every time. Do not waste time trying it. The same applies to `smartlead_fetch_lead_by_email` (returns `"leadId" must be a number`).

### How to actually update leads

Use the **Smartlead REST API directly** via Python `urllib`. The working endpoint is:

```
POST https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads?api_key={API_KEY}
```

With this body:

```json
{
  "lead_list": [
    {
      "email": "lead@example.com",
      "first_name": "Jane",
      "last_name": "Doe",
      "company_name": "Acme Corp"
    }
  ],
  "settings": {
    "ignore_global_block_list": false,
    "ignore_unsubscribe_list": false,
    "ignore_community_bounce_list": false,
    "ignore_duplicate_leads_in_other_campaign": false
  }
}
```

**Key facts:**
- The field name is `company_name`, NOT `company`
- Do NOT include `"update": true` in `settings` — the API rejects it with `"settings.update" is not allowed`
- When a lead already exists in the campaign, the API returns `"already_added_to_campaign": N` but **still updates the lead data at the platform level**
- Updates are **platform-level**, meaning the corrected data applies across ALL campaigns that lead appears in
- You still need a `campaign_id` to use this endpoint, even though the change is global

### Cloudflare blocking

The Smartlead API is behind Cloudflare which blocks requests with a Python user-agent (error 1010: `browser_signature_banned`). Always include a browser-like User-Agent header:

```python
headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}
```

### API Key location

The Smartlead API key is stored in the Claude Desktop config:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Under `.mcpServers.smartlead.env.SMARTLEAD_API_KEY`.

### Verifying updates

After updating, verify with:

```
GET https://server.smartlead.ai/api/v1/leads/{lead_id}?api_key={API_KEY}
```

This returns the lead's current data including `company_name`. Use the same browser User-Agent header.

---

## Complete Update Script Template

```python
import json, urllib.request, urllib.error

API_KEY = "<key>"
BASE = "https://server.smartlead.ai/api/v1"
CAMPAIGN_ID = <campaign_id>

headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

leads_to_update = [
    {"email": "...", "first_name": "...", "last_name": "...", "company_name": "..."},
    # ... more leads
]

url = f"{BASE}/campaigns/{CAMPAIGN_ID}/leads?api_key={API_KEY}"
data = json.dumps({
    "lead_list": leads_to_update,
    "settings": {
        "ignore_global_block_list": False,
        "ignore_unsubscribe_list": False,
        "ignore_community_bounce_list": False,
        "ignore_duplicate_leads_in_other_campaign": False
    }
}).encode()

req = urllib.request.Request(url, data=data, method='POST')
for k, v in headers.items():
    req.add_header(k, v)

with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read().decode())
    print(f"Uploaded: {result['upload_count']}, Already in campaign: {result['already_added_to_campaign']}")
```

---

## Finding Lead IDs from a Campaign

When you need lead IDs (e.g. for verification), paginate through the campaign:

```python
smartlead_list_leads_by_campaign(campaign_id=ID, limit=100, offset=0)
```

- Max `limit` is **100** (not higher — the API rejects it)
- The `search` parameter is **not supported** on this endpoint
- Results are saved to a file because they exceed token limits

### Parsing the saved results file

The results file uses double-escaped JSON (`\\"` for quotes). To extract lead IDs:

```python
import re

with open(filepath, "r") as f:
    content = f.read()

idx = content.find("target@email.com")
if idx != -1:
    before = content[max(0, idx-400):idx]
    ids = re.findall(r'\\"id\\":\s*(\d+)', before)
    lead_id = ids[-1] if ids else None
```

The lead `id` field appears before the `email` field in the JSON structure, so search backwards from the email match.

---

## Company Name Normalisation Rules

When scanning company names, flag these issues:

### Definitely fix
| Problem | Example | Fix |
|---------|---------|-----|
| **Missing / empty / `--`** | `--` or blank | Derive from website domain (e.g. `numa.com` → `Numa`) |
| **Contains location** | `Devoted Guardians Home Care in Phoenix, AZ` | Strip location → `Devoted Guardians` |
| **Pipe separator with description** | `Customer Growth \| Construction Social Media Agency` | Keep first part → `Customer Growth` |
| **"(previously ...)" suffix** | `OneMetric (previously Growtomation)` | Strip old name → `OneMetric` |
| **Incorrect capitalisation** | `the D2 collective` | Fix → `The D2 Collective` |
| **Generic lowercase** | `demonstro`, `inforcer` | Capitalise → `Demonstro`, `Inforcer` |

### Do NOT fix — intentional brand formatting
Many tech companies use intentional lowercase or camelCase branding. Leave these alone:

`eLocal`, `iCIMS`, `meshIQ`, `atVenu`, `eUnify`, `e360`, `evolv Consulting`, `dataquartz`

**How to tell the difference:** If the company name starts with a lowercase letter followed by an uppercase letter (camelCase like `eLocal`, `iCIMS`) or is a well-known brand with established lowercase styling, leave it. If it's a simple word that just wasn't capitalised (like `demonstro` or `inforcer`), fix it.

### Deriving company names from missing data
When company name is empty, try these sources in order:
1. **Website domain** — strip protocol, `www.`, path, and TLD. Capitalise. E.g. `https://www.numa.com/` → `Numa`
2. **Email domain** — same approach but less reliable (some use generic domains)
3. **LinkedIn URL** — sometimes contains company slug

---

## Workflow: Cleaning Company Names from a CSV

1. **Read the CSV** using the `Read` tool (use `offset`/`limit` for large files)
2. **Parse with Python** to identify problematic company names (missing, location-stuffed, pipe-separated, uncapitalised)
3. **Present findings** to the user in a table showing current → proposed fix
4. **Get the API key** from `~/Library/Application Support/Claude/claude_desktop_config.json`
5. **Push updates** via the direct API endpoint (batch all leads in one request)
6. **Verify a sample** using the GET endpoint to confirm changes applied

The user needs to provide a `campaign_id` because the update endpoint routes through a campaign, even though changes apply globally.

---

## Batch Size

There is no known batch limit on the leads endpoint, but for safety keep batches under ~50 leads per request. If updating hundreds of leads, split into multiple requests.


## Upload gate (MANDATORY)

Before ANY lead push into a Smartlead campaign that results from this skill (`add_leads_to_campaign` or equivalent), hand off to `lilly-upload-gate` and let it run to a green gate: every enabled check PASS or explicitly OVERRIDDEN per-flag, and the audit row written to `list_upload_qa_runs` BEFORE the first add-leads call. Never upload around the gate.
