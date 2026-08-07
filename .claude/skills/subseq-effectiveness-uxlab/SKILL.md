---
name: subseq-effectiveness-uxlab
description: Static orchestration skill that prototypes the "How effective are our automated follow-ups?" card — the new third column, wedged in on the right of the "Who actually replies?" section (lane 5) on the analytics page (navreo-signals.onrender.com/app/deliverability.html, beside "Who's replying" and "How fast we answer"). Builds 3 minimal, highly-visual, self-contained prototypes in the Navreo design system under app/prototypes/, each tracking subsequence performance against two benchmarks — POSITIVE-reply rate ≥ 12.5% and book-call rate ≥ 5% — with plain 16-year-old language and colour-as-severity. Reconciles the widget's definitions against real collated subsequence data for one client, then a 5-persona panel of non-technical founders and sales leaders scores every prototype until each earns 9/10+ on actionable insights, easy to digest, AND beauty. Delivers a gallery + scorecard for Bjion to pick a winner; never auto-ships. Loop Training Mode baked in, default ON. Trigger: "run the follow-up effectiveness lab", "prototype the subsequence widget", "subsequence effectiveness prototypes", "how effective are our follow-ups card", "/subseq-effectiveness-uxlab".
---

# Subsequence Effectiveness — UX Lab

One glance at the right of "Who actually replies?" tells a non-technical founder whether
our automated follow-ups (subsequences) are pulling their weight — or leaking meetings —
so they know to fix the copy. Static loop: fixed steps, checkable done-rules, Loop
Training Mode controls the pauses.

## ⚙️ LOOP TRAINING MODE → **ON** (default)

Flip it by editing this one line (a runtime "training off" / "training on" in the
invoking message overrides it for that run only):

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at every step: announce what the step is about to do, run it, show the result,
  then **WAIT for Bjion's explicit approval** before moving to the next step.
- Before running a step, **check its done-rule first. If it already passes, skip it** —
  say so and move on.
- Only (re-)run steps that **fail** their done-rule.
- Retry cap applies (below) — never loop a step forever.
- "go / yes / continue" advances; anything else is revision feedback — apply it and
  re-run the step (Bjion-requested re-runs don't count against the cap).

**When OFF**
- Run all steps autonomously, no pauses.
- Keep **every** done-rule check, every skip-if-passing, and the **same** retry cap.
  Report at the end, not between steps.

**Retry cap (both modes):** any single step runs **max 3** times against its done-rule,
and only the failing unit re-runs (a failing prototype, not all three; a failing panel
round, not the whole panel). On cap-hit, record **FAILED** with the honest reason, keep
going where possible, and surface it in the final report. **Never inflate a score or
fake a green to pass. Never silently exceed the cap.**

## THE GOAL

A dead-simple, highly visual card that answers one question — *are our automated
follow-ups working?* — for a non-technical founder in one glance, in words a 16-year-old
would use. It shows two numbers against two benchmarks (**positive replies ≥ 12.5%**, **booked
calls ≥ 5%**), colours them by severity, and says in one line what to do next so they
book more meetings. **If it needs explaining, it's already too complicated — redesign
it, don't caption it.**

## HARD INVARIANTS (all three prototypes)

- **The card is the third column of lane 5**, wedged in on the **right**: left stays
  "Who's replying", middle stays "How fast we answer", right is the new card. Prototypes
  render all three side by side so the fit is real — but only the right card changes.
- **Two benchmarks, both shown:** POSITIVE-reply rate **≥ 12.5%**, book-call rate **≥ 5%**. Under
  either → the card must make the shortfall obvious (that's the whole point: a bad
  subsequence copy shows up here).
- **Colour IS severity** (Navreo semantic trio, not decoration): `--green #2E7D5B` at/above
  target, `--amber #8F6600` just under, `--red #C2371F` well under. No fourth colour.
- Navreo design system exactly: `app/navreo.css` tokens, Acid Grotesk display + DM Sans
  body, `--radius 12`, flat cards (1px `--line` border, no shadow), **one orange element
  per screen** (`--orange #FF4D00` — reserve it; the take-arrow `→` is `--brown-400`, not
  orange). Match the sibling card grammar: `.card-kick` eyebrow · metric · `.subline` ·
  `.take`(`→` self-pinned to the bottom via `margin-top:auto`).
- **Minimal.** No explainer sentences, no legend doing the design's job, no tooltip
  crutches. One `→` recommendation line max. Plain English — "replies" / "booked calls",
  never "engagement" / "conversion".
- Self-contained prototype files: inline mock data, **zero API calls, zero production
  writes**. Show both a below-benchmark ("something's wrong with the copy") and a healthy
  state so the colour system is visible.

## FIXED CONTEXT (baked from recon 2026-07-29 — re-verify live in Step 1, live wins)

Source of truth is `~/navreo-signals` (push to `main` auto-deploys on Render; the iCloud
copy is deprecated — never edit it).

**Where the card goes** — `app/deliverability.html`, lane 5 `#lane-interested` (HTML
~496–517), scoped under `.ah`:
- Grid today: line **123** `.ah .c23{grid-template-columns:2fr 3fr}` (2 cols). Third
  column = change to `2fr 3fr 3fr` (or new class). `c23` is already in the ≤980px stack
  rule (line ~229) so mobile stacking is free if you reuse it.
- Add the third `<div class="acard">…</div>` as a child of `<div class="cards c23">`,
  after the "How fast we answer" card (~line 515).
- Card grammar to mirror (`.acard` flex column, gap 12): `.card-kick` (11px 600 uppercase
  `--ink-3`) · big metric `.bignum` (34px; `.bignum.warn` → `--amber`) · `.subline`
  (12.5px `--ink-3`) · `.take` (`→` `.arr` `--brown-400`, pinned bottom). Bars =
  `.brows`/`.brow` (grid `118px 1fr 42px`) with `.fill` (ink) / `.fill.orange`.

**How it gets fed (for the graduation checklist, NOT for the prototypes)** — the left +
middle cards are painted by `renderWho()` from one fetch: `GET /api/who-replies?client=
<state.client>&days=<state.range>` → payload `{ named, buckets, sizes, n, speed:{ n,
median_mins, under15_share } }`. The clean wiring for the new card is to **extend that
payload with a `subseq` block** (e.g. `{ enrolled, replied, reply_rate, booked, book_rate }`,
raw counts + derived %) and render it in `renderWho()` — same `client|range` key, one
fetch, no new round-trip.

**The subsequence data truth (this is why Step 3 exists)** — a subsequence *is its own
Smartlead campaign* whose `parent_campaign_id` points at the parent. It is **deliberately
excluded** from `campaign_scorecard` and from `/api/client-windows`, so **no per-client
subsequence rate exists in any store today** — it must be collated live:
1. One cached `GET /campaigns/` → the `{sub_id: parent_id}` map (`_parent_map()`,
   `app/setter.py:2077`, 10-min cache). This is the only source of the sub→parent link
   (the Supabase `campaigns` mirror has no `parent_campaign_id`).
2. Map each parent's name → client with `_client_win_label(workspace, parent_name)`
   (`app/server.py:13877`); keep the subsequence ids whose parent resolves to the target
   client. **Never label a subsequence by its own name** — subs are named generically
   ("Interested Reply", "Meeting Request") and would all fall into `__unassigned`.
3. Per selected sub id, one `GET /campaigns/{id}/analytics` (LIFETIME — do NOT use
   `analytics-by-date`, which 400s on any range > 30 days). Read `sent_count`,
   `positive_reply_count`, `total_count` (enrolled leads). POSITIVE-reply rate =
   `100 * Σpositive_reply_count / Σsent_count` — **sent-basis** (of those actually emailed:
   isolates the copy, not dragged down by unsent setter drafts). NOT all-`reply_count`, NOT
   the 30d-rolling fleet basis.
4. Booked calls = `_reply_archive_meetings(sub_ids)` (`app/server.py:7241`): distinct
   `(campaign_id, email)` with `category ∈ {"Call Booked","Meeting Request"}`. Book-call
   rate = `100 * Σbooked / Σsent_count` (same sent-basis). Benchmarks: positive-reply ≥ 12.5%,
   book-call ≥ 5%. (Reconciled live 2026-07-29 — see `subseq-effectiveness-reconcile.md`.)

**Load-bearing caveat:** the replies/meetings archive is **`workspace=eq.navreo` only**
(`app/server.py:7249`). So per-client subsequence book-call rate is trustworthy for
shared-navreo clients (Amplifyy, Arnic, Qwintiq, ThunderBird, Navreo); for a *connected
client workspace* the archive may not hold those replies. State this caveat wherever the
number ships. And note the definitional nuance: "Meeting Request" is really
"asked-for-a-meeting", "Call Booked" is confirmed — the metric is precisely
"requested-or-booked-a-meeting rate".

**Three prototype concepts (fixed — build these three, one shared fixture):**
- **P1 · Benchmark meters** — two labelled tracks (Positive replies, Booked calls); each bar
  fills to actual %, a **labelled** target tick + a shaded shortfall band; a plain-word chip
  (On target / Just under / Well under) on each. You *see* it fall short.
- **P2 · One verdict, one proof** — a single big number in the "7 h 51 m" family: booked rate
  as the hero (coloured + the severity chip **on the big number**), positive-reply rate as a
  clearly-chipped proof line beneath, one `→`.
- **P3 · Gap-to-target scorecard** — two rows, each: metric, big %, "target X%", and a
  **plain-word severity chip** (On target / Just under / Well under — never "−N pts", which
  fails the 16-yo word test); the `→` names the weak link AND the exact follow-up to rewrite.
- House-panel note (2026-07-29 run): the plain-word chip beats a bar-with-tick (founders won't
  "decode a picture") and beats one-big-number (it buries the second metric). P3 won 5/5.

## STEPS

### Step 1 — Baseline map (re-verify, don't trust the recon blindly)
Open `app/deliverability.html` lane 5; confirm the grid line, the two sibling cards, and
the `renderWho()` / `/api/who-replies` wiring still match FIXED CONTEXT. Confirm the two
benchmarks are still **12.5% positive-reply / 5% book-call** (ask Bjion if the numbers have moved).
Read the `dataviz` and `navreo-design-system` skills before any markup.
**Done-rule:** a ≤15-line note in `app/prototypes/subseq-effectiveness-inventory.md`
listing the exact grid line, the sibling-card grammar, the benchmarks, and any drift from
FIXED CONTEXT. Nothing about the left/middle cards changes.

### Step 2 — Build P1–P3 (three distinct concepts, one shared mock fixture)
Write `app/prototypes/subseq-effectiveness-p1.html … -p3.html`, each self-contained, each
rendering the **full lane-5 row** (real left + middle cards + the variant right card) so
the fit is real. One shared fixture with a below-benchmark client (e.g. 1,240 in
follow-ups · 9% reply · 3% booked) **and** a healthy toggle (14% · 6%) so both colour
states show. Zero API calls. No two prototypes share a layout skeleton.
**Done-rule (per prototype):** loads clean, **zero console + zero network errors**, both
benchmark states render with correct green/amber/red, the third card sits as a true 3rd
column beside the untouched siblings, no explainer paragraph, `→` line present. Screenshot
each with headless Chrome into `app/prototypes/subseq-effectiveness-pN.png`.

### Step 3 — Reconcile the definition against REAL data (the verification)
Read-only. Pick one shared-navreo client. Collate their subsequence totals with the
FIXED-CONTEXT recipe: `_parent_map()` → sub→parent→client → `GET /campaigns/{id}/analytics`
per sub id (Σsent, Σpositive_reply_count) → `_reply_archive_meetings(sub_ids)` (booked).
Compute positive-reply rate and book-call rate (sent-basis). Confirm the widget's definitions
and benchmarks match what the data can actually produce (same numerators/denominators, same
category set). **No writes, no sends, never touch a real prospect.**
**Done-rule:** `subseq-effectiveness-reconcile.md` shows the collated totals (enrolled, sent,
positive replies, positive-reply%, booked, book%) for one client, states they reconcile with the
widget's definitions (or names the exact gap), and records the navreo-workspace caveat. If the
number can't be computed for the chosen client, say so and pick a client where it can.

### Step 4 — Founder panel (5 personas, cold-read)
Spawn **5 independent subagents**, no pitch, no design notes — **3 non-technical founders
+ 2 sales leaders**:
- *Maya* — agency founder, non-technical, skims. *Jack* — 55, owner, distrusts anything
  fiddly. *Priya* — first-time SaaS founder, hates dashboards. *Tom* — sales leader,
  decides in 5 seconds. *Sofia* — sales director, 30 seconds between meetings.
Each scores **every** prototype **1–10** on **(A) actionable insights · (D) easy to digest
· (B) beauty of design**, and returns the **single worst moment / top fix** verbatim.
**16-year-old word test:** if a judge had to ask what anything meant, cap that prototype's
*easy-to-digest* at ≤6.
**Done-rule:** a 3×5 grid written to `app/prototypes/subseq-effectiveness-scorecard.md`
(Judge × Prototype, each cell `A/D/B`, an **Avg** row, a **Favourite** column, then the
consensus objections per prototype).

### Step 5 — Fix loop
Any prototype **< 9** on any axis from any panelist → fix its worst moments only, re-panel
**that prototype** with fresh judge contexts. **Cap = 3 panel rounds.**
**Done-rule:** all three at **9/10+ on all three axes from all five panelists**
("9+ = I'd ship this as-is"), scorecard updated per round. On cap-hit: **HALT, record
FAILED-BAR with the honest final scores** — never inflate to pass.

### Step 6 — Deliver / hand-off (never auto-ship)
Assemble `app/prototypes/subseq-effectiveness-index.html` (gallery linking all three +
their PNGs). Deliver **in chat**: the scorecard table, a one-line pitch per prototype, the
panel's favourite, and a ≤10-item **graduation checklist** for wiring the winner into
`deliverability.html` (the line-123 grid change, the third `.acard`, the `/api/who-replies`
`subseq` payload extension + `renderWho()` render, the 12.5%/5% benchmarks, colour-as-
severity, the navreo-workspace caveat). **Bjion picks the winner. Nothing merges to
production or deploys inside this loop** — shipping is a separate brief.
**Done-rule:** gallery + scorecard + pitches + favourite + graduation checklist delivered;
`git status` shows only new `app/prototypes/subseq-effectiveness-*` files, nothing staged,
nothing pushed.

## DONE-RULE (whole loop)
Three genuinely-distinct, minimal prototypes of the follow-up-effectiveness card exist
under `app/prototypes/`, each passing its Step-2 done-rule; the metric is reconciled
against real collated subsequence data (Step 3); every prototype scores 9/10+ on all three
axes from all five panelists (or a FAILED-BAR is recorded honestly); and a gallery +
scorecard + graduation checklist are delivered for Bjion to pick — with nothing shipped to
production.

## HARD DON'TS
- Never touch the left ("Who's replying") or middle ("How fast we answer") cards — only
  add the third column.
- Never call a production API or write production data from a prototype file; Step 3's
  reconciliation is **read-only** and must never send to, or modify, a real prospect.
- Never label a subsequence by its own name (always resolve parent → client), and never
  ship the book-call number without the navreo-workspace caveat.
- Never add an explainer paragraph, a legend, a tooltip crutch, a chart library, a fourth
  colour, or a second orange element. No emoji in the card.
- Never simulate the panel by driving a browser — the judges are subagents.
- Never exceed the retry cap, never inflate a score, never report done while any done-rule
  fails, and never merge/deploy inside this loop. Never edit the iCloud copy.

## FINAL REPORT (format)
```
SUBSEQ EFFECTIVENESS LAB — <date>
Mode: TRAINING <ON/OFF>   Rounds used: <n>/3
Reconcile: <client> — enrolled <n> · reply <x%> · booked <y%> · caveat noted <yes>
Scores (final round, A/D/B):
  P1 Benchmark meters       <a/d/b>  avg <n>
  P2 One verdict, one proof <a/d/b>  avg <n>
  P3 Gap-to-target          <a/d/b>  avg <n>
Bar met (≥9 all axes, all 5): <P1/P2/P3 or FAILED-BAR: which & why>
Panel favourite: <Pn>  —  <one line>
Graduation checklist: app/prototypes/subseq-effectiveness-index.html
Shipped to production: NO (separate brief)
```
