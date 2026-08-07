---
name: icebreaker-name-normalise
description: Static orchestration skill that normalises every full name, company name, and hiring job title feeding the signals tool's personalisations so all icebreakers are email-ready — no emojis or other special characters (incl. variation-selector residue), no role tails ("Mike Weiss ceo"), no mis-casing ("Buldrr Ai"), no auto-link domains ("Ocean.io"). Adds person-name + job-title + email-safe cleaners to app/name_hygiene.py, wires them into the fields that render into icebreakers (engager_full_name, post_author_name, company, hiring role), backfills rows already pulled, and verifies. One fixed step list, each with a checkable done-rule, plus a Loop Training Mode toggle. Use when the user says "normalise the personalisations", "make the icebreakers email-ready", "clean the names/titles in the icebreakers", or "/icebreaker-name-normalise".
---

# icebreaker-name-normalise

Normalise every full name and company name that feeds a personalisation, so **all icebreakers are email-ready**. Static loop — the steps below are fixed, each has a done-rule, and Loop Training Mode controls whether you pause between them.

Files: `app/name_hygiene.py` (the cleaners), `app/server.py` (ingest + icebreaker render). App runs at `http://localhost:7901/app/campaigns.html`; Supabase project `fnykldftbkrccihdjayl` holds `engagement_events` / `signal_leads`.

---

## ⚙️ LOOP TRAINING MODE  →  **OFF** (default)

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

---

## THE GOAL

Every icebreaker the signals tool renders must be **email-ready**: it may contain only letters (including accented Latin), digits, spaces, ordinary punctuation (`. , ' " - & ! ? ( ) : / @ % +`) and `{{merge_tags}}`. It must **not** contain emojis, pictographs, or any other special/symbol character. The names inside it must read like a human wrote them — no role tails (`ceo`, `founder`), no ALL-CAPS shouting, no mangled casing (`Buldrr Ai` → `Buldrr AI`).

**Job titles get the same treatment.** Whenever an icebreaker names a role a company is hiring for (`Saw {{company}} is hiring for {{role}}…`, `server.py:2868`), that job title must be email-ready too — no emoji/pictographs, no pipes, tidy casing (`SENIOR ACCOUNT EXECUTIVE 🚀 | Remote → Senior Account Executive Remote`). This is the `clean_job_title` cleaner.

**No company name may carry an auto-hyperlinking domain.** A company written as a domain (`Instantly.ai`, `Ocean.io`, `navreo.ai`) renders as a live link in an email client — strip the TLD so it reads as the brand: `Instantly.ai → Instantly`, `Ocean.io → Ocean`. This is exactly what `clean_company_name`'s `TLD_RE` already does (`.ai`, `.io`, `.com`, … are in its `EMAIL_AUTOLINK_TLDS` list), so it's covered by the same cleaner — just verify it fires.

**Definition of "special character" (email-safe test):** any codepoint outside the allow-set above — in practice the emoji/pictographic/symbol/dingbat Unicode blocks, plus stray control characters and zero-width joiners. This is the single test both the sanitiser and the verifier use.

**Convention (reuse, don't reinvent):** `app/name_hygiene.py` already ships `clean_company_name`, and `server.py:470-486` already runs it on `signal_leads.company` + `engagement_events.engager_company_name` at ingest. **Extend that file and that wiring** — add the person-name and email-safe cleaners alongside `clean_company_name`, and hook them into the same ingest pass. Do not write a parallel cleaner elsewhere.

**Where the emoji comes from (root cause):** icebreakers use the template `Saw your comment on {{WhosePost}}'s post about {{Topic}}...` (`server.py:2216`). `{{WhosePost}}` is filled from `post_author_name` (`server.py:2403-2407`), and `engager_full_name` fills the lead's own name — neither is cleaned today. `Michel Lieben 🍩` is a raw `post_author_name`.

---

## THE STEPS

### Step 1 — Add the cleaners to `name_hygiene.py`
- Add `clean_person_name(name)`: strip emoji / pictographs / symbols / zero-width + control chars; strip trailing role/title tails (`ceo, cto, cfo, coo, founder, co-founder, owner, md, vp, head of …, director`); collapse repeated whitespace; title-case ALL-CAPS or all-lowercase names while **preserving** genuine casing (`McCarthy`, `O'Brien`, `van der`, `iCrossing`-style brands don't apply to people but keep intra-word caps). Return the original if cleaning would empty it.
- Add `clean_job_title(title)`: email-safe the title, strip pipes/wrapping junk, and title-case SHOUTING words (>3 chars) while keeping small connectors lowercase and short acronyms (AE, VP, SDR, AI) intact.
- Add `email_safe(text)`: NFC-normalise, then remove every codepoint outside the allow-set in THE GOAL (including combining/variation-selector marks left by emoji sequences — e.g. the `U+FE0F` after `☕`), then collapse the whitespace it leaves behind. This is the belt-and-suspenders sanitiser for a rendered string.
- Add `is_email_safe(text) -> bool`: the verifier's predicate — `True` iff `text` contains no special character.
- Done-rule: `python3 -c "from app.name_hygiene import clean_person_name, email_safe, is_email_safe; print(clean_person_name('Mike Weiss ceo'), '|', clean_person_name('Michel Lieben 🍩'), '|', email_safe('Saw your comment on Ana 🍩‍'s post'), '|', is_email_safe('clean text'))"` prints `Mike Weiss | Michel Lieben | Saw your comment on Ana's post | True` (names de-tailed + de-emoji'd, sanitiser strips the emoji + ZWJ, predicate holds).

### Step 2 — Wire the cleaners into ingest
- In `server.py`, extend the existing cleaning pass (`_NAME_FIELD_BY_TABLE` / `server.py:470-486`) so that on ingest of `engagement_events` the person-name fields **`engager_full_name`** and **`post_author_name`** run through `clean_person_name`, and company fields keep running through `clean_company_name`. Do the same for `signal_leads` full-name fields if present.
- Done-rule: `grep -n "clean_person_name" app/server.py` shows it applied to `engager_full_name` AND `post_author_name`; a fresh pull stores those fields already cleaned (spot-check one new row has no emoji and no role tail).

### Step 3 — Sanitise at icebreaker render (last line of defence)
- Wherever the icebreaker string is finally assembled for display/push — the engagement render path around `server.py:2405-2410`, the hiring render path around `server.py:2917-2924`, and `fill_icebreaker` (`server.py:2466`) — pass the finished string through `email_safe(...)` before it is returned/stored. This guarantees no special character survives even from a field type added later.
- **Hiring role specifically:** the role is merged in *after* `fill_icebreaker` via `.replace("{{role}}", …)`, so it must be `clean_job_title`'d before injection AND the whole line re-run through `email_safe` after — otherwise a raw title's emoji bypasses the sanitiser.
- Done-rule: `grep -n "email_safe" app/server.py` shows it wrapping the rendered icebreaker in the engagement path, the hiring path (after the role replace), and `fill_icebreaker`'s return; rendering a template whose `WhosePost`/`role` still holds an emoji yields a clean line.

### Step 4 — Backfill rows already pulled
- The leads already in the tool (e.g. the 10 under "Engagers of 46 tracked competitor profiles") were stored **before** the cleaners existed. Run the cleaners over existing data so they're fixed retroactively:
  - Update `engagement_events` rows in Supabase: `engager_full_name`, `post_author_name` via `clean_person_name`; `engager_company_name` via `clean_company_name`.
  - Update `signal_leads` company fields via `clean_company_name`.
  - Clean any stored hiring-role fields on source-doc prospects (`role`, `hiring_for`) via `clean_job_title`.
  - Re-render / re-store any persisted `icebreaker` strings (draft sources + `custom_fields.Icebreaker`) through `email_safe`.
- Do this with a one-off backfill script (put it in `app/` or the scratchpad); read before writing, and report row counts changed.
- Done-rule: a scan query over `engagement_events` returns **0** rows where `engager_full_name`, `post_author_name`, or `engager_company_name` fail `is_email_safe`, still carry a role tail, or still end in an auto-link TLD (`.ai`, `.io`, `.com`, …); the screenshot's 10 leads now read `Mike Weiss`, `Buldrr AI`, `Michel Lieben` (no emoji), and any `Instantly.ai` / `Ocean.io` reads as `Instantly` / `Ocean`.

### Step 5 — Verify every icebreaker is email-ready
- Enumerate every icebreaker the tool would render across all draft sources (render them the way `server.py:2405` does, using the now-clean fields), and run `is_email_safe` on each.
- Also assert the embedded names are de-tailed and correctly cased on a sample.
- Done-rule: **100%** of rendered icebreakers pass `is_email_safe` (zero special characters); the failing-count is 0 and is reported explicitly. Any icebreaker that can't be made safe is listed by lead, not silently dropped.

---

## HOW TO RUN

1. Read the mode line above. If **ON**, work one step at a time and stop for approval after each; skip any step whose done-rule already passes. If **OFF**, run all five in order without pausing.
2. For each step: make the edits (`name_hygiene.py` for Step 1, `server.py` for Steps 2-3, backfill for Step 4), then check the done-rule — run the `python3` / `grep` assertion, and for Steps 4-5 run the Supabase scan. Retry up to 3× on failure, then mark FAILED and continue.
3. After a `server.py` change, make sure the server still boots and the app loads clean before calling the step done.

## OVERALL DONE-RULE

- Cleaners exist and are wired into both ingest (Step 2) and render (Step 3), so new pulls are clean by construction.
- Existing rows are backfilled (Step 4): 0 name/company fields fail the email-safe test or carry role tails.
- **Every rendered icebreaker passes `is_email_safe` — 0 special characters, 0 emojis (Step 5).**
- Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (with reason) — and the final email-safe pass rate (target 100%).
