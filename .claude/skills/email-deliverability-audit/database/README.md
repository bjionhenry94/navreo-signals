# Inbox Infrastructure Database

Maps every sender domain in the Smartlead fleet to its infrastructure batch (registrar + mailbox provider + expected DNS nameserver provider). Used by `email-deliverability-audit` to flag findings with batch context.

## Files

| File | Purpose | Format |
|---|---|---|
| `batches.json` | Batch definitions (registrar, mailbox provider, expected NS) | JSON |
| `domain_batches.csv` | Per-domain assignment to a batch (one row per domain) | CSV |
| `health_snapshot.json` | Point-in-time per-batch health stats (re-generate after each audit) | JSON |
| `lookup_batch.py` | Helper: `python3 lookup_batch.py <domain>` returns batch info | Python |

## Schema

### `batches.json`

```json
{
  "batches": {
    "<batch_key>": {
      "label": "<human-readable name>",
      "registrar": "<Porkbun|GoDaddy|...>",
      "mailbox_provider": "<Boomerang|Maildoso|Hypertide|...>",
      "expected_ns_provider": "<Cloudflare|DNSimple|...>",
      "expected_ns": ["ns1.x.com", "ns2.x.com"] or null,
      "added": "YYYY-MM-DD",
      "notes": "<provenance, migration history, gotchas>"
    }
  }
}
```

`expected_ns` is null when each domain in the batch has its own unique NS pair (e.g. Maildoso auto-provisioned Cloudflare zones).

### `domain_batches.csv`

```
domain,batch,inbox_count,source,notes
navreo.info,boomerang-cloudflare,3,user-declared-2026-05-19,
bridgeandscale.info,hypertide-dnsimple,5,inferred-from-default-rule-2026-05-19,
```

Source values:
- `user-declared-<date>` — explicitly assigned by user input on that date
- `inferred-from-default-rule-<date>` — assigned by default rule (anything not in another batch goes to the fallback batch, currently `hypertide-dnsimple`)

## Update patterns

### Adding a new batch

1. Append the batch to `batches.json` under `batches`
2. Add the explicit domains to `domain_batches.csv` with `source = user-declared-<today>`
3. Re-run `lookup_batch.py --validate-fleet /tmp/audit/inboxes.csv` to confirm 100% coverage

### Migrating a batch to new NS

1. Update `expected_ns` (or `expected_ns_provider`) on the batch in `batches.json`
2. Update `notes` with the migration date
3. Re-run the audit + `lookup_batch.py --health` to confirm fleet matches expectation

### Moving a domain from one batch to another

Edit the `batch` column for that row in `domain_batches.csv`. Add a `notes` cell explaining why.

## Default fallback rule

Any fleet domain not explicitly assigned to a batch goes to the `hypertide-dnsimple` bucket per the user's 2026-05-19 rule:

> "Any remainers are more than likely to be from Porkbun, mailboxes from Hypertide, and should have DNSimple nameservers"

If this assumption ever breaks (new mailbox provider added, etc.), update this README + the audit logic.

## Used by

- `email-deliverability-audit` — uses this DB to flag findings with batch context (e.g. "37 boomerang-cloudflare domains expected at Cloudflare but are still on DNSimple")
- (planned) `lilly-bot` — could use this to confirm a campaign's inbox set matches a single batch (avoid mixing Maildoso + Hypertide inboxes in one campaign by accident)
