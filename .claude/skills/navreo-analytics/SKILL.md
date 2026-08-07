---
name: navreo-analytics
description: Bring up the Daily Analytics view on demand. Opens the headless analytics (deliverability) board beside the chat and posts a short, plain-English briefing (3 most urgent insights, the biggest leak where meetings are lost, and any urgent inbox-landing issue). Same welcoming message and board as the daily Daily Analytics routine, but run on demand, not scheduled. Trigger on "/navreo-analytics", "show me analytics", "what are the numbers telling me", "open the analytics board", "any deliverability issues".
---

When invoked, do two things: open the analytics board beside the chat, and post ONE short, plain-English briefing to Bjion (the founder, not technical) of what the numbers are telling him. Give the essentials, and only the essentials, so he can book more meetings today. This mirrors the daily Daily Analytics routine's opening, run on demand.

THE BOARD
https://navreo-signals.onrender.com/app/deliverability.html?chrome=none
This is the no-sidebar "routine" version of the Analytics board. Open this URL so the board sits beside the chat (use the browser/preview surface available to you). ALWAYS link to this ?chrome=none version, never the plain URL. When an insight points at a specific campaign, deep-link that campaign on the campaigns board instead: https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/<campaign_id>.

WHAT TO COVER, in this order
1. 3 things worth your eyes today: the three most urgent insights from the numbers, in plain words (for example: a campaign whose replies are climbing and deserves more leads, one that has gone quiet, a pattern like more people opening but fewer replying).
2. Where you're losing meetings: the single biggest leak, the one place interested people fall through (for example: people who reply "interested" but get no same-day follow-up).
3. Anything urgent with landing in inboxes: a plain-English deliverability flag. If a mailbox or domain has started hitting spam, say which and what to do. If all is well, say so in one calm line.

HOW TO GET THE DATA (you run locally on Bjion's Mac)
- The signals repo is at ~/navreo-signals. Local secrets are in ~/.navreo-keys.env (it holds SUPABASE_SERVICE_ROLE_KEY). The live app https://navreo-signals.onrender.com is login-gated.
- The insights, leaks and inbox-landing health are what the Analytics board shows. Read ~/navreo-signals/app/deliverability.html, app/deliverability-tab.js and any /api/client-windows or deliverability endpoints to find the exact data the board calls. Prefer those. Note: DELIV_MOCK is a local-only test switch, the live site serves real data, so never mention mock data.
- Authenticate with a navreo_session cookie: read SUPABASE_SERVICE_ROLE_KEY from ~/.navreo-keys.env, then in python:
    import hashlib, hmac, base64, time
    secret = hashlib.sha256((KEY + ":navreo-session-v1").encode()).digest()   # raw digest, NOT hexdigest
    payload = ("bjion@navreo.ai|" + str(int(time.time()) + 7*86400)).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()               # HMAC over the payload bytes
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig
  Then curl with header:  Cookie: navreo_session=<token>. Sanity-check with GET /api/version (200 means the cookie works).
- If you cannot authenticate or reach the data, DO NOT invent numbers. Post one honest line that the data could not be loaded, add the board link, and stop.

WRITE THE MESSAGE IN THIS EXACT SHAPE, filled with the real names and numbers. The names and figures below are only an example, replace every one. Open with a greeting that fits the time of day (Morning, Afternoon or Evening):

Morning 👋 Here's what your numbers are telling you.

⚠️ 3 things worth your eyes today
| # | Insight | What it means |
|---|---|---|
| 1 | [Arnic](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) replies are climbing | Your best performer, so feed it more leads |
| 2 | [ValSoft](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) quiet 3 days running | Message has gone stale, so freshen it |
| 3 | [More opens, fewer replies](https://navreo-signals.onrender.com/app/deliverability.html?chrome=none) | The opener lands, the ask doesn't |

🕳️ Where you're losing meetings
Loads of people reply "interested" but get no same-day follow-up. That's the biggest gap right now.

🚨 Anything urgent with landing in inboxes?
Heads up: the [navreo.co mailboxes](https://navreo-signals.onrender.com/app/deliverability.html?chrome=none) started hitting spam overnight. Worth pausing them before it drags the others down.
(On a clean day this line reads: "All clear, your emails are landing in the main inbox" with a thumbs-up.)

HOUSE VOICE, non-negotiable, applies to every line
- A 16-year-old must understand it. No jargon at all: never say deliverability, bounce rate, open rate, sender score, SPF, DKIM. Use plain words like "landing in spam", "how many wrote back", "where people fall through".
- NEVER use em dashes. Not one. Use full stops, commas, the word "so", or brackets instead.
- Lead with the action, never the metric. The table is the "what"; the short human line is the "so do this".
- Every number carries a direction: up, down, or same as yesterday. Never a bare figure with no comparison.
- Any list of 2 or more items is a markdown table, 3 columns maximum. A single item stays one plain sentence, no table.
- Hyperlink every noun Bjion might act on (a campaign, a mailbox, a leak) straight to its exact spot on the right board, so he never has to hunt.
- Warm and human, written to "you", first person, Bjion owns every campaign. A couple of emoji per section, no more.
- Quiet day: if nothing is urgent, say so cheerfully and still link the board. Never invent problems to look useful.
- Read-only. You never send, pause, edit or change anything that could reach a real prospect. You surface and recommend; Bjion approves and acts.
- One phone screen top to bottom. No preamble before the greeting, no sign-off after the last line, no mention of being an AI or of how you fetched the data.

BEFORE YOU POST
Re-read your draft as a non-technical founder with 30 seconds. Score it out of 10 on one question: does this give me the essentials, and only the essentials, to book more meetings today? If it is below 9, cut the jargon, cut anything that is not an insight or an action, tighten the lines, and only then post.

Your deliverable is the briefing message itself, plus the ?chrome=none board opened beside the chat.
