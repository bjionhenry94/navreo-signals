# WALKTHROUGH — launch-ux-migration Steps 5+6 (2026-07-26, zero-spend)

**Zero-spend checks used, all scenarios:** every walk ran on fixtures — the single-idea
run.json (fabricated freight data), a fetch-stubbed local static serve of the deploy repo's
`campaigns.html` (`python3 -m http.server`, fixture JSON in-page), and dry re-reads of the
edited skills. No provider key was loaded, no Prospeo/AI-ARK/TheirStack/ListMint/MV/Smartlead
call was made, nothing touched navreo-signals.onrender.com's write endpoints. The ONLY engine
commands run were `validate` and `hydrate` (both offline/free). **Provider credits spent: 0 of
the ≤10 cap.**

| # | Routed skill (expected → actual) | Surfaces (expected → actual) | Verdict |
|---|---|---|---|
| S1 | lilly-strategy Single-campaign mode → ✅ (description + When-to-Use claim the phrase; lilly-tam defers) | single-view artifact → ✅ rendered end-to-end, zero console errors, Launch-ready reached by click | **PASS** |
| S2 | lilly-tam map → draft offer → single view → ✅ (TAM-map closing rule §; strategy guardrail 15 scoped) | none at map time → ✅; pool_pulls save EXISTS (server.py:4040-4234); single view on yes → ✅ (same artifact) | **PASS** |
| S3 | lilly-upload-gate top-up route → ✅ (description claims the phrases) | gate verdict in chat → ✅ (skill text mandates it); Leads page → ✅ rendered (`#/c/3709470/leads`, fixture table) | **PASS** |
| S4 | strategy single view + lilly-bot underneath → ✅ | walkthrough artifact → ✅; Overview opens → **MISS→FIXED**: `/overview` suffix bounces to the list (route regex `#\/c\/(\d+)(?:\/(messaging|leads|sources))?$` — bare `#/c/<id>` IS Overview). Links corrected in lilly-bot, lilly-recontact, lilly-strategy. Re-walk: `#/c/3709470` renders Overview ✅ | **PASS after fix** |
| S5 | lilly-copywriter chat-only → ✅ (no UI-launch instruction anywhere in the skill) | none → ✅ | **PASS** |
| S6 | lilly-recontact Flow A → ✅ | draft opens in tool → ✅ (post-fix link; Overview render proven at `#/c/<id>`) | **PASS after fix (same fix as S4)** |
| S7 | lilly-optimiser variant-swap scope → ✅ (chat-only exception §, cockpit auto-launch excluded) | none → ✅ | **PASS** |
| E1 | lilly-strategy FULL multi flow → ✅ (fork rule: explicit multi-idea ask) | STANDING wizard (5d6e5fdd…) → ✅ untouched this loop (standing-artifact gate); multi template retains idea rail (`#idea-list` + selectIdea handlers intact in `wizard-template.html`) | **PASS** |
| E2 | lilly-upload-gate → ✅ | same as S3; closing template's conditional partial-pool clause covers the empty-pool wording | **PASS** |
| E3 | lilly-tam map → offer → decline → END → ✅ (closing rule step 4: "On no: done… no UI, no draft, no follow-up nag") | none at any point → ✅ | **PASS** |

## Captured closing messages (verbatim, per scenario — ROUND 2 wording after panel round 1)

**S1** — "Your freight-forwarders campaign is ready to walk through — open it here:
<single-view artifact link>. You'll approve the audience, the emails and the final sign-off
inside (about 5 minutes); nothing sends without you."

**S2 (map moment)** — "TAM for Executive Coaching companies: ~2,400 companies, and ~5,100
decision makers we can actually reach — I've checked the count with the data provider and
removed everyone we've already contacted or who opted out. Want me to draft this as a
campaign? I'll save this exact audience and its filters to the campaign's Sources tab in the
tool — so you can pull more from it any time — and walk you through the rest."

**S3** — "Uploaded 412 leads to Collections and receivables firms. A record of this upload has
been logged — see the campaign's Leads page:
https://navreo-signals.onrender.com/app/campaigns.html#/c/3709470/leads
That's 412 of the 1,180 people saved for this campaign — 768 are still available, and you can
add them any time from the Sources tab on that campaign's page."

**S4** — "[build table] — and I've opened the campaign in the tool: it's on its Overview page
(https://navreo-signals.onrender.com/app/campaigns.html#/c/3709470). Review it there, and
launch from Smartlead when you're ready — until then it's paused and nothing sends."

**S5** — "[the copy: subject + body + 2 follow-ups, Navreo voice] — want a B version with a
different opener, or tweaks to this one?"

**S6** — "Draft created: Recontact: Customs — July 2026 (id 3709471). 1,021 people from the
old campaign are clear to re-approach — I've excluded everyone who opted out, replied
positively, was emailed in the last 30 days, or is in another live campaign. As agreed, the
April version is now paused so the two never overlap. I've opened the draft in the tool so you
can see it ready to go (…campaigns.html#/c/3709471) — it sends nothing until you launch it.
Next: want me to write the copy for it?"

**S7** — "[replacement variants B2 and D2, paste-ready] — B2 swaps the audit-shaped opener for
a send-able breakdown ask; D2 drops the two-question close that was killing replies. Variants
A and C stay live and untouched. Want me to save these into Smartlead for you? Heads up —
saving the sequence resets the per-variant stats, so if you want to keep the old numbers, edit
in the Smartlead UI instead."

**E1 (door line)** — "5 ideas are ready for the strategy call — open the board and pick:
<standing wizard link>. Everything's inside; nothing here spends money or sends email."

**E2** — "…that uses everyone saved for this campaign — I can find more people with the same
targeting whenever you want to extend it."

**E3** — "No problem — I've saved this map, so just ask me to 'pull up the MSP TAM from
earlier' whenever you want it or want to draft it."

## Step 6 fix list

1. **Overview deep-link shape** (S4/S6): `campaigns.html#/c/<id>/overview` → `campaigns.html#/c/<id>`
   in `lilly-bot/SKILL.md` (Output After Build), `lilly-recontact/SKILL.md` (Flow A step 6),
   `lilly-strategy/SKILL.md` (Single-campaign mode step 7). Root cause: the app's route regex
   only accepts `messaging|leads|sources` suffixes; bare id = Overview. Failed scenarios
   re-walked: Overview renders at the bare hash (fixture render confirmed). No other misses.

## Rendered-evidence register

- Single-view walkthrough: published artifact
  (https://claude.ai/code/artifact/a22225c6-ed10-4def-b0fa-5c662d7393b8) + full click-through
  (Not started → Step 1 who → Building → Step 2 emails/opener → Step 3 sign-off →
  Launch-ready), zero console errors. Screenshots in session transcript.
- Campaigns list, Overview, Leads tab: fixture-stubbed local render of the deploy repo's
  `campaigns.html` (screenshots in session transcript). Sources tab renders (honest empty
  state); the pull-more pool card markup is grep-verified live code (campaigns.html:3154-3171,
  V1 progress-bar card, pulled/remaining) — shipped by sources-pull-more-ship.
- Standing multi-idea wizard: NOT republished/touched (standing-artifact gate); rail intact in
  `wizard-template.html` (grep: `#idea-list`, selectIdea handlers present).
- Live login-walled pages: deferred to panel-time live proof with Bjion's session cookie
  (memory: setter-live-verify-auth) — not needed for zero-spend scenario walks.
