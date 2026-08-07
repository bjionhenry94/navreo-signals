---
name: update-porkbun-domains
description: "Bulk-update authoritative nameservers on Porkbun-registered domains by reading a CSV of `domain → ns1, ns2, …` mappings and POSTing each row to Porkbun's `updateNs` API. Use this skill whenever the user wants to point multiple Porkbun-registered domains at a new nameserver provider (Cloudflare, Vercel, Route53, etc.), has a CSV of domain-to-nameserver mappings to apply, or has just onboarded a batch of domains to Cloudflare and needs to set the per-domain NS pairs at the registrar. Trigger on phrases like 'update nameservers on Porkbun', 'bulk update NS', 'point these domains to Cloudflare', 'switch DNS provider on these domains', 'delegate these domains to X', 'apply this CSV of nameservers to Porkbun', or any time the user attaches a CSV with a `Domain` column and one or more `Nameserver` columns alongside Porkbun-related intent. Validates credentials via `/ping` first, confirms scope with the user before firing, then runs the bulk update with per-row reporting and a retry path for rows that failed because API access wasn't enabled on that domain."
---

# Update Porkbun Domains

## Purpose

Take a CSV of `domain → nameserver(s)` rows, validate Porkbun API credentials, confirm scope with the user, then POST each row to `https://api.porkbun.com/api/json/v3/domain/updateNs/{domain}` to change the authoritative nameservers at the registrar.

This is the registry-level NS change. It tells DNS resolvers "for this domain, ask `<new nameservers>`" instead of Porkbun's default NS. It does **not** change DNS records (A, MX, TXT, etc.) — those must already be configured at the destination nameserver provider before propagation, otherwise the domain goes dark.

Typical use case: user has just added a batch of domains to Cloudflare, Cloudflare assigned each domain a unique 2-server NS pair, and the user needs to apply those pairs at Porkbun in bulk. Skill works for any nameserver destination — Cloudflare, Vercel, Route53, custom NS, etc.

---

## When to Use

- User attaches a CSV with a `Domain` column and `Nameserver 1` / `Nameserver 2` columns (or `ns1` / `ns2`) and asks to apply it
- User says "update nameservers on Porkbun for these domains" or similar
- User just finished onboarding multiple domains to Cloudflare and has the per-domain NS pairs to apply
- User wants to switch the registrar-level NS for a batch of domains to any new provider

Do **not** use this skill for:
- Single-domain updates (faster to do via the Porkbun web UI)
- DNS record changes (A/MX/TXT records) — that's a separate workflow at the destination NS provider, not Porkbun
- Domains registered elsewhere (GoDaddy, Namecheap, etc.) — different APIs

---

## Pre-flight Checklist

Before firing the bulk run, walk through the user on each of these. The skill should refuse to proceed until all are confirmed.

### 1. Credentials are available

Two env vars must be set when the script runs:
- `PORKBUN_API_KEY` (format: `pk1_...`)
- `PORKBUN_SECRET_API_KEY` (format: `sk1_...`)

User's preferred location: `~/.navreo-keys.env` (mode 600, auto-loaded by `~/.zshrc`). Recommend adding both keys there so they don't need to be pasted into chat each time:

```
export PORKBUN_API_KEY=pk1_...
export PORKBUN_SECRET_API_KEY=sk1_...
```

If the user pastes keys directly into chat, flag that the transcript now contains them and recommend rotating both via Porkbun control panel → Account → API Access after the run completes.

### 2. API access is enabled per domain

Each domain must have "API ACCESS" toggled on at Porkbun. Without this, that domain's update call returns an error. Steps:
1. Log into Porkbun → Domain Management
2. For each domain, toggle the "API ACCESS" switch on (it's a per-domain setting)
3. There's no bulk-enable in the Porkbun UI; if the list is long the user can ignore this step and we'll surface the failed rows at the end, then they can enable + retry just those

### 3. DNS records exist at the destination NS provider

The registry NS change just points authority. If the destination provider doesn't already have the domain's A/MX/TXT records configured, the domain will be unreachable during propagation. Confirm the user has:
- Added every domain in the CSV to the destination NS provider
- Configured at least the records they need (typically root A/AAAA, MX if email, any TXT)
- Each domain shows the correct NS pair in the destination provider's panel (this is where the user got the per-domain NS values for the CSV)

### 4. CSV is well-formed

Required: a header row with a `Domain` column (case-insensitive, also accepts `domain`) and at least 2 nameserver columns. Nameserver columns are any column whose name starts with `Nameserver`, `nameserver`, or `ns` (case-insensitive, space-tolerant). Examples that all parse:
- `Domain,Nameserver 1,Nameserver 2`
- `domain,ns1,ns2,ns3,ns4`
- `Domain,NS1,NS2`

Each row needs ≥2 nameservers. Blank cells are skipped. Rows with <2 nameservers are skipped and reported.

---

## Confirmation Step (Mandatory)

Before running the bulk script, show the user a summary and wait for explicit "go" / "yes" / "proceed":

```
Ready to update <N> domains via Porkbun's updateNs API:

Preview (first 3 rows):
  <domain1> → [<ns1a>, <ns1b>]
  <domain2> → [<ns2a>, <ns2b>]
  <domain3> → [<ns3a>, <ns3b>]
  ... (<N-3> more)

Estimated runtime: ~<N> seconds (1s sleep between calls + API latency).

Pre-flight reminders:
  - API access must be enabled per-domain in the Porkbun panel
  - DNS records must already be configured at the destination NS provider
  - Propagation: minutes to ~24-48h

Proceed?
```

Don't auto-proceed even if the user provided strong intent in the original prompt. The confirmation gate exists to catch mistakes in the CSV that only become visible when listed back to the user.

---

## Workflow

### Step 1: Validate credentials via `/ping`

Run `scripts/porkbun_ping.py` first. This calls `POST /api/json/v3/ping` which returns `200` with `{"status":"SUCCESS","credentialsValid":true,"yourIp":...}` when the keys are valid and the request IP is allowlisted.

Common failure modes the ping catches before burning through the list:
- Wrong API key or secret key → `{"status":"ERROR","message":"All API requests must be authenticated."}`
- IP not allowlisted (if the user has set an IP restriction on the key) → ditto
- Network / DNS issue talking to `api.porkbun.com` → exception

Pass keys inline so they don't persist in the shell env across calls:

```bash
PORKBUN_API_KEY='pk1_...' PORKBUN_SECRET_API_KEY='sk1_...' \
  python3 ~/.claude/skills/update-porkbun-domains/scripts/porkbun_ping.py
```

Or if the user has them in `~/.navreo-keys.env` (auto-loaded by `~/.zshrc`), no inline assignment needed.

### Step 2: Run the bulk update

Once `/ping` confirms credentials work AND the user has explicitly said "go":

```bash
PORKBUN_API_KEY='pk1_...' PORKBUN_SECRET_API_KEY='sk1_...' \
  python3 ~/.claude/skills/update-porkbun-domains/scripts/bulk_update_porkbun_ns.py /path/to/domains.csv
```

The script prints one line per domain (`OK   <domain>: [<ns>...]` or `FAIL <domain> [<status>]: <body>`), then a `Total OK` / `Total FAIL` summary. Exit code 0 if all succeeded, 1 otherwise.

### Step 3: Handle failures

If any rows failed, classify them:

- **API access not enabled on that domain** — Porkbun returns `{"status":"ERROR","message":"..."}` mentioning the domain doesn't have API access. Tell the user which domains failed, point them at Porkbun → Domain Management to toggle API ACCESS on, then offer to re-run on just the failed rows (write a new CSV with only the failing rows, re-run the script with that path).
- **Wrong keys** — `/ping` should have caught this in Step 1; if it shows up here, something rotated mid-run.
- **Network / timeout** — re-run those rows after the network recovers.
- **Domain not on this Porkbun account** — verify the domain is actually registered at Porkbun on the same account as the API keys.

### Step 4: Post-run notes

Tell the user:

1. **Propagation timing**: typically minutes, up to 24–48h fully. If the destination is Cloudflare, the dashboard will flip each domain to "Active" once it sees the new NS records.
2. **Verify in destination provider**: encourage the user to spot-check a few domains in the destination provider's panel after a few minutes to confirm propagation has started.
3. **Rotate keys if pasted in chat**: if the keys were pasted directly into the conversation rather than read from `~/.navreo-keys.env`, recommend rotating both at Porkbun → Account → API Access.

---

## Why These Design Choices

### Use `requests`, not `urllib`

The macOS system Python (`/Library/Frameworks/Python.framework/Versions/3.10/...`) doesn't ship with a working CA bundle for `urllib`. Calling `https://api.porkbun.com/...` via `urllib.request.urlopen` produces `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`.

`requests` bundles its own CA via `certifi`, so it works without any system cert config. Both libraries are pre-installed on this user's machine (`requests` 2.33.1, `certifi` at `~/Library/Python/3.10/lib/python/site-packages/certifi/cacert.pem`).

The bundled script uses `requests`. If a future environment doesn't have it, fall back to constructing an `ssl.create_default_context(cafile=certifi.where())` and passing it to `urllib.request.urlopen`.

### Why `/ping` before the bulk run

One cheap call (no rate-limit cost, no domain consumed) confirms credentials work before we start iterating. Catches all credential-class failures up front rather than reporting 38 `FAIL`s for the same reason.

### Why 1-second sleep between calls

Porkbun's rate limits aren't strictly documented but they're not generous either. A 1s sleep keeps us well under any sane bucket and adds negligible time at typical batch sizes (38 domains → ~40s instead of ~20s).

### Why a confirmation gate even with explicit intent

Reading the list back to the user lets them spot CSV mistakes (wrong column accidentally treated as NS, off-by-one in row count, wrong destination NS pair, etc.) before the API calls are made. Registry NS changes are reversible, but each reverse is a separate API call + propagation cycle, so it's cheaper to catch errors before submitting.

### Why credentials inline rather than persisted

If we `export PORKBUN_API_KEY=...` it stays in the running shell. Inline assignment on the python invocation puts the var in the process env for one call and gone. Lower exposure if the user accidentally shares their terminal.

The exception is `~/.navreo-keys.env`, which is the user's chosen centralised credential store (mode 600, auto-loaded by `~/.zshrc`). If keys are there, the script will pick them up automatically without inline assignment.

---

## CSV Format Reference

Minimum:
```csv
Domain,Nameserver 1,Nameserver 2
example.com,ns1.cloudflare.com,ns2.cloudflare.com
```

With more nameservers (Porkbun accepts up to 4):
```csv
Domain,Nameserver 1,Nameserver 2,Nameserver 3,Nameserver 4
example.com,ns1.example-dns.com,ns2.example-dns.com,ns3.example-dns.com,ns4.example-dns.com
```

Alternative header conventions (all parse):
```csv
domain,ns1,ns2
```

```csv
Domain,NS1,NS2,NS3
```

Cloudflare assigns each zone its own unique 2-server NS pair (e.g. `jaziel.ns.cloudflare.com` / `kallie.ns.cloudflare.com`). Pull this per-zone from the Cloudflare dashboard or via the Cloudflare API and put each domain's specific pair on the same row.

---

## Scripts

- `scripts/porkbun_ping.py` — Credential validation. Exits 0 if `credentialsValid: true`, else 1.
- `scripts/bulk_update_porkbun_ns.py` — Bulk runner. Reads CSV from argv[1] (default `domains.csv`), POSTs each row to `updateNs`, prints per-row result, summary, and exit code.

Both scripts use the same env vars: `PORKBUN_API_KEY`, `PORKBUN_SECRET_API_KEY`.
