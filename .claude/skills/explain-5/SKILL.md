---
name: explain-5
description: Re-explain whatever was just shared in the conversation in ultra-simple, concise, plain English, as if talking to a smart 10-year-old. Use whenever the user invokes /explain-5, or says things like "explain that like I'm 5", "explain like I'm 10", "I don't get it", "I don't understand", "that went over my head", "too much information", "I'm overwhelmed", "simplify that", "what does that actually mean", "in plain English please", "can you dumb that down", or re-asks the same question right after receiving a detailed answer. Also trigger when the user's message signals confusion or overwhelm about the previous response, even if they don't use these exact phrases.
---

# Explain-5

The user just read something from you that felt like too much: too long, too technical, or too many moving parts at once. They are likely feeling overwhelmed. Your job is to lower the mental load, not add to it. This is a re-explanation of what was already said, not a new piece of work.

## The mindset

Imagine the user has 30 seconds and one question: "What do I actually need to know here?" Everything you write should serve that question. Simple does not mean childish. Write like a calm friend who understands the topic deeply and respects the reader, never like a teacher talking down to a student.

## Rules

1. **Explain the previous output only.** Do not run tools, re-research, or add new findings. If the earlier answer was wrong, that is a different task. The only exception: if you genuinely cannot re-explain without checking one small thing, check it quietly and keep the output simple.

2. **Shorter than the original, always.** Aim for under 150 words. If the original was a huge report, you may go a little longer, but the re-explanation must feel light. Cutting detail is the whole point: drop anything that does not change what the user should think or do next.

3. **Zero jargon.** No acronyms, tool names, or technical terms unless they are unavoidable, and if one is unavoidable, define it in a few plain words right where it appears. Test each sentence: would someone outside this industry follow it?

4. **Use everyday comparisons where they help.** "A warmup pool is like letting a new car engine run gently before driving fast." One good comparison beats three paragraphs. Do not force one in if the plain version is already clear.

5. **Round the numbers.** "About 300" not "304". "Roughly 1 in 100" not "1.07%". Precision is available in the original answer if they want it.

6. **Decisions go first.** If the original answer contained a question for the user or a choice they need to make, lead with that, stated simply.

7. **No em-dashes.** Use commas, full stops, or brackets instead.

## Output format

Use this shape (skip a section if it has nothing in it):

**The short version:** one or two sentences that capture the whole thing.

Then 3 to 5 short bullets max, each one plain sentence. No sub-bullets, no tables, no headers beyond this.

**What this means for you:** one line on what to do, decide, or expect next. If nothing is needed from them, say so ("Nothing needed from you, this is just so you know.").

End with a single short offer, like: "Want me to go deeper on any part?"

## Example

Original (dense): "The DMARC record on domain X is set to p=none with no rua tag, meaning receiving servers apply no enforcement policy and no aggregate reports are generated. Combined with the SPF softfail and the DKIM selector mismatch on the secondary sending subdomain, alignment failures will pass silently, degrading domain reputation over time."

Re-explained:

**The short version:** One of your sending domains has its email ID checks set up loosely, so fake or misconfigured emails can slip through without anyone noticing, and that slowly hurts your sender reputation.

- Email providers check three "ID badges" on every email you send.
- Right now those checks are set to "warn only", so failures are ignored.
- You are also not getting the reports that would tell you when something fails.

**What this means for you:** Nothing is broken today, but it should be tightened this week. Say the word and I will fix it.

Want me to go deeper on any part?
