# ROUTE-AUDIT — launch-ux-migration Step 1 (2026-07-26)

## Ground-truth re-verification

| Fact | Verdict | Evidence |
|---|---|---|
| Multi-idea wizard template + engine | CONFIRMED | `wizard-template.html` 242,696B; `engine.py` retro/probe/net/validate/hydrate/handoff; idea rail at L1585 (`#idea-list`), JS at L2216 |
| **Single-idea hydration** | **WORKS** | `validate` → `{"ok": true, "ideas": 1}` (mixture rule only bites at ≥5 ideas); `hydrate` → 231,075B output from a 1-idea run.json. The idea rail renders with one item — that rail is exactly what Step 2 removes. |
| Deploy repo clean, surfaces live | CONFIRMED | `~/navreo-signals` `main...origin/main` clean (untracked protos only). Leads tab: `campaigns.html:3053` (`#/c/<id>/leads`), hydrate at L3870. |
| **Pull-more saves pool/targeting** | **EXISTS** | `pool_pulls` standing record per pool (total/pulled/remaining) — `server.py:4040-4234`; one-button gated pull writes `list_upload_qa_runs` audit rows (`server.py:4151`); UI shows `pool.remaining`/`pool.pulled_ok` (`campaigns.html:3169,3387,3449`). |
| **Leads page shows upload records** | **PARTIAL GAP** | Upload audit rows EXIST in Supabase (`list_upload_qa_runs`, written by every gated upload) but the Leads tab renders platform leads only — no HTML references `list_upload_qa_runs`. Ruling #3's chat message stays truthful ("a record of the upload was logged — see the Leads page") but the record is not yet VISIBLE on that page. **GAP reported, not built** (repo gate). Fix ≈ small strip on the leads tab reading `list_upload_qa_runs` for the campaign — awaiting approval. |
| Upload gate report opens in browser (detour) | CONFIRMED | `lilly-upload-gate` description: "opens an HTML report in the browser". Ruling #3 needs the approve moment in-chat. |
| Recontact inline, draft-only | CONFIRMED | `lilly-recontact` Flow A proven 2026-07-23 (3274582 → 3709470); no tool-open at the end today. |

## Trigger-collision map (resolved in Step 3)

- "**build a list of freight forwarders**" (UC1's exact shape) currently triggers **lilly-tam**
  ("'build a list of [companies]', 'build a prospect list'") → lands in the probe pipeline with
  NO walkthrough. Collides with ruling #1.
- "**spin up a campaign for [client]**" triggers **lilly-idea-to-launch** — the rival
  walkthrough chain. Collides with rulings #1/#4.
- **lilly-strategy guardrail 15** ("EVERY run launches the wizard") is scoped to strategy runs
  but has no single-vs-multi fork, and would over-trigger the multi wizard for one-idea asks.

## The 7 routes

### UC1 — Build a prospect list for a niche
- **(a) Today:** → `lilly-tam` (trigger "build a prospect list"/"build a list of [companies]"): probe → sample → pull pipeline, chat tables, list lands at `lists.html#<id>`. No walkthrough, no campaign framing.
- **(b) Ruled:** single-view Lilly-strategy walkthrough (no tabbing) → campaign-launch walkthrough. Multi-idea view ONLY if the user asks for multiple ideas.
- **(c) Edits:** `lilly-strategy/SKILL.md` — new "Single-campaign mode" section: the fork rule (1 idea → `wizard-single-template.html` + its own artifact; explicit multi-idea ask → existing wizard), trigger phrases "build me a list of [niche]", niche-ask intake (skip full Phase 0), same engine pipeline (probe/net/validate/hydrate). `lilly-tam/SKILL.md` — description narrowed: campaign-intent list asks defer to lilly-strategy single-view; lilly-tam keeps raw TAM/enrichment/DM-finding and stays the build engine underneath.
- **(d) Interference:** `lilly-tam` trigger claim (narrow, per (c)); `lilly-idea-to-launch` (retire — see below).

### UC2 — Map a TAM for a segment
- **(a) Today:** → `lilly-tam` ("map TAM", "how big is the market"): probe-first pipeline, ends with hand-off options. No draft offer, no pull-more save.
- **(b) Ruled:** NO UI at map time. ALWAYS offer to draft the campaign; on yes → campaign added to the tool with pool/targeting saved via pull-more (`pool_pulls`) → single-view walkthrough. On no → done, no UI.
- **(c) Edits:** `lilly-tam/SKILL.md` — mandatory closing step on every TAM-map run: offer to draft; on yes, save the mapped pool + targeting filters as a `pool_pulls` record (source noted in Sources) and hand off to lilly-strategy single-view. `lilly-strategy/SKILL.md` — scope guardrail 15 to ideation runs only (a TAM map never launches the wizard).
- **(d) Interference:** lilly-strategy's always-wizard rule (scoped, per (c)).

### UC3 — Top up a campaign running dry
- **(a) Today:** → `lilly-tam`/`lilly-updates-leads` + forced `lilly-upload-gate`; the gate opens an HTML report in the BROWSER (a detour), closing message ad-hoc.
- **(b) Ruled:** the upload gate opens WITHIN the chat. After upload: link to the tool's Leads page + say a record of the upload was added there; if only part of the pool went up, explain that.
- **(c) Edits:** `lilly-upload-gate/SKILL.md` — the report/approve moment surfaces in the chat flow (verdict summary + FAIL/PASS table in chat; the HTML report becomes the secondary deep-view); fixed closing-message template: Leads-page link (`campaigns.html#/c/<id>/leads`) + "a record of this upload was logged" + partial-pool sentence (`X of Y uploaded; Z remain in the pool — pull more from Sources`).
- **(d) Interference:** none — `sources-pull-more-ship` is the UI-side twin and stays. GAP note: record VISIBILITY on the Leads page is the tool-side gap above.

### UC4 — Build a campaign shell (Smartlead / Instantly / Lemlist)
- **(a) Today:** → `lilly-bot` (Smartlead create) or `lilly-idea-to-launch` (rival chain). No consistent walkthrough; no tool-open at the end.
- **(b) Ruled:** single-view walkthrough (no other campaigns to show). On successful upload → open the campaign in the tool on its Overview page.
- **(c) Edits:** covered by lilly-strategy Single-campaign mode (walkthrough) + `lilly-bot/SKILL.md` closing step: after shell + upload succeed, open `campaigns.html#/c/<smartlead-id>/overview` from the chat.
- **(d) Interference:** `lilly-idea-to-launch` (retire — below).

### UC5 — Write cold email copy
- **(a) Today:** → `lilly-copywriter`, chat-only. **(b) Ruled:** same. **(c) Edits:** none (confirm no UI launches). **(d) Interference:** none.

### UC6 — Build a recontact campaign
- **(a) Today:** → `lilly-recontact` inline route; ends with the draft id in chat, no tool-open.
- **(b) Ruled:** no own UI, but on build → open the campaign inside the tool from the chat so the user sees it ready.
- **(c) Edits:** `lilly-recontact/SKILL.md` — Flow A gains a final step: open `campaigns.html#/c/<draft-id>/overview` in the chat's browser pane. UI hand-off route (ambiguous siblings) unchanged.
- **(d) Interference:** none.

### UC7 — Replace / swap failing email variants
- **(a) Today:** → `lilly-optimiser`, chat-only (paste-ready copy, never API-saved). **(b) Ruled:** same. **(c) Edits:** none (confirm). **(d) Interference:** none.

## Retirements (skill-retirement gate: trigger coverage moves, folders stay)

| Route | Action |
|---|---|
| `lilly-idea-to-launch` | SUPERSEDED banner in description + body ("superseded 2026-07-26 by the consolidated launch flow — use lilly-strategy Single-campaign mode"); trigger phrases removed from its description so they stop matching. Folder stays. |
| `lilly-strategy` always-wizard (guardrail 15) | Scoped: ideation runs only; never fires for TAM-map; single-idea runs use the single view. |
| `lilly-tam` campaign-intent triggers | Narrowed: "build a prospect list [for a campaign/niche]" defers to lilly-strategy single-view; lilly-tam remains the underlying build/probe engine and keeps raw TAM/DM/enrichment triggers. |

## GAP register (awaiting Bjion approval — NOT built by this loop)

1. **Leads-tab upload-record strip**: render `list_upload_qa_runs` rows for the campaign on the
   Leads tab (deploy repo `app/campaigns.html` + a small read endpoint). Until then, chat
   messaging says the record was logged and links the Leads page.
