# RUN-LOG — lilly-tam-recall-lab · 2026-07-13 · Training Mode OFF

## Credit ledger (running)
| # | Provider | Call | Credits | Cum P | Cum A |
|---|---|---|---|---|---|
| 1 | Prospeo | B1 shape S1 subtypes:[SaaS]+b2b+sub US 11-200 (4,711) | 1 | 1 | 0 |
| 2 | Prospeo | B1 shape S2 subtypes:[SaaS] alone US 11-200 (29,804) — ANCHOR ✓ | 1 | 2 | 0 |
| 3 | Prospeo | B2 shape S1 industry:[Mktg,Adv] US+UK 11-200 (28,345) — ANCHOR ✓ | 1 | 3 | 0 |
| 4 | Prospeo | B2 shape S2 industry ∩ subtypes:[Agency] (13,513) | 1 | 4 | 0 |
| 5 | Prospeo | B2 shape S3 subtypes:[Agency] alone US+UK (57,415) | 1 | 5 | 0 |

## Step 1 — anchors
- B2B SaaS anchor: subtypes:["SaaS"] US 11-200 → total_count 29,804 (2026-07-13, same-day, zero drift). PASS (±25% window 22,353–37,255).
- Marketing agencies anchor: industry-alone → 28,345. PASS.

## Per-brief shape log

### Inline-scored (orchestrator, pre-fanout) — Prospeo side
| Brief | Shape | Pool | Prec | Verdict |
|---|---|---|---|---|
| B1 S1 subtypes[SaaS]+b2b+sub US | tight | 4,711 | 92% | tighter-comp |
| B1 S2 subtypes[SaaS] US | **CHOSEN** | 29,804 | 88% | PASS |
| B1 S3 subtypes[SaaS,Platform] US | looser | 33,098 | 68% | REJECTED ✓comparison |
| B2 S1 industry[Mktg,Adv] US+UK | **CHOSEN** | 28,345 | 76% | PASS |
| B2 S2 industry∩Agency | tighter-comp | 13,513 | 92% | PASS |
| B2 S3 subtypes[Agency] US+UK | looser | 57,415 | scoring in fanout | — |
| B3 S1 industry[SW Dev] Europe | looser | 23,039 | 8% | REJECTED ✓comparison |
| B3 S2 industry[SWDev,IT]+self-ID kw Europe | **CHOSEN** | 4,009 | 76% | PASS |
| B4 S1 subtypes[E-commerce] US | — | 23,522 | 92% | PASS |
| B4 S2 +Retail | — | 54,791 | 88% | PASS |
| B4 S3 +Marketplace | — | 56,950 | 80% | PASS |
| B4 S4 +Food&Beverage | candidate | 60,769 | scoring in fanout | — |
| B5 S1 subtypes[Construction] UK | **CHOSEN** | 4,168 | 76% | PASS |
| B5 S2 industry[Construction] UK | looser | 11,736 | 60% | REJECTED ✓comparison |
| B6 S1 industry[IT Services] UK | looser | 5,761 | ~38% | REJECTED ✓comparison |
| B6 S2 industry+MSP kw UK | **CHOSEN** | 1,054 | 80% | PASS |
| B6 S3 wider kw basket UK | — | 1,036 | scoring in fanout (pool SHRANK — kw reshuffle) | — |
| B7 S1 subtypes[Logistics] DE+NL | looser | 3,304 | 28% | REJECTED ✓comparison |
| B7 S2 (BUGGED nesting — discarded; corrected shape re-fired in fanout) | — | 2,631 | VOID | — |
| B8 S1 industry[Staffing] AU 11-100 | **CHOSEN** | 834 | 96% | PASS · proven-loosest (sole on-brief enum; +HR Services rung = entity-type change) |
| B9 S1 industry[Accounting] CA 11-100 | **CHOSEN** | 848 | 88% | PASS · proven-loosest (sole on-brief enum) |
| B21 S1 subtypes[SaaS] UK | tighter | 6,691 | 92% | PASS |
| B21 S2 subtypes[SaaS,Platform] UK | **CHOSEN** | 7,492 | 76% | PASS |
| B21 S3 +Marketplace UK | looser | 8,143 | 56% | REJECTED ✓comparison |

Prospeo credits through batch 4: **33** (5 anchors/session + 5 + 9 + 11 + 3). Fanout adds ≤ ~60 more (probes+followups+baselines).
Law observed already: **the [SaaS,Platform] rung passes in UK (76%) but fails in US (68%)** — rung viability is geo-dependent; always score the rung, never assume.

## FINAL LEDGER (2026-07-13, run complete)
- **Prospeo: ≈88 / 5,000** — 37 orchestrator pages (incl. 2 free INVALID_FILTERS not counted) + 33 workflow niche probes + 6 follow-ups + 10 baselines + 2 final iterations (b25_S3, b26_S3)
- **AI Ark: ≈860 / 5,000** — ~740 across 27 workflow gate agents (size 10-15, ≤2 calls each) + 120 inline (b03/b06 retries, b11/b14/b22 finals, incl. 45 cr lost to SSE-parse error — 3 calls billed but saved empty; corrected raw-JSON parse documented)
- Zero email/contact-enrichment calls. Zero lookalike calls. No shape pulled >25 rows. No full-list extraction.
- Fanout: workflow wf_f1e6839e-4b5 — 59 agents, 0 errors, 33 min. Per-agent returns in the workflow journal.
- Hand-re-score verification: b04_S4 80%=80% MATCH · ark_b30 93.3%=93.3% MATCH · b24_S1 88% fail-list confirmed · b02_S3 4% fail-list confirmed · b27_S1 frame-sensitive, 76% confirmed under brief's OR-wording.
