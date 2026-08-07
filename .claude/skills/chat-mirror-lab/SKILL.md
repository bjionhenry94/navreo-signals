---
name: chat-mirror-lab
description: Static orchestration skill that inverts the strategy board's control model - the
  chat leads, the UI follows (Bjion directive 2026-07-27). Chat POSTs a tiny "focus" signal
  alongside run updates; /app/strategy.html auto-navigates to whatever surface the conversation
  is touching (targeting talk opens the chips view, content talk opens the emails page, checks
  open sign-off, background verification shows the build view), with smooth animated
  transitions, so the tool reads as a live dashboard of Claude's backend. Builds the focus
  plumbing for real (additive endpoint + page follower), then 3 prototype mirror styles as
  replay artifacts, each passing a simulated panel of 5 non-technical founders and sales
  leaders at 9/10+ on actionable insights, easy to digest, and beauty of the design. Winner
  merges into the live strategy.html only on Bjion's pick. Use when the user says "run the
  chat mirror lab", "make the UI follow the chat", "build the chat-led dashboard", or
  "/chat-mirror-lab".
---

# chat-mirror-lab

The board stopped being where work happens; chat is. So the page's job changes: it is the
**dashboard of what Claude is doing** - it goes where the conversation goes and shows the
change happening, smoothly. Static loop - fixed steps, checkable done-rules, Loop Training
Mode controls pauses.

## ⚙️ LOOP TRAINING MODE  →  **OFF** (flipped by Bjion, 2026-07-27)

Flip it by editing this one line:

    LOOP_TRAINING_MODE = OFF       # ON = approve every step · OFF = run autonomous

**When ON**
- Pause at the end of **every** step and wait for my explicit approval before continuing.
- Before running a step, check its done-rule first. **If it already passes, skip it** - say so and move on.
- Only (re-)run steps that fail their done-rule.
- Retry cap applies (below). Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its done-rule; the
panel (Step 4) runs **max 4 full rounds**. On cap-hit, record FAILED with the reason and honest
scores, keep going where possible, surface every FAILED item in the final report. Never declare
done on a cap-hit.

## THE GOAL

The UI is led by whatever is happening in chat - a mirror of Claude's backend, animated and
smooth. Concretely: while Bjion talks in chat, the open board navigates itself to the surface
being worked on and shows the change land - targeting chips update as roles are discussed,
the emails page opens when the content is being written, the checks surface when checks run,
the build view while verification works in the background. Nothing on the page needs clicking
to follow along, and following along never needs explaining.
**Verification bar: 5 simulated non-technical founders and sales leaders score EACH prototype
9/10+ on all three axes - actionable insights, easy to digest, beauty of the design.**

## THE CONTRACT (what makes the mirror possible)

- **Focus signal** - chat POSTs `{ideaId, view, note, ts}` to `/api/strategy/focus` after every
  action; `view` ∈ board · targeting · emails · opener · checks · building · signoff. `note` is
  one plain-English line of what Claude is doing ("removing Account Executive", "writing
  version C", "running the upload checks"). Storage piggybacks `campaign_insights`
  (scope=strategy, insight_key=wizard_focus) exactly like wizard_run - no new table.
- **One poll** - `GET /api/strategy/run` gains a `focus` field so the page keeps a single 5s
  poll. The follower maps view → the wizard's existing phases (targeting=2, building=3/5,
  emails=4p1, opener=4p2, checks/signoff=6); no new screens are invented.
- **Motion** - view changes cross-fade (180-240ms, ease-out), the touched element announces
  itself (chip fades out as chat removes it, number tweens on the 500ms re-check beat, rail
  card pulses when its campaign is being worked), and a quiet one-line ribbon shows the note.
  `prefers-reduced-motion` gets instant swaps. No spinners, no jank, nothing explains itself.
- **Never fight the hand** - if the user interacted with the page in the last 10s, a focus
  change pulses the rail + shows "Chat moved on - catch up" instead of yanking the view.
  Prototypes may vary the threshold and affordance; the panel judges what feels right.

## HARD GATES (non-negotiable)

- **Zero provider credits.** Prototypes replay a scripted session timeline (fixture); panel
  rounds never call a provider. The plumbing step's live test replays an existing run only.
- **Additive server change only** - the focus endpoint mirrors strategy_run_get/post patterns,
  verified locally (cookie + curl + browser) before any push; nothing existing is modified
  beyond adding `focus` to the GET payload. Repo edits in `~/navreo-signals` only.
- **Template law** - `wizard-template.html` and the live `strategy.html` are never edited in
  place by prototypes; P1-P3 are generated copies. The winner merges only on Bjion's pick via
  `build_live.py` (backup first). Prototype artifacts get their own URLs, distinct favicons.
- **Nothing sends** - no Smartlead writes, no uploads, no activation, anywhere in this lab.
- **House rules** - Navreo white DS tokens (`--sunken`/`--raised`/`--line-2`; `--card-toned`
  does not exist), jargon ban, 16-year-old language, no em-dashes in user-visible copy, never
  hide the decision cue. rAF is throttled in driven panes - drive animations with CSS
  transitions and direct sets, never rAF loops.

## THE THREE PROTOTYPES (same follower + timeline; only the mirror's voice differs)

| # | Style | The feel |
|---|---|---|
| M1 | **Quiet follow** | The view simply goes where chat goes; one slim ribbon line states what is happening. Calmest possible mirror. |
| M2 | **Narrated cockpit** | A persistent thin activity rail ticks each chat action as it lands (newest on top, older fading). The board feels alive even when you look away. |
| M3 | **Guided spotlight** | The exact element being changed gets a soft highlight sweep as it updates - the removed chip, the rewritten paragraph, the moving number - and the page auto-scrolls it into view. |

## THE STEPS

### Step 1 - Contract spec + replay timeline
- Write `mirror-lab/mirror-spec.md`: the focus schema, the view→phase map, the motion spec
  (durations, easing, reduced-motion, the never-fight-the-hand rule), and the ribbon/ticker
  copy rules (≤8 words per note, plain English). Write `mirror-lab/replay-timeline.js`: a
  scripted ~90-second session replaying a REAL-shaped flow over the current run fixture -
  targeting edit (roles removed, number re-checks) → content pass (emails page, a version
  body visibly updates) → checks (sign-off surface, checks ticking) → background verification
  (build view) → back to board. Every event carries its focus note.
- **Done-rule:** both files exist; the timeline covers all four surface types with ≥8 events;
  zero provider calls anywhere in the plan.

### Step 2 - Real plumbing: the focus signal
- Add `POST /api/strategy/focus` + `focus` in the run GET (patterns copied from
  strategy_run_get/post, including the http_json-4xx-truthy guard and far-future expires_at).
  Extend the live page's LIVE module with the follower (view→phase driver + ribbon, no motion
  styling yet). Verify locally end-to-end: browser open on the board, curl POSTs focus
  {view: emails, note}, page lands on the emails page ≤5s with journey state intact; then
  commit + push + prod /api/version + prod GET shows `focus`.
- **Done-rule:** the local browser walk and the prod checks above, all evidenced; zero console
  errors; the server diff is additive only.

### Step 3 - Build M1-M3 replay artifacts
- Generate three copies of the live page with the motion layer per style and the replay driver
  inline (a "Replay the session" button starts the timeline; no server needed). Publish each
  as its own artifact.
- **Done-rule (per prototype):** replay runs hands-free through all four surfaces; transitions
  are CSS-driven with the reduced-motion path working; never-fight-the-hand demonstrably works
  (interacting mid-replay pulses instead of yanking, catch-up affordance shown); zero console
  errors; 375px clean; artifact live.

### Step 4 - Panel: 5 non-technical founders and sales leaders
- Fresh cast, impatient, allergic to reading. Each watches every prototype's replay end-to-end
  (and interrupts it once, to feel the catch-up affordance), then scores /10 on the three axes
  with a one-line worst-moment quote.
- **Done-rule:** 15 scorecards, all three axes on each, a worst-moment quote on each.

### Step 5 - Fix loop
- Any prototype under **9/10 average on ANY axis** gets its worst moments fixed and re-panelled.
  Max 4 rounds. Over-minimising that hides what Claude is doing counts as a defect too.
- **Done-rule:** all 3 prototypes at 9/10+ on all three axes, or named FAILED-BAR lines with
  honest scores.

### Step 6 - Hand-off (chat summary, no new artifact)
- Report: 3 URLs, per-axis scores, what each style does best, the Step-2 plumbing evidence,
  and a recommendation. Append `lilly-strategy/sessions/chat-mirror-lab-<date>.md`. The live
  strategy.html keeps only the mechanical follower until Bjion picks; **on his pick**, merge
  the winning motion layer via `build_live.py` (backup first), push, prod-verify, and update
  `lilly-strategy` SKILL.md so every phase of a strategy run POSTs its focus signal (ideate →
  board, probe → targeting, copy → emails, gate → checks, build → building) - that wiring is
  what makes the tool "the manifestation of the backend", not just this lab.
- **Done-rule:** report delivered; session file written; pick-wiring documented as the named
  follow-up; live page still mechanically following (proven by one last focus POST).

## OVERALL DONE-RULE

Focus plumbing live in prod (additive, evidenced); 3 replay prototype artifacts walking all
four surfaces hands-free with working reduced-motion and catch-up affordances; 15 scorecards
with every prototype at 9/10+ on actionable insights, easy to digest, and beauty (or honest
FAILED-BAR lines); hand-off report + session file delivered; wizard-template.html and the live
strategy.html unmerged pending Bjion's pick. Zero provider credits, nothing sent, anywhere.
