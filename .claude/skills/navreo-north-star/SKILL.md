---
name: navreo-north-star
description: Navreo's final-goal north star — the yardstick for every change to the signals tool or to Navreo's operational processes. Load this WHENEVER you are building, editing, simplifying, or extending the Navreo signals tool (app/ pages, server.py, campaigns/lists/deliverability/notifications/setter/today surfaces, its Supabase data layer, edge functions, or any of the lilly-* / signals-* skills), OR whenever you are changing how Navreo operates as a company (SOPs, workflows, delivery roles, automations, cron/scheduled tasks, Make scenarios, learning loops). Use it to sanity-check that the work moves toward the autonomous, minimal-human-input outbound platform below. Trigger phrases: 'update the tool', 'change our process', 'add a feature to the signals app', 'new SOP', 'automate this step', 'is this the right thing to build', 'does this fit the goal', 'what are we building toward', 'north star', '/navreo-north-star'.
---

# Navreo North Star 🌟

The single reference for **what Navreo is ultimately building** — apply it to every change to the tool or to company operations.

## The final goal (verbatim)

> A platform that:
> 1. **builds accurate prospect lists** (TAM + decision makers),
> 2. **ideates high-converting offers**,
> 3. **drafts short, concise and relevant copy**,
> 4. **responds to campaign data to optimise campaigns** — with the goal of **driving more meetings**,
> 5. **can self-respond to inbound messages** to a level akin to an expert appointment setter,
> 6. and does **all of this automatically, with minimal human input besides top-line strategy.**

Live tool: https://navreo-signals.onrender.com/app/index.html

## How to use this skill

This is not a build workflow — it is a **decision filter**. When you are about to make (or are asked to make) a change to the Navreo signals tool or to a Navreo operational process:

1. **Name which pillar(s) the change serves** — list-building, offer ideation, copy, optimisation, inbound auto-reply, or the automation/minimal-human-input meta-goal.
2. **Check direction.** Prefer changes that:
   - increase **automation** (less human clicking / babysitting),
   - increase **accuracy** (better lists, better-targeted copy, fewer false positives),
   - drive **more meetings** (the ultimate success metric), and
   - reduce the **human input** required down toward top-line strategy only.
3. **Flag drift.** If a proposed change adds manual steps, human gates, or complexity that does not clearly serve a pillar, say so and propose the more-automated alternative before building.
4. **Keep it lean.** A simpler surface that a non-expert can run unattended beats a powerful one that needs an operator — this directly serves pillar 6.

## The six pillars → where they live today

| # | Pillar | Primary skills / surfaces |
|---|--------|---------------------------|
| 1 | Accurate prospect lists | `lilly-tam`, `lilly-tam(-v2)`, `lilly-ocean-tam-builder`, `lilly-tam`, `lilly-tam`, `lilly-lead-score`, signals Lists tab |
| 2 | High-converting offers | `offer-maker-ship` (/app/offer.html), `lead-magnet-brainstorm`, `lilly-strategy` |
| 3 | Short, relevant copy | `lilly-copywriter`, `lilly-icebreaker(-v2)`, `lilly-personalisation`, `lilly-qa` |
| 4 | Optimise on data → more meetings | `lilly-optimiser`, `lilly-data`, campaigns dashboards, `navreo-learning-loop` |
| 5 | Inbound auto-reply (setter) | Setter tab, `lilly-positive-reply-setup`, reply-categoriser pipeline |
| 6 | Automate w/ minimal human input | scheduled/cron tasks, Make scenarios, the whole autonomous loop tying 1→5 together |

## Guardrail

Every operational-process or tool change at Navreo is a step toward — or away from — this end state. Default to the version that gets us closer to the **autonomous, minimal-human-input platform** above. When in doubt, restate the goal and evaluate the change against it out loud.

Memory anchor: `project_navreo_north_star`.
