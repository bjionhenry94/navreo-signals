# Wizard Lab — final state (2026-07-17)

## Winner: R3 "Split view", owner-picked and iterated
https://claude.ai/code/artifact/5d6e5fdd-69d8-48f2-be8e-bec57da7b51f
Sticky left campaign list (live states: quiet / building+stage label / orange Needs-you / ink Launch-ready) · idea PREVIEW before starting (net number, who, offer, outreach mockup with rendered personal-opening) · parallel builds with Needs-you signals · TWO-PAGE copy pack inside ONE approval: page 1 "Your emails" (Version tabs A-E, Write another version, per-version + follow-up Tweak-the-wording, Don't-use-this-one with undo, min-one guard) → page 2 "The opener" (re-orderable on/off waterfall, safe-opener backup rule + skip warning) → single orange "Approve the copy pack" · sign-off + reopenable launch-ready summary with re-inspectable version pills.

## Round history
- Round 1 (5 interaction models): stepper 8.0 / chat 7.0 / flip-board 7.4 / flight plan 6.2 / deck 6.8 → all fixed (edits-visibly-apply was the universal killer) → flip-board model won with Bjion.
- Round 2 (5 board variations, parallel engine + copy pack): kanban 8.7 (parallel-obvious 10/10) / split view 8.4 (zero bugs) / parallel board 7.9 / dock 7.3 / tabs 7.1. Bjion picked split view + R2's card depth + outreach mockups.
- Final iteration: copy studio (generate/delete/edit both emails), opener as its own page, sticky rail. All agent-verified end-to-end, desktop + 375px, zero console errors.

## All prototype URLs
R1 parallel board ad2c0ddd… / R2 dock 49f27615… / R3 winner 5d6e5fdd… / R4 kanban 55bda551… / R5 tabs bc067d47… ; round-1 set b492d25a…(P1) bdb0ebf6…(P2) 473336da…(P3) 264355d6…(P4) 67f56102…(P5) — all under claude.ai/code/artifact/.

## Gotchas for the real build
- `overflow-x:hidden` on html/body silently kills `position:sticky` — use paired 100vh scroll panes on desktop.
- Missing `<meta name="viewport">` = mobile media queries never fire (980px default viewport).
- Edits MUST visibly apply wherever the content is later shown, or user confidence collapses (both panels' #1 finding).
- Save ≠ approve, always. "Needs you" never interrupts.
- Jargon ban: "opener", "version", "people we can reach", "double-checked".
- Skill loop note: gallery step skipped per Bjion's redirect (winner iterated directly instead); simulated-panel bar (9/10) superseded by owner-driven iteration after round 2.

## Sign-off suite (2026-07-18, owner refinements round 4)
- Opener lines editable per strategy (tweaks flow to every downstream preview; {company}/{colleague} tokens fill).
- Full backwards navigation from sign-off (state survives; completed builds never re-run).
- "See the full emails": assembled preview, surviving-versions × enabled-openers tab grid, opener spliced italic at the token.
- "Example people": 5 illustrative prospects with their exact version × opener assignment (one visibly falls through to safe opener); tap opens that combo.
- Auto-upload story: "full list uploads automatically" + View-the-full-list link to navreo-signals lists page, on sign-off AND launch-ready.
- Bug fixed in passing: window.__lab froze for background campaigns (sync only on renderAll) — now tracks background builds live.

## Use-case audit loop (2026-07-18, /strategy-wizard-usecase-audit, training off) — PASSED
- Step 1: usecases.md — 7 daily ideation asks with evidence contracts (UC1 ideate-for-client … UC7 recontact-free-first).
- Step 2: Bjion's 4 fixes live — per-person ACTUAL openers (edits inherit), Smartlead upload status on 3 surfaces (not-uploaded → uploading → In Smartlead #3002x), Share button w/ confirmation, "Ask in chat" prompts panel.
- Step 3: audit.md — verdict "the process has the evidence; the artifact didn't show it"; 5 artifact gaps + 5 real-build hand-offs.
- Step 4: evidence surfaces shipped — context header (148 campaigns · 18,721 replies), Why-lines per card, "What gets replies" per preview, free-vs-paid provenance, validation verdict card (named old campaign + date), copy-provenance badge. + contrast bug on launched cards fixed, "probe" jargon swapped.
- Step 5: panel round 1 CSM 7.9 / Cust 7.9 / Recip 6.3 (3 of 5 recipients MIS-CAST — my panel-spec error) → 7 fixes (share feedback, pre-approval contradiction, "Sent versions" label, peer-proof INTO ecomm emails, evidence upgrades, offer sharpening incl. lead-definition + HR pilot framing + customs reframe, disclaimer board-only) → round 2 with correct casting: **CSM 9.1 · Customer 9.3 · Recipient 9.0. PASS.**

## Real-build hand-off list (for the integrated version)
R1 chat→artifact live wiring ("ideate for [client]" regenerates the board) — Josh's wall: board is Navreo-only; client picker/context switch is THE gap between prototype and daily tool.
R2 live data feeds (scorecard/replies/cooldown populate cards at open; free-vs-paid splits everywhere history exists, with "no history yet" label where it doesn't — Kelly).
R3 real Smartlead push + real campaign ids; real list share links.
R4 per-person opener truth from the real icebreaker pipeline (mocked now).
R5 copy niceties from panels: named peer proof needs the real client name (Marcus), pilot size gets a number (Fiona/Renee — and the pilot promise must appear IN the email, not just the card), verdict cards should show their example email (Owen), speed-to-results line in emails (Elena), delete-version confirm affordance (Tunde), arrow disabled-states (Marta), offer-line prominence vs badges (Amara), vary the commercial skeleton across a 5-card menu (Priya).

## Minimalist lab + final blend (2026-07-18/19)
Five treatments built from the winner (progressive disclosure / numbers first / one thing per screen / visual language / calm board), founder-panel rounds: R1 8.6/6.9/7.5/8.6/5.4-style spread exposed THE lesson (never hide the decision cue); R2 after fixes: M5 9.06, M4 8.94, M2 8.92, M3 8.68, M1 8.6; final fix round (shared clipped-edit-box bug + per-proto residuals) then BJION'S BLEND merged into r3: M1 board + M2 captions/preview, M3 build+editor (Protecting stage dropped, 5 stages), M4 sign-off, ask-in-chat bottom, no context widget, narrow-screen overlay, dark/light mode. Board census 479 → 101 words. All verified two-campaigns-parallel in both themes, zero console errors. Backup r3-preblend.html.
