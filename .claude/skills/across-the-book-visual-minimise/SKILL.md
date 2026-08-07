---
name: across-the-book-visual-minimise
description: Static orchestration skill that reverts the campaign cockpit's "Across the Book" insight cards from a text-heavy layout back to the minimal, highly-visual, skimmable form of the signals home page (navreo-signals.onrender.com/app/) — every card is two lines max (1. the insight, 2. the action), the number is shown as a visual mark not a paragraph, and a 5-person non-technical founder panel must score it 8/10 on "quick, simple, easy to skim" before it ships. Use when the user says "make the Across the Book cards visual again", "the insights went text-heavy, revert them", "minimise the book insight cards", or "/across-the-book-visual-minimise".
---

# Across the Book — visual minimise

## Loop Training Mode: ON  ← flip to OFF to run autonomously

- **ON (default):** pause at every step and wait for Bjion's approval before continuing. Skip any step that already passes its done-rule. Only re-run steps that fail. Retry cap applies.
- **OFF:** run all steps autonomously, no pauses, but keep every done-rule check and the retry cap.
- **Retry cap:** max 3 attempts per step (Step 3 panel: max 4 revise-and-rescore rounds). On cap, stop and report the best result plus what is still failing.

## Goal

The "Across the Book" cards have reverted into something text-heavy. Revert them to the minimal, visual form of the signals home page (`/app/`): each card reads in **two sentences max** —

1. **The insight** (one line)
2. **The action** (one line, the `→ act` line)

The number that drives each card is shown as a **visual mark** (bar, chip, meter, delta arrow, count), not buried in a prose paragraph. Everything else — receipts, source, the sums-check, the "Bjion ruling" footnotes — moves behind an expander. A non-technical person skims the row and knows what is happening and what to do in seconds.

## Hard rules

- **Two lines of visible text per card, hard budget:** the insight headline and the `→` action line. No supporting paragraph, no "Source:" line, no ruling footnote in the visible card — all of it lives behind a "why?" / details expander.
- **The data is the visual.** Every card leads with the number as a mark (delta arrow for week-over-week, a bar/meter for a share or a threshold, a count chip for "46 waiting / 14 meetings"). The reader should not have to read the sentence to get the magnitude.
- **Match the home page (`/app/`), not a redesign.** Same rhythm, spacing, and restraint as the existing home insight feed. This is a *revert to that pattern*, applied to the book cards — do not invent a new grammar.
- **Navreo Design System only:** cream/ink, ONE orange accent moment per card max, Acid Grotesk data-URI, no emoji, chart-series palette for marks, dark mode + light mode both correct. (`~/.claude/skills/navreo-design-system/`.)
- **Owner chip stays** (Bjion / Lilly / Yasir) — it is one visual token, keep it.
- **Real data only** — the current live card contents (46 waiting / 14 meetings, 88→58 WoW, kill-line pair, stuck split, the five zero-positive offers, book verdict). No invented numbers.
- **Additive to content, subtractive to text:** no card or number is dropped; only prose is removed from the visible surface. Confirm before removing any card entirely.
- Responsive: no horizontal scroll at 375px or desktop, both themes.

## Steps

**Step 0 — Locate the surface.**
Find where "Across the Book" is rendered (the card headline strings: `WAITING ON A HUMAN`, `WEEKLY PULSE`, `KILL LINE`, `STUCK SPLITS`, `DEAD OFFERS`, `BOOK VERDICT`). Grep `app/` first; if not in a repo page it is the cockpit Artifact — resolve which artifact/URL. Snapshot the current card contents (the ground-truth numbers) so redesign uses real data.
*Done-rule:* the exact file/artifact and the current 6 cards' data are captured in the session record.

**Step 1 — Build the minimal-visual lab.**
One comparison Artifact showing the 6 real cards rendered in **3 genuinely different visual treatments**, each obeying the two-line budget with the number as a mark: (a) delta/mark-led chips (arrow or bar + 2 lines), (b) meter/threshold row (kill-line and share cards get a filled meter against the threshold), (c) ultra-minimal one-number + `→ act` with a "why?" expander. Theme toggle; 375px + desktop.
*Done-rule:* lab live; 6 cards × 3 treatments render in both themes at both widths, no horizontal scroll; every card's visible text is exactly two lines.

**Step 2 — Skim test (panel).**
5 fresh non-technical founder / sales-leader personas. Each gets a ~10-second skim of each treatment, then: what is this card telling me, what would I do, and a 1-10 score on "quick, simple, easy to skim — I got it in two sentences." Average per treatment.
*Done-rule:* ≥1 treatment averages **≥8.0** across a full 5-persona round, score table recorded. Revise and re-run with fresh personas until true; cap 4 rounds.

**Step 3 — Ship the winner into the real surface.**
Apply the winning treatment to the live "Across the Book" section (the file/artifact from Step 0), receipts/source/ruling moved behind expanders, owner chips kept. Browser-verify both themes at 375px + desktop; if it is the live app page, verify via the app's own authed API/DOM read (memory: this cockpit page can render blank in the Browser pane — verify via JS DOM reads, not a raw screenshot). Republish to the SAME URL.
*Done-rule:* live section shows the winning two-line visual cards on all 6, verification passes, font blob untouched, nothing lost.

**Step 4 — Handover.**
One line + link, auto-launch per the handover convention. Report: lab link, score table, winner and why, what changed.
*Done-rule:* handover delivered with link + scores + winner.

## CERTIFIED GRAMMAR (23 Jul 2026 — panel 8.4, Bjion: "perfection") — the standing card law

Applies to **Across the Book AND every individual campaign page's insight cards**. Every insight card is exactly:

1. **Hero number** (Acid Grotesk, ~46px, semantic colour: red = broken, amber = watch, green = healthy)
2. **Its own chart** — ALWAYS. The data is visualised on every card, no exceptions. Pick by shape:
   - part-of-whole → segmented bar (14 of 46)
   - over-time → mini vertical bars, current period red
   - vs-threshold → gauge with a threshold tick (kill line)
   - config states → labelled cells, the broken one outlined red (v1…v8 splits)
   - many-items-one-metric → thin horizontal bars sized by volume
   - status rollup → coloured dot row with legend in the caption
   - A-vs-B → two compare bars
3. **One caption line** (11.5px muted) naming what the chart shows
4. **One `→` action line** (orange arrow)
5. **why? expander** holding ALL receipts, sources, rulings, breakdowns
6. **Owner chip** (Bjion / Lilly / Yasir) top-right

Nothing else visible. Reference implementation: artifact `27265e95-e33c-4d22-8306-9a44d60ac8ba` (book section + campaign-page section, light/dark, 3→2→1 responsive). When `/lilly-optimiser` regenerates the cockpit it renders BOTH scopes in this grammar.

## Done

Steps 0-4 pass their done-rules: the live "Across the Book" cards are two-line, visual, home-page-minimal, and a full 5-persona panel scored the shipped treatment ≥8.0. If the Step 2 cap is hit without an 8.0, ship the best-scoring treatment only with Bjion's explicit approval; otherwise deliver the lab, the scores, and the blockers.
