---
name: setter-regen-feedback-fix
description: Static orchestration skill that fixes the Appointment Setter's "Regenerate
  with feedback" silently ignoring typed reviewer feedback — hardens the 4,000-char
  truncation so fresh feedback always reaches the drafter intact, and adds a visible
  can't-comply warning when feedback asks for content the drafter has no source for
  (e.g. resource links on an agentless row). Warn only, never inject — the never-invent
  rule stays absolute. One fixed step list, each step with a checkable done-rule, retry
  caps, and a Loop Training Mode toggle. Use when the user says "run the setter feedback
  fix", "regenerate with feedback ignores my feedback", "it didn't include the links I
  asked for", or "/setter-regen-feedback-fix".
---

# Setter: Regenerate-with-feedback honoured or explained

The owner typed specific feedback twice ("include links to the resources") on an agentless
Needs-review row (Lash Class) and the regenerated draft ignored it with zero explanation.
Two proven defects: (1) agentless rows have empty instructions, and the drafter is banned
from links not in the instructions, so it obeys-by-ignoring silently; (2) on agent-assigned
rows, fresh feedback is appended LAST after the LATEST OWNER RULES block + memory digest,
then the whole string is cut at 4,000 chars — a big digest starves or deletes the feedback.
Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses.

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON:** pause at EVERY step boundary and wait for the user's explicit approval before
continuing. Before starting a step, check its done-rule first — if it already passes,
report "Step N already passes, skipping" and move on. Only re-run steps whose done-rule
fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

**Destructive-action gate (both modes, non-negotiable):** the only live actions ever
taken are **redrafts — max 5 across the whole run**, on real Needs-review rows (the Lash
Class row is the primary case). A redraft regenerates a draft only. **Approve/send is
NEVER clicked and nothing is ever sent to a lead** — verified by check (6) below. In
Training Mode ON, additionally show which row is about to be redrafted and get approval
before each live redraft fires.

## Goal

> Typed feedback on "Regenerate with feedback" is always either **visibly honoured** in
> the regenerated draft or **visibly explained** why it can't be, on the live host.
> Concretely: (1) fresh feedback text always reaches the drafter's `reviewer_feedback`
> payload intact regardless of digest size, and (2) when feedback asks for content the
> drafter has no source for, the redraft response carries a can't-comply reason and the
> UI renders it next to the draft. **Warn only, never inject (user, 2026-07-16):** the
> never-invent rule stays absolute — links/facts typed in feedback are never pasted into
> the draft.

## Ground truth (verified 2026-07-16 — re-verify in Step 1, line numbers drift)

- **Live source is the deploy repo `~/navreo-signals`** (verified at commit `86eb8e8`);
  push = deploy. The iCloud copy under `Bjion [2023]/Navreo/Claude/Navreo` **diverges and
  reverts edits — never edit it as the fix**; reconcile it after deploy (memory:
  `signals-deploy-repo`, `setter-live-verify-auth`).
- Truncation: repo `app/setter.py:1021` — `payload["reviewer_feedback"] = regen_feedback.strip()[:4000]`
  inside `draft_reply()`. Combined string built at repo `app/setter.py:3911-3912` in
  `route_queue_redraft()` (~line 3827): `combined_feedback = "\n".join([mem_digest,
  feedback_text])` then `_prefix_latest_rules(...)` — **feedback sits at the truncatable
  tail**. Comment at 1007-1010 says rules ≈1,600 chars + digest ≈2,000, leaving ≈400 for
  fresh feedback even in the design case.
- Never-invent rules in `DRAFT_SYSTEM`: repo `app/setter.py` ~951 ("Never invent a link,
  never paste a link the instructions don't contain") and ~967 (reviewer_feedback "never
  overrides the never-invent rules"). Resource links live ONLY in `_agent_instructions(agent)`;
  agentless rows load `agent = {}` → empty instructions → nothing to link, silently.
- Agentless rows have an empty `mem_digest`, so truncation is NOT the cause there — the
  empty-instructions + never-invent combination is. Truncation bites agent-assigned rows.
- Frontend: `app/setter.html` — feedback input + "Regenerate with feedback" button
  ~1389-1391, click handler ~1444-1446, `doRedraft()` ~1537-1545 (sends `payload.feedback`,
  and `scope:"remember"` when Training Mode is on).
- `proofread_draft()` runs on the regenerated HTML before save (~3692 iCloud numbering).
- Drafter output is strict-JSON via `DRAFT_SCHEMA` (`{"subject","html"}`) — extending it
  is the planned can't-comply channel (see Step 3 default).
- Auth for live verification: mint a `navreo_session` cookie — SRK is in
  `~/.navreo-keys.env` (memory: `signals-session-cookie-mint`). Poll-log = deploy proof.
- Gotchas: `setter_queue` schema-freeze — PATCHing a key that isn't a column dies silently
  (**no new columns; the warning travels in the HTTP response only**); new/edited POST
  routes must read `self._post_body`, never `rfile.read`; parallel deploy-repo sessions
  commit each other's WIP — commit ONLY this work's files; the stale decision pill after
  redraft is owned by `setter-redraft-pill-refresh` — don't rebuild it.
- **Out of scope (user, 2026-07-16):** the `scope="remember"` persistence no-op on
  agentless rows — separate task later.
- Primary test row: Lash Class (lead `info@lashclass.ca`, campaign "Interested Reply",
  agentless, in Needs review). Unknown until Step 1: its queue row id; whether it is
  still in Needs review; exact current repo line numbers.

## Steps

### Step 1 — Re-verify ground truth in the deploy repo
`git -C ~/navreo-signals log --oneline -3 && git status --short` (note any WIP that is
not yours — leave it uncommitted). Confirm every Ground-truth bullet against current
code: the `[:4000]` line, the `combined_feedback` build order, the DRAFT_SYSTEM rule
lines, `DRAFT_SCHEMA`, and the setter.html handler lines — record fresh line numbers.
Mint the session cookie and find the Lash Class queue row id via the live API (or
Supabase `setter_queue`), and snapshot the **before** counts: Sent, Auto-sent today.
- **Done-rule:** (a) every bullet confirmed or corrected with fresh `file:line`; (b) Lash
  Class row id recorded and still in Needs review (else nominate another agentless row
  and record it); (c) before-counts snapshot saved.

### Step 2 — Harden the truncation so fresh feedback always survives
In `route_queue_redraft()` (and any other caller that combines a digest with typed
feedback before `draft_reply`), rebuild the combination so the 4,000-char budget is
allocated feedback-first: LATEST OWNER RULES stays the outermost prefix (recency
weighting is a shipped ruling), then the memory digest is truncated to whatever room
remains AFTER reserving space for the full `feedback_text` — the typed feedback is
never cut. Keep `draft_reply`'s `[:4000]` as a backstop.
- **Done-rule:** a local harness call proves it: with a synthetic 5,000-char digest and
  a distinctive 200-char feedback string, the actual `payload["reviewer_feedback"]`
  handed to the OpenAI call (log it or intercept `_HTTP`) contains the feedback string
  **verbatim and unclipped**. Failure is recorded, not hidden.

### Step 3 — Backend can't-comply channel (warn only, never inject)
Add an optional `feedback_note` field to `DRAFT_SCHEMA` (strict schema: add to
properties + required with `""` allowed) and a DRAFT_SYSTEM rule: when reviewer_feedback
asks for something the draft has no source for (a resource link when the instructions
contain none or there is no agent, a fact not in instructions/thread/slots), the model
must NOT invent it and must state the reason in `feedback_note` in plain English (e.g.
"No agent is assigned, so I have no resource links to include — assign an agent or
attach the link manually."), empty string otherwise. `route_queue_redraft` returns
`feedback_note` in its HTTP response. **No new `setter_queue` columns** (schema-freeze);
the note is transient, response-only. Never-invent rules stay word-for-word intact.
- **Done-rule:** (a) a local `draft_reply` call with empty instructions and feedback
  "include links to the resources" returns a non-empty `feedback_note` and an html body
  containing **no invented URL**; (b) the same call with compliant feedback ("two
  sentences") returns `feedback_note == ""`; (c) `grep` confirms the never-invent rule
  lines are unchanged.

### Step 4 — Frontend: render the warning next to the draft
In `app/setter.html`, after a redraft response arrives in `doRedraft()`, render
`feedback_note` (when non-empty) as a visible warning line/banner adjacent to the draft
and the feedback input — transient is fine (it may disappear on reload), matching the
existing pill/hint styling. No rendering change when the note is empty.
- **Done-rule:** grep shows the render path wired from the redraft response to a DOM
  element; a local page load shows no console errors and no visual change for the
  empty-note case.

### Step 5 — Deploy and prove the live host serves it
Commit ONLY the files this loop touched, push, then prove deploy from the destination:
poll-log/boot ledger shows the new boot, and a marker string from this change greps in
the live-served artifact. Then reconcile the iCloud copy to match the repo.
- **Done-rule:** (a) live host serves the pushed commit (poll-log proof, not git alone);
  (b) marker grep passes against the live asset; (c) iCloud copy reconciled.

### Step 6 — Live proof (≤5 redrafts, drafts only, cookie-minted session)
On the live host, spending the redraft budget carefully: (a) Lash Class agentless row +
compliance-checkable feedback "Keep it to two sentences and start with 'Quick note'" →
read the regenerated draft back **from the `setter_queue` table in Supabase**, not the
UI, and confirm it obeys; (b) same row + feedback "include links to the resources" →
the can't-comply warning renders in the **live browser UI — screenshot proof** — and the
draft contains no invented URL; (c) one agent-assigned row + specific typed feedback →
Supabase read-back shows it honoured; (d) re-read Sent/Auto-sent counts — unchanged from
Step 1's snapshot, and total live redrafts used ≤ 5.
- **Done-rule:** all four sub-checks (a)–(d) pass with artifacts (row ids, Supabase
  read-backs, screenshot). Any sub-check failing = the step fails; fix and re-run only
  what failed, within the redraft cap. **Cap-hit = FAILED, never done.**

## Final report (always, both modes)

One summary listing: each step passed/skipped/FAILED with reasons; fresh `file:line` for
every edit; the commit hash pushed and the deploy proof; the truncation-harness payload
excerpt; the Lash Class row id and both its live results; the agent-assigned row id and
its result; the screenshot path; redrafts used (n/5); before/after Sent + Auto-sent
counts; and anything deferred (including the out-of-scope `scope="remember"` agentless
persistence edge).

## Hard don'ts

- Never edit the iCloud copy as the fix — the deploy repo `~/navreo-signals` is the only
  fix surface; iCloud is reconciled after deploy, never before.
- Never inject links or facts from feedback text into a draft — warn only (user ruling
  2026-07-16); the never-invent rules stay word-for-word intact.
- Never click Approve/send or cause any email to a lead; more than 5 live redrafts is a
  cap-hit, reported as FAILED.
- Never add a `setter_queue` column or PATCH a non-column key (schema-freeze); the
  warning lives in the HTTP response only.
- Never touch the `scope="remember"` agentless persistence edge (out of scope) or the
  stale decision pill (owned by `setter-redraft-pill-refresh`).
- Never commit WIP from parallel deploy-repo sessions — only this loop's files.
- Never trust the app's own success labels — Supabase read-backs and a rendered-browser
  screenshot are the only accepted live evidence.
- Never exceed a retry cap or report done while any done-rule fails.
