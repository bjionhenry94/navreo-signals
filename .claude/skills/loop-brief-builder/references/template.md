# The house loop-brief template (format law)

Every generated brief follows this section order. Sections marked (always) are mandatory; the rest appear when the task needs them. Match the voice of the exemplars: dense, concrete, zero filler, bolded key rules.

---

## 0. Frontmatter (always)

```yaml
---
name: <kebab-name>
description: Static orchestration skill that <outcome in one breath> — <the mechanism>.
  One fixed step list, each step with a checkable done-rule, retry caps, and a Loop
  Training Mode toggle. Use when the user says "<phrase 1>", "<phrase 2>", or "/<name>".
---
```

The description is the trigger surface: lead with what it ships, include 3–4 realistic trigger phrases plus the slash form. If scope is deliberately confined, say so in the description too ("hiring + engagement signals only").

## 1. Title + one-paragraph framing (always)

`# <Human title>` then 2–4 lines: the gap this closes, why it exists, and the shape of the loop ("Static loop — fixed steps, each has a done-rule, Training Mode controls the pauses").

## 2. Loop Training Mode block (always)

```markdown
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
```

Set the default from the user's answer (OFF unless first-run destructive). If the loop iterates in rounds, add a round cap here ("max 4 full tester-rounds").

## 3. Destructive-action gate (when anything deletes / sends / spends)

Immediately after the mode block, non-negotiable and specific:

```markdown
**Destructive-action gate (both modes, non-negotiable):** the only <things> ever
<deleted/sent/spent> are <exact allowed set, with the classifier that decides>.
<Adjacent-but-not-allowed cases> are NEVER <actioned> — they're reported. In Training
Mode ON, additionally show the <affected list> and get approval before the <action> fires.
```

One gate per destructive surface. Include hard caps (max leads, max credits) as numbers.

## 4. Goal (always)

What is user-visibly true when done, as numbered outcomes. Include the measurable done bar (the numbers from the question round) here or in a dedicated "THE DONE-RULE (single source of truth)" section for loops with a composite bar:

```markdown
> <metric A> is **≥ X**, **and** <metric B holds for every case>, verified live and
> reset afterward. Anything less than both halves = not done. On the round cap, stop
> and report the gap honestly — do not declare done.
```

## 5. Ground truth (always)

`## Ground truth (verified <date> — re-verify in Step 1, line numbers drift)`

Bullets of verified facts: exact files + line numbers, endpoints + auth shape (with one proven request/response when an API was probed), key locations (`~/.navreo-keys.env`), table names + write helpers, rate limits, known gotchas, relevant memory names. Also record what is *unknown* and where Step 1 must resolve it. This section is what saves the loop from rediscovery — be generous.

## 6. Budget ledger (when the loop spends)

Running table or rule: hard budget, what each step may spend, what to do at 80% (pause and report in ON; stop-and-report in OFF).

## 7. Steps (always)

`### Step N — <imperative title>` … body … then:

`- **Done-rule:** <checkable observation>.`

Quality bar for every done-rule:
- Names the exact command or observation ("`grep -n "simulateVerify"` returns nothing", "polling `/api/jobs/<id>` shows queued→running→done with non-fabricated counts", "the app_activity_log row exists").
- Failure is recordable, not hidden ("FAILED rows count as complete — the loop records failure, it doesn't hide it").
- Multi-part rules are lettered (a)–(e) so partial passes are visible.
- Per-step retry cap noted when it differs from the default.

Canonical step skeleton (adapt, don't force):
1. **Re-verify ground truth** — confirm every Ground-truth bullet against current code; resolve the recorded unknowns; prove any unproven API with one live call.
2..k. **Build/fix steps** — backend before frontend; each independently verifiable.
If the brief creates something scheduled/recurring: wire it into the existing owned schedule (e.g. the Render cron via `run_daily.py`'s once-daily-gate pattern) rather than creating a new scheduler — never add a second writer to a schedule owned elsewhere, and always include an idempotency proof (pattern 8) since re-ticks WILL happen.

k+1. **Deploy** (when there's a deploy) — push, wait for live, marker-grep the deployed artifact, reconcile repo↔iCloud copies (memory `signals-deploy-repo`).
last. **Live proof** — the verification stack's end-to-end proof on the real system, smallest blast radius first. For UI: browser-rendered evidence (screenshot), never just a grep of deployed JS. For data: read back from the destination tool.

## 8. Final report (always)

`## Final report (always, both modes)` — one summary listing: steps passed/skipped/FAILED, the real numbers (counts, ids, spend, per-case results), artifacts (log row ids, file paths, screenshots), and anything deferred. Name the specific numbers this task produces — "a summary" is not a spec.

## 9. Hard don'ts (always)

5–8 bullets: the destructive gates restated as nevers, "never leave the mock/old path reachable as a silent fallback", "never guess endpoints not proven in Step 1", scope exclusions from the raw brief, "never exceed a retry cap or report done while any done-rule fails".

---

## Voice and mechanics
- Dense and specific; bold the load-bearing rules; use the user's ids/URLs/names verbatim.
- Record the user's rulings inline with attribution: "(user, 2026-07-12): EXCLUSIVE routing…".
- Keep the whole brief under ~200 lines. If ground truth or a test matrix outgrows that, the brief may reference a sibling file in its own skill folder.
