---
name: gtme-onboarding-sop
description: Orchestration skill that builds and maintains the GTME Onboarding SOP — the video-led field guide that gets a brand-new Go-To-Market Engineer running the Navreo tool for day-to-day client delivery (daily optimisations, daily health checks, launching campaigns, finding prospects already added, adding new prospects, plus the wider Tier 1–4 use-cases). Runs a fixed goal → steps → done-rule loop with a Loop Training Mode toggle (pause-for-approval vs autonomous). Use when asked to build, update, re-score, or ship the GTME onboarding SOP / team handover guide / "the SOP for the tool", or when someone says "run the GTME onboarding SOP loop".
---

# GTME Onboarding SOP

A static, pre-baked loop for taking the team-handover SOP from brief → draft → panel-scored → quiz-passed → shipped. Read it top to bottom once; it does not change between runs.

The SOP itself is **video-led**: short text per task, then a `🎥 VIDEO` placeholder that bullet-points exactly what the recording must show. Words carry the *what & when*; videos carry the *how*. If a section needs paragraphs to be understood, it's too wordy — cut it and let the video do the work.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip this one word to change how the whole loop runs. Default is **ON**.

**When ON (default — training):**
- **Pause at every step.** Do the step, show the result, then STOP and wait for my explicit approval before moving to the next step.
- **Skip any step that already passes its done-rule.** Don't redo finished work — check the done-rule first; if it's already green, say so and move on.
- **Only re-run steps that fail.** If a step's done-rule fails, fix and re-run that step only — not the whole loop.
- **Retry cap: 3.** Max 3 attempts on any one step. After 3 fails, STOP and surface the blocker in plain English. Never loop forever.

**When OFF (autonomous):**
- **No pauses.** Run every step start to finish without waiting for approval.
- **Keep the done-rule checks.** Every step is still gated on its done-rule; a failed done-rule still blocks progress.
- **Keep the retry cap (3).** Same 3-attempts-then-stop rule. Autonomous ≠ infinite.

> To change it later: edit the line above to `→ OFF` (or back to `→ ON`). Nothing else in this file needs touching.

---

## 🎯 Goal

Produce **ONE onboarding SOP** that takes a brand-new GTME — zero prior knowledge of how Navreo works — from "here's the tool" to independently delivering the day-to-day for clients **inside the tool**. It must be skimmable, video-led, and cover every task the team actually does.

**The five must-haves (the spine of the SOP):**
1. **Check daily for campaign optimisations** — Campaigns page + Optimise cockpit.
2. **Daily account-health check** — Analytics page (deliverability, reply/bounce, mailboxes).
3. **Launch a new campaign** — chat → Strategy walkthrough → live, lands on the campaign.
4. **Find prospects you've already added** — Lists page + "have we contacted…?" in chat.
5. **Add new prospects to an existing campaign** — Lists → Sources → Pull More / upload gate.

**Also mandatory:**
- **A one-time Setup section** that has each GTME **pin three daily chats** — `/navreo-inbox` (manage the inbox daily), `/navreo-analytics` (deliverability + account health, high-level), `/navreo-campaigns` (campaign-by-campaign insights daily; recommend making the actual changes in-app) — and states the **chat-OR-website** principle: everything can be done by talking to a chat OR clicking the website, whichever is easier.
- **A standalone Setter section** (its own Part — the AI-SDRs), covering, in order: **1) create an agent (via chat) · 2) train the AI-SDRs · 3) draft responses · 4) add them to automated follow-ups.**

Plus the wider use-case audit (Tier 1–4): build a niche list, size a TAM, write/QA copy, add/swap A/B variants, icebreakers, hiring & engagement signals, recontact, deliverability audit & follow-ups, archive dead angles.

## 🔒 SOP contract (keep / drop — never violate)

**KEEP:** one short "what & when" line per task · a `🎥 VIDEO` placeholder under every task that bullet-points what the video covers · the mental model "**say it in plain English to Claude → the tool is your cockpit where it lands and you action it**" · the **chat-OR-website** principle stated up front · the **Setup step** (pin the three daily chats) · a **standalone Setter Part** (create → train → draft → automated follow-ups) · for each task name the *trigger phrase*, the *page to watch*, and *what good looks like* · plain English a new hire understands · a one-page "cheat-sheet" of trigger phrases at the end.

**DROP:** long paragraphs · skill names / internal jargon / API talk (GTMEs never need them) · anything the video will show better than text · duplicated explanation · screenshots baked into text (that's the video's job).

**FEEL:** a field guide, not a manual. A new GTME should skim the whole thing in one sitting, know which page to open for any task, and know exactly which video to watch to actually do it.

---

## 🪜 Steps (each has its own done-rule — that's what Loop Training Mode gates on)

**1 · Frame.** Confirm the tool's page map (Campaigns · Lists · Analytics · Setter · Settings + the chat-driven Strategy walkthrough and Optimise cockpit) and the task list to cover = the five must-haves + the Tier 1–4 use-case audit. Restate the KEEP/DROP contract for this run.
  - *Done-rule:* page map + full task list named, KEEP/DROP acknowledged in writing.

**2 · Build.** Write / refresh `SOP.md` in this skill folder. Structure: a 60-second "how the tool works" intro → the 5 must-haves as the opening chapters → the wider Tier 1–4 tasks → a trigger-phrase cheat-sheet. Every task = one "what & when" line, a short "do this" (≤5 steps), a `🎥 VIDEO` placeholder bullet-pointing coverage, and (where useful) the trigger phrase + page + "what good looks like".
  - *Done-rule:* SOP.md exists; the **Setup section (three pinned chats + chat-OR-website)** and the **standalone Setter Part (create → train → draft → automated follow-ups)** are both present; every one of the 5 must-haves and every Tier 1–2 task has its own section with a `🎥 VIDEO` placeholder; no section runs longer than its video bullets; no skill names or jargon leak into the GTME-facing text.

**3 · Panel.** Run a panel of **5 simulated brand-new GTMEs** (distinct personas — e.g. ex-SDR, ops-generalist, non-technical career-changer, junior growth marketer, detail-oriented analyst). Each has **just been onboarded, no prior knowledge of how we work, and perfect recall of anything the SOP teaches** (if it's on the page, they remember it). Each scores the SOP **1–10 on ease of understanding**, names their single favourite thing and the one fix to reach a confident 9+.
  - *Done-rule:* all 5 reviewers returned an ease score + the one fix, recorded in the session file.

**4 · Quiz.** Same 5 GTMEs sit a **quiz that tests they can perform the Tier 1 and Tier 2 tasks** using only what the SOP taught (perfect recall assumed). Questions are task-shaped: "a campaign is running dry — what do you do, which page, what does done look like?" Score pass/fail per GTME; a pass = every Tier 1–2 task answered correctly (right trigger, right page, right done-signal).
  - *Done-rule:* all 5 GTMEs pass the quiz. Any wrong answer names the exact SOP gap to fix.

**5 · Polish.** Apply the highest-impact fixes surfaced by the panel + quiz. Re-score and re-quiz only what changed.
  - *Done-rule (THE BAR):* every one of the 5 GTMEs scores **≥ 9/10 on ease of understanding AND passes the quiz**. Below the bar → fix → re-run steps 3–4 (retry cap 3).

**6 · Ship & record.** Finalise `SOP.md`; render a clean, shareable read (Artifact or Notion-ready) so Bjion can drop it into the team's home. Save the session record + update memory (final scores, where it lives, the video shot-list count).
  - *Done-rule:* SOP.md final + shareable version produced; session file + memory written.

---

## ✅ Overall done-rule

Done when the SOP **scores ≥ 9/10 for ease of understanding from all 5 brand-new GTMEs AND all 5 pass the Tier 1 + Tier 2 quiz** — with every one of the five must-haves and the wider use-case audit covered, each task carrying a `🎥 VIDEO` placeholder that bullet-points its coverage, and zero jargon in the GTME-facing text. Anything less is not done; anything past 3 failed attempts on a step stops and reports the blocker.

## 🚦 Release model (staged)
The SOP ships in two Notion surfaces:
- **Full version (WIP, editors):** `Full-Version-Managing-Campaigns` — page `3b06e75598d980b18526dd8d2dadb62a`. Holds **every** task. This is where you edit; it's a child of the staged page (keep it nested — reference it with a `<page>` block on any `replace_content`, or it detaches).
- **Staged release (team-facing):** `Managing-the-Campaigns` — page `3b06e75598d9808eb123ccb991eac61c`. A **trimmed subset**. Wave 1 **excludes**: Launch a new campaign · Write & QA copy · Add icebreakers · Signal campaigns · Housekeeping. (Daily 5 → Daily 4 without Launch; wider toolkit renumbered.) Promote held-back sections here when a wave is approved.

## ⌨️ Command mappings (trigger phrases the GTME actually types)
- **Map a TAM & find/build prospects → `/lilly-tam`** (niche list + verify-DMs-at-companies + TAM sizing).
- **Add/swap A/B versions → `/lilly-bot`.**
- **Build a recontact campaign → `/lilly-recontact`.**
- **Deliverability audit & follow-ups → NOT a chat ask; it's the "Inbox & Domain Manager" section on the Analytics page** (same section the daily health check reads inline).
- Daily chats to pin: `/navreo-inbox`, `/navreo-analytics`, `/navreo-campaigns`.
- These slash-commands ARE user-facing (like the pinned chats) — allowed in GTME text; other internal skill names still are not.

## 🧭 Runbook quick-reference
- Canonical artifact: `~/.claude/skills/gtme-onboarding-sop/SOP.md` (this skill maintains it — the FULL version; the staged page is SOP.md minus the excluded sections).
- Tool page map: **Campaigns** (`campaigns.html`, home/health scoreboard/action cards) · **Lists** (`lists.html`, prospect lists + Sources/Pull-More) · **Analytics** (`deliverability.html`, health + mailbox manager) · **Setter** (`setter.html`, reply inbox) · **Settings**. Chat-driven: **Strategy walkthrough** (`strategy.html`, campaign launch) · **Optimise cockpit** (`optimise.html`, per-campaign optimisation).
- Mental model to teach: GTMEs drive the tool by **plain-English chat**; skills fire behind the scenes (never named to the GTME); the tool page is where results land and get actioned.
- Use-case source of truth: the Notion "Use-case audit" (Tier 1–4). Keep this SOP in sync if that audit changes.
- Persona/quiz rule for the panel: reviewers have **no prior Navreo knowledge** but **never forget what the SOP taught** — so a miss is always an SOP gap, never a memory lapse.
