---
name: preview-accuracy-ship
description: Make every idea/search preview in the Navreo signals tool (app/campaigns.html + app/server.py) show DECISION-MAKER counts, never company counts. Role split: Prospeo/TheirStack identify COMPANIES, AI-ARK identifies the DECISION MAKERS at them (better coverage); DM counts in previews come from AI-ARK size:1 totalElements probes. One static orchestration loop — audit every preview surface, convert the math and labels to DMs, wire AI-ARK as the pull-path DM finder, then verify by running the setup wizard end-to-end. Done when no wizard surface shows a company count where a person count belongs. Use when the user says "fix the preview counts", "run the preview accuracy skill", "/preview-accuracy-ship".
---

# preview-accuracy-ship

A preview that says "2" must mean 2 people we can email, not 2 companies. Fix the denominators everywhere, then prove it by walking the wizard.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by user 2026-07-05)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for the user's explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** max **4** full loops. Any single step retries **max 3** times. On cap-hit, stop and report the best result + what's still failing. Never declare done.

---

## THE GOAL

- **Previews = decision makers.** Wherever an idea or search is previewed (strategy-map ideas table, source-wizard previews, campaign cards, summary steps), the number shown is the count of DECISION MAKERS we expect to email — for hiring signals that means the DMs we'd find AT the hiring companies, not the companies themselves. Company counts may appear only as clearly-labelled secondary context ("at ~N companies").
- **Role split (user rule 2026-07-05).** COMPANIES are identified by Prospeo (and TheirStack for hiring) — unchanged. DECISION MAKERS at those companies come from **AI-ARK** (materially better people coverage). Prospeo may still size company TAM in previews, but the DM number shown to the user comes from AI-ARK.
- **The cheap DM count:** AI-ARK bills per person returned and has no free count endpoint — so probe with `people_search` **`size: 1` and read `totalElements`** (full match count across all pages, billed ≈1 person). This is the established DM-TAM count pattern (reference_dm_finder_apis.md ~line 173; operationalised in lilly-tam).

## HOUSE RULES THAT BIND THIS WORK (don't rediscover — primary sources: reference_dm_finder_apis.md + lilly-tam SKILL.md)
- Never Ocean people search. AI-ARK bills per person returned — every call caps `size` deliberately.
- **AI-ARK count probes:** `size:1` → `totalElements`. `title` is phrase-FUZZY (AND-of-words): rare phrases ≈90% on-function, common-word pairs can drop to ~65% — for counts on common titles, sample `size:10`, measure on-brief share, and discount the headline accordingly (show "≈"). Comma-separated `title` = OR across phrases.
- **Geography:** `companyLocation` means "has an office in X", NOT HQ — for a country campaign set BOTH `companyLocation` AND person `location` (drops counts ~12-16%, honestly).
- **Size filters:** `minEmployees`/`maxEmployees` filter numeric staff totals (server REST path: `employeeSize` RANGE — the REST `headcount` bucket is silently ignored). MCP is flat-param; server-side REST uses the nested shape — read the reference file before coding either.
- Seniority AND department combine as AND — "founders OR sales-leaders" needs two disjoint probes summed.
- Prospeo /search-person title matching is EXACT — expand_titles enumerates the family server-side (still used for company-side work).
- DM-TAM headline = a probed count or a clearly-marked ≈ estimate — never an unlabelled company count, never a bare LLM guess.
- A parallel session edits the same files: re-read before editing; "File has not been read yet" = external change.

## 💰 SPEND GUARD
- Audit and label/math fixes: zero provider calls.
- DM-count probes in previews: AI-ARK `size:1` (≈1 person's credits each) — cache by filter-set in the strategy cache so repeat wizard runs don't re-bill; fuzzy-title sampling (`size:10`) only when the title family has common-word pairs, once per family.
- Pull verification: ONE bounded live pull on a throwaway test source (AI-ARK `size` capped at ≤10 people total, then delete everything).
- Budget for the whole skill run: ≤ 15 provider credits / ≤ ~25 AI-ARK person-returns. Blown → stop, report.

## THE STEPS

### Step 1 — Audit every preview surface
Done-rule: a written map (in the run log) of every place a count is shown to the user during ideation/creation/preview — for each: file+line, what it counts TODAY (companies vs DMs vs people), and what it should count. Known suspects: strategy-map probe math for hiring/funding/exec_change/traffic_decline (server.py `probe_once`/`probe`), `/api/preview/hiring|companies|lookalike` ("N matched" in the source wizard), campaign list cards, wizard step-5 table + step-6 summary + step-7 preview, "People found · first N of TOTAL" lines.
- Zero spend: this step is reading code, not calling providers.

### Step 2 — Convert previews to decision-maker counts (AI-ARK size:1 probes)
Done-rule: every surface from the Step-1 map either (a) shows a genuine DM count — AI-ARK `people_search` `size:1` → `totalElements`, filtered by the source's own dm_titles (who we email) + the company filters, with the fuzzy-title discount applied where needed — or (b) shows "≈ N decision makers (at ~M companies)" where a probe isn't affordable — and NO surface shows a bare company count. Labels say "decision makers" / "people we can email", not "matched".
- Hiring ideas: companies still sized by TheirStack/Prospeo, but the HEADLINE number is the AI-ARK DM count at that company profile (or ≈ companies × titles until probed).
- Keep the strategy cache working (same cache key semantics) and keep `skip_probe` direct mode zero-spend ("sized on first run" stays).

### Step 3 — Wire AI-ARK as the DM-finder in pulls
Done-rule: the pull path (`pull_hiring_source` / `dm_find_by_domain` and any other DM-fill) keeps Prospeo/TheirStack for COMPANY identification, but finds the DECISION MAKERS at those companies via AI-ARK people_search (per-company or batched company filters, dm_titles applied, `size` capped per company); AI-ARK emails are real-time verified at source so they skip MillionVerifier; each lead stamps its provider; previews and pulls both leave Prospeo running company-side only. Verified per the spend guard (one bounded live pull on a throwaway source).
- Dedupe merged results on linkedin_url/email. Prospeo DM-search remains as the FALLBACK if AI-ARK errors on a run — never both billed for the same company in one pull.


### Step 4 — Verify through the wizard (the user's own test)
Done-rule: run the setup wizard end-to-end for ONE hiring idea (AI-suggest mode so numbers actually show; smallest sensible audience) and capture evidence: the ideas table, the summary, and the source card all show decision-maker counts, with any company figure clearly secondary. Then delete the test campaign. If any surface still shows a bare company count → step fails, back to Step 2.

### Step 5 — Log, clean up, decide
Done-rule: run log `PREVIEW-ACCURACY-<date>.md` written (surface map, before/after per surface, waterfall verification evidence, spend); all test artifacts deleted; live client campaigns untouched.
- **All step done-rules green → DONE.** Else loop (cap 4).

## THE DONE-RULE (single source of truth)

> Walking the setup wizard shows decision-maker counts at every preview surface (companies only as labelled context) — DM numbers sourced from AI-ARK size:1 probes or marked ≈ — and pulls identify companies via Prospeo/TheirStack but decision makers via AI-ARK; verified with evidence, cleaned up, within budget.

On cap-hit, report the gap honestly — never declare done.

## GUARDRAILS
- Don't inflate: a DM estimate must state it's an estimate (≈) until a probe confirms it. Accuracy is the goal, not bigger numbers.
- Don't slow the wizard: no new blocking probes in direct mode; AI-suggest mode may probe (it already does) but reuse its existing job/polling machinery.
- Scope: preview denominators + pull waterfall only. Creation UX (8.0/10) and push UX (8.33/10) are proven — don't regress their flows or their spend guards.
