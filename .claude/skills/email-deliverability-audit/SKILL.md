---
name: email-deliverability-audit
description: Diagnostic audit for a running cold email program. Checks domain authentication (SPF/DKIM/DMARC), inbox health (warmup status, reputation, smtp/imap, blocked) from Smartlead, and per-campaign + per-domain reply rate / bounce rate over a lookback window. Optionally scaffolds a Smart Delivery spam placement test (dashboard-only on most Smartlead tiers — script surfaces the UI link). Outputs markdown report + CSVs with concrete action items. Use when reply rates drop, when bounces spike, when onboarding someone else's account, or as a weekly/monthly health check.
---

# Email Deliverability Audit

**If your positive reply rate is dropping and you don't know why, start here.** Most of the time the problem is deliverability — your emails aren't reaching inboxes. This skill tells you what's broken.

## Data freshness — HARD RULE (no exceptions)

**Every audit, classification, or sweep MUST pull mailbox inventory and campaign performance live at request time.** Deliverability changes day to day (warmup blocks, DNS/MX knocks, reputation shifts, bounce drift after a list cleanup), so never:

- Reuse an `inboxes.csv` / rollup / report from earlier in the session or a prior day
- Trust a cached Notion "Mailboxes by Domain" snapshot for live health (it is downstream of Smartlead and can be hours stale)
- Carry a 7-day performance window forward without re-pulling

If the user asks for an audit and a recent pull exists, **discard it and re-pull**. Stamp every output with the live pull date + the exact lookback window so staleness is obvious at a glance. When in doubt, re-pull — it costs minutes, stale data costs wrong decisions.

(Set 2026-05-21 after a multi-day session served 2-day-old mailbox data and missed an overnight DNS knock.)

## What it checks

| Layer | What | How |
|---|---|---|
| DNS auth | SPF, DKIM, DMARC present on each sending domain | `dig` commands |
| Nameservers & domain age | Actual NS vs expected (DNSimple/Cloudflare/etc), creation date, expiry date | `dig NS` + RDAP via rdap.org |
| Inbox health | Warmup status, reputation, blocked reason, smtp/imap success, daily sent | Smartlead `/email-accounts` API |
| Signature | Sender display name matches the name in the signature; signature present; website line uses the defused `domain(.)tld` format (no clickable link) | Smartlead `/email-accounts` API (`from_name` vs `signature`) |
| Campaign performance | Sent count, reply count, bounce count, reply rate %, bounce rate % over lookback | Smartlead `/campaigns/{id}/analytics-by-date` |
| Domain performance | Aggregated campaign performance grouped by sender domain | derived locally |
| Spam placement | Inbox vs Spam vs Promotions placement via Smart Delivery | optional, dashboard fallback |

## The 1% rule — core domain-health threshold

**A healthy domain (or campaign) should have an overall reply rate of at least 1% after 200 emails sent.**

Below 1% after 200+ sends is a red flag — something is broken. The audit explicitly checks this and flags any **domain** or **campaign** that:
- Has sent ≥200 emails in the lookback window
- Has an overall reply rate <1%

> **Note on granularity:** Smartlead's public API doesn't expose per-inbox per-window analytics (the `/statistics` endpoint returns message rows without `email_account_id`). So the 1% rule is applied at the **campaign** and **domain** level, not per-inbox. Per-inbox health is judged from warmup reputation, blocked status, and smtp/imap success instead.

Possible causes when the 1% rule fires (the report's "root-cause suggestions" pinpoint which):
- Emails landing in spam (run the spam placement test, or check the Smartlead UI directly)
- Domain reputation damaged (check DMARC reports, consider domain age)
- Copy is broken (manually review for vague CTAs, generic openers; re-run `/spam-word-checker`)
- List is cold / wrong ICP (check bounce rate — if >3%, list is the problem)
- Inboxes on the domain haven't warmed enough (check warmup status)

Below 200 sends: too early to judge. The rule needs sample size.

## When to use

- Reply rate dropped by >30% week-over-week → run the full audit
- Bounces spiked above 2% → run auth + spam-placement checks
- Before scaling a campaign (make sure infrastructure is ready)
- Monthly as routine hygiene
- When taking over a Smartlead account you didn't set up

## Hard scope rules (apply every run)

- **Exclude PAUSED and COMPLETED campaigns** from default scope — only ACTIVE + STOPPED. PAUSED is a deliberate state and almost never the right thing to surface as "lingering issues". COMPLETED is by definition over. User can opt-in with `--statuses` flag if needed.
- **Always run the NS drift check** (`check_domain_ns_age.py`, see step 3.5). The script auto-cross-references `database/batches.json` to determine expected NS provider per batch, flags any drift, and prints a per-batch scoreboard. Surface every `flag_ns_drift = TRUE` row in the audit report. The Notion "Mailboxes by Domain" DB at https://www.notion.so/navreo/Mailboxes-3656e75598d980b59ba0de99f7d5a10c is the human-readable mirror of the same data.
- **Surface domains in `retired-client-mailboxes` or `Owner: RETIRED` batches that still have active mailboxes in Smartlead** — these are cleanup misses, not new findings, but they keep dragging fleet stats.

## Inputs

- `SMARTLEAD_API_KEY` (already in `~/.navreo-keys.env`)
- Optional scope flags (on each script):
  - `--client-id=X` (for sub-clients — Navreo client key `1417c9a6-...` for example)
  - `--campaign-id=X` (audit only one campaign's inboxes)
  - `--domain=example.com` (audit only one domain)
  - `--days=N` (lookback window, default 30)

## Steps

### 1. Pull the inbox inventory

```bash
python3 scripts/audit_inboxes.py --out=/tmp/audit/inboxes.csv
# optionally: --client-id=1417c9a6-... or --campaign-id=12345
```

Outputs per inbox: `id, email, domain, from_name, smtp_host, warmup_status, warmup_reputation, blocked_reason, max_per_day, daily_sent_today, smtp_ok, imap_ok, campaign_count, client_id, signature, sig_name_match`.

Health flags applied automatically:
- `flag_blocked` if `warmup_details.status == 'BLOCKED'` or `blocked_reason` is set
- `flag_smtp_fail` if `is_smtp_success == false`
- `flag_imap_fail` if `is_imap_success == false`
- `flag_low_reputation` if `warmup_reputation < 80` (as integer percent)
- `flag_sig_name_mismatch` if the sender's `from_name` does **not** appear in the signature (the signature signs off as a different person — see [§Signature standard](#signature-standard))
- `flag_sig_missing` if the inbox has no signature at all
- `flag_sig_live_link` if the signature's website line is a clickable/bare link instead of the defused `domain(.)tld` house format

The `sig_name_match` column carries the verdict: `MATCH` (every token of `from_name` is in the signature), `PARTIAL` (some but not all — e.g. first name only; worth a look but not hard-flagged), `MISMATCH` (none — the hard flag), `NO_SIG`, or `NO_FROM_NAME`.

### 2. Check domain authentication

```bash
python3 scripts/check_domain_auth.py --from-csv=/tmp/audit/inboxes.csv --out=/tmp/audit/auth.csv
```

For each unique domain, runs:

```bash
dig TXT <domain> +short                          # SPF
dig TXT default._domainkey.<domain> +short       # DKIM (most providers use "default" selector)
dig TXT _dmarc.<domain> +short                   # DMARC
```

Outputs: `domain, spf_present, spf_strict, dkim_present, dkim_selector, dmarc_present, dmarc_policy (none/quarantine/reject), notes`.

If your provider uses a non-default DKIM selector, pass `--dkim-selectors=default,google,k1,smtpapi` to try multiple.

### 3. Pull sent + reply + bounce metrics per campaign and per domain

```bash
python3 scripts/audit_performance.py --days=14 --out-campaigns=/tmp/audit/campaigns.csv --out-domains=/tmp/audit/domains.csv
# Default statuses: ACTIVE,STOPPED (PAUSED and COMPLETED excluded). Override with --statuses if needed.
```

For each ACTIVE/PAUSED campaign, calls `/campaigns/{id}/analytics-by-date` for the lookback window and pulls `sent_count`, `reply_count`, `bounce_count`. Then joins to the campaign's bound inboxes (via `/campaigns/{id}/email-accounts`) and **distributes** the campaign's sends across its inboxes' domains proportionally to inbox count per domain — giving you a domain-level rollup.

Campaign-level output columns: `campaign_id, name, status, days, sent, replies, bounces, reply_rate_pct, bounce_rate_pct, n_inboxes, n_domains, flag_low_reply, flag_high_bounce`.

Domain-level output columns: `domain, n_inboxes, n_campaigns, sent_attributed, replies_attributed, bounces_attributed, reply_rate_pct, bounce_rate_pct, flag_low_reply, flag_high_bounce`.

Flagged automatically:
- **`flag_low_reply = TRUE`** if `sent >= 200` and `reply_rate_pct < 1.0` (the 1% rule)
- **`flag_high_bounce = TRUE`** if `sent >= 50` and `bounce_rate_pct > 3.0`

### 3.5. Check nameservers + domain age + expiry (RDAP) + actual-vs-expected NS drift

```bash
python3 scripts/check_domain_ns_age.py --from-csv=/tmp/audit/inboxes.csv --out=/tmp/audit/ns_age.csv --workers=15
# RDAP via rdap.org rate-limits hard at >5 parallel; if coverage <50%, retry sequentially with --workers=3
# --db-dir=<path> to override (defaults to ../database relative to script)
```

For each unique domain runs:
- `dig NS <domain>` → records actual nameservers and classifies them by provider (cloudflare / dnsimple / azure-dns / aws-route53 / godaddy / porkbun / etc.)
- `curl https://rdap.org/domain/<domain>` → registration date and expiry date via RDAP (modern WHOIS replacement, works on .info / .biz / .com / .org / .xyz / .digital / .click / .me / .one / .online / .pro)
- **Cross-references `database/batches.json` + `database/domain_batches.csv`** to look up the expected NS provider (and optionally a pinned NS pair) for the batch this domain belongs to. Flags any drift.

Outputs: `domain, ns_records, ns_count, ns_provider_hint, created_date, expires_date, age_days, expiry_days, batch, expected_ns_provider, expected_ns_pair, ns_match, flag_no_ns, flag_new_domain, flag_expiring_soon, flag_ns_drift`.

Flagged automatically:
- **`flag_no_ns = TRUE`** if `dig NS` returns zero records (domain effectively offline)
- **`flag_new_domain = TRUE`** if `age_days < 30` (warmup risk — Gmail flags <30d domains)
- **`flag_expiring_soon = TRUE`** if `expiry_days < 60` (renewal cliff — if missed, every inbox on the domain dies overnight)
- **`flag_ns_drift = TRUE`** if the domain's batch declares an `expected_ns_provider` and the actual NS provider doesn't match it (or, if `expected_ns` is pinned, the actual NS pair doesn't match it exactly)

The `ns_match` column carries the three-state verdict:
- `TRUE` — actual matches expected (or this is a retired batch with `expected_ns_provider: DEAD` and actual is indeed empty)
- `FALSE` — drift; surface to user
- `UNKNOWN` — no batch assignment OR no `expected_ns_provider` declared on the batch; can't judge

**Per-batch drift scoreboard** is printed to stdout at the end of the run — one line per batch with `✓ matches / ✗ drift / ☠ dead / ? unknown` counts, plus detail lines for every drifted domain (showing actual provider + raw NS records). This is the primary surface for catching propagation failures, registrar mistakes, or stale documentation.

**Canonical NS mapping** lives in `database/batches.json`. Each batch has:
- `expected_ns_provider`: one of `Cloudflare` / `DNSimple` / `Azure DNS` / `Porkbun` / `DEAD` (retired-zone sentinel) / etc. Case-insensitive comparison to the actual provider hint.
- `expected_ns` (optional list): pin the exact NS hostnames. Use when the whole batch shares one pair (e.g. Boomerang's `rohin.ns.cloudflare.com` + `aurora.ns.cloudflare.com`). Set to `null` when each domain has its own per-zone NS pair (e.g. Maildoso, Hypertide-Azure on DNSimple).

When a domain has `expected_ns_provider: DEAD` (retired batch) the check inverts: any NS records that DO resolve are flagged as drift (the zone shouldn't exist).

RDAP coverage caveat: rdap.org returns empty for ~40-50% of .info domains due to GDPR restrictions at Identity Digital. Sequential retry recovers some but expect 30-50% perma-unknowns on .info. Don't treat missing date as a flag.

### 4. (Optional) Run a Smart Delivery spam placement test

```bash
python3 scripts/run_spam_test.py --campaign-id=12345
```

> **API access caveat:** Smart Delivery endpoints on `server.smartlead.ai/api/v1/sd/*` are **not exposed via API-key auth on most Smartlead tiers** (they return 404 / require session cookies). The script first probes the endpoints. If they're accessible on your tier, it runs the test end-to-end. If not, it prints the **UI link** (`https://app.smartlead.ai/app/smart-delivery`) and a paste-ready checklist of what to run there, so the audit step isn't a dead end.

When accessible, the script:
- Creates a manual placement test against the only available provider pools (G Suite + Office365, provider_ids 20, 21)
- Sends to ~200 seed mailboxes from ~100 of your senders
- Polls until completion (5–20 min)
- Pulls: providerwise, spam-filter-details, dkim-details, spf-details, blacklist
- Writes `/tmp/audit/spam-test.json`

### 5. Synthesize the report

```bash
python3 scripts/generate_report.py --audit-dir=/tmp/audit --out=/tmp/audit/report.md
```

This writes the raw `/tmp/audit/report.md` for technical reference. **For the chat-side output to the user, use the canonical 10-section tables-first format defined in [§Report format](#report-format) below.** Do NOT paste paragraph-style summaries into chat.

### 6. Act on the action items

> **Provider-first rule (message the mailbox or domain provider FIRST).** When a finding is an **MX-record problem, a domain / DNS-zone problem, or a whole batch of mailboxes being immediately rejected or hard-bouncing**, your first action is to message the provider that owns those mailboxes or that domain, *before* researching, diagnosing deeply, or trying workarounds. Why this is the default: the provider owns the infrastructure that is the root cause, it costs us nothing to ask, their support is the fastest and most authoritative path to a fix, and they will tell you exactly what needs changing. Don't spend time researching what one reply from them can answer. Identify the provider from the domain's `Batch` / `Provider` in the Notion "Mailboxes by Domain" DB and contact them:
> - **Hypertide Azure** (DNSimple NS + Outlook MX) → `support@hypertide.io`
> - **Maildoso / Boomerang / Zapmail / other mailbox provider** → that provider's own support channel
> - **Registrar / DNS-only issue** → the domain's registrar or DNS host (Porkbun, Cloudflare, etc.)
>
> Give them specifics: the affected domains or batch, the exact bounce reason or rejection message, and what you observe. Note the distinction from Smartlead support: this rule is about the **mailbox/domain provider** (the root cause), which is NOT the same as Smartlead the platform. Self-serve toggles that genuinely are self-serve (e.g. the warmup re-enable below, which does NOT need Smartlead support) still apply, but for MX / domain / batch-rejection root causes the provider message goes out first. Offer to draft the email for the user.

Feed the action items into the right next steps:
- **Missing DMARC / DKIM / SPF on a Hypertide-managed domain → email `support@hypertide.io` to publish the record.** Hypertide owns the DNS zone, so record fixes are theirs to make, not a self-serve UI change. Spot a Hypertide domain by its DNSimple nameservers (`ns1.dnsimple.com`, `ns2.dnsimple-edge.net`, etc.) combined with an Outlook MX (`*.mail.protection.outlook.com`). For a missing DMARC record, ask them to publish the fleet-standard `v=DMARC1; p=reject; pct=100;` (already on 75+ of our domains), unless the domain is under 2 weeks old, in which case start at `p=none`. This is the default action to surface to the user: offer to draft the email.
- Missing auth records on a non-Hypertide domain → fix at that provider's UI (Zapmail, Maildoso, etc.)
- Mailboxes blocked with "domain couldn't be found" / "no valid DNS entry" / "domain_does_not_exist" bounces → an unexpected nameserver or zone change knocked the domain out and Smartlead froze warmup in response. This is the MX / domain category from the **provider-first rule** above, so the order matters. Two-track fix, in this order: (1) **message the mailbox/domain provider first** for root cause and prevention (Hypertide domain → `support@hypertide.io`; other provider → its own support channel); they own the zone, so the durable fix is theirs to make. While you're at it, confirm the nameservers and zone resolve again, but trust the Smartlead bounce logs over a clean live `dig` (the zone has often self-reverted by audit time). (2) **Re-enable warmup yourself via the API; you do NOT need to message Smartlead support** for the warmup toggle (that is the platform, not the provider). A 2026-05-22 test confirmed `POST /email-accounts/{id}/warmup` flips warmup status INACTIVE→ACTIVE directly. Offer the user a bulk re-enable (see [§Reactivating warmup-disabled mailboxes](#reactivating-warmup-disabled-mailboxes-self-serve--no-smartlead-support-ticket)). The INACTIVE state is the *warmup*, not the mailbox: `is_smtp_success` stays true so these inboxes can still send campaigns; re-enabling restores reputation maintenance.
- Blocked inboxes from recipient-side hard bounces (not DNS) → tag "retired" in Smartlead UI and provision replacements
- Campaign schedule issues → Smartlead campaign schedule settings
- **Campaign with a high bounce rate (`flag_high_bounce`, >3%) → prompt the user to run MillionVerifier (`lilly-email-verification`) on its leads, and ask whether the campaign will be reused.** Scope the verification by that answer:
  - **Will be sent to again (reused) →** verify the *whole* list: every lead already contacted, plus anything still queued. A dirty list that gets reused keeps burning domain reputation, so clean all of it.
  - **One-off, won't be sent to again →** skip the already-contacted leads (no second touch is coming, so re-verifying them buys nothing) and verify only the leads still in the queue, so the remaining sends don't pile on more bounces.
  - Mechanically: export the campaign's leads from Smartlead (filter by send status for the queue-only case), then hand off to `lilly-email-verification`. Prospeo-sourced emails get the MV double-check there by default.
- Copy flagged by 1% rule → re-run `/lilly-qa` and review spam-trigger phrases manually
- **Signature flagged (`flag_sig_name_mismatch` / `flag_sig_missing` / `flag_sig_live_link`) → fix via the API** per [§Signature standard](#signature-standard). Mismatches (signature signs off as the wrong person) are the priority — group by client pool, confirm the corrected signature with the user, test one, then bulk-apply. Missing signatures on a not-yet-rolled-out fleet are expected; set them when the fleet goes live. Clickable links should be rewritten to the defused `domain(.)tld` form.

### 7. Sync per-domain results to Notion — MANDATORY

**This step is required on every audit** (standing user instruction, set 2026-05-21). After the report, **invoke the `notion-mailbox-sync` skill** — it writes the fresh per-domain health (Mailbox Count / # Active / # Blocked / # Disconnected / # Low-rep / Last Audit) into the Notion "Mailboxes by Domain" DB from this run's `inboxes.csv`, without touching the user-maintained classification fields (Owner / Provider / Registrar / Batch / Date Purchased).

Do not inline the sync logic here — `notion-mailbox-sync` is the single source of truth for the field mapping, scope (changed-domains default vs full-fleet), and the Notion write mechanism (MCP stem-search for changed-only; token + script for full-fleet). An audit is not complete until this step has run.

## Reactivating warmup-disabled mailboxes (self-serve — no Smartlead support ticket)

When Smartlead's warmup network hits a delivery error to/from a mailbox (most often a transient DNS/MX failure), it auto-sets that mailbox's `warmup_details.status` to `INACTIVE` and logs a `blocked_reason` (e.g. `domain_does_not_exist`, `no valid DNS entry`). **This is the warmup, not the mailbox.** `is_smtp_success` stays true, so the inbox can still send live campaigns — what is switched off is the background reputation-maintenance warmup. So "N inboxes inactive" is almost always "N warmups paused", not "N inboxes offline" — don't overstate it.

**You can re-enable it yourself via the API. No Smartlead support ticket needed** (proven 2026-05-22; this supersedes the old "message support" guidance).

### Endpoint

```bash
curl -X POST "https://server.smartlead.ai/api/v1/email-accounts/{id}/warmup?api_key=$SMARTLEAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"warmup_enabled":"true","total_warmup_per_day":"20","daily_rampup":5,"reply_rate_percentage":"20"}'
```

Returns `{"ok":true,"message":"Email warmup details updated successfully!"}` and flips `warmup_details.status` INACTIVE→ACTIVE instantly. Gotcha: `daily_rampup` minimum is 5 (the API 400s on anything lower).

### The offer-to-user workflow (run whenever the audit finds INACTIVE mailboxes)

1. **Detect** (live pull, per the freshness rule): count mailboxes with `warmup_details.status == INACTIVE`. Re-pull live — this number drifts day to day as some auto-recover.
2. **Offer, don't auto-fire:** "X mailboxes have warmup auto-disabled (usually a transient DNS knock). I can bulk re-enable them from here — no Smartlead support needed. Want me to?"
3. **Back up first** (reversibility): write the before-state (id, email, prior status, blocked_reason) to `audit-backups/<date>_reactivated_mailboxes.csv` so the exact set can be re-disabled if it turns out wrong.
4. **Bulk re-enable** at ≤150 req/min (account cap is 200/min — pace accordingly, with 429 back-off). Verify a sample flipped to ACTIVE.
5. **Validate it holds** — re-pull the INACTIVE count on the next audit. If they stayed ACTIVE, the DNS knock was transient and you're done. If a chunk bounced back to INACTIVE, it is a *recurring* issue: root-cause it (run §3.5 NS-drift check) rather than re-enabling again. **Re-enabling is symptom relief; repeated re-disables mean the root cause is still live.**
6. **Escalate to the mailbox provider after the second re-disable on a batch** — or on the *first* occurrence if it's clearly an infrastructure issue. If the symptom is an obvious MX / domain / batch-rejection problem from the start (not just an ordinary warmup pause), don't wait: apply the **provider-first rule** in Step 6 and message the provider now. The "wait for the second re-disable" threshold is only for cases that present as a plain warmup pause with no obvious infrastructure cause. Otherwise: if you have re-enabled warmup on a batch and it keeps disabling (the same set flips back to INACTIVE on a later audit), stop re-enabling and **message the provider that owns those mailboxes to find out why.** A whole-batch warmup wipeout that survives a re-enable is almost never something you can fix from the Smartlead side — it is the provider's infrastructure (DNS zone, MX, IP reputation, or a warmup-network block). Identify the provider from the domain's `Batch`/`Provider` in Notion and contact them:
   - **Hypertide Azure** (DNSimple NS + Outlook MX) → `support@hypertide.io`
   - **Maildoso / Boomerang / Zapmail / other** → that provider's support channel
   Ask specifically: why are warmups on these domains being auto-disabled, what is the root cause, and what is the fix/prevention. Surface the batch name, the affected domain count, and the recurring `blocked_reason` so they can act on it. Do NOT keep re-enabling on a loop in the meantime — that just masks the signal.

## Signature standard

Every sending mailbox's signature is audited on two things (both computed automatically by `audit_inboxes.py`, surfaced as `sig_name_match` + the three `flag_sig_*` columns):

**1. The sender name must match the signature.** The display name recipients see (`from_name`) has to be the same person the signature signs off as. A signature naming a *different* person is the classic copy-paste-across-mailboxes bug: the recipient gets an email "From: Jane Smithson" that's signed "Kevin Dormer", which reads as a mistake and dents trust and replies. `flag_sig_name_mismatch` catches exactly this. (Found at scale 2026-06-11: 518 Amplifyy "Client Trials (B)" inboxes were sending as Jane Smithson but signed Kevin Dormer.)

**2. The website line must use our defused-link house format.** Follow the same format we use with all of our mailboxes: the signature says **"Visit our website"** and then writes the domain with the dot in brackets so the mail client does **not** turn it into a clickable link. A live/clickable link in a cold-email signature is a deliverability risk, so the house standard is the bracketed form. `flag_sig_live_link` fires on any signature whose website line is a real clickable link (`http(s)://`, `www.`, an `<a href>` anchor, or a bare `domain.tld` with a real dot) instead of the defused form.

✅ Correct (house format): `Visit our website at amplifyy(.)com`
❌ Wrong (auto-links): `Visit our website at amplifyy.com` / `https://amplifyy.com` / `www.amplifyy.com`

**Canonical signature template** (4 stacked `<div>` lines, the website line defused):

```html
<div>{{Full Name}}</div><div>{{Role}}</div><div>{{Company}}</div><div>Visit our website at {{domain}}(.){{tld}}</div>
```

The `{{Full Name}}` must equal the inbox's `from_name`.

### Fixing signatures via the API

The signature is updatable per inbox via a **partial** update (only the field you pass is changed — daily limit, warmup, sender name are untouched). Confirmed 2026-06-11.

**Endpoint:** `POST https://server.smartlead.ai/api/v1/email-accounts/{id}?api_key={KEY}`
**Body:** `{"signature": "<div>...</div>..."}` — returns `{"ok":true,...}`.

Workflow when the audit flags signature problems:
1. **Group the flagged inboxes** by what the corrected signature should be (usually one fix per client/persona pool — the bad signatures are identical because they were pasted from one template). Pull the raw `signature` HTML of one inbox per group to preserve exact formatting; only swap the name/role/website that's wrong.
2. **Confirm the exact corrected signature with the user before firing** — it's an outward-facing change across many live inboxes. Confirm which direction a name-mismatch should resolve (fix the signature to match `from_name`, or fix `from_name` to match the signature).
3. **Test on one inbox**, re-fetch, confirm only the signature changed.
4. **Bulk-apply** at ≤150 req/min (200/min account cap — pace with 429 back-off), retry failures up to 3×.
5. **Back up first** (reversibility): write the before-state (`id, email, old signature`) to `audit-backups/<date>_signatures.csv` so the change can be reverted.
6. **Verify** a spread sample re-fetched to confirm the new signature stuck and no old name remains.

## Interpreting the numbers

### Bounce rates
- **<1%** — Excellent. Healthy list.
- **1–2%** — Normal for cold. No action.
- **2–3%** — Yellow. Check list quality, might be old emails.
- **>3%** — Red. Prompt the user to verify the list (via `lilly-email-verification`), and consider pausing. Scope by reuse: verify the whole list if the campaign will be sent to again, or only the still-queued leads if it's a one-off (see the high-bounce action item in Step 6).
- **>5%** — Stop immediately. You're damaging domain reputation.

### Spam placement
- **>90% inbox** — Great. Ship more.
- **80–90% inbox** — Acceptable.
- **70–80% inbox** — Yellow. Look at spam-filter-details to see what's triggering.
- **<70% inbox** — Red. Pause and fix auth + copy before sending more.

### DMARC policies
- **None** — Acceptable for first 2 weeks of a domain's life. After that, tighten.
- **Quarantine** — Recommended long-term. Emails that fail auth land in spam.
- **Reject** — Strictest. Only use after 30+ days of clean `rua=` reports confirming all legitimate mail passes.

### Warmup reputation
- Smartlead reports reputation as a percentage string (e.g. `"89%"`). The script strips `%` and compares as integer.
- ≥80: inbox is good to send from.
- 50–79: keep warming, don't use for critical sends.
- <50: don't send from this inbox — warmup peers aren't seeing it in their inboxes.

## Common root causes

- **SPF too lax** — `v=spf1 +all` whitelists everyone. Use `v=spf1 include:<provider> ~all` or similar.
- **DKIM missing** — new domain, selector not published. Most providers publish at `default._domainkey`.
- **DMARC alignment failure** — From-domain doesn't match SPF/DKIM domain. Usually a misconfigured reply-to or a 3rd-party sender.
- **Too many inboxes per domain** — Gmail flags domains with >3–5 inboxes as suspicious. Keep it at 2–3/domain.
- **Aggressive warmup ramp** — Jumping from 5 to 40/day in one week = flag. Ramp over 2–4 weeks.
- **Shared sending IP with spam traffic** — Most providers use shared pools. If someone else on your IP spammed, you suffer.

## What to do next

**If any flag fired:** triage the most critical ones first (blocked inboxes, missing DKIM on actively-sending domains) before fixing warnings.

**If all clean:** next Monday, run this again. Reputation changes propagate slowly — don't expect to see fixes reflected for 7–14 days.

## Related skills

- `lilly-qa` — pre-launch quality checks on a campaign (catches copy + spintax + variable issues)
- `lilly-email-verification` — verify a lead list deliverability before importing (kills bounce-rate spikes)
- `lilly-bot` — base Smartlead skill; all campaign operations

## Scripts

- `scripts/audit_inboxes.py` — pull + format inbox inventory; also audits each signature (sender-name match + missing + clickable-link checks → `sig_name_match` and `flag_sig_*` columns)
- `scripts/check_domain_auth.py` — dig-based SPF/DKIM/DMARC checks
- `scripts/check_domain_ns_age.py` — dig NS + RDAP for registration date / expiry; cross-references `database/batches.json` to flag drift from expected NS provider per batch; flags broken NS, <30d-old, <60d-expiring
- `scripts/audit_performance.py` — per-campaign + per-domain sent/replies/bounces from analytics (applies the 1% rule)
- `scripts/run_spam_test.py` — create + poll + pull Smart Delivery test (UI fallback if API not exposed)
- `scripts/_smart_delivery.py` — shared Smart Delivery API wrapper
- `scripts/generate_report.py` — synthesize all CSVs into markdown report

## References

- `references/smart-delivery-api.md` — Smart Delivery endpoints + UI fallback procedure
- `references/dns-records.md` — SPF/DKIM/DMARC record templates + interpretation guide

## Communication style

When delivering audit results to the user: use plain English. Don't say "campaigns failing the 1% rule" — say "campaigns where less than 1 in 100 people replied". Don't say "DMARC policy=none" — say "DMARC is set up but doesn't enforce anything yet". Reserve jargon for the report itself (which is for technical reference); make the chat summary readable to a non-technical operator.

The chat output must follow the canonical structure in [§Report format](#report-format) — TL;DR paragraph at the top, one big metrics table, then numbered "Top problems ranked" with short prose + inline tables + "Cost in plain English" callouts where applicable, then a recommendations table, then offer-next bullets, then file paths.

## Report format

This is the **canonical structure** for every deliverability audit chat output. Always use these sections, in this order. The format is a hybrid: short prose for diagnosis and ranked problems, tables for the numbers and the recommended actions.

**Status emoji convention** (use consistently):
- 🔴 critical / red / stop-immediately / today
- 🟡 medium urgency / watch / this week
- 🟢 acceptable / cleanup / this month
- ⭐ gold standard / benchmark
- ⚠️ caveat / footnote-worthy

### §1. Title

`# Deliverability Audit — <DD Month YYYY>`

### §2. TL;DR

One short paragraph (2-4 sentences). Lead with the headline diagnosis ("The fleet is bleeding reputation" / "Healthy with one watch-item" / etc.). Include: emails sent in window, reply count, reply rate, bounce rate, what % of campaigns and domains fail the 1% rule. Close with the single root-cause hypothesis ("biggest problem is list quality, not infrastructure" — or whatever the data says).

### §3. The numbers

One table, no sub-tables. Every row shows Metric / Value / Verdict. Use bold on critical rows.

| Metric | Value | Verdict |
|---|---|---|
| Inboxes audited | N across M domains | — |
| Inboxes still bound to active campaigns | ~X of N | M orphans worth cleaning |
| Emails sent (Nd) | N | — |
| Replies (Nd) | N | — |
| Reply rate | X.XX% | 🔴/🟡/🟢 (with threshold note) |
| Bounce rate | X.XX% | 🔴/🟡/🟢 (with threshold note) |
| Campaigns failing 1% rule | X of N (Y%) | 🔴/🟡 |
| Domains failing 1% rule | X of N (Y%) | 🔴/🟡 |
| Domains over 3% bounce rate | X of N (Y%) | 🔴/🟡 |
| Domains missing DKIM | N | 🟡 medium urgency |
| Domains missing DMARC | N | 🟡 medium urgency |
| Domains with DMARC p=none | N | 🟢 acceptable short-term |
| Domains on expected NS (matches batch) | N of M senders | 🟢 |
| Domains drifted off expected NS | N | 🔴 each = batch documentation lying or registrar mistake |
| Domains with NO nameservers (broken) | N | 🔴 each = silent deliverability hit (or 🟢 if expected — retired batches) |
| Domains expiring in <60 days | N | 🔴 each = renewal cliff |
| Domains <30 days old (warmup risk) | N | 🟡 |
| Inboxes where sender name ≠ signature | N | 🔴 each = email signed by the wrong person |
| Inboxes with no signature | N | 🟡 (🟢 if a not-yet-rolled-out fleet) |
| Inboxes with a clickable link in signature | N | 🟡 should use the defused `domain(.)tld` format |

### §3.5. Breakdown by batch / bucket

One table grouping the fleet by the Notion `Batch` field (or domain-name-pattern inference if not all Notion rows fetched). Surfaces which client / persona pool is healthy vs bleeding.

| Batch | Domains | Inboxes | Blocked | Sent 14d | Reply % | Bounce % | NoNS | DNS | CF |
|---|---|---|---|---|---|---|---|---|---|
| navreo-bjion-henry | … | … | … | … | …% | …% | … | … | … |
| amplifyy-kevin-dormer | … | … | … | … | …% | …% | … | … | … |
| arnic-jacki-arnic | … | … | … | … | …% | …% | … | … | … |
| client-backups-jane-smithson | … | … | … | … | …% | …% | … | … | … |
| andrea-henderson | … | … | … | … | …% | …% | … | … | … |
| olivia-duncan | … | … | … | … | …% | …% | … | … | … |
| retired-client-mailboxes | … | … | … | … | …% | …% | … | … | … |
| UNKNOWN (need Notion verification) | … | … | … | … | …% | …% | … | … | … |

One-line callouts under the table:
- Flag any `retired-client-mailboxes` row with `Inboxes > 0` — cleanup miss
- Flag any UNKNOWN with `Sent 14d > 0` — domain in active circulation but unclassified in Notion
- If a batch has dominant NS provider X but a minority on Y, note the drift

### §4. Top problems, ranked by how much they're hurting you

Numbered sections (1, 2, 3, 4, 5 — usually 3-6 items). Each item:

- **Bold header** = one-line problem statement with the headline number
- 1-3 sentences of plain-English diagnosis naming concrete domains/campaigns/inboxes
- Optional inline table when listing top-N offenders (worst 5 campaigns / domains)
- Optional "**Cost in plain English:**" italic callout when there's a quantifiable upside ("if you got bounces down to 1%, you'd add ~8,000 deliverable sends/month back")

Example shape:

> **1. List quality — your top emergency**
>
> 139 of your active domains are bouncing at over 3%. Worst cluster: every arnic-themed sender domain (arnic.biz, arnicbiz.biz, arnicbiz.info, arnicbizsolutions.biz, arnicbizsolutions.info) — all at 0.65% reply rate with bad bounces. This isn't a domain problem; it's the same lead list hitting every send-as variant. The list itself needs verifying.
>
> *Cost in plain English: if you got bounces down to 1%, you'd add ~8,000 deliverable sends/month back to the same domain pool without changing anything else.*

Rank order: bleed-rate × addressability. List quality / SMTP fails / 1% rule failures usually win the top slots; DKIM/DMARC gaps come lower because they're slower to bite.

### §5. What I recommend doing this week

One table. Priorities are time-anchored, not P0/P1/P2.

| Priority | Action | How |
|---|---|---|
| 🔴 today | … | `lilly-bot` / Smartlead UI / etc |
| 🔴 today | … | … |
| 🔴 this week | … | … |
| 🟡 this week | … | … |
| 🟢 this month | … | … |

### §6. What I can do next

A short bullet list (3-5 items) of concrete offers Lilly can fire immediately. Use the pattern "Produce …", "Run …", "Re-audit in 7 days …". Each bullet ends with the *deliverable*, not the action ("paste-ready, not 'go figure out which ones'").

### §7. Where the raw data lives

Bullet list of CSV/markdown paths with row counts, plus a footer note about durability:

- `/tmp/audit/inboxes.csv` — N rows with per-inbox health
- `/tmp/audit/auth.csv` — N domains × SPF/DKIM/DMARC
- `/tmp/audit/ns_age.csv` — N domains × actual nameservers, registration date, expiry date, age/expiry flags
- `/tmp/audit/campaigns.csv` — N campaigns with Nd performance
- `/tmp/audit/domains.csv` — N domains with Nd performance (attributed)
- `/tmp/audit/report.md` — auto-generated markdown report

> These are in /tmp so they'll vanish on reboot. Say the word and I'll move them somewhere durable (Google Drive / Notion).

### What NOT to do

- ❌ No "Critical issues / Warnings / Action items" prose lists (the old skeleton-style format).
- ❌ No 10 separate split tables for fleet/inboxes/DNS/distribution — they all belong in §3 "The numbers" as one table.
- ❌ No P0/P1/P2 labels in recommendations — use 🔴 today / 🔴 this week / 🟡 this week / 🟢 this month.
- ❌ No closing "Want me to fire any of the P0/P1 actions?" line — replaced by §6 "What I can do next" bullets.
- ❌ No emoji in the TL;DR — keep it prose, save the colour for tables.
