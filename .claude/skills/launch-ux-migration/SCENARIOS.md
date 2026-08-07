# SCENARIOS — launch-ux-migration Step 4 (2026-07-26)

Dummy-chat pack for the 7 tier-1 use cases + 3 edge scenarios. Every scenario is walked
zero-spend in Step 5 (fixtures/dry-runs only). "Surface" = what actually opens for the user.

---

## S1 — Niche list build (the Asad ask)
**User:** "Build me a list of freight forwarders in the US and UK."
**Expected route:** `lilly-strategy` → Single-campaign mode (NOT lilly-tam direct, NOT the multi wizard).
**Expected surfaces:** ONE — the single-view walkthrough artifact (hydrated `wizard-single-template.html`, own URL). No idea rail, no tabs.
**Expected closing shape:** short door — one or two lines + the artifact link ("Your freight-forwarders campaign is ready to walk through — open it here. Nothing sends without you."). No tables, no numbers dump in chat.

## S2 — TAM map, user accepts the draft offer
**User:** "Size and map the TAM for Executive Coaching companies."
**Expected route:** `lilly-tam` (map phases) → closing draft offer → on "yes" → pool/targeting saved (`pool_pulls`, visible in Sources with pull-more) → `lilly-strategy` Single-campaign mode.
**Expected surfaces:** NONE at map time (numbers in chat). After the yes: the single-view walkthrough artifact.
**Expected closing shape (map moment):** dual-number TAM + DM count in chat, then exactly: "Want me to draft this as a campaign? I'll save the pool and targeting into the tool and walk you through it."

## S3 — Top-up, partial pool
**User:** "The Collections campaign is running dry — top it up with fresh leads."
**Expected route:** `lilly-upload-gate` (top-up trigger): pull from the campaign's saved pool (pull-more), gate runs IN the chat, upload on pass.
**Expected surfaces:** the gate verdict summary in chat (review page linked as deep view only); after upload, link to the campaign's Leads page.
**Expected closing shape:** "Uploaded 412 leads to Collections and receivables. A record of this upload has been logged — see the campaign's Leads page: <link>. That's 412 of the 1,180 in this pool — 768 remain, and you can pull more from Sources whenever you need a top-up."

## S4 — Campaign shell
**User:** "Build a campaign shell in Smartlead for the exporters offer."
**Expected route:** `lilly-strategy` Single-campaign mode walkthrough → `lilly-bot` builds the shell underneath → `lilly-upload-gate` for any list push.
**Expected surfaces:** single-view walkthrough artifact during approval; on successful upload, the campaign's Overview page opens in the tool (`campaigns.html#/c/<id>/overview`).
**Expected closing shape:** build table (name/ID/step status) + "opened the campaign in the tool — it's on its Overview page, paused, nothing sends until you launch."

## S5 — Cold email copy
**User:** "Write the cold email copy for the freight forwarders campaign."
**Expected route:** `lilly-copywriter`, chat only.
**Expected surfaces:** NONE. Copy lands in chat, paste-ready (subject + body + follow-ups, Navreo voice).
**Expected closing shape:** the copy itself + one line offering variants or a tweak round. No UI links.

## S6 — Recontact campaign
**User:** "Build a recontact campaign from the old Customs campaign."
**Expected route:** `lilly-recontact` Flow A (inline: net against suppressions + contact_history, paused DRAFT, replaces predecessor).
**Expected surfaces:** after create, the draft campaign OPENS in the tool (`campaigns.html#/c/<draft-id>/overview`) from the chat.
**Expected closing shape:** draft id + eligible count + predecessor-paused note + "opened it in the tool so you can see it ready to go — it sends nothing until copy, shell and launch happen deliberately."

## S7 — Variant swap
**User:** "Versions B and D in the HR campaign are dead — swap in replacements."
**Expected route:** `lilly-optimiser` variant-swap scope (chat-only exception; NOT a cockpit run).
**Expected surfaces:** NONE. No page auto-launch.
**Expected closing shape:** replacement variants as paste-ready copy in chat (voice-checked), one line on why the replacements differ from the dead ones.

---

## E1 — Multi-idea ask (proves the fork)
**User:** "Give me 5 campaign ideas for Navreo — a proper menu for the strategy call."
**Expected route:** `lilly-strategy` FULL multi-idea flow (retro → 7 vectors → probes → shortlist).
**Expected surfaces:** the STANDING multi-idea wizard artifact (5d6e5fdd…), republished — never a new URL, never the single view.
**Expected closing shape:** short door — one or two lines + the standing link. No menu/table/numbers in chat (guardrail 16).

## E2 — Full-pool top-up (no partial sentence)
**User:** "Top up the Exporters campaign — push everything left in its pool."
**Expected route:** same as S3 (`lilly-upload-gate` in-chat).
**Expected surfaces:** gate verdict in chat; Leads-page link after upload.
**Expected closing shape:** same as S3 but NO partial-pool sentence — instead: "that empties the pool — pull more from Sources when you want to extend it."

## E3 — TAM map, user declines the draft offer (proves no UI)
**User:** "How big is the market for MSPs in the DACH region?" → (after numbers + offer) → "No thanks, just needed the number."
**Expected route:** `lilly-tam` map → offer → decline → END.
**Expected surfaces:** NONE, at any point. No wizard, no artifact, no tool page, no follow-up nag.
**Expected closing shape:** "Noted — the numbers are logged in the run record if you want to pick this up later." (or equivalent one-liner; run cached + ledgered as ever).

---

**Coverage check:** UC1→S1 · UC2→S2+E3 · UC3→S3+E2 · UC4→S4 · UC5→S5 · UC6→S6 · UC7→S7 · fork→E1. All 7 use cases + 3 named edges covered; no scenario blank.
