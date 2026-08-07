---
name: lead-magnet-brainstorm
description: "Helps the user come up with free lead magnets or hooks to offer in cold emails. Asks about their business, what they can legally give away, and what would be genuinely valuable to their ICP. Returns 5-10 concrete offer ideas with example CTA phrasings. Use this skill whenever the user says their campaign 'needs a hook', 'needs an offer', 'needs a CTA', asks 'what can I give away', or when ICP onboarding flagged a missing lead magnet — even if they don't explicitly say 'lead magnet'. Also trigger when reply rates are low and the diagnosis is that the ask itself is weak (i.e. 'book a call' with no upfront value)."
---

# Lead Magnet Brainstorm

Cold emails with a concrete free offer outperform "book a call" asks by 3-10x. This skill helps the user find an offer they can actually deliver.

## Why this exists

Most cold emails fail the "why should I reply?" test. The answer "because you might need our product" is not compelling. The answer "because we'll send you a free audit that'll save you money whether or not you buy from us" is.

A good lead magnet is:
- **Cheap to deliver at scale** (ideally automated)
- **Genuinely valuable to the prospect** (they'd pay for it, or it saves them obvious time/money)
- **Demonstrates your competence** (so buying becomes the natural next step)

## When to use

- During ICP onboarding when the user can't answer the "what can you give away" question
- When copywriting and the CTA feels weak
- When reply rates are <1% and the problem is "nobody cares about my ask"

## Steps

### 1. Intake — 4 questions

Ask one at a time:

1. **What do you sell, in one sentence?** (Use their ICP onboarding answer if you have it.)
2. **What's the #1 problem your best customer had BEFORE buying from you?** (This is the north star — the magnet should ease this problem.)
3. **What could you do for a prospect in under 30 minutes that they'd pay $100 for?** (The crux. Push back on "nothing" — there's always something. If they're an SEO agency, they could audit a page. A copywriter could rewrite a subject line. A dev shop could review one function.)
4. **Any legal / regulatory restrictions on what you can promise or give?** (Financial advice, medical claims, securities — know before proposing.)

### 2. Pick from the lead magnet archetype library

Match their business to one or more archetypes:

**A. The free audit / diagnostic**
- "Free 5-minute audit of your [thing]" — works for agencies, consultants, dev shops
- Delivery: you or AI runs a quick check, send back a 1-page report
- Examples: "I noticed your site doesn't have X, here's why that's costing you Y"
- CTA: *"Want me to run the full audit? Free, takes 5 min of your time."*

**B. The data / research piece**
- "Report on [their industry] — [metric or trend]"
- Delivery: create once, reuse infinitely
- Examples: "We analyzed 500 Shopify stores doing >$1M — here's what the top 10% have in common"
- CTA: *"Want me to send the report?"* or *"Want the 90-second summary?"*

**C. The competitive intel**
- "What your top 3 competitors are doing that you're not"
- Delivery: quick manual or AI-powered scrape
- Examples: "I pulled the LinkedIn post history of your 3 biggest competitors — want it?"
- CTA: *"Reply Y and I'll send the summary"*

**D. The template / checklist**
- "The exact [template/checklist/playbook] we use for [outcome]"
- Delivery: Google Doc, Notion, or PDF link
- Examples: "The 12-point pre-launch checklist we use for every new campaign"
- CTA: *"Want me to send it over?"*

**E. The intro / connection**
- "I can introduce you to [specific relevant person or type of person]"
- Delivery: warm intro from your network
- Examples: "I know 3 founders who solved exactly this — happy to intro"
- Warning: don't fake this. You have to actually know someone.
- CTA: *"Want the intro?"*

**F. The quick-win work**
- "I'll do [small scoped piece of work] for free as a sample"
- Delivery: 30-60 min of real work
- Examples: "I'll write 3 cold email subject lines tailored to your ICP, free"
- CTA: *"Reply with your ICP and I'll send them over"*

**G. The specific-to-them analysis**
- "I noticed [specific thing about their company] — here's what I think about it"
- Delivery: 2-3 sentences of real observation, no deliverable beyond the email
- Best for: high-ACV sales where a thoughtful observation is the magnet
- CTA: *"Happy to go deeper if useful"*

**H. The tool / free account**
- "Free account on [your product] with [specific scope removed]"
- Delivery: actual product access
- Examples: SaaS companies offering 30-day free trials framed as "free for your campaign"
- CTA: *"Spin you up an account?"*

**I. The 15-min working session**
- "15-min screen share where I [specific thing] for you"
- Delivery: 15 min of your real time
- Best for: high-ACV, later-stage buyers
- Examples: "15 min where I walk through your checkout flow and flag 3 friction points"
- CTA: *"Grab a slot? [calendly link]"*

**J. The benchmark / comparison**
- "How your [metric] compares to [peer group]"
- Delivery: you have benchmarks, they get theirs compared
- Examples: "Your Google rank for [term] is #X. The median in your industry is #Y. Want the full breakdown?"
- CTA: *"Want the full comparison?"*

### 3. Score each proposed magnet against the rubric

For each archetype that fits, score:

| Criterion | Score 1-5 |
|---|---|
| Cheap to deliver (1=expensive, 5=automated) | |
| Genuinely valuable (1=no, 5=they'd pay $100+) | |
| Demonstrates competence (1=no signal, 5=strong signal) | |
| Unique vs competitors (1=everyone does it, 5=only you could) | |

**Total ≥15/20 = worth proposing. <15 = skip or rework.**

### 4. Output: brainstorm table

Present the brainstorm as a single table. Each row is one magnet that passed the rubric in Step 3. Columns hold the metadata AND an email body that's ready to push straight to Smartlead. This keeps the magnet, value prop, contents, and copy aligned so the user can compare options at a glance and pick one to deploy without a separate copywriting pass.

Above the table, state the consistent subject line and preview text:

```
**Subject (all):** Quick one
**Preview (all):** Hi {{first_name}}, put this together and thought you'd want to see...
```

Then the table:

| # | Lead magnet | Value prop (tangible action) | What the 1-pager includes | Email body |
|---|---|---|---|---|
| 1 | **[Problem-framed title, e.g. "Why the playbook you built sits unused"]** | [The single, tangible action the recipient takes after reading. E.g. "Run your playbook through the 4 questions. Find the one missing property. Fix that one only."] | [Concrete contents of the 1-pager: the structure, the bullets, the diagnostic-and-fix pattern. Be specific enough that the user could draft the doc from this column alone.] | Hi {{first_name}},<br><br>**[Problem statement — generalised pain in the form "Most [ICP role]..." or "[Topic area] usually..."]**<br><br>**We put together a [resource type, e.g. 1-pager / guide / checklist / pack] which I thought might be useful for {{company_name}}, it covers [topic + the fix or framework].**<br><br>**[Case study line using the seller's real case studies, format: "We've helped companies like X struggling with Y see Z."]**<br><br>**Can I share it?**<br><br>%signature% |

#### Email body construction rules

These follow the lilly-copywriter Lead Magnet rules:

- **Magnet titles must be problem-framed.** Not "The 4 Properties of a Process Reps Execute" but "Why the playbook you built sits unused." The title names the pain, not the solution.
- **Problem statement opens the body.** Per the lilly-copywriter Lead Magnet Problem Statement Rule. Use generalised forms like "Most [ICP role]..." or "[Topic area] usually...".
- **Offer must be honest about personalisation.** If the 1-pager is one-size-fits-all (same doc for everyone), use "Thought this might be useful for you, it covers...". Do NOT claim "I put together a 1-pager specifically for {{company_name}}" unless per-company work was actually done. Per the lilly-copywriter Lead Magnet One-Size-Fits-All Resource Rule.
- **Case study line uses the seller's real case studies.** Pull from their existing Smartlead campaigns (via lilly-bot or the Smartlead API), website, or onboarding briefing. Format per lilly-copywriter: "We've helped companies like [X] struggling with [Y] [achieve Z]."
- **Soft send-based CTA.** "Can I share it?" or "Would you like me to send it over?" since the 1-pager can be delivered without a call.
- **No P.S. needed.** The case study line lives in the body, so the P.S. is redundant.
- **Body word count ≤50** (excluding greeting, problem statement, sign-off). Trim only where it doesn't hurt clarity.
- **Bold every customised cell** (problem statement, offer, case study line, CTA) so the user can see at a glance what was filled in vs the template.

### 5. Recommend the top 2-3

Pick based on:
- **Delivery friction** (favor low-friction — can be automated or pre-built)
- **Match to their ICP's actual pain** (question #2 from intake)
- **Novelty** (if every competitor does free audits, pick something else)

### 6. Save output

Save the full brainstorm + top picks to:

```
<project-root>/lead-magnets/<business-slug>-lead-magnets.md
```

If the user is coming from ICP onboarding or has a client profile, note the chosen magnet alongside the existing client record so it can flow into copywriting:

```
offer:
  lead_magnet: <top pick name>
  lead_magnet_details: <one sentence on what you deliver>
  lead_magnet_cta_example: <example reply-hook CTA>
```

## Common mistakes

- **Proposing magnets the user can't actually deliver.** Always confirm delivery capacity. "Free audit" from someone who has never done one = disaster.
- **Asking for a meeting as the "magnet."** A meeting is not a magnet, it's an ask. The magnet is what you give them BEFORE the meeting.
- **Lead magnets that require too much from the prospect.** "Fill out this 20-field intake form" = dead. Maximum ask: reply with 1-2 data points.
- **Gated PDFs behind forms.** For cold email, NEVER gate the magnet. Send it inline or as a direct link. Gating kills reply rate.
- **"Free consultation."** Generic and uninspiring. Replace with something specific — "15 min where I [specific action] for you".

## What to do next

With a lead magnet chosen, the user's next step is to write the email that delivers the magnet. Hand off to the **`lilly-copywriter`** skill (for the copy itself) or **`lilly-bot`** (to push the new CTA into a Smartlead campaign). Pass the chosen magnet's name, delivery details, and example CTA so the copywriter doesn't have to reinvent them.
