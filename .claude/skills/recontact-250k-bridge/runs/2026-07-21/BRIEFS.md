# Recontact 250k Bridge — Campaign Briefs
_Run 2026-07-21. Navreo-own campaigns only (31 client campaigns excluded: Byteplus, PushGroup, Olivia Duncan, WantMoreLeads, Arnic, DiscoLike). Gate: title-missing leads kept on campaign-name trust; title-present must be sales-leader/CEO/owner; known banned-geo dropped._

## The gap
- Target next month **250,000**; already committed (in-flight in 123 active campaigns) **158,355**; **gap 91,645**.
- **Found 161,853 net-new recontact prospects = 177% of the gap** (full coverage + overflow).

## Confidence
- Role: 25,254 title-confirmed sales-leaders/CEOs; 136,599 campaign-inferred (title missing, trusted to the list's targeting).
- Geo: 32,016 confirmed allowed-country; 129,837 country-unknown (kept; South America / Southern Asia / Africa dropped where known).
- Net-new: zero overlap with active campaigns, last-30-day sends, or suppressions (600-sample check passed).

## Build-time gates
1. **Verify emails** at upload via `lilly-email-verification` (verified at original send, non-bounced; no fresh signal on file). Drop fails.
2. **Geo** for the country-unknown share: confirm at enrichment for the literal 100% guarantee.

## Briefs (largest first)

### A. SaaS & tech sales leaders / CEOs — 84,920 people
- 12,284 title-confirmed, 72,636 campaign-inferred; 14,958 geo-confirmed.
- Segments: SaaS Sales Leaders/CEOs (45,493), Other Navreo verticals (28,835), CEOs (10,592)
- Offer: Free training/playbook for SaaS & tech sales leaders (defined outcome: "book N qualified demos/month, done-for-you"). Service magnet, never an audit.

### B. Industry verticals (wholesale/distribution/mfg/export) — 30,218 people
- 407 title-confirmed, 29,811 campaign-inferred; 9,283 geo-confirmed.
- Segments: Vertical (industry) (30,218)
- Offer: Free vertical outbound playbook for owners/MDs of wholesale/distribution/manufacturing/export firms. Service magnet, never an audit.

### C. Agencies (SEO/GEO + recruitment) — 23,463 people
- 7,459 title-confirmed, 16,004 campaign-inferred; 2,459 geo-confirmed.
- Segments: Recruitment (13,676), SEO/GEO Agencies (9,787)
- Offer: Free client-acquisition training for agency & recruitment owners ("land N retainer clients/month"). Service magnet, never an audit.

### D. General B2B sales leaders — 21,869 people
- 3,722 title-confirmed, 18,147 campaign-inferred; 4,274 geo-confirmed.
- Segments: Other Navreo (8,684), Other Sales Leaders (6,444), Catch-All Sales Leaders (3,427), Sales Worldwide 20-200 (3,314)
- Offer: Free training for B2B sales leaders ("N meetings/month without more headcount"). Service magnet, never an audit.

### E. Warm followers (Clay/SalesLoft/Instantly) — 1,383 people
- 1,382 title-confirmed, 1 campaign-inferred; 1,042 geo-confirmed.
- Segments: Followers (1,383)
- Offer: Warm re-intro + free resource for people who already followed Navreo. Service magnet, never an audit.

## Volume
Need 91,645 to hit 250k; pool holds 161,853. Briefs A (84,920) + B (30,218) alone exceed the gap — run largest/cleanest first, keep the rest as overflow.

## Build chain per brief
`lilly-recontact` → `lilly-copywriter` (lead-magnet email, no em-dashes) → `lilly-email-verification` → `lilly-upload-gate`. Nothing uploads from this run.

## Files
- `recontact_pool.csv` — all prospects (email, segment, title, country, role_basis, company_domain).
- `own_vs_client_ids.json` — 270 Navreo-own vs 31 client campaign IDs.