"""Navreo cold-email voice — the single source of truth for writing an email
that sounds like a real Navreo email a person sent, not a filled-in template.

Extracted from server.py's offer_email() (2026-07-18) so any endpoint or tool
can reuse the exact same voice. Behaviour is byte-identical to the shipped
Offer Maker preview writer.

Reuse:
    from navreo_voice import build_email_prompt, validate_email
    prompt, template, lead_magnet = build_email_prompt(fields, domain, audience)
    # ... call gpt-5-mini (reasoning_effort='low') with prompt, scrub the reply ...
    validate_email(email, lead_magnet)   # raises ValueError on any rule miss

Or, with your own transport, in one call:
    ok, email, template, err = write_navreo_email(fields, domain, audience,
                                                  llm_call=my_call, scrub=my_scrub)

`fields` is a dict with: name, problem, differentiator, pricing, risk_reversal,
mechanism (lead_magnet | pay_after_result | pay_per_result | guarantee_refund),
stipulation, opener.

The voice + rules are backed by 155 real first-touch Navreo emails that earned
positive replies (Supabase sent_messages, mined 2026-07-18). Full corpus +
profile: the `offer-email-voice-match` skill (voice-corpus.md).
"""
import hashlib
import re

# Real Navreo first-touch emails that earned interested replies (identities
# placeholdered). Few-shot voice references so the email reads like a human
# wrote it. Full corpus: offer-email-voice-match skill.
NAVREO_VOICE_EMAILS = '''\
VOICE: warm, casual, first-name greeting, contractions everywhere, 3-4 short
paragraphs, concrete numbers as proof, a little self-deprecation. Openers VARY
(a POC apology, a genuine observation about them, a market-noise line) - never
the same canned line twice. There is almost always a middle "It includes.../We
use..." elaboration line. CTAs vary and are warm ("Should I send it over?",
"Can I share it?", "Would you be open to a short video on how we'd do it for
[Company]?"). No em-dashes.

Real examples (learn the FEEL, never copy the wording):

--- a resource offer (lead magnet) ---
Hey Marcus,

Apologies if this isn't relevant, wasn't sure who at Brightwave was the best person for this.

I've put together a brief guide on how wholesalers are using AI to spot brands actively looking for new marketplace partners.

It includes a case study on how we helped a similar brand find companies scaling into new channels.

Should I send it over?

--- a resource offer with a proof-packed middle line ---
Hello Dana,

Saw you were doing a bit of cold outreach and thought this might land well.

We've put together a one-pager on the signal-based outbound system we use to generate serious pipeline for clients, without leaning on generic cold lists.

It includes the exact build, the best-performing triggers, and real campaign stories you can use to pull in 30 high-intent leads a month.

Can I send it over?

--- a service pitch with pay-per-result woven in ---
Hi Rita,

Saw you were working with a number of international brands and so wanted to reach out.

If we could open conversations with the buyers actively scoping new suppliers, and you only pay for the qualified leads after they show up, would you be open to a two-minute video on how we'd do it for Tattva?

We use exhibitor lists from international trade shows to find companies scaling into new markets.

--- a pay-after-result pitch, casual ---
Hey Priya,

Apologies if this isn't relevant, wasn't sure who the best person at Ninth Wave would be.

What if we could build you a lead engine that added 30+ qualified leads a month, without you hiring a BDR team?

You only pay after we've built it, so nothing upfront at all.

Could I send a one-pager explaining how it works?

--- a guarantee, understated ---
Hi Paul,

There's so much noise right now about which tools to use for going to market, so I wanted to reach out.

I recorded a short video for your team showing what we'd set up to book more meetings with retail and eCommerce leaders.

If it fits, we can run it for you and guarantee 30 qualified leads in 90 days or you get a full refund.

Can I share it?'''

_EMAIL_FIELD_KEYS = ("name", "problem", "differentiator", "pricing",
                     "risk_reversal", "mechanism", "stipulation", "opener")


def build_email_prompt(fields: dict, domain: str = "", audience: str = ""):
    """Build the full gpt-5-mini prompt for one Navreo cold email.

    Returns (prompt, template_name, lead_magnet_bool). Deterministically rotates
    the opener / CTA / P.S archetype by hashing the offer name so a page of
    offers spreads across styles instead of sharing one skeleton."""
    fields = {k: str(fields.get(k) or "").strip()[:600] for k in _EMAIL_FIELD_KEYS}
    audience = str(audience or "").strip()[:300]
    domain = str(domain or "").strip()[:120]
    who = f"The business sending this email is {domain}." if domain else ""
    aud = (f"They sell to: {audience}. Write the email to a realistic example person in that group."
           if audience else "Write the email to a realistic example person in the buyer group this offer targets.")
    # Template law: each mechanism maps to exactly ONE house template
    # (lilly-copywriter). Lead-magnet offers use the Lead Magnet template; the
    # three risk-reversal mechanisms use the Service Pitch template.
    lead_magnet = fields["mechanism"] == "lead_magnet"
    template_name = "lead_magnet" if lead_magnet else "service_pitch"
    # Cross-email variety: independent per-offer calls otherwise share one
    # skeleton and the SET reads templated (copywriter panel 2026-07-18).
    h = int(hashlib.md5(fields["name"].encode()).hexdigest(), 16)
    OPENERS = [
        "an observation about something specific they'd plausibly be doing right now (a launch, a hire, expansion, a busy season) - warm, not researched-sounding",
        "a light 'wasn't sure who the right person for this was' apology - vary the wording from the examples",
        "a market-noise line ('there's so much noise right now about X') that sets up the problem warmly",
        "a friendly 'noticed X about your world and thought of you' line tied to their situation",
        "a 'saw you were doing X and thought this might land' observation",
    ]
    CTAS = ([  # resource emails: offer to SEND the thing
        "Should I send it over?",
        "Can I share it?",
        "Want me to send it across?",
        "Should I send the details over?",
    ] if lead_magnet else [  # pitches: offer a tiny next artifact
        "Would you be open to a quick two-minute video on how we'd do it for their company?",
        "Could I send a short one-pager explaining how it works?",
        "Want me to send the details across?",
        "Can I send over how it'd work for them?",
        "Worth me sending a quick rundown?",
        "Happy to send over the specifics if useful?",
    ])
    PSS = [
        "a one-line P.S with an invented client and a concrete result the sender could measure",
        "no P.S at all - just the sign-off",
        "a one-line P.S naming a plausible client and a simple outcome",
    ]
    pick_opener = OPENERS[h % len(OPENERS)]
    pick_cta = CTAS[(h // 7) % len(CTAS)]
    pick_ps = PSS[(h // 13) % len(PSS)]
    variety_note = (f"FOR THIS EMAIL specifically (so a page of offers doesn't all sound the same):\n"
                    f"- Open with {pick_opener}.\n"
                    f"- Shape the CTA like: \"{pick_cta}\" (adapt naturally, keep it this short).\n"
                    f"- P.S: {pick_ps}.\n")
    if lead_magnet:
        template_block = """THIS IS A RESOURCE (LEAD-MAGNET) EMAIL. Shape it like the resource examples in the voice reference:

1. Greeting: "Hey <first name>," or "Hi <first name>,".
2. Icebreaker: ONE short, warm line. VARY it (a "wasn't sure who the best person at <company> was" apology, a genuine observation about them, or a market-noise line). Do not pitch here.
3. Problem line: ONE short line naming the problem the offer fixes, phrased warmly ("Most <their kind of company> find that <problem>" or "The tricky part is <problem>"). It sets up the offer - the reader should feel the gap before you offer the fix. This is REQUIRED, always between the icebreaker and the offer.
4. The offer: name the free thing and offer it in a human way, as the answer to that problem. Describing what it covers is GOOD ("a brief guide on how X are using Y to..."). Often a short elaborating line - "It includes...", "It features..." - with a concrete proof point. Make clear it costs them nothing, said naturally ("no charge", "on us", "nothing needed from you").
5. A warm one-question CTA to SEND it: "Should I send it over?" / "Can I send it over?" / "Can I share it?".
6. Sign-off first name.
7. Optional P.S with one concrete proof line (an invented client + a result the sender could actually measure).

RULES: exactly one question (the CTA). Never open with the CTA or the offer - the icebreaker is always first. Honest tense: if making the thing needs the recipient's input first, use future tense ("We'd love to put together..."); only past tense ("I've put together...") for something that can exist before you ever speak. Do NOT mention any guarantee, refund, or pay terms - the only promise is that it costs nothing. NEVER write eligibility or fine print ("matched to an agreed list of...", "applies to...", conditions) - keep it warm, not a spec. Avoid the bare word "free" and the phrase "no obligation" (Navreo says "no charge" / "at no cost"). Keep the whole thing tight, roughly 45-80 words."""
    else:
        template_block = """THIS IS A PITCH EMAIL for a paid offer (its mechanism is stated above). Shape it like the pitch examples in the voice reference:

1. Greeting: "Hey <first name>," or "Hi <first name>,".
2. Icebreaker: ONE short, warm line. VARY it every time - a genuine observation about them, a "wasn't sure who the best person was" apology, or a market-noise line. It does NOT have to end "so I wanted to reach out". Do not pitch here.
3. Problem line: ONE short line naming the problem the offer fixes, phrased warmly ("Most <their kind of company> find that <problem>" or "The tricky part is usually <problem>"). REQUIRED, always between the icebreaker and the pitch - it sets up why the offer matters.
4. The pitch, as the answer to that problem. VARY how you open it - do NOT start every email "What if we could" or "If we could" (that is the #1 template tell). Rotate naturally: sometimes state the outcome as a plain sentence ("You could be booking meetings with those buyers, and only paying once they show up."), sometimes a short "If we could... would you be open to...?" conditional, sometimes lead with what you'd do. Name a real, specific outcome, not a generic one.
5. Optionally a short supporting line ("We use...", "It works by...").
6. Sign-off first name, and a P.S with one concrete proof line (invented client + a result the sender could measure).

RULES: the promise is ONLY this offer's mechanism, said in ONE warm human clause (use guarantee/refund only if the mechanism is guarantee_refund; "you only pay after we've built it, so nothing upfront" / "you only pay per booked meeting" for the pay mechanisms). NEVER write terms, fine print or eligibility into the email - NO "it applies to...", "payment due within X days", "invoiced upfront", "standard pricing applies", "the guarantee only kicks in", "bookings must be confirmed within...", "after onboarding", no unit minimums or dollar thresholds. The one fair condition from the offer stays OUT of the email entirely; it is not the reader's problem yet. The closing ask is tiny and warm ("a two-minute video on how we'd do it for <their company>", "a quick one-pager explaining how it works", "seeing the details"). Never "book a call". Keep the pitch readable - if it sprawls past ~30 words, break out a supporting line rather than cramming."""
    prompt = f"""You are Navreo's house cold-email copywriter. Write ONE complete, ready-to-send cold email for the single offer below that sounds exactly like a real Navreo email a person sent - warm, human, specific - NOT a filled-in template.

Here is how Navreo actually writes (study the feel, the openers, the rhythm, the CTAs - never copy the wording):
{NAVREO_VOICE_EMAILS}

{who}
{aud}

THE OFFER (its one mechanism is: {fields['mechanism']}):
- Name: {fields['name']}
- Problem it solves (the NEW business the buyer is missing): {fields['problem']}
- What we would do and why it is better: {fields['differentiator']}
- Pricing angle: {fields['pricing']}
- The promise: {fields['risk_reversal']}
- One fair condition: {fields['stipulation']}
- Suggested opening line: {fields['opener']}

{template_block}

{variety_note}
HARD RULES (always):
- Say it once. NO over-explaining - do not add "That means...", "That lets you...", "which makes it easy to...", or stacked benefit sentences unpacking the offer. One crisp line of what it is, one short line of proof or how, then the ask. If you catch yourself explaining the benefit of the benefit, cut it.
- Do not write a triple list ("a simple pick, a quick ship, and a 14-day refund") - it reads assembled. One concrete detail beats three.
- State the pay-term or guarantee in ONE short clause and NEVER again - not restated in the pitch and again in a following sentence, not echoed in the P.S. Say it once, move on. ("you only pay after we launch the system" then "you pay nothing until we finish and launch the system" is the same point twice - delete one.)
- Do not repeat the offer's key noun (e.g. "per-site", "bestseller pack", "the outreach system") more than twice in the whole email - if it shows up three times you are over-explaining.
- Never use a colon set-up like "What we do is simple:" or "Here's how it works:" - just say it.
- NEVER write the offer's name as a capitalised product label ("a Pay After First Clean option", "our Viewing Clean service") - just describe what you'd do in lower-case plain words.
- Do NOT end the opener with "so I wanted to reach out" - it has become a tell. Reach for any of the other opener moves instead.
- Fill EVERY part with concrete, realistic values. Invent a realistic recipient first name, a realistic example company name, and a realistic sender first name. NEVER leave {{{{first_name}}}}, {{{{company}}}}, or any [square-bracket blank] in the email.
- The P.S proof line (when you use one) names a PLAUSIBLE INVENTED client - never a real well-known company. The proof must be something THIS business could measure ITSELF (meetings booked, days to turn a unit around, shipments on time), never the client's own downstream outcomes (their contract wins, footfall, revenue) which a vendor cannot know.
- ONE mechanism only: the email carries this offer's mechanism and nothing from any other (the P.S proof line is proof, not a second promise).
- The benefit is always NEW money coming in - never "win back", "recover lost", or "stop losing".
- Plain, warm English a busy person reads in five seconds. Contractions are good. NO em-dashes anywhere. Vary sentence length. Do not sound like a form.
- Real line breaks between paragraphs.

Reply with ONLY a JSON object, no fences, no commentary: {{"email": "<the full email, with real line breaks>"}}"""
    return prompt, template_name, lead_magnet


def validate_email(email: str, lead_magnet: bool):
    """Raise ValueError if the email breaks a substance or voice rule. Returns
    None when the email passes. Mirrors the shipped Offer Maker validator."""
    if len(email) < 60 or not re.match(r"(Hi|Hey|Hello) ", email):
        raise ValueError("email too short or malformed")
    if re.search(r"[—–]", email):
        raise ValueError("em-dash in email")
    if re.search(r"\{\{|\[[a-z ]+\]|first_name|square-bracket", email, re.I):
        raise ValueError("merge tag or bracket blank leaked")
    # Fine-print / contract language is the biggest voice-killer.
    if re.search(r"\bit applies to\b|\bapplies to (?:orders|new|accounts)\b"
                 r"|payment due|invoiced? upfront|invoice normally"
                 r"|standard (?:wholesale )?pricing applies|only kicks in"
                 r"|must be confirmed within|within \d+ days of|after onboarding"
                 r"|orders? (?:of|over) \d|\d+ units each", email, re.I):
        raise ValueError("terms/fine-print language in email")
    # The line after the greeting must be an icebreaker, never the CTA.
    lines = [l.strip() for l in email.splitlines() if l.strip()]
    if len(lines) > 1 and (lines[1].endswith("?") or
            re.match(r"(?:Can|May|Could|Would|Want|Should)\b.*\?", lines[1])):
        raise ValueError("email opens with the CTA")
    # Structure law: icebreaker -> problem -> offer. Require >= 3 content blocks.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", email) if b.strip()]
    content = [b for b in blocks[1:]  # drop greeting
               if not re.match(r"^(P\.?S|Best|Thanks|Cheers|Warm|Kind|All the best)", b, re.I)
               and len(b.split()) >= 6]
    if len(content) < 3:
        raise ValueError(f"missing the icebreaker->problem->offer structure ({len(content)} content blocks)")
    if re.search(r"so I wanted to reach out", email, re.I):
        raise ValueError("overused 'so I wanted to reach out' opener tell")
    if re.search(r"You're probably missing|You are probably missing", email, re.I):
        raise ValueError("presumptuous accusatory opener")
    if re.search(r"\b(?:What we do is simple|here's how it works|here is how it works)\b\s*:", email, re.I):
        raise ValueError("colon set-up phrase (pitch-deck tell)")
    if not lead_magnet:
        if re.search(r"^\s*What if we could\b", email, re.M):
            raise ValueError("banned 'What if we could' template opener")
        if "If we could" in email and not re.search(r"\?", email):
            raise ValueError("If-we-could never resolves to a question")
        if re.search(r"\baudit\b", email, re.I):
            raise ValueError("audit wording (banned offer type)")
    if lead_magnet:
        if not re.search(r"no charge|no cost|on us|without charge|no commitment|nothing needed|nothing to pay|at no", email, re.I):
            raise ValueError("lead magnet email missing the no-strings promise")
        if email.count("?") != 1:
            raise ValueError(f"lead magnet has {email.count('?')} questions, need exactly 1")


def write_navreo_email(fields: dict, domain: str, audience: str,
                       llm_call, scrub=lambda s: s, attempts: int = 3):
    """Full reuse helper for any Python caller with its own transport.

    llm_call(prompt) -> the model's raw text reply (a JSON object string).
    scrub(str) -> str applies your house text hygiene (e.g. em-dash removal).
    Returns (ok, email_or_None, template_name, error_str)."""
    import json
    prompt, template_name, lead_magnet = build_email_prompt(fields, domain, audience)
    err = ""
    for _ in range(max(1, attempts)):
        try:
            text = (llm_call(prompt) or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            email = scrub(json.loads(m.group(0) if m else text).get("email", ""))
            validate_email(email, lead_magnet)
            return True, email, template_name, ""
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
    return False, None, template_name, err
