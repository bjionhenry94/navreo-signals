# The shortlist — 7 changes, ranked by friction removed per effort

| # | Change | Kills | Owner surface | Status |
|---|---|---|---|---|
| C1 | **Adopt `smooth-campaign-launch` as THE launch path.** One sentence in → card → price → drafted campaigns out, exact provider call shapes baked in, found→sendable as named subtractions. No more ad-hoc heredoc launches. | A6, E3, and the whole "guess the call shape" family | skill (exists, built 27 Jul) | **done-today — adopt** |
| C2 | **Single-writer rule.** One chat session per workspace at a time; the standing artifact, `campaign_drafts` and `sources` have exactly one writer. Second sessions read only, or the tool's server API becomes the only writer (row-scoped `write_source()` exists; whole-list writes banned). | B1 B2 B3 B4 (≈2h + the day's worst confusion) | working agreement now; server enforcement later | **propose** |
| C3 | **Front-load the two gate packs.** (a) Standing targeting defaults saved once in `clients/navreo.json` — 15 geos, 5-200 staff, verified niche ids, 34-role signal titles, CEO/sales ladder, company AND person in-region — confirmed in one card, never re-litigated. (b) Mailbox + asset preflight (senders attached? video ready?) BEFORE any credit is spent. | E1 E2 (≈1.5h) | clients/navreo.json + launcher step 1/3 | **build-now (small)** |
| C4 | **Provider contract smoke tests.** Weekly (or pre-launch) zero/1-credit probes of every call shape the launcher uses; a differential check for any new filter (extreme threshold must move the count); engine hard-fails any people-count > 10M; keys location documented. | A1–A5 (all wasted credits, the silent failures) | engine + small cron | **build-now** |
| C5 | **Prototype honesty + draft visibility.** Any surface that is not wired says "PROTOTYPE — nothing is created" on its final button; edits made in it persist somewhere readable or the button is disabled. Campaigns page surfaces a just-created draft (or defaults its deep-link filter to All). | C1 C2 F2c (the single worst trust hit) | wizard template + campaigns.html | **propose (tool change)** |
| C6 | **Keep the two act-level guards, harden idempotency.** list-autopush + campaign-register guards stay (both caught real misses on day one). Fix: registration keyed by campaign id so manual+auto can never mint two sources; derivative-CSV false positive noted in guard docs. | D1 D2 B4 F2d | hooks + campaign_register.py | **done-today — harden (small)** |
| C7 | **Probe before claim.** Any overlap, size, or "these will collide" assertion in chat must carry a measured number or be labelled a guess. House rule, costs nothing. | F1 F2b B3's scare | working agreement / memory | **done-today — adopt** |

Coverage check: every ERRORS.md row maps to ≥1 change. Accepted-as-is: E3's shipped leakage
(user's explicit call; C1's named-subtraction table makes the next one visible before shipping).

Direct doc fix made by this loop (allowed by hard gates): `lilly-tam/SKILL.md` Prospeo enrichment
shape corrected to `/enrich-person` + `data.linkedin_url` (was: dead bulk/identifier shape).
