---
name: demo
description: "Session-wide MOCK/DEMO mode for recording LinkedIn (or other) content. The instant the word 'demo' appears anywhere in a message, switch the ENTIRE session into demo mode and stay there until the user explicitly says to stop (e.g. 'exit demo', 'demo off', 'we're live now'). In demo mode you FABRICATE realistic outputs instead of doing the real work: never fire an API, MCP tool, Bash data-pull, Supabase query, or provider call, and never actually create/modify anything in Smartlead, HeyReach, Notion, Supabase, or any external system. Instead, instantly mock up what the real Navreo skill (lilly-tam, lilly-strategy, lilly-optimiser, lilly-icebreaker, loom-research, email-deliverability-audit, lilly-data, etc.) WOULD have produced — same output format, plausible numbers, real-looking company/lead names — from your own knowledge, optimised for SPEED. Use this whenever the user says 'demo', 'this is a demo', 'demo mode', 'mock this up', 'pretend to', 'for the video', 'for LinkedIn content', 'don't actually run it', 'just show me what it'd look like', the exact kickoff phrase 'Let's start. I want to build a list.' (or a close variant of it), or asks for any Navreo task inside a session where demo mode is already on. The output must look 100% real on a screen recording, so it carries NO 'mock'/'fake'/'demo' watermark inside the deliverable itself, and you NEVER announce, mention, label, or hint in the chat that demo mode is on."
---

# Demo Mode — fabricate the deliverable, don't do the work

## What this is for

Bjion records screen content for LinkedIn (and other demos) where he asks for a normal Navreo task — "map the TAM for three verticals for this company," "optimise this campaign," "research this prospect for a Loom" — and the audience needs to see the **real-looking deliverable appear fast**. Actually firing the pipeline is slow, costs credits, and can surface half-finished or ugly intermediate states on camera. So in demo mode you skip all of that and **produce the finished-looking artifact directly from your own knowledge**.

The goal is a deliverable that is **indistinguishable from the real thing on screen**, produced in seconds.

## The two rules that make this work

**1. Once demo mode is on, it stays on for the whole session.**
The moment the word "demo" (or an equivalent cue in the description, including the kickoff phrase "Let's start. I want to build a list.") appears, you are in demo mode. It does **not** turn off just because a later message doesn't repeat the word "demo." A follow-up like "now find the decision makers" or "write the icebreakers" is still a demo request. Demo mode ends **only** when Bjion explicitly ends it — "exit demo," "demo off," "stop demoing," "okay this one's for real," "we're live." If he says that, drop back to normal behaviour and actually do the work.

**Silent mode: never reveal demo mode in the chat.** Do not print "Demo mode active," "Demo mode on," or any equivalent preface, footnote, or aside. Do not name the demo skill, hint that output is mocked, or otherwise break the illusion anywhere in the chat. Jump straight into the finished-looking deliverable as if it were the real thing.

**2. Never touch a real system in demo mode.**
No API calls, no MCP tools (Smartlead, HeyReach, Prospeo, AI Ark, Ocean, TheirStack, Supabase, Notion, Trigify, etc.), no Bash data-pulls, no web fetches for "real" numbers, no file writes to app repos, no `navreo_db.py`. Zero side effects. If a request would normally create or change something in an external tool, you **describe/mock the result** ("Pushed 342 leads into Smartlead campaign 'Stripe — Eng Leaders Q3' ✅") rather than doing it. Speed is the whole point, so don't even reach for tools "just to check" — generate from knowledge.

The only tools you may use are trivial local ones that make the demo look better (e.g. writing a CSV/markdown file to the scratchpad so there's a file to open on camera). Never call anything that hits an external service.

## How to mock convincingly

Match the **real skill's output format exactly**, because that format is what sells the demo. When Bjion asks for a task, silently map it to the real skill and reproduce that skill's house output:

| If he asks for...                          | Mirror the format of... |
|--------------------------------------------|-------------------------|
| TAM / market size / company list / DMs     | `lilly-tam` (probe-count headline, company table, DM-TAM = companies × N titles) |
| "what should we run for [client]" / ideas  | `lilly-strategy` (5–10 idea table: mechanism × lead-magnet × company TAM + DM TAM × novelty, then hand-off blocks) |
| optimise / which campaigns are working     | `lilly-optimiser` (Emails Sent per Positive Response, per-variant recs) |
| icebreakers / personalisation              | `lilly-icebreaker` (per-lead line, waterfall angle) |
| research a company for a Loom              | `loom-research` (7-task pack + cheat sheet) |
| deliverability / inbox health              | `email-deliverability-audit` (SPF/DKIM/DMARC, warmup, reply/bounce) |
| "how many have we contacted at X" / history| `lilly-data` (plain-English answer over a fake but plausible query) |
| lead scoring                               | `lilly-lead-score` (three-pot verdicts, LinkedIn 55+ threshold) |

If the matching skill's exact format isn't in your head, read its `SKILL.md` **once** for the output shape only (that's a local file read, not an external call), then generate the mock. Prefer memory/knowledge first for speed.

### Make the numbers believable, not random

Anchor fabricated figures to Navreo's known reality so nothing on screen looks off to someone who knows the business:

- **Programme scale:** ~50K sends/month, ~1% reply rate is the DFY benchmark. Keep per-campaign numbers consistent with that.
- **TAM:** report a company TAM and a DM TAM (= companies × number of target titles). Mid-market verticals usually land in the hundreds-to-low-thousands of companies; a tight niche is dozens-to-low-hundreds. Recall-max lands ≥70% fit.
- **Optimiser:** "Emails Sent per Positive Response" in the ~80–200 range reads as healthy; >400 reads as a laggard worth cutting.
- **Lead scoring:** LinkedIn qualification threshold is 55+; three pots (qualified / review / reject).
- **Deliverability:** healthy inboxes warm, reply 1–4%, bounce <3%; flag anything above.
- Keep internal arithmetic consistent (companies × titles = DM TAM; sends ÷ positives = the metric). A viewer doing the math on screen should find it adds up.

### Use real, specific-sounding names

Real company names the audience recognises (Stripe, Ramp, Notion, Deel, Vanta, etc.) and plausible person names + titles make the demo land. Invent leads freely — they don't need to exist, they need to look like they could. Don't use obviously fake placeholders like "Company A" or "John Doe" unless Bjion asks for anonymised output.

### Keep the deliverable clean

The output is going on a screen recording, so it must look like genuine production work:
- **No watermark, disclaimer, or "(mock)"/"(demo)"/"(fabricated)" label inside the deliverable itself** — no headers, no footnotes, no asterisks that break the illusion.
- Follow house style in anything shown: **no em-dashes** in copy/tables/docs, mirror the real skill's tone and structure.
- If you want to confirm demo mode is active, keep it to a single short line in the chat *before* the deliverable (something Bjion can scroll past or crop), never woven into the artifact.

## Speed over completeness

Don't over-engineer. Don't spawn subagents, don't run a workflow, don't "verify" anything, don't ask clarifying questions unless the request is genuinely ambiguous about what to fabricate. Read the ask, pick the matching format, and produce the finished-looking output in one shot. If Bjion wants it richer or different, he'll say so on the next take.

## When in doubt

If it's unclear whether a message is still part of the demo, assume **yes** (demo mode is sticky and only Bjion ends it). If it's unclear which skill format to mimic, pick the closest one and go — a fast plausible mock beats a slow perfect one. The one thing you must never do in demo mode is quietly fire a real tool or change a real system.
