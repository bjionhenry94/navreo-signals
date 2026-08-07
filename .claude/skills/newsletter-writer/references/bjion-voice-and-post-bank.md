# Bjion's voice + the post bank

This file defines whose voice the newsletter is in (Bjion Henry, founder of
Navreo), and how to choose which posts to draw from. The William structure in
`william-brown-style.md` is the vessel; this is what fills it.

## Who is writing

Bjion Henry. Founder of Navreo, an AI-automation agency that runs outbound /
go-to-market for B2B clients using Claude Code as the spine of the stack
(Smartlead, AI Ark, Prospeo, HeyReach, TheirStack, Ocean, Clay-replacement, etc.).
Ex-Google. Builds in public on LinkedIn. Bootstrapped and profitable.

He writes as a **practitioner with strong, specific opinions** about where AI,
outbound, and go-to-market are heading. He is not a guru. He shows the work.

## Voice fingerprint (pulled from his own posts)

- **Contrarian one-line openers.** "Go-to-market engineers are dead." / "We
  replaced Clay with Claude Code overnight." / "The US government banning Claude
  Fable will backfire." He commits to a strong claim in line one.
- **Short, punchy paragraphs.** One to two sentences. Lots of white space. (This
  already matches William's cadence, which is why the fit is natural.)
- **Specific numbers as proof.** "$5K+ p/m", "60% cheaper", "10x", "17% monthly",
  "4x better", "$10K-$20K with Clay". Never vague.
- **"Here is what we actually do" POV.** He speaks from running real campaigns
  across many clients, not from theory. "After testing 60+ data sources..."
- **Names tools and names them precisely.** Claude Code, Smartlead, AI Ark,
  Prospeo, HeyReach, TheirStack, Ocean, Clay, MillionVerifier, Fathom.
- **British spelling.** optimise, personalisation, behaviour, favour, programme.
- **Measured, not hypey.** He hedges fairly ("they won't go away, they're still
  needed"), acknowledges the other side, then states his view. Confidence without
  superlatives. Avoid "incredible / game-changer / insane" as filler.
- **Plain, direct, no jargon-for-its-own-sake.** Explains the mechanism simply.
- **Light arrows in lists when needed** (→, ↳). Use sparingly in an email; prose
  with rhythm beats slide-deck formatting.

## Hard rules

- **No personal stories.** This is the user's explicit standing instruction for
  newsletters. Exclude anything autobiographical: moving cities, the ICU /
  collapsed lung, the failed startup / raise, family, burnout, "as a kid my mum",
  Jamaica funeral, "if you feel trapped in your job". Those posts perform well but
  are OFF-LIMITS as newsletter source material. Draw only from his
  tactical / opinion / case-study / industry-shift posts.
- **No em-dashes.** Ever. Use commas, colons, full stops, or parentheses.
- **One post per newsletter. Do not mix and match.** Each newsletter is built
  from a single source post's core idea. Do not blend two posts into one email.
  Blending dilutes the one strong opinion that made the original post land.
- **Pure value, no CTA** (default — see SKILL.md if the user changes this).

## How to pick source posts

1. Run `scripts/rank_posts.py` on the export to get the ranked list + full text.
2. Skip every personal story (see exclusion list above).
3. From what remains, prefer posts that scored well on BOTH reach and engagement.
4. Pick the requested number (default 7), keeping the topics **distinct** so the
   week does not repeat itself. If two strong posts make the same point (e.g. two
   different "we replaced Clay with Claude Code" angles, or two "red flags"
   listicles), use only one and pick a different mechanism for the others.

## The proven non-personal angles (Bjion's best, as of the June 2026 export)

These are his strongest non-personal posts. Use them as the default source bank
when the user has not pointed at a specific export, and as a guide to the kinds
of angle that work for him:

1. **"Go-to-market engineers are dead"** (top performer, ~12.6k reach, 41
   comments). Opinion: Claude Code collapsed the technical moat; the GTME role
   gets commoditised (not extinct, but far less scarce).
2. **"We replaced Clay with Claude Code overnight"** + **"We cut outbound tool
   costs 60%"**. Case study: rebuilding the whole stack inside Claude Code, the
   six jobs it took over (list building, DMs, signals, copy, optimisation,
   adding tools).
3. **"The US banning Claude Fable will backfire"**. Opinion: export bans
   backfired with Nvidia/China and DeepSeek; banning models breeds cheaper,
   more diverse competition. Users lose short-term, win long-term.
4. **"7 red flags in your B2B outreach"**. Tactical checklist: reply rate <3%,
   high opens / low replies, spam, single sending domain, generic first lines,
   sequence stops at email 2, no data review.
5. **"Everyone pulls from the same 4 databases"**. Opinion: the edge is not the
   biggest database, it is knowing which database to use for which campaign
   (60+ tested, broken down by job).
6. **"HeyReach got banned. Good?"**. Contrarian: outreach gets a bad rap, but
   "spam" is how he hired a key employee and won paid partnerships; the real
   motive behind bans is often the platform's own competing product.
7. **"The competitor-follower signal that's 4x better"**. Tactical play: scrape
   the followers of tools your ICP already uses (Smartlead, Clay), qualify,
   lead-score, prioritise. Relevance makes it not feel cold.

Other reusable angles: the GTM tool-stack breakdown, "the old way vs the new
way" of B2B growth, extracting ICP customers from your LinkedIn connections
export, close rate up 17% with Claude + Fathom call review, the 3-layer Claude
system (Chat / Code / Cowork), "how teams scale outbound without hiring".

When a fresh export is provided, re-rank and re-pick from it rather than relying
on this list. His best angles will move over time.

## Voice calibration (learned from iterating a real set to 5/5)

These are the things that move a draft from "fine" to "indistinguishable from
him". The first draft of this skill missed several, so treat them as defaults.

1. **Use natural contractions everywhere.** don't, won't, it's, that's, you're,
   they're, here's, doesn't, isn't, we're, I'll, you'll, can't. Writing "it is /
   do not / they are / you are" in full instantly reads more formal than he is.
   This was the single biggest gap on the first pass.

2. **Use his inline `→` arrow lists.** When a newsletter needs a list, format it
   as `→` arrow bullets using the real glyph (his actual habit; Bjion confirmed
   2026-07-05 the symbol is `→`, not the ASCII `->`), NOT as a colon-prefixed label list
   ("List building: it does X. Decision makers: it does Y.") which reads like an
   internal SOP or deck, and NOT as sentence anaphora ("Now it... Now it...")
   which reads copywriter-structured.

3. **Never end on an invented polished two-line maxim.** This is the #1
   inauthenticity tell. Lines like "Access always gets commoditised. Judgement
   doesn't." or "What you don't measure, you can't fix." sound like a LinkedIn
   guru, not like him. He does not write manicured "X. Not Y." epigrams as closers.

4. **Vary the closers, and leave them a little unresolved.** His real endings: a
   blunt dare ("If you want to waste $60K this year, ignore this post"), a
   forward-looking hedge ("Let's see how it plays out", "I think there's a big
   shake-up coming"), or a plain practitioner instruction ("Stop rewriting it and
   go fix what's around it"). Less resolved beats more polished. Do not end every
   newsletter on the same shape.

5. **Keep his specific numbers, do not make them vaguer.** $5K p/m, $10K-$20K,
   60%, 90%, 10x, 4x, $60K. Specificity is core to his credibility. Reusing his
   actual figures and phrases verbatim is good, not lazy.

6. **Two-beat openers.** A bold claim, then a very short second line. ("It is not
   hiring. It's Claude Code." / "Most do not know yet.")

7. **Make ONE point hard.** Even when the source post is a listicle (e.g. "7 red
   flags"), frame the newsletter around a single claim and let the list be quick
   supporting beats, rather than seven equally-weighted diagnostic items with
   stats, which reads as a guru checklist.

8. **Drop the bloggy connective tissue.** "The best part is...", "Here's the
   thing." Prefer his plainer "But the reality is..." or just cut to the point.

Fast way to hit this bar: after drafting, reread every CLOSER and every LIST.
Closers are where the guru voice sneaks in; lists are where the SOP voice does.

## Voice learnings ported from `lilly-linkedin-copywriter` (2026-06-27)

Bjion confirmed the LinkedIn copywriter captions are "exactly how I would
talk". The canonical tone source is now the **VOICE — BJION (NAVREO)** section
in `lilly-linkedin-copywriter/SKILL.md` — read it if you want the fullest
picture. The points below are the ones that most improve a newsletter draft and
were under-weighted before. They sit UNDER the William structure (the newsletter
still follows the William cadence; this is about the sentence-level voice that
fills it).

1. **Parenthetical asides are a signature — use them.** This was the clearest
   tell missing from earlier drafts. He drops short, honest asides in brackets
   mid-sentence: "...backed by data (not a hunch).", "(their case studies, events
   they're exhibiting at, whatever fits)", "(usually 100, hence the name)",
   "(he's still in my corner today)". One or two per newsletter makes it sound
   like him talking, not a brand broadcasting. Don't force them; do reach for one.

2. **Casual British idiom is core to his voice.** He says: "a hell of a lot of
   work", "the manual graft sitting underneath it", "don't bin it", "a document
   they can just flick through", "it ate my time", "put the work in". Prefer these
   plain, slightly blunt British phrasings over polished corporate verbs. (Still
   British spelling throughout.)

3. **Genuine intensifiers ARE allowed, in moderation.** Earlier guidance to avoid
   "incredible / insane" as filler still holds for FILLER, but his real captions
   use "it works incredibly well", "highly effective, and fast", "super quickly",
   "very, very powerful". Don't sand every one out. The test is whether it's doing
   real emphasis on a true claim (keep) or padding a weak one (cut). One or two
   real ones per piece read as him; zero reads sanitised.

4. **Concrete anchors over cleverness in the opener.** His strongest openers lead
   with a real number, tool, or specific stake, not a witty abstraction: "A year
   ago, a go-to-market engineer cost you $5,000 a month.", "14 tools you can run
   from one window." Keep the two-beat shape (bold line, short second line) but
   make the first beat carry something concrete.

5. **The reframe + plain instruction close.** His best tactical closers are a
   clean reframe of the lesson followed by a flat, practical instruction:
   "The bottleneck was never the strategy. It was the manual graft sitting
   underneath it. If something works but won't scale, don't bin it. Find the part
   that's eating your time and hand it to AI." This is the newsletter-safe version
   of a closer — it gives the reader something to DO without manicuring it into a
   guru epigram (see rule #3 in the section above, which still stands: no polished
   "X. Not Y." poster lines).

6. **The honesty test (run it on every line).** Read the draft and ask: "would
   Bjion actually say this sentence out loud to one person?" If a line sounds like
   ghostwriter polish, rewrite it the plain way he'd say it. This single test
   catches most of what makes a draft feel off.

7. **£ for his own money, $ only where the source uses it.** His figures in £
   (pounds) when it's Navreo's money; keep $ where the original post/market figure
   used it (e.g. "$5K/month GTM engineer", "$130k job"). Match the source.
