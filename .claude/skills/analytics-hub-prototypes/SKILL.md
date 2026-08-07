---
name: analytics-hub-prototypes
description: Static orchestration skill — prototype the brand-new Navreo ANALYTICS HUB page. Builds 5 minimal, highly-visual prototypes of one central analytics page (deliverability with the inbox/domain manager table kept exactly as-is, lead counts + lead runway, campaign performance, who's replying, outreach needle movers, which messaging works) as self-contained pages under app/prototypes/ with mock data, every chart carrying a plain-language AI takeaway. Judged by a simulated panel of 5 non-technical founders and sales leaders at a 9/10 bar on actionable insights, easy to digest, and beauty of design. Use when the user says "run the analytics hub prototypes", "prototype the analytics page", "build the new analytics dashboard", or "/analytics-hub-prototypes".
---

# Analytics Hub Prototypes

## Loop Training Mode — TOGGLE (flip this line to change behaviour)

**Loop Training Mode: OFF** ← flipped 2026-07-26 per Bjion. Change to `ON` to pause at every step.

- **ON**: pause at EVERY step and wait for Bjion's explicit approval before
  continuing. Before starting a step, check its done-rule first — if it already
  passes, report "Step N already passes, skipping" and move to the next pause.
  Only re-run steps that fail. Show what you're about to do before doing it.
- **OFF**: run all steps end-to-end with no pauses, but still check every
  done-rule and respect the retry cap.
- **Retry cap (both modes)**: max **3 retries per step**. On cap-hit, HALT that
  step, record it FAILED with honest scores/reasons, and surface it in the final
  report. Never inflate a score to pass. Never loop forever.

## Goal

One brand-new central analytics page that a non-technical founder opens and — with
zero training — sees what's working, what isn't, and what to do today to book more
meetings. Every label in language a 16-year-old understands. Less explanation, more
intuitive design: **if it needs explaining, it's already too complicated.** Build
**5 prototypes**, each a genuinely different layout concept for the same content,
and prove them against a founder panel at a 9/10 bar.

## Fixed context (verified 2026-07-26 — re-verify in Step 1, don't trust blindly)

- Source of truth is the git/Render repo `~/navreo-signals` (push to `main`
  auto-deploys). The iCloud copy is DEPRECATED — never edit it.
- There is NO analytics page today — insights are scattered across
  `app/deliverability.html` and `app/campaigns.html`. This hub is new.
- The **inbox/domain manager table** is rendered inside `app/deliverability-tab.js`
  (the "Inbox and domain manager" sub-tab). Lift its markup + styles VERBATIM into
  every prototype. It is the one element that must not be redesigned.
- Prototypes live at `app/prototypes/analytics-hub-p1.html` … `p5.html`:
  self-contained, inline mock data, zero API calls, zero production writes.
- House rules: no emoji in UI; colour IS severity; charts are inline SVG — no chart
  libraries; read the `dataviz` and `navreo-design-system` skills before the first
  line of markup. Panels are agent-simulated reviews, never preview_click puppeteering.
- "AI-driven" here means: every chart/number carries ONE plain-language takeaway
  (≤12 words, e.g. "Tuesday gets you double the replies — send more on Tuesday").
  The page tells you what to do; it never just shows numbers.

## What every prototype must answer (same six, different layout)

1. **Are my emails landing?** — deliverability at a glance + the inbox/domain
   manager table, unchanged.
2. **Do I have enough leads?** — signals found, new campaigns added, and a lead
   runway countdown ("at this pace you run out of leads on Aug 14").
3. **Which campaigns are winning?** — and which to pause.
4. **Who actually replies?** — the type of person (title, industry, company size).
5. **What moves the needle?** — deliverability, response time, best days, how fast
   we reply.
6. **Which messages work?** — the copy/angle getting the replies.

## The five prototypes (pairwise distinct concepts, not skins)

| # | Concept | The idea |
|---|---|---|
| P1 | **The Briefing** | One column, reads top-to-bottom like a morning brief: big verdict line, then "Working / Not working / Do this today" cards. |
| P2 | **The Scoreboard** | Big-number tiles (meetings, replies, runway, health) + one hero chart. Everything else one click deep. |
| P3 | **The Funnel** | The whole page is one pipeline: leads → sent → replies → positives → meetings. The leak glows, with its fix beside it. |
| P4 | **The Rhythm** | Time-first: day×hour reply heatmap, response-speed dial, best-day callouts. "When" is the hero. |
| P5 | **The Coach** | Impact-ranked fix cards ("Fix this first: +3 meetings/mo"), each expandable to its evidence chart. |

## Steps

### Step 1 — Baseline map
Read `app/deliverability-tab.js` (extract the inbox/domain manager table markup +
token sheet), skim `app/campaigns.html`, and name the real data source behind each
of the six questions (Smartlead analytics endpoints, Supabase sync tables) so mock
data mirrors reality.
**Done-rule**: a ≤1-page note with the extracted table markup, the token sheet, and
each of the six questions mapped to its real data source.

### Step 2 — Build P1–P5
Build the 5 pages in `app/prototypes/` per the table, all fed by ONE shared mock
fixture that contains findable stories: one campaign dying, leads running out in
~19 days, Tuesday doubling replies, one message variant clearly winning, slow
reply-speed costing meetings. Every prototype covers all six questions, embeds the
table verbatim, and pairs every visual with its ≤12-word takeaway. No jargon
anywhere ("3 in 10 people reply", never "29.7% RR").
**Done-rule (per prototype)**: loads clean at 1440×900 with zero console errors and
zero network; all six questions answered; table markup identical to production;
every chart has its takeaway; every planted story is findable in under 30 seconds.

### Step 3 — Founder panel
Spawn 5 simulated panelists as subagents: **3 non-technical founders** (do their own
outreach, allergic to dashboards) and **2 sales leaders** (judge tools by whether
their team would open them daily). Scenario: *"Five minutes before your next call
you open this page. What's working, what isn't, and what will you do today to book
more meetings?"* Each scores every prototype 1–10 on three axes — **actionable
insights**, **easy to digest**, **beauty of the design** — plus the single worst
moment. House rule: if a panelist had to ask what anything means, easy-to-digest
caps at 8 for that prototype.
**Done-rule**: 25 scorecards (5 panelists × 5 prototypes), each with three axis
scores + a worst-moment quote.

### Step 4 — Fix loop
Any prototype scoring **under 9 on any axis from any panelist** gets its worst
moments fixed and is re-panelled (re-panel = a retry, max 3). Only re-run failing
prototypes. Over-simplification that hides a needed answer is a defect too.
**Done-rule**: all 5 prototypes at **9/10+ on all three axes from all five
panelists**. Cap-hit = FAILED-BAR with honest final scores; never inflate.

### Step 5 — Deploy + hand-off
Push the 5 prototype files to `main` (additive only — stage exactly the 5 new
files, `git fetch` + ff-only merge first, confirm `git diff` shows nothing but the
prototypes; production pages untouched). Confirm the URLs respond, then deliver the
report in chat: the 5 URLs, the full scorecard table, the recommended winner with
one-line reasoning per prototype, and a graduation checklist (≤10 items) for making
the winner the production analytics page. Bjion picks; nothing merges into
production inside this loop.
**Done-rule**: 5 live URLs + report with scorecard table + winner + checklist
delivered in chat.

## Done-rule (whole loop)

The loop is DONE when Step 4's bar is met (every prototype 9/10+ on all three axes
from all five panelists — or cap-hit honestly reported as FAILED-BAR), the 5
prototypes are live, and Step 5's report is delivered. Production pages, data, and
the inbox/domain manager table stay untouched — prototypes and report only.

## Hard don'ts

- Never redesign, restyle, or "improve" the inbox/domain manager table.
- Never add explainer paragraphs, legends that need studying, or tooltips required
  to understand a chart — fix the design instead.
- Never use a chart library, emoji in UI, or jargon a 16-year-old wouldn't get.
- Never call production APIs or write production data from a prototype.
- Never simulate the panel with preview_click puppeteering.
- Never exceed a retry cap or report done while any done-rule fails.
- Never edit the iCloud copy of the repo.
