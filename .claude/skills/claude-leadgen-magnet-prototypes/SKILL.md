---
name: claude-leadgen-magnet-prototypes
description: Static orchestration skill that prototypes 5 versions of the new "run your lead-gen from inside Claude Code" lead magnet as Notion pages — VSL placeholder up top, PAS arc, genuine training substance, real receipts dotted through, inline DIAGRAM briefs, an embedded Navreo ROI calculator, and the Email-2 "30 qualified leads in 90 days or you don't pay" offer preserved verbatim but presented in Daniel Fazio's ListKit offer shape. Mines campaign 3509012 + the two guide campaigns for who/what resonates, mines GojiBerry / Origami / ListKit for pains and agitation, then a simulated panel of 5 non-technical founders and sales leaders scores every version at a 9/10+ bar on four fixed statements. One fixed step list, checkable done-rules, retry caps, Loop Training Mode toggle. Use when the user says "build the Claude lead-gen magnet", "prototype the new lead magnet", "run the lead-magnet loop", or "/claude-leadgen-magnet-prototypes".
---

# Claude Lead-Gen Magnet Prototypes

The live email waves (4 problem variants + the Email-2 offer bump) win a "yes, send it over" — this loop builds the thing that gets sent. Five Notion prototypes of ONE lead magnet: *how to run your whole lead-gen from inside Claude Code* — a genuine free training that educates with PAS and converts the reader into a booked call. Static loop — fixed steps, each with a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

- **ON** (default): pause at EVERY step boundary and wait for Bjion's explicit approval before continuing. Before starting a step, check its done-rule first — if it already passes, report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule fails. Show what you're about to do before doing it.
- **OFF**: run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing behaviour, and retry caps stay exactly the same — only the pauses go.
- **Retry cap (both modes)**: max **3 retries** per step (in Steps 4 and 6, per *version*). On cap-hit: record the item as FAILED with the reason, continue to steps that don't depend on it, and surface every FAILED item in the final report. Never silently exceed the cap. Never declare the loop done on a cap-hit.

**Outward-action gate (both modes, non-negotiable):** the only outward writes this loop ever makes are (1) **new** Notion pages for the 5 prototypes (plus a parent index page if needed), and (2) in the signals repo, exactly two changes: one **new** self-contained calculator HTML file plus a **one-line addition** of its path to the `_AUTH_PUBLIC_GET` allowlist in `app/server.py` — nothing else in any existing file. It NEVER edits or deletes the three existing lead-magnet pages, never emails or messages any prospect, never writes to Smartlead or HeyReach (reads only), and spends **zero** paid credits (no Prospeo / AI Ark / MillionVerifier / Trigify). In Training Mode ON, additionally show the Notion parent + the 5 page titles before any page is created, and the calculator file path + diff + assumptions before it deploys.

## Goal

Five publishable prototypes of the lead magnet live in Notion, each one:
1. opening with a **VSL placeholder** — the slot for the video that walks the whole system, with a brief listing what it covers and where real examples of things we've done get dotted in,
2. running the **PAS arc** on a distinct problem angle (table below), agitating pains the market has already proven,
3. delivering **real training substance** — the emails promised *"a free training which shows you how to find high-intent buyers from one simple Claude or ChatGPT chat, where it runs 24/7 and gets better every week"* and the magnet must actually teach that, not just pitch,
4. showing the Navreo system as the fix — *super simple to use, deep insights that unearth what's going on, launch campaigns in just plain text, all in one place* — with real receipts dotted through,
5. carrying the **offer verbatim** (Ground truth below) presented in the ListKit/Fazio shape, with the **Navreo ROI calculator embedded**, so the reader knows exactly what's on the table before any call,
6. instructing every diagram via inline **DIAGRAM briefs**,
and a simulated panel of **5 non-technical founders and sales leaders scores each version 9/10+ on all four statements** below. Winner recommendation + diagram/VSL to-do list delivered in chat.

**THE DONE-BAR (single source of truth)** — a version passes only when **every one of the 5 panelists scores it ≥9/10 (integers 1–10) on every one of these four statements**:
> 1. "They understand the pain I'm experiencing"
> 2. "Their solution sounds simple and easy to implement"
> 3. "I know what they're offering before I jump on the call"
> 4. "This sounds like something I want."

## Ground truth (captured 2026-07-27 — re-verify live sources in Step 1)

- **The promise being fulfilled** (live email copy): a free training showing how to find high-intent buyers from one simple Claude or ChatGPT chat, running 24/7, getting better every week. Break this promise and the reply→magnet moment kills trust.
- **The offer — verbatim, never altered** (Email 2 primary): *"30 qualified leads for {{company_name}} in 90 days across email and LinkedIn, every one a decision maker you approved replying wanting to talk, and if we miss 30 you don't pay."* Risk-reversal variants in the live emails: *"or we'll refund you"* / *"you don't pay anything until it's built and live."* The magnet's offer section states this promise; its wording is untouchable.
- **Resonance sources**: Smartlead campaign **3509012** (app.smartlead.ai/app/email-campaign/3509012/analytics) plus the two other lead-magnet campaigns — the **Clay→Claude guide** campaign and the **run-outreach-inside-Claude guide** campaign (ids unknown — Step 1 resolves them). Positive replies also live in the Supabase replies archive (lilly-data). Smartlead/Supabase keys per lilly-bot / lilly-data conventions (`~/.navreo-keys.env`) — re-verify.
- **Previous magnets that worked** (read all three in Step 2; mine structure and moves):
  - *Ultimate Claude Code Guide for Sales Leaders* — navreo.notion.site/36a6e75598d98047b5ecd20c2c6e1280 (what the Clay→Claude askers got)
  - *The $15,480,000 playbook* — navreo.notion.site/30c6e75598d9805d819cd1d02b8cb386 (converted many positives into calls early this year)
  - *Ultimate AI Sales Pack V2* — navreo.notion.site/2626e75598d980238d33d70974b95694 (most successful ever, but LinkedIn-only traffic and 2–3 years dated — reuse its moves, never its claims)
- **Competitors to mine in Step 2**: **GojiBerry** (app.gojiberry.ai — ~$3.5M in 12 months on "we find you qualified leads"; simplicity, cutting the complex parts), **Origami** (origami.chat), and **ListKit** (listkit.io — Daniel Fazio's company; browse the site, especially the ROI calculator UX). The captured Fazio marketing below stays the baseline.
- **Fazio/ListKit marketing, captured**: tweet voice — *"Have had some people say this offer sounds 'too good to be true'. I assure you it's true."* then a flat included-list (.com domains, google inboxes, warmup, leads, verification, sending, AI script writer), closing *"single handedly the best cold email offer ever created"*. Landing: "Send 1,000 Cold Emails Per Day for $597/mo" — "all in one platform. All for one price." Pricing card "Full Cold Email Stack": volume slider **$597/mo = 1k/day, $1,194 = 2k, $1,791 = 3k, $2,985 = 5k, $5,970 = 10k** (linear ~$597 per 1k/day); domains always free and scaling **$300/$600/$900/$1,500/$3,000 per yr — "on us, for as long as you're subscribed"**; *"There are absolutely zero additional costs you have to pay. This is EVERYTHING you need…"*; "Everything you need" checklist (triple-verified leads via AI search, email engine with warmup, domains & inboxes, AI script agent trained on top templates, 1-on-1 concierge onboarding, Slack community + weekly calls, mastery course); **Book a Demo**; **Cancel anytime**; trust bar *977M+ triple-verified contacts · 98% Deliverability · 4.8/5 on G2* (his numbers, never ours).
- **ListKit ROI calculator, captured** (the shape ours mirrors): inputs — emails/day slider (1k–10k), average client LTV slider ($500–$50,000), close rate from meetings (5–50%); footnote *"Conservative assumption: 1% reply rate · 5% positive · 40% book a meeting · 22 sending days/mo"*; outputs — total replies, positive replies (leads), meetings booked, deals closed, projected revenue, cost, ROI%; **Book a Demo** beneath the ROI line.
- **Offer ruling (Bjion): do not change the offer — mirror Fazio's offer exactly.** Substance = the verbatim Email-2 promise above; shape = ListKit's presentation: one headline promise, everything-included checklist, zero-additional-costs statement, objection pre-empted head-on, risk reversal, ROI calculator, book-a-call CTA, trust bar built from OUR real proof.
- **Author voice to mimic**: Fazio's — blunt declarative one-liners, plain lists, names the objection before the reader does, zero hedging, zero corporate speak.
- **Navreo positioning (Bjion's ruling)**: we do the same things the competitors shout about — triple verification, finding the data, signals — the difference is **simplicity + design** (Bjion's background). One place instead of tab-bouncing between a million tools you don't trust; say what you want in plain English; Claude integrates and manages the tools and combines them into something better; deep insights; launch campaigns in plain text.
- **The Notion embed answer** (Bjion asked, 2026-07-27): Notion can't run custom code, but a `/embed` block renders any public iframe-able URL — so the calculator is a self-contained static HTML page at a public unauthenticated URL, embedded per prototype. Host: `~/navreo-signals` (push to `main` auto-deploys to navreo-signals.onrender.com). **Gotcha (verified 2026-07-27): the server 401s every GET whose path isn't in `_AUTH_PUBLIC_GET` in `app/server.py` (~line 13535 — drifts, re-find it)** — so the calculator needs its path added there (the one-line edit the gate authorizes). Render deploys asynchronously: after pushing, poll `/api/version` until the new commit is live (memory `signals-live-verify-recipe`) before treating a curl failure as a retry.
- **Notion access**: use the token publish-skill already uses for the workspace. Default parent for the 5 new pages = the parent of the three existing magnet pages (retrieve one of the three by the page ids in the URLs above and read its parent). ON-mode pause can override.
- **Unknowns to resolve**: the two guide-campaign ids (Step 1); a measured booking rate if one exists in Supabase/Smartlead (Step 1); **Navreo's price** for the calculator's cost/ROI lines — ask Bjion at a Training-Mode pause; if withheld, the calculator shows projected pipeline/revenue only, no cost/ROI lines.

## The five versions (one magnet, five PAS lead-ins — distinct openings, same training, same system, same offer)

| # | Angle | Problem it opens on | Pairs with |
|---|---|---|---|
| V1 | **Tool overload** | A million tools, no idea who to trust, each one hard to use, tabs everywhere | The core premise (all traffic) |
| V2 | **Hiring cost** | $75k/yr salesperson before a single call is booked | Email Variant A repliers |
| V3 | **Missed intent** | Everyone's emailing the same lists; buyers already in motion get missed | Email Variant B repliers |
| V4 | **Founder time** | Founders still prospecting themselves — hours lost to lists and dead follow-ups | Email Variant C repliers |
| V5 | **Referral cliff** | Referrals slow down and nothing reliable fills the gap | Email Variant D repliers |

All five converge into the same Agitate (the complexity/tab-chaos compounding the opening pain), the same training + system reveal, the same offer block. Panel feedback may reshape bodies freely; the angle mapping and the offer never move.

## Steps

**Run directory (all artifacts, so a resumed session can check done-rules):** `~/.claude/skills/claude-leadgen-magnet-prototypes/runs/<YYYY-MM-DD>/` — files: `digest.md`, `positioning.md`, `proof.md`, `v1.md`…`v5.md`, `panel-round-<n>.md`, `report.md`. Every done-rule check starts by reading this directory; reuse the newest run directory unless Bjion says start fresh.

### Step 1 — Mine who's replying and what's resonating
Re-verify ground truth (keys, campaign ids, the server-allowlist line). Resolve the guide campaigns: list Smartlead campaigns and match names containing Clay / Claude / guide / outreach; fall back to the Supabase campaigns table (lilly-data); if one still won't resolve, mark it blocked and (in ON mode) ask at the pause. Pull recipients + positive replies from campaign 3509012 and every resolved guide campaign (Smartlead API reads + Supabase replies archive — reads only). Write `digest.md`: who the positive repliers are (titles, company types, sizes), which email variant/angle is winning, verbatim reply quotes capturing the words THEY use for the pain, and the campaigns' measured reply/positive rates — plus a booking rate if the data actually yields one (these feed the calculator's conservative-assumption footnote).
**Done-rule**: `digest.md` exists with (a) campaign 3509012 pulled, and each guide campaign either pulled or explicitly recorded blocked with the reason (never a silent drop), (b) a title/segment breakdown of positive repliers, (c) ≥5 verbatim positive-reply quotes, (d) a one-line "winning angle so far" call, (e) measured reply/positive rates recorded with their campaign ids (booking rate recorded as measured or "none measured"), (f) every Ground-truth unknown resolved and recorded, or explicitly marked blocked.

### Step 2 — Mine the market: competitors + our own winners
(a) GojiBerry, Origami, and ListKit: browse their product + marketing pages; extract WHICH pains they agitate and HOW (verbatim phrases), their simplicity promises, their offer shapes, and ListKit's calculator UX beyond the captured spec. (b) Read all three previous Navreo magnets end to end; note the structures, proof formats, and moves that converted.
**Done-rule**: `positioning.md` exists with (a) ≥8 pain/agitation entries, each with a verbatim source phrase + source, (b) one line per entry on how Navreo's simplicity+design angle beats it, (c) ≥5 reusable moves lifted from the three previous magnets, each tagged with which magnet it came from.

### Step 3 — Build the proof inventory
Collect every claim the magnet may make: case studies and numbers from navreo.ai, the Supabase archive (named clients, {{CaseStudy}} names, the $3M+ pipeline line, meetings booked), and still-true claims from the previous magnets. Each entry: the claim, the source, where it's usable.
**Done-rule**: `proof.md` has ≥6 proof points, each with claim + source; anything unsourced is marked UNUSABLE and never appears in any draft or in the calculator.

### Step 4 — Draft the five versions
Write `v1.md`…`v5.md` per the angle table. Every version contains, in order:
- **[VSL PLACEHOLDER]** at top, with a ≤5-line brief: the video walks the whole system end to end, and lists the exact points where real examples of things we've done get dotted in.
- **PAS arc** — Problem = the version's angle in the reader's own words (Step 1 quotes); Agitate = Step 2's proven agitations + the tab-chaos/trust spiral; Solution = the training itself: how to find high-intent buyers from one simple Claude chat, shown step by step with enough substance that the reader could genuinely start (this is the free value; the previous magnets set the depth bar).
- **≥3 real receipts** from `proof.md` dotted through the body.
- **≥2 inline DIAGRAM briefs**, formatted `[DIAGRAM — slug: what to draw, elements/labels, what it proves]`, placed exactly where each diagram belongs.
- **The offer block**: the verbatim promise, presented in the ListKit shape (one headline promise, everything-included checklist of what Navreo runs for them, zero-additional-costs statement, the "too good to be true" objection pre-empted, risk reversal from the live email variants, trust bar from `proof.md` only), with an **[ROI CALCULATOR EMBED]** slot where the Step-5 calculator gets embedded.
- **Book-a-call CTA.**
Voice = the Fazio voice throughout. No emoji.
**Done-rule (per version)**: every listed element present and findable by scanning; the offer promise diffs clean against Ground truth; every number traces to `proof.md`; zero fabricated names, quotes, or ratings; body ≤1,600 words (`wc -w`, excluding DIAGRAM briefs).

### Step 5 — Build + host the Navreo ROI calculator
One self-contained static HTML page (no backend, no login, inline CSS/JS, Navreo design language), mirroring the captured ListKit shape but built on OUR offer — the funnel starts from the guaranteed promise, not send volume: **30 approved leads (fixed, from the offer) → meetings booked (booking rate: Step 1's measured rate if one exists, otherwise a reader-adjustable slider — never an invented number, never ListKit's 40%) → deals closed (close-rate slider, 5–50%) → projected revenue (LTV slider)**; cost + ROI lines only if Bjion supplied the price (Ground-truth unknown); conservative-assumption footnote citing where each fixed number came from; book-a-call button beneath. Add the file to `~/navreo-signals` and its path to `_AUTH_PUBLIC_GET` (the gate's authorized one-line edit), push to `main`, poll `/api/version` until the commit is live.
**Done-rule**: (a) anonymous `curl` of the deployed URL returns 200 with the calculator markup (no login redirect), (b) the page renders and computes correctly in the browser pane (screenshot), (c) every fixed number traces to Step 1/3 (sliders carry no sourced claim), (d) the push diff shows exactly one added file + the one-line allowlist edit, nothing else.

### Step 6 — Panel + fix loop
Round 1: spawn ONE panel of 5 fresh simulated panelists — **3 non-technical founders + 2 sales leaders**, persona details calibrated to Step 1's actual positive-replier titles — each independently scoring ALL five versions. Each panelist receives ONLY the rendered draft (the full markdown body of each version, nothing else — no research, no authorship context), reads as a skeptical cold-traffic recipient who just replied "sure, send it over", and is told that [VSL PLACEHOLDER], [DIAGRAM …] and [ROI CALCULATOR EMBED] stand for a finished video / finished diagrams / working calculator (the briefs describe what will appear) — score the copy and offer as if those assets are present. Output per panelist per version: integer 1–10 on each of the four DONE-BAR statements + a worst-moment quote + the single change that would raise their lowest score. Write `panel-round-<n>.md`.
A version passes only at the DONE-BAR. Failing versions get rewritten against the worst-moments; each retry re-panels ONLY the failing version with 5 FRESH panelists (a re-panel = one retry; max 3 per version; never reuse a panelist who saw a prior round). The final-report table uses each version's final-round scores.
**Done-rule**: every version either passes the DONE-BAR or is marked FAILED-BAR with its real final scores. Never inflate scores.

### Step 7 — Publish to Notion + hand-off
Create the 5 pages in the Navreo Notion workspace (new pages only, per the gate; default parent per Ground truth; in ON mode confirm parent + titles at the pause). Publish ALL five versions, including any at FAILED-BAR — a FAILED-BAR page still ships as a prototype for Bjion's review, tagged FAILED-BAR in the report — but the loop is still never declared done while any version sits at FAILED-BAR. Match the house look of the previous magnets. Replace each [ROI CALCULATOR EMBED] slot with a Notion embed block pointing at the Step-5 URL. Read each page back independently (fetch the public URL or API read), then open at least one published page in the browser pane and screenshot the calculator visibly rendering inside the Notion embed.
**Done-rule**: 5 page URLs live, each read back containing (a) the VSL placeholder, (b) every DIAGRAM brief, (c) the calculator embed block pointing at the live URL, (d) the verbatim offer promise; plus (e) the in-Notion embed screenshot; `report.md` written and the report delivered per the spec below.

## Final report (always, both modes)

- Steps passed / skipped / FAILED, with reasons and retry counts.
- The 5 Notion URLs, each tagged with its angle and which email variant it pairs with; the calculator's public URL + its assumption sources.
- The scorecard table — 5 versions × 4 statements × 5 panelists (final round) — pass/FAILED-BAR per version, and the recommended winner with one line of reasoning.
- The consolidated **diagram to-do list** (every DIAGRAM brief, with page + placement) and the **VSL brief** (what the video covers + the example insertion points, merged from the placeholders).
- Proof points used vs marked UNUSABLE.
- Suggested next moves (not executed): diagrams via create-figma-diagram, record the VSL, wire the winner into the live sends via lilly-bot.

## Hard don'ts

- **Never alter the offer promise.** The Email-2 wording in Ground truth appears verbatim in every version; the presentation is ListKit-shaped, the substance never moves.
- **Never fabricate proof** — no invented numbers, clients, quotes, ratings, or calculator assumptions; if Step 1/3 can't source it, it doesn't ship. The ListKit trust-bar numbers (977M+/98%/4.8) and 40% booking assumption are THEIRS, never presented as ours.
- **Never edit, overwrite, or delete the three existing lead-magnet Notion pages** — or any existing Notion page. In the signals repo, the ONLY permitted edit to an existing file is the single `_AUTH_PUBLIC_GET` line.
- **Never contact a prospect from this loop**: no sends, no Smartlead/HeyReach writes, no list uploads, no test emails to real addresses. Reads only.
- **Never spend paid credits** (Prospeo, AI Ark, MillionVerifier, Trigify — none needed, none allowed).
- **Never drop or fill the VSL placeholder** — it ships as a placeholder with its brief; recording the video is Bjion's job.
- **Never ship the calculator behind a login** — a gated embed renders as a login box inside Notion; anonymous-200 proof or it isn't done.
- **Never soften the DONE-BAR** (9/10+, all 5 panelists, all four statements) and never declare done while any done-rule fails or any version sits at FAILED-BAR unreported.
