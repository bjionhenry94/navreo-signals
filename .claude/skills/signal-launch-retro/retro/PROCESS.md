# The one smooth path: "run this signal" → live campaign

Spine = `/smooth-campaign-launch` (exists). This spec adds the front-loaded gates (C3),
the single-writer rule (C2) and the honesty rules (C5, C7) around it. The user makes
**exactly 3 decisions**; everything else is automation or a hard stop.

## The journey

| Moment | What the user sees | Who does it | Exists today? |
|---|---|---|---|
| 0 · One sentence | They type: "launch a campaign for [audience/signal]" | user | — |
| 1 · **DECISION 1 — the Card** | One card: audience in plain words, SIGNAL or FIXED LIST, size+title tiers **pre-filled from the standing defaults** (15 countries, 5–200 staff, B2B niches, role set, CEO/sales ladder, company AND person in-region), **plus one rendered example email** (the copy's best variant, opener filled for a realistic company — tap to expand). They say yes or edit; reading the actual email happens here, not after paying. Edits update the saved defaults so next time asks nothing. | launcher step 1 + `clients/navreo.json` defaults | launcher yes · defaults block = build item C3a |
| 2 · Preflight (automatic stop, not a decision) | One line: "Senders: N mailboxes ready · Video/asset: found/missing." If either fails, the run STOPS here — before any credit — with what's missing and who owns it. | new preflight check | build item C3b |
| 3 · **DECISION 2 — the Price** | One line with cash next to credits: "310 credits (≈ £22) buys about 270 people you can email. 26,100 left after." Approve or resize. Not a credit moves before this. | launcher step 3 (hard gate) | yes · cash figure = tiny addition |
| 4 · The machinery (ticking, not silent) | One plain line per stage ("Finding people… 287 found · Checking emails… 270 good"): probe → pull → bank to Lists tool → dedupe/clean (found → sendable, every subtraction named) → verify emails → build DRAFTED campaign from the copy source → load with test-lead-first → upload gate → **auto-register in the tool** (idempotent by campaign id). Every number probe-confirmed; any claim without a measurement is labelled a guess (C7). | launcher steps 2,4–8 + guards | yes (guards shipped 27 Jul) |
| 5 · **DECISION 3 — the Handover** | Opens with "**Nothing has been sent.** It sends only when you press Start." Then: campaign links that open even though it's a Draft, what was spent, what refreshes vs burns down, ONE next action: "review it, then press Start in Smartlead." | launcher step 9 | yes · draft deep-link visibility = build item C5 |

## Standing rules around the journey

- **One writer.** One session runs a launch at a time; the board, drafts and sources
  tables are never whole-list written by chat. Second sessions read. (C2 — agreement now,
  server enforcement later.)
- **No prototype ambiguity.** Any surface not wired end-to-end says "PROTOTYPE — nothing
  is created" on its final button and never eats an edit. (C5.)
- **Contracts stay fresh.** Weekly smoke probes of every call shape the launcher uses;
  new filters get a differential check; the engine hard-fails absurd counts. (C4.)

## Mock walkthrough (paper, zero credits)

"Launch a campaign for UK+US design studios hiring their first marketer" → Card appears
pre-filled (SIGNAL, defaults applied), user taps yes → preflight: "6 senders ready, video
linked" → "Price: 310 credits ≈ 270 sendable people, 26,100 left after" — yes → 4 minutes
of silent machinery → Handover: two links, 287 found → 270 sendable table, "press Start in
Smartlead when ready." Three decisions, zero jargon, zero surprises. ✔ completes on paper.

## Build items (all trace to CHANGES.md)

1. C3a — standing `targeting_defaults` block in `clients/navreo.json`, read by the Card.
2. C3b — preflight check (mailboxes attached? asset URL live?) before the Price gate.
3. C5 — prototype banner + draft deep-link visibility (tool-side, needs approval).
4. C4 — contract smoke-test cron + engine >10M hard-fail.
