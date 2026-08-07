# Campaign Strategy Shortlist — Northwind Cloud (MOCK)
**Date:** 2026-05-31
**Briefed by:** Bjion
**History snapshot:** 1 active campaign, 1 dead angle (the "cloud bill audit" magnet, killed at 16K sent)

> **THIS IS A MOCK.** Northwind Cloud is a fictional client invented to show what `/lilly-strategy` produces. **No API probes were fired** — every Companies / DM count below is an illustrative LLM estimate, NOT a probe-confirmed number. On a real run, the `Companies` column would carry a `/search-company` `total_count` and the table would be hyperlinked to verified LinkedIn slugs.

**Who they are (1-line):** Done-for-you FinOps — Northwind cuts AWS bills 20-40% for cloud-heavy B2B SaaS, no re-architecture.
**Ideal customer:** Engineering / platform / finance leaders (CTO, VP Eng, Head of Platform, FinOps Lead) at B2B SaaS & data/AI companies, 51-500 staff, English-first geos + DE/NL.
**Decision-maker multiplier:** N = 4 titles (CTO, VP Engineering, Head of Platform, FinOps Lead) → **DM TAM = Companies × 4** on every row.

---

## Recommended campaign menu

| # | Campaign idea | Mechanism | Lead magnet | Companies | × titles (N) | **Decision-makers (DM TAM)** | Fit | Nov | Intent | Total /20 | Build chain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Recently-funded SaaS (Series B+, last 6 months)** | News / funding intent | Free AWS cost teardown (DFY) | ~340 | ×4 | **~1,360** | 5 | 4 | 5 | **17** | `/lilly-icebreaker-news-search` |
| 2 | **Companies actively hiring a FinOps / Cloud-Cost Engineer** | Hiring signal | Cloud-waste benchmark report | ~120 / 30d | ×4 | **~480** | 5 | 5 | 5 | **17** | `/lilly-theirstack-setup` |
| 3 | **FinOps X 2026 + AWS re:Invent exhibitors** | Events | Reserved-instance / savings-plan audit | ~280 | ×4 | **~1,120** | 5 | 4 | 4 | **16** | manual + `/loom-research` |
| 4 | **Engagers of FinOps Foundation + cloud-cost thought-leaders** | LinkedIn engagement | "10 hidden AWS cost leaks" guide | ~600 engagers/mo | n/a* | **~600 / mo** | 4 | 4 | 4 | **15** | `/lilly-trigify-setup` |
| 5 | **AWS-heavy B2B SaaS, 51-500 staff, core geos** | Targeted list | Free FinOps maturity assessment | ~1,800 | ×4 | **~7,200** | 5 | 3 | 2 | **14** | `/lilly-tam-mapper` |
| 6 | **Followers of competitor pages (CloudZero, Vantage, Antimetal)** | LinkedIn followers | Cloud-waste benchmark report | ~140K raw | n/a* | **~140K raw / filter hard** | 3 | 4 | 3 | **14** | `/lilly-linkedin-page-finder` → `/lilly-company-followers` |
| 7 | **Lookalikes of Northwind's 5 best clients** | Lookalikes | Free AWS cost teardown (DFY) | ~450 | ×4 | **~1,800** | 5 | 3 | 2 | **13** | `/lilly-tam-mapper` (lookalike) |
| 8 | **Companies scaling Platform-Engineer headcount (broad)** | Hiring signal | FinOps maturity assessment | ~900 / 30d | ×4 | **~3,600** | 3 | 3 | 3 | **13** | `/lilly-theirstack-setup` |

\* For engagement (#4) and followers (#6) the **engager/follower IS the lead**, so the `× titles` multiplier does not apply — the headline number is the audience pool itself, not Companies × N.

**Reading the numbers:**
- **Decision-makers (DM TAM) is the headline number** — it's the sendable-lead count that sizes the campaign, so ideas are scored on it, not on company count.
- **DM TAM = Companies × 4** (4 target titles per company). The `× titles` column makes the maths transparent — same N on every row.
- DM TAM is a **target reach** (≈1 contact per title per company), NOT a guaranteed-findable count. Actual findable contacts are confirmed later, at the `lilly-decision-maker-finder` enrichment step (real-world findable rates for mid-market SaaS run lower than the target).
- **Total /20** = TAM-band + Fit + Novelty + Intent (each /5). Delivery-friction is the tiebreaker, not part of the score.
- **All figures here are illustrative (mock).** A real run replaces the `Companies` column with a live `/search-company` `total_count`.

---

## Recommended top 3 (where to start)

Ranked by **(Total score × ease-of-build)** — so a slightly lower-scoring idea that's pure-API can outrank a high-scoring one that needs manual scraping:

### 1. Companies actively hiring a FinOps / Cloud-Cost Engineer  *(idea #2)*
- **What it is:** Target SaaS companies with a live job posting for a FinOps, Cloud Cost, or Cloud Economist role. The posting itself is the buying signal — they've admitted, in public, that cloud spend is now a named problem they're staffing for.
- **Why it'll work:** This is the tightest signal-to-offer match on the menu. A company hiring for cloud cost is a company that will either build it slowly in-house or hand it to Northwind today. Highest novelty + highest intent on the board.
- **Lead magnet:** Cloud-waste benchmark report — "here's what your peers at your stage are wasting." Soft, data-led, no commitment.
- **Build chain on sign-off:** `/lilly-theirstack-setup` → `/lilly-decision-maker-finder` → `/lilly-email-verification` → `/lilly-bot`.
- **Approx. credit budget to launch:** ~5-10 credits (TheirStack preview is free; spend is in DM enrichment).

### 2. AWS-heavy B2B SaaS, 51-500 staff, core geos  *(idea #5)*
- **What it is:** The straight ideal-customer list — every B2B SaaS company in the size band and geos that runs heavily on AWS. The volume anchor.
- **Why it'll work:** Lower intent (it's a cold list), but it's the biggest, cheapest-to-build, always-on backbone campaign. Pure API, no manual glue. Every client needs one of these running underneath the sharper signal plays.
- **Lead magnet:** Free FinOps maturity assessment — a quick self-scored "how leaky is your cloud bill" framework.
- **Build chain on sign-off:** `/lilly-tam-mapper` → `/lilly-decision-maker-finder` → `/lilly-email-verification` → `/lilly-bot`.
- **Approx. credit budget to launch:** ~30-60 credits (multi-provider company pull + DM enrichment at this volume).

### 3. Recently-funded SaaS (Series B+, last 6 months)  *(idea #1)*
- **What it is:** Companies that just raised a Series B or later. Fresh capital = fresh burn = a CFO who has just started asking why the AWS bill is what it is.
- **Why it'll work:** Highest-intent signal on the menu. The funding event creates both budget and scrutiny at the same moment — exactly when a FinOps pitch lands.
- **Lead magnet:** Free AWS cost teardown (we do it for you) — fits the post-raise "show me where the money's going" mindset.
- **Build chain on sign-off:** `/lilly-icebreaker-news-search` (against a SaaS TAM list) → `/lilly-decision-maker-finder` → `/lilly-email-verification` → `/lilly-bot`.
- **Approx. credit budget to launch:** ~15-25 credits (news search + enrichment).

---

## Brainstormed but cut

| Angle | Mechanism | Why cut |
|---|---|---|
| All B2B SaaS regardless of cloud spend | Targeted list | Too broad — no cost-pain signal, would dilute the core list (#5) with companies that have no AWS problem to solve. |
| Followers of the official AWS company page | LinkedIn followers | Zero qualification — everyone in tech follows AWS. Score 9/20. |
| Companies hiring a CFO | Hiring signal | A CFO hire isn't a cloud-cost mandate. Weak signal-to-offer map; score 11/20. Revisit only if paired with a funding event. |
| Re-run the "cloud bill audit" magnet | (any) | **[re-pitch: previously killed at 16K sent]** — only worth retrying if the delivery angle changes (e.g. reframed as a benchmark, not an audit). Flagged per history. |

---

## Notes
- **Dead angle on file:** the "cloud bill audit" magnet was killed at 16K sent. It is *not* re-pitched silently anywhere above — it only appears in the cut list, flagged as a re-pitch with the condition for retrying it.
- **Engagement & followers rows (#4, #6)** size differently from the rest: the engager/follower is the lead, so there's no `Companies × N` step — the audience pool is the headline number, and it needs strict title-filtering at scrape time.
- **Hyperlinks:** on a real run every named client, competitor, and event would be hyperlinked to a verified LinkedIn slug / official URL. They're left as plain text here because the client is fictional and I won't fabricate links.

## What this skill did NOT do (by design)
- Did not fire any API probes (mock — no credits spent).
- Did not auto-build any campaign. On "approve idea #N", the next step is a per-idea hand-off brief for the named build skill — the user fires it manually so the credit-spend gate stays with them.
