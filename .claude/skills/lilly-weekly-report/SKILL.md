---
name: lilly-weekly-report
description: "Generate weekly campaign performance reports for Lilly clients from Smartlead data. Covers a 7-day window (default: previous Monday to previous Sunday), scoped to a single client's campaigns, delivered as a Slack-paste message (the default deliverable) following the Hypersight template - per-campaign sections with Status / Sent / Replies / Reply Rate / Positive Replies / Insight, plus an Overall summary and Next steps - with an optional PDF (Cloneify Report template) only when the user explicitly asks. The report is also saved into the client's Notion portal (Project Files / Weekly Reporting) and a client-share link plus message template are produced. Use whenever the user asks for weekly reporting, campaign performance summary, weekly client update, Monday morning report, or any variant. Trigger on phrases like 'weekly report', 'campaign performance report', 'Monday report', 'weekly campaign update', 'last week's stats for [client]', 'send [client] their weekly update'. Pairs with lilly-bot (Smartlead API conventions, no-em-dashes rule) and lilly-optimiser (recommendations framing)."
---

# Lilly Weekly Report 📊
### Weekly Campaign Performance Reporting - Persistent Instructions

---

## Identity
You are the Lilly weekly reporter. Pull Smartlead analytics for a single client across a 7-day window, group sensibly, classify positive replies with user input, and produce the deliverable: a Hypersight-style Slack message for the client channel (the default). A Cloneify-style PDF is optional, generated only when the user explicitly asks.

The cadence is weekly. The default trigger is Monday morning, reporting on the previous calendar week (Mon to Sun).

---

## When to use this skill
- "send me Arnic's weekly report"
- "Monday report for [client]"
- "campaign performance for last week"
- "weekly stats for [client]"
- "give [client] their weekly update"
- Or scheduled invocations on Monday morning (see Scheduling below)

## When NOT to use this skill
- Single-campaign deep dives -> use lilly-bot directly
- Strategy decks / recommendation documents -> different deliverable, not weekly cadence
- Lifetime / all-time program review -> change the window manually if the user explicitly asks, but flag that this is outside the weekly default
- Reporting on multiple clients in one document -> not the intent; run once per client

---

## Required inputs at invocation time

The user MUST provide (or you MUST ask before proceeding):

1. **Client name** (e.g. "Arnic", "Cloneify"). Used to filter campaign names. Match case-insensitively, substring match.
2. **Smartlead API key** for the relevant account. If not in environment or memory, ask.

The user MAY provide (otherwise use defaults):

3. **Window**. Default: previous Monday to previous Sunday (full calendar week). Format: ISO `YYYY-MM-DD`.
4. **Known positive reply counts per campaign**. Smartlead's `interested` flag is rarely populated reliably, so positive reply counts come from manual master-inbox classification. Ask the user before finalizing the report.
5. **LTV** (Lifetime Value per converted lead). Used to compute expected revenue per the reporting guide: `expected revenue = LTV x positive responses`.
6. **Excluded campaign filter** (e.g. "exclude any campaign with Navreo in the name"). Useful where the same Smartlead account hosts multiple clients.

---

## Workflow

### Step 1 - List and filter campaigns

- Call `GET https://server.smartlead.ai/api/v1/campaigns?api_key={KEY}`
- Save the response to a file (do not dump it to terminal output)
- Filter by name containing the client string, case-insensitive
- Apply any user-specified exclusion filters (e.g. "no Navreo")

**CRITICAL: Always verify the filtered list with the user before fetching analytics.** Show the campaign IDs and names, ask the user to confirm or refine the filter. This follows the lilly-bot data protection convention and prevents accidental cross-client data exposure.

### Step 2 - Compute the window

- Default (scheduled Monday-morning run): `end_date = yesterday (Sunday)`, `start_date = yesterday - 6 days (previous Monday)`
- Default (manual run): `end_date = today`, `start_date = today - 7 days`
- Manual override allowed via user input

### Step 3 - Fetch date-filtered analytics

For each filtered campaign, call:
```
GET https://server.smartlead.ai/api/v1/campaigns/{id}/analytics-by-date?api_key={KEY}&start_date={start}&end_date={end}
```

Save each response to a separate file for auditability. Verified Smartlead behavior:
- This endpoint correctly filters by date
- Returns `sent_count`, `reply_count`, `bounce_count`, `unique_sent_count` within the window
- The `analytics` endpoint (without `-by-date`) returns lifetime totals; do NOT use that for weekly reports

### Step 4 - Confirm scope, then group and aggregate

First confirm the report scope with the user (keep it short and simple, per the SOP). Offer three levels:
- **Headline only** - report just the live campaign(s) carrying the volume; one sentence noting any older/legacy campaigns are winding down, no legacy numbers. Usually the right default.
- **Headline + legacy roll-up** - lead with the live campaign(s), and roll older/archived campaigns that still sent inside the window into a single "legacy (winding down)" line.
- **Itemize everything** - list every campaign that sent in the window separately (longest, most detailed).

Note: archived campaigns can still have sent inside the window (they were archived part-way through the week), so always check analytics-by-date for them rather than assuming archived = zero sends.

If grouping is needed (client has more than 6 active campaigns), group by theme to keep the report digestible:
- Combine Soft + Hard variants of the same theme
- Roll up "Reconnect:" series under one section
- Roll up underperformers (sub-0.3% reply rate) into a single "Other active campaigns" section

Compute per-group totals: sent, replies, reply rate. Round reply rate to 2 decimal places.

Identify:
- Top performer by combined volume + rate (the "scale candidate")
- Highest reply rate (might be small volume but worth reproducing)
- Lowest reply rate (the "pause or rewrite" candidate)
- Largest volume sender (often a different campaign than the top performer)

### Step 5 - Classify positive replies

**Do NOT rely on Smartlead's `interested` lead-stat field.** In practice, teams rarely mark leads as Interested in the master inbox, so the API value is often 0 even when positive replies exist.

Instead:
- Ask the user explicitly for positive reply counts per top campaign before finalizing
- For campaigns where the user does not provide a count, mark the Positive Replies field as `(pending master inbox review)` rather than fabricating
- Surface this caveat in the Observations section

### Step 6 - Generate the PDF (optional, only on request)

The Slack message (Step 7) is the default deliverable. Only build a PDF when the user explicitly asks for one.

When asked, use the parameterized builder at `scripts/build_report_pdf.py` in this skill directory. It takes a dict of sections + observations + recommendations and outputs the PDF in the Cloneify style.

Default output path: `~/{client_lowercase}-weekly-report-{end_date}.pdf` (the user's home directory). Override allowed via user input.

### Step 7 - Generate the Slack-paste version (default deliverable)

Plain text following the Hypersight template (see below). No HTML, no `<br>` tags. Use ` - ` and ` to ` instead of em dashes.

### Step 8 - Upload to the client portal (default), then surface the client-share link

Every report is also saved into the client's Notion portal so there is a permanent, client-visible record, not just a Slack DM. This is the default; skip only if the user says not to.

The portals live in the **Active Clients** database (`2616e75598d98022b3a7fde57d29ad14`). For each client:
1. Find the client's row in Active Clients (match on Name), and open its child **[Client] | Client Portal** page.
2. Open the **Project Files -> Weekly Reporting** sub-page of that portal. This page is a **container/index only** - it holds one child page per week, never the report bodies stacked onto a single page.
3. **Create a new, unique child page for this week** under the Weekly Reporting page (use `notion-create-pages` with the Weekly Reporting page as the parent). **Each week gets its own page - never append a new week onto an existing week's page or onto the container.** Title the page exactly `Week of {start} to {end}` (e.g. `Week of 25 to 31 May 2026`). Put the full report body **inside that new page**: a short bold phase label (e.g. `**First branded week (live program)**`), the roll-up bullets (`Emails sent`, `Replies (rate)`, `Positive replies`), then `**What we learned**`, `**What we're doing about it**`, and `**Summary**`. Use Notion bold / bullets, not a fenced code block. No em dashes. The newest week naturally sorts to the top of the child-page list.
4. If sending capacity changed this week, `update_properties` the **Sending Capacity** text field on the client's Active Clients row.
5. Build the client-share message from the template below and hand it to the user together with **the link to this week's report page** (the child page you just created, not the container page).

**Confirm before writing**: the portal is client-visible. On the first run for a client, or whenever the campaign list or wording is ambiguous, confirm with the user before posting (see Step 1).

**Client share template:**

> Hi {first_name}, your weekly report is up in your portal. It's a quick view of last week's performance, what we learned, and what we're doing about it this week: {this_weeks_report_page_link}
> Happy to walk through any of it on our next call.

---

### Step 9 - Deliver

- Output the Slack message inline in chat, in a fenced code block, so the user can copy-paste (this is the default deliverable)
- If a PDF was generated (only when the user asked), also output its file path as a markdown link
- Output the link to this week's report page (the child page created in Step 8) and the filled client-share template
- Note any caveats (e.g. positive reply counts pending)
- Only include the `Expected Revenue` line (`LTV x positive responses`) if the user provided an LTV; otherwise omit it entirely

---

## PDF template (Cloneify style)

Build with the parameterized script at `scripts/build_report_pdf.py`.

Visual conventions:
- Letter portrait, 0.9 inch margins
- Helvetica throughout, near-monochrome (black + thin grey rules)
- Title: 24pt bold, "Campaign Performance Report"
- Subtitle: 11pt muted grey, "Reporting window: {start} to {end}"
- Section headings: 14pt bold, numbered ("1. {client} - {campaign}")
- Bullets under each section: Status, Emails Sent, Replies → Reply Rate, Positive Replies → Positive Reply Rate (if known)
- Insight paragraph: 10.5pt regular, begins with "**Insight:**"
- Thin horizontal rule between campaign sections
- Two final sections: "Overall Observations" (bulleted) and "What we're doing this week" (numbered, framed in agency voice - see convention below)
- Footer on each page: "{client} - Weekly Performance Report | {start} to {end} | page N"

---

## Slack template (Hypersight style)

Plain text. No HTML, no `<br>`. Use real line breaks. No em dashes.

```
Hey {@client},

Reporting to you with campaign stats from {start} to {end}:

{Campaign 1 name}
Status: Active
Emails Sent: {n}
Replies: {n} -> Reply Rate: {pct}%
Positive Replies: {n} -> Positive Reply Rate: {pct}%
Insight: {one-sentence why}

{Campaign 2 name}
... (one block per campaign or group)

Overall: {one-paragraph summary, the WHY}

Next steps:
- {action 1}
- {action 2}
- {action 3}

These stats are estimated based on what we're seeing in your inboxes - please correct us if there are inaccuracies.

{Expected Revenue: $X (LTV ${L} x {N} positive responses)}   <- only if LTV provided
```

---

## Style conventions (inherited from lilly-bot)
- **Never use em dashes (—)** anywhere. Use ` - ` or ` to ` instead. This rule applies to PDF copy, Slack copy, and grammar-check passes.
- Never use HTML tags in user-facing Slack output
- For PDF output, use ReportLab Platypus with Helvetica, near-monochrome, letter portrait, 0.7-0.9 inch margins
- Keep insight paragraphs short (2-4 sentences). Explain the WHY, not just the WHAT

## Agency voice in recommendations (CRITICAL)

The report is delivered FROM Lilly TO the client. The recommendations section reports on what **we (the agency) are doing on the client's behalf**, not what the client should go and do themselves.

**Always frame recommendations in first-person plural, present continuous or simple present.** "We're scaling X." "We're pausing Y." "We're rewriting Z." "We're holding W for another week of data."

**Never use bare imperatives that read as instructions to the client.** "Scale X." "Pause Y." "Rewrite Z." These are internal Lilly notes, not client-facing language.

| Wrong (client-imperative) | Right (agency voice) |
|---|---|
| Find the winning magnet inside LinkedIn Followers Soft. | We're pulling per-variant data this week to identify the winning magnet inside LinkedIn Followers Soft. |
| Continue the Reconnect push. | We're continuing the Reconnect push and planning a second wave for next week. |
| Wind down the original Campaign 4. | We're winding down the original Campaign 4 and migrating its lead inventory into Reconnect: C4. |
| Reduce LinkedIn Followers Hard volume. | We're cutting LinkedIn Followers Hard volume and rotating in the Reconnect-style Hard variants. |
| Pause Volume with Industry and Sparkle. | We're pausing Volume with Industry and Sparkle to free mailbox bandwidth for Reconnect. |
| Hold Sales Leader for another week of data. | We're holding Sales Leader for another week of data before deciding whether to migrate it into Reconnect: Sales Leader. |

If a recommendation depends on input from the client (e.g. positive reply classification, LTV input, decisions on direction), frame it as a question or a flagged-for-client-input item, not an imperative:
- "We'd like your read on whether to keep the Sales Leader originals running or migrate the list into Reconnect: Sales Leader."
- "Pending your master inbox review on positive replies for LinkedIn Followers Soft - we'll finalise the variant retention decision once we have those counts."

Same voice applies to the Slack message's "Next steps" section.

---

## Reporting guide (from "How to give clients weekly reporting")

- Explain WHY the stats are as they are over Slack
- Expected revenue is LTV multiplied by positive responses
- Keep it short and simple
- Always include "These stats are estimated based on what we're seeing in your inboxes - please correct us if there are inaccuracies."

---

## Worked example: Arnic weekly report

User says: "send me Arnic's weekly report"

1. **List campaigns** -> filter for `arnic` in name, EXCLUDE any with `navreo` in name (per user's standing instruction)
2. **Confirm** the 22 matching campaigns with the user
3. **Window**: today minus 7 days (e.g. 2026-05-05 to 2026-05-12)
4. **Fetch** analytics-by-date for each of the 22
5. **Group** into 5-6 sections:
   - Reconnect Series (8 campaigns rolled up)
   - LinkedIn Followers - Soft (the 8-magnet test)
   - LinkedIn Followers - Hard
   - Campaign 4 - Partner-Focused (Soft + Hard combined)
   - Sales Leader (Soft + Hard combined)
   - Other active campaigns (Volume + Campaign 1 + Sparkle rolled up)
6. **Ask user** for positive reply counts (e.g. "2 in LinkedIn Followers Soft, others TBD")
7. **Build PDF** with sections + observations + recommendations
8. **Build Slack message** with the same structure compressed to plain text
9. **Output** both, note caveats

---

## Scheduling (every Monday morning)

This skill is designed to be invoked on a Monday cron schedule.

To set up the schedule, use the `schedule` skill:
- Cron expression: `0 9 * * 1` (9 AM every Monday, in the user's local timezone)
- Trigger prompt: `lilly-weekly-report for {client}` (replace `{client}` with the actual client name)
- The skill should default to "previous Mon to previous Sun" window when triggered automatically

Alternative manual scheduling:
- macOS launchd plist with `StartCalendarInterval` for Monday 9 AM
- The launchd job invokes the skill via Claude Code CLI

For multiple clients, create one scheduled task per client. Do NOT batch multiple clients into one invocation; each client's data must be reviewed for positive-reply counts separately.

---

## Important notes

- **API keys**: never log or expose in terminal output. Save raw responses to files in `/tmp/` for auditability.
- **Campaign filtering**: ALWAYS confirm the filtered campaign list with the user before fetching analytics. This prevents cross-client data exposure when a Smartlead account hosts multiple clients (e.g. the Arnic account contains both Arnic and Navreo campaigns).
- **Positive reply data**: never fabricate. If unknown, mark as `(pending master inbox review)`.
- **File output**: PDF is optional (only when the user asks); default path `~/{client_lowercase}-weekly-report-{end_date}.pdf`. Honor user overrides.
- **Date format in filename**: use ISO `YYYY-MM-DD` so files sort chronologically.
- **Em dashes**: zero tolerance. Run a final grep for `—` over both PDF and Slack output before delivering.
