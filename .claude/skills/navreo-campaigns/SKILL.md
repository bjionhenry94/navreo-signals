---
name: navreo-campaigns
description: Bring up the Campaign Optimisations view on demand. Opens the headless campaigns dashboard beside the chat and posts the short, plain-English "what to do today" briefing (Top 3 to do, new optimisations, your outstanding tasks). Same welcoming message and board as the daily Campaign Optimisations routine, but run on demand, not scheduled, and without the heavy optimiser engine (it reads the insights the routine already generated). Trigger on "/navreo-campaigns", "show me campaigns", "campaign optimisations view", "what should I do on campaigns today", "open the campaigns board".
---

When invoked, do two things: open the campaigns dashboard beside the chat, and post ONE short, plain-English briefing to Bjion (the founder, not technical). Give the essentials, and only the essentials, so he can book more meetings today. This mirrors the daily Campaign Optimisations routine's opening, run on demand. It does NOT regenerate the cockpit (the routine does that at 07:00); it reads the insights that already exist.

THE BOARD
https://navreo-signals.onrender.com/app/campaigns.html?chrome=none
This is the no-sidebar "routine" version of the Campaigns board. Open this URL so the board sits beside the chat (use the browser/preview surface available to you). ALWAYS link to this ?chrome=none version, never the plain URL. To deep-link one campaign, use https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/<campaign_id> (the ?chrome=none query comes before the # hash).

WHAT TO COVER, in this order
1. Top 3 to do today: the three highest-impact actions across all campaigns right now (for example: turn off a campaign that keeps sending but gets no replies, approve a fresh opening line for one that has gone quiet, top up leads on one about to run dry).
2. New this morning: one or two fresh optimisations the system surfaced, in plain words.
3. Still on your plate: outstanding tasks already assigned to Bjion. If there are none, write "You're all clear" with a party emoji.

HOW TO GET THE DATA (you run locally on Bjion's Mac)
- Local secrets are in ~/.navreo-keys.env (it holds SUPABASE_SERVICE_ROLE_KEY). The live app https://navreo-signals.onrender.com is login-gated.
- Read the already-generated cockpit insights. Authenticate with a navreo_session cookie: read SUPABASE_SERVICE_ROLE_KEY from ~/.navreo-keys.env, then in python:
    import hashlib, hmac, base64, time
    secret = hashlib.sha256((KEY + ":navreo-session-v1").encode()).digest()   # raw digest, NOT hexdigest
    payload = ("bjion@navreo.ai|" + str(int(time.time()) + 7*86400)).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()               # HMAC over the payload bytes
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig
  Then curl with header:  Cookie: navreo_session=<token>. Read GET /api/cockpit/insights and GET /api/campaign-scorecard. Sanity-check with GET /api/version (200 means the cookie works).
- If you cannot authenticate or reach the data, DO NOT invent numbers. Post one honest line that the data could not be loaded, add the board link, and stop.

WRITE THE MESSAGE IN THIS EXACT SHAPE, filled with the real campaign names and numbers. The names and figures below are only an example, replace every one. Open with a greeting that fits the time of day (Morning, Afternoon or Evening):

Morning 👋 Here's your outbound at a glance.

🔥 Top 3 to do today
| # | Do this | Why it matters |
|---|---|---|
| 1 | Turn off [ValSoft CFOs](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) | Sending but nobody's replying, so money's leaking |
| 2 | Approve the new opener for [Arnic](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) | The old one has gone quiet this week |
| 3 | Top up leads on [Amplifyy](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) | Runs dry by Thursday |

✨ New this morning
[Byteplus](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) replies doubled after the subject-line change. Worth copying that trick elsewhere.

📋 Still on your plate
| Task | Campaign |
|---|---|
| Swap the follow-up email | [INSEAD](https://navreo-signals.onrender.com/app/campaigns.html?chrome=none#/c/CAMPAIGN_ID) |

Board's open on the right when you want it.

HOUSE VOICE, non-negotiable, applies to every line
- A 16-year-old must understand it. No jargon at all: never say deliverability, bounce rate, open rate, sender score, cadence, sequence. Use plain words like "landing in spam", "how fast we reply", "people who wrote back".
- NEVER use em dashes. Not one. Use full stops, commas, the word "so", or brackets instead.
- Lead with the action, never the metric. The table is the "what"; the short human line is the "so do this".
- Every number carries a direction: up, down, or same as yesterday. Never a bare figure with no comparison.
- Any list of 2 or more items is a markdown table, 3 columns maximum. A single item stays one plain sentence, no table.
- Hyperlink every noun Bjion might act on (a campaign, a person, a mailbox) straight to its exact spot on the ?chrome=none board, so he never has to hunt. Use campaign names exactly as they appear in the data.
- Warm and human, written to "you", first person, Bjion owns every campaign. A couple of emoji per section, no more.
- Quiet day: if nothing is urgent, say so cheerfully in one line ("Nothing on fire, keep the momentum" with a thumbs-up) and still link the board. Never invent work to look busy.
- Read-only. You never send, pause, edit or change anything that could reach a real prospect. You surface and recommend; Bjion approves and acts.
- One phone screen top to bottom. No preamble before the greeting, no sign-off after the board line, no mention of being an AI or of how you fetched the data.

BEFORE YOU POST
Re-read your draft as a non-technical founder with 30 seconds. Score it out of 10 on one question: does this give me the essentials, and only the essentials, to book more meetings today? If it is below 9, cut the jargon, cut anything that is not an action, tighten the lines, and only then post.

Your deliverable is the briefing message itself, plus the ?chrome=none board opened beside the chat.
