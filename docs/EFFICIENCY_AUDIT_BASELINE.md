# Navreo Signals — Efficiency Audit Baseline (2026-08-22)

Branch: `audit/efficiency-2026-08-22` off `94830ed`. Local dev server: `NAVREO_NO_BG=1 DELIV_MOCK=1 python3 app/server.py 7901`.
Authed via locally-minted `navreo_session` cookie (admin@navreo.ai). Times include live Supabase round-trips.

## Architecture facts
- Backend: single `app/server.py` (23,373 lines), raw `SimpleHTTPRequestHandler` + `ThreadingHTTPServer`. One giant `do_GET`/`do_POST` dispatcher. ~70 distinct `/api/*` endpoints.
- Frontend: monolithic standalone HTML pages, all CSS+JS+markup inline in one file each.
- gzip IS served on-demand (Accept-Encoding: gzip) — compression is NOT the bottleneck.
- Data layer: Supabase + on-disk JSON blobs + Render crons. Web instance 512MB (OOM-prone).

## Front-end page weight (raw / gzipped)
| Page | Raw | Gzip |
|------|-----|------|
| campaigns | 483 KB | 150 KB |
| setter | 428 KB | 131 KB |
| deliverability | 199 KB | 59 KB |
| strategy | 156 KB | 69 KB |
| optimise | 119 KB | 33 KB |
| lists | 114 KB | 29 KB |
| report | 51 KB | 15 KB |

## Backend endpoint baseline (THE headline problem)
| Endpoint | HTTP | Bytes | Time |
|----------|------|-------|------|
| **/api/sources** | 200 | **19.6 MB** | **22.8 s** |
| **/api/campaigns-unified** | 200 | 345 KB | **17.9 s** |
| /api/notifications | 200 | 1.28 MB | 4.0 s |
| /api/collisions | 200 | 203 B | 3.7 s (all latency) |
| /api/workspaces | 200 | 922 B | 1.6 s |
| /api/analytics-hub | 200 | 18 KB | 1.5 s |
| /api/clients | 200 | 1.7 KB | 0.67 s |

(cockpit/campaigns/deliverability returned 404 — need page-specific query params; to re-measure with real params.)

## Headline findings
1. **/api/sources ships 19.6 MB in 22.8s** — massive data-surface violation. campaigns.html calls it on load.
2. **/api/campaigns-unified takes 17.9s** for 345 KB — backend compute/query fan-out.
3. **/api/notifications ships 1.28 MB** every page (campaigns calls it 4×).
4. Several tiny-payload endpoints (collisions 203B/3.7s, workspaces 922B/1.6s) are pure latency — repeated Supabase round-trips with no caching.

## Next
- Profile /api/sources and /api/campaigns-unified to attribute the seconds (query vs blob I/O vs serialization).
- Map duplicate data production across endpoints.
- Optimize highest-cost paths, re-measure ≥20% target per Sol's done-rules.
