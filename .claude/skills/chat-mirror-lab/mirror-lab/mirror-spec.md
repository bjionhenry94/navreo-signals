# chat-mirror-lab — contract spec (Step 1) · 2026-07-27

## Focus signal

`POST /api/strategy/focus` body: `{ "ideaId": "growth-hiring"|null, "view": "...", "note": "..." }`
- `view` ∈ `board` · `targeting` · `emails` · `opener` · `checks` · `building` · `signoff`
- `note`: ≤8 words, plain English, present tense, what Claude is doing right now
  ("removing Account Executive", "writing your emails", "running the checks"). No jargon,
  no idea ids, no numbers unless the number IS the news.
- Storage: campaign_insights scope=strategy / insight_key=wizard_focus, supersede+insert,
  data_fingerprint set, expires_at far-future (same laws as wizard_run).
- `GET /api/strategy/run` gains `"focus": {ideaId, view, note, ts}` (ts = generated_at) so the
  page keeps ONE 5s poll.

## View → wizard phase map (no new screens)

| view | drives |
|---|---|
| board | activeId = null (the campaign list) |
| targeting | idea open, phase 2 (chip editor / base who-gate) |
| building | idea open, phase 3 if build A unfinished else 5 |
| emails | idea open, phase 4, copyPackPage 1 |
| opener | idea open, phase 4, copyPackPage 2 |
| checks | idea open, phase 6 (sign-off surface = where checks read out) |
| signoff | idea open, phase 6 |

**State normalisation on jump** (chat did the work backend-side; the page must not break when
focus lands past un-walked gates): jumping to ≥4 sets `stagesDone = max(stagesDone, aCount)`;
jumping to ≥6 sets `stagesDone = 5`, runs `ensureVersions`, defaults `chosenVersion` to the
first active version if unset. Jumps never un-do user-made state (edits, approvals survive).

**Run-patch reactivity:** applyRun invalidates a campaign's cached `s.versions` when the
idea's `pain`/`offer`/`moment` changed AND the user has not edited any version
(`versionTweaks` empty, no generated versions) — so content work from chat visibly rewrites
the emails page. Targeting-sig changes rebuild chips (existing rule).

## Motion spec

- View swap: workspace fades out 180ms ease-out → re-render → fade in 220ms ease-out.
- Touched element: chip being removed fades+shrinks 240ms before the re-render; the headline
  number tweens on the existing 500ms re-check beat; the worked campaign's rail card pulses
  (2 soft outline pulses, 1.2s total).
- Ribbon: one slim line, top of the workspace, slides down 200ms, shows `note`; stays while
  focus is fresh (<20s), then fades. M2 replaces the ribbon with the activity rail; M3 keeps
  the ribbon AND spotlights the touched element (soft background sweep 600ms + scrollIntoView
  block:center).
- `prefers-reduced-motion: reduce` → all transitions 0ms, no pulses, no sweeps; content still
  updates, ribbon still appears.
- Implementation law: CSS transitions + class toggles + direct sets only. NO rAF loops (driven
  panes throttle rAF; proven 2026-07-27).

## Never fight the hand

If the user interacted with the page (pointerdown/keydown/wheel) in the last **10s**, a focus
change does NOT navigate. Instead: the target campaign's rail card pulses and the ribbon shows
the note + a small **"Catch up"** button; tapping it applies the pending focus. A newer focus
replaces the pending one. Prototypes may tune threshold (M1 10s · M2 8s · M3 12s) and the
affordance's wording; the panel judges feel.

## Replay timeline (prototypes only — no server, no credits)

`replay-timeline.js` exports `REPLAY_RUN` (frozen 4-idea fixture from the launch lab's
lab-run.json — growth-hiring/jd-outbound/stack/newrole with targeting blocks) and
`REPLAY_EVENTS`: ~90s, 12 events, each `{at_ms, kind: "focus"|"run", focus?, patch?}`.
Sequence: board hello → targeting open → role removed (number re-checks) → role added →
emails open → version A body sharpened (visible rewrite) → opener open → checks (2 ticking
notes) → background verification (build view animates) → board, launch-ready note.
A "Replay the session" button starts it; a second tap restarts. Mid-replay interaction must
trigger the catch-up affordance (the driver keeps emitting; the follower holds).

## Copy rules

Ribbon/ticker lines: ≤8 words, present tense, a 16-year-old's English, no em-dashes. The
mirror never explains itself — if a line needs a second line, cut it.
