---
name: optimisations-specificity-loop
description: Static orchestration loop that kills repetitive, generic optimisation cards on the Navreo campaigns cockpit (campaigns.html "Review N" panels and the Optimisations tab). Fixes the GENERATOR (the act/bold lines /lilly-optimiser writes into campaign_insights, plus the deterministic bullets in build_notifications.py) so every card names the specific variant, step, subject line, segment or number that makes it true for THAT campaign and nothing else. Fixed step list, machine-checkable done-rules, retry cap, Loop Training Mode ON by default. Use when the user says "the optimisations are repetitive", "they all say the same thing", "make the recommendations specific", "these don't feel actionable", or "/optimisations-specificity-loop".
---

# Optimisations Specificity Loop

## Loop Training Mode: **ON** (default)

Flip it by editing this line: `LOOP_TRAINING_MODE = ON`

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
- Max **3** full loop rounds (Step 1 through Step 8). After round 3, stop and report even if Bjion is still grading below 8.
- Never widen scope to "fix it another way" after a cap is hit. Report and stop.

---

## The Goal

Every optimisation card on the cockpit reads as if it were written about **that one campaign** by someone who looked at it. A card is a failure if you could paste it onto a different campaign and nobody would notice.

Today's failure mode (verified 26 Jul 2026, live cockpit): four different campaigns all show "Replace the weakest copy. Draft in chat, paste by hand." and "Draft replacements in chat, paste into Smartlead by hand. Never via the API." The only thing that changes between cards is the number in the sub-line. The instruction is about the **mechanism of editing** (paste by hand, never the API), not about **what to actually change**.

## Where the text actually comes from (do not guess, this is settled)

1. **The cards Bjion sees** render in `app/campaigns.html` -> `actionCardHTML()` (~line 2781). Headline = `payload.act`, sub-line = `payload.bold`, receipts = `payload.stats` + `payload.note` inside the `Why?` expander. The "Fix inside of Claude" prompt is built from `p.act` + `p.bold`, so a vague act line poisons the handed-off Claude prompt too.
2. **Those payloads are written by Claude**, not by the app. `/lilly-optimiser` analyses a campaign and upserts rows into Supabase `campaign_insights` (scope = campaign id, payload = widget-grammar JSON). That is why the strings are nowhere in the repo. **The generator to fix is `~/.claude/skills/lilly-optimiser/SKILL.md`.**
3. **A second, deterministic source**: `app/build_notifications.py` writes `optimiser_notifications` rows with template bullets and `build_claude_prompt()` text (the 800-send / 1,500-ratio / 15,000-kill rules). Those templates are shared across every campaign by construction, so they are the other half of the sameness. Fix the templates to interpolate campaign-specific facts, never to drop the thresholds (the thresholds are correct, they just should not be the whole sentence).

Do not "fix" this in `campaigns.html`. The renderer is fine. Rewording at render time would fabricate specificity the payload does not have.

## The Specificity Contract (this is what gets written into the generator)

Every `act` line must satisfy **all five**:

- **S1 Names the thing.** It points at a specific object in that campaign: variant letter, subject line fragment (quoted, 3 to 6 words), sequence step number, the named segment/persona, or the specific mailbox/domain. "The weakest copy" fails. "Variant B, subject 'quick one about hiring'" passes.
- **S2 Says what changes, not how to type it.** The headline states the substantive change (what angle, what to replace it with, what to test against). "Draft in chat, paste by hand" and "never via the API" are **mechanics**: they move into `Why?` and the handed prompt. They never occupy the headline.
- **S3 Carries one number that only this campaign has.** Not the threshold. The campaign's own figure: this variant's sends and positives, this step's reply rate, this list's remaining leads.
- **S4 Distinct verb.** Across all live cards in one cockpit refresh, no opening verb is used by more than 30% of cards.
- **S5 Fails the swap test.** Paste the act line onto another campaign in the book: if it still reads as true, it is too generic and gets rewritten.

`bold` (the sub-line) must back-solve from that campaign's own numbers with a one-source, one-window figure, per the certified card grammar. It never repeats the threshold sentence verbatim across campaigns.

Standing rules that still bind: no em dashes anywhere; kid-simple titles, 15 words max, never truncated; captions 5 words max; owner chip and eyebrow tag live in `Why?`; two sentences max on the visible card.

---

## Steps

### Step 0 - Preflight
Read `~/.claude/skills/lilly-optimiser/SKILL.md` (cockpit contract + widget grammar), `app/campaigns.html` `actionCardHTML()`, and `app/build_notifications.py` (`build_campaign_findings`, `build_section7`, `build_claude_prompt`). Confirm `~/navreo-signals` is on latest main (`git pull`).

**Done-rule:** all three read this session, repo clean and current.

### Step 1 - Baseline the repetition
Mint an authed session cookie (sha256 of `SUPABASE_SERVICE_ROLE_KEY + ":navreo-session-v1"` from `~/.navreo-keys.env`, mirrors `_mint_session` in `app/server.py`). GET `/api/cockpit/insights` on the live host. Extract every live card's `act` and `bold`. Write the raw set to the scratchpad.

Compute and record:
- `dup_rate` = share of cards whose `act` is byte-identical to another card's
- `prefix_rate` = share of cards sharing their first 4 words with another card
- `verb_top_share` = share of cards opening with the single most common verb
- `swap_fails` = count of act lines with no campaign-specific noun or number

**Done-rule:** baseline numbers recorded in the scratchpad with the card count they came from. (This step measures, it cannot fail on quality.)

### Step 2 - Write the Specificity Contract into the generator
Edit `~/.claude/skills/lilly-optimiser/SKILL.md`: add the five-rule contract above to its insight-writing section, plus the explicit ruling that editing mechanics (draft in chat, paste by hand, never via the API) belong in `Why?` and the handed prompt, never in the headline. Include 3 worked before/after examples drawn from the real failing cards captured in Step 1.

**Done-rule:** the contract text is present in the file, names all five rules S1-S5, carries the mechanics ruling and 3 real before/after examples.

### Step 3 - De-template the deterministic bullets
In `app/build_notifications.py`, rework the shared bullet and prompt strings so each interpolates campaign-specific facts: the failing variant's id/subject, its own sends and positives, which sequence step, how much of the list is worked. Keep every threshold intact (800 sends, 1 per 800, 1,500 sent/pos, 15,000 kill line). The threshold becomes the justification clause, not the sentence.

**Done-rule:** for a 5-campaign dry run, no two campaigns produce a byte-identical bullet, and every bullet contains at least one campaign-unique token.

### Step 4 - Regenerate a sample
Run `/lilly-optimiser` against at least 6 campaigns spanning the failure modes: zero-positive early stage, above-1,500-ratio mid stage, kill-threshold, healthy winner, list-nearly-dry, low-reply-rate. Let it write fresh `campaign_insights` rows (regeneration supersedes, per its own cache rules).

**Done-rule:** `/api/cockpit/insights` returns a fresh `generated_at` and live rows for all 6 sampled campaigns.

### Step 5 - Machine check the contract
Re-run the Step 1 metrics on the fresh cards. Thresholds to pass:
- `dup_rate` = 0 (no two identical act lines)
- `prefix_rate` <= 0.20
- `verb_top_share` <= 0.30
- `swap_fails` = 0 (every act line carries a campaign-specific noun **and** number)
- zero act lines containing "paste by hand", "in chat", or "via the API"
- zero em dashes anywhere in any payload string

**Done-rule:** all six pass. Any failure routes back to Step 2 (contract wording) or Step 3 (templates), then forward again. Retry cap applies.

### Step 6 - Live browser verify
Rendered page is the only done-evidence for UI. Set the minted cookie via `/app/login.html` then navigate to `campaigns.html#/`. Expand at least 3 different campaigns' "Review N" panels and the Optimisations tab. `campaigns.html` screenshots blank in the Browser pane, so read the DOM with JS: pull the `.action-how` and `.action-payoff` text from each expanded card.

**Done-rule:** the DOM-read act lines match the fresh payloads, all three campaigns show different headlines, and the `Why?` expander holds the mechanics and the receipts.

### Step 7 - Bjion grades it (the human gate)
Present exactly 5 cards from 5 different campaigns, in chat, as plain text: headline, sub-line, and what the `Why?` holds. Ask one question: **"Does each of these read as written about that campaign specifically? Grade 1 to 10."**

**Done-rule:** every card graded **8 or above**. Below 8 on any card: capture his exact wording as a ruling, fold it into the Step 2 contract, and re-run Steps 2 through 7. Loop-round cap applies (3 rounds).

### Step 8 - Ship and record
Commit `app/build_notifications.py` (and anything else touched) to `~/navreo-signals` main and push, so Render redeploys. Let the publish-skill hook carry the `lilly-optimiser` edit to Notion and GitHub. Write one memory recording the contract, the passing metrics, and Bjion's rulings from Step 7.

**Done-rule:** commit pushed, live host serving the new commit, memory file written and indexed in `MEMORY.md`.

---

## Guardrails

- Never edit `campaigns.html` to reword cards at render time. The renderer is correct; the payload is the defect.
- Never delete or loosen a threshold to make a card sound less repetitive. Thresholds are the reasoning; specificity is the phrasing.
- Never regenerate the whole book to test a wording change. Sample 6 campaigns, per Step 4.
- Nothing gets marked done on curls alone. Step 6 is mandatory.
- If a step is blocked (API down, no keys, cookie invalid), say so plainly, finish every step that does not depend on it, and name what was skipped.
