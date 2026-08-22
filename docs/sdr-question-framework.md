# SDR training — better-questions framework

Goal: ask better between-round questions so a business owner trains an AI-SDR to the pass mark **fast and correct**. Better questions = faster training = happier customer. Built and measured 2026-08-21 by simulating a business owner training in the live wizard across 5 use-case archetypes.

## What "a good question" is (the rules)

1. **Ask only for missing FACTS that change how the SDR answers** — a number, policy, stance, link, or resource. Never the reply itself.
2. **WHAT, never HOW** — no wording ("what one-sentence reply should it send"), no tone/voice/formality/length.
3. **Common, not edge** — target the ~90% most common prospect questions (what it is / what's included, price, proof, how it works + book, the one differentiator, timeline). Skip edge cases (niche compliance, obscure legal/PO terms, rare sector assets) — the 1-in-10 test: if fewer than 1 in 10 prospects would ask it, don't ask the owner.
4. **No disqualification, no internal-ops** — never "who is it NOT for / who to close on", and never reply-SLA, working hours, or post-booking logistics. The SDR answers prospects and books calls; it isn't interviewed on back-office.
5. **No wording, no repeats** — return only genuinely new questions (0–5); when the offer is covered, END rather than pad with repeats.

## The per-use-case question playbook (verified, WHAT-focused)

Every archetype converges on the same ~8 slots — this IS the framework:

| Slot | Question shape |
|------|----------------|
| Booking | The exact booking/scheduling URL to send. |
| Pricing policy | The price/range/model, and whether a number may be shared before a call. |
| Proof | The case-study / results link to send. |
| What's included | What the offer is and what a prospect gets. |
| How it works / first call | Plain how-it-works and what the first call covers. |
| The one differentiator | The single fact for "why you" / "we already do this" / "too expensive". |
| Timeline | How long it takes / how soon they see results. |
| Getting-started essentials | The 1–2 offer-specific must-knows (e.g. free-trial terms, equipment, fee timing, collateral). |

(Concrete sets for SaaS, agency/service, recruiting, coaching, fintech are in the session record; they all map to these slots.)

## Measured training experience (3 use-cases, live wizard)

| Use-case | Rounds to 90+ | Ratings | Est. owner time |
|----------|---------------|---------|-----------------|
| SaaS analytics | 4 | 21 | ~8.0 min |
| Web-design agency | 4 | 21 | ~7.1 min |
| Recruiting | 4 | 28 | ~9.4 min |

- **Time-to-pass: PASS** — all under the 15-minute bar.
- **Readiness math:** `score = 100 × (0.6·decision + 0.4·reply) × min(1, n/20)` → ~18–20 *correct* ratings reach 90. Good questions → accurate brain → drafts rated Correct → 90 in fewer ratings.
- Interview questions are asked WHILE the next round builds, so they fill the ~32s generation wait instead of adding to it. Fewer/better questions keep that wait filled without dragging.

## Two setup rules the questions CANNOT fix (learned the hard way)

1. **Scenarios must be built from the offer's OWN outreach.** Training scenarios come from `training_outreach` (or the agent's real campaigns). If those don't match the offer, drafts blend offers no matter how good the questions are.
2. **Build a new client's SDR FRESH — never clone another client's agent.** A clone inherits the source client's `memory`, `voice_examples`, `instruction_edits`, `feedback_log`, and reply corpus, and the drafter uses all of it — so a recruiting SDR cloned from a cloud-cost client will talk about "savings we'd find" and "read-only assessments". Cloning is safe ONLY for the SAME client's new campaign set. For a NEW client: new agent, own instructions, own campaigns/`training_outreach`, empty memory. (See the lilly-appointment-setter skill's duplicate guardrail.)

## Verdict

Faster training and question quality are proven (≤15 min, clean WHAT questions). Correctness-at-100 must be re-verified on **fresh, isolated** agents (the simulation used cloned dummies, which contaminated drafts). The clone-across-clients contamination is itself the top fatal bug to close before onboarding a new client by duplication.
