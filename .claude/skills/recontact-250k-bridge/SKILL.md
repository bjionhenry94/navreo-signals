---
name: recontact-250k-bridge
description: Static orchestration skill that bridges the gap to 250,000 prospects going out next month by building recontact campaigns from Navreo's own history. Finds the largest past campaigns that got no traction, rebuilds their lists as net-new recontact pools (sales leaders, CEOs and similar, B2B only; no South America, Southern Asia or Africa), nets out anyone in an active campaign or contacted in the last 30 days, keeps only verified emails, and packages briefs with a lead-magnet / free-training offer. One fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle (ON by default). Use when the user says "run the 250k recontact bridge", "bridge the volume gap with recontact", "build the recontact campaigns for next month", or "/recontact-250k-bridge".
---

# recontact-250k-bridge

## Loop Training Mode (the toggle - edit this line to flip it)

**LOOP_TRAINING_MODE: OFF**

* **ON:** pause at EVERY step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule. Only re-run steps that fail. Retry cap applies.
* **OFF:** run all steps autonomously, no pauses, but keep every done-rule check and the retry cap.

**Retry cap:** 3 attempts per step. On the 3rd failure, HALT the loop and report exactly which done-rule failed and why. Never loop past the cap.

## Goal

Find enough recontact volume to bridge toward **250,000 prospects going out next month**. Full coverage is not required - every packaged batch that passes the done-rule counts. Prioritise the LARGEST past campaigns first, especially big lists (e.g. Prospeo/SPO pulls) that historically got no traction. The new angle is a **different offer: a lead magnet or free training** (service-based magnets only - NEVER an audit offer, house rule).

## Hard gates (apply to every lead, no exceptions)

1. **Net-new only:** NOT currently in any active campaign, and NOT contacted in the last 30 days (check `sent_messages` for any outbound, not just first contact).
2. **Role:** sales leaders (CRO, VP/Head/Director of Sales) or CEO/founder/MD and similar top roles.
3. **B2B businesses only.**
4. **Geo:** exclude South America, Southern Asia, and Africa. Otherwise relaxed.
5. **Verified email required** (re-verify - old verifications go stale).
6. Suppressions and exclusions via `v_exclusion` / `check_exclusions`, client-scoped, as always.

## Steps

### Step 1 - Measure the gap
Count leads already committed for next month: leads loaded in ACTIVE Smartlead campaigns (live statuses, all relevant workspaces) cross-checked against Supabase `contact_history` + `campaigns`. Gap = 250,000 minus committed.
**Done-rule:** one gap number reported with its denominators (committed count, campaign list). Numbers shown, not asserted.

### Step 2 - Rank the source campaigns
From Supabase, list finished/paused/drained campaigns by lead count, join reply performance (positives per 1k sends; fetch `sent_count` live from Smartlead analytics, ~0.35s throttle). Sweep ARCHIVED and ACTIVE SIBLING campaigns too (house rule). Rank: biggest lists with weakest traction first.
**Done-rule:** a ranked table exists with, per campaign: lead count, sends, positives per 1k, and a recontact-priority order.

### Step 3 - Build the raw recontact pool
For the top-ranked campaigns (work down the list), pull their leads from `contact_history` and apply the role, B2B, and geo gates.
**Done-rule:** per-campaign filter waterfall (started with X, role gate left Y, geo gate left Z). No campaign in the pool without its waterfall.

### Step 4 - Net the pool
Drop anyone who is: in ANY active campaign, contacted in the last 30 days (any outbound in `sent_messages`), on `v_exclusion` / `suppressions`, or a duplicate email across batches.
**Done-rule:** netted counts per campaign, and a re-run of the overlap query returns ZERO rows against active campaigns and last-30-days sends.

### Step 5 - Verify emails
Run the surviving pool through email verification (use the `lilly-email-verification` skill). Keep only leads with a verified email.
**Done-rule:** every remaining row is verification-passed; report kept vs dropped counts.

### Step 6 - Package the campaign briefs
Batch the verified pool into campaign-sized briefs, largest sources first. Each brief: source campaign it recontacts, netted verified count, the gates it passed, and the new angle (lead magnet or free training offer - to be written via `lilly-recontact` / `lilly-copywriter` at build time, never an audit offer). Report cumulative packaged total vs the Step 1 gap.
**Done-rule:** briefs saved with list files and counts; cumulative total stated against the gap. STOP HERE - no Smartlead upload happens inside this loop. Uploads go through `lilly-upload-gate` as a separate, explicitly approved action.

## Global done-rule (the loop is DONE when)

Every packaged lead is confirmed: (a) in no active campaign, (b) no outbound to them in the last 30 days, (c) verified email, (d) passes role/B2B/geo gates - and the packaged briefs plus their cumulative total vs the 250k gap have been reported to Bjion. Full 250k coverage is NOT required for done.

## Notes

* Read-only against Supabase throughout; the only artifacts are list files + briefs on disk.
* Any ad-hoc API pull made along the way must be uploaded to the tool before done (house rule).
* Plain-English reporting: state denominators and periods with every number.
