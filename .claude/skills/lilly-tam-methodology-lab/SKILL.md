---
name: lilly-tam-methodology-lab
description: "Static orchestration skill that runs a controlled list-building experiment across Ocean, Prospeo, and AI Ark to converge on ONE consistent, written methodology per platform — maximum volume at ≥70% brief-accuracy, cheap 50-row probes, explicit stop-rules for when extra filter approaches hit diminishing returns. Produces PLAYBOOK-ocean.md / PLAYBOOK-prospeo.md / PLAYBOOK-aiark.md validated on a hold-out brief. Use when the user says 'run the methodology lab', 'experiment with list-building approaches', 'fix the list-building inconsistency', or '/lilly-tam-methodology-lab'. Complements (does not replace) lilly-tam-mapper: the mapper BUILDS TAMs for production; this lab DISCOVERS the recipe the mapper should use."
---

# lilly-tam-methodology-lab

Run a controlled experiment across the three list-building platforms and come out the other side with **one written, repeatable methodology per platform**. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going, and surface it in the final report. Never silently exceed.

**Credit cap (both modes, hard):** **max 15 credits per platform per brief** during experiments (probe pages only, never full pulls). If a step would exceed it, stop and report — the cap is part of every done-rule.

---

## THE GOAL

Our list-building yields inconsistent results: sometimes high volume with brief-drift, sometimes accurate but tiny. Done means:

> For each platform (Ocean, Prospeo, AI Ark) there is a written **PLAYBOOK** — filter recipe + probe protocol + stop-rule — that on ≥2 test briefs produced its maximum volume at **≥70% verified accuracy**, where every further filter approach or pagination depth was tried and demonstrably fell below 70% (diminishing returns proven, not assumed).

**Sampling model (the physics of this experiment):**
- **Prospeo + AI Ark:** a **50-row sample is representative of the full pool.** 80% accuracy at 50 rows ≈ 80% at 50,000. So one 50-row probe per filter approach = the whole verdict. Cheap.
- **Ocean:** precision **decays with pagination depth** (lookalike especially — 70% page 1 → 40% pages 4-6 is documented). A page-1 sample is NOT representative of the pool; the experiment must measure the decay curve and find the depth at which the *running* precision crosses 70%. That depth IS the stop-rule.

**Accuracy = verified precision**, always measured the same way: sample → `lilly-lead-score` verdict table (never inline pattern-matching) → precision = ✅ ÷ (✅+⚠️+❌). Borderline ⚠️ does NOT count toward the 70%.

**Reuse, don't reinvent:** `lilly-tam-mapper` + the three single-tool skills (`lilly-ocean-tam-builder`, `lilly-prospeo-list-builder`, `lilly-ai-ark-list-builder`) already hold hard-won rules (buyer-type keywords, never industries-only, tight seed clusters, tier diagnostics, exclude caps). The lab treats those as **hypotheses to measure**, not folklore — each playbook confirms, quantifies, or overturns them with numbers.

---

## THE STEPS

### Step 1 — Fix the test briefs + baseline
- Pick **3 test briefs** with the user: (A) a hard-filterable brief, (B) a soft-category brief (services-vs-software type), (C) a **hold-out** brief reserved for Step 6 — never touched during experiments. Prefer briefs from real client work (memory: Navreo ICP, Amplifyy, HeyGrand, WordBank) so results are immediately useful.
- For each brief write a one-paragraph **gate**: what a company must BE to count as ✅ (the lead-score rubric).
- Free preflight all three platforms: Ocean `/v2/credits/balance` + `/v2/data-fields`, Prospeo `/account-information`, AI Ark D1/D2 tier diagnostic (≤2 cr — the one paid preflight).
- Record starting credit balances in `LAB-LOG.md` (in this skill's folder — every step appends to it).
- Done-rule: `LAB-LOG.md` exists with 3 briefs, 3 gates, 3 balances, and the AI Ark tier verdict (filter-tier or basic-tier). 0 credits spent except the AI Ark diagnostic.

### Step 2 — Prospeo experiment (cheapest, run first)
- On briefs A and B, fire **one 50-row probe (2 pages, 2 cr) per filter approach**, in this fixed order, each approach's results excluded from the next (`websites.exclude`):
  1. Buyer-type keywords + industry + headcount + geo (the incumbent recipe)
  2. `company_lookalike` icp_text mode (natural-language ICP, tier T2)
  3. One brief-relevant 2026 signal filter (e.g. `company_website_search`, type/business-model) layered on approach 1
- Score every 50-row probe via `lilly-lead-score`. Record per approach: `total_count`, verified precision, projected volume = `total_count × precision`, net-new vs prior approaches, credits.
- **Diminishing-returns rule:** keep an approach only if it is ≥70% precise AND adds net-new volume. Stop adding approaches when the newest one fails either test — that is the platform's ceiling, write it down.
- Done-rule: `LAB-LOG.md` has a Prospeo results table for both briefs; ≥1 approach per brief at ≥70%, and the first sub-70% (or zero-net-new) approach is recorded as the proven ceiling; ≤15 cr per brief. If NO approach reaches 70% on a brief after 3 retuning retries → record FAILED for that brief×platform and move on.

### Step 3 — AI Ark experiment
- Same protocol as Step 2, approaches ordered by the tier verdict from Step 1:
  1. Filter-first (`account.*` only — filter-tier keys only; on basic-tier skip straight to 2)
  2. Lookalike (5 tight seeds from the brief) + layered filters (Path A) or + client-side filtering (Path B)
  3. Lookalike with a SECOND, differently-clustered seed set (tests seed-verticality as a lever)
- 50-row probes (probe actual credit cost via dashboard delta on the first call — AI Ark billing is undocumented; if per-result, drop probe size to 25 and say so).
- Same diminishing-returns rule and scoring as Step 2.
- Done-rule: same shape as Step 2's, for AI Ark; the measured credit-cost-per-probe is written in `LAB-LOG.md`.

### Step 4 — Ocean experiment (the decay curve)
- On briefs A and B, run the two legal angles (**keyword-only**, **lookalike-only** — never industries-only) and for each: paginate `size:50` **one page at a time to page 4 max**, scoring EVERY page via `lilly-lead-score`. Do not stop at page 1 — the decay curve is the deliverable.
- Record per page: page precision, **running cumulative precision**, and net-new. The **stop-depth** = last page where running precision ≥70%.
- If page-1 precision <50%: one re-seed/re-keyword retry (per the mapper's recovery protocol), max 3 total, then FAILED.
- Then test ONE layered variant (winner angle + industry filter) for 1 page to see if layering shifts the curve.
- Done-rule: `LAB-LOG.md` has a per-page decay table for both angles on both briefs, a stated stop-depth per angle, and the layered-variant comparison; ≤15 cr per brief.

### Step 5 — Write the three playbooks
- From the log, write `PLAYBOOK-ocean.md`, `PLAYBOOK-prospeo.md`, `PLAYBOOK-aiark.md` in this skill's folder. Each is ≤1 page and contains exactly:
  1. **The recipe** — the winning filter approach(es), in firing order, with the exact filter shapes used.
  2. **The probe protocol** — sample size that predicts the pool (50 for Prospeo/AI Ark; per-page for Ocean) and the lead-score gate.
  3. **The stop-rule** — the measured condition to stop adding approaches/pages (sub-70% approach, zero net-new, or Ocean stop-depth).
  4. **The numbers** — precision, projected volume, credits-per-qualified-co from the experiments, per brief.
- Where a finding contradicts an existing rule in the mapper/list-builder skills, flag it explicitly in the playbook ("overturns rule #X") — do NOT edit those skills; that's a user decision after review.
- Done-rule: all 3 playbook files exist, each ≤1 page with all 4 sections populated from measured numbers (no placeholders, no folklore-only claims).

### Step 6 — Hold-out validation
- Run brief C (untouched until now) through each playbook's recipe verbatim — one probe per platform, no improvisation. Score via `lilly-lead-score`.
- Pass per platform = the playbook's recipe hits **≥70% precision on the hold-out** without modification.
- A platform that fails gets ONE playbook revision + re-probe (counts as a retry). Second failure → mark that playbook PROVISIONAL in its header.
- Done-rule: `LAB-LOG.md` has a hold-out table (platform × precision × pass/fail); every playbook is either VALIDATED or PROVISIONAL — none unlabelled; ≤6 cr total for this step.

### Step 7 — Final report
- Append to `LAB-LOG.md` and present: total credits spent per platform vs the caps, the three playbook verdicts, projected volume at ≥70% per brief per platform, the diminishing-returns evidence (the sub-70% approaches that were tried and cut), any FAILED steps with reasons, and the list of mapper/list-builder rules confirmed vs overturned.
- Recommend (CTA pattern, don't just ask): which playbook findings should be folded back into `lilly-tam-mapper` and the single-tool skills.
- Done-rule: report delivered; every experiment credit is accounted for; nothing spent on full pulls.

---

## GUARDRAILS

1. **Probes only, never full pulls.** This lab measures; it does not extract. Any full pagination is a separate, user-triggered `lilly-tam-mapper` run using the finished playbook.
2. **All scoring via `lilly-lead-score`.** Inline classification is banned — it's the main source of the inconsistency this lab exists to kill.
3. **Never Ocean people search; DMs are out of scope.** This lab is companies-only. DM enrichment stays in `lilly-decision-maker-finder-v2`.
4. **Cumulative excludes across approaches** within a platform, client-side post-filter always (provider excludes leak).
5. **Confirm filter inputs with the user literally** before the first paid call of each platform step — inclusions/exclusions are stated, never inferred.
6. **Every paid call gets a line in `LAB-LOG.md`** (platform, filters, cost, precision). If it isn't logged, it didn't happen.

## See also
- `lilly-tam-mapper/SKILL.md` — the production orchestrator these playbooks will feed.
- `lilly-ocean-tam-builder`, `lilly-prospeo-list-builder`, `lilly-ai-ark-list-builder` — per-platform mechanics (filter shapes, caps, gotchas).
- `lilly-lead-score/SKILL.md` — the single scoring gate.
- `lilly-decision-maker-finder-v2/SKILL.md` — downstream DM step, out of scope here.
