---
name: porkbun-domain-ideator
description: "Ideate ALT-DOMAIN variants for an EXISTING brand (e.g. cold-email sender infrastructure, sender-rotation pools, redirect domains, brand-defence registrations), then bulk-check availability + price via Porkbun's `/api/json/v3/domain/checkDomain` endpoint, and return a clean shortlist the user can paste into porkbun.com/bulk to add to basket manually. Use this skill whenever the user wants to find ~30-100 cheap available alt-domains for an existing brand, expand a brand's domain footprint, build a sender-rotation domain pool, get throwaway domains for cold-email infrastructure, register defensive variants, or generate `<brand><word>.<tld>` / `<word>with<brand>.<tld>` / `get<brand>.<tld>` combinations. Trigger on phrases like 'ideate domains for [brand]', 'find me alt domains for [brand]', 'generate domains for [brand]', 'we need sender domains for [brand]', 'add generic words to [brand]', 'expand the domain footprint of [brand]', 'check availability for these brand variants'. Runs a 4-block setup wizard (brand basics with WebFetch-prefilled description, word-category picklist, TLD picklist, patterns + target-count) — defaults pre-checked, user just calls out diffs. Then **iterates: ideate → check → top up — repeats rounds until the user's requested AVAILABLE count is met** (typical hit rate 50-70%, so a target of 50 usually takes 1-2 rounds at ~9 min each, max 5 rounds before asking the user to relax constraints). Each round dedupes against previously-burned candidates and can optionally widen the word/TLD palette. **Streams AVAILs to the user in batches of 5 as they come back from the API** (background script + Monitor + batched reporting) so the user has live visibility into the 9-min run instead of staring at a silent waiting indicator. Porkbun's `/checkDomain` is rate-limited at 1 call per 10s sliding window (script sleeps 11s for safety), so cost is purely time, not money. Outputs ONLY the verified-available shortlist as a sorted markdown table plus a plain one-per-line copy-paste block ready for porkbun.com/bulk. Never shows the user an unverified candidate list — the verify-first principle is non-negotiable."
---

# Porkbun Domain Ideator

## Purpose

Generate ~30-100 alt-domain variants for an EXISTING brand (the brand already has a primary domain; we're finding supplemental/throwaway/sender-rotation domains), bulk-check availability and price via Porkbun's API, and return a paste-ready shortlist for porkbun.com/bulk.

Typical use case: cold-email sender infrastructure. A brand sending high volume distributes sends across 10-50+ secondary domains to avoid reputation concentration on the primary. Each secondary is cheap (.info, .biz, .pro etc. often $1-3 year 1), redirects to or aliases the primary, and gets used as a sending domain. Other use cases: defensive brand-variant registration, redirect domain pools, microsite domains for campaigns.

This skill is NOT for creative naming of a brand-new business — for that, ideate freeform without this skill.

---

## Step 1: Setup wizard

### Step 1a: WebFetch the brand's primary domain to pre-fill

Before showing the wizard, try to WebFetch the brand's primary site so the "what the brand does" line and vertical-specific word picks are pre-populated instead of bouncing back at the user. This converts the wizard from a quiz into a quick yes/no review.

URL resolution order:
1. **Domain explicitly given** in the user's prompt (e.g. "ideate domains for amplifyy.com") → fetch that.
2. **Memory check** — if `MEMORY.md` has a project memory naming this brand with a domain (e.g. amplifyy → kevin@amplifyy.com), use the matching domain.
3. **Guess** `<brand>.com` first; if it 404s or returns parked/registrar boilerplate, try `<brand>.io`, `<brand>.co`, `<brand>.ai`. Stop after the first that returns real brand content.
4. **Give up** and ask the user for the URL — only after the above all fail.

Run the WebFetch with a prompt that extracts: what the company does in one sentence, who their ICP is, the vertical/category, and any vocabulary that recurs on the homepage (product names, value props, jargon). That recurring vocabulary becomes the seed for the vertical-specific word pick.

If the homepage fetch is too generic to draw a vertical from (e.g. landing page with only a logo and signup form), don't guess — leave the description blank in the wizard and ask the user to fill it.

### Step 1b: Render the wizard

Render as a single structured message. Show defaults pre-checked, let the user override anything in their reply. Don't proceed past the wizard until brand name + brand description are answered (everything else has sensible defaults).

The wizard has four blocks: brand basics → word-category picks → TLD picks → patterns/count. Use checkbox-style markers `[✓]` (default on) and `[ ]` (default off) so the user can see at a glance what they're getting and just call out diffs (e.g. "turn on .xyz, turn off .me, exclude 'fba'").

When pre-filling from WebFetch, mark the pre-filled fields with `(from <domain> — correct if wrong)` so the user knows it's inferred, not their input.

```
🪄 Domain Ideator — Setup

**1. Brand basics**
- Brand name? (e.g. "amplifyy")
- What does the brand do? (1 line, so I can pick vertical-relevant words — e.g. "Amazon ads agency for FBA sellers")

**2. Word categories** — which categories of generic words to combine with the brand? (default: all five general categories on, vertical-specific words inferred from brand description)
- [✓] Growth verbs — growth, scale, reach, boost, lift, accelerate, expand, amplify
- [✓] Outcomes — revenue, sales, leads, deals, conversion, bookings, performance
- [✓] Function/dept — marketing, agency, partners, strategy, media, ops, brand
- [✓] Infrastructure — hub, engine, lab, platform, system, network, flow, machine
- [✓] Wrappers — get, try, my, with, use, build, launch, hey (used in `wrapper<brand>` style)
- [auto] Vertical-specific — inferred from the brand description (e.g. Amazon → sellers, brands, marketplace, listings)
- Custom words to ADD?
- Words to EXCLUDE? (off-brand or weird-association)

**3. TLDs** — which extensions to allow? (default: top 4 cheap pool)
- [✓] .info   ($2-4 Y1 / $15-20 renew, most common in user's past sender pools)
- [✓] .biz    ($4-6 Y1 / $15-18 renew, solid second)
- [✓] .org    ($9-12 Y1 / $11-14 renew, even Y1/Y2 pricing)
- [✓] .pro    ($2-12 Y1 / $15-20 renew, often promo Y1)
- [ ] .xyz    ($1-3 Y1 / $12-15 renew, cheap but big renewal jump)
- [ ] .click  ($3-5 Y1 / $12-15 renew, slight spam-association risk on some MTAs)
- [ ] .one    ($2-5 Y1 / $15-18 renew)
- [ ] .online ($1-5 Y1 / $35-45 renew, big renewal jump)
- [ ] .digital($3-8 Y1 / $30-40 renew, big renewal jump)
- [ ] .me     ($9-15 Y1 / $20-25 renew)
- [ ] .live   ($3-6 Y1 / $30-35 renew, big jump)
- [ ] .site   ($1-3 Y1 / $35-40 renew, big jump)

**4. Patterns + count**
- Patterns (default all 5 on):
  - [✓] Brand-suffix    — `<brand><word>.tld` (e.g. amplifyysales)
  - [✓] Brand-prefix    — `<word><brand>.tld` (e.g. salesamplifyy)
  - [✓] Wrapper         — `get/try/my/with/use<brand>.tld`
  - [✓] Connector       — `<word>with<brand>.tld` (e.g. saleswithamplifyy)
  - [✓] The-pattern     — `the<brand>.tld`, `the<brand><word>.tld`
- How many AVAILABLE candidates do you want? (default 50)
  Note: This is a TARGET, not a candidate-count cap. The skill iterates — round 1 ideates ~target candidates, then tops up with additional rounds until that many come back AVAILABLE. Typical hit rate is 50-70%, so a target of 50 usually takes 1-2 rounds (~9-18 min). Hard targets in saturated namespaces can take 30-45 min. Porkbun rate-limits `/checkDomain` to 1 call per 10s — checkDomain is free, the cost is time.

Reply with any answers / overrides. Defaults apply for anything you skip. Once confirmed, I'll ideate + check + share only what's actually buyable.
```

**Filling gaps from context:** Combine the WebFetch result (Step 1a) with `MEMORY.md` brand context (e.g. amplifyy → Kevin Dormer's Amazon-ads DFY client). Show the user the wizard with both sources already merged into the pre-filled fields, marked `(from <source>)` so they can see what's inferred vs. their input. They should only have to touch the wizard if they want to override.

**No second confirmation:** Once the user replies to the wizard, proceed straight into generation + check. Don't show an unverified candidate list for them to prune (the whole point of the verify-first principle). If they want to course-correct, they'll do it from the verified-available shortlist.

---

## Step 2: Build the generic-word palette

Tune to the brand's vertical. Mix from these categories — pick ~30-40 words total, weighted toward the brand's space:

**Universal growth/revenue vocab** (works for most B2B):
growth, scale, reach, boost, lift, expand, accelerate, amplify, signal, engine, hub, lab, platform, system, flow, machine, pipeline, revenue, sales, leads, deals, bookings, conversion, acquisition, retention, expansion, funnel, demand, performance, results, roi

**Function/department**:
marketing, ads, sales, ops, brand, agency, partners, partner, media, campaigns, creative, analytics, data, insights, strategy, playbook, intelligence

**Infrastructure**:
engine, hub, lab, platform, network, signals, flow, system, machine, ops, build, launch, deploy

**Wrappers**: get, try, my, with, use, build, launch, start, scale, run, the, hey, go (used in `wrapper<brand>` and `<brand>wrapper`)

**Vertical-specific overlays** — add these on top of universal vocab:
- **Amazon / e-com**: sellers, brands, fba, marketplace, sponsored, listings, ppc, asin, roas, merchants, dtc, shopify
- **Cold email / outbound**: outbound, outreach, prospecting, pipeline, replies, booking, meetings, intro, opener, cadence, sequence
- **Recruiting / talent**: talent, hires, hiring, sourcing, recruit, execs, executive, leadership, search
- **Consulting / advisory**: advisors, advisory, strategy, intelligence, geo, risk, reputation, comms, global
- **SaaS / product**: app, api, cloud, stack, suite, tools, kit, studio
- **Healthcare / clinical**: clinical, devices, trials, deploy, provisioning, mobility
- **Education / courses**: courses, learn, academy, school, university, certified

If the user's vertical isn't covered, ask them for 5-10 vertical-specific words.

---

## Step 3: Generate the candidate list

**Same-word duplicates across patterns are allowed and often valuable.** A generic word like "sales" can legitimately produce `amplifyysales`, `salesamplifyy`, and `saleswithamplifyy` — three separate candidates with one shared theme. For the sender-rotation use case (the dominant one), multi-form variety per theme is a feature: it lets one theme be spread across three sender domains, breaking the "one theme = one mailbox" correlation that mailbox providers look for. Don't dedupe by base word unless the user explicitly asks for it.

Combine the brand + word palette + TLD palette across the 5 patterns. Aim for the requested count (default 50), with diversity:

**Pattern 1 — Brand-suffix** (`<brand><word>.<tld>`) — most common, ~50% of candidates:
amplifyysales.info, amplifyygrowth.biz, amplifyyscale.org, amplifyyengine.pro

**Pattern 2 — Brand-prefix** (`<word><brand>.<tld>`) — ~15%:
salesamplifyy.info, growthamplifyy.biz, scaleamplifyy.org

**Pattern 3 — Wrapper** (`get/try/my/with/use<brand>.<tld>`) — ~15%:
getamplifyy.info, tryamplifyy.biz, myamplifyy.org, withamplifyy.pro, useamplifyy.xyz

**Pattern 4 — Connector** (`<word>and<word>.<tld>` or `<word>with<brand>.<tld>`) — ~10%:
saleswithamplifyy.info, growthwithamplifyy.biz, reachandscale.org

**Pattern 5 — The-pattern** (`the<word>.<tld>` or `the<brand>.<tld>`) — ~10%:
theamplifyy.info, thebravecourses.info

Spread TLDs across the palette (don't put everything on .info). Default weighting roughly: .info 30%, .biz 20%, .org 15%, .pro 10%, .xyz 8%, .click 5%, .one 5%, .digital 4%, other 3%.

Validate each candidate: lowercase, ASCII alphanumeric + hyphens only, no leading/trailing hyphen, label ≤ 63 chars. Drop anything invalid.

---

## Step 4: Pre-flight credentials

The bulk-check script needs `PORKBUN_API_KEY` and `PORKBUN_SECRET_API_KEY`. Check if they're in the keys file:

```bash
grep -E '^export PORKBUN' ~/.navreo-keys.env
```

If both are set, the script picks them up (zshrc auto-loads). If not, ask the user to either:

(a) Add to `~/.navreo-keys.env` (preferred — persists):
```
export PORKBUN_API_KEY=pk1_...
export PORKBUN_SECRET_API_KEY=sk1_...
```

Keys are generated at [Porkbun → Account → API Access](https://porkbun.com/account/api). Each domain in the user's Porkbun account doesn't need API access enabled for checkDomain — that toggle is only for write operations like updateNs.

(b) Paste inline for this run only. If pasted in chat, flag that the transcript now contains them and recommend rotating after.

---

## Step 5: Run the bulk availability check, iterating until target met

**Critical rule: never show the user an unverified candidate list and ask them to prune it.** Verification via `/checkDomain` is free and ~11s/candidate (rate-limited). Make the user mentally filter "is this even available?" alongside "is this on-brand?" wastes their attention. Generate the candidates internally, write to a temp file, run the check, then show only what's actually buyable.

**Iterate until the requested count of AVAILABLE candidates is met.** If the user asks for 50 and round 1 returns 28 available, generate enough additional candidates to plug the gap (oversampled for the hit rate) and check them. Repeat until the target is hit or termination kicks in.

### Iteration loop (pseudocode)

```
target = user-requested count from the wizard (default 50)
verified_avail = []         # all AVAIL domains collected so far
burned = set()              # all domains already checked (AVAIL + TAKEN + FAIL), exact-string dedup only
round = 1
max_rounds = 5              # escape hatch — total ~45 min at 50/round

while len(verified_avail) < target:
    needed = target - len(verified_avail)
    # Estimate hit rate from prior rounds (floor 30% to bound oversample)
    hit_rate = max(0.30, len(verified_avail) / max(1, len(burned)))
    # Oversample 10% so we don't undershoot
    to_generate = ceil(needed / hit_rate * 1.10)

    new_candidates = generate(
        excluding=burned,             # never re-check anything from previous rounds
        count=to_generate,
        widen_palette=(round >= 2),   # loosen on later rounds if palette getting tight
    )
    if len(new_candidates) == 0:
        break   # palette exhausted, can't generate more

    write to /tmp/<brand>_round{round}.txt
    run scripts/bulk_check_porkbun.py
    parse results: AVAIL → verified_avail, all → burned

    if round >= max_rounds:
        break
    round += 1

return verified_avail[:target]   # trim if oversampling overshot
```

### Per-round announcement

Before each round, post a one-line status to keep the user informed:

```
Round 1: checking 50 candidates (~9 min)
Round 1 done: 28/50 AVAIL. Generating 40 more candidates for round 2 (~7 min).
Round 2 done: 47/50 AVAIL. Generating 8 more for round 3 (~1.5 min).
Round 3 done: 51/50 AVAIL — trimming to 50.
```

### Widening the palette on later rounds

If round 2+ is needed, expand the candidate space so we're not just sampling the same combinations again:
- Round 1: configured word palette + configured TLDs + configured patterns
- Round 2: + secondary growth/function vocabulary (intelligence, accelerator, ventures, collective, studio, ops, system)
- Round 3+: + alternative TLDs from the broader cheap pool (.xyz, .click, .one, .digital — even if user defaulted them off, ask first before crossing this line; the user might prefer to relax word constraints over TLD constraints)
- Round 4+: prompt the user — "saturating the original palette, want to relax word/TLD constraints or stop here?"

### Termination + reporting

When the loop exits:
- **Target met** → render shortlist (Step 6).
- **Palette exhausted** → render whatever was found, tell the user "couldn't reach N, got X — consider broader word palette / TLDs."
- **Max rounds hit** → render whatever was found, ask user if they want a fresh batch with relaxed constraints.

### Script invocation with streaming progress

For each round, write candidates to `/tmp/<brand>_round<N>.txt` (one domain per line), then kick the check off **in the background with unbuffered Python**:

```bash
source ~/.navreo-keys.env && python3 -u ~/.claude/skills/porkbun-domain-ideator/scripts/bulk_check_porkbun.py /tmp/<brand>_round<N>.txt 2>&1
```

Set `run_in_background: true` on the Bash call. **Both `python3 -u` and background are required:** without `-u`, Python block-buffers stdout when redirected to a file, and Monitor sees nothing for the entire 9-min run. Without background, the foreground Bash blocks you from responding to the user mid-run.

Then **immediately arm a Monitor on the output file**:

```bash
tail -f <task-output-file> | grep -E --line-buffered "AVAIL|FAIL|Results:|Traceback|Error"
```

The Monitor fires on:
- Each `AVAIL` line — buffer for batched reporting (see below)
- Each `FAIL` line — usually transient read-timeouts or rate-limit cascades (see below)
- The final `Results: AVAIL=N PREMIUM=N TAKEN=N FAIL=N` — batch complete, render shortlist (Step 6)
- Any `Traceback` / `Error` — script crashed; investigate

The script itself:
1. Validates credentials via `/ping` (fast-fails on auth)
2. POSTs each candidate to `/domain/checkDomain/{domain}` with 11s sleep between calls
3. Prints one line per check showing status and price
4. Writes results to `<input>.results.json` alongside the input file

#### Stream AVAILs to the user in batches of 5

As AVAIL events arrive, post a batch update **every 5** in this shape:

```
**Batch N (X of Y)**:

```
domain1.tld
domain2.tld
domain3.tld
domain4.tld
domain5.tld
```

Z more to find.
```

Where `X` is the cumulative AVAIL count across the whole job (across all rounds), `Y` is the user's target, and `Z` is `Y - X`. Between batches, single-line per-AVAIL acknowledgements (`1/5 (batch N): <domain>`) are fine but optional — the batch-of-5 is the load-bearing update.

If the user specifies a different cadence ("every 10", "as soon as you find each one", "don't bother streaming"), respect that.

#### Handle FAIL cascades

If ≥3 consecutive `FAIL ... 1 out of 1 checks within 10 seconds used` events arrive, the script's 11s sleep has stopped recovering — usually because (a) a prior 30s read timeout desynced the pacing, or (b) another `bulk_check_porkbun` process is competing for the same Porkbun API key (different Claude session). Let the current batch finish, then:

1. Run `pgrep -f bulk_check_porkbun` to check for concurrent jobs. If any, coordinate with the user before killing.
2. Wait 45-60s for the rate-limit window to fully clear.
3. Re-run only the FAIL'd candidates as a small retry batch (`<brand>_round<N>_retry.txt`).

Read-timeout FAILs (`HTTPSConnectionPool ... Read timed out`) are single-shot — one retry usually clears them.

#### Runtime and rate-limit notes

Runtime: **~11 seconds per candidate** (Porkbun rate-limits `/checkDomain` to 1 call per 10s sliding window). 30 candidates ≈ 5.5 min, 50 ≈ 9 min, 100 ≈ 18 min. Multi-round runs can push total to 20-45 min for hard target counts. Tell the user the per-round ETA when kicking off each round.

**Don't try to go faster.** A 1s sleep causes ~80% of calls to return `"1 out of 1 checks within 10 seconds used"` because the rate limit is sliding-window from the previous attempt (success or fail counts). 11s gives a 1s safety margin over the 10s window.

If the user mentions a vibe-preference mid-stream (e.g. "no ad-flavoured words"), apply it in the NEXT round's candidate generation, not as a post-check filter.

---

## Step 6: Render the shortlist

Read the `.results.json` sidecar and format AVAILABLE survivors as a markdown table. Sort by:
1. Premium = no first (cheaper, no special handling)
2. First-year price ascending
3. Domain alphabetical

Columns: Domain | Y1 | Renewal | Notes (e.g. "promo Y1", "premium")

```
**Available** (18 of 52) — sorted by year-1 price

| Domain                       | Y1     | Renewal | Notes    |
|------------------------------|--------|---------|----------|
| amplifyysellers.info         | $2.99  | $14.99  | promo Y1 |
| amplifyyfba.info             | $2.99  | $14.99  | promo Y1 |
| amplifyysales.biz            | $5.99  | $14.99  |          |
| ...                          |        |         |          |

**Taken** (34): amplifyy.com, amplifyy.io, amplifyysales.info, ... (collapsed if >10)

**Next step**: copy the block below, paste into https://porkbun.com/checkout/search (or the bulk-search if Porkbun re-adds it), check the boxes for the ones you want, click "Add to Cart". Cart checkout is manual — Porkbun's API doesn't expose registration.
```

Then print a clean copy-paste block of just the available domains, one per line, no formatting:

```
amplifyysellers.info
amplifyyfba.info
amplifyysales.biz
...
```

Be aware: **renewal prices matter a lot** for sender-rotation pools. Many TLDs are $1-3 first year and $15-30 renewal. Highlight any renewal > 5× the first-year price in the Notes column so the user can decide if they're OK paying the renewal in 12 months. If they're building a long-term pool, renewal cost is the real cost.

If fewer than 5 came back available, offer to re-ideate a fresh batch (looser TLD palette, different word mix, longer/shorter variants) before sending the user to checkout.

---

## Step 7: Manual checkout

The skill stops at "paste-ready list." Tell the user:

1. Go to porkbun.com (logged in)
2. Use the search bar at the top OR the bulk-search if available (Porkbun has moved this around — homepage search accepts multi-line paste in most versions)
3. Paste the list, hit Search
4. Check the boxes for the domains they want
5. Click "Add to Cart"
6. Review cart for first-year promo applicability, complete checkout

Porkbun's API doesn't expose a `register` endpoint, so this step can't be automated through this skill.

---

## Why these design choices

### Why ask for "what the brand does" upfront

The generic-word palette is the difference between useful and useless candidates. `amplifyysales.info` is great for an ads agency, irrelevant for a healthcare device company. A one-line description lets the skill pick vertical-appropriate words instead of pasting a generic vocabulary list at every brand.

### Why check BEFORE showing candidates

Verification is free (`/checkDomain` costs nothing, ~1.2s/candidate). Showing the user an unverified candidate list and asking them to prune it wastes their attention: they have to mentally filter "is this even available?" alongside "is this on-brand?" The right flow is generate-then-check-then-show, so what the user sees is already buyable. Brand-fit pruning still happens, but on a shorter, verified list. If a vibe-preference surfaces mid-stream (e.g. "no ad-flavoured words"), apply it in candidate GENERATION and re-run, don't surface it as a post-show prune.

### Why filter to AVAILABLE only in the shortlist

The user's next action is "paste into Porkbun and add to cart." They don't want to scroll through 50 results to find 18 buyable ones. The collapsed "Taken" list is there for namespace-saturation signal (and for the user to verify "yes I see X is taken, that confirms what I expected").

### Why flag big renewal-price jumps

TLDs like .xyz, .online, .info, .digital, .pro frequently run $1-3 promotional first-year pricing with $15-30 renewal. For a sender-pool of 30+ domains, the year-2 cost can 5-10x the year-1 cost. The user should see this before deciding which to add to cart.

### Why no register-via-API

Porkbun's public API exposes check / DNS / manage / ping endpoints, but registration requires a reseller agreement that this account doesn't have. The skill is honest about that and stops at "paste-ready list."

### Why stream AVAILs in batches of 5

A 9-min batch is a long time to leave the user staring at a blank waiting indicator. Streaming AVAILs as they come in (batched at 5 to avoid notification spam) gives the user real-time visibility into hit rate, lets them flag a name they hate before paginating further, and turns "waiting" into "watching." Without streaming, the user gets no signal between "starting check" and "here are 31 results" 9 minutes later. With streaming, they see momentum every ~55 seconds.

Batch-of-5 is the sweet spot: per-domain updates (~1 every 11s) is notification spam; per-batch-of-10 (~1 every 110s) feels slow. 5 lands at one update every ~55s — frequent enough to feel live, sparse enough not to drown.

### Why 11-second sleep between checks

`/checkDomain` is rate-limited at exactly 1 call per 10 seconds (sliding window from previous attempt). Verified empirically 2026-05-11: with a 1s sleep, 39 of 50 calls returned `"1 out of 1 checks within 10 seconds used"`. 11s gives a 1-second safety margin over the 10s window. This is slow (50 candidates = ~9 min) but unavoidable on this endpoint. Tell the user the ETA before kicking off so they don't think it's hung.

---

## Reference: TLD palette characteristics

Defaults are picked for cheap, broadly-accepted-by-SMTP-providers TLDs. Quick sanity table:

| TLD     | Y1 typical | Renewal typical | Notes                                |
|---------|------------|-----------------|--------------------------------------|
| .info   | $2-4       | $15-20          | Most common in user's past pools     |
| .biz    | $4-6       | $15-18          | Solid second                         |
| .org    | $9-12      | $11-14          | More even Y1/Y2                      |
| .pro    | $2-12      | $15-20          | Often promo Y1                       |
| .xyz    | $1-3       | $12-15          | Cheap but high renewal jump          |
| .click  | $3-5       | $12-15          | Spam-association risk on some MTAs   |
| .one    | $2-5       | $15-18          |                                      |
| .online | $1-5       | $35-45          | Big renewal jump                     |
| .digital| $3-8       | $30-40          | Big renewal jump                     |
| .me     | $9-15      | $20-25          |                                      |
| .live   | $3-6       | $30-35          | Big renewal jump                     |
| .site   | $1-3       | $35-40          | Big renewal jump                     |

Avoid by default: .com (too expensive at scale, brand probably already owns the .com), .ai (expensive — $70+/yr), .io (expensive — $40+/yr), .co (expensive — $25+/yr), .app/.dev (require HSTS / TLS — extra setup).

User can override if they want any of these.

---

## Scripts

- `scripts/bulk_check_porkbun.py` — Reads candidate list from argv[1] (one domain per line), pings credentials, then POSTs each to `/domain/checkDomain/{domain}` with 11s sleep (Porkbun's `/checkDomain` is rate-limited to 1 call per 10s sliding window — 11s gives a 1s safety margin), prints per-domain status, writes `<input>.results.json` sidecar. Uses `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` env vars. **Always invoke with `python3 -u` and `run_in_background: true`** so Monitor can stream events to the user — see Step 5.
