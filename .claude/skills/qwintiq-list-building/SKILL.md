---
name: qwintiq-list-building
description: >-
  Qwintiq's end-to-end prospect-list builder, powered by AI Ark only. Turns a plain
  campaign brief into (1) a market-size count of matching companies, (2) a count of the
  decision-makers inside them, and ONLY THEN, behind an explicit credit-spend confirmation
  phrase, (3) an exported CSV. Use this whenever you want to size a market, count companies
  or decision-makers in a vertical / geography / company-size band, build a prospect or
  contact list, or go from a campaign brief to an exportable list. Trigger on "build a
  list", "map the market", "how many companies / decision-makers in X", "find companies /
  contacts in [industry] in [country]", "size this audience", "who can we reach at [type of
  company]", or any campaign-brief-to-list request. This skill NEVER exports rows or spends
  meaningful credits until the user types the exact confirmation phrase. It is fully
  self-contained: it sets up AI Ark from scratch with the user's own API key and needs no
  other tools or prior context.
---

# Qwintiq List Building

This skill takes a campaign brief and walks it through three stages, in order:

1. **Map the market**: how many companies match the brief (cheap, a few credits).
2. **Map the decision-makers**: how many of the right people sit inside those companies (cheap).
3. **Export**: pull the actual rows into a CSV. This is the only step that spends real credits, and it is locked behind a confirmation phrase.

It runs entirely on **AI Ark** (one data source, one API key). It does not use or need any other tool, login, or prior setup.

---

## THE ONE RULE: never export without the confirmation phrase

This is the most important behaviour in the whole skill, because the person running it is spending their own money. AI Ark bills per record pulled, so an accidental "export everything" on a 70,000-row market is a 70,000-credit mistake.

**You may freely run the cheap mapping/counting steps** (Phases 2 and 3). Those request a single sample row and read the total, so they cost about a credit each.

**You may NOT pull a full list, retrieve rows in bulk, or write an export CSV** until the user types this sentence back to you, with the real number filled in:

> **`I confirm to export this and use X amount of credits`**

Rules for the gate:

- Replace `X` with the actual estimated credit count you calculated (e.g. `I confirm to export this and use 500 amount of credits`).
- The user must type it themselves. "yes", "go ahead", "do it", "export", a thumbs-up: none of these count. If they say anything other than the phrase, do not export. Politely show them the exact sentence to type and wait.
- Accept it if the wording matches in substance and the **number matches what you quoted** (case and trailing punctuation do not matter). If they type a *different* number than you quoted, stop and re-confirm. Do not guess.
- The phrase authorises **one** export of the scope you just described. A later or larger export needs a fresh confirmation with its own number.
- Never lower the number to make the sentence easier to say, and never type the phrase on the user's behalf or "assume" it. The gate exists to protect the client's credits and their trust in the system. Bypassing it defeats the entire purpose of the tool.

If you are ever unsure whether something counts as "an export", ask yourself: does this call return more than one row, or scale its cost with the number of matches? If yes, it is gated.

---

## How to talk to the user

The person running this is a business operator, not an engineer. Keep language plain:

- Say "how many companies match" or "market size", not "TAM" or "totalElements".
- Say "the contacts" or "decision-makers", not "DMs" or "enrich".
- Say "this will use about N credits", not "per-record billing".
- Never paste raw API JSON at them. Report clean numbers, short samples, and clear choices.

When you hit a decision point, give them the number first, then the choice.

---

## Phase 0: Connect AI Ark (one-time setup)

Goal: confirm you can call AI Ark with the user's key before doing anything else.

**Step 0.1, is AI Ark already connected?**
Check whether AI Ark search tools are available in this session (their names end in `company_search` / `people_search`; see `references/ai-ark-reference.md` for how the tool names look).
- If yes, say "AI Ark is connected" and go to Phase 1.
- If no, continue.

**Step 0.2, ask for the key.** Say something like: *"To use AI Ark I need your AI Ark API key. You'll find it in your AI Ark dashboard under API access. Paste it here."* Wait for it.

**Step 0.3, choose how to connect.** Offer both, recommend the first for regular use:
- **Option A (recommended for ongoing use): connect the AI Ark tool properly.** This adds AI Ark to Claude's config so its tools load automatically every session. It needs a one-time restart of the app. Steps are in `references/ai-ark-reference.md` ("MCP setup").
- **Option B (fastest, no restart): use the key right now.** Call AI Ark's web API directly with the key. Works immediately; the user pastes the key again next time unless they do Option A. (This path has a couple of data quirks that you handle automatically, see the reference file.)

**Step 0.4, validate the key with ONE tiny test call.** Before trusting it, run a single search for a well-known company by its website (e.g. a household-name firm in the brief's sector) and confirm a sensible result comes back. If it errors or returns nothing, the key or connection is wrong: troubleshoot via the reference file, do not proceed. Tip: pick a known company *in the brief's vertical* so the same call also shows you the exact industry label AI Ark uses (you will need it in Phase 1, see reference section 3), saving a credit.

Full connection details, both paths, and the API quirks live in **`references/ai-ark-reference.md`**. Read it now if AI Ark is not already connected.

---

## Phase 1: Take the campaign brief

Capture the brief in plain English. Ask for whatever is missing, do not assume. You need:

1. **What they sell** (one line, context for judging fit).
2. **Ideal customer: what kind of company?** The industry / vertical (e.g. "recruitment agencies", "dental clinics", "B2B SaaS").
3. **Where?** Country or countries.
4. **How big?** Employee size band (e.g. 11 to 50). If they do not know, ask whether they want small (1 to 50), mid (51 to 200), or any size.
5. **Who is the decision-maker?** The job titles / roles to target (e.g. "founders and sales leaders", "practice owners and managers", "heads of marketing").
6. **Anything to exclude?** Roles, company types, sub-sectors to leave out.

Then **play the brief back in one short paragraph and get a yes** before spending anything. While you do, translate it into AI Ark's filter values (see the reference file: industry must be an exact lowercase label, resolve it). If a filter value is uncertain, confirm a known example company lands in it before relying on it.

**Confirm the inclusions and exclusions literally**: the exact role/title set, the size band, the country, the exclusions, so there is no daylight between what they meant and what you will search. This matters because the count you produce, and later the credits they spend, depend on it.

---

## Phase 2: Map the market (how many companies)

Run one **company search** with the brief's filters (industry + country + size band), asking for just **1 sample row** and reading the **total match count**. A `size: 1` call costs about one credit.

Report it plainly: *"About 4,200 companies match: [vertical], [country], [size]."*

**Sample-fit and leakage check (do this every time, it protects the client's money).** Pull a small sample to eyeball. Keep it tiny, because each row you pull costs about a credit (a 5-row sample is about 5 credits). Then judge honestly:

- Are these genuinely the kind of company the brief means?
- **Watch for leakage.** A single broad industry label almost always sweeps in *adjacent* company types: trade associations and professional bodies, suppliers and equipment vendors, labs, training providers, franchisors, consultancies *to* the sector. Example: an industry label of "dental" returns dental associations and dental-equipment firms alongside actual dental practices. The count includes all of them.
- If the sample is plain wrong (wrong industry/size/country), the filter is wrong: fix and re-count.

**If the sample leaks, tighten BEFORE you move on.** Do not hand the client a number padded with companies they cannot sell to. Tightening options:
- Add a **keyword** that names the real target ("practice", "clinic", "agency", "studio") so only companies describing themselves that way match.
- **Exclude** the adjacent industries or company types that are leaking (e.g. exclude manufacturing/supply, or exclude non-profit and educational types for association leakage).
- Re-count after tightening and re-check the sample. Repeat until the sample is clean enough that the client would happily pay to reach everyone in it.

Tell the user plainly what you saw and what you tightened ("the raw label included some dental suppliers and associations, so I added a 'practice/clinic' keyword, which lands it at about X clean practices").

Do **not** export the companies here. This is a count only.

(Mechanics: params, the size-filter gotcha, keyword/exclude params, how to read the total, are in the reference file.)

---

## Phase 3: Map the decision-makers (how many people)

Now count the *people* who match both the company filters AND the target roles. Run a **people search** with the company filters PLUS the role filters, asking for **1 sample row** and reading the total.

**Mapping roles to the search.** There are three dials, and one search ANDs them together:
- **Seniority** (founder, owner, c_suite, partner, director, head, vp, manager, ...): how senior the person is.
- **Department / function** (sales, business_development, marketing, operations, finance, ...): what part of the business. This is NOT always "sales", match it to the brief.
- **Title** (free text, e.g. "practice manager"): use this when the role has no clean seniority or department handle.

Because one search ANDs the dials together, a brief that names **two different kinds of role usually needs two (or more) separate counts that you then add up.** Pick the dial that best isolates each role, and keep the counts non-overlapping so the sum is clean. Worked examples:

- **"Founders + sales leaders" (e.g. recruitment agencies):**
  - Count A: seniority = founder, owner, c_suite, partner, director, head, vp (no department). Founders, MDs, CEOs, sales and commercial directors.
  - Count B: department = sales, business_development AND seniority = manager, with excludeTitle = "Account Manager" (drops relationship/delivery managers). Catches BD and Sales Managers.
  - Total is A + B.
- **"Practice owners + practice managers" (e.g. dental clinics, which have NO sales function):**
  - Count A: seniority = owner, founder, c_suite, partner, director. The principal/owner layer.
  - Count B: title = "practice manager" (a title search, since there is no "sales" department here).
  - Total is A + B.
- **"Heads of marketing" (a single role):** one count, department = marketing AND seniority = head, director. No summing.

Report the split and total in plain English: *"About 3,000 decision-makers: 2,500 owners/leadership plus 500 practice managers."*

**Always play the role-to-filter mapping back to the user** (tell them which dials you used for each role) so they can catch a mismatch before any spend, e.g. if they meant "office managers" and you searched "practice managers". Sample-check fit again (are the sample people really the right roles at the right companies?). Then **stop. Do not pull the people.** This is a count only.

---

## Phase 4: The export gate (STOP HERE)

By now the user has two clean numbers (companies, decision-makers) and trusts the targeting. Only now do you discuss spending real credits.

**Step 4.1, ask what to export and how many.** Companies, decision-makers, or both? All of them, or a capped first batch (e.g. first 1,000)? Most clients cap.

**Step 4.2, estimate the credit cost (X).** AI Ark bills roughly **one credit per row returned**. So:
- Exporting N companies is about N credits.
- Exporting M decision-makers is about M credits.
- X = the total rows they chose to export. State it as an estimate and tell them to sanity-check it against their AI Ark plan balance.

**Step 4.3, present the gate.** Quote the exact sentence with the real number:

> To export **[scope, e.g. 1,000 decision-makers]** I'll use about **[X]** credits.
> To go ahead, type this exactly:
> **`I confirm to export this and use [X] amount of credits`**

**Step 4.4, wait.** Do not pull rows, paginate, or write a CSV until they type it (per THE ONE RULE above). If they hesitate, change the scope, or want a smaller batch, recompute X and re-quote the sentence. Anything other than the phrase means keep waiting.

---

## Phase 5: Export and hand off

Only after a valid confirmation:

1. **Pull the rows up to the agreed cap X.** Page through the results collecting companies and/or people, but **never request more rows than X**: size each page so the running total cannot exceed X, and stop the instant you reach it. The confirmation authorised X rows and no more; overrunning spends credits the user did not approve.
2. **De-duplicate** by company website (and by person for contacts).
3. **Write a CSV** with clear columns:
   - Companies: `company_name, website, country, employee_count, industry, linkedin`
   - Decision-makers: `full_name, title, company_name, website, country, linkedin` (plus `email` only if the user separately asked for verified emails; note that email verification is a different paid step and you must gate it the same way, with its own confirmation phrase and number).
4. **Tell them where the file is** and give a one-line summary (how many rows, how many credits used).
5. **Next step:** the rows are ready to load into the client's outreach tool. Qwintiq runs outreach through **Lemlist** (email + LinkedIn). Load the list into a Lemlist campaign with **qwintiq-lemlist-upload** (straight from Claude Code), or import the CSV in the Lemlist UI. This skill stops at the CSV.

---

## Reference

- **`references/ai-ark-reference.md`**: everything AI-Ark. How to connect (both ways), the exact search parameters, how to resolve industry/location labels, how to read counts, the per-record billing, and the handful of data quirks that will otherwise waste your time. Read it during Phase 0 and keep it open for Phases 2 to 5.

## Guardrails (the short version)

1. **No export without the exact confirmation phrase and correct number.** This is the whole point of the tool. (See THE ONE RULE above.)
2. **Mapping is cheap and allowed; exporting is gated.** Counts use 1 sample row. Never count by pulling the whole list.
3. **AI Ark only.** No other data source, login, or tool is needed or used.
4. **Confirm the brief and the role/title mapping before spending.** Do not infer the target set: play it back and get a yes.
5. **Always check the sample fits the brief, and tighten leakage, before trusting a count or exporting.**
6. **Plain English with the user.** No jargon, no raw JSON.
7. **Self-contained.** Assume a fresh Claude with no other skills, no saved keys, no memory. Set AI Ark up from scratch each time it is not already connected.

## Cloud upload (mandatory)

Every exported partner/prospect list from this skill MUST be uploaded to the central Supabase list store before the run ends — a list that only exists on this machine is not a finished deliverable. After the export lands, run:

`python3 ~/.claude/skills/_shared/list_upload.py <final.csv> --name "<descriptive list name>" --client "Qwintiq" [--folder "<Theme>"] --source-skill qwintiq-list-building --brief "<one-line brief>" --owner "<who asked>"`

Then show the returned `https://navreo-signals.onrender.com/app/lists.html#<id>` link to the user — that link is part of the deliverable, alongside the CSV.

Folder rules: `--client` is the client named in the brief (this skill's lists are Qwintiq's unless the brief says otherwise; internal/Navreo pulls go to `Navreo`); add `--folder` ONLY when the brief names a campaign theme or segment — never deeper than two levels. Re-running with the same name+client replaces that list's rows in place, so re-exports are safe.
