# PANEL-SCORECARD — launch-ux-migration Step 7 (2026-07-26)

**Panel:** 5 simulated testers (independent agent personas, sources-pull-more-ship precedent):
- **Marcus** — Senior GTM Engineer (5 yrs, ex-Clay, API-native, click-averse)
- **Priya** — Junior GTM Engineer (8 months, needs everything spelled out, send-anxious)
- **Deena** — Senior Account Strategist (7 yrs, 12 clients, wants quotable numbers)
- **Tom** — Mid Account Strategist (3 yrs, the weekly top-up/variant-swap operator, cynical)
- **Sofia** — New Account Strategist (6 weeks, judges by "day two without asking anyone")

Every tester scored every scenario (10 × 5 = 50 scores per round), simplicity 1–10 + one-line
reason. Bar: **average ≥9, no tester below 8, no scenario below 8.** Max 4 rounds.

## Round 1 — FAIL (average 8.28)

| Scenario | Marcus | Priya | Deena | Tom | Sofia | Avg |
|---|---|---|---|---|---|---|
| S1 list build | 9 | 9 | 8 | 9 | 9 | 8.8 |
| S2 TAM map+draft | 8 | 5 | 9 | 9 | 6 | **7.4** |
| S3 top-up partial | 9 | 8 | 9 | 9 | 8 | 8.6 |
| S4 shell | 8 | 8 | 8 | 8 | 8 | 8.0 |
| S5 copy | 10 | 9 | 10 | 10 | 9 | 9.6 |
| S6 recontact | 8 | 6 | 9 | 8 | 7 | **7.6** |
| S7 variant swap | 7 | 6 | 9 | 8 | 8 | **7.6** |
| E1 multi-idea | 9 | 8 | 7 | 9 | 8 | 8.2 |
| E2 top-up full | 9 | 8 | 9 | 9 | 8 | 8.6 |
| E3 TAM decline | 10 | 7 | 10 | 10 | 7 | 8.8 |
| **Tester avg** | 8.7 | **7.2** | 8.8 | 8.9 | **7.8** | **8.28** |

**Under bar:** scenarios S2/S6/S7; testers Priya/Sofia. **Recurring critiques:**
1. Agency jargon in user-facing closings — "probe-confirmed, suppression-netted" (S2),
   "eligible after netting" (S6), shorthand "A/C" (S7), bare nouns "Sources"/"pool"
   (S3/E2), "run record" (E3).
2. S7 stops at paste-ready copy — the actual swap left to the user, unstated.
3. S6's predecessor auto-pause reads as a surprise to juniors; next step unnamed.
4. S2 doesn't say WHERE the pool/targeting saves; E1's door line carries nothing quotable.
5. S4 drops the user on Overview without saying what to do there.

## Round 1 → 2 delta (what changed)

- **lilly-tam closing rule:** plain-English numbers line mandated ("decision makers we can
  actually reach — removed everyone we've already contacted or who opted out"); draft offer
  names the campaign's Sources tab; decline path replaces "run record" with "ask me to pull
  up the [segment] TAM from earlier".
- **lilly-recontact:** plain-English closing template (exclusions spelled out), predecessor
  pause framed as agreed-at-step-3.5, single next step named ("want me to write the copy?").
- **lilly-optimiser variant-swap:** now OFFERS to save the swap into Smartlead (with the
  honest stats-reset warning + UI-edit alternative); variant names written in full.
- **lilly-upload-gate closing:** "people saved for this campaign" instead of "pool"; names
  "the Sources tab on that campaign's page"; explicit pool-emptied variant.
- **lilly-strategy single-view door:** concrete about what's inside + time ("about 5
  minutes") + safety; post-upload closing says what to do on Overview; multi-idea door may
  carry the idea COUNT (never the ideas).

## Round 2 — **PASS (average 9.12)**

| Scenario | Marcus | Priya | Deena | Tom | Sofia | Avg | Δ vs R1 |
|---|---|---|---|---|---|---|---|
| S1 list build | 9 | 10 | 8 | 9 | 9 | 9.0 | +0.2 |
| S2 TAM map+draft | 9 | 8 | 9 | 9 | 8 | 8.6 | +1.2 |
| S3 top-up partial | 10 | 9 | 10 | 10 | 9 | 9.6 | +1.0 |
| S4 shell | 8 | 9 | 8 | 9 | 8 | 8.4 | +0.4 |
| S5 copy | 10 | 9 | 10 | 10 | 9 | 9.6 | 0.0 |
| S6 recontact | 9 | 9 | 10 | 9 | 9 | 9.2 | +1.6 |
| S7 variant swap | 9 | 8 | 10 | 10 | 9 | 9.2 | +1.6 |
| E1 multi-idea | 9 | 9 | 8 | 9 | 9 | 8.8 | +0.6 |
| E2 top-up full | 9 | 9 | 10 | 9 | 9 | 9.2 | +0.6 |
| E3 TAM decline | 10 | 9 | 10 | 10 | 9 | 9.6 | +0.8 |
| **Tester avg** | **9.2** | **8.9** | **9.3** | **9.4** | **8.8** | **9.12** | +0.84 |

**Bar check:** average 9.12 ≥ 9 ✅ · lowest tester 8.8 (Sofia) ≥ 8 ✅ · lowest scenario 8.4
(S4) ≥ 8 ✅ · every tester ran every scenario (50/50 scores both rounds) ✅. **Rounds used:
2 of 4.**

**Biggest wins:** S7's finish-the-job offer with the stats-reset warning (Tom: "the single
biggest win of the round"); S6's plain-English exclusion list ("replaces trust with
verification"); S3 called "the gold standard for my weekly job".

**Residual items (noted for Bjion, all above bar):**
- S2 opened with unexplained "TAM" (Priya/Sofia) → POLISHED post-panel: closing line now
  leads with "Market size for [segment]:" (lilly-tam closing rule).
- S4's two-surface reality (review in the tool, launch in Smartlead) is inherent to where
  launch lives — testers scored it honest-but-split (8.4). A same-page launch affordance
  would be a tool-side feature request, not a messaging fix.
- S7's "audit-shaped opener" shorthand (Priya) — copy-explanation phrasing, cosmetic.
- E1/S1: the artifact hop itself is the floor of the design (chat stays a door — Bjion
  ruling); testers priced it at 8-9, not below bar.
