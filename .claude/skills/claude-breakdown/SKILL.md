---
name: claude-breakdown
description: "Build the client-facing 'Outbound Campaign Breakdown' lead-magnet: a polished Notion doc that maps the exact outbound campaigns Navreo would run for a named prospect, with a worked cold-email shown for each. Trigger on 'create a campaign breakdown for [prospect]', 'build the outbound breakdown doc', 'make the breakdown lead-magnet', '/claude-breakdown [prospect]'."
---

# claude-breakdown

## Purpose

Produce the **Outbound Campaign Breakdown** — a client-facing Notion document we send to a prospect as a lead-magnet. It shows the prospect the exact outbound campaigns we'd build for them, one section per campaign type, each with a plain-English explanation, a target table, a short Loom walkthrough, and a real example of the cold email we'd send.

This is a SALES ASSET the prospect reads. It is NOT an internal research doc. Everything in it is written to build trust and show competence, not to expose our tooling.

The gold-standard reference is the **"Outbound Campaign Breakdown Template (Expandin example)"** Notion page (ID `3756e755-98d9-8116-b1ba-d83300fc8bf4`). When in doubt about structure, tone, or formatting, match that page.

## When to trigger

- "Create a campaign breakdown for [prospect]"
- "Build the outbound breakdown doc for [prospect]"
- "Make the breakdown lead-magnet for [prospect]"
- "/claude-breakdown [prospect]"

Do NOT trigger for internal research (that's `loom-research`), for campaign ideation (`/lilly-strategy`), or for standalone copy (`/lilly-copywriter`). This skill assembles the client-facing deliverable on top of those.

## Hard constraints (never break)

1. **ZERO em-dashes.** Anywhere in the doc. Use commas, colons, periods, or parentheses. Hyphens and arrows are fine.
2. **Plain English, client-facing.** No jargon. Never write "TAM", "ICP", "lookalike search", "enrichment", "Prospeo", "Ocean", "AI Ark", "webhook", "filter", "DM", "signal probe", etc. Translate every mechanic into how-it-helps-you language.
3. **Hide internal mechanics, with ONE exception:** the AI Ark look-a-like link in §2 is shown to the prospect as a live "here's the list we built" link. Every other tool stays invisible.
4. **Exhibitor-only events.** §3 pulls EXHIBITORS, never attendees. Say so.
5. **Each email is a standalone, sendable email.** No `{{variables}}` left in brackets: every placeholder is filled with a concrete value. 45-70 word body (excluding greeting, sign-off, icebreaker), no spam words (free, trial, guaranteed, today, urgent, risk-free).

## Inputs

- **Prospect name + website** (required).
- **What we'd sell them / our offer** (required) — the outcome we promise, plus any risk reversal and case study. If unknown, ask.
- **Loom video links** (optional) — the template already contains the 5 standard campaign-type walkthrough videos, and they render correctly when you duplicate the page. KEEP them by default. Only swap a `<video>` block if the user supplies a prospect-specific Loom for that section. Never delete a video block or turn it into a text placeholder.

## Process

### Step 1 — Research with `loom-research`

Run `loom-research` for the prospect. It returns the 7 tasks that feed this doc:

| loom-research task | Feeds breakdown section |
|---|---|
| TASK 1 Company Overview | §1 What you do |
| TASK 2 ICP table | §1 targeting + persona names for emails |
| TASK 3 Named Clients + AI Ark look-a-like links | §2 Look-a-like lists |
| TASK 4 Upcoming Events (in-person, exhibitor-focused) | §3 Events |
| TASK 5 Hiring Signals | §4 Hiring |
| TASK 6 Top 10 Competitors by LinkedIn followers | §6 Competitor audiences |
| TASK 7 Sales Team Structure (Prospeo `/search-person`) | persona names + titles for icebreakers |

For §5 (other buying signals), you may ONLY use signals from the fixed list below. These are the only company signals we can actually retrieve, so NEVER invent a new signal type and NEVER promise a signal we cannot pull. Pick the 4-5 most relevant to the prospect's offer and reframe each one in the prospect's own language. The example counts in the table can be illustrative (flag them to the user), but the signal TYPES must come from this list:

1. **Raised new funding** (recently closed a round)
2. **New senior leader appointed** (a relevant C-level, VP, or Head just started)
3. **In the news** (announced an expansion, launch, partnership, or similar)
4. **Won a new key client or customer** (publicly announced)
5. **Opened a new office, location, or entity**
6. **Adopted a specific technology** (shows in their tech stack)

These map to what our data tools pull (`company_funding`, `company_key_execs`, `company_news`, `company_key_customers`, location/registry data, technology lookups), but surface them to the prospect in plain English only, never the field names. If a prospect's offer genuinely fits none of the six, say so rather than inventing a seventh.

### Step 2 — Gather social proof for the P.S. lines

Before writing any email, collect proof for the P.S. lines:
- WebFetch / WebSearch the prospect's site for real results (success rate, countries, industries, named clients).
- If the site is JS-rendered and returns nothing, use WebSearch summaries instead, and FLAG to the user that the figures came from search and should be confirmed before sending.
- One confirmed named client is enough to reuse across multiple P.S. lines (each email is seen by one prospect).
- Where no real number exists, a plausible fictitious result is acceptable as social proof, but tell the user which numbers are illustrative.

### Step 3 — Duplicate the template, THEN replace the text

**Always duplicate the example page first. Never build the structure from scratch.** The template already has every callout, table, video block, and divider formatted correctly, and those are fiddly to rebuild by hand. Duplicating is also the ONLY way the 5 walkthrough videos render correctly: they are real native Notion `<video>` blocks, and rebuilding from scratch (or pasting text in their place) flattens them into dead placeholders.

1. Duplicate the Expandin page (`3756e755-98d9-8116-b1ba-d83300fc8bf4`) with `notion-duplicate-page`. The duplicate is created async: it returns a `page_id` + `page_url`, and the child blocks populate after a short delay, so re-fetch the page before you start editing.
2. Rename the copy to `[Prospect] - Outbound Campaign Breakdown` (company name FIRST, e.g. `Rentalmatics - Outbound Campaign Breakdown`).
3. Move the copy into the **Bespoke Outreach** database with `notion-move-pages`, setting `new_parent` to `{"type": "database_id", "database_id": "3756e755-98d9-8059-8b11-c9692ce51802"}` (the database lives under Marketing; its title column is `Name`). EVERY breakdown doc must be created in this database, never left as a loose top-level page. Moving preserves the full body, including the native video blocks.
4. Replace each section's text on the copy, section by section, leaving the structure untouched. Whether you use `update_content` (in-place) or `replace_content` (whole-body), you MUST re-include every native block tag verbatim, especially the `<video src="...">` blocks. `replace_content` keeps a block native ONLY if its tag is present in the markdown you send: omit the tag and the block is lost.

**NEVER replace a `<video>` block with a text placeholder** (e.g. "🎥 Loom walkthrough to be recorded"). The template's 5 Looms ARE the correct, standard campaign-type walkthroughs, and they are confirmed to render correctly via duplication. KEEP them exactly as they are. There is one `<video>` at the top of each of §2-§6; preserve all five. The current template Loom URLs are:

| Section | Loom |
|---|---|
| §2 Look-a-likes | `https://www.loom.com/share/8e2f55b45e234b628cd9b8e7a9602846` |
| §3 Events | `https://www.loom.com/share/7728e428b4474d6f96e416bbca4b92e9` |
| §4 Hiring | `https://www.loom.com/share/08ce893c9b284f47a8664a230fba3fef` |
| §5 Data signals | `https://www.loom.com/share/326a356af613490fb6e66d2c9536f2a5` |
| §6 Competitors | `http://loom.com/share/116998ded83948dc8c1fe59ca33518a5?focus_title=1&muted=1&from_recorder=1` |

The template's structure (what you're replacing the text inside) is below. Sections §2-§6 each have: prose → table → Loom video → email callout.

```
> Here's the full breakdown we promised, mapping out exactly how we'd build your outbound and the campaigns we'd run.

*Prepared for [Prospect]*

---

## 1. Understanding your business

[1-2 plain-English sentences on what they do and who they sell to.]

[Table: | What you do | Who you sell to | Where you're growing |]

## 2. Building look-a-like lists of your best clients

[Plain-English: we take companies like your existing clients and find more that look just like them.]

[Table: | Client | What they do | The look-a-like list we built |]
  (the third column is the AI Ark link, shown as a markdown link "View the list")

[<video src="loom..."> ]

[<callout icon="✉️"> CASE STUDY email ]

## 3. Reaching the companies exhibiting at the events your buyers attend

We pull the exhibitor list from each one, match them to your decision-maker titles, and build a campaign timed around the event.

[Table: | Event | When | Where |  (5 in-person events) ]

[<video> ]

[<callout icon="✉️"> ONE-SENTENCE PUNCH email ]

## 4. Targeting companies hiring for roles that signal they need you

[Plain-English: when a company hires for X, it's a sign they're about to need what you do.]

[Table: | The hire | Why it's a buying signal |  (4 hiring signals) ]

[<video> ]

[<callout icon="✉️"> SERVICE PITCH email ]

## 5. Catching companies the moment they show they're ready to buy

[Plain-English: other public signals (funding, news, new leadership, new clients) that mean budget + intent right now.]

[Table: | The signal | Why it means they're ready |  (4-5 buying signals) ]

[<video> ]

[<callout icon="✉️"> SERVICE PITCH email ]

## 6. Reaching the people already following your competitors

[Plain-English: people following competitor pages already care about this category.]

[Table: | Competitor | LinkedIn followers | Engaged audience |  (5 competitors, hyperlinked) ]

[<video> ]

[<callout icon="✉️"> SERVICE PITCH email ]

---

Across these campaigns you have warm, reachable decision-makers in the thousands. [1-2 closing sentences on what working together looks like next.]
```

### Step 4 — Write the emails (one per section)

Generate each email with `/lilly-copywriter`, then strip ALL brackets and fill concrete values. Copy-type per section is FIXED:

| Section | Copy type | Icebreaker / opener | Notes |
|---|---|---|---|
| §2 Look-a-likes | **CASE STUDY** | Reference a **made-up colleague with a made-up title**, formatted `Name (Title)`. Look-a-likes have no concrete trigger, so the opener hedges: "Apologies if this isn't relevant, I wasn't sure whether you or Rachel Lim (VP of Sales) would be the better person to reach about [topic]." | Body uses the case-study pattern: "We've helped companies like [client] who were struggling [problem] [outcome]." then a soft CTA: "Not sure if you've got a partner helping you [service], but would you be open to seeing the case study?" |
| §3 Events | **ONE-SENTENCE PUNCH** | Cite the exhibiting trigger: "Saw you're exhibiting at [event], so I wanted to reach out." | Binary yes/no question, then "We help [ICP] [outcome], [risk reversal]." then a short closing CTA ("Worth a quick chat?"). |
| §4 Hiring | **SERVICE PITCH** | Cite the hire: "Saw you're hiring a [role], so I wanted to reach out." | "If we could [outcome] without [pain], starting with [risk reversal], would that be worth a short call?" |
| §5 Data signals | **SERVICE PITCH** | Cite the signal: "Saw you recently [signal], so I wanted to reach out." | Same service-pitch shape as §4. |
| §6 Competitors | **SERVICE PITCH** | Cite the follow: "Saw you follow [competitor] on LinkedIn, so I wanted to reach out." | Same service-pitch shape as §4. |

**Opener rule (all sections):** trigger observation + "so I wanted to reach out", nothing else. Never pack the pitch or a value-angle into the opener. The offer goes in the body.

**P.S. rule (all sections):** the P.S. is SOCIAL PROOF. Name-drop a real client found in research and/or cite a real result from their site; if none exist, use a plausible fictitious result. Examples: "P.S - We've helped companies like Triton Digital break into Asia and book their first enterprise meetings within weeks, with a 98% success rate across more than 25 countries."

### Step 5 — Notion callout syntax

The duplicated template already has one `<callout icon="✉️">` block per section (after the table and Loom video), each starting with `**The email we'd send:**`. You REPLACE the email text inside the existing callout, you don't insert a new one.

Confirmed syntax:
- Lines inside a callout are stored tab-indented (`\t`).
- Blank lines (`\n\n`) collapse, so the email renders as a tight stacked block. That's the desired look.
- The closing `</callout>` is flush-left (no tab).
- To disambiguate identical repeated lines (e.g. the same P.S. across sections) when editing, include the FOLLOWING flush-left context (the next `## heading` or `---` divider) in `old_str`. Don't rely on tab-matching inside the callout.

### Step 6 — Final pass

- Grep the whole doc for em-dashes. Remove every one.
- Confirm no `{{variable}}` brackets remain.
- Confirm no tool names leaked (except the AI Ark link in §2).
- Confirm all 5 native `<video>` blocks survived the duplicate-and-replace and still render (re-fetch the page and check).
- Flag to the user any illustrative numbers and any past-dated events that need refreshing.

### Step 7 — Deliver the link, then one-click publish

The doc is built. Hand it off so the user can share it right away:

1. **Return the live page link** as a clickable URL (the `page_url` from the duplicate, or `https://app.notion.com/p/<page_id_without_dashes>`).
2. **Tell the user the one click that makes it public**, in a single line: *"Open the page in Notion, click Share (top-right), then Publish, to get a public link you can send the prospect."*

The Notion API/MCP CANNOT toggle "Publish to web" itself (it is UI-only), so this one click is always required before the page is publicly viewable. Never claim the page is already public or already shared. Double-check the prospect name in the title is correct before handing it off.

## Template / worked example

The Expandin page (`3756e755-98d9-8116-b1ba-d83300fc8bf4`) is BOTH the page you duplicate in Step 3 AND the canonical reference for tone and final-form emails. Always duplicate it first, then replace the text. Never rebuild the structure from scratch.

---

**Voice:** For email voice: follow lilly-copywriter's "THE NAVREO VOICE" section (canonical) and read ~/.claude/skills/offer-email-voice-match/voice-corpus.md before writing any email copy.
