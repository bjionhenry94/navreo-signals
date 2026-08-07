---
name: lilly-tam
description: "THE one skill for the entire prospect-mapping pipeline: brief → company TAM (recall-max, ≥70% accuracy) → decision-maker map (title-primary, ≥90% accuracy) → verified-email enrichment → hand-off to push/verify skills. REPLACES lilly-tam-mapper, lilly-prospeo-list-builder, lilly-ai-ark-list-builder, lilly-decision-maker-finder and lilly-decision-maker-finder-v2 (all archived 2026-07-14) — any reference to those names means this skill. Providers (waterfall, Bjion 2026-08-03): GetLeads FIRST, Prospeo SECOND — AI Ark is RETIRED (subscription ended; never call it). Filters/classifiers/self-ID keywords ONLY — every lookalike feature on every provider is banned; Ocean optional for company discovery via lilly-ocean-tam-builder, its people endpoints stay banned. Prospeo-sourced emails are ALWAYS ListMint-verified before delivery — no exceptions. Use for ANY of: 'map TAM', 'build the full TAM', 'find every company in [vertical]', 'how big is the market', 'expand the TAM', 'find more companies', 'find decision makers at [domains/vertical]', 'find [title] at [companies]', 'get me contacts/emails for these companies', 'who can we contact at', 'enrich these companies with DMs', or as the build engine underneath any signal/strategy skill that produces a company list. ROUTING (consolidated launch flow, Bjion 2026-07-26): a CAMPAIGN-intent list ask — 'build me a list of [niche]', 'build a prospect list' for a new campaign — routes to lilly-strategy Single-campaign mode (the single-view walkthrough), which drives this skill underneath; lilly-tam stays the direct entry only for raw TAM/market-size/DM/enrichment work. EVERY TAM-map run ends by offering to draft the campaign (never launches a UI at map time); on yes, the pool + targeting are saved to the tool (pool_pulls via Sources' pull-more) and the single-view walkthrough takes over. Probe-first and gate-heavy: cheap counts before samples, samples before pulls, explicit user go-ahead before any volume spend or email enrichment."
---

# Lilly TAM — one pipeline: companies → decision makers → verified contacts

Replaces the five-skill patchwork (tam-mapper, both list-builders, both dm-finders — archived in `_archive/2026-07-14-unified/`). Methodology proven 2026-07-13/14 in `lilly-tam-recall-lab/` (30-brief company lab: 25/30, median 3.6× volume at ≥70%; 6-brief DM verify: 150/150 = 100% Prospeo title accuracy at the 90% bar).

> **Provider waterfall (Bjion 2026-08-03): GetLeads → Prospeo. AI Ark is RETIRED** (no subscription — every AI Ark call fails/bills nothing for us; treat any remaining Ark instruction in older skills as void). GetLeads opens every company and DM search; Prospeo fills what GetLeads can't reach. Prospeo-sourced emails are **always ListMint-verified** before they count as deliverable; GetLeads `VALID` emails also get a ListMint pass before any send (its VALID flag overstates deliverability ~24% — memory `data-provider-duel-verdict`).

## THE LAWS (non-negotiable, user-ruled)
1. **No lookalike features, ever — on ANY provider** (user 2026-07-13: "they both suffer from decay"). Discovery = native classifiers + industry enums + self-ID keywords. Ocean's people endpoints also banned (standing).
2. **No emails/phones as a side-effect** — company work is company-fields-only; DM search returns no emails; enrichment fires only after the user's explicit go-ahead. Never request mobiles unless asked (10× credit cost).
3. **Company accuracy bar = 70% · DM accuracy bar = 90%** (user: titles make DM targeting easier — hold it higher). Score actual returned rows, `lilly-lead-score` semantics, borderline ⚠️ never counts.
4. **DM filters: titles ALWAYS primary, Director+ seniority LAYERED on top — never seniority or department alone.** No bare "Director"/"Partner" in role sets (Partner only behind an industry gate). Director-and-above floor unless the user names lower.
5. **Location = person location AND company location in the target geo, unless told otherwise.**
6. **Size globally, tier after** — geo/headcount/sub-vertical tiers are post-extraction labels; per-tier filter queries collapse pools 6.6-11×.
7. **Additive, never replace** — cumulative exclude lists client-side (provider excludes are leaky/absent); dedup by canonical domain (companies) and normalised LinkedIn URL (people).

## Pipeline (each phase ends in a user gate)
**Phase A — Company map** → report dual-number TAM → *user gate* → **Phase B — DM map** → 90%-scored sample → *user gate* → **Phase C — Enrich + output** → hand-offs (`lilly-email-verification`, `lilly-heyreach-upload`, Smartlead via `lilly-bot` + `lilly-upload-gate`). Suppression gate runs BEFORE any paid people call.

**`pull_spec` input (from /lilly-strategy engine handoffs, 2026-07-19):** when the brief arrives as a strategy hand-off it carries a machine-readable `pull_spec` — `{provider, filters, notes}` with the EXACT probe-confirmed filter shape (schema: `lilly-strategy/engine/README.md`). Execute that shape verbatim as the Phase-A/B opening shape (it already passed the strategy probe — don't re-derive it); `notes` carries build-time exclusions to apply. Netting/suppression per wave runs through `lilly-strategy/engine/engine.py net --client <slug> --domains …` (the 30-day cooldown router: terminal / cooldown / free-from-records / new) — free-from-records rows are rebuilt from our own Supabase archive at zero provider cost, never re-purchased.

---

## Phase A — Company map (recall-max, proven 25/30)

**The selection rule: among shapes that hold ≥70% on a ≤25-row sample, keep the BIGGEST pool.**
1. Open at the LOOSEST defensible shape — native classifier alone (`company_type.subtypes` value, or one `company_industry` enum family) + headcount + geo. Never open with `business_model`/`has_subscription`/keywords.
2. ≥70% → try one WIDER rung (adjacent subtype/enum); keep widening until a rung fails; the failed rung is the recorded maximality proof. <70% → add exactly ONE narrowing layer (self-ID keywords with the gate kept on), re-gate. **Max 3 shapes per brief per provider.**
3. Rungs are GEO-DEPENDENT ([SaaS,Platform]: UK 76% ✓ / US 68% ✗) — score per geo, never transfer. Keyword baskets rerank non-monotonically (wider basket can SHRINK the pool) — baskets are probes, not dials.
4. **Dual-number TAM always:** per-provider pools AND the domain-deduped union (union = GetLeads + Prospeo − measured sample overlap; near-disjoint FAILS on tight niches — MSP UK measured 20%). GetLeads counts are CONTACT counts — estimate its company pool by deduping a sample's Company Domain column, never by quoting the contact total as companies.
5. **Structural routes (don't burn iterations):** brand/DTC briefs → Prospeo subtypes ladder E-commerce→Retail→Marketplace (measured 60,769 @ 80%). Provider-swamps (US MSPs, US mgmt-consulting — staffing/IT-consulting own the vocabulary on provider indexes) → pull the best 55-68% pool small + `lilly-lead-score` triage, or switch to signal mechanisms. Capability-flooded niches + micro-pools <20 → census + triage.
6. Optional third source: Ocean via `lilly-ocean-tam-builder` (free MCP browse pages to sample; its lookalike stages are Ocean-scoped — GetLeads/Prospeo stages here never use lookalike).

### Prospeo `/search-company` mechanics
`POST https://api.prospeo.io/search-company` · `X-KEY: $PROSPEO_API_KEY` (`~/.navreo-keys.env`) · body `{"page":1,"size":25,"filters":{…}}` · **1 credit/page (25 rows)**; `INVALID_FILTERS`/`NO_RESULTS` are FREE (use for enum discovery). Read `.pagination.total_count` (the pool) + `.results[].company{name,domain,industry,description,…}` (the sample).
Filters (top-level under `filters`, NEVER nested inside each other): `company_type{subtypes.include:[27 values incl SaaS/Agency/Construction/Consulting/Logistics/FinTech/E-commerce/Marketplace/Retail…], business_model, has_subscription}` · `company_industry.include` (STRICT LinkedIn strings — "Marketing Services" ✓, "Marketing" ✗, "Truck Transportation" ✗INVALID) · `company_keywords{include,exclude,include_company_description:true}` · `company_headcount_range` buckets · `company_location_search.include` (full country names; "Europe" valid) · plus the extended set (attributes/funding/news/key_execs/integrations/traffic/NAICS-SIC — probe page-1 per code family before trusting). Keyword EXCLUDES are not free precision (reduced it in 3/6 measured re-probes) — probe, keep prior shape as fallback. Multi-level-TLD domains (`.uk.com`) abort batches — strip before any `websites` list.

### GetLeads mechanics (FIRST in the waterfall — company AND DM side)
Hosted GetLeads MCP. **Call it SERIALLY — parallel count/search calls time out** (`person_description` is the slowest path). `count_contacts` = FREE exact totals for any filter set — always count before searching; `search_contacts` = 1 cr/row (max 100/call); `export_contacts`/`check_contact_export` = async CSV, 50k cap, `max_per_company` for balance. Enum values via `get_available_values` (`industries` are STRICT LinkedIn strings shared with Prospeo's `company_industry`; `personas`, `seniority`), filter mapping via `recommend_filters` — never guess enums. Company-side filters: `industries` + `company_description` keyword substring (comma = OR) + `employees_min/max` (band-overlap, no exact headcount) + `countries`; company pool = dedupe sampled `Company Domain`. Qualification: `require_email: true` + `email_status: ["VALID"]` (enum is VALID, never "verified"). Gotchas: search offsets return alphabetically clustered rows (one company can dominate a page — spread sample offsets); the `CRO` persona also matches Chief RISK Officers (banks/insurers) — exclude or budget ~7% pollution; plan credits ≠ prepaid wallet (wallet only funds paid scrapes — never report a low wallet as "out of credits").

### Phase-A gates
- **WebFetch-verify** a spot sample of any pot feeding a deliverable; hard abort a shape <50%; iteration cap 3 then record FAILED honestly (never declare done on a cap).
- **Report** per-provider pool + union + accuracy + the failed wider rung, then PAUSE for the user before any pagination/extraction (TAM mapping ≠ list pull; extract only what the user asks for).
- **Cache + ledger (mandatory):** every productive page → `navreo_db.put_enrichment("company", domain, "<provider>", obj, endpoint=…, source_skill="lilly-tam")` (downstream skills read funding/tech/headcount from this cache) and `navreo_db.log_provider_usage("<provider>", credits, endpoint=…, source_id="lilly-tam")`. Helper: `~/.claude/skills/_shared/navreo_db.py`. Check `get_enrichment` before any paid re-fetch.

---

## Phase B — DM map (verified 100% Prospeo / 90% bar)

**The method (user's canonical, verified 6 briefs):**
1. **LLM long-tail title expansion** of the brief's roles (~20-35 variants; include local-language titles — "Geschäftsführer"/"Algemeen directeur" match as exact Prospeo canonicals, verified 100%).
2. **Qualify** — prune anything not out-and-out close to the brief or below Director. Canonicalise survivors via free `/search-suggestions` `{"job_title_search": …}`.
3. **Search with titles PRIMARY + Director+ seniority layered** (law 4), **GetLeads first**: `personas`/`job_titles` + `seniority` + the Phase-A company shape (`industries`/`company_description`/size/geo), `require_email` + VALID; free `count_contacts` = the DM-TAM before any spend. **Prospeo `/search-person` is the SECOND rung** — fire it for what GetLeads can't reach (coverage gaps, long-tail titles needing `include_partial_match`, fixed domain lists): EITHER the Phase-A recall-max company shape passed straight into `/search-person` (verified: it accepts `company_type`/`company_industry`/`company_keywords` top-level — vertical-wide DM pulls inherit the ≥70% company gate, no domain list needed) OR `company.websites.include` (≤500 domains/call, auto-split silently) for fixed account lists. Cross-provider dedup locally by email + normalised LinkedIn URL.
4. **Score a 25-row sample against the 90% bar** (right function AND Director+; assistant-to/coordinator/below-floor = fail) and post-check `person.location` for the geo (Prospeo has no person-location filter; measured 0-8% off-geo leakage). **Present the audit as a `lilly-list-audit`-style function-mix breakdown** — on-brief % headline + the mix (OWNER/EXEC, SALES-LEADER, off-ICP functions, below-floor) + the named fails — then PAUSE for user go-ahead. The sample audit is what they approve; it is never skippable, regardless of how clean the shape looked at the company stage.

### Prospeo `/search-person` (SECOND in the waterfall — flat 1 cr/page regardless of rows)
Body `{"page":1,"filters":{<company scope>, "person_job_title":{"include":[canonical titles],"include_partial_match":true}, "person_seniority":{"include":["Founder/Owner","C-Suite","Partner","Vice President","Head","Director"]}}}`. Valid seniority strings exactly those (not "VP"/"Owner"). Response rows `{person{full_name,current_job_title,linkedin_url,location,person_id}, company{name,domain,industry}}` — **no emails in search**. Read `pagination.total_count` = the DM-TAM; report it before paginating. President is safe here (exact match can't hit "Vice President"). Accented titles can kill curl payloads — quote-safe or ASCII them.

### GetLeads DM search (FIRST in the waterfall — see GetLeads mechanics above)
- DM rows arrive WITH emails at 1 cr/row — that is the enrichment, not a side-effect; the volume-spend gate (user go-ahead) still applies before any pull beyond the 25-30-row sample.
- Fixed account lists: `domains` filter (or `getleads_lookup_colleagues_by_domain` for per-domain DM sweeps). `max_per_company` at export for "one/two per company" asks.
- Judge samples by title floor exactly as with Prospeo; the CRO/Chief-Risk-Officer collision and offset clustering (mechanics section) are the two known leak patterns.

### Suppression gate (BEFORE any paid people call)
Check the central suppression/already-contacted data (`lilly-data` / `navreo_db`) and the client's exclusions. Also sweep archived + active sibling campaigns on recontact-style briefs.

---

## Phase C — Enrich + output (only after the user's explicit go-ahead)

1. **Emails — the waterfall:** GetLeads rows already carry emails (`email_status: ["VALID"]` filtered) — they are the first source, no separate enrich call. Only for DMs GetLeads couldn't email: Prospeo `POST /enrich-person` body `{"data":{"linkedin_url":…},"only_verified_email":true}` (charges only verified hits, ~60% hit rate calibration; also accepts name+company_website or person_id inside `data`), email at top-level `email.email` with `email.status`.
2. **ListMint verification (MANDATORY on Prospeo emails — user law 2026-08-03):** every Prospeo-sourced email goes through ListMint before it counts as deliverable — never optional, never skipped. Spec: base `https://api.listmint.io/api/`, auth `?api-key=$LISTMINT_API_KEY` as a QUERY param (header form rejected; key in `~/.navreo-keys.env`), `POST /verify-emails?return=true`; statuses `valid | invalid | catch_all_valid | catch_all_invalid` — only `valid`/`catch_all_valid` survive into the deliverable. GetLeads `VALID` emails get the same ListMint pass **before any send** (VALID overstates ~24%) but may ship in the list deliverable flagged "ListMint pending" when the user defers verification.
3. **Output:** CSV/xlsx (inline table if ≤10) — full_name, title, linkedin, email, domain, company, source tags (`getleads_search` / `getleads_export` / `prospeo_company_search` / `prospeo_search_person` / `prospeo_enrich`) + `email_verification` (`listmint_valid` / `listmint_catch_all_valid` / `getleads_valid_unverified`). Domain-match filter drops cross-contaminated emails. Three-pot company output (qualified / borderline / off-brief) when the deliverable is a company list.
4. **Push hand-offs:** HeyReach via `lilly-heyreach-upload` (AddLeadsToListV2 only); Smartlead via `lilly-bot` campaign flow behind `lilly-upload-gate` (mandatory). Cache writes + usage ledger as in Phase A (person cache via `navreo_db.put_enrichment("person", …)`).
5. **Budget table before volume spend:** pagination credits + enrich credits (`total_count × 60% × 1`) + per-USEFUL-lead cost (discount by the sample's off-brief rate). Cap-hits and sub-bar results are reported as FAILED-with-gap, never "done".

## Contracts & guardrails (restored via 5-auditor completeness audit, 2026-07-14 — these are load-bearing)

**Cloud upload (MANDATORY — "a list that only lives on this machine isn't done"):** every finished deliverable (qualified.csv + borderline.csv company pots, and every verified-email DM CSV) uploads to the central Supabase list store before the run ends: `python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name … --client … --source-skill lilly-tam --brief … --owner …` (never off-brief.csv — stays local). The returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link is part of the deliverable. `--client` mandatory (internal → Navreo); `--folder` only for a named theme; max two levels; re-run with same name+client replaces rows in place.
**FULL-FIDELITY uploads (user rule 2026-07-14 — "use ALL the available information"):** the uploaded CSV carries EVERY field the providers returned, never a slimmed deliverable view — company rows: name, domain, description, industry, employee_count, employee_range, country/state/city, linkedin_url, keywords, naics/sic, technology, funding, founded, revenue_range + `source` (provider/endpoint) + `shape_tag` (the filter shape that found it — e.g. `subtypes:SaaS` — these are the self-labelling entity tags that make our own database searchable later) + the scored verdict (✅/⚠️). DM rows: full_name, title, seniority, linkedin_url, person location, email + verification status, company domain + company fields, source, shape_tag. Show the user a lean table in chat; upload the full one (`list_upload.py` carries whatever columns the CSV has — the slimming was always on our side). **Simultaneously upsert the rich company fields into the companies table** — `navreo_db.upsert_company(domain, name=…, description=…, industry=…, employee_count=…, employee_range=…, country=…, city=…, linkedin_url=…)` for every scored row (measured 2026-07-14: 294K companies in the table, <1% with industry/description because runs never called this — every paid row must land here from now on).

**Suppression mechanics (both phases, not just people):** seed the cumulative exclusion list from Supabase BEFORE the first COMPANY provider call — `navreo_db.check_exclusions(client_id, emails, domains)` or full-seed via `GET /rest/v1/v_exclusion?client_id=eq.{client}` + global `client_id=is.null` rows. **A `None` return = check UNAVAILABLE, never "no exclusions"** — fail-soft to the legacy local CSVs and say so in the summary. Report "N suppressed, M already contacted, K proceeding" before the probe. **Unattended runs** (e.g. theirstack daily): don't block on a human — apply what's available, log the degradation. Smartlead-campaign-as-input: paginate its leads, extract domains, AUTO-suppress every existing lead.

**Data write-backs:** per verified DM row → `navreo_db.upsert_person(email, linkedin_slug, first_name, last_name, title, company_domain, provider=…)`. Cache-first BEFORE paid people spend: query the Supabase people table (`/rest/v1/people?company_domain=eq.X&email=not.is.null`) — cached people satisfying the brief cost nothing. Append one line per run to `~/.navreo-cache/lilly-dm-runs.log` ({date | N domains | role | output | push | name}, cap 100) — powers "save as [name]" / "run [name]".

**Accuracy honesty:** GetLeads pages are alphabetically clustered — pools ≥100 get ONE deep sample at a large offset (~70% depth) and report **blended accuracy = mean(gate, deep)**; pools <100 = census, skip. TAM numbers always 3-column: **Verified (sample) / Estimated (raw × sample precision) / Pulled** — never one unlabelled number. Coverage honesty: domains where BOTH providers return 0 people are named in the summary — never a silently incomplete CSV.

**Spend guards:** free preflight (Prospeo `/account-information`) before the first paid call. Confirm the literal filter object (inclusions AND exclusions, auto-applied ones highlighted) with the user before the first paid probe, and restate the inferred DM title list in one line for confirm/override before any paid people call (standing user law: confirm inclusions/exclusions first). Expansion briefs (">50-company input list + find more"): measure sample overlap vs the input FIRST — ≥80% overlap → recommend skipping with projected net-new + cost; mid-run a page that's ≥80% already-known = stop paginating that source. Prospeo anchor-excludes: pass source-TAM domains in `filters.company.websites.exclude` (≤500 cap) AND client-side post-filter — both, always. 1-record `/enrich-person` probe before scaling — **contract drift 2026-07-27:** `/email-finder` + `/linkedin-email-finder` return DEPRECATED and `/bulk-enrich-person` now rejects `identifier` payloads (every row lands in `invalid_datapoints`, cost 0); the working call is `POST /enrich-person` body `{"data":{"linkedin_url":…},"only_verified_email":true}` (also accepts name+company_website or person_id inside `data`), email at top-level `email.email` with `email.status`; `free_enrichment:true` = no charge; a no-email result is free and TERMINAL — never retry; 429 on either provider = pause 10s, retry once, then provider-failure.

**Pot routing + quality gates:** on DM hand-off, borderline pot IS auto-included (never counted in headline qualified numbers); off-brief/unreachable rows are locked out of enrichment. WebFetch-verify EVERY company that will be enriched for a client deliverable (spot-samples are only for TAM numbers). Persistent off-brief drift blocklist `off_brief_blocklist.json` (in this folder) auto-prepends to excludes; prompt post-run for new drift attractors. Pre-push: HeyReach rows need linkedin_url; both destinations drop `email_status=invalid`; never auto-exclude catch-all/unknown without asking. "One per company" asks: group by domain post-merge, keep top-N by exact-title > adjacent-senior > result order.

**Defaults + phrasing:** no role in brief → proceed WITHOUT asking at the Director+ floor across departments, noting "No role specified — returning Director-and-above". Size-conditional targeting: ≤200 employees → top-of-org; >200 → mid-management entry (still Director+ unless user says lower). Sub-bar sample (70-89% DM accuracy): the user may explicitly override in so many words ("pull it anyway") — record the override. Deliverables use full words ("Companies", "Decision Makers" — never "cos"/"DMs" in user-facing output). Ocean-chained deliverable column order: `country, company, website, segment, tier, decision_maker_name, title, linkedin, email, phone, source`.

**API corrections (from audit contradictions):** Prospeo `person_seniority` also accepts "Manager" — the Director+ floor forbids using it unless the user explicitly asks below-Director. `company_intent` is FORBIDDEN on /search-company (UI-only); `company_icp.company_sizes` uses a different 5-bucket enum than `company_headcount_range` — never mix; short acronyms substring-match unrelated verticals ("ASO" → HR/PEO) — spell phrases out. **When Prospeo is down/out of credits, GetLeads carries the whole run alone** — record any coverage gap honestly rather than reviving a retired provider. The full probed extended-filter table (attributes/funding/news/traffic enums) lives in `_archive/2026-07-14-unified-into-lilly-tam/lilly-prospeo-list-builder/SKILL.md` — consult it before using an exotic filter. (AI Ark corrections removed 2026-08-03 with the provider — history in git.)

## Cost cheat-sheet
| Call | Cost |
|---|---|
| Prospeo search-company / search-person page (25 rows) | 1 cr; error/no-result pages free |
| Prospeo /search-suggestions, /account-information | free |
| Prospeo bulk-enrich email | 1 cr per VERIFIED match (batch 10) |
| Prospeo phones | 10 cr per hit — never without explicit ask |
| GetLeads count_contacts | FREE (exact total, any filter set) — always count first |
| GetLeads search/export row (email included) | 1 cr per row (search max 100/call; export 50k cap, async) |
| ListMint verify | per-email; key `LISTMINT_API_KEY` in `~/.navreo-keys.env` — MANDATORY on Prospeo emails |

## TAM-map closing rule (consolidated launch flow — Bjion ruling 2026-07-26)

Every TAM-MAP run (the "size/map the market" shape — Phase A/B numbers as the deliverable)
ends the SAME way, no exceptions:

1. **No UI launches at map time.** The numbers land in chat (dual-number TAM, DM count,
   confidence) — no wizard, no artifact, no tool page. **Plain English, always:** the
   user-facing line never says "probe-confirmed", "suppression-netted" or "netting" — say
   what it means, and lead with "market size" so juniors don't stall on the acronym:
   *"Market size for [segment]: ~X companies, ~Y decision makers we can actually reach (I've
   checked the count with the data provider and removed everyone we've already contacted or
   who opted out)."* The technical terms stay in the session record, not the chat.
2. **Always offer to draft the campaign** — one closing line, every run:
   *"Want me to draft this as a campaign? I'll save this exact audience and its filters to
   the campaign's Sources tab in the tool — so you can pull more from it any time — and walk
   you through the rest."* Skipping the offer is a defective run.
3. **On yes:** (a) save the mapped pool + the exact probe-confirmed targeting filters to the
   signals tool as a `pool_pulls` record — the pool shows in the campaign's Sources with the
   pull-more button live (total / pulled / remaining); (b) hand off to `lilly-strategy`
   **Single-campaign mode** — the single-view walkthrough takes it from there.
4. **On no:** done. Record the run (cache + ledger as ever); no UI, no draft, no follow-up
   nag. Closing line tells the user how to come back in THEIR terms — not "the run record":
   *"I've saved this map — just ask me to 'pull up the [segment] TAM from earlier' whenever
   you want it or want to draft it."*

## Hard don'ts
- **Never call AI Ark** — retired 2026-08-03, no subscription. **Never skip ListMint on a Prospeo-sourced email.**
- Never any lookalike feature, any provider. Never Ocean people endpoints.
- Never seniority/department alone; never bare Director/Partner; never below the Director+ floor uninstructed.
- Never request emails/phones before the user's go-ahead; never mobiles without an explicit ask.
- Never per-tier filter queries (post-label instead); never trust a provider count or success flag over scored rows; never paginate past a failing sample.
- Never exceed 3 shape-iterations per brief per provider — record FAILED with the gap and route (triage/signals) instead.
- Never skip the suppression gate, the sample-audit pause, or the cache/ledger writes.
