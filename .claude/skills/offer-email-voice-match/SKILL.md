---
name: offer-email-voice-match
description: Static orchestration skill that fixes HOW the Offer Maker writes its preview cold
  emails (offer_email in app/server.py) so they read like a real Navreo email a human would
  actually send, not a template-filled robot. Mines a voice corpus from every email Navreo has
  ever sent via Smartlead (Supabase sent_messages), rebuilds the email prompt around that real
  voice, and proves it with a panel of 5 simulated Navreo copywriters trained on that same
  corpus who must rate 10 preview emails 9/10 for style coherence. One fixed step list,
  checkable done-rules, retry caps, Loop Training Mode toggle. Use when the user says "fix the
  preview copywriting", "make the offer emails sound like us", "run the offer email voice match",
  or "/offer-email-voice-match".
---

# Offer Email Voice Match — previews that read like a real Navreo email

The Offer Maker's UI and the offers themselves are good. The problem is the example cold email
on each card: it is coherent English but it does not feel like an email Navreo would actually
send. Too formulaic, too obviously assembled from a template. This loop fixes only that — the
`offer_email()` writer — by teaching it Navreo's real voice from the emails Navreo has actually
sent, and proving the result against copywriters trained on that same voice. Static: fixed
steps, each with a done-rule.

## ⚙ Loop Training Mode: **ON**   ← flip this line to OFF to run autonomously

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes, report
"Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show
what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule. The panel
rounds (Step 5) cap at **max 5 full rounds**. On cap-hit: record the step FAILED with the
reason, surface it in the final report, and stop — never silently exceed a cap, never declare
done on a cap-hit.

**Spend gate (both modes):** the only spend is OpenAI `gpt-5-mini` (preview regen + panel
judging), hard-capped at **250 calls for the whole loop**. Supabase is READ-ONLY. Nothing is
sent to leads, no campaigns touched, no rows written.

## Goal

The example cold email on every Offer Maker card reads like a real, natural email a Navreo
copywriter would send — same voice, rhythm, and restraint as the emails in Navreo's own sent
archive — while still obeying every substantive copy law already shipped (one mechanism, right
party, deliverable promise, new money, finished conditional, bare CTA).

> **THE DONE-RULE (single source of truth):** on the PRODUCTION page, a panel of 5 simulated
> Navreo copywriters — each given the real `sent_messages` voice corpus from Step 2 as their
> style reference — independently score preview emails 1-10 for **coherence to Navreo's voice**.
> **At least 10 distinct preview emails** (spanning ≥3 different websites and all 4 mechanisms)
> must each land a **panel average ≥ 9.0/10 with no single panelist below 8**. Anything less =
> not done. On the round cap, stop and report the gap honestly with the lowest-scoring lines.

## Ground truth (verified 2026-07-18 this session — re-verify in Step 1, lines drift)

- **Work ONLY in `~/navreo-signals`** (git, Render auto-deploys on push to `main`). iCloud copy
  is DEPRECATED. Marker in `app/offer.html` is currently `offer-maker-v2-chord-r13` — bump it
  each deploy. Deploy repo can be shared with a parallel session: `git fetch` + `merge --ff-only`
  before committing, rebase (never merge) if the push is rejected, and never discard another
  session's uncommitted setter WIP.
- The writer is **`offer_email()`** in `app/server.py`: one `gpt-5-mini` call at
  `reasoning_effort="low"` per offer, picks a lilly-copywriter template by mechanism
  (lead_magnet → Lead Magnet template, the three paid mechanisms → Service Pitch), returns
  `{email, template}`. It already has a validator block and a 3-attempt retry.
- **Architecture laws (do NOT undo — `project_offer_maker_shipped`):** emails are per-offer
  calls, never batched into the main generate call (502s the gateway, reverted twice); low
  reasoning effort is mandatory; the whole thing must stay well under Render's ~100s proxy
  timeout.
- **The voice corpus lives in Supabase** `sent_messages` (project `fnykldftbkrccihdjayl`, ALL
  outbound archive — `project_sent_messages_outbound_archive`), queried per the `lilly-data`
  skill. Join to `replies` to tag which sent copy earned a positive reply — those are the
  gold-standard voice, not just any send.
- **Shipped copy laws that must survive (keep the substance, this loop changes the FEEL):**
  one risk mechanism per email; addressed to the right party; promise only what the sender can
  deliver and measure; new money only (no recovery/retention); Service Pitch = "If we could …
  would you be interested in [X]?" as ONE finished conditional ≤30 words; bare 3-word CTA (no
  "…plan showing the X we'd build"); Lead Magnet says "no charge or commitment", opens on an
  icebreaker not the CTA; no em-dashes; no audits; invented client names only in the P.S.
- **The likely root cause (form vs. substance):** rounds r4-r13 stacked many *rigid* rules
  (forced phrasings, banned words, hard word caps, regex validators). Real emails vary. The
  lever here is to make the writer sound human — vary openers, let sentences breathe, drop the
  tell-tale scaffolding — WITHOUT loosening the substantive laws above. Prefer teaching by
  real example (few-shot from the corpus) over adding yet another rule.
- Style memories that still apply: `feedback_no_em_dashes`, `feedback_plain_english_explanations`,
  the lilly-copywriter templates (`~/.claude/skills/lilly-copywriter/SKILL.md`), and the
  Service Pitch shape in `project_offer_maker_shipped`. `feedback_browser_verify_before_done`.

## Steps

### Step 1 — Re-verify ground truth
In `~/navreo-signals` (fetch + ff-only first): find `offer_email()`, its prompt, its validator
block, the current `offer.html` marker, and confirm one live `gpt-5-mini` call works (debit
ledger). Confirm the `sent_messages` + `replies` tables answer a read-only probe per lilly-data.
- **Done-rule:** you can name the current `offer_email()` line, its template-selection logic,
  its validator rules, the live marker, and a captured real `gpt-5-mini` response, and the
  Supabase probe returned rows.

### Step 2 — Mine the real Navreo voice corpus (read-only)
Per `lilly-data`, pull a representative sample of real first-touch outbound from `sent_messages`
(target ~150-300 emails), preferring those joined to a positive `reply`. Strip to the body,
swap any real names/domains/emails for neutral placeholders (identities never leave), and from
that corpus write a short **voice profile**: how Navreo really opens, how long sentences run,
how the offer is phrased, how the CTA is asked, how the P.S reads, punctuation habits, the
words Navreo does and does not use. Save corpus + profile to
`~/.claude/skills/offer-email-voice-match/voice-corpus.md`.
- **Done-rule:** the file exists with (a) ≥40 verbatim real-voice email bodies, identities
  scrubbed (grep for any `@` or known client name returns nothing), and (b) a voice profile of
  concrete, checkable patterns — not vague adjectives.

### Step 3 — Rebuild the `offer_email()` prompt around the real voice
Rewrite the prompt so it teaches voice by EXAMPLE: embed 4-6 scrubbed real emails from the
corpus as few-shot references ("write like these"), fold the voice profile into the
instructions, and consciously **de-robotise** — allow opener variety, natural sentence length,
and remove any instruction that forces a single tell-tale phrasing where the corpus shows
variety. Keep every substantive law from Ground truth intact (and keep the validator, but
relax any rule that the real corpus proves is too rigid, e.g. a hard phrase or word the real
emails vary). Do not touch offer GENERATION, the UI, rate limits, or the per-offer-call shape.
- **Done-rule:** local curl of `/api/offer/email` on 6 offers (mixed mechanisms) returns 6
  emails that (a) still pass every substantive law, and (b) a quick self-read confirms opener
  and structure now VARY across the six rather than being one template refilled.

### Step 4 — Deploy and generate the preview set
Bump the marker, commit, push, wait for live. On PRODUCTION generate previews for ≥3 varied
sites (e.g. `navreo.ai` + an e-com/agency/local-service site) and collect ≥10 preview emails
spanning all 4 mechanisms into a scored set file.
- **Done-rule:** production marker live; ≥10 preview emails captured across ≥3 sites and all 4
  mechanisms, each rendered with zero console errors in a real browser; repo↔live consistent.

### Step 5 — The copywriter panel (production), iterate to the bar
Spawn 5 parallel simulated **Navreo copywriter** panelists. Each is handed the Step-2 voice
corpus as its ONLY style reference and scores every preview 1-10 for **coherence to that voice**
(not correctness — Step 3 already guards correctness), with a one-line reason and the single
weakest phrase per email. Compute per-email panel average. For any email below the bar, feed the
panel's weakest-phrase notes back into the Step-3 prompt, redeploy via Step 4's done-rule, and
re-panel. Max 5 rounds.
- **Done-rule:** THE DONE-RULE above passes in a single round — ≥10 emails at panel-avg ≥9.0
  with no panelist below 8 — with the per-email score table and a final production screenshot
  of a rendered card captured.

## Final report (always, both modes)

Steps passed/skipped/FAILED with reasons; production URL + marker; the voice-corpus file path
and size; the per-email panel score table (email, mechanism, site, 5 scores, average) and round
count; the before/after of at least 3 emails so the voice shift is visible; the gpt-5-mini
ledger (used / 250); any substantive-law relaxation made and why; anything deferred.

## Hard don'ts

- Never change offer GENERATION, the UI, the ranking/filter, rate limits, low reasoning effort,
  or the per-offer email-call shape — this loop touches `offer_email()` copy only.
- Never relax a SUBSTANTIVE law (one mechanism, right party, deliverable-only promise, new
  money, finished conditional, bare CTA, no audits) to win a style point. Voice changes are
  presentation only.
- Never let an em-dash, a real client identity, or a `{{merge tag}}`/`[bracket blank]` reach a
  preview email.
- Never judge the panel on the app's own labels — production browser render + the corpus-trained
  panel are the only evidence.
- Never exceed a retry cap, the 5-round panel cap, or the 250-call ledger — cap-hit = FAILED
  with the gap, never "done".
