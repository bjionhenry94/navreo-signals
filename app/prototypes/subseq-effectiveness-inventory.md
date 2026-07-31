# Subsequence Effectiveness — baseline map (Step 1)

Re-verified against `app/deliverability.html` on 2026-07-29. Live matches the recon; no drift.

## Where the card goes
- Lane 5 `#lane-interested` (HTML ~496–517), scoped under `.ah`.
- Grid today: line **123** `.ah .c23{grid-template-columns:2fr 3fr}` (2 columns).
- Third column = new `<div class="acard">` appended after the "How fast we answer" card
  (~line 515), and the grid rebalanced to 3 tracks (`2fr 3fr 3fr`, or a new `c233`).
- `c23` is already in the ≤980px stack rule (~line 229) → mobile stacking is free if reused.

## The two siblings — NOT touched
- **Left · "Who's replying"** — `.brows`/`.brow` bars (grid `118px 1fr 42px`), `.fill`/`.fill.orange`,
  a `#who-size` subline, a `.take` `→` footer. Fed by `p.buckets` / `p.sizes` / `p.named`.
- **Middle · "How fast we answer"** — `.bignum` (34px; `.bignum.warn` → `--amber`), `.subline`,
  `.take`. Fed by `p.speed{ n, median_mins, under15_share }`.
- Both painted by `renderWho()` from one fetch `GET /api/who-replies?client=&days=`.

## Card grammar to mirror (from navreo.css + .ah scope)
`.acard` flex column gap 12 · `.card-kick` 11px/600/uppercase `--ink-3` · metric `.bignum`
· `.subline` 12.5px `--ink-3` · `.take` (`→` `.arr` `--brown-400`, self-pinned bottom via
`margin-top:auto`). Flat card: 1px `--line`, no shadow. One orange per screen (`--orange #FF4D00`).

## Benchmarks (confirmed with Bjion 2026-07-29)
- **POSITIVE**-reply rate **≥ 12.5%**  ·  Book-call rate **≥ 5%**. Under either → follow-up copy problem.
  (Positive = `positive_reply_count`, sent-basis. Corrected mid-run from "reply rate 12%".)
- Colour = severity: `--green #2E7D5B` ≥ target · `--amber #8F6600` just under · `--red #C2371F` well under.

**Done-rule met:** grid line, sibling grammar, wiring, and benchmarks confirmed live; left/middle unchanged.
