---
name: qwintiq-partner-signals
description: >-
  Qwintiq's end-to-end daily partner/PR signal routine. Each run it finds at least 20 companies
  that just did something Qwintiq cares about (launched a partner / channel / reseller programme,
  started hiring a PR Director or comms lead, or started hiring a Head of Partnerships / partnerships
  lead), works out each company's website, keeps only the ones that fit the company-type rule, uses
  Qwintiq's decision-maker finder (AI Ark people search) to pull the right roles inside them, writes a
  personalised icebreaker that names what we found, and pushes the finished people into a chosen
  Lemlist campaign. It is built around a five-step setup wizard the user fills in once per routine
  (1: which signals, 2: what type of company, 3: which decision-makers, 4: how the icebreaker reads,
  5: which Lemlist campaign), plus a run-mode choice (Supervised or Autopilot), saved as a routine config so the daily run is one command afterward. Use
  this whenever the user wants to set up or run Qwintiq's partner-signal prospecting, "find companies
  that just launched a partner programme / are hiring a PR or partnerships lead", build the daily
  partner routine, or top up the Qwintiq Lemlist campaign with timely partner prospects. Trigger on
  "set up the Qwintiq partner routine", "run today's partner signals", "find companies hiring a Head of
  Partnerships / PR Director", "who just launched a partner programme", "show me my partner routine",
  "what signals am I tracking", "change my partner signals", "add a signal to my routine", "put my
  routine on autopilot", "switch back to supervised", or any partner/PR event-driven prospecting request
  for Qwintiq. It controls spend by run mode: Supervised stops each day for the exact typed confirmation
  phrase before pulling people, while Autopilot uses a one-time standing permission with a required daily
  credit cap. It asks the user to define the five targeting inputs because they are judgement calls that
  belong to the user.
---

# Qwintiq Partner Signals

This skill is Qwintiq's **daily partner-signal routine**, wrapped end to end. Each run turns "a company just did something worth noticing" into "the right people, with a personalised opener, loaded into the Lemlist campaign, today".

It is built from the existing Qwintiq parts, tied together by one setup wizard:

- The find-and-qualify-and-pull-people engine is **qwintiq-signals** (web search, domain resolution, qualifying, AI Ark people search).
- The opening line is **qwintiq-icebreaker**.
- The push into the campaign is **qwintiq-lemlist-upload**.
- The message sequence (if it is not written yet) is **qwintiq-copywriter**.

This skill's job is to hold the routine's settings, run those parts in the right order with no gaps, and stop at the one place that costs money.

> Note on the name: the client is **Qwintiq** (sometimes said "Quintic"). The "Quintic decision maker finder" the user refers to is Qwintiq's decision-maker finder, which is the **AI Ark people search** used in Step 3 below.

---

## THE ONE RULE: spending people-credits is always the user's call

Finding companies, resolving their websites, and qualifying them is all free web work. **Using AI Ark to pull the decision-makers costs the user's own credits, about one credit per person returned.** So an unchecked "find everyone" on a busy news day can be a large, unintended spend. That spend is always under the user's control, but *how* it is controlled depends on the run mode they chose when they created the routine (Step 6 of the wizard).

You may always freely do the find, resolve, and qualify steps, and you may freely *count* how many decision-makers AI Ark sees (a count uses one sample row, about one credit). What is gated is the **pull** of the actual people (and any email enrichment).

### Supervised mode (the default)

You may **NOT** pull the people until the user types this sentence back, with the real number filled in:

> **`I confirm to export this and use X amount of credits`**

- Replace `X` with the real estimated number of people you are about to pull.
- The user must type it. "yes", "go ahead", "do it", a thumbs-up: none of those count. Show them the exact sentence and wait.
- It authorises **one** pull of the scope you just described. Tomorrow's run needs a fresh confirmation.
- Never type it for them, and never lower the number to make it easier to say. The gate protects their credits and their trust in the routine.

### Autopilot mode (explicit, bounded standing permission)

A routine may instead be created on Autopilot: the user gives **one explicit, up-front authorization** to find the decision-makers and push them straight into the campaign on their own each day, with no daily stop. Autopilot is real, but it is bounded:

- It is valid **only** if the user set it (at creation, or later in plain words such as *"put my routine on autopilot"*) and it is recorded as `run_mode: "autopilot"` in the routine config. If the config does not say so, you are Supervised. Never assume Autopilot.
- Autopilot **must carry a daily credit ceiling** (`daily_credit_cap`). If the user turns it on without naming a cap, ask for one before saving (offer a sensible default such as 20). The cap is the standing equivalent of the confirmation number: you may spend up to it on your own, never past it.
- Each day, do the free find / resolve / qualify / count as normal. If the day's count N is at or under the cap, pull and push without stopping. If N is over the cap, pull up to the cap (best companies first), push those, and tell the user the rest are waiting. Never exceed the cap.
- Email enrichment stays **off** under Autopilot too (LinkedIn-only), unless the user separately and explicitly authorised a paid email pull with its own cap.
- After every Autopilot run, post the end-of-run summary. Standing permission is not silence: the user must always be able to see what was found, pulled, spent, and pushed.
- The user can revoke it any time (*"take my routine off autopilot"* / *"back to supervised"*). When in doubt, fall back to Supervised, the safe default.

During testing, keep batches small and **avoid email enrichment** (verifying emails is a separate paid step that burns credits fast). Pull LinkedIn-only people (their LinkedIn steps still run in Lemlist) unless the user specifically asks and confirms an email pull with its own gate.

---

## How to talk to the user

Plain language, always:

- Say "companies that just launched a partner programme" or "companies hiring a Head of Partnerships", not "signal hits".
- Say "the right people inside them" or "decision-makers", not "DMs" or "enriched contacts".
- Say "this will use about N credits", not "per-record billing".
- Give the count first, then the choice. Never paste raw search results or JSON.
- No em dashes. Use commas, colons, or full stops.

---

## Your routine, in plain terms (make it, run it, change it)

A **routine** is just your saved set of choices, with a friendly name. You make it once by talking to Claude in plain words. After that, one short sentence runs it, and one short sentence changes it. **You never open a file, write a single search term, or touch any settings yourself. Claude does all of that for you.** Here is the whole life of a routine.

### 1. Make it (the first time)

Say: *"Set up my partner signals routine."*

Claude walks you through five quick questions (the wizard below). The only one that takes any real thought is the first, **which signals you want**, and even that is a pick-list:

- Claude shows you a short menu of ready-made signals (companies that just launched a partner programme, that are hiring a PR lead, that are hiring a partnerships lead, that just rebranded, that just raised funding, and a few more).
- You pick the ones you want by number, in any order, for example *"I'll take 1 and 3."*
- Or you describe your own in one sentence, for example *"also track companies that just opened a US office."* Claude turns your sentence into a working signal for you. You do not write search terms, Claude does that quietly in the background.

When the five answers are set, Claude reads them back to you in plain English and saves the routine under a name you will recognise (for example **"Partner and PR signals"**). That is it, you are done.

### 2. Run it (every day)

Say: *"Run today's partner signals."* (or let it run on its own each morning, once you have set it to.)

Claude loads your saved routine and does the day's work: finds the companies, checks they fit, then handles the people step the way you set it up:

- **Supervised:** it stops and shows you the shortlist and the spend, and waits for your OK before it finds anyone or loads them.
- **Autopilot:** it finds the right people and loads them straight into the campaign on its own, up to your daily credit cap, then sends you a summary.

You do not re-answer anything. The routine remembers your choices.

### 3. See what it is set to

Say: *"Show me my partner routine"* or *"What signals am I tracking?"*

Claude prints your routine back in plain English: the signals in order, how far back it looks, how many companies a day, the company rule, the roles it pulls, and the campaign it loads. No file, no code, just a readable summary you can check at a glance.

### 4. Change it (any time)

Just say what you want in plain words. Claude updates the saved routine and reads the change back to confirm. You never edit anything yourself. Common changes:

| You say | What happens |
|---|---|
| *"Add a signal for companies that just rebranded."* | Claude adds it and asks where it should sit in the order. |
| *"Drop the PR hiring signal."* | Claude removes it. |
| *"Put the partnerships hire first."* | Claude reorders the list. |
| *"Look back 30 days instead of 14."* | Claude changes the recency window. |
| *"Aim for 30 companies a day."* | Claude changes the daily target. |
| *"Only B2B SaaS in the US and UK."* | Claude updates the company rule. |
| *"Send them to the 'Partner Outreach Q3' campaign instead."* | Claude switches the Lemlist campaign. |
| *"Make the opener mention the partner programme more directly."* | Claude updates the icebreaker brief. |
| *"Put my routine on autopilot."* | Claude switches it to Autopilot and asks for a daily credit cap. |
| *"Put it back to supervised."* | Claude switches it back, so it asks before every spend. |
| *"On autopilot, spend up to 20 credits a day."* | Claude sets or changes the daily credit cap. |

After any change, Claude reads the whole routine back so you can see it landed right. If you ever want to start fresh, say *"redo my partner routine"* and Claude runs the wizard again from scratch.

### Where it lives (you do not need this, but here it is)

Your routine is saved as a named routine **inside Claude**, so any new chat can find it by name. You can have more than one: say *"what routines do I have?"* to list them, and name a new one when you make it, for example *"set up a second routine for events signals."* The technical copy sits at `~/.claude/skills/qwintiq-partner-signals/routines/<name>.json`, but **you never need to open that.** Every change is a sentence to Claude. Treat the file as Claude's notebook, not yours.

### The plain-English read-back (what "show me my routine" prints)

Whenever you save a routine, change one, or the operator asks to see one, render it in exactly this friendly shape. Never show JSON, file paths, search terms, or AI Ark dials.

> **Partner and PR signals** (your saved routine)
>
> **Watching for**, best first:
> 1. Companies that just launched a partner programme
> 2. Companies hiring a partnerships lead
> 3. Companies hiring a PR lead
>
> **How recent:** anything from the last 14 days
> **How many a day:** at least 20 companies
> **Only companies that are:** B2B SaaS in the US and UK, 11 to 500 staff
> **People I'll find inside them:** Head of Partnerships, VP Partnerships, Head of PR, plus the founder or CEO at smaller ones
> **Where they go:** your "Partner Outreach Q3" Lemlist campaign
> **How it runs:** Supervised, I check with you before I spend each day (Autopilot would push on its own up to your daily cap)
>
> Want to change anything? Just tell me, for example *"look back 30 days"* or *"add a signal for new funding."*

If part of the routine is not set yet (for example the company rule or the campaign), show that line as **"not set yet, want to fill it in?"** rather than hiding it.

To answer *"what routines do I have?"*, read the `routines/` folder and list each routine's friendly name and its one-line "watching for" summary, nothing else.

---

## The setup wizard (one time per routine)

A "routine" is one saved set of the answers below: five targeting answers (Steps 1 to 5) plus how it runs (Step 6). The user fills it in once, you save it, and every day after that the run is one command.

Run the wizard when there is no saved routine, or when the user wants to change one. Ask the blocks below, pre-fill the defaults shown, and let the user call out only what they want to change. Then play it all back in one short paragraph and get a yes before saving.

**Only Step 1 (the signals) needs a real choice from the operator.** Steps 2 to 6 each have a sensible default (for Step 6 the default is Supervised), so offer the default in plain words and let the operator just say *"that's fine."* Keep the whole wizard to a couple of minutes. Never make them answer something they do not care about, take the default and move on.

### Step 1: Which signals (the recent, specific things that make a company worth reaching out to right now)

**This is the only step that takes real thought, so make it a pick-list, not an essay question.** Show the operator the menu below, let them pick by number or describe their own, and you do all the technical work (the search terms, where to look) silently. The operator should never see or write a search term.

Present it exactly like this, in plain words:

> Here are signals I can watch for. Pick the ones you want (just give me the numbers), and tell me if you want to add your own:
>
> 1. **Just launched a partner programme** (a partner, channel, reseller, or affiliate programme)
> 2. **Hiring a PR or communications lead** (PR Director, Head of Comms, VP Communications)
> 3. **Hiring a partnerships lead** (Head of Partnerships, VP Partnerships, Head of Channel)
> 4. **Just rebranded** (new name, new look, relaunch)
> 5. **Just raised funding** (seed, Series A and up)
> 6. **Just launched a new product** (a launch worth getting press for)
> 7. **Just opened a new office or market** (new country, new region)
>
> Or describe your own in a sentence, like *"companies that just won an award,"* and I'll set it up.

Then capture two more things in plain terms, offering the defaults so they can just say "those are fine":

- **How recent** an event must be to count (default: the last 14 days). Older than that and the hook is stale.
- **How many companies a day** you want (default: at least 20).

Handle their answer for them:

- Turn each picked or described signal into a working signal (a plain label, where to look, and the search terms behind it). **You write the search terms; never ask the operator for them and never show them the JSON.**
- The signals run as a **waterfall**, best first: each day you work the top signal first and drop to the next only if the day is thin. Ask the operator for their preferred order in plain words (*"which matters most?"*), or offer a sensible order and let them confirm.
- The operator can add, remove, reorder, or reword signals at any time (see "Change it" above). Do not invent signals they did not ask for, and do not quietly drop ones they did.

### Step 2: What type of company

The qualifying rule a company must pass before you spend any credits finding people inside it. Capture in plain terms:

- **What kind of company** (for example B2B SaaS with a product worth partnering around, a platform with an app marketplace, a tech vendor that sells through channel).
- **Size** band if they want one (employees min to max).
- **Geography** if they want one (countries).
- **A self-check** if useful (must have a partnerships or integrations page, must sell B2B, must have a product not just a service).
- **Exclusions** (company types or sectors to leave out).

This is judgement that belongs to the user. Ask, do not guess. Note that a partner-programme launch is already a strong product-and-channel signal, so the company-type rule is mostly there to drop obvious non-fits.

**Ask it like this:** *"What kind of company should count? My default is B2B companies with a real product worth partnering around. Want me to add a size range or specific countries, or anything to leave out?"* If they say the default is fine, take it and move on.

### Step 3: Which decision-makers (the Qwintiq decision-maker finder)

The exact roles to pull inside each qualifying company, which the AI Ark people search (Qwintiq's decision-maker finder) will look for. Sensible default set for partner/PR outreach, for the user to confirm or change:

- Head of Partnerships, VP Partnerships, Director of Partnerships, Head of Channel (the partnerships buyer).
- Head of PR, Communications Director, Head of Communications (the comms buyer, when the PR-hire signal fired).
- Founder, CEO, CMO (the senior sponsor at smaller companies).

Write these down as concrete roles. You translate them into AI Ark's dials at run time (see Step 3 of the daily run). Capture how many people per company is enough (default: up to 3) and whether to stay LinkedIn-only (default: yes, for Lemlist's LinkedIn steps).

**Ask it like this:** *"Inside each company, who should I reach out to? My default is the partnerships and PR leads, plus the founder or CEO at smaller companies. Happy with that, or change it?"* The operator just names roles in plain words, you turn them into the search behind the scenes.

### Step 4: How the icebreaker reads (what we found)

The opener always names the signal that surfaced the company, because that is the warm, true hook. Capture:

- **The anchor**: the signal itself (for example "Saw you just launched your partner programme, so wanted to reach out", or "Saw you are building out the partnerships team, so wanted to reach out").
- **Recency window** for any extra detail the icebreaker searches (default: last 3 months).
- **Off-limits**: never open on anything negative or sensitive (layoffs, lawsuits, scandals), even if public.
- **Fallback order** if the signal detail is thin: a real colleague already in the pulled list, then an honest role and company line. Never invent a fact or a name.

This is **qwintiq-icebreaker**'s job; this step just records the anchor and rules so the daily run can hand it the right brief.

**Ask it like this:** *"The opening line will mention whatever we found, for example 'Saw you just launched your partner programme, so wanted to reach out.' That work for you?"* This one is mostly automatic, so it is usually a quick yes.

### Step 5: Which Lemlist campaign

Where the finished people go. Capture the **campaign name** (you resolve it to its `cam_...` id at run time via **qwintiq-lemlist-upload**) and confirm it is the right one (draft or running, email-only / LinkedIn / multichannel). If the user has not picked one, list the Qwintiq campaigns and let them choose, or point them to duplicate a master template first (see qwintiq-lemlist-upload).

**Ask it like this:** *"Which Lemlist campaign should these people land in?"* If they are not sure of the name, list their Qwintiq campaigns and let them pick. If none is ready yet, offer to help them set one up first (qwintiq-lemlist-upload).

### Step 6: How it runs each day (Supervised or Autopilot)

This is the one HOW question, not a WHO or WHAT one: it sets what happens at the credit gate on every run. Capture it at creation (default Supervised) and let the user switch any time.

- **Supervised (default):** each day the routine does the free work, then stops in the chat to show the shortlist and the spend, and waits for the typed confirmation phrase before it pulls anyone or uploads. Pick this when the user wants to eyeball each batch.
- **Autopilot:** the user gives standing permission, once, to find the people and push them straight into the campaign on their own each day, with no daily stop. **Autopilot must have a daily credit cap** (ask for one, default 20), and it still posts a summary after every run. Pick this when the user trusts the signal and wants zero daily clicks.

**Ask it like this:** *"Last thing: each morning, do you want me to check with you before I spend any credits and upload (Supervised), or just find the people and load them into the campaign on my own, up to a daily limit (Autopilot)? Most people start Supervised and switch to Autopilot once they trust it."* Record `run_mode`, and for Autopilot record the `daily_credit_cap`.

### Save the routine

Once all six are confirmed:

1. **Give it a friendly name** the operator will recognise (for example "Partner and PR signals"). Ask if they want to name it, or suggest one. Use a clean lowercase file name derived from it for `<routine_id>` (for example `partner-and-pr-signals`), but refer to it by the friendly name in conversation.
2. **Read it back in plain English** before saving: the signals in order, the recency window, the daily target, the company rule, the roles, the campaign, and how it runs (Supervised, or Autopilot with its daily credit cap). Get a yes.
3. **Save** to `routines/<routine_id>.json` (schema in the Routine config section below). The operator never sees or edits this file.
4. **Tell them the three things they can now say**, in one short line:
   - Run it: *"run today's partner signals"*
   - See it: *"show me my partner routine"*
   - Change it: *"add / drop / reorder a signal,"* or any change in plain words.

If the operator asks to change anything later, edit the saved JSON for them, then read the updated routine back in plain English. Never hand them the file or ask them to edit it.

---

## The daily run

Once a routine is saved, each day runs in this order. Load `routines/<routine_id>.json` first. If no routine is saved yet, do not start a run and do not show an error: say so warmly and offer to set one up, for example *"You do not have a routine saved yet. Want me to set one up? It takes about two minutes."* Then run the wizard.

### Phase A: Find at least 20 companies (free)

Use web search to find companies matching the top signal within the recency window. Work the waterfall: top signal first, drop to the next ranked signal only if the day is thin. Keep going until you have **at least the target count** of distinct, in-window, on-sector companies (default 20), or you have exhausted fresh news for all signals (say so plainly if you fall short).

For each company, note the source and the one-line reason it qualified ("launched channel partner programme, press release, 3 days ago" / "hiring a Head of Partnerships, posted 5 days ago"). Skip duplicates, recycled old stories, and obvious out-of-sector noise.

This is **qwintiq-signals** Phase 1 behaviour. Keep the batch timely and sized to the target, not hundreds.

### Phase B: Resolve each company's website (free)

For each company, find its real website and clean domain (a quick web search usually does it). You need the bare domain because that is how AI Ark matches the company in Phase D. Confirm it is the right company, not a same-name business elsewhere. Drop any company whose domain you cannot confidently resolve, and tell the user which you dropped and why. (qwintiq-signals Phase 2.)

### Phase C: Qualify on company type (free, before any spend)

Apply the Step 2 company-type rule to each company using what you can see on the website and in public info. Keep only the clear passes; keep a one-line reason for each cut. Show the user the qualified shortlist (company, domain, why it qualified) and a count of how many you cut, before spending anything. Every company cut here is credits not wasted. (qwintiq-signals Phase 3. Use **lilly-lead-score** if you want a structured fit verdict on a borderline batch.)

### Phase D: Find the decision-makers (AI Ark, gated)

This is the Qwintiq decision-maker finder. Only now do you touch AI Ark. Full AI Ark mechanics, label resolution, the dials, and the per-record billing live in **qwintiq-list-building**'s `references/ai-ark-reference.md`; the same rules apply here.

**D.1 Map the Step 3 roles to AI Ark dials.** One people search ANDs seniority, department, and title together, so two different kinds of role usually need two counts you then add. For the partner/PR default set:

- Partnerships roles: `department = business_development` with `seniority = head, vp, director` (and `title = "partnerships"` or `"partner"` where the department dial is too broad). Channel roles: add `title = "channel"`.
- PR / comms roles: `title = "communications"` / `"public relations"` / `"PR"`, with `seniority = head, director, vp` (there is rarely a clean "PR" department, so lead with title).
- Senior sponsor: `seniority = founder, owner, c_suite` (Founder, CEO, CMO).

Match people to each company on its domain so they stay tied to the right company.

**D.2 Count first (cheap).** For the qualified companies, run AI Ark people counts for the mapped roles (one sample row each, read `totalElements`, about one credit per count). Sum the non-overlapping counts to get N, the number of people you would pull.

**D.3 Branch on the routine's run mode** (`run_mode` in the config).

*Supervised (default): present the gate and wait.* Quote the real number:

> I found about **[N]** decision-makers across the **[M]** qualifying companies. Pulling them will use about **[N]** credits.
> To go ahead, type this exactly:
> **`I confirm to export this and use [N] amount of credits`**

Wait for the exact phrase (THE ONE RULE). If they want a smaller batch (top companies only, or one role type), recompute N and re-quote the sentence.

*Autopilot: do not stop, apply the cap.* Compare N to the routine's `daily_credit_cap`. If N is at or under the cap, pull all N. If N is over the cap, pull up to the cap (best companies first) and note the remainder for the summary. Never exceed the cap, and never silently raise it. The standing permission plus the cap is the authorization, so no typed phrase is needed. If an Autopilot routine somehow has no cap saved, do not pull: fall back to Supervised and ask.

**D.4 Pull** up to the agreed number (Supervised: the confirmed N; Autopilot: the smaller of N and the cap), never more. De-duplicate by person and by company. Keep LinkedIn-only (skip email enrichment) unless the user separately confirmed an email pull with its own gate. Cap at the Step 3 max-per-company.

### Phase E: Write the icebreaker (free)

Hand the pulled list to **qwintiq-icebreaker** with the Step 4 brief. The signal you already found in Phase A is the anchor, so most openers write straight from it ("Saw you just launched your partner programme, so wanted to reach out"). For any person where the anchor detail is thin, icebreaker falls back to a real colleague already in this same pulled list, then to an honest role and company line. Never fabricate. Show each finished line with its source (signal / colleague / fallback) so the user can trust it.

If the message sequence itself is not written yet, run **qwintiq-copywriter** to write it, passing the icebreaker as the `[Icebreaker]`.

### Phase F: Push into the Lemlist campaign

Hand the finished people to **qwintiq-lemlist-upload** with the Step 5 campaign:

- Resolve the campaign name to its `cam_...` id and confirm name, id, and status (draft / running, and whether it auto-launches) back to the user.
- Map each person into a lead: `linkedinUrl` (and `email` if you pulled and verified one), `firstName`, `lastName`, `companyName`, `jobTitle`, `icebreaker`, plus any custom variables the copy uses.
- Trial 1 to 3 leads first, confirm the echo, then push the rest with `?deduplicate=true`.
- Report the tally and remind the user whether the campaign is already sending (auto-launch) or whether they launch it in the Lemlist UI.

Never message a real prospect during a test: use a draft / paused campaign or a dummy lead, confirmed with the user (qwintiq-lemlist-upload's rules).

### End-of-run summary

Give the user a short, plain summary: how many companies found, how many qualified, how many people pulled, how many credits used, how many icebreakers by source, and how many leads landed in which campaign. Note any company you fell short on (for example, if the day was thin and you found fewer than the target).

---

## Routine config (saved per routine)

Save to `~/.claude/skills/qwintiq-partner-signals/routines/<routine_id>.json`. The default partner/PR routine ships in this folder as `qwintiq-partner-pr-signals.json`; the wizard fills the user-specific blanks (company type, exact decision-maker titles, the Lemlist campaign, and the run mode: `run_mode` is `supervised` by default, or `autopilot` with a required `daily_credit_cap`).

```json
{
  "routine_id": "qwintiq-partner-pr-signals",
  "routine_name": "Partner-programme and PR/partnerships hiring signals",
  "client": "Qwintiq",
  "created_at": "2026-06-23",
  "run_mode": "supervised",
  "daily_credit_cap": null,

  "signals": {
    "recency_days": 14,
    "target_count": 20,
    "ranked": [
      {
        "id": "partner-programme-launch",
        "label": "Just launched a partner / channel / reseller / affiliate programme",
        "where": "news, press releases, company blog",
        "search_terms": [
          "launches partner program", "announces partner programme",
          "new channel partner program", "launches reseller program",
          "affiliate program launch", "partner ecosystem launch",
          "introduces partner program"
        ]
      },
      {
        "id": "hiring-pr-director",
        "label": "Hiring a PR Director or comms lead",
        "where": "job posts, hiring announcements",
        "search_terms": [
          "hiring PR Director", "Head of Communications job",
          "VP Communications hiring", "Director of Public Relations opening",
          "Head of PR vacancy", "Director of Communications role"
        ]
      },
      {
        "id": "hiring-partnerships-lead",
        "label": "Hiring a Head of Partnerships or partnerships lead",
        "where": "job posts, hiring announcements",
        "search_terms": [
          "hiring Head of Partnerships", "VP Partnerships job",
          "Director of Partnerships opening", "Head of Channel hiring",
          "Partnerships Manager vacancy", "Partnerships Lead role"
        ]
      }
    ]
  },

  "company_type": {
    "note": "Filled in by the wizard. The qualifying rule a company must pass before any credit spend.",
    "description": null,
    "size_min": null,
    "size_max": null,
    "countries": [],
    "self_check": null,
    "exclusions": []
  },

  "decision_makers": {
    "note": "Default partner/PR role set. Wizard confirms or changes before first run.",
    "target_roles": [
      "Head of Partnerships", "VP Partnerships", "Director of Partnerships", "Head of Channel",
      "Head of PR", "Communications Director", "Head of Communications",
      "Founder", "CEO", "CMO"
    ],
    "ai_ark_dials_hint": {
      "partnerships": {"department": ["business_development"], "seniority": ["head","vp","director"], "title": ["partnerships","partner","channel"]},
      "pr_comms": {"title": ["communications","public relations","PR"], "seniority": ["head","director","vp"]},
      "senior_sponsor": {"seniority": ["founder","owner","c_suite"]}
    },
    "max_per_company": 3,
    "linkedin_only": true
  },

  "icebreaker": {
    "anchor": "the signal that surfaced the company (partner-programme launch, or the PR / partnerships hire)",
    "recency_months": 3,
    "off_limits": ["layoffs", "lawsuits", "scandals", "anything negative or sensitive"],
    "fallback_order": ["signal", "colleague-in-list", "honest role/company line"]
  },

  "lemlist": {
    "note": "Filled in by the wizard.",
    "campaign_name": null,
    "campaign_id": null,
    "channel": "multichannel (email + LinkedIn)"
  }
}
```

---

## Running it day to day

(The plain-English version of this, for the operator, is in "Your routine, in plain terms" above. This is the operational detail.)

- Each morning, the user says `run today's partner signals` (or `/qwintiq-partner-signals`). You load the saved routine and start at Phase A, stopping at the gate in Phase D.
- If they instead say *"show me my partner routine"* or *"what signals am I tracking?"*, do not start a run: print the saved routine back in plain English (signals in order, recency, daily target, company rule, roles, campaign) and stop.
- If they ask to change anything (*"add a signal,"* *"look back 30 days,"* *"switch the campaign"*), edit the saved JSON for them, read the change back, and stop. Do not make them touch the file.
- Keep each day's batch timely and sized to the target. Freshness is the whole value of a signal.
- If a day is thin on the top signal, drop to the next ranked signal before widening anything.
- A scheduled, unattended run follows the routine's run mode. **Supervised:** it does the free work, then stops and waits for the typed confirmation before pulling anyone (it simply holds until the user confirms). **Autopilot:** it pulls and pushes on its own up to the daily credit cap, then posts the end-of-run summary. The cap is a hard ceiling, never exceed it.

---

## Guardrails (the short version)

1. **People-credits are always the user's call.** Supervised pulls need the exact typed confirmation phrase and correct number; Autopilot pulls require a routine explicitly set to autopilot with a daily credit cap, and never exceed that cap. (THE ONE RULE.)
2. **Find, resolve, and qualify are free and allowed; pulling people is gated.** Count with one sample row; never count by pulling everyone.
3. **The user defines all five targeting inputs and the run mode.** Confirm them and save the routine before running. Claude does not decide what counts as a signal, a fit, the right roles, or whether to run on Autopilot.
4. **Qualify before you spend.** Cut bad-fit companies on free web info first.
5. **At least 20 qualifying companies is the daily target.** Work the signal waterfall to reach it; say so plainly if a thin day falls short.
6. **Icebreakers are true or blank, never invented.** Anchor on the found signal; fall back only to a real in-list colleague, then an honest line.
7. **AI Ark is the data source for finding people** (Qwintiq is AI-Ark-native). Mechanics live in qwintiq-list-building's AI Ark reference.
8. **Lemlist is the destination** (email + LinkedIn). Trial first, confirm campaign name and status, never message a real prospect during a test.
9. **Avoid email enrichment during testing.** LinkedIn-only for Lemlist unless the user confirms an email pull with its own gate.
10. **Plain English with the user. No jargon, no raw output, no em dashes.**
11. **Self-contained.** Assume a fresh Claude: if no routine is saved, run the wizard; re-confirm the campaign every run, and either get the typed credit confirmation (Supervised) or respect the saved daily cap (Autopilot).

---

## Related Qwintiq skills

- **qwintiq-signals**: the generic version of this routine (any user-defined signal). This skill is the partner/PR specialisation with the icebreaker and Lemlist steps built into one routine.
- **qwintiq-list-building**: AI Ark market sizing and list building, and the home of the AI Ark reference used in Phase D.
- **qwintiq-icebreaker**: writes the Phase E opening line.
- **qwintiq-copywriter**: writes the message sequence.
- **qwintiq-lemlist-upload**: the Phase F push into the Lemlist campaign.
- **lilly-lead-score**: optional structured fit verdict for borderline companies in Phase C.
