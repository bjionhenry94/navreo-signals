# Campaign header — binding inventory (nothing-removed checklist)

Source of truth: `app/campaigns.html` `renderList()` L2583–2630 (header template),
`drawPerf()` L3145–3184 (stat boxes), PRESETS L2532–2540. Live visual: Bjion's
screenshot 2026-07-27 (browser pane blocks the onrender domain by policy; repo is the
deploy source, so markup here IS live markup).

## Region A — "Performance, whole fleet" (`.perfx-card`)
| # | Control / stat | Live detail (clone these numbers) |
|---|---|---|
| A1 | Title `.perfx-title` | "Performance, whole fleet" |
| A2 | Live status `.live-meta--perf` | green `.live-dot.is-ok` + "Live · Data from moments ago" |
| A3 | Refresh `.live-refresh` | orange underlined text button, re-checks Smartlead |
| A4 | Window toggle `.perfx-toggle` | 7d · 14d · 30d, **30d active** (ink pill). ≤3 presets, 30-day cap — standing ruling |
| A5 | Stat: Emails sent | hero **286,588**, spark #1971C2, delta "▲ 6,475 vs last week" (flat/dark — no good direction) |
| A6 | Stat: Reply rate | hero **1.42%**, spark #2F9E44, delta "▼ 0.2pt vs last week" red (good=up) |
| A7 | Stat: Emails per positive | hero **1 : 1,433**, spark #7048E8, delta "▲ 104 vs last week" red (good=down) |
| A8 | Stat: Meetings booked | hero **49**, spark #E8590C (--series-orange, data color not accent), delta "▲ 1 vs last week" green (good=up) |
| A9 | Per-box anatomy | uppercase `.perfx-lab` · `.perfx-num tnum` hero · `.perfx-spark` 48px SVG (series line + dashed avg `.perfx-thr` + endpoint dot) · `.perfx-delta up/down/flat` |
| A10 | Spark hover tooltip `.perfx-tip` | day + value per point ("no data" for null) |

## Region B — Filter bar (`.filter-bar`)
| # | Control | Live detail |
|---|---|---|
| B1 | Search `.search-input` | placeholder "Search a campaign or client…", icon left, live row filter |
| B2 | Client picker `#client-select` | label "CLIENT", options: All clients + distinct client names (derived from campaign names), 172px pill |
| B3 | Status picker `#status-select` | label "STATUS", options: All statuses / **Active (default, shows live count 109)** / Paused / Completed / Draft / Archived — checked live against Smartlead |

## Region C — View bar (`.view-bar .view-chips`) — each chip filters AND sorts in one tap
| # | Chip | Note (title attr) |
|---|---|---|
| C1 | **All Priorities** (default active) | priority triage: needs a decision → watch → fine |
| C2 | Most meetings | best meeting-getters on top |
| C3 | Most positives | most positive replies on top |
| C4 | Most efficient | fewest emails needed per meeting booked |
| C5 | Most left to send | most people still to be contacted |
| C6 | Biggest lists | every campaign by total lead count |

## Behaviours that must survive
Window toggle re-slices heroes + sparks + deltas · live dot has ok/error/loading states ·
search + client + status + chip all combine · active chip = ink pill `.is-active` ·
sr-only live region announces filtered count.

## Tokens / classes to reuse (cockpit `:root`, NOT navreo.css — different token set)
`--nav-orange #FF4D00` (ONE accent per screen; charts use `--series-orange #E8590C`) ·
`--fg/--fg-muted/--fg-subtle` ink scale · `--border/--border-strong` · `--bg-elevated` ·
`--sunken #F7F7F6` · `--chip-active-bg/fg` (ink pill) · `--r-pill/--r-lg` · success
`#2E7D5B` / danger `#C2371F` · `--font-display` Acid Grotesk (self-host `../fonts/AcidGrotesk-Normal.otf`) ·
`--font-sans` DM Sans → Helvetica fallback (live page loads no webfont for body) ·
classes: `.perfx-box/-lab/-num/-spark/-delta` `.filter-bar` `.search-wrap/-input/-icon`
`.status-picker/.status-select` `.filter-chip.view-chip.is-active` `.live-meta/.live-dot/.live-refresh` `.tnum`.
Page frame: `.cockpit` max-width 1180px, 64px `.rail` sidebar to the left.
