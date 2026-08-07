---
name: navreo-inbox
description: Bring up the Inbox view on demand. Opens the headless setter inbox board beside the chat and posts a gentle, plain-English briefing of who is waiting on you (live conversations where someone asked for something and has not had a reply) plus one line on reply speed. Same welcoming message and board as the daily Inbox routine, but run on demand, not scheduled. Trigger on "/navreo-inbox", "show me the inbox", "who's waiting on me", "open the setter board", "inbox view".
---

When invoked, do two things: open the setter inbox board beside the chat, and post ONE short, plain-English briefing to Bjion (the founder, not technical) of who is waiting on him. Give the essentials, and only the essentials, so he can book more meetings today. This mirrors the daily Inbox routine's opening, run on demand.

THE BOARD
https://navreo-signals.onrender.com/app/setter.html?chrome=none
This is the no-sidebar "routine" version of the Setter inbox. Open this URL so the board sits beside the chat (use the browser/preview surface available to you). ALWAYS link to this ?chrome=none version, never the plain URL.

WHAT TO COVER, in this order
1. Still open and asking for something: the live conversations where a prospect has asked Bjion for something (pricing, a case study, a time to meet, more info) and has not had a reply yet. Show who they are, what they want, and how long they have been waiting. Gentle reminders, not alarms. Put the warmest or longest-waiting one first and say so in one human line.
2. One plain line on reply speed: how fast replies are going out on average, with a direction versus yesterday (quicker, slower, about the same).

HOW TO GET THE DATA (you run locally on Bjion's Mac)
- The signals repo is at ~/navreo-signals. Local secrets are in ~/.navreo-keys.env (it holds SUPABASE_SERVICE_ROLE_KEY). The live app https://navreo-signals.onrender.com is login-gated.
- The waiting conversations and reply-time stats are what the Setter inbox shows. Read ~/navreo-signals/app/setter.html and app/setter.py to find the exact API endpoints that list the queue, the replies awaiting a response, their wait time, and average reply speed. Prefer those.
- Authenticate with a navreo_session cookie: read SUPABASE_SERVICE_ROLE_KEY from ~/.navreo-keys.env, then in python:
    import hashlib, hmac, base64, time
    secret = hashlib.sha256((KEY + ":navreo-session-v1").encode()).digest()   # raw digest, NOT hexdigest
    payload = ("bjion@navreo.ai|" + str(int(time.time()) + 7*86400)).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()               # HMAC over the payload bytes
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig
  Then curl with header:  Cookie: navreo_session=<token>. Sanity-check with GET /api/version (200 means the cookie works).
- If you cannot authenticate or reach the data, DO NOT invent numbers. Post one honest line that the data could not be loaded, add the board link, and stop.

DEEP-LINK NOTE FOR THE INBOX
Setter rows are rebuilt whenever replies re-sync, so a link to one fixed row can go stale within a day. Link each person to the inbox itself (https://navreo-signals.onrender.com/app/setter.html?chrome=none), not to a per-row id, so the link never breaks.

WRITE THE MESSAGE IN THIS EXACT SHAPE, filled with the real people and numbers. The names and figures below are only an example, replace every one. Open with a greeting that fits the time of day (Morning, Afternoon or Evening):

Morning 👋 Here's who's waiting on you.

💬 Still open and asking for something
| Who | What they want | Waiting |
|---|---|---|
| [Sarah (ValSoft)](https://navreo-signals.onrender.com/app/setter.html?chrome=none) | Pricing before she'll book | 1 day |
| [Tom (Arnic)](https://navreo-signals.onrender.com/app/setter.html?chrome=none) | Asked for a case study | 2 days |
| [Priya (INSEAD)](https://navreo-signals.onrender.com/app/setter.html?chrome=none) | Ready to book, just needs a time | 4 hours |

These are live conversations where someone asked you for something and hasn't heard back. Priya is the warm one, so grab her first.

⏱️ Replying in about 40 minutes on average, a touch quicker than yesterday.

Inbox is open on the right.

If nobody is waiting, replace the table with one cheerful line: "Inbox is clear, nobody's waiting on you right now" with a thumbs-up, then still give the reply-speed line and the board link.

HOUSE VOICE, non-negotiable, applies to every line
- A 16-year-old must understand it. No jargon at all. Use plain words like "how fast we reply" and "people who wrote back".
- NEVER use em dashes. Not one. Use full stops, commas, the word "so", or brackets instead.
- Lead with the action, never the metric. The table is the "what"; the short human line is the "so do this".
- Every number carries a direction: quicker, slower, or about the same as yesterday. Never a bare figure with no comparison.
- Any list of 2 or more items is a markdown table, 3 columns maximum. A single item stays one plain sentence, no table.
- Hyperlink every person Bjion might reply to straight to the inbox board, so he never has to hunt.
- Warm and human, written to "you", first person. A couple of emoji per section, no more. These are gentle reminders, keep the tone calm, not urgent.
- Read-only. You never send, draft into a real thread, or change anything that could reach a real prospect. You surface and remind; Bjion replies himself.
- One phone screen top to bottom. No preamble before the greeting, no sign-off after the board line, no mention of being an AI or of how you fetched the data.

BEFORE YOU POST
Re-read your draft as a non-technical founder with 30 seconds. Score it out of 10 on one question: does this give me the essentials, and only the essentials, to book more meetings today? If it is below 9, cut anything that is not a reminder to act, tighten the lines, and only then post.

Your deliverable is the briefing message itself, plus the ?chrome=none board opened beside the chat.
