---
name: positive-reply-router-fix
description: Static orchestration skill that fixes the Make positive-reply Slack notifier so replies to Navreo's own campaigns never post into client channels — audits EVERY client route's filter for the outer=OR/inner=AND mis-nesting class of bug, patches the routes via the Make API, and proves the fix with one controlled replay read back from Slack itself. One fixed step list, each step with a checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user says "run the router fix", "fix the positive-reply routing", "Navreo replies are posting to client channels", or "/positive-reply-router-fix".
---

# Positive-Reply Router Fix

On 2026-07-15 a positive reply to Navreo's own campaign was posted by Make into **Amplifyy's client channel** — the client saw Navreo's outreach in his feed and complained. This loop finds the broken route filter(s), fixes every client route (not just the leak), and proves routing with a live replay. Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run without pauses

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gates (both modes, non-negotiable):**
- **Scenario edits:** the only Make mutations allowed are filter/route patches on the positive-reply notifier scenario(s), and only AFTER the full blueprint is snapshotted to this skill folder. In Training Mode ON, show the exact filter diff and get approval before the patch fires.
- **Replay:** exactly **ONE** live replay fire (Mark Adeption's reply via Make hook 4001002), only after the patched blueprint passes the offline simulation. It will post a duplicate notification of the July-9 reply into #interested-replies — acceptable; give it a "routing test" thread note. Never post anything else to any channel.
- **Deletions:** the only permitted deletion is a stray replay post landing in a CLIENT channel — delete immediately, cap 1 per channel. Nothing else in Slack is ever deleted or edited.

## Goal

1. A positive reply on any Navreo-owned campaign posts its notification to **#interested-replies** and nowhere else (user ruling, 2026-07-15).
2. Every client route in the Make notifier is proven to fire only for its own client's campaigns.
3. No unfiltered/fallback route can reach a client channel.

> **THE DONE-RULE (single source of truth):** the route-simulation table over ALL active
> campaigns shows zero cross-client matches on the read-back patched blueprint, **and** the
> single live replay lands in #interested-replies (read back from Slack) with zero new bot
> posts in any client channel, **and** the Make execution log confirms the run took the
> Navreo route. All of it, or it isn't done.

## Ground truth (verified 2026-07-15 — re-verify in Step 1)

- **Incident:** "Interested" reply from markw@adeption.io ("Sure, why not", replied 2026-07-09 19:59 UTC), campaign **"Navreo | Latka | Saas "** (Smartlead ID **3477409**, workspace navreo — pipe separators + trailing space in the name), posted by Make into **#amplifyy-navreo** (`C0AV6J0MFPS`, Slack workspace `T06JZLA7QSV`) at 08:49 local. Parent post since deleted by the user; Make's 8:53 thread reply may remain.
- **Correctly-routed contrast case (same day, 16:39):** Client: Amplifyy, campaign "Amplifyy - Not on Amazon (Soft) - StoreLead - NEW" → #amplifyy-navreo. Suggests routes key off "Client - …" name prefixes, which the pipe-separated Navreo name violates.
- **Suspected mechanism:** Make filter semantics — **outer rows = OR, inner rows = AND** (memory `reference_make_filter_or_and_semantics`; same class of bug previously found on Asteri's route in scenario 9187631). A mis-nested filter or an unfiltered fallback let the Navreo reply into Amplifyy's route.
- **Supabase** (project `fnykldftbkrccihdjayl`): `campaigns` maps 3477409 → `client_id='navreo'` (correct); the `replies` row for the incident carries `client_id` NULL. Determine which field the router actually keys off. **If NULL-stamping is the root cause: REPORT it — rewriting the sync stamping is OUT of scope (user ruling, 2026-07-15).**
- **Make API:** `MAKE_API_TOKEN` in `~/.navreo-keys.env` (added 2026-07-15, untested — prove in Step 1). Start at scenario **9251436** (Navreo reply categoriser); related: **8946472** (positive-reply no-name fix), hook **4001002** (manual positive-reply replay), **9187631** (Asteri categoriser — the earlier OR/AND victim).
- **Slack channels:** destination **#interested-replies** (channel ID unknown — resolve in Step 1). Client channels to sweep (enumerate fully in Step 1): amplifyy-, arnic-, blume-, grouts-, listmint-, stimuli-x-, thunderbirdleadership-, wordbank-, pharmacyx-, cascade-cloud-, acquird-, krg- variants plus navreo-asteri-partners, navreoai-heyreach — anything pairing a client name with navreo, including *-notifications channels.
- **Unknowns for Step 1:** which scenario actually contains the Slack-posting router (9251436 is the starting guess, not a verified fact); the exact route list + filter JSON; whether a fallback route exists; #interested-replies channel ID; whether hook 4001002 is still active.

## Steps

### Step 1 — Re-verify ground truth and map the router (read-only)
Source `MAKE_API_TOKEN` from `~/.navreo-keys.env`. List scenarios via the Make API; identify the scenario(s) that post positive-reply notifications to Slack (start at 9251436, follow the Slack modules). Fetch the full blueprint(s) read-only. Extract every route: its filter JSON and its Slack channel ID. Resolve the #interested-replies channel ID (from an existing correct route, or the Slack UI/API). Pull all ACTIVE campaigns (name, smartlead_campaign_id, client_id) from Supabase. Determine which payload field the router filters on (campaign name vs client field) and note whether the replies `client_id` NULL is load-bearing.
- **Done-rule:** (a) an authenticated Make GET returns 200 with the scenario list; (b) the notifier scenario is identified by ID with its blueprint saved read-only; (c) a route table exists — every route's filter JSON + target channel ID; (d) #interested-replies channel ID resolved; (e) ACTIVE campaign list pulled with count > 0. All five parts or the step fails.

### Step 2 — Offline route simulation (no writes)
Evaluate every ACTIVE campaign against every route's filter, honouring Make semantics (outer=OR, inner=AND). Produce the defect list: cross-client matches, Navreo campaigns not mapping to #interested-replies, any unfiltered or fallback route targeting a client channel. Name the root cause of the 2026-07-15 incident explicitly.
- **Done-rule:** (a) simulation table covers 100% of ACTIVE campaigns × all routes; (b) each defect cites the route index and the offending filter JSON; (c) the incident's root cause is stated and reproduced by the simulation (the Latka campaign must land in a client route or fallback in the pre-fix blueprint — if it doesn't, the diagnosis is wrong: stop and report, don't patch).

### Step 3 — Snapshot, patch, read back
Save the timestamped blueprint snapshot into this skill folder. Patch the filters: each client route matches only its client's campaigns; Navreo-owned campaigns route to #interested-replies; any fallback/else route points at an internal channel, never a client one. **Training Mode ON: show the filter diff and get approval before patching.** Then fetch the blueprint again via a **fresh GET** (never trust the patch response) and re-run the Step-2 simulation against the read-back blueprint.
- **Done-rule:** (a) snapshot file exists in the skill folder; (b) read-back blueprint contains the intended filters; (c) re-run simulation shows ZERO cross-client matches and every `client_id='navreo'` campaign mapping to #interested-replies; (d) no route (fallback included) targets a client channel for non-matching payloads; (e) scenario is still enabled/ON after the patch.

### Step 4 — Live replay proof (the ONE allowed fire)
Fire hook 4001002 once with Mark Adeption's reply payload. Read back from Slack itself (not Make's success label): the notification appears in #interested-replies — add the "routing test" thread note; sweep every client channel for new bot posts in the replay window — must be zero. Check the Make execution log: the run succeeded and took the Navreo route. If a stray post lands in a client channel: delete it immediately (cap 1 per channel), mark the step FAILED, and only retry after a further Step-3 fix (max 3 total patch attempts).
- **Done-rule:** (a) the replay message is read back from #interested-replies in Slack with the thread note added; (b) the client-channel sweep shows zero new bot posts, with the sweep's channel list recorded; (c) the Make execution log shows a successful run through the Navreo route. All three or FAILED.

## Final report (always, both modes)

Steps passed/skipped/FAILED; the notifier scenario ID(s) actually patched; the route table before and after (channel IDs + filter summaries); the named root cause of the 2026-07-15 incident (and whether the replies `client_id` NULL stamping is implicated — reported, not fixed); simulation counts (campaigns × routes, cross-client matches before → after); replay evidence (Slack permalink of the #interested-replies post, sweep channel list, Make execution ID); snapshot file path; anything deferred.

## Hard don'ts

- Never patch before the snapshot exists, and never trust the patch response as read-back — fresh GET only.
- Never fire more than ONE live replay, and never post anything else to any channel.
- Never delete or edit anything in Slack except a stray replay post in a client channel (cap 1 per channel).
- Never rewrite the Supabase sync's `client_id` stamping — report it if implicated (user ruling, 2026-07-15).
- Never guess scenario or channel IDs not proven in Step 1.
- Never leave the scenario disabled after a patch, and never leave a fallback route pointing at a client channel.
- Never exceed a retry cap or report done while any done-rule fails.
