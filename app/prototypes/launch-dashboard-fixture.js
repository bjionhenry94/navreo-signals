/* launch-dashboard-fixture.js
   The 5 live Prospeo campaigns from the 2026-07-27 Navreo run, caught MID-LAUNCH.
   Campaign names + net numbers are REAL (sessions/navreo-2026-07-27-prospeo-run.json).
   Per-stage launch state is PREVIEW (mocked) until real builds run — every prototype
   shows one small "preview" mark so no invented progress is passed off as real.
   One campaign sits on each of the five stages, so the whole pipeline is on screen. */
window.LD = {
  preview: true,
  updated: "just now",
  stages: [
    { key: "targeting",  label: "Targeting",  verb: "Finding the people" },
    { key: "copy",       label: "Copy",       verb: "Writing the emails" },
    { key: "icebreaker", label: "First line", verb: "Personal first lines" },
    { key: "checks",     label: "Checks",     verb: "Safety checks" },
    { key: "live",       label: "Live",       verb: "Ready in Smartlead" }
  ],
  campaigns: [
    {
      id: "newexec", name: "New sales boss just hired", caption: "New boss, new mandate",
      net: 925, tag: "Hot intent", active: 0, pct: 64, eta: "tomorrow",
      targeting: { found: 592, target: 925,
        roles: ["Owner / CEO", "VP / Head of Sales", "Commercial Director", "Head of BD"],
        signal: ["New CRO", "New VP Sales", "New CMO", "New CEO — last 6 months"] },
      copy: null, icebreaker: null, checks: null, live: null
    },
    {
      id: "msp", name: "Managed IT providers", caption: "Biggest pool",
      net: 10097, tag: "Biggest", active: 1, pct: 45, eta: "in 2 days",
      targeting: { found: 10097, target: 10097,
        roles: ["Owner / CEO", "Managing Director", "VP / Head of Sales", "Sales Director"],
        signal: ["Describes itself as a managed IT / MSP"] },
      copy: { subject: "one extra managed-services contract a month",
        preview: "Most MSPs grow on referrals, with nothing predictable behind them. We build the channel that keeps the calls coming." },
      icebreaker: null, checks: null, live: null
    },
    {
      id: "stack", name: "Already run a sales stack", caption: "Closest to what already works",
      net: 1273, tag: "Recommended", active: 2, pct: 70, eta: "tomorrow",
      targeting: { found: 1273, target: 1273,
        roles: ["Owner / CEO", "CRO", "VP / Head of Sales", "Commercial Director"],
        signal: ["Salesforce", "HubSpot", "Outreach", "Salesloft", "Apollo", "Pipedrive", "ZoomInfo", "Clay"] },
      copy: { subject: "running the stack you already pay for",
        preview: "You have bought the sales tools. Most teams never find the time to run them as a system. That is the part we do." },
      icebreaker: { samples: [
        "Owning the tools and running them are two different line items.",
        "Saw the sequencing stack on your site — the plumbing is already in.",
        "You clearly run a proper outbound stack already." ] },
      checks: null, live: null
    },
    {
      id: "growth", name: "On a growth tear", caption: "Momentum, no funding talk",
      net: 387, tag: "Hottest", active: 3, pct: 80, eta: "today",
      targeting: { found: 387, target: 387,
        roles: ["Owner / CEO", "VP / Head of Sales", "Commercial Director"],
        signal: ["Expansion", "New partnership", "Launch", "Award — last 6 months"] },
      copy: { subject: "the one growth channel still on manual",
        preview: "You are clearly growing. Outbound is the one channel most teams leave on manual. We build and run it for you." },
      icebreaker: { samples: [
        "The busy stretch right after a win is when outbound slips off the list.",
        "Saw the expansion news — momentum like that is the moment to add a channel." ] },
      checks: { items: [
        { label: "Emails verified", state: "pass" },
        { label: "No duplicates", state: "pass" },
        { label: "Nobody emailed in 30 days", state: "run" },
        { label: "Safe to send", state: "wait" } ] },
      live: null
    },
    {
      id: "freight", name: "Freight & 3PLs", caption: "Half already ours",
      net: 8424, tag: "Half ours", active: 4, pct: 100, eta: null,
      targeting: { found: 8424, target: 8424,
        roles: ["Owner / CEO", "Managing Director", "VP / Head of Sales", "Commercial Director"],
        signal: ["Freight forwarder", "3PL", "Customs broker"] },
      copy: { subject: "one new lane a month",
        preview: "Most new business still comes from lane referrals. We put your quotes in front of shippers who are not calling you yet." },
      icebreaker: { samples: [
        "A new lane a month is real money once you count it across a year.",
        "The trade runs on relationships and quotes — which is what a warm intro channel is for." ] },
      checks: { items: [
        { label: "Emails verified", state: "pass" },
        { label: "No duplicates", state: "pass" },
        { label: "Nobody emailed in 30 days", state: "pass" },
        { label: "Safe to send", state: "pass" } ] },
      live: { status: "ready", sent: 0 }
    }
  ]
};
