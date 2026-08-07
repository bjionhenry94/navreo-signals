# Launch-day error audit — 2026-07-27

Sources: pre-baked catalog in SKILL.md · `lilly-strategy/sessions/navreo-2026-07-27.md` (153 lines,
4 targeting revisions logged) · `~/.claude/state/list_uploads.jsonl` · `campaign_registrations.jsonl`
(4 registrations) · independent corroboration: the parallel session's own count was **23 failures**,
and it encoded extra provider gotchas into `smooth-campaign-launch` (Prospeo `timeframe_month`,
Smartlead duplicate-endpoint variant truncation) — consistent with class A below.

Cost key: cr = provider credits · min = wall-clock minutes of rework · trust = user had to correct Claude.

| # | What happened | Cause | Cost | Prevented by (→ CHANGES) |
|---|---|---|---|---|
| A1 | Engine posted flat filters to AI Ark REST; silently ignored WHILE billing; two probes returned the whole 414M DB as a "count" | A | 2 cr, 15 min | C4 contract tests + engine hard-fail >10M |
| A2 | AI Ark `metricGrowth*` 400s on every combination; idea cut late | A | 10 min | C4 |
| A3 | TheirStack `company_industry_or` invalid param, silent null | A | 5 min | C4 |
| A4 | Prospeo drift: 2 endpoints DEPRECATED, bulk-enrich rejects LinkedIn URLs; docs stale in lilly-tam | A | 40 min | C4 + doc fix (done in this loop) |
| A5 | Smartlead key in keys file invalid; real key only inside mcp-remote process args; first regex truncated it | A | 20 min | C4 (key location documented in launcher) |
| A6 | Sequences API field asymmetry (`delay_in_days`) + shell quoting broke api_key; 2 failed saves | A | 10 min | C1 (launcher bakes exact shapes) |
| B1 | Both sessions republished the standing artifact: 3 conflicts, foreign ideas on the board, chat ≠ artifact | B | 45 min, trust | C2 single-writer |
| B2 | Whole-list write from other session clobbered this session's campaign_drafts row after it was verified | B | 15 min | C2 |
| B3 | Near-duplicate campaigns built twice off one signal (4 drafts); overlap only proven ~1% by manual check | B | 30 min | C2 + C7 probe-before-claim |
| B4 | Three campaigns created unregistered by the other session | B/D | 25 min | C6 guard (done) + C2 |
| C1 | Wizard let Bjion complete a full "launch"; nothing was created; his copy edits lost unrecoverably | C | 60+ min, trust | C5 prototype honesty |
| C2 | Cards showed no concrete targeting until a targeting block was built mid-day | C | 30 min | C5 (shipped same day: targeting block) |
| D1 | List-push rule lived in skills; ad-hoc pull escaped it; guard fired late + false-positived on a derivative CSV | D | 15 min | C6 (shipped; FP noted) |
| D2 | Campaign registration not part of the act; helper+guard built mid-session; v1 had 2 bugs (key regex, urllib SSL); manual+auto double-registered ONE campaign as two identically-named sources | D | 40 min, trust | C6 (shipped; dupes cleaned) |
| E1 | No mailboxes attached, no 2-min video ready — discovered after the campaign was built | E | handoff risk | C3 preflight gates |
| E2 | Targeting arrived in 4 revisions (roles ×2, geo 15, niches ids, DM ladder, person+company location) — each a re-probe + republish | E | 90+ min | C3 standing defaults |
| E3 | Size-filter leakage (national newspaper in a 5-200 list); shipped by explicit choice | E | quality risk | C1 step-5 named subtractions |
| F1 | "These campaigns overlap heavily" asserted without measuring; real overlap 1% | F | trust | C7 |
| F2a | Wrong ideas surface used at session start; user had to intervene angrily | F | 20 min, trust | C2 (one surface) + skill already names it |
| F2b | Mid-message link swap (3723446/3723450) | F | trust | C7 |
| F2c | Finished draft "invisible" in campaign view (default Active filter hides Drafts) | F | 15 min, trust | C5 (draft visibility) |
| F2d | Two identically-named sources ("50 found" vs "0 found") confused the Sources view | D/F | 15 min | C6 idempotency by campaign id |

**Totals: 22 distinct errors · ~2 wasted credits · roughly 6.5 hours of rework/back-and-forth · 7 trust hits.**
Root-cause weight: E (late gates / drip-fed targeting) and B (two writers) each account for ~1/3 of lost time;
A (provider drift) for most of the credits and the scariest silent failures.

Sweep result: no additional errors found beyond the pre-baked catalog; the parallel session's "23" count
aligns (their list includes provider gotchas from their own pull that this session never hit).
