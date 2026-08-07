---
name: discovery-followup
description: "Draft Navreo's house-format post-call follow-up email from a discovery / sales call, built only from what was actually said. Reads the call straight from a Fathom URL / call-id, or from a pasted transcript / notes. This skill produces ONE deliverable: the email. It never builds a breakdown doc, never runs research, never creates a Notion page. Use whenever the user wants to write up a call, send the follow-up, send the recap, or 'do the follow-up for [Fathom link]'. Trigger phrases: 'follow up on this call', 'write the follow-up for [url]', 'recap this call', 'post-call email', '/discovery-followup [url]'."
---

# discovery-followup

## Purpose

After a discovery or sales call, draft Navreo's standard follow-up email: greeting, thank-you, Challenges Discussed, Pricing / ways to work together, Useful Resources, testimonials, Next Steps, sign-off. Built from what was ACTUALLY said on the call.

The call is read directly from a Fathom link, call-id, or share link (no need to ask the user to paste the transcript). The email is grounded in the transcript, never invented.

**This skill drafts an email. That is the whole job.** It does not build a campaign breakdown, does not run `claude-breakdown`, does not run `loom-research`, does not create a Notion page, and does not spend research credits. If the user wants a breakdown doc, that is a separate, explicit request and a separate skill. Never bolt one onto a follow-up because the call mentioned sending "a document".

## When to trigger

- "Write the follow-up for [Fathom url]"
- "Follow up on this call / recap this call / write up this call"
- "Do the post-call email for [prospect]"
- "/discovery-followup [url]"

Do NOT trigger for internal call notes only (just summarise), for campaign ideation (`/lilly-strategy`), or for standalone copy (`/lilly-copywriter`).

## Hard constraints (never break)

1. **ZERO em-dashes** anywhere in the email. Use commas, colons, periods, or parentheses. Hyphens and arrows are fine. (House rule.)
2. **Grounded in the call.** Every line in "Challenges Discussed" and "Next Steps" must come from what was actually said. Never invent a pain, a commitment, or a who-does-what. If something is unclear, leave it out rather than guess.
3. **"You..." framing for challenges.** Each challenge is written back to the prospect in their own words, second person ("You have been frustrated because...", "You found that..."). Mirror their language, do not editorialise.
4. **Honesty over polish.** If the call was a soft no, a partial fit, or a pivot, the email must reflect that candidly (see "No-fit / pivot calls" below). Do not paper a "no" with a generic sales recap.
5. **Real next steps, split by owner.** Use the exact commitments from the call, grouped by who owns each one ([Prospect] will... / Bjion will... / The team will...).
6. **Sign-off is fixed** (see template). Bjion Henry, CEO + Co-Founder.
7. **15-word cap on every Challenges Discussed and Pricing bullet.** Hard ceiling, count the words. These two sections are scanned, not read: a bullet that runs past 15 words has become a paragraph and stops doing its job. If a bullet won't fit, cut the qualifier or the caveat, not the number. Detail that genuinely matters moves into a prose sentence below the section, or into the call itself. This cap applies ONLY to these two sections, never to the testimonials (constraint: never compressed).
8. **Never paste a raw URL into the email.** Every link is a markdown hyperlink on short descriptive anchor text: `[Watch the walkthrough](url)`, never `Watch the walkthrough https://www.loom.com/share/761e98...`. A naked URL is the single ugliest thing in an otherwise clean email, and a 180-character Google Slides link wraps across three lines and makes the whole thing look like spam. See "Link hygiene" below for the exact rules and the canonical URLs.

## Link hygiene

Constraint 8 in practice. Get this right without being asked.

**Always hyperlink the anchor text.** Markdown link syntax (`[anchor](url)`) is correct: it renders clean in chat, and when the user copies the rendered email into Gmail it pastes as a real hyperlink. The URL itself should never be visible in the body.

**Use the clean canonical URL.** Strip the junk before linking:
- Strip `?share=copy`, `?source=copy_link`, `?usp=sharing` and any other share / tracking fragment.
- Strip `#slide=id.g...` and other deep-link fragments.
- **Strip `/u/1/` and `/u/0/` from Google links.** This is not cosmetic. `/u/1/` hard-codes Bjion's second Google account into the URL and it 404s or shows a wrong-account error for the recipient. Always use the plain `/d/<id>/edit` form.

**Anchor text is short and descriptive.** It says what the recipient gets, not "click here" and not the URL. Three to eight words.

**Canonical resource URLs (use these exact ones, already cleaned):**
- Loom walkthrough: `https://www.loom.com/share/761e986f5f964550ab3375694f68687b`
- Service Deliverables slides: `https://docs.google.com/presentation/d/1FxMpYaNtmArGKlJuSbQJ11s1fHiM0ITt2wtoSJROtRQ/edit`
- Pipeline playbook: `https://navreo.notion.site/This-playbook-generated-over-15-480-000-in-Sales-Pipeline-for-50-GTM-Teams-v1-0-30c6e75598d9805d819cd1d02b8cb386`
- All testimonials: `https://www.navreo.ai/testimonials`

## Inputs

- **A Fathom URL, call-id, or share link** (required). Resolve it yourself, do not ask the user to paste the transcript.
- If the user pasted a transcript or notes instead of a link, use those directly.
- **If there is no recording and no notes**, say so and ask for them. Do not write an email from nothing.

## Process

### Step 1 — Read the call

1. Load the Fathom tools, then resolve the link with `get_recording_by_url` (or `get_recording_by_call_id` for a bare number).
2. Pull BOTH `get_meeting_summary` and `get_meeting_transcript` (pass the `url` so transcript links are timestamped). The summary gives you the spine, the transcript gives you the verbatim language for the "You..." lines.

If the user says there is no recording, skip straight to their pasted notes. Do not hunt for a call that does not exist.

### Step 2 — Extract the spine

From the call, pull out:
- **Prospect name(s) + company.** If more than one person was on the call, the greeting names all of them.
- **Challenges / pains / goals** — in their own words. These become "Challenges Discussed".
- **Verdict** — is this a fit, a partial fit, or a no / pivot? This sets the tone of the whole email.
- **Pricing or commercial model** — only if discussed. If not, replace the Pricing block with "Ways we could work together" or omit it.
- **Agreed next steps**, split by owner.

### Step 3 — Draft the follow-up email

Use the house template (below). Rules:
- **Keep it short. Aim for half a screen.** Succinct is the house style: the recipient skims, they do not read. Every section except the testimonials should be as tight as it can be while still landing.
- **Any section that is a list uses real dash bullets (`- `):** Challenges Discussed, Pricing / ways-to-work options, Useful Resources, the three testimonials, and Next Steps all get bulleted. Prose sections (Where we landed) stay as plain sentences, no bullets.
- Keep the section order. Drop a section only if the call genuinely had nothing for it (e.g. no pricing).
- "Challenges Discussed" = the pains in "You..." framing, mirroring their words, but compressed. Two or three tight bullets, not one per sentence they said. Fold related pains into a single line. **Maximum 15 words per bullet** (constraint 7): mirror their language, then stop. Drop the "so that..." tail and the second clause, the pain lands without them.
- **Pricing bullets are also capped at 15 words each** (constraint 7). One number, one thing it buys, nothing else. Conditions, at-cost notes, qualification criteria, and anything that needs a "because" belong in a short prose line under the options, not stuffed into the bullet.
- "Where we landed" / "Where we got to" = at most two sentences. For a no-fit, the candid line lives here.
- **Prose sections must read as natural, flowing email sentences, not clipped note-fragments.** Never open with a bare fragment like "Fair challenge." or "A two-way fit." and never use a report-style header like "On the [topic] question". If you need to answer a point the prospect raised, weave it into a normal paragraph (e.g. "You asked a fair question on the call: ...") and let it flow into the opportunity. Read it back as if you were the recipient: if it sounds like meeting notes, rewrite it.
- "Next Steps" = the real commitments, grouped by owner, each a single clear action. Usually two lines is enough.
- **Testimonials are the one section we never compress.** Always include exactly THREE, verbatim, picked as the three most relevant to this prospect (from the wall in the template). Never drop them, never water them down to a count. Three real, named results beats a wall of ten.
- The **Useful Resources** block is reusable boilerplate: trim it to the 2-3 links that matter for this call. Every link hyperlinked per constraint 8.

### Step 4 — Deliver

Return, in one message:
1. The **follow-up email**, copy-paste ready (no em-dashes, no naked URLs, no leftover brackets).
2. Flag anything that needs the user's eyes before sending: pricing left blank, an unclear commitment dropped, a section written from thin notes, a house number (like the $15.4M) that did not come from this call.

Do not offer to build a breakdown, a research pack, or any other asset unless the user asks.

## House template (follow-up email)

```
Hi [First Name],

Thank you for your time ([Watch the recording](url) / [slides link if shared]). [Optional one-liner, e.g. "Sorry for the delay, wanted to find the right stuff to send."]

Challenges Discussed
- You [pain 1, compressed].
- You [pain 2]. (2-3 tight "You..." bullets, related pains folded together, MAX 15 WORDS EACH)

Where we landed
[Optional. At most two sentences, plain prose, no bullets. For a no-fit or pivot call, the candid line goes here. Omit for a clean fit / pricing call, as the gold-standard examples do.]

Pricing
- [Option / number 1, one line, exactly as quoted on the call, MAX 15 WORDS]
- [Option / number 2, one line, MAX 15 WORDS]
[Any condition, at-cost note, or qualification criteria goes here as one short prose sentence, not inside the bullets.]
(Only if discussed. For a re-quote / discount follow-up this may be the whole email. Otherwise omit.)

What the first three months look like
(Optional. Include only when the engagement shape was walked through on the call. Split by model, one line per month.)
Done-with-you
- Month one: [...]
- Month two: [...]
- Month three: [...]
Done-for-you
- Month one: [...]
- Month two: [...]
- Month three: [...]

Useful Resources
- [A short walkthrough of exactly how the system works](https://www.loom.com/share/761e986f5f964550ab3375694f68687b)
- [Service Deliverables: what do you get?](https://docs.google.com/presentation/d/1FxMpYaNtmArGKlJuSbQJ11s1fHiM0ITt2wtoSJROtRQ/edit)
- [The playbook behind $15.4M+ in sales pipeline](https://navreo.notion.site/This-playbook-generated-over-15-480-000-in-Sales-Pipeline-for-50-GTM-Teams-v1-0-30c6e75598d9805d819cd1d02b8cb386)
- [All our testimonials](https://www.navreo.ai/testimonials)
(Trim to the 2-4 links that matter for this call. Do not dump every link. Hyperlinked anchor text only, never a bare URL.)

What do clients say about us?
- [Testimonial 1 of 3, verbatim from the wall below, hyperlinked on the sentence]
- [Testimonial 2 of 3]
- [Testimonial 3 of 3]

Next Steps / Let me know which one suits
- [Prospect] will [their commitment(s)].
- Bjion will [Bjion's commitment(s)].

Thanks,
Bjion

Bjion Henry
CEO + Co-Founder
```

**Testimonial wall (the pool to pick 3 from, paste verbatim, hyperlinked on the whole sentence):**
```
[WATCH TESTIMONIAL: How we helped Marc from Pathos Communication scale to 50 calls a day and grow revenue by 33% month over month.](https://vimeo.com/1057741968)
[WATCH TESTIMONIAL: How we helped Philip Okito from TrAIDe generate deals worth multiple millions in turnover.](https://vimeo.com/1086762817)
[WATCH TESTIMONIAL: How we helped Eric Bartosz from SIHL add millions of dollars to their sales pipeline.](https://vimeo.com/1040108223)
[WATCH TESTIMONIAL: How we helped Gavin Todd from Touchpoint add $30K worth of monthly leads to their sales pipeline.](https://vimeo.com/1090062044)
[WATCH TESTIMONIAL: How we helped Dan Barry from Revenews save $24K in annualised costs.](https://vimeo.com/1090052951)
[WATCH TESTIMONIAL: How we helped Ricky Solanki from Push Group build in-house tools for their sales and delivery team.](https://vimeo.com/909001806)
```

**Testimonial selection rule:** pick the three whose result maps most tightly to this prospect. Scale / volume plays lead with Pathos; SaaS / tech and big-pipeline plays lead with TrAIDe and SIHL; a prospect who wants to bring it in-house gets Push Group (in-house tools). Always exactly three, always hyperlinked, never a bare vimeo.com URL.

## No-fit / pivot calls

Some calls are a soft no, a partial fit, or pivot into a partnership rather than a services deal. The honesty rule applies (constraint 4). For these:
- Open by acknowledging the candid conversation, do not pretend it was a standard discovery.
- In "Challenges Discussed", still mirror what they're trying to do, then state plainly where we are not the right fit (using what was said on the call), so the email matches the conversation they remember.
- Replace "Pricing" with the actual paths discussed (e.g. a build-for-X exchange, a content / sponsorship arrangement), each as one clear bullet.
- Keep the three testimonials (the one section we never cut), just pick the three that fit the new direction.

## Reference

The canonical example of the house format is the Gary Reilly follow-up (the format the user pastes as the gold standard). Match its section names, ordering, link labels, and the testimonial wall.
