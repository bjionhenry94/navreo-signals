---
name: optimisation-wording-simplify
description: Static orchestration skill that rewrites the wording of the campaign OPTIMISATION SUGGESTIONS (the optimiser_notifications shown on app/optimise.html and app/campaigns.html in ~/navreo-signals, live at navreo-signals.onrender.com) so a 16-year-old understands every one at a glance — without dumbing the language down so far that a sales leader reads it as amateur. Rewording ONLY: thresholds, numbers, logic, action_type and which suggestion fires never change. A 4-persona panel (2 sixteen-year-olds, 2 sales leaders) must score every rewritten suggestion 9/10+ for ease of understanding — and the sales leaders 9/10+ for "not amateurish" — on the LIVE page before the loop can close. Includes a Loop Training Mode toggle (ON by default). Trigger with "/optimisation-wording-simplify", "make the optimisation suggestions easier to understand", or "simplify the optimiser wording".
---

# optimisation-wording-simplify

Rewrite the **wording** of the campaign optimisation suggestions so they read clean and
obvious — a 16-year-old gets each one instantly, a sales leader still respects it. The
suggestions are the `optimiser_notifications` rows (`title`, `detail`, `suggested_action`)
built as **static template strings** (no LLM) in `app/build_notifications.py` (primary) and
`app/fetch_data.py`, and rendered on `app/optimise.html` and `app/campaigns.html`. This loop
touches **only the human-facing text** of those strings. Static loop — fixed steps, each with
a done-rule; Loop Training Mode controls pausing.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at **every** step and wait for my explicit approval in chat before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** —
  say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end,
  not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule;
the panel gate in Step 5 caps at **3 rewrite→re-vote rounds**. On cap-hit, stop that step,
record it FAILED with the reason and best result reached, keep going, and surface it in the
final report. Never silently exceed.

---

## THE GOAL

Every optimisation suggestion is instantly understandable: plain, concrete, jargon-free
wording a **16-year-old rates 9/10+ for ease of understanding**, that **two sales leaders
also rate 9/10+ for ease AND 9/10+ for "reads professional, not amateur"** — with every
number, threshold, and recommended action exactly as accurate as before.

**Standing wording rulings from Bjion (2026-08-02, fold into the next run):**
- **The verdict must SAY THE ACTION, not name the diagnosis.** An all-variants-failing
  card read "Drop the 'Your Amazon ranking' angle" — vague; nobody knows what tapping
  means. It must read like "**drop all existing variants and come up with a new offer**":
  when every variant on the step has 0 positives, the suggested action is drop-everything
  + new offer, said in those words.
- **Wording drives the BUTTON.** The cockpit routes each card's primary by its headline
  (see `action-card-routing`): mechanical verbs (move/shift/weight/back/scale/turn off)
  produce a real one-click; ideation verbs (rebuild/rewrite/new angle/audit/retire/pivot)
  keep Copy-prompt. When rewriting a headline, keep the verb honest to the action's
  nature or the card grows the wrong button — and after any wording change, re-run the
  routing regression pair (campaign 3576107 cards 1+2).
- Spell variants in full — "Email 1: Variant G", never "Var G" / "Version G".

## Hard safety rails (every step, no exceptions)

- **Wording only.** Change display text (`title` / `detail` / `suggested_action`) ONLY.
  Never change a threshold, a computed number, the `action_type`, `priority`, `block_number`,
  which suggestion fires, or any branching logic. If the code decides *whether* or *what* to
  suggest, it is off-limits — only *how it's phrased* is in scope.
- **Numbers stay true.** Every send count, reply rate, %, variant label and campaign name
  interpolated into a string must render identically after the rewrite. Reword the sentence
  around the value, never the value.
- **Not dumbed-down.** Simpler ≠ childish. Keep the real sales/outbound noun when it carries
  meaning (variant, reply rate, sequence, deliverability) — cut the jargon that doesn't
  (assets, leverage, cadence-optimise). No emojis, no exclamation-mark hype, no baby-talk.
- **No em-dashes / no spintax in the strings** (house rule; `clean_text` / `clean_dashes_only`
  already enforce — keep it that way).
- **NEVER send to real prospects** and never trigger any Smartlead write; this loop edits
  text and re-runs the notification builder against test/live-read data only.
- **Ship-and-verify-LIVE law.** Local greps and green diffs are never done-evidence. Push,
  poll `/api/version` for the redeploy, mint a `navreo_session` cookie past the login gate,
  then read the rewritten suggestions on **navreo-signals.onrender.com** (`optimise.html`
  and a campaign card on `campaigns.html`).

---

## STEP 0 — Inventory every suggestion string (blocking)

Pull the full catalogue of user-facing strings before editing anything. Grep
`app/build_notifications.py` and `app/fetch_data.py` for every `title` / `detail` /
`suggested_action` literal and f-string template. Record each as `file:line`, note whether
it's a fixed literal or a template (and what values it interpolates), and open
`optimise.html` + a campaign card on the live host to capture how each actually reads in
context. Build one table: original wording → the confusing bit → interpolated values that
must survive.

*Done-rule: a written catalogue with a row per distinct suggestion string, each with its
`file:line`, its interpolated values, and a one-line note on what's unclear about it.*

## STEP 1 — Draft the plain-English rewrite for each string

For every catalogue row, write the replacement text: shortest clear sentence, everyday
words, the point first. Keep the load-bearing outbound noun, cut the filler jargon, keep
every interpolated value in place and correctly formatted. Keep the same rough length so the
UI doesn't reflow badly. Produce an old→new column beside the catalogue.

*Done-rule: every row has a proposed rewrite; a spot-read of the set shows no jargon-for-its-
own-sake, no lost number, no em-dash, and no template placeholder dropped.*

## STEP 2 — Apply the rewrites to the source

Edit the strings in place in `app/build_notifications.py` and `app/fetch_data.py`. Text only —
diff must show zero changes to thresholds, numeric expressions, `action_type`, keys, or
control flow. Keep the f-string interpolation fields byte-identical.

*Done-rule: `git diff` touches only string contents; grep confirms every interpolated field
(`{sent:,}`, `{v['label']}`, rates, campaign names) is still present in the reworded strings.*

## STEP 3 — Rebuild notifications and verify data integrity

Re-run the notification builder against real campaign data (`python3 app/build_notifications.py`
or the daily path) so rows regenerate with the new wording. Compare a sample of regenerated
rows to their pre-rewrite values: same campaigns flagged, same priorities, same action_types,
same numbers — only the prose changed.

*Done-rule: for a sample of ≥10 suggestions across types (variant call, low reply flag,
distribution flag, recommended actions, all-clear), each has identical priority / action_type
/ interpolated numbers as before and only the phrasing differs; no row disappeared or appeared.*

## STEP 4 — Ship and read it on the live UI

Push, poll `/api/version` for the redeploy, log past the gate, and read the suggestions on
**navreo-signals.onrender.com/app/optimise.html** and on a campaign card in `campaigns.html`.
Confirm they render cleanly (no overflow, no broken placeholder, no double space where a word
was cut) and the numbers on screen match the campaign's real stats.

*Done-rule: reworded suggestions render correctly on both live pages, numbers on screen match
the backing stats, zero console errors on the walked paths, with a one-line "read X, saw Y" note.*

## STEP 5 — 4-persona panel to 9/10 (quality gate)

Convene **4 reviewers as parallel subagents**, each reading the *live* reworded suggestions:

- **Two 16-year-old personas** — bright, no sales background. Each scores every suggestion
  **Ease of understanding 1–10** ("would you know exactly what this is telling you to do?").
  Flag any word or sentence they'd have to re-read.
- **Two sales-leader personas** — experienced outbound/agency leaders. Each scores every
  suggestion on **two axes 1–10**: **Ease of understanding** AND **Professional, not amateur**
  ("does this read like a sharp operator wrote it, or like it was dumbed down?"). Flag anything
  that reads childish, vague, or hype-y.

If any teen scores any suggestion **< 9 on ease**, or any sales leader scores any suggestion
**< 9 on ease OR < 9 on professional**: apply the highest-value wording fixes, redeploy,
re-verify Steps 3–4 still pass, re-vote. Max **3** rewrite→re-vote rounds.

*Done-rule: on the final vote — **both 16-year-olds ≥ 9/10 ease** AND **both sales leaders
≥ 9/10 ease and ≥ 9/10 professional**, on every reworded suggestion — with Steps 3–4 still
green after the last fix.*

---

## HOW TO RUN

1. Read the mode line. If **ON** (default): do Step 0, present the catalogue, and stop for
   approval; then one step at a time, pausing after each; skip any step whose done-rule
   already passes. If **OFF**: run 0→5 in order, no pauses.
2. Every step: edit → rebuild → push → poll `/api/version` → verify the done-rule on the live
   host (read_page / screenshot). 3 retries max, then FAILED and move on.
3. Interruptions count as redeploys — re-confirm live state after any interruption before
   calling a step done.

## OVERALL DONE-RULE

Every optimisation suggestion reworded in the source (`build_notifications.py` + `fetch_data.py`),
rebuilt with identical priorities / action_types / numbers, live on
**navreo-signals.onrender.com** (`optimise.html` + `campaigns.html`), and the panel passing:
**both 16-year-olds ≥ 9/10 ease, both sales leaders ≥ 9/10 ease and ≥ 9/10 not-amateur**, on
every suggestion. No logic or number changed, nothing sent, no writes to real prospect data.
Final report: one line per step — DONE / SKIPPED (already passed) / FAILED (reason + retries
used) — the panel scores per persona per axis, a before/after sample of 5 suggestions, and a
browser link I have confirmed loads.
