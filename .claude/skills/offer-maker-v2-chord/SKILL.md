---
name: offer-maker-v2-chord
description: Static orchestration skill that upgrades the live public Offer Maker
  (https://navreo-signals.onrender.com/app/offer.html) so its offers consistently hit a
  chord with the target customer. Four fixes in one loop — (1) deeper autonomous prospect
  research before generation (multi-page scrape → written company brief → inferred ICP,
  per the auto-research competitor pattern), (2) ONE risk mechanism per offer (a lead
  magnet OR a guarantee OR pay-after — never stacked), (3) example cold emails aligned to
  the lilly-copywriter templates (any template passes), (4) a Google-search-minimalist UI
  rebuild (one field, clean result cards, download, per-card "more like this"). Proven by
  a 5-persona ICP panel (would they be enticed?), a sender-deliverability panel (can the
  sender comfortably deliver it?), and a template-compliance judge. Fixed step list,
  checkable done-rules, retry caps, Loop Training Mode toggle. Use when the user says
  "run the offer maker upgrade", "fix the offer maker", "simplify the offer maker UI",
  or "/offer-maker-v2-chord".
---

# Offer Maker v2 — offers that hit a chord, on a page as simple as a search box

The shipped Offer Maker works but: the UI is word-heavy and clunky; the example emails
drift from the lilly-copywriter templates; offers stack mechanisms (a guarantee inside a
lead magnet) instead of picking ONE; and research is shallow. This loop fixes all four
and proves the result with recipient, sender, and template panels. Static — fixed steps,
each with a done-rule.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
Panel rounds (Step 7) cap at **max 4 full rounds**. On cap-hit: record the step FAILED
with the reason, continue to the next step if it doesn't depend on the failed one, and
surface every FAILED step in the final report. Never silently exceed a cap. Never
declare the skill done on a cap-hit.

**Spend gate (both modes):** OpenAI `gpt-5-mini` calls hard-capped at **300 for the whole
loop**. The shipped endpoint's live rate limits (10 gens/IP/hr, 30 attempts/IP/hr,
200/day global, 80/IP/hr email bucket) must survive the change untouched. Supabase is
READ-ONLY. Nothing is sent to leads; no campaigns touched.

## Goal

An offer system that creates offers which consistently hit a chord with the target
customer: the page takes a website URL (plus the existing optional "who do you sell to"
field), researches the company properly, and returns simple single-mechanism offers with
template-true example emails — on a UI as minimal as a Google search.

> **THE DONE-RULE (single source of truth):** on the PRODUCTION page, for each of 3 test
> websites: (a) a panel of 5 simulated target-ICP recipients says **≥4/5 "I'd probably be
> enticed"** per site, (b) a sender-side panel confirms **≥90% of offers are ones the
> sender could comfortably and easily deliver** per the offer framework, (c) **100% of
> generated example emails pass the lilly-copywriter template-compliance judge** (any one
> template — Service Pitch, One Sentence Punch, Lead Magnet, or Case Study), (d) **0
> offers stack risk mechanisms**, and (e) the minimalist UI passes the browser check in
> Step 5. Anything less = not done; on the round cap, stop and report the gap honestly.

## Ground truth (verified 2026-07-16 — re-verify in Step 1, line numbers drift)

- **Work ONLY in `~/navreo-signals`** (git, Render auto-deploys on push to `main`). The
  iCloud copy is DEPRECATED — never edit it (`reference_signals_deploy_repo`).
- Live page: `app/offer.html`, public via `_AUTH_PUBLIC_GET`; backend `offer_generate()`
  + `offer_email()` in `app/server.py`, routes in `ROUTES`, public via `_AUTH_PUBLIC_POST`.
- **Architecture law (do NOT undo — `project_offer_maker_shipped`):** generation is ONE
  synchronous `POST /api/offer/generate` at `reasoning_effort="low"` (async job-poll was
  tried and REVERTED — Render's LB breaks in-memory job stores; medium effort 502s the
  gateway). Whatever research is added, the total request must stay well under Render's
  ~100s proxy timeout. Emails are per-offer calls — never batched into the main call
  (REVERTED twice).
- New-money rule is structural in the prompt (banned-offer list + self-check) — keep it.
- Winning-offer few-shots live in `OFFER_WINNING_EXAMPLES` (source:
  `~/.claude/skills/offer-maker-ship/winning-offers.md`) — keep them.
- lilly-copywriter templates (`~/.claude/skills/lilly-copywriter/SKILL.md`): Email 1a
  Service Pitch (greeting → icebreaker ending "so I wanted to reach out" → ONE flowing
  "If we could [outcome] by [what we do], [risk reversal], [low-risk CTA]?" sentence →
  sign-off → concrete P.S. proof), Email 1b One Sentence Punch, Lead Magnet (offer to
  SEND/GIVE/SHOW something, CTA bias rule, briefing-language rule), Case Study. Emails
  must match ONE of these; square-bracket slots are the only free text.
- Competitor research pattern (`auto-research-public`, Downloads/SKILL (2).md): scrape
  homepage + /about + /product + /pricing + /customers → write a short company analysis
  (what they do, who their likely customers are, social proof, outreach angles) → THEN
  generate. That analysis step is what makes output data-backed — port it server-side.
- Style laws: no em-dashes in copy or UI, plain English zero jargon
  (`feedback_no_em_dashes`, `feedback_plain_english_explanations`); browser-rendered
  proof only (`feedback_browser_verify_before_done`); walk the whole live flow before
  handover (`feedback_full_live_ui_flow_before_handover`).

## Steps

### Step 1 — Re-verify ground truth
In `~/navreo-signals` (fetch + ff-only merge first): locate `offer_generate()`,
`offer_email()`, their ROUTES lines, the `_AUTH_PUBLIC_*` entries, the rate-limit code,
and `OFFER_WINNING_EXAMPLES`. Load the live page logged-out and capture a baseline
screenshot + the current static-UI word count above the fold.
- **Done-rule:** you can name the current line numbers for all of the above, the repo is
  clean and up to date with origin/main, and a baseline production screenshot exists.

### Step 2 — Research upgrade (backend, competitor pattern)
Extend the server-side fetch in `offer_generate()` from homepage-only to homepage +
/about + /product + /pricing + /customers (and /services, /case-studies if linked),
fetched in PARALLEL with per-page timeouts (~8s) and a hard overall research budget
(~20s) so the synchronous call stays far under the proxy timeout. Have the model write a
compact company brief FIRST (what they do, who they sell to, proof signals, angles) as a
structured preamble inside the SAME single response, then generate offers grounded in it.
Return the brief's "who you sell to" inference in the JSON so the UI can show it.
- **Done-rule:** for `navreo.ai` + 2 varied real sites, the response includes a non-empty
  company brief with an inferred target customer, ≥80% of offers cite a concrete fact
  from the scraped pages (judge pass), total request time <60s per site, and a JS-heavy
  storefront still returns the honest "email us" error.

### Step 3 — Single-mechanism offer rule
Make it structural in the prompt (low effort ignores soft guidance): every offer picks
exactly ONE risk mechanism — lead magnet OR guarantee/refund OR pay-after-result OR
pay-per-result. Add a banned-stacking list ("no guarantee inside a lead-magnet offer, no
lead magnet bolted onto a pay-per offer") + a final self-check line, mirroring how the
new-money rule was made to stick. Each offer's JSON gains a `mechanism` field.
- **Done-rule:** across the 3 Step-2 test sites, an automated judge finds **0 offers**
  containing more than one risk mechanism, all four framework components still present,
  and new-money compliance still ≥90%.

### Step 4 — Email template alignment (lilly-copywriter)
Rewrite the `offer_email()` prompt so each email follows exactly ONE lilly-copywriter
template, chosen by mechanism: lead-magnet offers → Lead Magnet template (offer to
send/give/show, CTA-bias rule); proof-led offers → Case Study; everything else → Service
Pitch (the current shape — keep the one-flowing-sentence law, concrete invented names, no
merge tags, no brackets). Embed condensed template skeletons in the prompt; state which
template was used in the response.
- **Done-rule:** 12 sample emails (4 per test site, mixed mechanisms) each pass a
  template-compliance judge against the named template — correct structure, icebreaker
  ends "so I wanted to reach out" where the template requires it, one mechanism only, no
  em-dashes, no merge tags — at **12/12**.

### Step 5 — Minimalist UI rebuild (Google-search feel)
Rebuild `app/offer.html`'s above-the-fold to: logo-weight title, ONE centered URL field,
the small optional "who do you sell to" field, one button. No paragraphs of education
before results (move any teaching into collapsed "how this works" and per-card "why this
works"). Results: the inferred target line, then clean cards (mechanism badge, offer,
example email, why-it-works collapsed) with per-card **"More like this"** (re-calls
generate biased to that offer's mechanism + angle — new small backend param, same
endpoint), copy, and CSV/download kept. Static UI text above the fold ≤40 words.
- **Done-rule:** local browser logged-out: page loads, full flow renders with zero
  console errors, above-the-fold static text ≤40 words (counted from rendered DOM),
  "More like this" returns 3-5 new offers of the same mechanism, CSV row count matches
  card count, copy-all matches on-screen text.

### Step 6 — Deploy and verify live
Commit + push from `~/navreo-signals` (marker `offer-maker-v2-chord`). Wait for Render,
then logged-out on PRODUCTION: marker-grep the deployed HTML, run one full generation on
a real URL, one "More like this", one email render, one CSV download.
- **Done-rule:** all four production checks pass in a real browser, zero console errors,
  and rate-limit behaviour is confirmed unchanged (11th rapid request refused).

### Step 7 — Panels: recipient, sender, template (production)
For each of 3 test sites, generate on PRODUCTION, then run: (a) **ICP panel** — 5
simulated personas matching that site's inferred target customer each react cold to the
offers ("would this entice you to reply? why/why not"), pass = ≥4/5 probably enticed;
(b) **sender panel** — as the site's owner: "could you comfortably deliver this offer as
promised, per the framework's easy-to-deliver test?", pass = ≥90% of offers; (c)
**template judge** on every rendered email, pass = 100%. Sceptical personas must be
allowed to say no — fix prompts/UI between rounds (max 4), redeploying via Step 6.
- **Done-rule:** THE DONE-RULE above passes in a single round, with per-site panel tables
  and one final production screenshot of rendered cards.

## Final report (always, both modes)

Steps passed/skipped/FAILED with reasons; production URL + marker; per-site panel tables
(persona, enticed?, one-line reason), sender-panel %, template-judge score; stacking and
new-money judge results; above-the-fold word count before → after; research budget
timings; gpt-5-mini ledger (used / 300); round count; screenshot path; anything deferred.

## Hard don'ts

- Never revert the single-synchronous-call architecture, low reasoning effort, per-offer
  email calls, or the shipped rate limits.
- Never let the research phase push total request time near the ~100s proxy timeout.
- Never ship an offer with two risk mechanisms, or an email that matches no
  lilly-copywriter template.
- Never edit the iCloud copy — `~/navreo-signals` only.
- Never expose client or prospect identities; winning-offer few-shots stay
  identity-swapped.
- Never verify via the app's own labels — browser-rendered production proof only.
- Never use em-dashes or jargon in offer copy or UI text.
- Never exceed a retry cap, the 4-round panel cap, or the 300-call ledger — cap-hit =
  FAILED with the gap, never "done".
