# Variant fair-test law — v3 (Bjion, 2026-09-02)

The rules the best-opener verdict and the Variant Auto-Mover must follow.
Locked via the harness deck (every scenario below was approved live).
Mirrored in three lockstep sites: `build_notifications.pill_best_opener`,
`campaigns.html` versionTableHTML, `optimise.html` versionTableHTML.

## The judging bar
- Flat **800 sends per live version**, always. No small-list drop to 300
  (removed 2026-09-02). Small audiences simply wait.
- Nobody is crowned below the bar — one early positive at ~200 sends reads
  like a winner but can be luck. (One exception: the meeting override, below.)

## Winner ranking (lower is better)
1. **sent / meeting** among versions with ≥1 booked meeting — the top
   indicator of success.
2. Fallback **sent / positive** only when no eligible version has a meeting.
- Meeting ⟹ positive: effective positives = max(positives, meetings); a row
  never shows meetings > positives.

## Meeting-leader override (early crown)
- A **live** version with **≥2 meetings** that **leads on sent/meeting** is
  crowned early — partial 80/20 — **even under 800 sends**. Don't throttle a
  path showing that much promise.
- Exactly **1** meeting does NOT trigger it (threshold is 2). A ≥2-meeting
  version that is *not* the sent/meeting leader stays a normal laggard.
- It holds 80% until it clears 800, then normal full-verdict rules resume.

## Verdict modes
- **NONE** — no eligible version past the bar and no early-crown override →
  keep testing.
- **FULL (100%)** — a single clear winner, past the bar, with every live
  version past the bar. Winner 100%, past-bar losers dropped to 0.
- **PARTIAL (80/20)** — a winner is judged but some live version is still
  under 800. Winner 80%; the remaining 20% is split evenly across every other
  eligible version so each keeps gathering data.
- **TIE** — co-leaders tied on the winning metric split traffic **evenly**
  (2-way = 50/50). Clearly-losing versions that are **past** the bar are
  dropped to 0. A pure 2-way tie with no loser = 50/50 = no change. If an
  under-bar live laggard is present, co-leaders share 80 and the laggard
  keeps 20.

## Never starve
- The auto-mover **never** switches a variant off before 800 sends. Under-bar
  variants always keep a testing share so they can prove/disprove themselves.
- Only a **past-800 judged loser** may be dropped to 0.

## Human-off is sticky (overrides never-starve)
- A variant a **human** intentionally switched off or removed **stays off** —
  the auto-mover keeps its data but must never re-enable it or route traffic
  to it, even if it is the top performer (the client may simply not want that
  message).
- Distinct from a system/under-provisioned "off" (split 0 but never a human
  decision), which never-starve keeps alive.
- **Implementation dependency:** requires an off-provenance signal (human vs
  system). Source TBD — Smartlead may not expose this cleanly; if not, we need
  to record the human-off decision on our side at the moment it's taken.

## Approved harness scenarios (regression fixtures)
See `app/test_best_opener_flat800_tie.py` (v3 fixtures to be extended:
meeting-override, tie-split allocation, human-off exclusion, never-starve).

## Human-off provenance (the signal, resolved 2026-09-02)
The codebase already carries the convention (server `even_split`, now shared
via `_variant_sent_by_vid`): **0% share WITH send history = switched off on
purpose (human-off, sticky); 0% with zero sends = never configured (eligible).**
Once the Auto-Mover ledger exists, a 0% that matches the mover's own last
write is system-off (never-starve keeps it alive); until then, and whenever
the ledger has no record, an under-800 0%-with-sends version defaults to
human-off — the conservative reading (the dangerous error is resurrecting a
message a client rejected).

## Engine contract — `pill_best_opener(m) -> (label, has_scale, ev)`
- `ev.mode` ∈ `full | partial | tie`; `None` return = NONE / keep testing.
- `ev.leaders` — the co-leader labels (1 for full/partial, ≥2 for tie).
- `ev.laggards` — labels that keep the 20% lane (partial: EVERY other
  eligible version; tie: under-bar live non-leaders).
- `ev.dropped` — labels set to 0 (past-bar judged losers; empty in partial).
- `ev.override` — true when the winner is crowned early under 800 on ≥2 mtg.
- `ev.human_off` — labels excluded as human-off.  `ev.via` — ranking tier.
- `ev.lead_share` (tie only) — each co-leader's even share (80/n or 100/n).
- `label` is `None` for a tie; `has_scale` is true when traffic must move.

## Door actions (id-intact, `save_sequence_ids_intact`)
- FULL → `scale_winner` (100 to the winner, rest 0).
- PARTIAL → `back_winner` (winner 80; named laggards share 20; rest 0). A
  never-configured 0% laggard may now join the lane; a human-off one is refused.
- TIE → **`split_leaders`** (new; confirm `SPLITLEADERS`): `leaders` share
  100 evenly, or 80 when `laggards` keep 20; everyone else 0; human-off refused.

## Build status (2026-09-02)
- DONE + tested (22/22 approved fixtures, `app/test_best_opener_flat800_tie.py`):
  flat-800 floor; meetings-first ranking with the ≥2-meeting override;
  tie→even-split with past-bar losers dropped; never-starve; human-off
  exclusion — all in `pill_best_opener`.
- DONE: `split_leaders` door action; `back_winner` never-starve/human-off gate.
- Auto-Mover (not yet built — see the `variant-auto-mover` skill): must add
  `split_leaders` to its action allowlist (R12) and route `ev.mode == "tie"`
  to it. It still contains no judging logic of its own.
