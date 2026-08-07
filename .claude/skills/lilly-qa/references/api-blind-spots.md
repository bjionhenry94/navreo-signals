# API Blind Spots

Things the SmartLead read API doesn't expose. Always include this section in the report so the user knows what wasn't checked.

## Cannot verify via API

| Setting | Where to check in UI |
|---|---|
| Mailbox assignment to campaign | Campaign → Email Accounts tab |
| Per-mailbox sending limits | Campaign → Email Accounts → individual mailbox |
| Email signature content per mailbox | Settings → Email Accounts → mailbox → Signature |
| Open-rate tracking enabled/disabled | Campaign → Settings → Tracking |
| Click-rate tracking enabled/disabled | Campaign → Settings → Tracking |
| Send as plain text setting | Campaign → Settings → Optimise Email Delivery |
| Force plain text setting | Campaign → Settings → Optimise Email Delivery |
| Email Variant & Spintax Distribution Mode (Randomized vs Sequential) | Campaign → Settings → Variant Distribution |
| Sending pattern split (50/50 follow-up vs new lead) | Campaign → Settings → Prioritise sending pattern |
| Timezone | Campaign → Schedule |
| Sending days (Mon-Fri vs other) | Campaign → Schedule |
| Sending window (start-end hours) | Campaign → Schedule |
| Daily sending limit | Campaign → Settings → Max New Leads Per Day |
| Schedule start date | Campaign → Schedule |
| Suppression / blocklist attached | Settings → Blocklist |
| Unsubscribe list applied | Settings → Unsubscribed |
| Sub-sequence trigger conditions | Campaign → Master Inbox → Sub-sequences |
| Whether the campaign is assigned to a client | Campaign → Settings → Client |

## Flag these in the report

Always include this section verbatim (or close to it):

> ## 🚫 Cannot verify via API (need UI eyeballs)
>
> - Mailbox assignment + signatures + per-mailbox sending limits
> - Open-rate / click-rate tracking toggles
> - Plain text + force plain text settings
> - Distribution mode = Randomized
> - 50/50 sending pattern
> - Schedule (timezone, days, hours, daily limit, start date)
> - Suppression / blocklist
> - Lead list (status, count, personalisation columns)
> - Sub-sequence trigger conditions

The user is expected to tick these manually before launch. Do NOT pass them silently — even a clean QA report with this section should leave the user clear on what's been verified and what hasn't.
