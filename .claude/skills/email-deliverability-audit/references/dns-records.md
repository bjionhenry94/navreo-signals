# DNS Records — SPF, DKIM, DMARC

Email auth checks the audit runs, what good records look like, and how to
fix common failures.

## SPF (Sender Policy Framework)

**What it does:** lists which IPs / providers are authorised to send mail
"from" your domain.

**Where it lives:** TXT record at the apex of your domain.

```
dig TXT example.com +short
```

**A healthy SPF record:**
```
v=spf1 include:zapmail.com include:_spf.google.com ~all
```

The trailing `~all` is "soft fail" — receivers should *quarantine* (not
reject) mail not matching the listed senders. `-all` is "hard fail" —
receivers should reject. Both are acceptable; `~all` is the conservative
default.

**Bad:**
- `v=spf1 +all` — wide-open. Anyone can send as you.
- No `all` mechanism — defaults to neutral, no enforcement.
- Multiple SPF records on the same domain — only one is allowed; receivers
  will reject all of them as `permerror`.

**The audit's `spf_strict` column** is TRUE only when the record contains
`~all` or `-all` and does NOT contain `+all`.

**Common fix:** edit the SPF record at your DNS provider (Cloudflare,
Porkbun, GoDaddy, Route53). If Zapmail or another email provider manages
your DNS, fix it from their UI — they may overwrite manual edits.

## DKIM (DomainKeys Identified Mail)

**What it does:** cryptographically signs outgoing mail with a key that
receivers verify against a public key in your DNS.

**Where it lives:** TXT record at `<selector>._domainkey.<domain>`. The
*selector* is provider-specific:

| Provider | Default selector |
|---|---|
| Zapmail / Maildoso | `default` |
| Google Workspace | `google` |
| SendGrid | `s1`, `s2` |
| Mailgun | `k1` |
| AWS SES | `selector1`, `selector2` |
| Microsoft 365 | `selector1`, `selector2` |

```
dig TXT default._domainkey.example.com +short
```

The audit script tries `default,google,k1,smtpapi,selector1,selector2` by
default — override with `--dkim-selectors`.

**A healthy DKIM record:**
```
v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQ...
```

The `p=` part is the public key — long base64 string. Length depends on
key size (1024-bit = ~200 chars, 2048-bit = ~390 chars).

**Common fix:** if `dkim_present == FALSE` for an actively-sending domain,
the selector might be wrong. Check the email provider's UI for the
correct selector. If Zapmail/Maildoso shows DKIM as published in their UI
but `dig` returns nothing, the record may have been added to the wrong DNS
zone (e.g. a subdomain instead of apex).

## DMARC (Domain-based Message Authentication, Reporting & Conformance)

**What it does:** tells receivers what to do when a message fails SPF or
DKIM alignment ("alignment" = the From: domain matches the SPF / DKIM
domain).

**Where it lives:** TXT record at `_dmarc.<domain>`.

```
dig TXT _dmarc.example.com +short
```

**Three policies, in order of strictness:**

| Policy | What receivers do | When to use |
|---|---|---|
| `p=none` | Just monitor — deliver normally, send reports | First 2 weeks. Verify all your legitimate senders pass. |
| `p=quarantine` | Failing mail goes to spam folder | Long-term default. Use after `p=none` reports look clean. |
| `p=reject` | Failing mail is bounced. | Only after 30+ days of clean reports. Strictest. |

**A healthy starter DMARC record:**
```
v=DMARC1; p=none; rua=mailto:dmarc-reports@example.com; aspf=r; adkim=r
```

The `rua=` is where aggregate reports get sent (daily, summarizing what
passed/failed). Set it to a real mailbox or a DMARC reporting service
(e.g. dmarc.postmarkapp.com, EasyDMARC) to actually see the data.

**A healthy mature DMARC record:**
```
v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc@example.com; aspf=s; adkim=s
```

The `s` on `aspf=` and `adkim=` is "strict alignment" — From: domain must
match exactly. `r` is "relaxed" — subdomain matches count.

**Common failure:** misconfigured reply-to (e.g. `Reply-To: support@othercorp.com`
when sending from `you@example.com`) creates an alignment problem. SPF +
DKIM may pass on `example.com` but DMARC fails because the From: domain
doesn't match the underlying authenticated domain.

**Common fix sequence:**
1. Start with `p=none` + `rua=` reporting for 14 days.
2. Read the reports — identify any legitimate senders that fail.
3. Fix their SPF/DKIM alignment.
4. Tighten to `p=quarantine`.
5. After another 14–30 days, tighten to `p=reject` if you want maximum
   protection from spoofing.

## Quick troubleshooting matrix

| Symptom | Likely cause | Fix |
|---|---|---|
| `dkim_present == FALSE` | Wrong selector, or DKIM never published | Verify selector at provider UI; re-publish |
| `dmarc_policy == none` for >2 weeks | Procrastination | Tighten to `p=quarantine` |
| `spf_strict == FALSE` | `+all` or no `all` mechanism | Change to `~all` (soft) or `-all` (hard) |
| `dmarc_present == FALSE` | Never added | Add starter record (`v=DMARC1; p=none; rua=...`) |
| Multiple SPF records | Tools added duplicates over time | Consolidate into one record with combined `include:` directives |

## Tools

- `dig` (built into macOS/Linux) — the audit script's primary tool.
- [mxtoolbox.com](https://mxtoolbox.com/SuperTool.aspx) — UI for sanity-
  checking the same records.
- [dmarcian.com](https://dmarcian.com/dmarc-inspector/) — DMARC-specific
  inspector with reading of `rua=` reports.
