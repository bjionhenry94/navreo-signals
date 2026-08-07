---
name: campaigns-all-visible
description: Static orchestration skill that makes EVERY Smartlead campaign visible on the live cockpit at navreo-signals.onrender.com/app/campaigns.html, and keeps it that way. Fixes the root cause that the campaign list is built from the AI crunch cache (campaign_insights) instead of from the campaign inventory (campaign_scorecard), so any campaign Claude has not crunched is invisible no matter that Smartlead knows about it. Ships a scorecard-driven list, a no-insight row state, a coverage guard, and a standing Smartlead-vs-tool reconciliation. Fixed steps, per-step LIVE done-rules, retry cap, Loop Training Mode toggle (ON by default). Use when the user says "campaigns are missing from the tool", "why isn't this campaign showing", "run campaigns-all-visible", "make all campaigns visible", or "/campaigns-all-visible".
---

> **SUPERSEDE NOTE (2026-08-02, platform-wide-stabilise):** app/campaigns-classic.html was REMOVED from the repo and live site (it 404s). Any step or done-rule below that expects it to serve/render is historical — skip or adapt it; the campaigns cockpit at app/campaigns.html is the only campaigns page.

# campaigns-all-visible

## LOOP TRAINING MODE  ->  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for Bjion's explicit approval before starting the next.
- Before running a step, check its done-rule FIRST. If it already passes, **skip the step**, say so in one line, move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap still applies. Never loop a step forever.

**When OFF**
- Run every step autonomously, no pauses.
- Still check every done-rule, still honour the retry cap. Report once at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule. On cap-hit: stop that step, record it FAILED with the reason, continue to the next step, surface it in the final report. Never silently exceed.

---

## THE GOAL

Every campaign that exists in Smartlead is accounted for on `https://navreo-signals.onrender.com/app/campaigns.html`: either it renders as a row, or it sits in a **named, deliberate** exclusion bucket that the page states out loud. No campaign is ever invisible just because Claude has not written about it yet.

---

## THE ROOT CAUSE (already diagnosed 25 Jul 2026, do not re-derive)

`app/campaigns.html` `join()` (around line 2202) builds the list by iterating `byScope`, which is built from `/api/cockpit/insights` rows only. `/api/campaign-scorecard` is used **only as a join** (`sc[scope]`), never as a row source.

Result: **insight-gated, not campaign-gated.**

Measured on 24 Jul 2026 data:

| Source | Count |
|---|---|
| `campaign_scorecard` rows (Smartlead inventory) | 1,053 |
| of those, status ACTIVE | 136 |
| distinct scopes with live unexpired `campaign_insights` | **45** |
| rows the page can therefore render | **45** |

All six campaigns in Bjion's screenshot (3710792, 3710654, 3710554, 3710405, 3709667, 3709470) are present and correct in `campaign_scorecard` with real sent counts. Every one has `live_insights = 0`. The Smartlead sync is **not** broken.

Second failure mode, same table: every live insight row was written by a **single** crunch (24 Jul) and expires 27 to 31 Jul. There is no rolling coverage. If the morning crunch misses a day, the page empties itself.

A precedent for the fix already exists in the file: the deep-link "ghost" path (around line 3294) already renders a campaign page from scorecard stats alone when there is no insight. That pattern just was never applied to the list.

---

## GOTCHAS FOUND ON THE FIRST RUN (25 Jul 2026, shipped `e1b1c22`)

- The row source is not the only gate. `renderRows()` has a **second** hardcoded list, `tiers = [decision, watch, fine]`, that silently dropped 893 unreviewed rows after `join()` was fixed. Same bug one layer down. Check both.
- `/api/campaign-scorecard` selected `name` from Supabase but never copied it into the response, so every un-crunched row rendered as "Campaign 3710654". Fixed in `_all_campaign_scorecard`.
- `/api/cockpit/live-status` hard-caps at **150 ids**. With the full inventory on the list, make `liveBucket` fall back to the synced status or the Status filter empties, and choose which 150 ids to spend the cap on (running campaigns first).
- Smartlead `GET /campaigns` returns the **whole** workspace unpaginated (935 in one call, verified). No pagination needed. The real inventory bug was the opposite: no **pruning**, so campaigns deleted in Smartlead lingered forever. Prune only off a non-empty list.
- Booting the app locally starts the scorecard sync thread and burns the Smartlead rate limit. Kill it before any manual `/campaigns` pull, and use `curl`, never `urllib` (SSL trust store).
- 4 draft campaigns are genuinely nameless in Smartlead. "Campaign &lt;id&gt;" is the correct honest fallback, not a bug.

## STANDING LAWS

- **Additive, never replace.** Do not touch `app/campaigns-classic.html`. Confirm any removal with Bjion first.
- **Deploy source:** `~/navreo-signals`, branch `main`, Render auto-deploys on push. The iCloud copy is deprecated and reverts edits. Never edit it.
- **LIVE-verify or it is not done.** Only the rendered page on `navreo-signals.onrender.com` counts. Anonymous curl proves nothing (the auth gate 302s everything). Verify with an authed same-origin fetch or a minted-cookie authed curl, and read the DOM, not screenshots.
- A campaign with no insight must render as an **honest** row: real stats, no prose, no invented verdict. Never fake a tag.
- No em dashes anywhere in UI copy.
- Times render browser-local with the timezone named.

---

## THE STEPS

### Step 0 - Pin ground truth
- `~/navreo-signals` clean, on `main`, level with `origin/main`.
- Pull the current inventory: count `campaign_scorecard` rows by status, and count distinct live unexpired `campaign_insights` scopes. Record both numbers as the "before".
- Decide the **render set** with Bjion (Training Mode ON: ask; OFF: use the default). Default render set = every campaign in `campaign_scorecard` that is not `ARCHIVED`. ARCHIVED and DRAFTED go behind a stated filter, not a silent drop.
- **Done-rule:** repo clean on `main`, plus a written before-count and an agreed render set.

### Step 1 - Make the scorecard the row source
- In `app/campaigns.html` `join()`: build the row set from `STATE.scorecard.campaigns` (filtered to the agreed render set), then LEFT JOIN insights onto it by scope. Insights decorate a row; they no longer create one.
- Campaign with no insight renders with: name (from scorecard `name`), live status chip, sent / replied / positives / bounced / total from the scorecard, and a neutral "Not yet reviewed" pill instead of a tag. No teaser, no fabricated verdict.
- Keep the mid-sync zero guard, the drift marker, and the full-row click target. Reuse the existing ghost-detail path so a no-insight row still opens its campaign page.
- **Done-rule:** on the LIVE host, an authed DOM read of `campaigns.html` returns a row count equal to the render set size (within the stated filter), and all six screenshot ids render by name.

### Step 2 - Close the expiry cliff
- A row must never vanish because prose aged out. When a scope's insights are expired or missing, the row still renders from the scorecard and the prose area says when it was last reviewed, or "Not yet reviewed".
- **Done-rule:** simulate by excluding the newest crunch from the insights payload; the row count does not drop.

### Step 3 - Coverage guard (this is the "going forward")
- Add a coverage check that runs with the daily crunch and writes its result where the page can read it: `scorecard non-archived count` vs `rendered row count` vs `scopes crunched`.
- Surface it on the page as one honest line, for example "1,053 campaigns tracked · 45 reviewed by Lilly · 0 unaccounted for". Unaccounted-for > 0 renders as a visible warning, not a silent pass.
- Repoint the morning crunch so its scope list is driven by the scorecard (every ACTIVE campaign), not by a curated list. If volume forces a cap, the cap must be **stated on the page**, never silent.
- **Done-rule:** the coverage line renders live with correct numbers, and "unaccounted for" reads 0.

### Step 4 - Harden the inventory feed
- `_scorecard_sync_all()` in `app/server.py` calls `GET /campaigns` with no pagination. Confirm it returns the full set per workspace. If Smartlead pages it, paginate and **stop only on an empty list**, never on an error mid-page (a rate-limit error reads as end-of-list and silently truncates).
- Keep the 0.28s pace and the batched upserts. One bad campaign must never abort a cycle.
- **Done-rule:** a full sync cycle logs a campaign count that matches the live Smartlead count per workspace, and the newest campaign created today appears in `campaign_scorecard` within one cycle.

### Step 5 - Ship and LIVE-verify
- Commit, push `main`, wait for the Render deploy, then verify on the live host with an authed DOM read. Not a local render, not a source grep.
- **Done-rule:** the page loads, the row count is right, the six screenshot campaigns are visible by name with correct sent counts, and the coverage line reads 0 unaccounted for.

---

## THE FINAL DONE-RULE (cross-platform reconciliation)

The loop is done only when **two platforms are reconciled by id**:

1. **Platform A, Smartlead:** pull every campaign across every enabled workspace (`get_campaigns`, per workspace key). Set A = all ids.
2. **Platform B, the tool:** authed DOM read of the live `campaigns.html`, plus `/api/campaign-scorecard`. Set B = all rendered ids.
3. Compute `A \ B` and `B \ A`.

**PASS requires all three:**
- `A \ B` contains only ids in a named exclusion bucket (ARCHIVED, DRAFTED) that the page states, and **zero** ACTIVE campaigns.
- `B \ A` is empty. The tool never invents a campaign Smartlead does not have.
- For 5 spot-checked campaigns picked at random from A, sent / replied / positives shown in the tool match Smartlead's `/analytics` exactly.

Print the reconciliation as a table: total in Smartlead, total rendered, excluded-by-bucket with the bucket named, and unaccounted-for. **Unaccounted-for must be 0.** Anything else is a FAIL, no matter how good the page looks.

---

## FINAL REPORT (always, both modes)

- Before and after counts: scorecard rows, ACTIVE, rendered rows, crunched scopes.
- The reconciliation table above.
- Every step: PASSED / SKIPPED (already passing) / FAILED with reason and retry count.
- Commits pushed, with sha.
