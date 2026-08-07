---
name: campaign-leads-hub-ship
description: Rebuild the campaign detail Leads area in the signals tool into one leads hub - replace the "Sample of the live audience" card with a lists.html-identical interactive grid (first 50 leads + Download-all-CSV button), fold the Sources tab's cards in under that grid (tab removed, old hash redirected), add an "Add more leads" copy-ready Claude prompt card wired to lilly-strategy, and strip the optimisation pills from the header. Finishes only when a 5-account-strategist panel scores the page 9/10+ on both "see what's in the campaign" and "add new leads easily". Trigger: "ship the campaign leads hub", "replace the audience sample with the leads grid", "/campaign-leads-hub-ship".
---

# Campaign Leads Hub - ship

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule first - if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same - only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step FAILED with the reason, continue only to steps that don't
depend on it, and surface every FAILED step in the final report. Never declare done on
a cap-hit.

## Goal

**A strategist opening any campaign sees, on one Leads tab: the real audience (a
lists-view-identical grid of the first 50 leads with a Download button for all of
them), where every lead came from (the source cards, directly under the grid), and a
one-copy path to adding more (an "Add more leads" prompt card that drops a
campaign-aware lilly-strategy brief onto the clipboard).** No Sources tab, no
optimisation pills in the header. Done means a 5-account-strategist panel scores the
page **9/10 or higher** on BOTH axes: ease of seeing what's in the campaign, and ease
of adding new leads / campaign ideas.

## Config (baked)

```yaml
PROVING_CAMPAIGN: 3507283      # Navreo | Distributors [June] - 15.8k leads, 3 sources
GRID_CAP: 50                   # rows shown; Download is the door to the full list
LEADS_API: /api/campaign-platform-leads   # exists; paginated, limit<=100, returns
                                          # name/email/company/title/status/replied
CSV_ENDPOINT: /api/campaign-leads-csv     # NEW - streams ALL leads as CSV
PANEL_PERSONAS: 5              # account strategists; ALL must score >= PANEL_BAR
PANEL_BAR: 9                   # out of 10, on both axes
PANEL_ITERATION_CAP: 3         # redesign loops before surfacing failure
RETRY_CAP: 3
```

## Ground truth

- Repo `~/navreo-signals` (LIVE deploy source - NOT any iCloud copy); push main →
  Render auto-deploy (~2 min); poll `/api/version` until the new commit serves. Live
  verify with the minted `navreo_session` cookie ([[signals-live-verify-recipe]]).
- Design mirror source: `app/lists.html` grid - toolbar (~L380-401: Download btn,
  `svgDownloadIcon`, search, Filter, Sort, columns, Start row/Rows, ‹ 1-N of M ›
  cluster), Clay-density row CSS, `downloadListCsv` (~L1171). The campaign grid must
  be visually indistinguishable from this.
- Anchors in `app/campaigns.html`: tab nav ~L3046-3047 (Leads + Sources links);
  Leads tab-panel ~L3109-3111 holds the "Sample of the live audience" ov-card
  (`#leads-sample`, filled by `hydratePlatformLeads` ~L3714, 15 rows); source cards
  render via `hydrateDraftSources` ~L3130 (`#draft-sources-section`, incl. the
  Pull-more panel shipped by sources-pull-more-ship - it must survive the move);
  header insight pills ("Zero positives", "list audit", …) built as `badges` ~L3019
  from `KIND_LABEL`/`TAG_META`.
- Server: `app/server.py` - `campaign_platform_leads` ~L6555, routed ~L14766.
  Smartlead pages 100 at a time via the owning workspace's key.
- Hash law ([[campaigns-overview-hash-shape]]): bare `#/c/<id>` is Overview; a
  removed tab's hash must REDIRECT, never bounce.
- Design system: `app/navreo.css`, one orange per screen. Insights stay on Overview -
  only the header pills die.

## Steps

### Step 1 - The leads grid (replace the sample)
In the Leads tab-panel, delete the "Sample of the live audience" card and its 15-row
table; render the lists.html grid in its place: same toolbar, same row density, same
column chrome, columns EMAIL · FIRST_NAME · LAST_NAME · COMPANY_NAME · STATUS ·
REPLIED, fed by ONE `LEADS_API` call with `limit=GRID_CAP`. Search/Sort/Filter act on
the 50 loaded rows; the count cluster reads honestly ("1-50 of 15,824"); a footer line
says "First 50 - Download for the full list." Add the Download button (lists.html
style): hits `CSV_ENDPOINT` (new handler in `app/server.py` that pages the platform
API to the end and streams every lead as CSV - honest filename `<campaign>-leads.csv`).
- **Done-rule:** on `PROVING_CAMPAIGN` the grid renders 50 real rows and is
  side-by-side indistinguishable from lists.html (screenshot pair); the downloaded
  CSV's row count equals Smartlead's total for the campaign.

### Step 2 - Sources move under the grid; tab dies
Remove the Sources tab link and panel; render the source cards (name, people count,
"pushed to Smartlead · date", View the list) and the Pull-more panel UNDER the leads
grid in the Leads tab, under a plain "Sources" section label. Router: `#/c/<id>/sources`
redirects to `#/c/<id>/leads`.
- **Done-rule:** no Sources tab anywhere; all three proving-campaign source cards +
  Pull-more render under the grid with nothing lost; the old /sources hash lands on
  Leads without a bounce.

### Step 3 - "Add more leads" prompt card
At the bottom of the Leads tab, one design-system card: title "Add more leads", one
orange **Copy prompt** button, and this prompt (campaign name/id filled client-side):

> Add more leads to "{{campaign_name}}" (Smartlead campaign {{campaign_id}}). First
> pull this campaign's full picture: targeting and ICP so far, every source list
> already pushed, and lead performance - who replied, who was positive, who booked
> (use lilly-optimiser + lilly-data). Then run lilly-strategy focused on THIS
> campaign: suggest new lead ideas that either top it up or justify a sibling launch,
> never re-pitching dead angles and netting every idea against contact_history +
> suppressions. When I approve an idea, pull the list and route the upload through
> /lilly-upload-gate into campaign {{campaign_id}} (or the new sibling).

- **Done-rule:** card renders on live; Copy puts the full prompt on the clipboard
  with the real campaign name + id; pasting it into a fresh Claude session triggers
  the history-first → lilly-strategy chain (spot-check the trigger, not a full run).

### Step 4 - Kill the header pills
Stop rendering the insight badge pills in the campaign header. "Runs in Smartlead ·
active" and Open in Smartlead stay. The insight system and Overview cards are
untouched.
- **Done-rule:** proving campaign's header shows zero pills on live; Overview still
  shows its insight cards; grep confirms the badge markup is gone from the header
  render only.

### Step 5 - Deploy + live verify
Commit+push; poll `/api/version` until the new commit is live; with the minted cookie,
browser-verify DOM-first on the LIVE host, proving campaign: grid (50 rows, real
data), Download CSV completes with full count, sources + Pull-more under the grid, no
Sources tab, /sources hash redirect, prompt copies, no header pills, zero console
errors.
- **Done-rule:** every check above passes on live in one pass; screenshot proof
  captured.

### Step 6 - Strategist panel (the bar the task sets)
Run `PANEL_PERSONAS` distinct account-strategist personas (runs campaigns daily,
audits lists, ideates top-ups) through the live page. Each scores 1-10 on BOTH axes:
(a) how easily they can see what leads are in the campaign and where they came from,
(b) how easily they can add new leads / spin a new campaign idea from here. ALL
scores >= `PANEL_BAR` on both axes. Below-bar feedback → fix → re-run ONLY the steps
whose done-rules the fix touches → re-panel (max `PANEL_ITERATION_CAP` loops).
Scores + reasons recorded verbatim - never invented, never averaged past a fail.
- **Done-rule:** a recorded round where every one of the five scores >= 9/10 on both
  axes; every prior round's fixes listed.

### Step 7 - Record
Update memory (project note: leads hub shipped - grid cap, CSV endpoint, sources
moved, pills gone, prompt card), publish the skill per convention, final report with
per-step status, panel scores, any FAILED steps.
- **Done-rule:** live host serves the shipped commit; memory updated; report
  delivered.

## Hard don'ts
- Never render more than `GRID_CAP` rows in the grid - Download is the only door to
  the full list.
- Never break the Pull-more panel or its gated pipeline while moving sources - and
  never add any raw-push control.
- Never leave `#/c/<id>/sources` bouncing (hash law).
- Never delete the insight system - only the header pills.
- Never fake, average, or round up a panel score - an 8.9 is a fail.
- Never exceed a retry cap or report done while any done-rule fails.
