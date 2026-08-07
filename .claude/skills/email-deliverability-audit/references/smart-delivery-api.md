# Smart Delivery API Reference

Smartlead's Smart Delivery feature runs inbox-placement tests against seed
mailboxes at G Suite and Office365 to measure what % of your sends actually
land in the inbox vs spam vs promotions tabs. It's the ground truth for
deliverability.

## API access caveat

**Smart Delivery is not consistently exposed via API-key auth across all
Smartlead account tiers.** Public docs reference several endpoint shapes:

- `POST /api/v1/smart-delivery/manual-placement-tests`
- `POST /api/v1/smart-delivery/tests`
- `POST /api/v1/sd/spam_test`

…but the Navreo account (and most non-enterprise tiers) returns 404 on all of
these. The `/api/v2/smart-delivery/list` endpoint responds with
`"Please login to continue"` — meaning Smart Delivery uses session-cookie auth
from the logged-in dashboard, not API keys.

`scripts/_smart_delivery.py` probes all known variants and returns `None` if
none respond. `scripts/run_spam_test.py` falls back to printing dashboard
instructions when that happens.

## Dashboard URL

```
https://app.smartlead.ai/app/smart-delivery
```

## Dashboard procedure (when API isn't available)

1. Open the dashboard URL.
2. Click **+ New Test** → **Manual Placement Test**.
3. Pick the campaign you want to test.
4. Pick ~100 senders from that campaign (or "All" if the campaign has <100
   inboxes).
5. Leave provider pool default — G Suite + Office365 are the only two
   consistently available.
6. Click **Run**. Test takes 5–20 minutes typically.
7. When complete, the result panel shows:
   - **Folder placement**: Inbox / Spam / Promotions / Updates breakdown per
     provider
   - **Spam filter details**: which Gmail/Outlook spam triggers fired (e.g.
     `DKIM_INVALID`, `SPF_SOFTFAIL`, `URL_REPUTATION`)
   - **DKIM/SPF details**: whether each seed mailbox saw your DKIM/SPF as
     passing
   - **Blacklist**: which (if any) RBLs your sending IP is on

## Interpreting placement

- **>90% inbox** — Great. Ship more from this campaign / domain set.
- **80–90% inbox** — Acceptable. Worth investigating any single provider
  that's <60%.
- **70–80% inbox** — Yellow. Look at the per-provider breakdown. If Outlook
  is the laggard, check DKIM specifically (Outlook is the strictest on DKIM
  alignment).
- **<70% inbox** — Red. Pause campaign expansion until you fix auth + copy
  + warmup state.

## Exporting results for the audit report

If you ran the test from the dashboard, you can drop the exported JSON into
the audit dir as `spam-test.json` and re-run `generate_report.py` to fold
the result into the report. The expected shape (based on observed Smartlead
responses) is:

```json
{
  "status": "COMPLETED",
  "providerwise": [
    {"provider": "Gmail", "inbox_count": 86, "spam_count": 12, "promotions_count": 2},
    {"provider": "Outlook", "inbox_count": 71, "spam_count": 28, "promotions_count": 1}
  ],
  "spam_filter_details": [...],
  "dkim_details": [...],
  "spf_details": [...],
  "blacklist": [...]
}
```

If your dashboard exports a different shape, the report still includes the
raw JSON in a fenced code block — no schema validation is enforced.

## Provider IDs (when API IS available)

If your tier does expose the API, the only consistently-available provider
pools for the manual test flow are:

| ID | Provider |
|----|----------|
| 20 | G Suite  |
| 21 | Office365 |

Other provider IDs may exist for automated tests on enterprise tiers — those
aren't covered here.

## Cost

Each Smart Delivery test consumes Smartlead "test credits" from your account
balance. Manual tests in the dashboard typically cost 1 credit per test
regardless of the sender count (subject to Smartlead's pricing changes).
