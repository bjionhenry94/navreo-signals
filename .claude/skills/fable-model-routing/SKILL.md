---
name: fable-model-routing
description: Model-routing policy for sessions running on Fable 5. Fable 5 (the main loop) handles orchestration, planning, logical decisions, and problem solving; all execution work delegated to subagents runs on Sonnet 5. Apply whenever the session model is Fable 5 and you are about to spawn an Agent or Workflow agent() call — set model 'sonnet' for execution tasks, keep Fable for judgment-heavy stages. Trigger phrases: 'model routing', 'which model should the subagent use', or automatically on any Agent/Workflow delegation while running as Fable 5.
---

# Fable 5 Model Routing

## Policy

When the session is running on **Fable 5** (`claude-fable-5`):

1. **Fable 5 = the brain.** Keep orchestration, planning, architectural decisions, trade-off judgments, debugging diagnosis, verification verdicts, and problem solving in the main loop (or in subagents that inherit the session model when the task is genuinely judgment-heavy).
2. **Sonnet 5 = the hands.** Any delegated *execution* task runs on Sonnet 5 by passing the model override explicitly:
   - `Agent` tool: `model: "sonnet"`
   - `Workflow` scripts: `agent(prompt, { model: "sonnet" })`

## What counts as execution (→ Sonnet 5)

- Mechanical code edits from an already-decided plan
- File sweeps, searches, migrations, renames, formatting
- Data processing: CSV cleaning, enrichment loops, API fan-outs
- Running tests / builds and reporting output
- Drafting from a fixed template (briefs, reports whose structure is decided)
- Scraping / fetching / summarising individual sources in a research fan-out

## What stays on Fable 5

- Deciding WHAT to do: strategy, campaign ideation, plan design
- Judge / verify / adversarial-review stages in Workflows
- Root-cause debugging and anything where a wrong conclusion is expensive
- Synthesis steps that merge many subagent results into a decision

## Rules

- This policy applies ONLY when the session model is Fable 5. On other session models, omit `model` and let subagents inherit as usual.
- Never downgrade a verify/judge stage to Sonnet just because it is a subagent — classify by task type, not by delegation.
- In Workflow scripts, it is normal to mix: finder/executor stages `{ model: "sonnet" }`, verifier/judge stages with no override (inherit Fable).
- When genuinely unsure whether a task is execution or judgment, keep it on Fable 5.
