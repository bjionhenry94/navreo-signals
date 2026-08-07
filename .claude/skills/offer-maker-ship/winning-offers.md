# Winning offer lines (mined from Supabase, 2026-07-12)

Source: `replies` categorised positive (Interested, Meeting Request, Call Booked,
Information Request, positive-re-reply, Re: Interested) joined to `sent_messages`
Email-1 bodies on (email, smartlead_campaign_id). 999 positive threads, 607 copy
clusters. Lines below are VERBATIM from the sent copy; only client and prospect
identities are swapped for neutral placeholders ({{company}}, "a dev agency" style).
Evidence = positive replies credited to the template cluster(s) the line appears in.

---

1. "If it fits, we can build or run it for you guaranteeing 30 qualified leads in 90 days or we refund you."
   - tags: risk-reversal=guarantee+full-refund | pricing=outcome-priced | CTA=send-a-Loom | mechanism=engagement-signal
   - evidence: 30+ positive replies across the "recorded a Loom for {{company}}" template family (9+8+5+5 in the top clusters alone)

2. "You only pay after we've built it, so zero upfront amount."
   - tags: risk-reversal=pay-after-result | pricing=zero-upfront | CTA=send-a-one-pager | mechanism=engagement-signal
   - evidence: 12 positive replies (7 Call Booked/Info + 5 Interested clusters)

3. "If it's useful, we run it for you on a pay-per-lead basis."
   - tags: risk-reversal=pay-per-result | pricing=per-unit | CTA=send-a-video | mechanism=pain-first opener
   - evidence: 6 positive replies (incl. 5 positive-re-reply)

4. "If it lands, we can run it for you on a pay-per-lead basis, so you only pay for the leads we deliver."
   - tags: risk-reversal=pay-per-result | pricing=per-unit spelled out | CTA=2-minute video | mechanism=referral-ceiling pain
   - evidence: 4 positive replies (3 Call Booked)

5. "You only pay once sales come through, so nothing out of pocket to start."
   - tags: risk-reversal=pay-per-result | pricing=performance-basis | CTA=open-to-seeing-how | mechanism=gap-spotting (client: an Amazon growth agency)
   - evidence: 10 positive replies across two "selling everywhere but Amazon" clusters (6+4)

6. "We've helped brands like {{brand A}} and {{brand B}} who were selling everywhere but Amazon launch and scale past six figures a month there, all on a performance basis."
   - tags: differentiator=named-proof + performance basis | risk-reversal=pay-per-result | mechanism=gap-spotting
   - evidence: same 10 positive replies as line 5 (same template)

7. "If you'd like to see what my work looks like, feel free to send me a brief on one room from a current project or proposal. I'd happily put together a mood board, a render, and a sourcing snapshot, and have it back within 48 hours, no charge or commitment."
   - tags: risk-reversal=free-sample | pricing=free-first | CTA=send-me-a-brief | mechanism=freelance placement (client: an interior designer)
   - evidence: 38 positive replies (21 Interested, 12 Information Request, 5 Meeting Request) — highest single cluster

8. "I've compiled a breakdown showing how we're using Claude Code to almost replace Clay in our outbound, reducing cost and complexity while improving results. Want me to send it across?"
   - tags: risk-reversal=free-resource | CTA=want-me-to-send-it | mechanism=tool-follower trigger
   - evidence: 59 positive replies across three "Claude Code" clusters (28+25+6)

9. "We've moved our entire go-to-market stack off Clay and onto Claude Code, going from campaign build to launch in a few prompts at around 90% less cost."
   - tags: differentiator=concrete cost delta | pricing=90%-less framing | mechanism=pricing-news trigger
   - evidence: 9 positive replies across two "Clay pricing" clusters (5+4)

10. "We've put together a quick breakdown of the exact campaigns we'd run to get {{company}} 30 qualified leads a month."
    - tags: risk-reversal=free-custom-sample | pricing=quantified outcome | CTA=can-I-send-it | mechanism=named-account breakdown
    - evidence: 7 positive replies (all Interested)

11. "I recorded a Loom for {{company}} showing what we'd build to help you land more clients."
    - tags: CTA=send-a-Loom | risk-reversal=free-custom-sample | mechanism=engagement-signal
    - evidence: 30+ positive replies (backbone line of the Loom template family)

12. "Saw you followed {{tool}} on LinkedIn, and so wanted to ask, if we could build you an AI lead-generation engine that added 30+ qualified leads every month, without needing to hire a BDR team, would you be interested?"
    - tags: problem=hiring-BDRs-burns-budget | differentiator=engine-not-headcount | pricing=quantified outcome | mechanism=tool-follower
    - evidence: 12 positive replies (two clusters, 7+5)

13. "Most SaaS leaders we speak to find hiring and ramping SDRs burns months and budget before any pipeline shows up."
    - tags: problem=high-consequence (months + budget with no pipeline) | mechanism=pain-first opener
    - evidence: 6 positive replies (5 positive-re-reply)

14. "If we could help {{company}} book your sales team meetings with facility and property managers needing building services, and I showed you exactly how through a 2-minute video, would you be keen to see it?"
    - tags: CTA=2-minute video | problem=referral-ceiling | outcome=meetings-with-named-buyer-type | mechanism=vertical-specific
    - evidence: 4 positive replies (3 Call Booked)

15. "We're offering a select few companies $1,000 of API credits. Hoped you might find it valuable for generating better outputs more cheaply."
    - tags: risk-reversal=free-sample (credits) | pricing=free-to-test | CTA=onboarding call | mechanism=product-launch trigger (client: an AI model provider)
    - evidence: 10+ positive replies across the credits template family (6+4, heavy Call Booked)

---

## Pattern notes (for the generation prompt)

- The three risk-reversal types all appear in winners: guarantee+refund (line 1),
  pay-after-result (line 2), pay-per-result (lines 3-6). Free sample / free custom
  sample is the strongest CTA softener (lines 7, 10, 11, 15).
- Winning CTAs ask permission to SEND something (Loom, breakdown, one-pager,
  sample) — almost never "book a call" directly. Ask-to-send converts.
- Quantified outcomes recur: "30 qualified leads in 90 days", "30+ qualified leads
  every month", "six figures a month", "90% less cost".
- Problems are stated as consequences: budget burned before pipeline shows,
  growth capped at existing referrals, paying more after a pricing update.
