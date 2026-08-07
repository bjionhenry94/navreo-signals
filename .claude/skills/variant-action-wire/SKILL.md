---
name: variant-action-wire
description: Static orchestration skill that gives every variant-level insight in the Navreo tool a working one-click action — sweep every seam that names a variant but offers no action (campaigns list, campaign detail Messaging tab, optimisation insights + cockpit, analytics "Why?" digests, every Smartlead-writing skill/cron), then ROUND 1 build ONE labelled P1/P2/P3… prototype artifact of the full flow for each action idea (seam → control → confirm → simulated post-write proof) and pause for the pick, then ROUND 2 wire only the picked designs live with every sequence write routed through ONE shared ID-intact save helper (fresh GET → POST full sequence with every step + variant ID echoed, delayInDays→delay_in_days) behind an explicit confirm, refactoring every pre-existing sequence-write path onto that helper. Includes a Loop Training Mode toggle (ON by default). Trigger with "/variant-action-wire", "run the variant action loop", or "wire one-click actions onto the variant insights".
---

# variant-action-wire

Every place in the Navreo tool that **names a variant** (an insight card, the Messaging
tab, a "Why?" digest, an optimisation cockpit row) should also let me **act on it in
one click** — disable it, approve a copy change, edit it in bulk — instead of naming a
problem and leaving me to go fix it by hand in Smartlead. This loop finds every such
seam, prototypes the action designs on one artifact for me to pick from, then wires only
the picked ones live through a single ID-safe save helper so no code path can ever save
a sequence and lose a variant's ID or its `get_campaign_variant_statistics` history.

Static loop — fixed steps, each with a done-rule; Loop Training Mode controls pausing.

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
- Still check every step's done-rule and still honour the retry cap. Report at the
  end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its
done-rule. On cap-hit, stop that step, record it FAILED with the reason and the best
result reached, keep going, and surface it in the final report. Never silently exceed.

**Hard gate that ignores the mode:** the pick pause at the end of ROUND 1 is a real
stop in BOTH modes. OFF still means autonomous *execution*, not deciding which
prototypes win — never start ROUND 2 without my pick.

---

## THE GOAL

Every variant-level insight in the tool carries a working one-click action whose design
I picked from a P1/P2/P3 prototype artifact, and **no code path in the platform can save
a sequence without every existing variant's ID intact.**

## Hard safety rails (every step, no exceptions)

- **NEVER send to real prospects.** No live Smartlead write happens in ROUND 1 at all.
  In ROUND 2, exercise every new action only on a **paused / low-stakes Navreo**
  campaign, check `row.status` before any write, delete/send nothing on real client data.
- **The ID-intact recipe is law for every sequence write** (proven, `smartlead-variant-edit-recipe`):
  fresh **GET** the campaign sequences → **POST** the *full* sequence back with **every
  step id and every variant id echoed** → rename `delayInDays` → `delay_in_days` on the
  way out. Never construct a sequence payload from scratch; never omit an id; never send
  a partial sequence. A write that can't prove it echoed the ids does not run.
- **One helper, no exceptions.** All sequence writes — the new actions AND every
  pre-existing write path in the platform — route through the single shared save helper
  (below). No second code path may call `save_campaign_sequences` directly.
- **Explicit confirm before every write.** Each action shows exactly what changes (which
  campaign, which step, which variant, old→new) and waits for my yes before it fires.
- **Ship-and-verify-LIVE law.** Local renders, greps, and green labels are never
  done-evidence for a UI step. Push, poll `/api/version` for the redeploy, mint a
  `navreo_session` cookie past the login gate, verify on **navreo-signals.onrender.com**.
- Web is a **512MB Render starter** — no in-process bulk sweeps. Supabase clips at
  **1000 rows** — paginate. The artifact link is verified to render before hand-over.

## THE SHARED SAVE HELPER (the one door every write goes through)

One function, one place. Signature roughly:

    save_sequence_ids_intact(campaign_id, mutate_fn):
        seqs = GET current sequences for campaign_id        # fresh, every time
        new  = mutate_fn(deep_copy(seqs))                   # caller edits IN PLACE
        assert every step id and variant id in `seqs` still present in `new`   # ID guard
        payload = rename delayInDays -> delay_in_days over `new`
        POST payload back to save_campaign_sequences
        refetch and return the saved sequences               # for the proof step

- `mutate_fn` is the *only* thing an action supplies (disable this variant, swap this
  copy, apply this bulk edit). It never sees the transport, never rebuilds ids.
- The **ID guard assertion is inside the helper** — a mutate_fn that would drop an id
  fails loud before the POST, not after.
- Every caller — insight-card disable, Messaging-tab disable, copy-change approve, bulk
  edit, and every refactored legacy path — calls this and nothing else.

## Field learnings (2026-08-02, proven live — read before touching any variant action)

- **The action set now includes `shift_share`** (`/api/campaigns/{cid}/variant-action`,
  confirm token `SHIFT`): moves ALL of one live variant's share onto another
  (loser → winner), source kept on the step at 0% with id + history intact. First
  production execution 2026-08-02 on campaign 3642625 (A 50%→100%, B 50%→0%).
- **Equal-split campaigns read as all-zero.** Smartlead's "split the variant percentage
  equally" checkbox stores NO percentages — the GET returns 0/null for every variant
  while each really receives 100/n. Any guard shaped `_pct_of(x) <= 0 → refuse` falsely
  rejects these campaigns ("has no share to move - already at 0%"). Rule: when a step's
  stored pcts **sum to 0**, compute *effective* even shares (100/n across non-deleted
  variants) and run guards + arithmetic on those. `shift_share` does this; **`scale_winner`
  still carries the latent bug** — apply the same fix if it ever fires on an equal-split
  campaign.
- **`variant_distribution_type: "MANUAL_PERCENTAGE"` is mandatory on every
  variant-carrying step of a save** (Bjion, 2026-08-02). The GET never returns it, and a
  save that omits it flips the step back to EQUAL — the UI shows every variant re-enabled
  on an even split with the stored percentages ignored underneath. The save helper ships
  it; never bypass.
- **The done bar for a new action is a live-UI execution, not a render.** Drive the real
  page (prod, real session cookie), click the button, type the confirm token, confirm, and
  read the receipt — the helper's verify_fn re-pulls from Smartlead and asserts the saved
  pcts before success shows, so the receipt is proof. Rendering the button or opening the
  modal proves nothing about the write path (the equal-split bug rendered perfectly).

---

## STEP 0 — Sweep for variant seams with no action (blocking, read-only)

Walk the whole tool and every Smartlead-writing skill/cron. List every seam that
**names a variant** (or a copy/subject line tied to one) but offers **no way to act**:

- campaigns list, campaign detail **Messaging tab**, optimisation **insights cards** +
  **cockpit** rows, analytics **"Why?" digests**, and every skill/cron that writes to
  Smartlead sequences (`lilly-optimiser`, `lilly-bot`, `campaign-detail-optimise`,
  `campaign-insight-cockpit`, `messaging-tab-variant-uxlab`, `insight-why-digest`, …).

Also inventory **every existing code path that writes a sequence** today (grep for
`save_campaign_sequences` and any wrapper), with file:line — these are the paths ROUND 2
must refactor onto the shared helper.

*Done-rule: a written seam list — for each, `page/skill:line`, the variant it names, the
action it's missing — covering at minimum: one-click disable from an insight card,
one-click disable from the Messaging tab, one-click approve of a suggested copy change,
and bulk variant edits across campaigns; PLUS a written inventory of every current
sequence-write call site with file:line. Both lists explicit before any build.*

---

## ROUND 1 — PROTOTYPES (no live write)

### STEP 1 — Build one labelled prototype artifact for every action idea

For **every distinct variant-action idea** the sweep surfaced, build a **working visual
prototype of the full flow** — all four beats, simulated end to end:

1. **the seam** where the action lives (the card / Messaging row / digest / cockpit),
2. **the action control** (Disable · Approve change · Bulk-edit …),
3. **the explicit confirm step** (shows campaign, step, variant, old→new),
4. **the simulated post-write proof state** (the "done, IDs intact, history preserved"
   result — faked, no real Smartlead call).

Put **all** prototypes on **ONE one-page artifact**, each labelled **P1, P2, P3, …**
with a **one-line pitch** per prototype. Minimum set: insight-card disable,
Messaging-tab disable, copy-change approve, cross-campaign bulk edit — plus any further
seam ideas the sweep uncovered. No live Smartlead write in this round.

*Done-rule: one artifact, every idea present as a labelled P#, each P# demonstrating all
four beats (seam · action · confirm · simulated proof) with a one-line pitch; the
artifact link is opened and **confirmed to render** before hand-over.*

### STEP 2 — Pause for my pick  (HARD STOP, both modes)

Present the artifact link and the P# list in chat. **Stop.** Wait for me to name the
winning prototype(s). Do not build anything live until I've picked.

*Done-rule: I have named the winning P#(s) in chat.*

---

## ROUND 2 — WIRE LIVE (only the picked designs)

### STEP 3 — Build the shared save helper first

Implement `save_sequence_ids_intact` (above) as the single sequence-write door, with the
ID-guard assertion inside it. Nothing else is wired until this exists and is unit-proven.

*Done-rule: helper exists; a test proves (a) a normal edit round-trips with every id
preserved, and (b) a mutate_fn that drops an id is rejected by the guard before any POST.*

### STEP 4 — Wire the picked actions onto their seams

Implement **only** the prototypes I picked, matching the picked design. Each action:
builds its `mutate_fn`, shows the explicit confirm, and on my yes calls
`save_sequence_ids_intact`. No action calls `save_campaign_sequences` directly.

*Done-rule: each picked action renders on its live seam matching the picked prototype,
and firing it on a **paused/low-stakes Navreo** campaign changes **exactly** the intended
variant and nothing else (verified live).*

### STEP 5 — Refactor every legacy sequence-write path onto the helper

Repoint every write call site from the Step-0 inventory (`lilly-optimiser`, `lilly-bot`,
any server route, any cron) to go through `save_sequence_ids_intact`, so no path can save
a sequence without the ID guard. Behaviour of existing writes stays identical.

*Done-rule: a repo-wide grep shows `save_campaign_sequences` is called from **exactly one
place** (the helper); every former caller now routes through it; touched skills/paths
still perform their original write correctly.*

---

## STEP 6 — Four-part verification (the done gate)

All four, or it isn't done:

1. **Artifact** — the one-page artifact exists at a confirmed-rendering link and shows
   every idea as a labelled P1/P2/P3… each demonstrating seam, action, confirm step, and
   simulated proof state.
2. **UI matches + acts** — the shipped UI matches the picked prototypes, and exercising
   each new action on a live paused/low-stakes Navreo campaign changes **exactly** the
   intended variant.
3. **IDs + history preserved** — the post-write re-fetch proves every pre-existing
   variant kept its **exact ID**, and `get_campaign_variant_statistics` still shows its
   prior history for those variants.
4. **One door** — a code-level grep confirms **all** sequence writes route through the
   shared helper (`save_campaign_sequences` called from one place only).

*Done-rule: parts 1–4 all pass, on the live host, with evidence for each.*

---

## HOW TO RUN

1. Read the mode line. If **ON** (default): do Step 0, present the seam + call-site
   lists, stop for approval; then one step at a time, pausing after each; skip any step
   whose done-rule already passes. If **OFF**: run the steps in order, no pauses — but
   the STEP 2 pick pause is still a hard stop.
2. Every UI/write step: edit → push → poll `/api/version` → verify the done-rule on the
   live host (read_page / screenshot / network / a live re-fetch). 3 retries max, then
   FAILED and move on.
3. ROUND 1 does **zero** live Smartlead writes. ROUND 2 writes only through the helper,
   only on paused/low-stakes Navreo campaigns, only after an explicit confirm.
4. Interruptions count as redeploys — re-confirm live state after any interruption before
   calling a step done.

## OVERALL DONE-RULE

Every variant insight the sweep found carries a one-click action whose design I picked
from the P#-labelled artifact; the shipped actions match the picks and each changes only
its intended variant on live; every pre-existing variant kept its exact ID with
`get_campaign_variant_statistics` history intact after the writes; and a grep proves
every sequence write in the platform goes through the one shared ID-intact helper. All
four verification parts green on **navreo-signals.onrender.com**, no permanent actions on
real client data at any point. Final report: one line per step — DONE / SKIPPED (already
passed) / FAILED (reason + retries used) — the P# list with the pick marked, the
four-part verification evidence, before/after grep of the write call sites, and a browser
link I have confirmed loads.
