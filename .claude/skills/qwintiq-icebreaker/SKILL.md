---
name: qwintiq-icebreaker
description: >-
  Writes the single personalised opening line (the "icebreaker") that sits at the top of a
  Qwintiq partnership message. The user states what to look for ONCE, in plain words, by picking
  from a short menu of FOUR website/LinkedIn detection angles built for partnership outreach:
  (1) an explicit partner or referral invite on their site, (2) a client vertical that overlaps
  ours, (3) a case-study "inflection moment" where PR could have helped, and (4) a services gap
  where they offer SEO / paid / content but NOT PR. That choice (which angles, in what order,
  plus recency, off-limits, and the backup) is saved as a named "setup" the user can run, view,
  and edit any time in plain words, never by touching a file. Each run loads the saved setup,
  confirms it, then writes one line per person: the first angle that finds something real wins;
  if none do it falls back to a real colleague already in the user's list, then to an honest,
  flagged plain line. It never invents a person or a fact. Use this to personalise the first line
  of partnership outreach, fill an {{icebreaker}} field for Lemlist, or add a warm opener to a
  list of partners. Trigger on "write icebreakers", "set up my icebreakers", "personalise the
  opener", "find a hook for these people", "show me my icebreaker setup", "change my icebreaker
  angles", "add an angle", or any request to top a partnership message with a personal note. It
  NEVER makes up a fact, and it never spends AI Ark credits without the confirmation phrase.
---

# Qwintiq Icebreaker

This skill writes the one personalised line that goes at the very top of a partnership message: the "icebreaker". A good icebreaker shows the person you actually looked at them before reaching out. A bad one (or a made-up one) does more harm than no personalisation at all.

Qwintiq's outreach is **partnership / referral** outreach: the goal of the opener is to start a partnership conversation, not to pitch a product. So the icebreaker is built from things you can see on a prospect's **website or LinkedIn** that say "there is a reason for us to work together".

It works in a confirmed order:

1. **The four detection angles** (primary): look at the prospect's site / LinkedIn and try each of the four angles below in the order the user confirmed at setup. The first angle that finds something real wins.
2. **A real colleague** (backup): if none of the four fire, mention a colleague, but only a colleague who is already in the user's list, so the name is always real.
3. **A safe, honest fallback** (last resort): if there is no colleague either, write a neutral line that is still true, and flag it so the user knows it was not personalised.

It feeds straight into the rest of the system: the line it produces is the `[Icebreaker]` you give to **qwintiq-copywriter**, and the `{{icebreaker}}` value you load into **qwintiq-lemlist-upload**.

> This framework is still being refined by Qwintiq, so it is built to be edited. The four angles, their detection words, the verticals, the services list, and the order all live in the user's **saved setup** and can be changed any time in plain words (see "Your icebreaker setup" below). Load the saved setup and confirm it on every run; never hardcode the order or the lists into your head.

---

## THE GOLDEN RULE: never make anything up

The whole point of an icebreaker is that it is true and specific. If you guess, you will eventually send "saw you just raised a Series B" to someone who never raised anything, and that one line burns the relationship and the client's name.

So:

- **Only state something you actually saw** on the prospect's website / LinkedIn, or a colleague name you can see in the user's list. Nothing else.
- If you are not sure a fact is about *this* exact person or company, treat it as not found and move down the order.
- If you find nothing solid, say so (use the honest fallback and flag it). Never pad a line to look personalised.

This rule outranks "fill every row". A blank-but-honest opener is fine. A confident wrong one is not.

---

## How to talk to the user

The person running this is a business operator, not an engineer. Keep it plain:

- Say "the hook" or "the opening line", not "the personalisation variable".
- Say "I looked at their site and saw / didn't see...", not "the detection query returned null".
- Show them the finished line in quotes, and where each one came from (which angle, a colleague, or the fallback), so they can sanity-check before it goes out.
- Never paste raw page source, JSON, or keyword-match logs at them.

---

## Your icebreaker setup, in plain terms (make it, run it, change it)

A **setup** is just your saved choice of what the AI looks for and in what order, with a friendly name. You state it once in plain words. After that, writing icebreakers is one sentence, and changing what it looks for is one sentence. **You never open a file, write a single detection word, or touch any settings yourself. Claude does all of that for you.**

### 1. Make it (the first time)

Say: *"Set up my icebreakers."*

Claude shows you a short menu of things it can look for on a prospect's website or LinkedIn (the "angles"), and you just pick:

- Pick the ones you want by number, in the order you want them tried, for example *"use 1, 4, then 2."* The first angle it finds something real for wins.
- Or describe your own in a sentence, for example *"also look for companies that just won an award."* Claude turns your sentence into a working angle. You do not write detection words, Claude does that quietly in the background.

Claude reads your setup back in plain English and saves it under a name you will recognise (for example **"Qwintiq partnership icebreakers"**). Done.

### 2. Run it (every time you personalise a list)

Say: *"Write icebreakers for this list."*

Claude loads your saved setup, shows it for a quick *"still good?"*, then writes one line per person, trying your angles in order. If it finds nothing for someone, it mentions a real colleague already in your list, and only then an honest flagged line. It never makes anything up.

### 3. See what it is set to

Say: *"Show me my icebreaker setup"* or *"What are my icebreaker angles?"*

Claude prints your setup back in plain English: the angles in order, how recent a detail must be, what is off-limits, and your backup. No file, no code.

### 4. Change it (any time)

Just say what you want in plain words. Claude updates the saved setup and reads the change back. Common changes:

| You say | What happens |
|---|---|
| *"Put the services-gap angle first."* | Claude reorders the angles. |
| *"Drop the shared-industry angle."* | Claude removes it. |
| *"Add an angle for companies that just won an award."* | Claude adds it and asks where it should sit. |
| *"Only count things from the last 3 months."* | Claude tightens the recency window. |
| *"Add fintech and logistics to the industries we share."* | Claude extends that angle's list. |
| *"If you find nothing, leave it blank instead of a fallback line."* | Claude changes the backup. |

After any change, Claude reads the whole setup back so you can see it landed right. To start fresh, say *"redo my icebreaker setup."*

### Where it lives (you do not need this, but here it is)

Your setup is saved as a named setup **inside Claude**, so any new chat finds it by name. You can have more than one (say *"what icebreaker setups do I have?"* to list them, and name a new one when you make it). The technical copy sits at `~/.claude/skills/qwintiq-icebreaker/setups/<name>.json`, but **you never need to open that.** Every change is a sentence to Claude.

### The plain-English read-back (what "show me my setup" prints)

Whenever you save a setup, change one, or the user asks to see one, render it in this friendly shape. Never show JSON, file paths, or detection words.

> **Qwintiq partnership icebreakers** (your saved setup)
>
> **Looks for, in order:**
> 1. They ask for partners or referrals on their site
> 2. A client industry we also work in
> 3. A case-study moment (a client launched, raised, or rebranded)
> 4. A gap where they do SEO / paid / content but not PR
>
> **How recent a detail must be:** the last 6 months
> **Never opens on:** layoffs, lawsuits, or anything negative
> **If it finds nothing:** mention a real colleague in your list, then an honest flagged line
>
> Want to change anything? Just tell me, for example *"put the services gap first"* or *"add fintech to the industries."*

If part of the setup is not chosen yet, show that line as **"not set, want to pick one?"** rather than hiding it. To answer *"what icebreaker setups do I have?"*, read the `setups/` folder and list each setup's friendly name and its one-line "looks for" summary.

---

## Phase 0: Your setup (load and confirm, or build it the first time)

This is the most important step. Before you look at a single prospect, get the setup in front of the user and get a yes. There are two cases.

**If the user has a saved setup** (a file in `setups/`): load it, show the plain-English read-back from "Your icebreaker setup" above, and ask one question: *"This is your saved setup. Still good, or do you want to change anything (reorder, drop, or add an angle, change the recency or the backup)?"* Apply any change they ask for, re-show the read-back, save, then proceed. Do not re-ask the whole thing from scratch; the saved setup is the starting point.

**If there is no saved setup** (first time, or they said "set up my icebreakers" / "redo my setup"): build one. The block below is your menu. Show it, let the user pick the angles and the order by number or describe their own, confirm the recency, off-limits, and backup, then save it (see "Save the setup" after the block). You hold the detection words; the user never types them.

```
Skill: qwintiq-icebreaker  —  setup wizard (runs every time)

What I'll do: for each person on your list I'll look at their website (and LinkedIn
where I can see it) and try each angle below in order. The first angle I find something
real for wins. If I find nothing for any of them, I mention a real colleague who is
already on your list. If there's no colleague either, I write an honest plain line and
flag it, so nothing is ever made up.

ANGLE ORDER (confirm or reorder):
  1. Partner / referral invite  — they openly ask for partners or referrals on their site
                                   (why: fastest to activate, they already want this)
  2. Shared client vertical     — they work in an industry we also work in
                                   (why: shows overlapping client potential)
  3. Case-study moment          — a client in their case studies hit a launch / raise / rebrand
                                   (why: shows exactly where we'd add value)
  4. Services gap (no PR)        — they offer SEO / paid / content but NOT PR
                                   (why: shows the gap we fill)
  ----- backups (always last, in this order) -----
  5. Colleague mention          — name a real colleague who is already on your list
  6. Honest plain line          — true, neutral, flagged as not personalised

RECENCY (for the time-sensitive angles, e.g. a case-study moment or a new hire):
  within the last {6} months. Older than that reads as stale.

OFF-LIMITS (never open on these, even if public):
  layoffs, lawsuits, scandals, closures, deaths, anything negative or sensitive.

IF NO COLLEAGUE EITHER:  {write an honest flagged line}  |  {leave blank for you to fill}

WHAT I LOOK FOR IN EACH ANGLE (editable — call out anything you want changed):
  1. Partner/referral words: "Partners", "Partner with us", "Become a partner",
     "Referral Program", "Alliances", a partner form or partner email,
     "open to partnerships / collaborations".
  2. Shared verticals: Tech, Software, SaaS, Healthcare, Medical, Health, Wellness,
     Beauty, Skincare, Consumer, E-commerce, Apparel, Fashion, Travel, Lifestyle,
     Professional services, B2B.
  3. Inflection words in case studies / testimonials: "launch", "fundraise",
     "funding", "rebrand", "new product".
  4. Adjacent services (the gap fires if these appear but "PR" / "Public Relations"
     does NOT): SEO, Organic search, Content strategy, Conversion optimization,
     GEO / Generative engine optimization, Technical SEO, Paid media, Paid search,
     Paid social.

Want to add, drop, or reorder any of these?
```

### Save the setup

Once the user is happy with the angles, the order, the recency, the off-limits, and the backup:

1. **Give it a friendly name** they will recognise (suggest "Qwintiq partnership icebreakers"). Use a clean lowercase file name for `<setup_id>`.
2. **Read it back in plain English** one last time (the read-back template in "Your icebreaker setup" above) and get a yes.
3. **Save** to `setups/<setup_id>.json` (schema in "Your setups" below). The user never sees or edits this file.
4. **Tell them what they can now say**, in one line: run it (*"write icebreakers for this list"*), see it (*"show me my icebreaker setup"*), change it (*"reorder / drop / add an angle,"* or any change in plain words).

**Treat any change as a hard override.** If the user reorders the angles, edits a word list, swaps the industries, or changes the backup, apply it to the saved setup, re-show the read-back, and save before running.

---

## Phase 1: Take the list

You need the list the user is personalising. For each row you need at least:

- **Person's name** and **job title**.
- **Company name** and the **company website** (and LinkedIn if you have it). The website is what the four angles are read from, so a row with no website can only reach the colleague backup or the fallback.
- Any **colleagues** in the same list at the same company (you will use these for the backup, so keep the whole list in view, not one row at a time).

If a row is missing the basics (no name, no company), flag it and skip it rather than guessing.

---

## Phase 2: Run the four detection angles (primary)

For each person, look at the prospect's site and LinkedIn and walk the **confirmed** angle order. The first angle that finds something real wins; stop there and write that line. Do not keep going to find a "better" angle, and do not stack two angles into one opener.

**How to look (per company, once):**

- Fetch the company **homepage** first. From it, find and open the most relevant of these pages where they exist: a **Partners / Partnerships / Referral** page, a **Services / What we do** page, and a **Case studies / Work / Clients** page. One to three page reads per company is plenty.
- Read for the angle's detection words from the wizard. A match must be genuinely about **this** company (not a generic footer link, not a third party).
- Where you can see the company or person **LinkedIn** (from the list, an export, or cached data), use it the same way, especially for angle 1 (a "we're hiring partners / open to collaborations" post) and angle 3 (a client win post).
- Respect the recency window and the off-limits list from Phase 0.

Keep every opener to **one short, natural line** that does two things only: name the thing you saw, and give a light reason for reaching out. The actual PR / partnership offer goes in the message body (qwintiq-copywriter handles that), never in the opener. Leave `{{firstName}}` and `{{companyName}}` as merge fields if the line will be loaded into Lemlist; write the specific detail (the vertical, the service, the client name, the inflection) in plain text.

### Angle 1 — Partner / referral invite

**Detect (website / LinkedIn):** "Partners", "Partner with us", "Become a partner", "Referral Program", "Alliances", a partner application form or a partners@ email, "open to partnerships / collaborations".

**Why:** fastest time-to-activation. They are already telling the world they want this, so the opener just points at it.

**Write (examples):**
- *"I saw your referral program page on your site, so wanted to reach out."*
- *"Saw {{companyName}} has a partner program, so thought I'd reach out."*

If there is no partner / referral signal: skip to angle 2.

### Angle 2 — Shared client vertical

**Detect (website):** the prospect names a client industry that is on our verticals list: Tech, Software, SaaS, Healthcare, Medical, Health, Wellness, Beauty, Skincare, Consumer, E-commerce, Apparel, Fashion, Travel, Lifestyle, Professional services, B2B.

**Why:** shows we have overlapping client potential, so a partnership has a natural fit.

**Write (example):**
- *"I was researching {{companyName}} and saw you work with [vertical] brands too, so wanted to reach out."*

Name the **specific** vertical you actually saw (e.g. "skincare", "SaaS", "travel"), not the word "vertical". If they list several, pick the one with the strongest overlap. If no overlapping vertical is visible: skip to angle 3.

### Angle 3 — Case-study inflection moment

**Detect (website case studies / testimonials):** a named client that went through "launch", "fundraise", "funding", "rebrand", or "new product".

**Why:** shows exactly where PR could have added value, so it sets up the conversation naturally.

**Write (example, kept to one light line):**
- *"I was going through your case studies and saw [client name] went through a [inflection], so wanted to reach out."*

Name the real client and the real moment from the case study. Keep the opener to the observation plus the light reason. The point about helping similar brands "gain even more visibility with PR" is the **offer**, so it belongs in the message body, not the opener. If no inflection moment is visible in a case study: skip to angle 4.

### Angle 4 — Services gap (no PR)

**Detect (website):** they offer adjacent services (SEO, Organic search, Content strategy, Conversion optimization, GEO / Generative engine optimization, Technical SEO, Paid media, Paid search, Paid social) **but the site does NOT mention "PR" or "Public Relations"**. Both halves must be true: the adjacent services are present AND PR is absent.

**Why:** shows a clear gap in their offering that we fill.

**Write (example):**
- *"I was researching {{companyName}} and saw you do [service 1], [service 2] and [service 3] among other things, but not PR. Is that right?"*

Name three real services you actually saw. The soft "Is that right?" is a deliberate, low-pressure open that invites a reply; keep it, but do not add a pitch on top of it. If PR / Public Relations IS mentioned on their site, this angle does **not** fire (there is no gap); skip to the colleague backup.

> Note on the house style: Qwintiq openers stay light (an observation plus a reason to reach out). Angles 2, 3 and 4 each hint at the reason we'd partner, which is fine, but never stack the full offer into the opener. If an angle's natural wording starts to sound like a pitch, trim it back to the observation and let qwintiq-copywriter carry the offer in the body.

---

## Phase 3: The colleague backup (only if the colleague is in the list)

If none of the four angles fired, you may open by mentioning a **colleague**, but only under a strict condition that protects the GOLDEN RULE:

- **The colleague must already appear in the user's list** (the same export you are personalising), at the **same company**. You are not allowed to go and find a new name, and you are never allowed to invent one. If the list has only one person at that company, there is no colleague to use, so skip to Phase 4.
- Pick the most senior or most relevant colleague at that company from the list.

Write a simple, honest line that references the real colleague:

- *"Saw you and {{colleagueFirstName}} both look after [area] at {{companyName}}, so wanted to reach out."*
- *"Came across {{companyName}} while looking at {{colleagueFirstName}}'s team, so thought I'd reach out to you directly."*

Keep it to one line, same as the angle openers. Do not imply you have spoken to the colleague unless that is true.

(Optional, only if the user explicitly asks and accepts the cost: you may run an AI Ark people lookup to find a colleague who is not already in the list. That spends credits, so it is gated, see the credits note below. Default behaviour is list-only and free.)

---

## Phase 4: The honest fallback (last resort)

If none of the four angles fired and there is no colleague in the list, do **not** fabricate. Follow the backup choice the user made at the wizard:

- **Honest flagged line (default):** a safe role / company line that is still true, e.g. *"Came across {{companyName}} and the work you're doing as {{jobTitle}}, so wanted to reach out."* Mark the row `FALLBACK` so the user can see it was not personalised.
- **Leave blank:** if the user chose this at the wizard, leave the icebreaker empty and mark the row `NO HOOK FOUND`.

Tell the user how many rows ended on the fallback. A high fallback rate usually means the angles or word lists are too tight for this list; suggest they loosen a list or reorder at Phase 0 and re-run.

---

## Output: hand off the lines

Give the user, per person:

1. The finished **icebreaker line** (in quotes).
2. **Where it came from**: `partner/referral`, `vertical`, `case-study`, `services-gap`, `colleague`, or `fallback`. This is the trust check, keep it visible.

Present it as a clean table (name, company, icebreaker, source), or write the line back into the list column the user is filling (commonly `Icebreaker` or `{{icebreaker}}`). Also show the **angle distribution** (e.g. "8 partner/referral, 5 vertical, 6 case-study, 9 services-gap, 4 colleague, 3 fallback") so the user can see how the list broke down and whether to retune the angles.

Then point them to the next step:

- To turn these into full messages, run **qwintiq-copywriter** and give it this line as the `[Icebreaker]`.
- To load people with no email straight into LinkedIn outreach, run **qwintiq-lemlist-upload** and map this line to the `{{icebreaker}}` field.

---

## A note on credits

Looking at a prospect's website is free, and reading colleagues from a list you already exported is free, so the normal path costs nothing. The **only** thing that costs AI Ark credits is going out to *find* a new colleague who is not in the list (the optional bit in Phase 3). Treat any AI Ark people pull as a spend and gate it: quote the number and have the user type, exactly:

> `I confirm to export this and use X amount of credits`

Do not run that lookup on "yes" or "go ahead"; wait for the phrase. Everything else in this skill is free, so use it freely.

---

## Your setups (saved config)

Save to `~/.claude/skills/qwintiq-icebreaker/setups/<setup_id>.json`. The default ships as `qwintiq-default-icebreaker.json`; copy and adjust it when a user wants a different angle order or different lists. The user changes it only through plain-word requests (see "Your icebreaker setup" above), never by hand.

```json
{
  "setup_id": "qwintiq-default-icebreaker",
  "setup_name": "Qwintiq partnership icebreakers",
  "client": "Qwintiq",
  "angles": {
    "ranked": [
      {"id": "partner-referral-invite", "label": "They ask for partners or referrals on their site",
       "look_at": "website, LinkedIn",
       "detection_words": ["Partners","Partner with us","Become a partner","Referral Program","Alliances","partner form","partners@ email","open to partnerships","open to collaborations"]},
      {"id": "shared-client-vertical", "label": "They work in an industry we also work in",
       "look_at": "website",
       "detection_words": ["Tech","Software","SaaS","Healthcare","Medical","Health","Wellness","Beauty","Skincare","Consumer","E-commerce","Apparel","Fashion","Travel","Lifestyle","Professional services","B2B"]},
      {"id": "case-study-inflection", "label": "A client in their case studies hit a launch, raise, or rebrand",
       "look_at": "website case studies, testimonials",
       "detection_words": ["launch","fundraise","funding","rebrand","new product"]},
      {"id": "services-gap-no-pr", "label": "They offer SEO / paid / content but NOT PR",
       "look_at": "website services pages",
       "detection_words_present": ["SEO","Organic search","Content strategy","Conversion optimization","GEO","Generative engine optimization","Technical SEO","Paid media","Paid search","Paid social"],
       "detection_words_absent": ["PR","Public Relations"]}
    ]
  },
  "recency_months": 6,
  "off_limits": ["layoffs","lawsuits","scandals","closures","deaths","anything negative or sensitive"],
  "backups": {"order": ["colleague-in-list","honest-flagged-line"], "if_no_colleague": "honest-flagged-line"}
}
```

The order of `angles.ranked` is the order the angles are tried. Every edit (reorder, drop, add, extend a list, change recency or backup) is a plain-word request you apply here, then read back. Each saved setup is self-contained; a user can keep several (for example a tighter or a broader angle set) and name each one.

---

## Guardrails (the short version)

1. **Never fabricate.** Only real, seen facts and real, in-list colleague names. (See THE GOLDEN RULE.)
2. **Load the saved setup and confirm it every run.** Show the plain-English read-back and let the user adjust before looking anyone up. Do not re-ask from scratch; the saved setup is the starting point. If there is no setup yet, build one from the menu (Phase 0). The framework keeps changing, so always confirm, but never make the user re-state what is already saved.
3. **Four angles first, real colleague second, honest fallback last.** Never skip straight to a made-up hook, and never reorder the backups (colleague always before fallback).
4. **First angle to fire wins.** Walk the confirmed order, stop at the first real match, never stack two angles into one opener.
5. **Angle 4 needs both halves.** The services gap only fires when adjacent services are present AND PR / Public Relations is absent. If PR is on their site, it does not fire.
6. **Colleague backup is list-only** by default. A fresh AI Ark lookup is optional, costs credits, and is gated by the confirmation phrase.
7. **One line only.** Observation plus a light reason to reach out. No pitch in the opener; the offer lives in the message body (qwintiq-copywriter handles that).
8. **Never open on anything negative or sensitive**, even if public.
9. **Respect recency.** Time-sensitive angles (case-study moment, a hire) only fire inside the window confirmed at the wizard.
10. **Always show the source of each line** (which angle / colleague / fallback) so the user can trust it.
11. **Plain English with the user. No jargon, no raw page source, no em dashes.**
12. **Self-contained.** Assume a fresh Claude with no memory: load the saved setup (or build one from the menu if none exists), confirm it, and re-ask for the list each time.
