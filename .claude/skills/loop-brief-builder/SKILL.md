---
name: loop-brief-builder
description: Convert a written or spoken brief (voice-note transcript, rambling message, meeting excerpt, half-formed idea) into a paste-ready loop brief in the house template — "The Task / The Goal / The Verification" followed by the verbatim "Build me ONE Orchestration Skill…" Loop Training Mode boilerplate. The whole point is to front-load ALL the back-and-forth into one batched question round so the three filled lines carry every ruling, gate, and gotcha the eventual loop needs. The deliverable is the template-format brief text itself, returned in full in chat — NOT a finished SKILL.md (the skill file gets built later, when the user fires the brief). This skill NEVER executes the loop the brief describes, and only saves/publishes anything when asked. Use this whenever the user wants a task turned into a loop/brief/skill, says "turn this into a loop brief", "make this a loop", "convert this into one of those briefs", "build me a skill for this task", "set this up so it runs until done", "use the task verification and goal framework", pastes a voice-note transcript with build intent, or describes a multi-step build/fix/ship task and wants it packaged for autonomous execution. Trigger even if they just dump a messy description and say "you know what to do with this".
---

# Loop Brief Builder

Turn raw intent into a paste-ready loop brief. **The output is the brief in the fixed template below — NOT a finished SKILL.md** (ruling: user, 2026-07-12, after two wrong deliveries). The skill file itself only gets written later, when the user pastes/fires the brief; this skill's job is the three filled lines plus the verbatim boilerplate.

## The deliverable template (format law — boilerplate verbatim, only the [brackets] get filled)

```
The Task: [the task — every surface, ruling, gate, and gotcha baked in, in prose].

The Goal: [one sentence — what done looks like].

The Verification: [the rule that confirms done — the composite done bar, "all parts or it isn't done"].

Build me ONE Orchestration Skill with the goal, steps, and done-rule pre-baked. Static. Small enough to read in one sitting.

Bake in a feature called Loop Training Mode with these exact rules:

- When ON: pause at every step and wait for my approval before continuing. Skip any step that already passes the done-rule. Only re-run steps that fail. Cap retries so it can't loop forever.
- When OFF: run autonomously, no pauses, but keep the done-rule checks and the retry cap.

Set Loop Training Mode to ON by default. Document the toggle at the top of the skill file so I can flip it later.
```

Everything below "The Verification:" is IMMUTABLE boilerplate — never reword it, never merge it into prose, never replace it with a SKILL.md-shaped document. All the intelligence of this skill (ground-truthing, verification-stack design, the question round) gets compressed into the three filled lines: rulings attributed inline where useful, destructive gates and exclusions stated in The Task, the full multi-part done bar in The Verification. Training Mode is fixed ON by the boilerplate — never ask about it.

The house SKILL.md framework (same shape as `signals-verify-jobs-ship`, `signal-push-uxlab`, `warmup-capacity-restore`) is what the brief PRODUCES when fired — [references/template.md](references/template.md) still governs that later step, not this deliverable.

**Why this exists:** the user's biggest cost is back-and-forth — bug reports, "it didn't actually work", clarifying questions mid-run. A loop brief kills that in two ways: (1) verification thorough enough that "done" means *proven working*, not "code written", and (2) every judgment call the loop would otherwise interrupt for is asked ONCE, up front, in a single batched round. Optimise everything for those two outcomes.

## The workflow (fixed order)

### 1 — Ingest and mine the raw brief
Read the whole input (transcript, message, doc). Voice transcripts ramble, repeat, and self-correct — the LAST statement of an idea wins over earlier versions. Extract into a working sheet:

- **Outcome:** what is true when this is done, in the user's words.
- **Surfaces touched:** files, apps, APIs, campaigns, tables, external tools. Resolve vague references ("the dashboard", "that campaign") against the codebase, memory index, and existing skills BEFORE asking the user about them — a question you could have answered yourself wastes one of your question slots.
- **Destructive / outward / spend surfaces:** anything that deletes, sends, publishes, or costs credits/money. Each one becomes a gate in the brief.
- **Numbers mentioned:** counts, thresholds, ids, dates. Capture verbatim — these seed done-rules.
- **Exclusions:** anything the user said NOT to do, however offhand. These become Hard don'ts.

### 2 — Establish ground truth yourself
Before drafting, verify what you can with tools: open the files, hit the endpoints read-only, check the tables, find the line numbers. Ground-truthing itself is free-only: reads, greps, and zero-cost probes. Anything that would spend credits/money to verify goes into Step 1 of the generated brief instead, debited against that brief's budget. The brief's **Ground truth** section must contain *verified* facts with locations (`file:line`, endpoint, table name), dated, and marked "re-verify in Step 1 — line numbers drift". A ground-truth section built from assumptions is how loops burn retries on rediscovery. What you cannot verify becomes either Step 1 work in the generated brief or a question in step 4.

### 3 — Design the verification stack (the heart of the job)
Do this BEFORE writing steps, and design it one notch more thorough than the user asked for. For every claim the finished loop will make, ask: *how would this fail silently, and what observation would catch it?* Read [references/verification-patterns.md](references/verification-patterns.md) and select every pattern that applies — typical briefs use 4–7 of them. Non-negotiable minimums:

- Every step gets a **done-rule** that is checkable by command or observation (grep output, curl response, live-tool read, screenshot, matching row). "The code looks right" is never a done-rule.
- The final step is always a **live proof** on the real system: for UI work the rendered page in a browser is the only acceptable done-evidence; for data/API work, read the numbers back from the *destination* tool, never from the app's own success label.
- Anything the loop writes must be **read back independently** — the write path is never trusted to verify itself.
- If the loop mutates shared/live state, verification includes **reset or cleanup**, so a stale artifact can't produce a false pass next run.

### 4 — One batched question round (the only interruption)
Now — and only now — ask the user. One round, **maximum 5 questions**, via AskUserQuestion when available (numbered list otherwise). A question earns a slot only if a wrong guess would waste real work, money, or live-system state — those get asked. Everything else (design choices with a sensible convention, storage locations, naming) gets baked into the brief as a stated default the user can veto when you present it; don't spend a slot on it. Every question carries a stated default so "defaults are fine" is a complete answer. Draw from, in priority order:

1. **The done bar** — the number that separates done from not-done (how many testers, what accuracy %, which threshold). Propose a specific value, don't ask open-ended.
2. **Destructive gates** — for each delete/send/spend surface: confirm the exact allowed action and the cap ("only hard-invalid leads get deleted, max N; correct?").
3. **Budget caps** — credits, sends, £, API-call ceilings. Propose a cap from the task's scale.
4. **Scope edges** — one thing that plausibly belongs but you suspect is out of scope.

(Training Mode is NOT a question — the boilerplate fixes it ON by default; never spend a slot on it.)

Do NOT ask about anything you verified in step 2, anything with an obvious convention in memory/CLAUDE.md, or naming/formatting. If the raw brief already answers a category, skip it silently.

### 5 — Draft the brief (three lines + verbatim boilerplate)
Fill ONLY the three bracketed lines of the deliverable template at the top of this file. Compression rules:

- **The Task** carries the payload: surfaces (exact paths/ids), the mechanism, every question-round ruling, destructive gates ("style-only — no JS/markup changes"), exclusions ("never touch the iCloud copy"), and the load-bearing gotchas from ground truth (auth walls, deprecated copies, banned approaches). Dense prose, not headings.
- **The Goal** is ONE sentence of user-visible done state.
- **The Verification** is the composite done bar from step 3 — every independent check named concretely (the grep, the audit, the live browser proof), ending with "All N, or it isn't done."
- The boilerplate below The Verification is copied character-for-character. No SKILL.md frontmatter, no Steps section, no Hard don'ts section — those belong to the skill the brief will generate later.

### 6 — Self-review gate before delivering
Re-read the draft as the agent who will receive this brief cold, and check:

- Could I build the loop skill from these three lines without asking the user anything? If not, the missing ruling goes into The Task — fix the brief.
- Is The Verification falsifiable, independent of the system's own success labels, and multi-part where the failure modes are multi-part?
- Would a plausible bug survive The Verification? Walk the top 3 silent-failure paths and confirm the bar catches each. If one survives, add the missing check to The Verification.
- Is the boilerplate untouched, verbatim?

### 7 — Deliver the brief (the brief IS the deliverable)
Output the COMPLETE brief, verbatim, in the final message — Task/Goal/Verification plus the boilerplate, in one copy-paste-ready block. That block is what the user asked for; a summary of it is not a substitute, and **a full SKILL.md is not a substitute either** (the 2026-07-12 mistake: delivering the finished skill file when the user wanted the template brief). Below the block, 2–3 plain-English sentences on what got baked into the three lines, and the offer to run it (which is when the SKILL.md per [references/template.md](references/template.md) actually gets built).

NEVER start executing the loop the brief describes — this skill's job ends when the brief is delivered. Building the brief, building the skill from it, and running the loop are three separate decisions, always the user's.

## Hard don'ts
- Never deliver a SKILL.md-shaped document as the brief. The deliverable is the Task/Goal/Verification template with its boilerplate verbatim — the skill file comes later, only when the user fires the brief (user, 2026-07-12).
- Never reword, trim, or absorb the "Build me ONE Orchestration Skill…" boilerplate. Character-for-character, Training Mode ON by default.
- Never execute the loop the brief describes, and never start "just the first step". The output of this skill is text: the formatted brief, shown in full. Execution happens only when the user fires the brief themselves or explicitly says "run it".
- Never ask more than one question round, and never more than 5 questions. If you're tempted to ask a sixth, the answer belongs in the brief as a stated default the user can veto.
- Never write a done-rule that trusts the system's own success indicator (a "✓ sent" label, a 200 response, a log line saying done). Independent read-back or it doesn't count.
- Never leave a destructive action ungated — every delete/send/spend gets an explicit rule for what is allowed, a cap, and (when Training Mode is ON) an approval pause before it fires.
- Never invent ground truth. Unverified beliefs go into Step 1 of the generated brief as things to prove, clearly marked.
- Never let the brief declare done on a cap-hit — cap-hits are reported as FAILED with the gap, in the generated brief and in this skill alike.
