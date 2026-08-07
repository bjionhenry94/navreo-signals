---
name: insight-why-digest
description: Static orchestration loop that fixes the "Why?" expander on recommendation cards in the Navreo campaigns cockpit (campaigns.html action cards). Today one card's Why? dumps EVERY optimiser finding for the whole campaign - unrelated variant calls, "Recommended actions" paste blocks, other cards' stories. This loop scopes each Why? to its own card and redesigns it as a short visual digest (stat chips + mini variant bars, capped prose). Fixed step list, machine-checkable done-rules, retry cap, strategist-panel gate at 9/10+. Use when the user says "the Why is too long", "the Why shows unrelated fixes", "make the Why easier to digest", "make the reasoning visual", or "/insight-why-digest".
---

# Insight Why? Digest Loop

## Loop Training Mode: **OFF** (default)

Flip it by editing this line: `LOOP_TRAINING_MODE = OFF`

**When ON**
- Pause at the end of **every** step. Show the step's done-rule result, then wait for Bjion's approval before moving on. Never chain two steps in one turn.
- **Skip** any step whose done-rule already passes. Say "Step N already passes, skipping" and move to the next.
- Only re-run steps that **fail**.
- Retry cap applies (below).

**When OFF**
- Run every step back to back, no pauses, no approval requests.
- Done-rule checks still run on every step. Retry cap still applies.
- Report once at the end: which steps ran, which were skipped, which failed.

**Retry cap (both modes)**
- Max **3** attempts per step. On the 3rd failure, stop the loop, report the step, the done-rule, the last failure output, and the best guess at the blocker. Never attempt a 4th.
- Max **3** full loop rounds (Step 1 through Step 6). After round 3, stop and report even if the panel is still grading below 9.
- Never widen scope to "fix it another way" after a cap is hit. Report and stop.

---

## The Goal

Opening "Why?" on a recommendation card answers exactly one question - *why this recommendation* - in under 10 seconds of reading. It shows only the receipts behind **that card**, and it shows them visually (chips and bars first, prose last). A Why? is a failure if it mentions any other card's fix, or if it takes scrolling to finish.

## Where the defect actually lives (verified 26 Jul 2026, do not guess)

1. Cards render in `~/navreo-signals/app/campaigns.html` -> `actionCardHTML()` (~line 2780). The quick numbers (`p.bold`, `p.stats`, `p.note`) render instantly in `.opt-why-body` - **this part is fine and stays**.
2. The wall of unrelated fixes is the lazy-loaded `.why-full` block: `whyBreakdownFetch(cid)` (~line 4171) fetches `/api/notifications?slim=1&campaign_id=<cid>` - **per campaign, not per card** - and `whyBreakdownHTML(rows)` (~line 4198) renders **every** `optimiser_notifications` row for that campaign into every card's expander. One card's Why? therefore carries every variant call, the "Recommended actions" paste block, "Whole offer failing", "Upload more leads", "Performing" - all of it, on all cards.
3. The card knows who it is: `r.insight_key` (used for `data-action-key` in the same function). The breakdown rows carry `title` / `suggested_action` / `priority`. The fix is to pass the card's identity into the breakdown and render **only its matching row(s)**.

Do not fix this in `/lilly-optimiser` or `build_notifications.py`. The data is fine; the renderer is dumping the whole table into every card.

## The Why? Contract (what the redesigned expander must satisfy)

- **W1 Scoped.** Only content belonging to this card's finding renders. Zero mentions of other variants' REPLACE calls, other cards' actions, or campaign-level verdicts that belong to a different card.
- **W2 One screen.** The open expander fits without scrolling on a 1280x800 desktop viewport: max 1 short prose line beyond the existing quick-number bullets, then visuals.
- **W3 Visual first.** Numbers render as stat chips (sent / positives / ratio / meetings) and per-variant comparisons as horizontal mini bars (sends vs positives per variant), not as a full 8-column table. The table only appears when the card's own finding is variant-level, trimmed to the variants it names.
- **W4 Verdict line.** Exactly one bolded takeaway sentence, 15 words max, restating why the recommendation follows from the numbers shown.
- **W5 No paste blocks.** The "Recommended actions" copy-paste blob never renders inside Why? - that content already lives in the "Copy prompt for Claude" button.

Standing rules still bind: no em dashes anywhere; kid-simple wording; captions 5 words max; two sentences max on the visible card.

---

## Steps

### Step 0 - Preflight
Read `actionCardHTML()`, `whyBreakdownFetch()`, `whyVariantsTable()`, `whyBreakdownHTML()` in `app/campaigns.html`, and the shape of `/api/notifications?slim=1` rows in `app/server.py`. Confirm `~/navreo-signals` is on latest main (`git pull`).

**Done-rule:** all reads done this session, repo clean and current.

### Step 1 - Baseline the bloat
Mint the authed session cookie (sha256 of `SUPABASE_SERVICE_ROLE_KEY + ":navreo-session-v1"` from `~/.navreo-keys.env`, mirrors `_mint_session` in `app/server.py`). On the live host, pick 3 campaigns with multiple cards, expand one card's Why? per campaign, and DOM-read `.opt-why`. Record per card: rendered character count, count of `.why-block`s, and how many of those blocks belong to a different card's finding.

**Done-rule:** baseline recorded in the scratchpad for 3 cards. (Measures only, cannot fail on quality.)

### Step 2 - Scope the fetch to the card
In `campaigns.html`: pass the card's `insight_key` (and the finding's title/tag from `r.payload`) into the `.why-full` lazy-load, and filter the fetched rows to the one(s) matching this card before rendering. Keep the per-campaign fetch + `WHY_CACHE` (one request, filter client-side). A card with no matching row shows the quick numbers plus "No further findings behind this one."

**Done-rule:** DOM-read on the 3 baseline cards shows zero `.why-block`s from another card's finding (W1), and the campaign still makes exactly one `/api/notifications` request however many cards open.

### Step 3 - Redesign the digest
Replace the matched row's rendering per the contract: stat chips for the headline numbers, mini bars for variant sends/positives when the finding is variant-level (only the named variants), one bolded verdict line (W4), strip the paste blocks (W5). CSS lives with the existing `.opt-why` styles.

**Done-rule:** on the 3 baseline cards, open expander fits 1280x800 without scrolling (W2), chips + bars present where data exists (W3), verdict line present and 15 words max, zero paste-block text (W5).

### Step 4 - Live browser verify
Rendered page is the only done-evidence for UI. Log in via `/app/login.html` with the minted cookie, open `campaigns.html#/`, expand at least 5 Why?s across 3 campaigns including: a variant-level card, a campaign-level card (whole offer failing), and a list card (upload more leads). `campaigns.html` screenshots blank in the Browser pane, so DOM-read each open `.opt-why` and check W1-W5 against the text and element structure. Also confirm the pre-existing quick-number bullets still render and nothing else on the card regressed (buttons, badges, prompt copy).

**Done-rule:** all 5 expanders pass all five contract rules by DOM evidence; no console errors.

### Step 5 - Strategist panel (the 9/10 gate)
Spawn 3 independent subagents, each prompted as a cold-email account strategist reviewing the cockpit for a client. Give each the DOM-read content of the same 5 Why?s (before-text from Step 1 available on request, but grade the AFTER only). One question each: **"As the strategist who has to act on this card, grade the Why? experience 1 to 10 for how quickly and clearly it justifies the recommendation."**

**Done-rule:** every panelist grades every card **9 or above**. Any lower score: capture the exact objection, route it back to Step 2 (scoping) or Step 3 (design), re-run forward. Loop-round cap applies (3 rounds).

### Step 6 - Ship and record
Commit `app/campaigns.html` (and any CSS touched) to `~/navreo-signals` main and push, so Render redeploys. Verify the live host serves the new commit and one Why? still passes post-deploy. Write one memory recording the scoping fix, the contract, and any panel rulings.

**Done-rule:** commit pushed, live host on the new commit, post-deploy spot check passes, memory file written and indexed in `MEMORY.md`.

---

## Guardrails

- Never edit `/lilly-optimiser`, `build_notifications.py`, or the `optimiser_notifications` data to fix this. The payloads are correct; the renderer's scoping is the defect.
- Never drop the instant quick-number bullets in `.opt-why-body`. They are the part that already works.
- Keep one fetch per campaign (`WHY_CACHE`). Do not turn the fix into N requests per card.
- Nothing gets marked done on code reads or curls alone. Step 4 is mandatory.
- If a step is blocked (host down, no keys, cookie invalid), say so plainly, finish every step that does not depend on it, and name what was skipped.
