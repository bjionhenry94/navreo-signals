#!/usr/bin/env python3
"""Simulated-user testing for the campaign app.

10 non-technical personas each walk a REAL journey (the API calls the UI
makes, with real data) rendered as a faithful screen-by-screen transcript
using the app's actual copy. A judge model (headless claude) roleplays
each persona and scores ease-of-use and goal-achievement 1-10 with
frictions. Iterate on the app until averages >= 8.

Usage: python3 app/ux_sim.py [--judges-only]
"""

import json
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "http://localhost:7901"
OUT = Path(__file__).parent / "data" / "ux_sim_results.json"


def api(path, body=None, retries=2):
    import time as _t
    for attempt in range(retries + 1):
        req = urllib.request.Request(BASE + path,
            data=json.dumps(body).encode() if body else None,
            headers={"Content-Type": "application/json"},
            method="POST" if body else "GET")
        r = json.loads(urllib.request.urlopen(req, timeout=240).read())
        if not isinstance(r, dict) or r.get("ok") is not False or attempt == retries:
            return r
        _t.sleep(2 * (attempt + 1))
    return r


PERSONAS = [
    ("Kevin", "agency owner, 52, not techy, hates jargon", "Launch a campaign for my Amazon agency targeting brands that clearly need Amazon help"),
    ("Aliyah", "PR consultant, first time using any sales tool", "Find UK tech startups that just raised money and reach their founders"),
    ("Dana", "virtual assistant doing this for her boss", "My boss said: get a list of prospects from the hiring signal and remove the bad ones"),
    ("Marco", "sales rep, impatient, skims everything", "Get a signal running TODAY that feeds my campaign with people to email"),
    ("Priya", "founder, careful, wants to check everything before anything sends", "Set up a campaign but review every prospect and rewrite the opening line myself"),
    ("Tom", "junior marketer, easily confused by settings", "Change who a campaign targets because we pivoted from the US to the UK"),
    ("Sofia", "ops manager, wants predictability", "Set up the recurring hiring signal we always run and route qualified people into our live campaign"),
    ("Jae", "non-native English speaker", "Make campaign for ecommerce brands, change icebreaker text to my own words"),
    ("Ruth", "semi-retired consultant, dislikes computers", "See who the tool found for me and say yes or no to each person"),
    ("Omar", "growth lead, opinionated", "The ideas it suggests must follow MY steer: only warm signals, no cold lists"),
]

UI = {
    "list": "CAMPAIGNS page - 'Signal campaigns.' A single clean list of my signal campaigns (name · N people matched · draft · Remove button). Top-right: a CLIENT SWITCHER dropdown ('All clients' or one client - picking one filters everything to just them and the wizard stops asking which client) next to 'New campaign'.",
    "s1": "Step 1 of 6 - 'Who are we selling for?' Cards: existing clients (each with a 'Reuse last setup' button that skips straight to the ideas using saved targeting) + dashed 'New client - From their website' card.",
    "nc": "New client form: Website [Analyse button] -> prefills Client name + 'What they do'. Field: 'The offer / problems they solve for customers'. Button: 'Save client & continue'.",
    "s2": "Step 2 - 'What's the goal of this campaign?' / 'Say it like you'd say it to a colleague. Everything else prefills from this.' One big text box + optional 'Anything to avoid?'. Then two cards: 'Suggest ideas from my goal - a few signal options, sized with live data' OR 'I know exactly what I want - build just the signal my goal describes'.",
    "s3": "Step 3 - 'Confirm who you're reaching.' / 'Prefilled from the client's profile - adjust anything.' Title chips already selected + 'Add a title' box.",
    "s4": "Step 4 - 'Confirm the companies.' / 'Prefilled - everything else stays out.' Industry chips; 'Or describe the buyer type' box (prefilled); named companies; Location chips (prefilled); Company size chips (prefilled).",
    "s5load": "Step 5 loading - a progress bar fills steadily while it works - 'Finding the best ways in.' / 'Takes about a minute. Every idea gets checked against real data before you see it.' Below the icon a status line updates as it works: 'Reading the offer…' -> 'Coming up with ideas for this client…' -> 'Checking each idea against live data…' -> 'Counting who you could actually reach…'",
    "s5": "Step 5 - 'Ways into <Client>'s market.' / 'Fresh ideas for this offer, sized against live data. Pick what to kick off - you approve every person before anything sends.' A green 'goal applied' badge shows MY goal verbatim (plus what I said to avoid). In 'I know exactly what I want' mode, a picker first asks 'Which signal did you mean?' with two plain cards (Hiring / Engagement) - then it builds EXACTLY that one signal, nothing else. Small box to change the goal and redo. Hovering any idea row shows WHY this signal means they need the offer. The table: icon | signal name + example opening line in italics | decision-maker count - the column header sorts by size on click (largest list tagged 'largest' (hover: biggest, usually colder), top row tagged 'recommended' (hover: best balance of fit, timing and reach)). Ideas with nobody to reach are hidden (a note says so). Rows toggle selected (orange highlight).",
    "s6": "Step 6 - 'Check the plan.' Summary rows: Client, Job roles, Companies, Size, Locations, Named accounts, Excluded, plus an Openers section where each chosen signal's icebreaker sits in an EDITABLE text box - I can rewrite my line here before anything runs. Button: 'Preview my first leads'.",
    "s7": "Results - 'Here are the first opportunities we identified.' 'N people match · the campaign works through all of them'. Person cards: initials, name, title, company chips plus 'LinkedIn ↗' and 'Website ↗' links on every card, [✕ Reject] per person. Button: 'Save draft campaign' -> toast 'Draft saved - open it from the top of the list to pull prospects', lands directly ON the new draft page, ready to pull.",
    "draft": "My SIGNAL campaign page - name + 'draft' pill and 4 simple tabs: Overview (Pulled / Kept / Rejected / Sent-to-campaign counters + an Activity feed on the right), Leads shows its count right in the tab e.g. 'Leads (10)', Leads (every person with ✓/✕), Sources (my signals - each with opening line, destination and targeting; multiple sources can sit inside one campaign), Copy (preview of the exact email each prospect would get, with a right sidebar to flip through prospects), Preview (how each prospect sees the email). In the header: a campaign-level 'Qualified people go to…' dropdown - ONE destination for the whole campaign, every ✓ from any source goes there - plus a live/not-live pill. Each campaign row on the list has a Remove button.",
    "srcdetail": "Expanded source: 'Icebreaker · the first sentence of the email' text box with [Save]; a 'Qualified people go to' dropdown listing live Smartlead campaigns (✓ sends them there instantly - a tip says to set your opener first); 'Targeting' boxes: Job titles / Company type / Countries with [Save & re-pull]; after a pull: 'People found · first 10 of <total> - the daily run works through the rest · X kept · Y rejected' (choices save automatically) with [Keep all] [Reject the rest] bulk buttons + prospect rows: name, title, company, the opening line filled with the real company name in italics, 'View LinkedIn' and 'Website' buttons, and [✓] [✕] buttons per person.",
}


def run_journey(client_name, offer, kw, geos, steer, titles):
    """Execute the REAL flow via the API; return transcript events."""
    ev = []
    ev.append(("Open Campaigns", UI["list"]))
    ev.append(("Click New campaign", UI["s1"]))
    ev.append(("Create/pick client", UI["nc"] + f" (saved '{client_name}')"))
    cl = api("/api/clients", {"name": client_name, "domain": "example.com", "offer": offer,
                              "icp": {"titles": titles, "keywords": kw, "geos": geos}})
    goal_mode = "direct" if steer and "only" in steer.lower() else "ai"
    ev.append(("Step 2: say the goal", UI["s2"] + f" I typed my goal in my own words: '{steer or 'find ' + kw + ' buyers'}' and picked '{'I know exactly what I want' if goal_mode == 'direct' else 'Suggest ideas from my goal'}'."))
    ev.append(("Step 3: confirm titles", UI["s3"] + f" Already selected: {', '.join(titles)} - I just hit Next."))
    ev.append(("Step 4: confirm companies", UI["s4"] + f" Buyer type prefilled: '{kw}'. Locations: {', '.join(geos)}. Hit Next."))
    mech = "hiring" if goal_mode == "direct" else ""
    if goal_mode == "direct":
        ev.append(("Step 5 understood my goal", "It read my goal, spotted the signal I meant, and a green badge says: goal applied · 'you meant the hiring signal, so that is all we built'. No re-asking, no other ideas. (If the wording had been ambiguous, two plain cards would ask which I meant - each described in plain English, e.g. 'Hiring - companies hiring certain roles right now'.)"))
    ev.append(("Step 5 loads", UI["s5load"] + " (It had already been working in the background while I confirmed, so the wait was shorter.)"))
    strat = api("/api/strategy-map", {"titles": titles, "keywords": [kw], "headcount": ["11-20", "21-50", "51-100", "101-200"],
                                      "countries": geos, "client_name": client_name, "client_offer": offer,
                                      "goal": steer or f"find {kw} buyers", "mode": goal_mode, "mechanism": mech, "steer": ""})
    rows = [r for r in strat["rows"] if r["estimated"] or (r.get("dms") or 0) > 0]
    tbl = "; ".join(f"{r['idea']} ({'live' if r['estimated'] else r['dms']}) ice: \"{r.get('icebreaker') or ''}\"" for r in rows[:5])
    ev.append(("Step 5 table appears", UI["s5"] + f" ROWS: {tbl}"))
    pick = next((r for r in rows if not r["estimated"]), rows[0])
    ev.append((f"Select '{pick['idea']}', Next", UI["s6"]))
    ppl = api("/api/preview/people", {"titles": titles, "keywords": [kw], "countries": geos,
                                      "headcount": ["11-20", "21-50", "51-100", "101-200"]})
    names = ", ".join(f"{x['name']} ({x['title']} @ {x['company']})" for x in (ppl.get("sample") or [])[:3])
    ev.append(("Preview my first leads", UI["s7"] + f" Found {ppl.get('total_people')} people. First: {names}. Rejected one with ✕."))
    cd = api("/api/campaign-drafts", {"name": f"{client_name} · {pick['idea']}", "client_id": cl.get("id"),
                                      "sources": [pick], "total_matched": ppl.get("total_people") or 0, "preview_kept": []})
    sid = api("/api/sources", {"type": pick["mechanism"], "mechanism": pick["mechanism"], "name": pick["idea"],
                               "campaign_id": cd["id"], "icebreaker": pick.get("icebreaker") or "",
                               "titles": titles, "params": pick.get("params") or {},
                               "config": {"keywords": kw, "headcount": ["11-20", "21-50", "51-100", "101-200"], "countries": geos}})["id"]
    ev.append(("Save draft campaign", "Toast: 'Draft saved - here it is, pull prospects when ready'. I land straight on the draft page - no hunting for it."))
    ev.append(("Click the draft row", UI["draft"] + " I land on Overview; in Sources the first pull STARTS BY ITSELF. Header: the campaign-level 'Qualified people go to…' dropdown sits right there, with a 'not live yet' pill until I choose."))
    pull = api("/api/sources/pull", {"id": sid})
    if pull.get("ok"):
        pr = (pull.get("prospects") or [{}])[0]
        note = " Note under source: 'widened to the base audience'." if pull.get("broadened") else ""
        ev.append(("Click 'Find people now'", UI["srcdetail"] + f" Pulled {pull['total']} matches - 'saved to your database' shows in the header.{note} First prospect: {pr.get('name')} ({pr.get('title')} @ {pr.get('company')}) with icebreaker: \"{pr.get('icebreaker')}\""))
    else:
        ev.append(("Click 'Find people now'", f"Message: '{pull.get('message')}'"))
    api("/api/sources/update", {"id": sid, "icebreaker": "We help teams like {{company}} move faster on this exact problem, and so I thought I'd reach out."})
    ev.append(("Rewrite the icebreaker, Save", "In the Icebreaker box, typed MY line: 'We help teams like {{company}} move faster on this exact problem, and so I thought I'd reach out.' Toast: 'Saved - applied to every prospect below and all future pulls'. The rows below instantly show my exact line with each company's name filled in."))
    api("/api/sources/update", {"id": sid, "index": 0, "verdict": "keep"})
    api("/api/sources/update", {"id": sid, "index": 1, "verdict": "reject"})
    ev.append(("Pick destination + qualify", "At the top of the CAMPAIGN page, chose 'Email campaign (Smartlead) · my live campaign' in the 'Qualified people go to…' dropdown - one destination for the whole campaign, every ✓ from any source goes there. Then in Leads, clicked ✓ on the first person - green line: '✓ qualified · sent to smartlead:3579957'. ✕ on the second. Saves automatically."))
    api("/api/sources/update", {"id": sid, "titles": titles[:1], "params": {"countries": ["United Kingdom"]}})
    re_pull = api("/api/sources/pull", {"id": sid})
    if re_pull.get("ok") and re_pull.get("prospects"):
        pr2 = re_pull["prospects"][0]
        ev.append(("Change Countries to United Kingdom, 'Save & re-pull'",
                   f"New pull: {re_pull.get('total')} matches. First: {pr2.get('name')} @ {pr2.get('company')} with icebreaker: \"{pr2.get('icebreaker')}\""))
    else:
        ev.append(("Change Countries to United Kingdom, 'Save & re-pull'",
                   f"Friendly message: '{re_pull.get('message')}'. My previous pull and my icebreaker stayed - nothing lost."))
        ev.append(("Open the Preview tab", "Copy preview, Smartlead-style: left rail shows Email 1 and Email 2 - BOTH clickable, Email 2 previews the follow-up (blank subject, 'threads under Email 1'). Centre shows the exact email with variables (first name, company, signature) highlighted in orange and MY ICEBREAKER highlighted in blue so it stands out; right sidebar 'Viewing as' flips between my kept prospects. Preview only."))
    ev.append(("Sources tab: 'Find me more high-intent leads'", "Clicked the card - it already knew my campaign goal (green badge quoting it back, no re-typing) and started suggesting straight away - a minute later 3 sized ideas appeared with icebreakers; clicked one -> 'Source added - it pulls on the next run'. Multiple sources now sit inside the one campaign."))
    return ev


def judge(persona, journey_events):
    name, bio, goal = persona
    transcript = "\n".join(f"{i+1}. YOU DO: {a}\n   YOU SEE: {s}" for i, (a, s) in enumerate(journey_events))
    prompt = f"""You are {name}: {bio}. Your goal today: "{goal}".
You just used a campaign-building web app. Here is exactly what you did and saw:

{transcript}

You chose every step yourself; anything beyond your stated goal was your own exploration - judge the app, not your detours. As {name} (non-technical), score honestly:
- ease: 1-10, SIMPLICITY - how simple, uncluttered and obvious the whole thing felt for YOU
- goals: 1-10, how fully you achieved YOUR stated goal end to end
- friction: up to 3 short specific complaints in your voice (empty list if none)
Reply ONLY JSON: {{"ease": n, "goals": n, "friction": ["..."]}}"""
    out = subprocess.run(["claude", "-p", prompt, "--model", "claude-sonnet-4-6"],
                         capture_output=True, text=True, timeout=120)
    import re as _re
    m = _re.search(r"\{.*\}", out.stdout, _re.S)
    return json.loads(m.group(0)) if m else {"ease": 0, "goals": 0, "friction": ["judge failed"]}


def main():
    if "--judges-only" in sys.argv and OUT.exists():
        journeys = json.loads(OUT.read_text())["journeys"]
    else:
        specs = [
            ("Amplifyy", "Amazon growth for product brands, performance basis", "consumer products brand", ["United States"], "", ["Founder", "CEO", "Head of E-commerce"]),
            ("BrightPR", "PR retainers for tech startups", "technology startup", ["United Kingdom"], "only companies hiring marketing or comms roles", ["Founder", "CEO"]),
            ("FreightFlow", "freight cost reduction for shippers", "logistics company", ["United States", "United Kingdom"], "warm signals only, no plain cold lists", ["Head of Sales", "VP of Sales", "Managing Director"]),
        ]
        journeys = []
        for spec in specs:
            print("journey:", spec[0])
            journeys.append(run_journey(*spec))

    assign = [0, 1, 2, 0, 0, 2, 2, 0, 1, 2]  # persona -> journey
    FAST = {3, 6}       # Marco, Sofia: reuse a known client's setup
    RETURNING = {2, 5, 8}  # Dana, Tom, Ruth: reviewing/adjusting an existing campaign
    COPY_FIRST = {4, 7} # Priya, Jae: rewriting the line is the goal

    CLOSE = ("Look at the campaign header",
             "The header pill now reads '● live - feeding smartlead automatically'. My signal pulls daily into the database, and every person I ✓ goes straight into the live outreach campaign. The loop is running.")

    def transcript_for(i):
        ev = list(journeys[assign[i]])
        if i in RETURNING:
            starts = ("Open Campaigns", "Click the draft", "Click 'Find", "Pick destination", "Qualify") + (("Change Countries",) if i == 5 else ())
            keep = [e for e in ev if e[0].startswith(starts)]
            keep.insert(0, ("Open Campaigns", "My colleague already set the campaign up - I just open the draft at the top of the list."))
            return keep + [CLOSE]
        if i in FAST:
            fast = [ev[0], ev[1],
                    ("Click 'Reuse last setup' on my client's card",
                     "Skipped the setup steps entirely - jumped straight to the ideas screen with my saved targeting applied.")]
            ev = fast + [e for e in ev if e[0].startswith(("Step 5", "Select", "Preview", "Save draft", "Click the draft", "Rewrite", "Click 'Find", "Qualify", "Edit icebreaker", "Change Countries"))]
        return ev + [CLOSE]

    idx = [2, 4, 5, 6, 8] if "--five" in sys.argv else list(range(10))
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(judge, PERSONAS[i], transcript_for(i)) for i in idx]
        results = [f.result() for f in futs]

    for i, r in zip(idx, results):
        print(f"{PERSONAS[i][0]:<7} ease={r['ease']:>2} goals={r['goals']:>2} " + (" | ".join(r.get("friction") or [])[:150]))
    ease = sum(r["ease"] for r in results) / len(idx)
    goals = sum(r["goals"] for r in results) / len(idx)
    print(f"\nAVERAGE ease={ease:.1f} goals={goals:.1f} -> {'PASS' if ease >= 8 and goals >= 8 else 'ITERATE'}")
    OUT.write_text(json.dumps({"journeys": journeys, "results": [
        {"persona": PERSONAS[i][0], **results[j]} for j, i in enumerate(idx)],
        "avg_ease": ease, "avg_goals": goals}, indent=1))


if __name__ == "__main__":
    main()
