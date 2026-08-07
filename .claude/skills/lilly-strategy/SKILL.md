---
name: lilly-strategy
description: "Campaign-ideation orchestrator. Takes a client profile (offer, ICP, geo, history) and produces a paste-ready shortlist of 5-10 campaign ideas — each one = mechanism (targeted list / hiring signal / engagement signal / events / followers / lookalikes / news / Prospeo signal filters) × lead-magnet × probe-confirmed TAM × novelty score. Reports ONE size number per idea: NET findable decision makers (a 1-credit /search-person page-1 total_count, suppression-netted for free against Supabase contact_history + suppressions). Company counts never appear in any output; nothing is pulled or enriched at strategy time (1 credit per idea, hard ceiling). EVERY multi-idea run POSTs the run to the signals tool's live board (https://navreo-signals.onrender.com/app/strategy.html, fed by /api/strategy/run) — that page IS the deliverable the user works in and the ONLY surface the results appear on; chat never carries the menu (results live on the board + the session-file record), and chat-side targeting edits re-POST so the page updates live. Pulls existing campaign history via lilly-optimiser so it never re-pitches dead angles, runs lead-magnet-brainstorm to surface offer hooks, and probes every idea for real company + DM TAM (LLM estimates are not the headline number). Output is the tool's live board (the results never go in the chat), backed by a session-file record and per-idea hand-off blocks naming the exact skill chain to fire when the client approves. Use whenever the user wants to: ideate fresh campaigns for a client, build a campaign menu for a strategy call, brainstorm new angles after lilly-optimiser flags TAM-exhausted or low-positive campaigns, or onboard a new DFY client and pick their first 3-5 campaigns. Trigger phrases: 'ideate campaigns for [client]', 'what should we run for [client]', 'campaign menu for [client]', 'new campaign ideas after the optimiser', 'strategy call prep for [client]', '/lilly-strategy'. ALSO owns SINGLE-CAMPAIGN launches (consolidated launch flow, Bjion 2026-07-26): 'build me a list of [niche/vertical]' (freight forwarders / MSPs / commercial roofers), 'build a prospect list for [niche]', 'spin up a campaign for [client]', 'build a campaign shell' — these run Single-campaign mode: the SAME walkthrough in the single-view wizard (wizard-single-template.html, its own artifact, NO idea tabbing) because there is only one campaign; the multi-idea wizard fires ONLY when the user asks for multiple ideas. Does NOT build campaigns — the build hand-off names the skill chain (lilly-tam / lilly-theirstack-setup / lilly-trigify-setup / etc.) but execution is a separate, user-triggered step."
---

# Lilly Strategy — Campaign Ideation Orchestrator

## Purpose

Orchestrator skill. Takes a client profile and produces a shortlist of fresh campaign ideas — each idea = **mechanism × lead-magnet × TAM × novelty** — formatted as a paste-ready table the user can show a client (or internal team) for sign-off.

The whole point of this skill is **idea throughput with discipline**:
- Cast wide across 7 mechanism vectors so we don't accidentally narrow to "just another targeted list".
- Pull campaign history first so we never re-pitch what's already dead.
- LLM-estimate TAM for every angle (free), API-probe only the top 5 (cheap).
- One markdown table out, ready for the client. No 4-page strategy doc.

This skill does NOT build campaigns. On client sign-off, it names the skill chain (`lilly-tam`, `lilly-theirstack-setup`, `lilly-trigify-setup`, etc.) for the user to fire manually. Execution stays a separate step so the user controls when credits get spent.

**⚡⚡ HARD RULE — THE BOARD OPENS IN THE CLAUDE BROWSER, AND ONLY THERE (Bjion ruling 2026-08-03, supersedes BOTH 2026-08-02 rulings: the SendUserFile in-chat render AND the macOS `open` into the default browser — "I only want Claude").** On every publish, update, and hand-over, open the live board in the Claude Browser (`mcp__Claude_Browser__navigate`) at the session's keyed URL. NEVER run macOS `open` to the user's default browser, and never SendUserFile-render the stale template snapshot. The Claude Browser pane is the user's view; chat + that pane are the whole experience. The chat message still carries the keyed link as text for when the user wants it elsewhere.
**Which side to open (Bjion ruling 2026-08-04): the TOOL-USER view, always.** The pane must show the logged-in board — the one carrying the "Share with your client / Share a link" block (Preview tab) plus the reorder arrows — so the user can mint the client link in one click. Mechanics: inject a minted session cookie into the prod tab (`javascript_tool`: `document.cookie='navreo_session=<minted>; path=/; secure'`), then `navigate` to the BARE keyed URL `strategy.html#/r/<run_id>` (cache-bust with `?v=<commit>` after a deploy). The share-token URL (`?share=<token>#/r/<run_id>`) is ONLY what gets SENT to clients (chat text / the Share button mints it) — never what opens in the pane, because share mode hides the share button itself.

**⚡ THE OUTPUT SURFACE IS THE TOOL'S LIVE BOARD — every multi-idea run, no exceptions (Bjion ruling 2026-07-27, supersedes the 2026-07-19 standing-artifact ruling).** Ideating ideas ALWAYS ends by POSTing the run to the signals tool and pointing the user at **https://navreo-signals.onrender.com/app/strategy.html** (mechanics in Phase 5 → "Launch the board" and guardrail 15). The page polls `/api/strategy/run` every 5 seconds, so chat-side edits to targeting appear in the UI while the user watches. The user picks, approves and walks campaigns to launch-ready on that page. Never publish a multi-idea strategy run to a claude.ai artifact; the old standing artifact (5d6e5fdd…) is historical only.

**⚡ CHAT OPENS WITH A WELCOME BRIEFING — a short summary of the ideas, then how to take them further (Bjion ruling 2026-08-02, amends the 2026-07-19 "no results in chat" rule).** Every multi-idea run ends by posting ONE short, plain-English WELCOME MESSAGE to chat (exact shape in the "## WELCOME MESSAGE" section below): a light summary of the ideas (each idea's name, who it's for, and how many people we can reach), one human "start here" line, then a few concrete things the user can say to progress (e.g. "Create more copy ideas for the insurance one", "Build idea 2", "Give me more ideas"). This is a SUMMARY, not the full deliverable: the per-idea email copy, the outreach previews, the cut list and the approve/build flow still live only on the board (the experience the user works in) and the session file (the durable record). Keep the chat briefing to one phone screen; the depth is on the board, opened beside the chat and in the user's browser.

**⚡⚡ ALWAYS WORK IN THE CLAUDE BROWSER, NEVER A LOCAL SERVER (Bjion ruling 2026-08-03, VERY IMPORTANT).** lilly-strategy always opens the Claude Browser (`mcp__Claude_Browser__`) on the LIVE board and does ALL its work between chat and that browser. NEVER spin up a locally-hosted copy of the site (no `python app/server.py 7911`, no dev-server, no localhost verification) — the real deployed board is the only surface. The prod board opens fine in the Claude Browser via the public client permalink: mint it (`POST /api/strategy/share {run_id}`) and `navigate` there (`https://navreo-signals.onrender.com/app/strategy.html?share=<token>#/r/<run_id>`) — that shows all five pages logged-out. To verify GTME-only bits (reorder arrows, Build/share controls), inject the session cookie in the open prod tab via `javascript_tool` (`document.cookie='navreo_session=<minted>'` then reload) rather than a local mock. Editing the code still happens on `~/navreo-signals/app/strategy.html` directly + push; verification happens on the deployed board in the Claude Browser. (Supersedes the old "browser pane blocks navreo-signals" note — the share URL loads.)

**⚡ THE SIGNATURE FORMAT IS FIXED (Bjion ruling 2026-08-03).** `%signature%` in any email ALWAYS resolves to exactly this shape:
```
[Client Name]
[Role]
[Company]
Visit our website at [domain](.)[tld]
```
The website line ALWAYS uses the house DEFUSED-LINK form — the dot in brackets, e.g. `navreo(.)ai` — never a clickable link (deliverability standard, see email-deliverability-audit). Carried as `run.signature = {name, role, company, domain}` with `domain` stored defused. **If you don't know the name / role / company / domain, ASK the user — never guess it.** Navreo's own: Bjion / Founder / Navreo / navreo(.)ai.

## ⚡ CHAT VOICE — extremely non-technical, always (Bjion ruling 2026-07-27)

Every chat message during strategy work — progress updates, questions, the door line, answers —
reads like you are explaining it to a smart 16-year-old. Short sentences. No shop talk.

**Never say in chat:** tool, provider or database names (the job-ads source, the contact
databases, the sending platform, the storage — none of them get named), file names, endpoint
or code words (probe, POST, API, run.json, engine, hydrate, commit hashes), or trade shorthand
(TAM, DM, ICP, enrichment, suppression, net ratio, gross, vector, spintax, subsequence).

**Say instead (the translations that come up most):**

| Instead of | Say |
|---|---|
| "Probed via TheirStack: 18,990 postings / 11,751 companies" | "I counted them for real: about 11,700 companies are hiring for these roles right now" |
| "gross → net after suppression netting (ratio 0.88)" | "About 1 in 10 came off the list because we've already emailed them recently" |
| "net findable decision makers" | "people we can reach" |
| "enrichment / email verification" | "finding and double-checking their email addresses" |
| "the upload gate / QA checks" | "the safety checks before anything is loaded" |
| "drafted in Smartlead, campaign 3651763" | "saved and ready — nothing sends until you say so" |
| "re-probe is free" | "checking again costs nothing" |
| "1 Prospeo credit per idea" | "each idea costs one paid lookup to size properly" |
| "icebreaker / sequence / variant" | "opener / the emails / version A, B, C" |
| "hiring signal / engagement signal" | "companies hiring right now / people reacting to posts about this" |

Numbers stay — they are the substance — but framed in plain words. Links to the board and to
pages in the tool are fine (that is navigation, not jargon). If Bjion asks a technical question,
answer it straight; the ban is on unprompted shop talk, not on honesty. Session files and run
records keep full technical detail — they are the durable record, not chat. The chat DOES open with a short welcome summary of the ideas (the "## WELCOME MESSAGE" shape: name + who + reach per idea, plus how to progress) — but never paste the full rundown into chat: the per-idea email copy, previews, cut list and approve/build flow stay on the board. Summary yes, full deliverable no (Bjion ruling 2026-08-02, amends guardrail 16).

---

## WELCOME MESSAGE — the chat briefing every multi-idea run ends on (Bjion ruling 2026-08-02)

Mirrors the `/navreo-inbox` and `/navreo-analytics` welcome: the board opens beside the chat AND in the user's browser, and you post ONE short, plain-English briefing to Bjion (the founder, not technical). It does TWO jobs, in this order: (1) summarise the ideas, (2) tell him how to take them further. Post it only AFTER the run is live on the board (POST returned `ok`); the numbers in it are the run's real probe-confirmed reach figures, never invented.

WRITE THE MESSAGE IN THIS EXACT SHAPE, filled with the real idea names and numbers. The names and figures below are only an example, replace every one. Open with a greeting that fits the time of day (Morning, Afternoon or Evening):

Afternoon 👋 Here are five fresh campaign ideas for Navreo.

💡 The ideas
| Idea | Who it's for | People we can reach |
|---|---|---|
| [Runs a sales stack](https://navreo-signals.onrender.com/app/strategy.html) | Agencies already paying for the sales tools | 1,600 |
| [Insurance brokers](https://navreo-signals.onrender.com/app/strategy.html) | Commercial insurance brokerages | 9,800 |
| [Debt recovery firms](https://navreo-signals.onrender.com/app/strategy.html) | Collections and unpaid-invoice firms | 5,900 |
| [New sales boss](https://navreo-signals.onrender.com/app/strategy.html) | Firms that just hired a sales leader | 700 |
| [On a growth tear](https://navreo-signals.onrender.com/app/strategy.html) | Firms in the news for a recent win | 400 |

Start with the sales-stack one, it's the exact crowd behind all your best past campaigns. That's about 18,000 people we can reach in total, and every number is counted for real.

👉 To take it further, just say:
- "Open the insurance one" to walk through its audience and emails
- "Create more copy ideas for the debt-recovery one" for fresh email angles
- "Build idea 1" to get it launch-ready (nothing sends without you)
- "Share this board with my client" for a link they can open and edit the emails in
- "Give me more ideas for Navreo" for a fresh set

Board's open on the right, and in your browser. This board is this session's own page, so it stays exactly as we leave it.

SHAPE RULES
- Summary table is 3 columns max: Idea, Who it's for, People we can reach. Round the reach numbers to something a human reads at a glance (1,600 not 1,604). One row per idea; cap the table at the strongest 3-5 so it stays one phone screen (if the run has more, table the top ones and add "plus N more on the board").
- Every idea name in the table links to the board at THIS SESSION'S keyed URL (`…/strategy.html#/r/<run_id>`, never the bare page and never a per-idea deep link).
- One human "start here" line naming the single idea to open first and why, plus the one total reach figure.
- The "take it further" block is 3-4 plain things he can SAY, each a real progression path: open/expand an idea, more copy ideas for an idea, build/approve an idea, or get more ideas. Use his own words ("Create more copy ideas for X").
- Close on one line that the board is open on the right and in his browser. No sign-off after it.
- House voice (same as `/navreo-inbox`): a 16-year-old understands every line, no jargon, no tool/provider names, NEVER an em-dash, warm and written to "you", a couple of emoji per section at most, one phone screen top to bottom. No preamble before the greeting, no mention of being an AI or how you fetched anything.
- Never put the full deliverable in chat: no per-idea email copy, no cut list, no probe/credit detail. Those live on the board and in the session file. Summary + how-to-progress only.

BEFORE YOU POST: re-read it as a non-technical founder with 30 seconds. Does it tell me what the ideas are and exactly what to say next, in one screen? If not, cut and tighten, then post.

---

## When to Use

Trigger when the user wants to:
- Onboard a new DFY client and pick their first 3-5 campaigns.
- Refresh a client whose existing campaigns have plateaued (typically flagged by `/lilly-optimiser` — see "Optimiser hand-off" below).
- Prep for a client strategy call: needs a menu of options the client can pick from.
- Pivot a campaign that's hit the `lilly-optimiser` kill threshold (15K+ sent, ratio > 2,500/positive).
- Expand into a new geo or vertical for an existing client.

Accept input forms:
- "Ideate campaigns for [client]"
- "What should we run for [client]?"
- "Strategy call prep for [client] on [date]"
- "[Client]'s [campaign] is dead — new angles?"
- "/lilly-strategy [client-name]"

Single-campaign asks (consolidated launch flow, Bjion 2026-07-26) — trigger **Single-campaign mode** (section below), NOT the multi-idea flow:
- "Build me a list of [niche/vertical]" — freight forwarders, MSPs, commercial roofers, etc. (the most common daily ask).
- "Build a prospect list for [niche]" / "spin up a campaign for [client]" / "build a campaign shell in Smartlead".
- A TAM map the user just approved drafting into a campaign (hand-off from `lilly-tam`).
The fork rule: ONE campaign in play → single-view walkthrough. The multi-idea wizard fires ONLY when the user explicitly wants multiple ideas ("give me ideas", "campaign menu", "what should we run").

Skip / don't trigger when:
- User wants to optimise an existing campaign (vs. ideate new ones) → `/lilly-optimiser`.
- User wants to ideate lead magnets only (no campaign mechanism) → `/lead-magnet-brainstorm` directly.
- User wants a raw TAM/market-size answer with no campaign intent → `/lilly-tam` (which ALWAYS ends by offering to draft the campaign; a yes routes back here in Single-campaign mode).

---

## Single-campaign mode — the single-view walkthrough (Bjion ruling 2026-07-26)

The consolidated launch flow for ONE campaign. Same walkthrough, same voice, same engine —
just no idea list to tab between, because there is nothing to switch to.

**When:** any single-campaign ask (see When to Use): a niche list-build, a campaign shell, a
recontact needing a walkthrough, or a TAM map the user said yes to drafting.

**Template:** `~/.claude/skills/lilly-strategy/wizard-single-template.html` — the sibling of
the multi wizard with the idea rail reduced to one static status card (no click-to-switch, no
validation rail entry). NEVER the multi template, and NEVER the standing multi-idea artifact URL.

**Flow (lean — skip the full Phase 0–5 sweep):**
1. **Intake** — niche/vertical, geo, the client (default Navreo), offer line. Pull what memory
   and Supabase already know; ask only for what's missing. No 7-vector brainstorm.
2. **Probe + net** — same engine, same law: `engine.py probe` for the gross (1 credit ceiling),
   `engine.py net` for the suppression-netted number. Numbers are never hand-written.
3. **run.json with exactly ONE idea** — same schema, same creative fields (who/offer/pain/
   moment/videoAngle/why/repliesLine + 4-5 illustrative people). `validate` passes single-idea
   boards (mixture rule starts at 5 ideas).
4. **Hydrate the single template** —
   `python3 engine.py hydrate --run run.json --template wizard-single-template.html --out <scratchpad>/wizard-single-<client>.html`
   (copy semantics as ever: never edit a template in place).
5. **Publish to the run's OWN artifact** — single-campaign runs mint/reuse a per-campaign
   artifact URL. The standing multi-idea artifact is never repointed (guardrail 15 stays
   scoped to multi-idea runs).
6. **Chat stays a short door** — guardrail 16 applies unchanged: one or two lines + the link;
   the walkthrough IS the experience. The user approves audience → copy → opener → sign-off in
   the artifact, exactly like the multi wizard's per-campaign track.
   Door copy is concrete about what's inside and that it's safe (panel ruling 2026-07-26):
   *"Your [niche] campaign is ready to walk through — open it here. You'll approve the
   audience, the emails and the final sign-off inside (about 5 minutes); nothing sends
   without you."* Multi-idea door lines may say how many ideas are waiting inside ("5 ideas
   are ready — open and pick") but never the ideas themselves (guardrail 16).
7. **On upload approval** — the upload path still runs `/lilly-upload-gate` (no exceptions);
   after a successful upload the closing message opens the campaign in the tool
   (`https://navreo-signals.onrender.com/app/campaigns.html#/c/<id>`) and says what to do
   there: *"it's on its Overview page — review it, and launch from Smartlead when you're
   ready; until then it's paused and nothing sends."*
   **"Upload to the campaign / the tool" ALWAYS means the prospects land INSIDE the Smartlead
   campaign** (`add_leads_to_campaign`), not just attached as a tool-side source — registering
   the campaign is necessary but not sufficient. Do both (tool registration AND the Smartlead
   lead-push, to a DRAFTED campaign unless told to launch). Bjion 2026-08-04, memory
   [[upload-to-campaign-means-smartlead]].

**Multi-idea escape hatch:** if mid-walkthrough the user asks for alternatives ("what else
could we run?"), that's a NEW multi-idea run (full flow, standing wizard) — don't bolt a rail
onto the single view.

---

## Architecture

```
lilly-strategy  (this skill — orchestrator)
   │
   ├── Phase 0 — Client briefing (intake)
   │
   ├── Phase 1 — History pull  →  lilly-optimiser  (extract what's been tried)
   │
   ├── Phase 2 — Mechanism brainstorm (7 vectors, LLM-only, free)
   │       ├── Targeted TAM list           →  hand-off: lilly-tam
   │       ├── Hiring signals              →  hand-off: lilly-theirstack-setup
   │       ├── LinkedIn engagement signals →  hand-off: lilly-trigify-setup
   │       ├── Events                      →  hand-off: manual + loom-research lists
   │       ├── LinkedIn company followers  →  hand-off: lilly-linkedin-page-finder + lilly-company-followers
   │       ├── Lookalike audiences         →  hand-off: lilly-tam (from named clients as seeds)
   │       └── News/funding intent         →  hand-off: lilly-icebreaker-news-search
   │
   ├── Phase 3 — Lead-magnet brainstorm  →  lead-magnet-brainstorm  (5-10 offers)
   │
   ├── Phase 4 — TAM probing (LLM-first; API-probe top 5 only)
   │       └── lilly-tam Stage 0.5-style 1-credit probe per top-5 idea
   │
   ├── Phase 5 — Score & shortlist  (TAM × Fit × Novelty × Buying-intent)
   │       → markdown table, top 5-10 ideas
   │       → persisted to sessions/<client>-<date>.md
   │
   └── Phase 6 — Build hand-off  (per approved idea: named skill chain + brief pre-fill)
```

**⚙️ THE ENGINE (installed 2026-07-19):** `engine/engine.py` is the deterministic back end for every number and every artifact splice — `retro` (scorecard), `probe` (per-idea gross via the idea's pull_spec: Prospeo 1 cr / TheirStack free / AI Ark ~1 cr), `net` (30-day cooldown suppression router), `validate` (schema + house rules incl. the ≥3-vector mixture), `hydrate` (run.json → wizard html, round-trip-proven), `handoff` (/lilly-tam brief). The session writes ONLY the creative fields; any number not produced by the engine is invalid. Contract + command crib: `engine/README.md`.

---

## Phase 0 — Client briefing

Goal: get enough about the client to ideate without burning the user's time on a long intake.

**If a client profile already exists** at `clients/<client-slug>.json`, load it and skip to confirmation. Confirmation = a 3-line summary, ask user "anything stale or wrong?"

**If no profile exists**, ask these 6 questions (one at a time, terse, no preamble):

1. **Client name + business slug** (e.g. "Amplifyy" → `amplifyy`). Used for file naming.
2. **What do they sell?** One sentence.
3. **Who's their ICP?** Verticals + roles + geo + headcount band. Skip if you can read this from a memory file (e.g. `project_amplifyy_icp`, `project_amplifyy_account`).
4. **Existing client list** — 5-10 named customers. Used as lookalike seeds + as social proof in copy.
5. **Existing Smartlead campaigns** — list of active campaign names, OR Smartlead client-key so we can pull via `/lilly-optimiser`. If none, mark as "greenfield".
6. **Constraints** — taboo verticals, geos to exclude, lead magnets they can't deliver, regulatory restrictions (e.g. cannot promise financial outcomes).

Save the answers to `clients/<client-slug>.json` (overwrite if confirmed-stale, append-with-history otherwise). Schema:

```json
{
  "client_slug": "amplifyy",
  "client_name": "Amplifyy",
  "what_they_sell": "...",
  "icp": {
    "verticals": ["..."],
    "roles": ["..."],
    "geo": ["US","GB","..."],
    "headcount_bands": ["..."],
    "dm_titles": ["CEO","Head of Sales","CFO"]
  },
  "named_clients": ["..."],
  "existing_campaigns": {
    "smartlead_client_key": "...",
    "campaign_names": ["..."]
  },
  "constraints": {
    "taboo_verticals": ["..."],
    "geo_exclusions": ["..."],
    "lead_magnet_blockers": ["..."],
    "regulatory": ["..."]
  },
  "first_briefed_at": "YYYY-MM-DD",
  "last_refreshed_at": "YYYY-MM-DD"
}
```

**Memory check:** before asking question 3 or 4, scan `MEMORY.md` for any `project_<client>_*` entries. Many clients have ICP / role / account memories already; use them rather than re-asking. State which memory you're loading from so the user can correct if stale.

**Capture `dm_titles` from Q3's roles.** List the distinct buyer titles the user wants to hit per company (e.g. `["CEO","Head of Sales","CFO"]`), dropping non-buyer ICs (e.g. plain "Account Executive" for a service-business buyer, per `feedback_dm_finder_skip_account_manager`) unless the user explicitly wants them. **`N = len(dm_titles)` is the DM-TAM multiplier** used in Phase 4 Step 2b (DM TAM = Company TAM × N). Confirm the list with the user before the probe sweep (per `feedback_always_confirm_inclusions_exclusions`) — adding/removing a title changes every idea's DM TAM, so it's the user's lever.

---

## Phase 1 — History pull (lilly-optimiser)

Goal: extract what's been tried so Phase 2 doesn't re-pitch dead angles.

**⚙️ ENGINE (run this first, free):** `python3 ~/.claude/skills/lilly-strategy/engine/engine.py retro --client <slug> --out-json retro.json` — totals, winners (≥1/1k at ≥500 sent), the dead list (≥1,500 sent under 0.5/1k) and small in-flight campaigns from the Supabase campaign scorecard, with reply-subsequence rows filtered out. This is the retro's factual backbone; the optimiser adds the qualitative layer below when a deeper read is needed.

**If the client has a Smartlead client-key**, delegate to `/lilly-optimiser` with that key. Extract from the optimiser output:

| Field | What to capture |
|---|---|
| **Active campaigns** | Names + sent/positive ratio + status (performing / needs-optimisation / nearing-completion) |
| **Dead angles** | Disabled variants + their angles (the "Previously Tested" section in optimiser deep-dives) |
| **Killed ICPs** | Campaigns past the 15K-send + 2,500-ratio kill threshold |
| **Reply pattern data** | If the optimiser ran a "response breakdown", capture who's actually replying (titles / industries / sizes) — this often diverges from the nominal ICP |
| **Lifecycle status** | Campaigns at 75%+ completion (need fresh leads OR fresh angles) |

**If no Smartlead history exists** (greenfield client), skip Phase 1 and note `history: greenfield` in the session file. All ideas are by definition novel.

**Output of Phase 1:** a single block in the session file:

```markdown
## History (from lilly-optimiser)

**Active campaigns:** N (M performing, N-M needing optimisation, K nearing completion)

**Killed ICPs / dead angles to AVOID re-pitching:**
- [angle 1] — reason killed
- [angle 2] — reason killed
- ...

**Actual reply patterns** (where optimiser response-breakdown found divergence):
- [segment] over-indexes by N×
- ...

**Refresh-needed campaigns** (75%+ complete, need fresh leads):
- [campaign 1]
- ...
```

---

## Phase 2 — Mechanism brainstorm (7 vectors)

Goal: 2-5 concrete angles per vector. LLM-only — no API calls, no credits spent. Speed > precision here; Phase 4 prunes the weak ones.

For each vector below, generate angles using the client's offer + ICP from Phase 0 and the avoid-list from Phase 1.

### Vector 1 — Targeted TAM list  (→ `/lilly-tam`)

Direct ICP targeting via cross-provider list-builder. Highest-fit, lowest-intent.

**⚡ Tech-stack targeting is a FIXED LIST, not a signal (Bjion ruling 2026-08-04).** Targeting
companies by the tools they run (e.g. "uses Outreach / Apollo / Clay / Smartlead") belongs HERE,
as a targeted/fixed list — a tech stack is a static company attribute with no time-based trigger,
so it is never presented as a buying signal (`vector: targeted_list`, never a `*_signal` vector,
and the board never gives it signal framing). Two sub-rules:
- **Outbound-only tools qualify as an "already does outreach" list** (Outreach, Apollo.io,
  Salesloft, Clay, Lemlist, Smartlead, Instantly). Generic CRMs (HubSpot, Salesforce) do NOT
  imply outreach and never qualify.
- **Size it via TheirStack tech-detection**, not Prospeo integrations: `POST /v1/companies/search`
  with `company_technology_slug_or` + geo + employee bounds, read `metadata.total_companies`
  (free). Prospeo `company_integrations` barely detects outbound tools (verified 2026-08-04:
  Apollo 30 / Clay 16 / Smartlead 9 vs TheirStack's 9,483 ICP-filtered companies).

Ideate angles like:
- Core ICP, all 14 high-GDP countries (default Navreo geo set)
- ICP slice by sub-vertical (e.g. "ID firms" → "hospitality ID firms" + "residential ID firms" + "commercial ID firms")
- ICP slice by company size band (51-200 vs 201-500 — different buying motions)
- ICP slice by geo cluster (US-only campaign vs. UK+IE vs. EU)

Per angle, capture: **ICP description** + **filter intent** (verticals/roles/geo/size) + **est. TAM** (LLM guess, 3-column rule: Verified-sample / Estimated TAM / Pulled-full — all three at this phase are estimates).

### Vector 2 — Hiring signals  (→ `/lilly-theirstack-setup`)

Buying intent via job postings. Strong angle when the new hire's job description maps to the client's offer.

**⚡ No industry callouts in the copy (Bjion ruling 2026-08-05):** people found via hiring
signals can't usually be filtered by industry (~90% of pulls carry no industry filter), so the
copy and opener angle on the ROLE being hired, never a named industry/vertical — unless this
idea's `pull_spec` genuinely filters industry (rare; then it's allowed). Full rule in Phase 2c
→ TEMPLATE FIDELITY.

Ideate angles like:
- Hires that signal "we're building this internally" (e.g. for Navreo: GTM Engineer, RevOps, Founding Sales)
- Hires that signal "we just promoted someone, they need tools" (e.g. new VP/Head of Sales)
- Hires that signal "we just got funded" (mass-hiring → growth-stack buyers)
- Hires that signal "we lost someone, urgent replacement" (60-day-old postings still open)

Per angle: **role pattern** (job-title strings) + **why it signals buying intent for THIS client's offer** + **est. monthly TAM** (LLM guess, calibrate against known briefs — e.g. existing Navreo "GTM Hiring Signal" brief gets ~292/30d for title-based angle A).

### Vector 3 — LinkedIn engagement signals  (→ `/lilly-trigify-setup`)

Buying intent via competitor / thought-leader post engagement. Engager IS the lead — no DM-finder phase needed.

Ideate angles like:
- Engagers of N specific competitor founder posts (pick competitors from `/loom-research` Task 6 if available)
- Engagers of N category thought-leader posts (people the ICP follows — Bertelsen, Pete Caputa, Dan Martell, etc. — match to client's offer)
- Engagers of the CLIENT's own founder posts (if the client posts on LinkedIn) — warm-audience expansion
- Engagers of niche conference / event organiser pages (cross-pollinates Vector 4 events)

Per angle: **tracked profiles** (names + LinkedIn slugs) + **why their engagers fit the ICP** + **est. engagers per month per tracked profile** (LLM guess, typical 50-300/profile/month for a 10K-follower founder).

**Apply the hiring-signal `skip_angles` rule for icebreakers** (from memory `feedback_hiring_signal_icebreaker_skip_angles`): every Trigify brief flowing from this skill must pass `skip_angles=["Hiring", "You joined"]` to `lilly-icebreaker` at the data-processing phase to avoid stalker-coded openers when role-change happens to also be the signal. Note this in the build hand-off block.

### Vector 4 — Event Exhibitors  (→ manual + `/loom-research` event tables) — CONTRACT (Bjion 2026-08-03)

Events where the **ICP exhibits**, so we scrape the **exhibitor companies**. This is the
**Event Exhibitors** campaign type — it has a fixed contract, follow it exactly.

**EXHIBITORS, NOT ATTENDEES (hard, load-bearing).** We ALWAYS and ONLY target the companies with a
stand — the ICP brands **exhibiting** — never the attendees/visitors. If the ICP is food & beverage
brands, we target the F&B brands **exhibiting** at those events, not people who attended. Any angle
or copy that implies attendees is wrong. Excluded: organisers, non-ICP sponsors, attendees.

**How we find them:** use the `/loom-research` methodology (Task 4 events — name · date · location ·
who exhibits · why relevant · website). Pull the Task 4 tables from `sessions/` if loom-research has
been run for the client's named clients; otherwise LLM-generate by ICP. Prioritise events in the
next 3-6 months (recent past editions OK if the exhibitor list is still scrapeable).

**Targeting page:** list **all** events we could target and scrape — each **hyperlinked** to its
event site. One targeting group, "Events we pull exhibitors from", with the exhibitors-not-attendees
callout in `targeting.note`.

**Reach (Bjion update 2026-08-03, supersedes the earlier no-number rule): an ESTIMATE of about
100 decision makers per event.** `net = 100 × number of events listed`, ALWAYS labelled as
estimated (`netUnit` "decision makers (estimated)", `probe.provider:"manual"`, 0 credits) — never
presented with the counted/probed framing other types use. Flag delivery friction: exhibitor lists
need manual scraping (exhibitor-directory / PDF parse).

**Opener (the ONLY one, fixed):** `Saw you exhibiting at {events} and thought I'd reach out.`
`{events}` = the event(s) that lead exhibited at ("X, Y and Z"), a per-lead merge var filled from
the exhibitor scrape. `icebreaker.kind:"fixed"`, one angle + generic fallback.

### Vector 5 — Company Followers  (→ `/lilly-linkedin-page-finder` + `/lilly-company-followers`) — CONTRACT (Bjion 2026-08-03)

**Classification (Bjion 2026-08-04): Company Followers is a FIXED LIST, not a live signal.**
You get it from a 3rd party (Trigify / Phantombuster follower scrape) then upload it as a CSV —
it does not refresh daily and the tool pulls nothing for it. Register the tool campaign with
mechanism `fixed_list` (`active=False`), NOT `followers`. Build the list CLEAN at upload:
recycled follower rows carry corrupt company names/websites and stale cross-client custom
fields — re-source or drop them, never ship them (see 2026-08-04 dry-run: `{{company_name}}`
rendered "Combu", rows carried `ArnicIcebreaker`).

Followers of a competitor / category-tool / thought-leader / event-organiser / media **LinkedIn
company page** — a self-selected audience that already cares about the category. This is the
**Company Followers** campaign type — it has a fixed contract, follow it exactly.

**How we find the pages:** use the `/loom-research` methodology to identify the LinkedIn **company
pages** whose follower base = the client's ICP (competitors, category tools, thought-leaders, event
organisers, category media). Identify the pages, not the people.

**Reach math (HARD):** get each page's LinkedIn follower count (WebSearch `"{page}" LinkedIn
followers`, or `/lilly-linkedin-page-finder`), then **reach = 5% of the SUM of all identified pages'
followers** — `net = round(0.05 × Σ followers)`. That 5% is "the decision makers we would likely
find". This is **arithmetic on follower counts, NOT a probe** — no Prospeo credit; `probe` provider
is `manual`. Never hand-wave the number; it's the sum × 0.05.

**Targeting page (HARD):** list **every** company page, each **hyperlinked** to its LinkedIn company
URL with its **follower count** shown, plus the summed total and the 5% line ("Σ followers → 5% = N
reachable"). One targeting group, "Pages whose followers we email"; each chip = page name (carries
its LinkedIn URL) + follower count as its sub-label.

**Opener (the ONLY one, fixed):** `Saw you were following {page} and thought I'd reach out.`
`{page}` = the page that lead follows, a per-lead merge var filled from the follower scrape.
`icebreaker.kind:"fixed"`, one angle + generic fallback. **Never** a dynamic waterfall — the
targeting (they chose to follow the page) IS the personalisation. Scraping the follower lists lives
outside Lilly skills (Trigify / Phantombuster) — flag delivery friction.

### Vector 6 — Look-a-like  (→ `/lilly-tam` from named-client seeds) — CONTRACT (Bjion 2026-08-03)

Target the **vertical the sender already has proof in** — the type of company the sender has worked
with or has case studies with. This is the **Look-a-like** campaign type — it has a fixed email-1
template, follow it exactly.

**How we find the seeds:** find the companies the SENDER has worked with / has case studies with
(`/loom-research` client base + `/lilly-data` outreach history + the client's own proof), then target
**that vertical**. Navreo worked with an Amazon agency → target Amazon agencies. Tight sub-vertical
clusters beat mixed-seed mega-calls (`lilly-tam` rule #22).

**Reach:** normal probe-confirmed net DM (standard lookalike/TAM sizing via `/lilly-tam` Stage 0.5 —
this type KEEPS its number; only Event Exhibitors has none).

**Email 1 template (HARD — this fixed shape IS the copy; board tokens `{first}`/`{company}`/
`{icebreaker}` + `%signature%`, no em-dashes). NO P.S line — Look-a-like carries no postscript
(Bjion ruling 2026-08-05; the validator flags one that sneaks back in):**
```
Subject: question for {first}

Hi {first},

{icebreaker}

{pain framed as a question they answer in their head}

Asking because we {relevant social proof} and thought {company}
could be a good fit for the same.

{offer / CTA}

%signature%
```
The three `{ }` fills — pain-question · social-proof · offer/CTA — are written
ONCE per campaign from the client's REAL case study (generate through the Offer Maker per Phase 2c,
then anchor the social-proof to the real proof — the case-study win + how it was billed).
`{first}`/`{company}` stay verbatim merge tokens. Never reword the fixed scaffolding
("Asking because we … could be a good fit for the same."). Any risk reversal folds into the
{offer / CTA} fill as a body line, never a postscript.

**⚡ THE PAIN LINE IS AN INNOCENT QUESTION THAT PROVOKES A THINK (Bjion rulings 2026-08-05).**
A genuine, personable question — the kind a real, curious human would actually ask — that
quietly IS the problem: the reader answers it in their own head, and that honest silent
answer is what reminds them of the pain. Keep it warm and conversational (contractions,
light lead-ins like "out of interest", "how's X going for you"). It must feel like an
innocent question, NEVER a clever sales "gotcha" — the moment it reads as marketing (a
smart rhetorical twist, a knowing "…, or [the painful truth]?") it's wrong. Three banned
shapes: (1) a statement with a soft tag slapped on the end — "…hard to tell what's working.
Sound familiar?" / "Ring true?" / "Is that fair?"; (2) a limp empathy check — "Do you feel
X?" / "Are you struggling with X?"; (3) the salesy provocative twist. Reach for HOW MUCH /
WHICH / WHEN / CAN YOU / DO YOU KNOW so the honest answer surfaces the gap on its own.
`engine.py validate` flags the banned tags on any lookalike version.

**The icebreaker (Bjion correction 2026-08-03): the pain question is PART OF THE COPY TEMPLATE — it
is NOT the icebreaker.** A Look-a-like campaign still needs its own real icebreaker strategy:
`icebreaker.kind:"dynamic"` with the normal Phase 2b waterfall (hiring / tech / recently-joined /
colleague + generic fallback), resolved into the template's `{icebreaker}` line above the pain
question. Never present the pain question as the opener. Worked Navreo/Amazon example:
```
Subject: question for Nick

Hi Nick,

I noticed Peakline is hiring a business development rep, so growing new
business is clearly on your mind right now.

Out of interest, how much of your Amazon growth feels like it's actually in your control right now?

Asking because we helped another Amazon agency generate 3x ROI within a
month of working with us, and thought {company} could be a fit for the same.

We worked with them on a pay-per-meeting-booked basis too.

Would you be open to seeing a 2-min video as to how we'd do it for you?

%signature%
```

### Vector 7 — News / funding / award intent — **DROPPED (Bjion 2026-08-04)**

News / funding / expansion / award intent is **no longer a campaign type** in lilly-strategy.
Do not ideate it, do not put it on the board, do not register a `news` mechanism. (Funding /
hiring / recently-joined still exist as ICEBREAKER angles inside a dynamic waterfall — Phase 2b —
but "news" as a standalone targeting vector is retired.)

---

### Vector 2 brainstorm tactic — describe-then-translate

For hiring signals especially, describe the ROLE the client wants to target in plain English first, then translate to title patterns. Title patterns alone miss roles whose actual title varies wildly (e.g. "person responsible for outbound" might be VP Sales / Head of Demand Gen / GTM Engineer / Founder, depending on company stage).

For each hiring-signal angle, capture both:

```
description: "Companies hiring their first dedicated GTM person — typical signal that they're moving from founder-led sales to a system"
title_patterns: ["Founding Sales","First Sales Hire","Founding GTM","Head of GTM","GTM Engineer","Director of Growth"]
```

`lilly-theirstack-setup` Phase 2 will TAM-test the title patterns — if a pattern returns < 50 jobs/30d in the target geo, it gets dropped in favour of broader patterns surfaced by the description.

---

## Phase 2b — Icebreaker strategy (per idea) — Bjion methodology 2026-08-03

Ideating a campaign is **not complete without its icebreaker strategy.** Every idea on the board has an Icebreaker stage and it must never be empty. The engine that runs it at build is `/lilly-icebreaker-v2` (6-angle waterfall: Colleague · Hiring · Funding · You-joined · Tech · generic Fallback, first-to-fire wins). At ideation time you decide, per idea, whether it even needs a dynamic icebreaker and — if so — which angles the waterfall uses.

**Step 1 — Fixed or dynamic? (the first decision).**
- **Fixed / no dynamic icebreaker needed** when the TARGETING ITSELF IS the personalisation. If the reason we're emailing them already carries the relevance — e.g. **company followers** (they follow the tool), **engagement signals** (they reacted to the post), a **tight named-list** — the opener can be fixed copy that references that shared context. Don't spend data personalising what the targeting already personalised.
  - **The two fixed-opener campaign types (Bjion 2026-08-03) — always fixed, never a waterfall:**
    **Company Followers** (Vector 5) → `Saw you were following {page} and thought I'd reach out.`
    · **Event Exhibitors** (Vector 4) → `Saw you exhibiting at {events} and thought I'd reach out.`
    Fill only the merge var; never reword the scaffolding. (**Look-a-like** is NOT fixed — Bjion
    correction 2026-08-03: its pain question is part of the copy template, not the icebreaker; a
    lookalike runs the normal DYNAMIC waterfall into the template's `{icebreaker}` line.)
- **Dynamic (waterfall)** when the message is otherwise generic and needs relevance bolted on — the classic **big list** case (a 90K+ pull where nothing about the list itself is personal). Here we run the icebreaker waterfall to find something relevant per person.

**Step 2 — What to AVOID (hard preferences).**
- **Never just call out what they do.** "I saw you run a marketing agency…" is massively overused and reads negative. Not an angle.
- **Avoid anything that needs website scraping.** Scraping each site (via Claude Code or paid alternatives) is expensive, so we default to signals we can get cheaply/at-source. NOT a total ban — for a **small list** a scraped, hand-crafted opener can absolutely be worth it; call that out explicitly when the list is small.

**Step 3 — The default dynamic waterfall (Bjion's usual), in order:**
1. **Hiring signal.** A role they're hiring for that implies the problem the SENDER'S service fixes. Per idea, list the **specific job titles** that signal need for this sender (e.g. for an outbound service: hiring SDRs / BDRs / sales reps / "first sales hire"), and a one-line note on why each job implies the need. **One hiring lookup per person only** (conserve data — the free TheirStack per-domain call, `company_domain_or` + `blur_company_data:true`, 0 credits, still one call per domain).
2. **Tech stack they use.** Technologies whose presence implies the sender's service is relevant (e.g. a company using **Clay** is a great fit for us). Per idea, list the **tech names** that qualify — and they MUST come from the TheirStack technology catalog (the canonical 32,572-tech list):
   ```bash
   # FREE — catalog calls consume no API credits; cached at ~/.navreo-cache/theirstack/technologies.json
   curl -s "https://api.theirstack.com/v0/catalog/keywords?keyword_type=technology&limit=100000" \
     -H "Authorization: Bearer $THEIRSTACK_API_KEY"
   ```
   Each entry carries `name`, `slug`, `category`, `description`, and **`companies` + `jobs` counts** — so the catalog both validates the exact tech name to mention AND sizes the audience for free (verified 2026-08-03: Clay 8,539 companies · Apollo.io 21,563 · Outreach.io 23,355 · Calendly 8,867 · Smartlead 1,651 · Instantly 549). Use the CANONICAL catalog name in triggers (it's "Apollo.io"/"Outreach.io", not "Apollo"/"Outreach"). Refresh the cache when stale; look up locally with `jq`, never re-fetch per idea. **ALWAYS say WHY the tool is relevant in the line itself — never just name-drop it.** Pattern: "Saw {company} is using {tool}, assumed you {inference}." (Bjion example: *"Saw you were using Instantly and assumed you might be doing outreach."*) So each tech on the list carries its own why (the inference that tool implies), not just the name.
3. **They recently joined** (person-level, ≤ 60 days in seat). If the PROSPECT themselves joined their company in the last 60 days, they're fresh and open to new ideas. Pattern: *"Saw you recently joined {company}, and thought you may be the best person to speak to about this."* (This is the `You-joined` angle in `/lilly-icebreaker-v2`; note it uses ≤3-months by default — set the 60-day window in the strategy.)
4. **Colleague mention** (usually the BACKUP — it's so common). Names a senior peer at the same company. This is nearly free because we already **pull multiple people at parallel stature** (e.g. several sales-director-level contacts per company), so the colleagues come straight from the list we pulled, no extra data.

**MUST list the exact triggers for Hiring and Tool angles.** Any hiring or tool icebreaker on an idea has to spell out **exactly which roles trigger it** (the job titles that fire the hiring angle) or **exactly which tools trigger it** (the tool names that fire the tool angle) — never a vague "they're hiring" or "they use a tool". On the board these render as trigger chips under the angle; each idea's `icebreaker.angles[]` carries `triggers:[…]` (+ optional `triggerLabel`) for those two angle types.

**Step 4 — ALWAYS a fallback (non-negotiable).** Every waterfall ends on the generic safe opener so `{{Icebreaker}}` is never empty:
> *"Apologies if this isn't relevant, wasn't sure who the best person to speak about [X] at [company] was."*

**Step 5 — Ideate 4-5, let the user cut down.** For each idea propose **4-5 candidate icebreaker angles** (drawn from the waterfall above + any idea-specific ones), then the user cuts them to the final set. Don't pre-narrow to one.

**When a signal IS the list, the signal IS the icebreaker (Bjion ruling 2026-08-03).** For signal-vector ideas (hiring/engagement/news), the opener is a FIXED line that calls out the signal itself — that's the whole point of the list. E.g. a first-GTM hiring list opens: *"Saw you were hiring your first GTM, so I thought I'd reach out."* No dynamic waterfall spend needed (the targeting is the personalisation, same principle as followers). Keep the colleague backup + the generic fallback beneath it. The `skip_angles=["Hiring","You joined"]` hand-off to `/lilly-icebreaker-v2` still applies in its narrow sense: the DYNAMIC engine must not also fire its own generic hiring/you-joined lines on top of the fixed signal opener.

**Carry it on the run** so the board's Icebreaker page + the `{icebreaker}` merge field are populated: each idea gets an `icebreaker` block — `{kind:"fixed"|"dynamic", waterfall:[{angle, note, jobs?/techs?}], fallback:"…"}` (fixed ideas carry just the one referenced-context opener + fallback). At build, hand this straight to `/lilly-icebreaker-v2` as the strategy (it takes the order from the instruction, no menu).

---

## Phase 2c — Writing the copy + sourcing the offer (Bjion rulings 2026-08-03)

**The copy ALWAYS follows `/lilly-copywriter`.** Every email written into a run (`sequence` versions, follow-ups, the primary `email`) uses the exact same copywriting approach as `/lilly-copywriter` — ground in its three synced homes before writing a line:
1. **Rules (canonical):** the "THE NAVREO VOICE" section in `~/.claude/skills/lilly-copywriter/SKILL.md` — every rule is mandatory.
2. **Corpus:** `~/.claude/skills/offer-email-voice-match/voice-corpus.md` — real reply-winning Navreo emails; few-shot the feel, never copy the wording.
3. **Code:** `app/navreo_voice.py` in `~/navreo-signals` (`build_email_prompt` + `validate_email`) — the server-side single source of truth.
Non-negotiables: icebreaker → problem → offer; exactly ONE mechanism (lead magnet OR pay-after OR pay-per OR guarantee); no fine-print in the body; bare warm one-line CTA; service-based magnets only, never audits; no em-dashes. Don't restate the rules — point at the sources.

**Email copy uses the `/lilly-copywriter` Email-1 templates, every campaign type (Bjion
2026-08-03).** Followers and Events email 1 = **2 Service Pitch (1a)** + **2 One Sentence Punch
(1b)** across the 4 versions (the shapes in `/lilly-copywriter` → "REQUIRED OUTPUT STRUCTURE";
don't restate them). Look-a-like keeps its own fixed template (Vector 6 — already the OSP family).
The type's opener is the icebreaker line; every version carries a `P.S -` case study/sweetener —
EXCEPT Look-a-like, which carries NO P.S at all (Bjion ruling 2026-08-05).
`engine.py validate` enforces it: `_validate_framework` requires a Service Pitch AND a One Sentence
Punch on each followers/events idea + a P.S on every followers/events version (and
`_validate_type_contracts` flags any P.S on a Look-a-like); `_validate_voice` runs each version
through `navreo_voice.validate_email` (the compact Service Pitch yields on the >=3-block rule; every
other shape is a hard gate). Follow-up bumps are exempt. The concrete-proof line, P.S proof (never
on Look-a-like), and varied CTAs are part of the templates — write them in.

**Email 1 always has FOUR versions (Bjion rule 2026-08-03, every campaign idea, every type).**
`sequence[0].versions` carries 4 distinct variations of the first email — same offer and mechanism,
different angle/wording per version (for fixed-template types like Look-a-like, vary the pain
question, social-proof framing and CTA while keeping the fixed scaffolding). Follow-ups can
have one. `validate` enforces this.

**Every merge token must resolve in the Summary tab (Bjion rule 2026-08-03).** Any custom token
used in copy or an opener — `{page}`, `{events}`, `{tool}`, `{Role}`, … — must be carried on EVERY
preview person in `people[id]` (as `p.<token>` or `p.vars.<token>`) so the board's Summary tab
shows a real resolved email. The board resolves leftover `{token}`s from the person's own fields
and leaves unknowns visible — a literal "page"/"events" showing in a preview means the run is
wrong, not the render. `validate` enforces this per idea.

**⚡⚡ TEMPLATE FIDELITY — the copy never leaves the fixed shapes (Bjion rulings 2026-08-05,
the fidelity loop).**
1. **Template lock.** Every version is exactly ONE named template shape — Service Pitch (1a),
   One Sentence Punch (1b), the Vector 6 Look-a-like scaffold, or a fixed-opener type shape —
   and the ONLY writing happens inside the bracketed slots. Scaffolding stays verbatim; never
   invent a new shape, add a section, or reorder one. If no template fits the ask, SAY SO and
   ask which shape to use — never freestyle one.
2. **No industry callouts in hiring-signal copy.** Hiring pulls are filtered by ROLE, not
   industry (~90% of pulls carry no industry filter), so copy and openers never name a
   specific industry or vertical unless the idea's `pull_spec` actually filters industry.
   Role-anchored language instead: "teams hiring SDRs", never "SaaS companies hiring SDRs".
   Social-proof fills stay truthful to the real case study, but must never imply the
   recipient is in that industry.
3. **The final read (cohesion sweep) — mandatory, after assembly.** Read every version
   top-to-bottom as ONE message from one person. Fix stitched joins (sections that don't
   talk to each other), dangling references, and typos ("Can I sent it over?" → "Can I send
   it over?"). Every sentence must follow from the one before it. Log the sweep per version
   in the session file (flaws found + fixed, or "clean") — an unswept version doesn't ship.

**Offer sourcing — when there's no known offer.** The offer in the copy comes, in order:
1. **Previous campaigns** (Phase 1 retro): reuse the offer already proven for this client.
2. **The user gives one** in the brief.
3. **Neither?** → use the tool's own **Offer Maker** to ideate offers and pick from them: the page is https://navreo-signals.onrender.com/app/offer.html; programmatically it's `POST /api/offer/generate` (public endpoint, body carries the client's website URL — it fetches the homepage and returns 12-18 cold-email offer ideas; `POST /api/offer/email` writes a worked email for one offer). Surface the best few offer ideas for the user to pick (same ideate-then-cut pattern as icebreakers), then write the copy on the chosen offer. Never invent an offer from thin air when this tool exists.

---

## Phase 3 — Lead-magnet brainstorm

Goal: 5-10 lead-magnet ideas the client can actually deliver. Each shortlisted campaign idea in Phase 5 will pair with ONE of these.

**Delegate to `/lead-magnet-brainstorm`** with the client's Phase 0 data:
- "What they sell" (Q2 from intake) → maps to lead-magnet-brainstorm Q1
- ICP's pain point (Q3 from intake or memory) → maps to lead-magnet-brainstorm Q2
- Existing constraints (Q6 from intake) → maps to lead-magnet-brainstorm Q4

Receive back: a scored table of 5-10 magnets (per lead-magnet-brainstorm's rubric — ≥15/20 score).

**Filter the brainstorm output** against the "Killed angles" from Phase 1 — if the client already ran "free Amazon audit" as a magnet and it failed, drop it (or note it as "previously failed: re-pitch only if novel delivery angle").

Save the magnet shortlist alongside the session file (`<client>-<date>.md` includes both the magnets and the campaign ideas).

---

## Phase 4 — TAM probing (LLM-first, API-probe top 5)

Goal: validate Phase 2's TAM estimates cheaply. LLM estimates are ±50% accurate; API probes confirm size + sample-fit before any idea makes the shortlist.

**All probing and pulling runs through `/lilly-tam`.** It is THE prospect skill (it replaced tam-mapper / dm-finder / prospeo-list-builder) — use its probe shapes for every Company-TAM and findable-DM number below; never hit a provider directly outside them.

**Step 1 — LLM pre-rank.** For each angle from Phase 2, score on a back-of-envelope 1-5:

| Dimension | What it means |
|---|---|
| **TAM-estimate** | LLM-guessed reachable prospect count. 1 = <100, 5 = >10K. |
| **ICP-fit** | How tightly the angle hits the client's ICP. 1 = adjacent, 5 = bullseye. |
| **Novelty** | Whether this angle has been tried before (per Phase 1 history). 1 = exact prior failure, 5 = unexplored. |
| **Buying-intent** | How "hot" the signal is. 1 = cold-cold (broad TAM list), 5 = hot-hot (recent hire + recent funding + competitor engagement layered). |
| **Delivery-friction** | How much manual setup the build needs. 1 = lots of glue + scraping, 5 = pure API + existing skills. |

Sum to get a **gut score (5-25)**. Cut to top 5-8 angles before any API call.

**Step 2 — API-probe the top 5.** For each top-5 angle, fire ONE 1-credit probe to confirm:

| Mechanism | Probe |
|---|---|
| **Targeted TAM list** | `lilly-tam` Stage 0.5 saturation probe: 1 Ocean lookalike call with the angle's filter, sample 50. Report `totalElements × sample_precision` as Estimated TAM. |
| **Hiring signal** | `lilly-theirstack-setup` Phase 2 free-preview test: title-pattern search over 30-day window, report `30d_tam` + `fit_pct`. Free credits-wise (TheirStack free previews). |
| **LinkedIn engagement** | Manual: look up each tracked profile's recent post engagement counts (LinkedIn UI — 1 minute per profile). Report avg engagers/post × posts/month. |
| **Events** | Lookup attendee/exhibitor count (event website or past-edition PDF). Free, manual. |
| **LinkedIn followers** | Look up each target page's follower count via LinkedIn — verify with `lilly-linkedin-page-finder` if not already known. Free. |
| **Lookalikes** | `lilly-tam` Stage 0.5 with named-client seeds. 1 Ocean credit. |
| **News intent** | `lilly-icebreaker-news-search` test query against ~10 representative ICP companies. Report hit-rate × annualized. ~10 Serper credits. |
| **Prospeo signal filter** | `lilly-tam` `/search-company` probe with the angle's new-filter shape (`company_key_execs` / `company_funding` / `company_integrations` / `company_attributes` / `company_news` / `company_key_customers` / `company_website_traffic` / etc.) layered on the brief's stock ICP filter. 1 credit. Report `total_count` as the **Company TAM**. |

**Step 2b — NET decision-maker TAM (every idea; Bjion ruling 2026-07-16).** The ONLY TAM number that ever appears in any output is **net findable decision makers**. Company counts are internal working data — never show them, never headline them, never put them in a table.

```
NET DM TAM  =  /search-person total_count  ×  net ratio (from the free sample-vs-history check)
```

**⚙️ ENGINE (numbers are engine-produced, never hand-computed).** Write each idea's `pull_spec` (provider + exact filters — schema in `engine/README.md`), then:
- `engine.py probe --run run.json --idea <id>` — gross count from the spec's provider (`prospeo_person` 1 cr · `theirstack` free · `aiark_people` ~1 cr); page-1 sample domains returned, rows auto-cached + ledger written.
- `engine.py net --client <slug> --domains <probe sample domains>` — the 30-day cooldown router: terminal / cooldown / free-from-records / new + net ratio, exactly per the split below.
- Record both outputs on the idea (`probe`, `netting`) — `engine.py validate` fails any idea whose numbers lack a probe provenance. The same `pull_spec` later drives the /lilly-tam build (probe-confirmed shape = build shape).

- **The probe is `/search-person` page 1 (1 credit):** the idea's company shape passed top-level (verified: `/search-person` accepts `company_industry` / `company_keywords` / `company_headcount_range` / `company_location_search` with no domain list) + the `dm_titles` title family + Director+ seniority. Read `pagination.total_count` = **gross findable DMs**. This is the cheapest accurate DM count that exists — never estimate it, never derive it by multiplying a company count.
- **Suppression-first netting (free; 30-day cooldown rule, Bjion 2026-07-16):** check the page-1 sample's domains/people against Supabase `contact_history` + `suppressions` (free SQL) and split three ways:
  1. **Cooldown — excluded from NET:** contacted for THIS CLIENT within the last 30 days (or currently enrolled in an active campaign), plus terminal excludes (suppression list, positive repliers — never re-cold-emailed).
  2. **Free from records — IN the net:** contacted before but outside the 30-day window. These are re-pullable at ZERO provider cost from our own archive (contact_history/people/enrichments already hold their email + fields) — never re-purchased from a provider.
  3. **Fresh — IN the net:** never contacted; these are the only rows that cost provider credits at build time.

  Report **NET = gross − cooldown**, with the split shown: "2,100 gross → 1,900 net (of which ~700 free from records, ~1,200 paid pull)". The split IS the cost forecast per idea.
- **Never pull rows, never enrich, never verify at this phase.** Strategy costs 1 credit per idea, full stop. Row pulls and email spend belong to the build skill after sign-off.
- `dm_titles` still comes from Phase 0 and is confirmed with the user; it defines the title family inside the probe, not a multiplier.

**Cost ceiling for Phase 4: 1 credit per idea, hard.** One `/search-person` page-1 probe per shortlisted idea; the suppression netting is free SQL. No row pulls, no enrichment, no verification — those are build-phase spend, after sign-off. Per `feedback_lilly_strategy_probe_tam_first`, probe every idea — estimates are never the headline.

**Step 3 — Update scores.** Replace LLM guesses with the probe-confirmed **NET DM TAM** and re-rank if a probe shifts the order materially. Score on net DMs — it is the sendable-lead pool.

---

## Phase 5 — Score & shortlist

Goal: produce a single shortlist that hydrates the artifact and is saved to the session file. **It does NOT go in the chat** (guardrail 16 / Purpose banner).

**Final shortlist size: top 5-10 ideas.** Lean to 5 if the client has bandwidth for 1-2 campaigns; lean to 10 if it's a strategy-call menu where the client picks 3-5.

**Output format (use this verbatim — the table goes into `sessions/<client>-<date>.md` and is what you hydrate the artifact's `IDEAS` array from. NEVER print it in chat):**

```markdown
# Campaign Strategy Shortlist — {Client Name}
**Date:** {YYYY-MM-DD}
**Briefed by:** {user name or "Bjion"}
**History snapshot:** {N active campaigns, K dead angles from Phase 1}

## Recommended campaign menu

| # | Campaign idea | Mechanism | Lead magnet | **Decision makers (net)** | gross → net | ICP-fit | Novelty | Intent | Total score | Build chain |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **[Idea title, 6-10 words]** | [Targeted list / Hiring signal / etc.] | [Magnet #N from Phase 3] | [**net findable DMs**] | [gross probe → net after suppression] | [1-5] | [1-5] | [1-5] | [/20] | [skill chain] |
| 2 | ... | | | | | | | | | |
...

**TAM column rules (Bjion ruling 2026-07-16):**
- **Decision makers (net) is the ONLY size number.** No company counts, anywhere, in any output — internal working data only.
- It is **probe-confirmed** (`/search-person` page-1 `total_count`, 1 credit) and **suppression-netted** (free history check) — never estimated, never a company-count multiple.
- The `gross → net` column shows the suppression haircut so the netting is transparent.
- Client-facing exports: label it "Reachable decision makers", per the plain-English guardrail.

## Recommended top 3 (where to start)

Ranked by **(Total score × delivery-friction)**:

### 1. {Idea title}
- **What it is:** [2-3 sentences plain English]
- **Why it'll work:** [tie to Phase 1 reply-pattern data if available, else ICP rationale]
- **Lead magnet:** [magnet name + 1 sentence on delivery]
- **Build chain on sign-off:** {skill 1} → {skill 2} → {skill 3}
- **Approx. credit budget to launch:** [N credits, sum from probe + build]

### 2. ...

### 3. ...

## Brainstormed but cut

(Briefly list 2-5 angles that scored below cut, with one-line "why cut" — useful so the client can challenge and we can put them back in if they want.)
```

**Score cut threshold:** ≥13/20 makes the shortlist. <13/20 goes to "Brainstormed but cut".

**File save:** write the full markdown to `sessions/<client-slug>-<YYYY-MM-DD>.md`. If a session for the same client + date already exists, append `-rev2`, `-rev3`, etc. Don't overwrite — strategy sessions are versioned for traceability.

**⚡⚡ THE BUILD ISN'T DONE UNTIL {{Icebreaker}} IS FILLED (Bjion ruling 2026-08-04, learned on campaign 3760383).** Ideating the icebreaker strategy is NOT the same as executing it. Any upload into a Smartlead campaign whose copy carries `{{Icebreaker}}` MUST fill the per-lead Icebreaker custom field AT UPLOAD TIME, resolved from the idea's `icebreaker` block: a fixed opener resolves its merge vars per lead from the build data (e.g. the stack line fills `{tool}` from the per-company tech detection — keep the domain→trigger map from the pull, it IS the icebreaker data); a dynamic waterfall executes via `/lilly-icebreaker-v2`. Every unresolvable lead gets the generic fallback — never a blank, and NEVER an inherited value: rows recycled from our own records (free-from-records) carry STALE icebreakers from past campaigns ("Saw you're hiring an SDR…" on a stack list was the 3760383 failure) — always overwrite the field, never trust what rode in. The upload gate's variable-fill check counts `{{Icebreaker}}` like any other merge var.

**⚡⚡ ALWAYS NORMALISE THE COMPANY NAME — EVERYWHERE IT RENDERS (Bjion ruling 2026-08-04).** Run `app/name_hygiene.clean_company_name` on `company_name` AND on every company name embedded inside an icebreaker, across EVERY signal and fixed list — the engagement post author (`Saw your comment on {author}'s post…`), the new_exec subject company, the followers page. The 2026-08-04 engagement bug was a raw post-author name leaking into the opener ("CMA Exam Academy - Pass the Exam on Your First Try!'s post"). Normalise the same as the job title (`clean_job_title`). **Caveat:** normalisation is syntax-only — it returns a mangled source value ("Combu" for Combustion Institute) unchanged. It does NOT verify the name is correct; only the send-ready read does. Cross-check `company_name` ↔ email domain ↔ website; if they disagree the row is corrupt — drop it.

**⚡⚡ THE QUALITATIVE SEND-READY READ IS A GATE, NOT A FORMALITY (Bjion ruling 2026-08-04).** Before declaring any campaign built, RESOLVE ≥3 sample emails fully — merge every field, pick one spintax render — and READ each as the recipient. Field-presence checks pass leaked fallbacks, mangled names, and cross-client stale fields; only the read catches them. A lead is NOT send-ready if: (1) a generic fallback/placeholder leaked into the sentence ("another lead-generation/GTM company", "your company") — the specific hook is missing, so SUPPRESS the lead, never ship the stand-in; (2) `{{company_name}}` renders a truncation/all-caps blob/domain-mismatch; (3) the trigger is one the recipient would dispute (a new-exec line sent to the new exec; a post-sale "Account Manager" pitched as a skip-the-BDR reason); (4) the row carries another client's custom fields; (5) the first two sentences don't sound like a human who actually looked. One NO blocks the campaign. Same enforcement lives in `/signal-launch-dryrun` Step 4b.

**⚡ IDEATION INCLUDES THE ICEBREAKER STRATEGY (Bjion ruling 2026-08-03).** Ideating a campaign is not complete without its icebreaker (opener) strategy — full methodology in **Phase 2b** (fixed-vs-dynamic decision, the avoid-list, the Hiring→Tech→Colleague default waterfall, always a fallback, ideate 4-5 then the user cuts down). Carry each idea's `icebreaker` block on the run so the board's Icebreaker page + the `{icebreaker}` merge field are populated; hand it to `/lilly-icebreaker-v2` at build. Never leave the Icebreaker stage empty.

### Phase 5 closing step — LAUNCH THE BOARD (mandatory, every run; Bjion ruling 2026-07-27)

Ideation is not done until the tool's live board is serving this run. This is THE deliverable; the table above is the session-file record, never a chat paste.

**⚡ SESSION-SCOPED RUNS (strategy-session-share, Bjion ruling 2026-08-02).** Every chat session gets its OWN board — the whiteboard for THIS session's set of ideas — so sessions never overwrite or taint each other:
- **Mint a `run_id` ONCE per chat session**, at the first publish: `<client>-<YYYYMMDD>-<4 random lowercase alphanum>` (e.g. `navreo-20260802-k3f9`; must match `^[a-z0-9][a-z0-9-]{2,58}[a-z0-9]$`). Reuse THAT id for every re-publish and edit in the same session. A NEW session NEVER reuses an old run_id — reopening an old board is an explicit ask ("open the <client> board from <date>"), served read-mostly at its own URL.
- **`run.json` carries `"run_id"`** top-level. POST `/api/strategy/run` stores it under its own key (`wizard_run:<run_id>`); a POST without run_id hits the legacy shared board and returns a warning — treat that warning as a bug in the run.
- **The board URL is keyed:** `https://navreo-signals.onrender.com/app/strategy.html#/r/<run_id>`. EVERY link, `open`, and SendUserFile hand-over uses this URL, never the bare page (bare = whatever session published last).
- **Focus signals carry `run_id` too** (`POST /api/strategy/focus {run_id, ideaId, view, note}`) so this session's chat-mirror never steers another session's open board.
- **Client share permalink:** when the user wants to share with a client (or the run reaches ready-to-share), `POST /api/strategy/share {run_id}` (authed) returns the permalink URL (`/app/strategy.html?share=<token>#/r/<run_id>`). The client opens it logged-out and sees ALL pages — Targeting, Icebreaker, Copy, Summary and Launch (amended 2026-08-02: the whole story is visible; ONLY the Build button and the share block are GTME-only and never enter their DOM). They can edit the copy in place, and their saves reflect on the GTME's board within one poll (`edited_by:"client"` + per-idea `clientEdits` stamps). Only copy fields can ever come back through that door. The Launch page (renamed from "Live") checklist IS the `lilly-upload-gate` pre-checks — the real QA that runs just before the receipt/upload. Copy checks (signature present, spam scan, opt-out line) are computed live from the email; the list checks tick ONLY on verified-evidence flags the gate/chat stamps when the work is actually done — `idea.checks` / run-level `checks` with keys mirroring the gate: `schema`, `normalisation`, `variable_fill`, `spintax`, `recontact`, `email_verification`, `list_audit` (plus `grammar`). Never claim a tick by editing copy alone. The Summary/Preview page highlights every substituted merge variable and puts each prospect's website/LinkedIn links in their thumbnail. **Those links MUST be DIRECT (Bjion ruling 2026-08-05): every preview prospect carries `website` (the real site, `https://<domain>`) and `linkedin` (the person's real profile URL), so Website ↗ opens the site and LinkedIn ↗ opens their profile — never a Google/LinkedIn search page.** Preview people are best pulled real (a `/search-person` page-1 gives name + company + domain + `linkedin_url`), globally de-duped so no company repeats across any idea's preview; illustrative people still need at least `domain` (the board derives a direct website link from it).

1. **Write `run.json`** (schema: `engine/README.md`) — the session writes the creative fields (names, offers, who-lines, pains, why-lines, example people, colleagues, footer); the numbers (`net`/`gross`/`freeFromRecords`/`newPeople` + `probe`/`netting` provenance) come from the engine's Phase-4 outputs, and every idea carries its `pull_spec` AND its `targeting` block (label/roles/excluded/meta/note — the board renders the roles as editable chips). **The `who` line IS the Targeting page's idea description, and it PITCHES the idea, never just describes it (Bjion ruling 2026-08-05): two sentences — `Targeting [who] at [companies showing the signal]. This works because [why that signal means they need the offer right now].` A `who` that only restates the mechanism is a defect.** Running campaigns go in a top-level `shelf` array (`[{name, net, status, note}]`), never as menu ideas — the board shows them on a separate "Already running" shelf. Save it as `sessions/<client-slug>-<YYYY-MM-DD>-run.json`.
2. **Validate via the engine:** `engine.py validate --run run.json` (must pass — enforces probe-confirmed numbers, the ≥3-vector mixture on boards of 5+, no audit offers, DM-only language).
3. **POST the run to the tool:** mint a `navreo_session` cookie (recipe: memory `signals-live-verify-recipe` / `_mint_session` in `~/navreo-signals/app/server.py` — HMAC signs the RAW payload bytes, not the b64 token), then
   `curl -s -X POST -H "Cookie: $C" -H "Content-Type: application/json" --data-binary @run.json https://navreo-signals.onrender.com/api/strategy/run`
   The response must be `{"ok": true, ...}` — anything else is a failed publish (the endpoint reports real storage errors; never claim the board updated on a non-ok). The server strips engine-only fields (`vector`/`probe`/`netting`/`pull_spec`) before the page ever sees them.
4. **Point the user at the board AND auto-show it in chat — every publish and every update (Bjion ruling 2026-07-30, supersedes any "link alone is the door" / "browser pane is agent-side only" framing).** The user CANNOT see the prod board in the agent's browser pane, so NEVER rely on the link alone — a run they can't see is a failed run. On the initial publish AND on every chat-driven update (targeting change, number change, reframe), immediately RENDER the run to the user with `SendUserFile` (`display:"render"`): hydrate the wizard page (or a companion page from the same run.json) and send it so it opens in their side panel. **This in-chat render is the HARD RULE at the top of this file — always open the strategy dashboard in the chat browser, no exceptions; a link or a real-browser `open` never satisfies it on its own.** Pair it with the WELCOME MESSAGE (see the "## WELCOME MESSAGE" section): the plain-English briefing that summarises the ideas and tells the user how to progress, ending on the board link https://navreo-signals.onrender.com/app/strategy.html for the fully-interactive board (where they pick/approve/build). This does NOT violate guardrail 16 — "no results in chat" means no TYPED menu / table / top-3 / per-idea numbers pasted as text; you SHOW the rendered page, you never paste the results. (The dev-server-in-pane recipe — 7901 + `signals-attach` + `/api/_mock/dev-login` — is optional agent-side verification, not a substitute for auto-showing the user.)
   **Open it in the CLAUDE BROWSER only (Bjion ruling 2026-08-03, supersedes the 2026-08-02 real-browser `open` + SendUserFile render).** After the POST returns `ok`, mint the share token and `mcp__Claude_Browser__navigate` to `strategy.html?share=<token>#/r/<run_id>` — that pane is the user's view. Never macOS `open`, never a SendUserFile template snapshot.

**⚡⚡ READ-MODIFY-WRITE — never republish a locally rebuilt run over a board the user may have touched (Bjion ruling 2026-08-04, learned the hard way).** The user edits copy DIRECTLY on the board (GTME edits and share-link `copy-edit`s both land as superseding rows). A re-POST of a script-rebuilt run.json SILENTLY CLOBBERS those manual edits. So EVERY update after the first publish MUST: (1) GET the current live run (`/api/strategy/run?run_id=…`, or the latest `campaign_insights` row `scope=strategy, insight_key=wizard_run:<run_id>`), (2) apply ONLY the requested delta to that payload, (3) POST it back. Build scripts are for the FIRST publish only. If a clobber does happen, the full history survives as `superseded` rows in `campaign_insights` — diff the user's last pre-clobber row against live and restore their fields verbatim (never "improve" their text while restoring). Fields carrying `clientEdits` stamps are the user's hand-written text: treat as untouchable unless the user explicitly asks to change them.

**Chat edits (the live loop):** when the user asks for a targeting change ("drop Account Executive", "add Head of Growth", "US only"), apply it per the read-modify-write law above (roles + a re-probed number when the change is material — TheirStack re-probes are free; never hand-write a changed number), re-validate, re-POST. The page polls every 5s, so the change appears in the UI while they watch, with an "updated from chat" stamp. Journey state (approvals, builds) survives repaints; a targeting change rebuilds that idea's chips because chat is the source of truth.

**⚡⚡ EDIT-ONE-THING LAW + DIFF RECEIPT (Bjion ruling 2026-08-05 — no more guessing what
changed).** A requested edit touches ONLY the named field of the named version/idea — every
other byte of the run stays identical. Mechanics: a single-field copy edit goes through the
board's own surgical door, `POST /api/strategy/copy-edit` `{run_id, ideaId, field, value}`
(field grammar: `version:<i>[:subject]` · `seq:<step>:<ver>[:subject]` · `ice:<n>` ·
`ice:fallback`); anything wider uses read-modify-write with the delta applied to the LIVE
payload. NEVER re-run copy generation and re-POST a rebuilt run because one line changed —
regeneration happens only on an explicit "rewrite this" ask, and even then only the named
version(s). Every edit is answered in chat with a one-line diff receipt:
`changed <idea> · <field> · "<before>" → "<after>" · nothing else touched`. If an edit forces
a knock-on change elsewhere (rare: a token rename), NAME the knock-on in the receipt — a
silent second change is a defect.

**Merge variables in copy/icebreaker edits (Bjion ruling 2026-08-03):** any `{curly-brace}` token in copy, openers, examples or fallbacks — `{company}`, `{firstName}`, `{Role}`, `{colleague}`, `{tool}`, `{{Icebreaker}}` — is a MERGE VARIABLE resolved per-lead at build/send time, never fixed text. When the user supplies or edits a line containing one (e.g. *"I noticed {company} is hiring a {Role}, and thought I'd reach out."*), keep the token VERBATIM (casing included) — never substitute a literal value for it, never "fix" it as a typo, never resolve it to an example. The reverse edit is just as deliberate: swapping a hard-coded word for a variable (e.g. "an estimator" → "a {Role}") generalises the line — that IS the edit, apply it as given. When an edit introduces a NEW token, make sure it's resolvable per-lead at build time (e.g. `{Role}` fills from the hiring-angle trigger that fired for that company) and that the build hand-off names where it comes from; the board highlights tokens automatically, so an unresolvable token will still render as if real — the render proves nothing about fill.

**Focus signals — the page follows the conversation (chat-mirror, Bjion rulings 2026-07-27: chat leads, UI mirrors; blend M2 rail + M3 spotlight live as ecc72d7).** Alongside every run POST, POST where you are working so the open board navigates itself there:

```
curl -s -X POST -H "Cookie: $C" -H "Content-Type: application/json" \
  -d '{"ideaId":"<id-or-null>","view":"<view>","note":"<≤8 plain words>"}' \
  https://navreo-signals.onrender.com/api/strategy/focus
```

`view` ∈ board · targeting · emails · opener · checks · building · signoff. Fire one at every phase of live work, AFTER the run it refers to is on the board (a focus at an empty board is a no-op):

| Working on | POST |
|---|---|
| Board published / refreshed (Phase 5 close) | `{view:"board", note:"Fresh ideas on your board"}` |
| Probing or editing an idea's targeting | `{ideaId, view:"targeting", note:"Removing Account Executive"}`-style, one per material change |
| Writing or reworking email copy | `{ideaId, view:"emails", note:"Writing your emails"}` |
| Opener work | `{ideaId, view:"opener", note:"Choosing the opener"}` |
| Upload gate / QA running | `{ideaId, view:"checks", note:"Running the checks"}` |
| Background enrichment / verification / list build | `{ideaId, view:"building", note:"Double-checking the list"}` |
| Idea launch-ready, awaiting the user | `{ideaId, view:"signoff", note:"Ready for your sign-off"}` |

Notes are ≤8 words, present tense, a 16-year-old's English, no jargon, no em-dashes. The page holds still if the user's hand is on it (10s window, "Catch up" chip) — never assume the view moved; the signal is fire-and-forget. The board shows the note in its activity rail and sweeps the surface being changed, so narrate honestly: one focus per real action, never decorative spam.

Done-rule: `GET /api/strategy/run` returns this run's `updated` stamp and the page renders this client's ideas. A run that publishes the board but ALSO dumps the results in chat is a defective run (guardrail 16); a run that ends with a chat table but no board POST is an incomplete run.

---

## Phase 6 — Build hand-off (per approved idea)

**⚡ THE LAUNCH GO-AHEAD CODE (board Launch page → build, Bjion ruling 2026-08-03).** The board no longer has a "Build the campaign" button. Instead the Launch page shows a **final go-ahead block** with a stable per-idea code and the exact line to paste in chat: `Launch "<idea name>" · code LAUNCH-XXXXXX` (the code is `launchCode()` in strategy.html: a deterministic hash of `run_id:idea_id`, uppercase base36, so it's the same every render and unique per idea). When the user pastes that line, treat it as the FINAL sign-off to build THAT idea:
1. Confirm the code matches the idea on this run (recompute it the same way, or match the idea by name) — a mismatched/absent code is not a launch.
2. Run the build chain for the idea's vector (Phase 6 table below): `/lilly-tam` (or the vector's build skill) with the idea's probe-confirmed `pull_spec` → create the Smartlead campaign → **`/lilly-upload-gate`** on the pulled list (the gate that also produces the checks the Launch page previews). Never skip the gate.
3. As the gate runs, stamp the Launch checklist evidence flags back onto the run (`idea.checks.{schema,normalisation,variable_fill,spintax,recontact,email_verification,list_audit,grammar}`) and re-POST so the board's checklist ticks live.
4. **On completion, post EXACTLY three links in chat, in this order:** (1) the **Campaign page** in the tool (`…/app/campaigns.html#/c/<id>`), (2) the **Upload-gate receipt** (the gate's audit record / review page), (3) the **official list** in the tool (the campaign's Leads/list page). Nothing sends — the campaign stays paused until the user launches it from Smartlead.

When the user (or the client via the user) says "approve idea #N" (without the code), produce the pre-filled brief below but do NOT pull/build — the launch code is the spend gate.

**⚡ A SHARED LINK CARRIES THE EXACT PULL RECIPE — any teammate with the same tool access can pull the identical list (Bjion goal 2026-08-04).** The run is stored server-side WITH its `pull_spec`/`probe`/`netting`; the board and client shares strip those, but an AUTHENTICATED GTME request gets them back via `GET /api/strategy/run?id=<run_id>&full=1` (with a `navreo_session` cookie). So a teammate needs only the keyed link + their own tool login + the provider keys (Prospeo, GetLeads, ListMint, Smartlead) + Claude Code with the lilly skills — no synced local `run.json`. To build from a link: mint/copy the session cookie, `GET …/api/strategy/run?id=<run_id>&full=1`, read each idea's `pull_spec`, and feed it VERBATIM to `/lilly-tam` (same shape the probe confirmed = the build shape). A logged-out client share NEVER receives `full=1` (the route ignores it without a session), so the recipe stays GTME-only. `engine.py handoff` still works off a local `run.json` when you have one; the `full=1` fetch is the path when you only have the link.

**⚙️ ENGINE:** `engine.py handoff --run sessions/<client>-<date>-run.json --idea <id>` renders the brief — headline numbers with probe provenance, the idea's exact probe-confirmed `pull_spec` for `/lilly-tam` to execute verbatim, and the house build rules (suppression-first waves, free→cached→paid). For non-tam vectors the pull_spec still records the source (theirstack shape, follower export, tracked profiles) and the table below names the build skill:

| Mechanism | Build skill | Brief format |
|---|---|---|
| Targeted TAM list | `/lilly-tam` | ICP filters (verticals/roles/geo/size) + seed domains + soft-category flag |
| Hiring signal | `/lilly-theirstack-setup` | ICP description + offer + signal rationale + 4-6 candidate title patterns |
| LinkedIn engagement | `/lilly-trigify-setup` | ICP + offer + signal rationale + tracked-profile slugs + `skip_angles=["Hiring","You joined"]` |
| Events | (Manual + `/loom-research` for additional event context) | Event name + date + scrape source |
| LinkedIn followers | `/lilly-linkedin-page-finder` then `/lilly-company-followers` | Target page slugs + ICP qualification criteria |
| Lookalikes | `/lilly-tam` Stage 1 lookalike-only | Seed domains + cumulative-exclude defaults |
| News intent | `/lilly-icebreaker-news-search` against a TAM list | TAM source (Phase 1 existing list or new TAM build) + signal types to include |

For each approved idea, produce ONE markdown block the user can paste straight into the build skill's invocation:

```markdown
## Approved: Idea #{N} — {title}

**Hand-off to:** /{build-skill-name}

**Brief:**
- {field 1}: {value}
- {field 2}: {value}
...

**Lead magnet to use:** {magnet name from Phase 3}
- **Delivery:** {1-sentence delivery method}
- **CTA template:** {1-line CTA}

**Expected credit budget:** {N credits}

**Smartlead campaign target name:** {client-slug}-{mechanism}-{slug-from-idea-title}
```

**Don't auto-fire the build skill.** Hand the block to the user; they invoke the build skill manually. Keeps the credit-spend gate in their control.

---

## Optimiser hand-off (passive trigger)

`/lilly-optimiser` flags certain conditions that suggest fresh ideation is needed. When the user reads those flags in an optimiser output, they may invoke `/lilly-strategy` to ideate replacements. Conditions:

| Optimiser flag | Why it suggests /lilly-strategy |
|---|---|
| **Campaign kill threshold hit** (15K+ sent, ratio > 2,500/positive) | ICP/offer mismatch — needs a new angle, not new copy |
| **Variant exhaustion** (all 4 offer variants failed Phase 1 at 800 sent) | Offer angle is wrong — re-ideate from Phase 3 lead-magnets |
| **No positive replies in 30 days** across an active campaign | Channel or angle dead — replace |
| **75%+ completion with no fresh leads queued** (Lifecycle Section) | TAM exhausted — ideate adjacent angles |
| **Response-breakdown reveals divergent reply ICP** | Actual ICP ≠ nominal — spin off a sub-campaign for the real ICP |

`/lilly-optimiser` includes a passive one-line mention of `/lilly-strategy` in any Section 8 (Recommended Actions) entry that matches one of these flags. The mention reads:

> *Consider `/lilly-strategy {client-slug}` to ideate replacement angles.*

`/lilly-strategy` does NOT trigger automatically from optimiser output — the user reads the mention and invokes if they want fresh ideation.

When invoked post-optimiser, **skip Phase 0 client briefing** if the client profile exists (just confirm freshness), and **carry forward the optimiser output** to Phase 1 instead of re-running it.

---

## Output contract

| Phase | Output |
|---|---|
| 0 | `clients/<client-slug>.json` (created or refreshed) |
| 1 | Markdown block: active campaigns + dead angles + reply patterns |
| 2 | Markdown table: 7 vectors × 2-5 angles each = 15-30 raw ideas |
| 3 | Markdown table: 5-10 lead magnets with delivery method + CTA |
| 4 | Updated angle list with probe-confirmed **Company TAM** + computed **DM TAM (= Company × N)** (per Step 2b) + sample-fit % |
| 5 | **The standing wizard artifact republished with this run's ideas** (Phase 5 closing step) + `sessions/<client-slug>-<YYYY-MM-DD>.md` |
| 6 | (On approval) Per-idea hand-off blocks ready for build skills |

Headline deliverable = the hydrated wizard artifact at https://claude.ai/code/artifact/5d6e5fdd-69d8-48f2-be8e-bec57da7b51f; the Phase 5 session file is the durable record. Everything before it is working notes.

---

## Guardrails

1. **Never auto-fire build skills.** This skill ideates and hands off; the user fires the build skill manually. Credit-spend stays under their control.
2. **Never re-pitch a dead angle without flagging it as a re-pitch.** If Phase 1 shows an angle was killed, and Phase 2 surfaces it again, mark it `[re-pitch: previously killed because X — only worth retrying if Y]` rather than silently re-suggesting.
3. **TAM column always uses the 3-column rule** (per `lilly-tam` rule #27): label each number as **Verified (sample)** / **Estimated TAM** / **Pulled (full)** — never a single ambiguous number.
4. **Cap Phase 4 probes at top 5 angles.** Probing all 15-30 raw angles would burn 30+ credits. The LLM pre-rank in Phase 4 Step 1 must cut to 5-8 before any paid call.
5. **No em-dashes.** Use commas / colons / parentheses (per `feedback_no_em_dashes`).
6. **Plain English, no jargon — everywhere the user reads (widened 2026-07-27).** Chat, the board, and client-facing exports all follow the CHAT VOICE section: 16-year-old English, no tool or provider names, no trade shorthand. Only session files and run records keep technical detail.
7. **Always show the "Brainstormed but cut" section.** Even when 20 angles get cut, list at least the 5 strongest cuts so the user (and client) can challenge the cut.
8. **Hyperlink every named client, competitor, and event** in the output. LinkedIn slugs for companies (`[name](https://linkedin.com/company/slug)`), official URLs for events. The user reads this on a call with the client — clickable references matter.
9. **Always pass `skip_angles=["Hiring","You joined"]` to lilly-icebreaker** when handing off to a hiring-signal or engagement-signal campaign (per `feedback_hiring_signal_icebreaker_skip_angles`). Note this explicitly in Phase 6 hand-off blocks.
10. **Idempotent re-runs.** A second run for the same client on the same day appends `-rev2` to the session file rather than overwriting. The client may iterate on the menu during a strategy call — keep all versions.
11. **Memory before questions.** Before asking any Phase 0 question, scan `MEMORY.md` for `project_<client>_*` entries. Many clients have ICP / role / vertical / account memories already populated. Ask only what's missing.
12. **Mandatory delivery-friction column.** Two ideas with identical TAM × Fit × Novelty × Intent scores get tiebroken by delivery friction (per Phase 4 Step 1). Surface this explicitly so the user can pick the easier-to-build one when scores tie.

13. **Named-entity depth (every vector, every angle).** Category-level abstractions ("competitor founders", "cold-email thought leaders", "marketing agencies") are not acceptable in any vector's output. Every angle must drill to:
    - **V1 (Targeted lists):** named example companies from the probe sample (5 cos minimum) + hyperlinked LinkedIn slugs + WHY column tying to a named-client pattern
    - **V2 (Hiring signals):** named example job titles from the TheirStack sample + WHY column anchored on Navreo's offer-to-signal mapping
    - **V3 (Engagement signals):** 5 named companies (with follower-count estimates) + 5 named thought-leaders (with follower-count estimates) + WHY column per row
    - **V4 (Events):** event name + dates + location + WHY ICP exhibits there (not attends) + est. relevant exhibitor count
    - **V5 (Followers):** named target pages + estimated follower counts + WHY their followers fit
    - **V6 (Lookalikes):** AI Ark lookalike URLs in `https://app.ai-ark.com/search/company?value=https%3A%2F%2Fwww.linkedin.com%2Fcompany%2F{slug}` format (per `loom-research` SOP) — one per seed, NOT one mixed-seed mega-search
    - **V7 (News/intent):** named recent news examples (e.g. specific funded cos from the last 30 days) + WHY each sub-signal type matters + per-probe Serper credit cost
    - **Every probe row must also surface its credit cost** explicitly (Prospeo cr / TheirStack free / Serper cr / manual UI lookup) so the user can audit spend per angle.

    Why this rule exists: category-level outputs let the client read past them without noticing what's actually being proposed. Named entities force the client to evaluate the actual companies / people / events on the table. Rule codified after HeyGrand rev2 caught the abstraction failure (2026-05-18).

14. **NET decision makers is the ONLY number; company counts never appear (Bjion ruling 2026-07-16).** Every idea's size = `/search-person` page-1 `total_count` (gross findable DMs, 1 credit) × the suppression net-ratio from the free sample-vs-`contact_history`/`suppressions` check. Never report a company count in any output; never derive DMs by multiplying companies × titles; never spend more than 1 credit per idea at strategy time; never pull or enrich rows before sign-off. Suppression netting is mandatory — we already own the contact history, so no idea is sized gross.

15a. **All offer/idea email copy in the artifact follows the Navreo voice:** lilly-copywriter's "THE NAVREO VOICE" section is canonical (corpus: `offer-email-voice-match/voice-corpus.md`; runtime: `app/navreo_voice.py`). Never restate the rules here — point there.

15. **THE surface = the tool's live board — MULTI-IDEA runs only (Bjion ruling 2026-07-27, superseding the 2026-07-16/17/18 artifact rulings).** Multi-idea runs POST run.json to `/api/strategy/run` and hand the user https://navreo-signals.onrender.com/app/strategy.html (mechanics in Phase 5). The page is generated from `wizard-template.html` by `~/.claude/skills/wizard-launch-lab/wizard-lab/build_live.py` → `~/navreo-signals/app/strategy.html` (commit + push to ship changes); the template itself is still never edited in place. Single-campaign runs keep their own per-campaign artifacts (Single-campaign mode, unchanged). Historical text of the superseded artifact ruling follows for context only:
    (superseded) **THE artifact = the standing wizard board — MULTI-IDEA runs only (Bjion rulings 2026-07-16/17/18, scoped 2026-07-26).** Scope: this guardrail governs multi-idea ideation runs. Single-campaign runs use `wizard-single-template.html` + their own per-campaign artifact (see "Single-campaign mode") and never touch the standing URL. A TAM-map request launches NO wizard at all at map time — `/lilly-tam` maps, then offers to draft; only a yes starts the single-view walkthrough. For multi-idea runs, unchanged: lilly-strategy does not mint menu artifacts. Its output surface is the ONE standing interactive wizard:
    **https://claude.ai/code/artifact/5d6e5fdd-69d8-48f2-be8e-bec57da7b51f**
    Template lives at `~/.claude/skills/lilly-strategy/wizard-template.html` (the panel-passed split-view board: sticky idea list, pre-start previews with outreach mockups, parallel builds, two-page copy studio, opener waterfall, sign-off suite — white app colourway, Navreo voice).
    **Every run — no exceptions:** launching this artifact is Phase 5's mandatory closing step (mechanics there): COPY the template to scratchpad (never hydrate the master in place), hydrate the copy's inline `IDEAS` array + context header + evidence lines with the run's REAL output — per idea: name, net DMs (gross → net), free-vs-paid split, who-line, offer, "Why this idea" evidence, "What gets replies" line, the four voice-compliant email versions + follow-up + opener lines, validation cards for fast-verdict asks. Then publish the copy with `url:` = the standing URL (required from every new session; same-session republish by file path also works). NEVER mint a new URL for a strategy run; a run without the artifact republish is incomplete. Keep the "In flight" states for campaigns already building, and the footer's "last updated" line.
    The flow the CSM experiences: mention a client in chat → lilly-strategy runs (retro → ideas → 1-credit net probes) → **the artifact opens/updates with the ideas in the UI** → they pick, approve, and walk campaigns to launch-ready inside it, while chat stays the place to ask for more angles.

16. **Chat carries NO results — the whole experience is opening the artifact (Bjion ruling 2026-07-19).** The results of a strategy run — the menu table, the recommended top 3, the "brainstormed but cut" list, any per-idea numbers or idea-by-idea rundown — NEVER appear in the chat message, not even condensed as a "quick summary" or a "here's what I found." They live in exactly two places: the hydrated artifact (the experience) and `sessions/<client>-<date>.md` (the record). The closing chat message is a short door to the artifact: one or two lines plus the link, at most one load-bearing caveat (wrong-client catch, an already-launch-ready campaign, a spend note). Reproducing the shortlist in chat is a defect even when the artifact also published — the point is that the user opens the wizard to see the work, not scrolls the transcript. (Chat is still the place for the user to ask for more angles or give feedback; that's dialogue, not results.) Why: Bjion, 2026-07-19 — "never put the results in the actual chat, make the whole experience about opening the artefact."
    **Reconciliation (Bjion ruling 2026-07-30):** "no results in chat" governs TYPED text only — it never means withhold the visual. On every publish and every update you MUST auto-render the board/page to the user via `SendUserFile` (`display:"render"`), because they cannot see the prod board in the agent's browser pane and "otherwise I can't see it" (Bjion). Showing the rendered page is required; pasting the menu/table/numbers as text is still forbidden. See Phase 5 → "Launch the board" step 4.
    **Browser addendum (AMENDED 2026-08-03, supersedes 2026-08-02):** the board opens in the CLAUDE BROWSER only (`navigate` to the share-token keyed URL). No macOS `open` to the default browser, no SendUserFile snapshot. Mechanics in Phase 5 → "Launch the board" step 4.
    **Welcome-summary amendment (Bjion ruling 2026-08-02, supersedes the "no summary at all" reading above):** the chat message is no longer a bare door line — it is now the WELCOME MESSAGE (see the "## WELCOME MESSAGE" section), which DOES briefly summarise the ideas (name + who it's for + reach per idea) and then tells the user how to progress. What stays banned in chat is the FULL deliverable: per-idea email copy, the brainstormed-but-cut list, probe/credit detail, and any long idea-by-idea rundown — those still live only on the board and in the session file. Read every "no results in chat" / "never a summary" phrasing above and in the CHAT VOICE section through this amendment: a short ideas summary + how-to-progress is required; the full rundown is still forbidden.

---

## Quick reference — cost per session

| Phase | Cost (credits) | Time |
|---|---|---|
| 0 — Client briefing | 0 (or 0 if memory hits) | 2-5 min |
| 1 — History pull via /lilly-optimiser | 0 (Smartlead API only) | 1-3 min |
| 2 — Mechanism brainstorm (7 vectors) | 0 (LLM only) | 3-5 min |
| 3 — Lead-magnet brainstorm | 0 (LLM only) | 2-3 min |
| 4 — TAM probing (1 Company-TAM probe/idea; DM TAM is arithmetic) | ~1 credit/idea → ~10 credits for a 10-idea sweep (+1/idea only if user requests findable-DM probes) | 5-10 min |
| 5 — Score + shortlist + write session file | 0 | 1-2 min |
| 6 — Build hand-offs (per approval) | 0 (just formatting) | <1 min per idea |
| **Total per session** | **~10 credits** (×2 if findable-DM probes requested) | **~15-30 min** |

Bench: a fresh-client strategy session that produces 5-10 ideas with probe-confirmed Company TAM + computed DM TAM should run in under 30 min for ~10 credits. Company-TAM probes are fast (~0.5–1s) and cheap (1 credit each); DM TAM = Company × N is free arithmetic. Only the optional `DM TAM (findable)` `/search-person` probes add ~1 credit/idea, and only when the user asks for them.

---

## See also

- `lilly-optimiser/SKILL.md` — invoked in Phase 1 to pull campaign history
- `lead-magnet-brainstorm/SKILL.md` — invoked in Phase 3 to surface offer hooks
- `lilly-tam/SKILL.md` — hand-off target for Vector 1 (targeted lists) and Vector 6 (lookalikes); also the source of the Phase 4 Step 2 Ocean saturation probe pattern
- `lilly-theirstack-setup/SKILL.md` — hand-off target for Vector 2 (hiring signals); brief format matches `briefs/*.json` files in that skill
- `lilly-trigify-setup/SKILL.md` — hand-off target for Vector 3 (engagement signals)
- `lilly-linkedin-page-finder/SKILL.md` + `lilly-company-followers/SKILL.md` — hand-off chain for Vector 5 (LinkedIn followers)
- `lilly-icebreaker-news-search/SKILL.md` — hand-off target for Vector 7 (news/funding intent)
- `loom-research/SKILL.md` — source of competitor lists (Task 6) and event lists (Task 4) when those research packs exist for the client's named clients
- `sessions/<client-slug>-<YYYY-MM-DD>.md` — the per-session deliverable
- `clients/<client-slug>.json` — the persistent client profile (created in Phase 0, refreshed on each session)
