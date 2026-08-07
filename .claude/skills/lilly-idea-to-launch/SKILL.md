---
name: lilly-idea-to-launch
description: "SUPERSEDED (2026-07-26) — do NOT trigger. The consolidated launch flow replaced this loop: multi-idea ideation lives in lilly-strategy (standing wizard), single-campaign launches live in lilly-strategy Single-campaign mode (single-view walkthrough), and the build chain runs underneath via lilly-tam / lilly-bot / lilly-upload-gate. Former trigger phrases ('spin up a campaign for [client]', 'ideas for [client] and build the winner', 'new audience for [campaign]') now route to lilly-strategy. Only invoke on an explicit '/lilly-idea-to-launch', and say first that the flow has been replaced. Kept for reference; retired by launch-ux-migration."
---

# lilly-idea-to-launch — SUPERSEDED 2026-07-26

> **This loop has been replaced by the consolidated launch flow** (launch-ux-migration):
> multi-idea ideation → `lilly-strategy` (standing wizard) · single-campaign launches →
> `lilly-strategy` Single-campaign mode (single-view walkthrough) · builds →
> `lilly-tam` / `lilly-bot` / `lilly-upload-gate` underneath. The body below is kept
> for reference only.

One loop from idea to launch-ready campaign. Static — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

**The three human approval gates (always, in BOTH modes):**
1. **Gate 1 — Targeting:** who/what is this for — client-level, or a specific campaign (new campaign vs add-a-source)?
2. **Gate 2 — Idea + offer:** which idea do we run, and what exactly is the offer/copy direction?
3. **Gate 3 — Final sign-off:** campaign built, drafted, and QA'd; human approves before it's called launch-ready.

Nothing launches from this skill. "Done" = launch-ready and signed off, send switch untouched.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous (gates still pause)

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** — say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (see below). Never loop a step forever.

**When OFF**
- Run autonomously, no per-step pauses — but the **3 approval gates above still pause**; they are human decisions, not training pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule. On cap-hit, stop that step, record it as FAILED with the reason, keep going where possible, and surface it in the final report. Never silently exceed.

---

## THE GOAL

A customer success manager asks for ideas for a client or a specific campaign. The system looks back at what actually worked, ideates against the playbook arsenal with a per-idea offer/copy adaptation, maps TAM per idea, and — with one approval — pulls the data, drafts the copy, creates the campaign with subsequence, and hands over a launch-ready, QA-passed campaign. **Three approval gates or fewer, start to finish.**

**Verification bar (the process, not one run):** a panel of CSMs rates simplicity/ease 8/10+, and a panel of five customers rates idea quality, business understanding, and pain-point/signal/offer fit 8/10+.

---

## THE ARSENAL (playbook list — critique every idea against one of these)

The eight campaign types, from `lilly-strategy`'s vectors plus Prospeo signals. Every idea MUST name its playbook; no playbook, no shortlist.

| # | Playbook | Build hand-off | Copy/offer adaptation rule |
|---|---|---|---|
| 1 | Targeted TAM list | `lilly-tam` | Coldest audience: lead with the client's strongest proof, soft-CTA offer |
| 2 | Hiring signal | `lilly-theirstack-setup` | Anchor the offer to what the NEW HIRE will need (e.g. new CRO → "breakdown of how Claude Code gives you a top-level view of everything, so you onboard faster") |
| 3 | LinkedIn engagement signal (keywords/posts they engaged with) | `lilly-trigify-setup` | Reference the topic they engaged with as the reason-for-reaching-out; `skip_angles=["Hiring","You joined"]` |
| 4 | Events | manual + `loom-research` | Offer framed around the event ("before/after [event]") |
| 5 | Company followers | `lilly-linkedin-page-finder` + `lilly-company-followers` | Offer anchored on the followed page's category |
| 6 | Lookalikes of named clients | `lilly-tam` (seed clusters) | Lead with the named-client proof they resemble |
| 7 | News / funding intent | `lilly-icebreaker-news-search` (Prospeo: `company_funding` works; news+key_execs filters DEAD) | Offer tied to the moment ("post-raise" framing) |
| 8 | Prospeo signal filters (integrations, key customers, traffic, attributes) | `lilly-tam` `/search-company` | Offer names the signal explicitly as the trigger; {{Tool}} = trigger only, never teardown claim |

**Copy adaptation is mandatory per idea, even high-level (1-2 lines):** state how the offer, angle, or sending author changes to fit the campaign type. **New-audience rule:** if the idea reuses an EXISTING campaign's proven copy on a new audience, don't rewrite — adapt: keep the mechanism/offer, swap the audience-specific pain, proof, and vocabulary, and say what changed.

---

## THE STEPS

### Step 1 — Gate 1: targeting intake
- Establish: which client; **client-level** (fresh ideas) or **campaign-level** (a named campaign — and if so, "add a source" to it or spin a sibling campaign). Load `lilly-strategy/clients/<slug>.json` and memory before asking anything (ask only what's missing; confirm inclusions/exclusions and `dm_titles`).
- Done-rule: client slug + scope (client-level | campaign:<name> + add-source|new-campaign) + dm_titles are stated back and the user has said yes. **This is Gate 1.**

### Step 2 — Retrospective (what worked / what didn't)
- Pull the client's history: `lilly-optimiser` for live Smartlead stats, and `lilly-data` (Supabase) for cross-campaign patterns — positives by mechanism, by offer/lead-magnet, by title/vertical, dead angles, killed ICPs, TAM-exhausted campaigns.
- Output one block: **WINNERS** (mechanism × offer × audience, with positive counts), **LOSERS** (dead angles with reason), **REPLY PATTERNS** (who actually replies vs nominal ICP). Greenfield client → note `history: greenfield`, all ideas novel.
- Done-rule: the block exists with at least one named winner or loser (or an explicit greenfield note), and every claim carries a number pulled from Smartlead/Supabase, not memory.

### Step 3 — Ideate against the arsenal
- Generate 5-8 ideas. Every idea = **playbook # × audience × offer × copy-adaptation note**, critiqued against Step 2: winners get doubled-down variants, losers are never re-pitched unflagged. Named entities, not categories (lilly-strategy guardrail 13).
- If scope is campaign-level: ideas must extend THAT campaign (new source / adjacent audience), and copy notes must adapt its existing copy per the new-audience rule.
- Done-rule: every idea names its playbook, its copy-adaptation note (or new-audience adaptation), and cites which retro finding supports it. No idea duplicates a Step 2 loser without a `[re-pitch because X]` flag.

### Step 4 — NET decision-maker TAM per idea (via `/lilly-tam` probe shapes)
- **One `/search-person` page-1 probe per idea (1 credit, hard ceiling)** — company shape top-level + dm_titles family + Director+ → `total_count` = gross findable DMs. **Suppression-first netting (free):** check the sample's domains against `contact_history` + `suppressions`; NET DM TAM = gross × net ratio. **Company counts never appear in any output.** No row pulls, no enrichment at this step.
- **Offer artifact:** publish a private Artifact — one card per shortlisted idea: idea, net DM TAM, offer, rendered example email per its copy-adaptation note.
- Done-rule: every shortlisted idea shows gross → net DMs (probe-confirmed, suppression-netted, never estimated) and appears in the artifact; table saved to `lilly-strategy/sessions/<client>-<date>-i2l.md`.

### Step 5 — Gate 2: pick idea + approve offer
- Present the table; user picks the idea and approves (or edits) the offer + copy direction. Capture the approved direction verbatim — it is the copy brief.
- Done-rule: exactly one idea marked APPROVED with a written offer/copy direction from the user. **This is Gate 2.**

### Step 6 — One-command build: data pull
- **Suppression routing BEFORE any paid pull or enrich (Bjion ruling 2026-07-16, refined same day):** the canonical implementation is the strategy engine's router — `python3 ~/.claude/skills/lilly-strategy/engine/engine.py net --client <slug> --domains …` (terminal / cooldown / free_from_records / new + net ratio; never re-implement the SQL by hand). Semantics: load `contact_history` + `suppressions` FIRST and route every candidate three ways: (1) contacted for THIS client within 30 days / active enrollment / suppression-list / positive-replier → EXCLUDE; (2) contacted before but outside 30 days → include FREE from our own records (email + fields from the archive; never re-purchase or re-enrich); (3) never contacted → the only rows provider credits are spent on. Never pay a provider for a person our database already holds.
- Fire the approved idea's build chain (arsenal table column 3) to pull the leads: TAM pull via `/lilly-tam` → DM finding (Prospeo before AI Ark) → verification → **`lilly-upload-gate` (mandatory)** → upload to a new Smartlead campaign named `<client-slug>-<playbook>-<idea-slug>` (or into the incumbent campaign if scope = add-source).
- **Wave-based, never TAM-based (spend rules 2026-07-16):** launch wave = ~300 leads; never enrich more than 1.5× the wave. Fill order: (1) free-from-records people via the company-domain join, (2) cached enrichments (`get_enrichment` before ANY paid call), (3) fresh paid pulls. AI Ark fires only on shortfall and only at domains where Prospeo found zero DMs. Refill waves only when the optimiser shows ~75% consumed.
- **Checkpoint every pull** (write pages to disk as fetched; resume from last page) and **cache every paid row** (`navreo_db.put_enrichment` + `log_provider_usage`) so a crash or a future campaign never re-buys data.
- Done-rule: wave live in the right Smartlead campaign, upload-gate passed, per-source counts reported (free / cached / paid) vs the Step 4 net TAM.

### Step 7 — One-command build: copy + subsequence
- Draft the sequence via `lilly-copywriter` using the Gate-2 approved direction and the Step 3 adaptation note (new-audience rule if reusing proven copy). **Voice: lilly-copywriter's "THE NAVREO VOICE" section is canonical (corpus at offer-email-voice-match/voice-corpus.md; runtime code app/navreo_voice.py).** Save sequence + add the standard subsequence. Fill personalisation per playbook (icebreakers via `lilly-icebreaker`, `skip_angles` where the arsenal row says so).
- Done-rule: sequence + subsequence saved in Smartlead; copy visibly reflects the approved offer and the adaptation note; no unfilled merge variables in the saved copy.

### Step 8 — System-led QA
- Run `/lilly-qa` (full playbook: structure, spintax, variables ≥95% fill, formatting, lead hygiene). Fix mechanical fails and re-run (retry cap 3).
- Done-rule: lilly-qa passes with zero blocking issues.

### Step 9 — Mirror into the UI
- Register the approved idea in the signals tool so chat and UI stay one system: create the campaign (or attach the source to the incumbent campaign) via the app's API (`app/server.py` campaign/source endpoints), carrying name, playbook, offer note, and Smartlead campaign id.
- Done-rule: the campaign/source is visible on the live campaigns page (browser-verify the rendered page — that's the only done-evidence for UI).

### Step 10 — Gate 3: final human sign-off
- Present the launch-ready pack: campaign link, lead count, sequence preview, QA report, UI link. User signs off (or sends specific steps back — re-run only those, retry cap still 3).
- Done-rule: explicit user sign-off recorded. **This is Gate 3. Do NOT start the campaign.**

---

## HOW TO RUN

1. Read the mode line above. If **ON**, one step at a time, stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run straight through, pausing ONLY at Gates 1/2/5/10.
2. Gates never auto-pass, in either mode. Everything else is skippable when its done-rule already holds (e.g. fresh lilly-strategy session <7 days old satisfies Steps 3-4 — confirm and reuse it).
3. Plain English throughout (explain-5 default); no em-dashes; client-facing tables jargon-free.

## OVERALL DONE-RULE

- Gates 1-3 each have an explicit user approval on record.
- Smartlead campaign exists with leads (upload-gate passed), sequence + subsequence saved, lilly-qa clean, mirrored into the UI, **not launched**.
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (reason) — plus the launch-ready pack.
