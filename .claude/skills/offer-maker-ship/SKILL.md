---
name: offer-maker-ship
description: Static orchestration skill that ships the public "Offer Maker" page in the
  Navreo signals app — customer enters their website URL, gets 12-18 cold-email-ready
  offer ideas (specific problem + differentiator + favorable pricing + risk reversal,
  all passing the new-money test) with plain-English guidance, copy-all and CSV export.
  Builds backend route + one-page UI, mines VERBATIM winning offers from Supabase
  (identities anonymised), deploys live to Render, and proves it with 10 simulated
  mixed-ability testers on the production page. One fixed step list, each step with a
  checkable done-rule, retry caps, and a Loop Training Mode toggle. Use when the user
  says "run the offer maker ship", "build the offer tool", "ship the offer ideation
  page", or "/offer-maker-ship".
---

# Offer Maker — public offer-ideation page, shipped and tester-proven

Customers (business owners / heads of sales with LOW cold-email understanding) paste their
website URL and get a menu of cold-email-ready offers they can copy or download as CSV and
present back to Navreo. The offers follow the offer framework law (below); the page teaches
as it goes — every screen assumes zero outbound knowledge. Static loop — fixed steps, each
has a done-rule, Training Mode controls the pauses. No platform state is saved.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
Tester rounds (Step 7) cap at **max 4 full rounds**. On cap-hit: record the step as FAILED
with the reason, continue to the next step if it doesn't depend on the failed one, and
surface every FAILED step in the final report. Never silently exceed the cap. Never
declare the skill done on a cap-hit.

**Spend gate (both modes, non-negotiable):** the only spend is OpenAI `gpt-5-mini` calls,
hard-capped at **400 calls for the whole loop** (ledger below). The shipped public endpoint
must itself be capped: **max 10 generations per IP per hour and 200 per day globally** —
without these limits in code, the page does not ship. Supabase access is READ-ONLY.
Nothing is ever sent to leads, no campaigns touched, no rows deleted.

**Confidentiality gate (user, 2026-07-12, revised same day): VERBATIM examples are IN.**
Supabase winning-offer mining pulls the actual offer lines that drove positive replies and
uses them verbatim as few-shot examples in the generation prompt and as "real offers that
got replies" examples in the UI. Stated default (veto-able): client and prospect names are
swapped for neutral placeholders ("a dev agency", "{{company}}") — the copy stays verbatim,
the identities don't. Prospect email addresses and personal names never appear anywhere.

## Goal

1. `app/offer.html` is live on the production Render URL, reachable **without login**
   (user, 2026-07-12: public page).
2. Entering any real company website URL returns **12-18 offer ideas** (default; user may
   veto the count), each with: the specific high-consequence problem, the differentiator,
   favorable-pricing angle, a risk reversal (spread across pay-after-result /
   pay-per-result / guarantee+refund), a suggested stipulation, a one-line example opener,
   and a plain-English "why this works on cold email" explainer. Every offer sells NEW
   leads/calls/sales (new money), never optimisation of something they already do.
3. Copy-all and CSV download both work; the CSV parses and matches the on-screen offers.
4. Scope default (veto-able): **offers only, no full email drafts** — customers present
   offers to Navreo; Navreo writes the copy.

> **THE DONE-RULE (single source of truth):** 10 simulated mixed-ability testers (novice
> business owner → savvy head of sales) each complete the flow cold on the PRODUCTION
> page — enter URL, understand the output, export — with average simplicity **≥ 8/10 and
> 10/10 completion**, AND the framework-compliance check passes on **5/5 test websites**
> (every offer has all four components + new-money). Anything less = not done. On the
> round cap, stop and report the gap honestly.

## Ground truth (verified 2026-07-12 — re-verify in Step 1, line numbers drift)

- **Email voice lives in `app/navreo_voice.py`** (added 2026-07-18): `build_email_prompt()` +
  `validate_email()` + `write_navreo_email()` are the single source of truth for the preview
  cold-email voice. `offer_email()` in server.py just calls them. Change the voice THERE, never
  by re-inlining a prompt. Voice rules + corpus: lilly-copywriter "THE NAVREO VOICE" section.
- App: `app/server.py` (~9,966 lines), stdlib `ThreadingHTTPServer`. POST handlers register
  in the `ROUTES` dict at `server.py:7838`. Static pages served from `app/`.
- LLM pattern to copy: `_run_claude_ideation` at `server.py:1275` — OpenAI `gpt-5-mini`
  via `http_json` (`server.py:213`) with `KEYS.get("OPENAI_API_KEY")`; key present locally
  in `~/.navreo-keys.env` and on Render via env group `navreo-secrets` (`render.yaml`).
  Regex-extracts a JSON array from the reply; falls back loudly on failure.
- Auth gate: `_AUTH_PUBLIC_GET` set at `server.py:8829`, `_AUTH_PUBLIC_POST` at
  `server.py:8831` — add `/app/offer.html` + the new API route there for public access.
- Server-side external fetch: `urllib.request.urlopen(..., context=SSL_CTX)` used
  throughout (e.g. `server.py:857`) — use for fetching the customer's website HTML.
- Winning-offer data: Supabase project `fnykldftbkrccihdjayl` — `replies` (positive
  categories), `sent_messages` (outbound copy archive), `campaigns`. Query shape per
  `lilly-data` skill. UNKNOWN: exact columns joining reply→sent copy — resolve in Step 2.
- Offer framework law (from the two source transcripts, 2026-07-12): a good offer =
  (a) specific high-consequence problem, (b) differentiator (what + why better),
  (c) favorable pricing, (d) risk reversal on a spectrum — pay-after-result (lowest
  recipient risk) → pay-per-result → guarantee+full-refund — protected by stipulations;
  cold traffic only buys NEW leads/calls/sales ("new money"), never optimisation; low-risk
  CTA (offer a Loom / a free sample) beats "book a call"; talk about what THEY get.
- Style laws (memories): `feedback_no_em_dashes` (no em-dashes in offer copy),
  `feedback_plain_english_explanations` (no jargon in UI), language laws in
  `project_unified_campaigns_lists_prototype`, `feedback_browser_verify_before_done`,
  deploy-repo gotcha in `INDEX_signals_app` (**iCloud REVERTS edits — reconcile
  repo↔iCloud after every deploy**).

## Budget ledger

| Surface | Cap | Debited by |
|---|---|---|
| OpenAI gpt-5-mini calls (build + tests + testers) | **400 total** | Steps 3, 5, 7 |
| Supabase | read-only, unlimited | Step 2 |

At 80% of the OpenAI cap: ON → pause and report; OFF → finish the current check, then
stop and report. A cap-hit is FAILED-with-gap, never "done".

## Steps

### Step 1 — Re-verify ground truth
Confirm every Ground-truth bullet against current code (line numbers drift). Prove the
OpenAI key with **one live gpt-5-mini call** (debit ledger). Confirm `_AUTH_PUBLIC_*`
mechanics still gate as described by curling a public and a non-public path locally.
- **Done-rule:** you can name (a) the current `ROUTES` dict line, (b) the current
  `_AUTH_PUBLIC_GET/_POST` lines, (c) a captured real gpt-5-mini response, (d) the
  Supabase tables respond to a read-only probe.

### Step 2 — Mine winning offers verbatim (read-only)
Per `lilly-data`: pull positive-reply-driving outbound copy (join replies categorised
positive → `sent_messages` bodies), extract the OFFER expressed in each, and keep the
winning lines VERBATIM, tagged by mechanism, risk-reversal type, pricing shape, and CTA
style, with per-line evidence (positive-reply count). Swap client/prospect identities for
neutral placeholders; keep the copy itself untouched. Save to
`~/.claude/skills/offer-maker-ship/winning-offers.md`.
- **Done-rule:** (a) the file exists with ≥10 verbatim winning offer lines, each with its
  positive-reply evidence and tags, (b) `grep` of the file for every client name in
  `INDEX_clients` and for any `@`-address returns nothing — identities swapped, copy
  verbatim.

### Step 3 — Backend: `POST /api/offer/generate`
New handler in `server.py` following the `_run_claude_ideation` shape: fetch the submitted
URL server-side (timeout ~15s, follow the homepage only, strip to text), build the prompt
from the offer framework law + the verbatim winning-offers file (embedded as a constant,
as few-shot examples), request
12-18 offers as a JSON array covering all three risk-reversal types, validate the shape,
return JSON. Failures return the REAL error (unreachable site, LLM failure) — no silent
fallback catalogue. Implement the per-IP (10/hr) and global (200/day) rate limits here.
Register in `ROUTES`; add route to `_AUTH_PUBLIC_POST`.
- **Done-rule:** local curl with `navreo.ai` returns valid JSON of 12-18 offers, all four
  components non-empty per offer; curl with a garbage URL returns a plain-English error,
  not offers; the 11th rapid request from one IP is refused with a clear message.

### Step 4 — Frontend: `app/offer.html` (one page, education-first)
Single page in house style (`navreo.css`, `shell.js` NOT required — public page stands
alone). Flow: URL input → progress state → offer cards grouped by risk-reversal type with
a plain-English intro explaining the framework and WHY these work on cold email (zero
jargon, no em-dashes). Each card: problem, differentiator, pricing, risk reversal,
stipulation, example opener, "why this works". A "real offers that got replies" section
shows a handful of the verbatim winning lines (identities anonymised) so users see what
good looks like. Copy-all button + CSV download (client-side blob). Banner: results
aren't saved — download before leaving. Add page to `_AUTH_PUBLIC_GET`.
- **Done-rule:** in a local browser (logged OUT): (a) page loads without redirect to
  login, (b) full flow renders offers with zero console errors, (c) the downloaded CSV
  parses and its row count equals the on-screen card count (independent read-back),
  (d) copy-all puts matching text on the clipboard.

### Step 5 — Framework-compliance check across 5 real websites
Run generation against 5 real, different-vertical sites (include `navreo.ai` + 4 varied:
e.g. an e-com brand, a dev agency, a logistics co, a local-service co). An automated judge
pass (LLM, debit ledger) scores every offer: has all four components, passes the new-money
test, no jargon, no em-dash, opener ≤ 20 words. Fix prompt and re-run on failures.
- **Done-rule:** 5/5 sites produce 12-18 offers with **100% of offers** passing all
  component checks and ≥90% passing new-money on first judge pass; per-site results
  recorded (FAILED rows count as complete rows).

### Step 6 — Deploy to Render and reconcile
Commit, push, wait for live. Marker-grep the deployed `offer.html` and hit the production
`/api/offer/generate` once with a real URL. Reconcile repo↔iCloud for every touched file
(iCloud reverts edits — diff must be empty).
- **Done-rule:** (a) production page returns 200 logged-out, (b) marker string found in
  deployed HTML, (c) one production generation returns valid offers, (d) repo↔iCloud diff
  for touched files is empty.

### Step 7 — Live proof: 10 simulated mixed-ability testers (production page)
10 personas from "never heard of cold email" to "head of sales who's run outbound", each
driving the PRODUCTION page in a browser cold: enter a real URL, interpret the output,
export. Each yields a transcript, simplicity score /10, pass/fail. Confused personas must
actually get stuck, not be rescued. Include one real-failure injection: a tester submits an
unreachable URL and must see the real plain-English error. Iterate UI copy between rounds
(max 4 rounds), redeploying via Step 6's done-rule each time.
- **Done-rule:** avg simplicity **≥8/10 AND 10/10 completion** in a single round, the
  failure-injection tester sees the real error, and a final production screenshot is
  captured showing rendered offer cards.

## Final report (always, both modes)

Steps passed/skipped/FAILED with reasons; the production URL; tester table (persona, score,
pass/fail, one-line friction note) and the round count; framework-compliance table for the
5 sites (offers generated, % passing each check); OpenAI ledger (calls used / 400); the
rate-limit settings shipped; CSV read-back result; screenshot path; winning-offers file
path with line count; anything deferred (e.g. count/scope vetoes to apply).

## Hard don'ts

- Never expose client or prospect IDENTITIES — winning-offer copy is used verbatim (user
  ruling, 2026-07-12), but names, companies, and email addresses are always swapped for
  neutral placeholders.
- Never ship the endpoint without the per-IP and global rate caps live in code.
- Never generate offers that fail the new-money test or "book a call"-only CTAs as the
  default — low-risk CTA framing is the law.
- Never add full cold-email drafts — offers only (stated default; user may veto).
- Never verify via the app's own success labels — CSV read-back, production curls, and
  browser-rendered proof only; a grep of deployed JS proves the deploy, not the feature.
- Never save user state or the submitted URL server-side beyond transient logs.
- Never use em-dashes in offer copy or UI text; plain English, zero outbound jargon.
- Never exceed a retry cap, the 4-round tester cap, or the 400-call ledger — cap-hit =
  FAILED with the gap, never "done".
