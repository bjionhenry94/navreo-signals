---
name: lilly-optimizer-campaigns-ship
description: Static orchestration skill that ships the "Lilly Optimizer" cockpit artifact (claude.ai artifact 1c7161d8, title "The cockpit · Navreo daily briefing") as the UI served at /app/campaigns.html on the Navreo signals tool (navreo-signals.onrender.com). The cockpit is a static hydrated page, so the drop-in preserves the current live campaigns console at /app/campaigns-classic.html (nothing lost, fully reversible). Fixed step list, per-step LIVE done-rules, a retry cap, and a Loop Training Mode toggle (ON by default). Use when the user says "ship the Lilly Optimizer to campaigns", "make the cockpit the campaigns page", "push the cockpit artefact as campaigns.html", or "/lilly-optimizer-campaigns-ship".
---

> **SUPERSEDE NOTE (2026-08-02, platform-wide-stabilise):** app/campaigns-classic.html was REMOVED from the repo and live site (it 404s). Any step or done-rule below that expects it to serve/render is historical — skip or adapt it; the campaigns cockpit at app/campaigns.html is the only campaigns page.

# lilly-optimizer-campaigns-ship

Ship the **Lilly Optimizer cockpit** (claude.ai artifact `1c7161d8`, title "The cockpit · Navreo daily briefing") as the UI served at **`/app/campaigns.html`** on the live Navreo signals tool. The current live campaigns console stays reachable at **`/app/campaigns-classic.html`** (drop-in plus fallback, so nothing is lost).

Deploy model: all edits live in the git/Render repo `~/navreo-signals` (branch `main`); Render auto-deploys on push. The iCloud copy is deprecated. Never edit it.

**Ship-and-verify-LIVE law.** The only proof is the live rendered page on `navreo-signals.onrender.com`. A local render, a source grep, or a green label is never done-evidence. Push, let Render redeploy, then verify in a real browser.

---

## ⚙️ LOOP TRAINING MODE  →  **ON**

Flip it by editing this one line:

    LOOP_TRAINING_MODE = ON        # ON = approve every step · OFF = run autonomous

**When ON (default)**
- Pause at the end of **every** step and wait for explicit approval before starting the next.
- Before running a step, check its done-rule first. **If it already passes, skip it** (say so) and move on.
- Only (re-)run steps that fail their done-rule.
- The retry cap still applies. Never loop a step forever.

**When OFF**
- Run all steps autonomously, no pauses.
- Still check every step's done-rule and still honour the retry cap. Report at the end, not between steps.

**Retry cap (both modes):** any single step retries **max 3** times against its LIVE done-rule. On cap-hit: stop that step, record it FAILED with the reason, keep going, surface it in the final report. Never silently exceed.

---

## THE GOAL

On the **live deployed** host: opening `https://navreo-signals.onrender.com/app/campaigns.html` shows the **Lilly Optimizer cockpit** (the "The cockpit · Navreo daily briefing" UI), and the previous live campaigns console is still reachable at `https://navreo-signals.onrender.com/app/campaigns-classic.html`.

Ruling (why the fallback exists): the cockpit is a **static hydrated** page (0 `fetch()`, 0 `/api/` calls), whereas today's `campaigns.html` is a **live console** (60 `fetch()` across ~25 endpoints: sources, leads, drafts, launching, scorecards). A bare drop-in would delete that console, so `campaigns-classic.html` keeps it. Do **not** delete the classic page.

---

## THE STEPS

### Step 0 — Pin the exact artefact source and repo state (blocking gate)
- The source of truth is the **live published artifact `1c7161d8`**. It is private, so WebFetch cannot read its raw bytes. Open it in the user's authenticated Chrome (claude-in-chrome), read what it shows, and match that against the newest local export in the owning session's scratchpad (candidates seen: `.../f8c66187.../cockpit_navreo_0723.html` ~609 KB and `.../83e071eb.../proto6.html` ~391 KB). Pick the file whose content matches the live artifact.
- Confirm `~/navreo-signals` is clean, on `main`, and up to date with `origin/main` (`git fetch` then `git status`).
- Done-rule: you hold **one** artefact HTML file confirmed to match live `1c7161d8`, and the repo is clean on `main`.

### Step 1 — Preserve the current live campaigns console
- In `~/navreo-signals`, copy `app/campaigns.html` to `app/campaigns-classic.html` byte-for-byte. Do not modify it.
- Local pre-check: `diff app/campaigns.html app/campaigns-classic.html` is empty.
- Done-rule (LIVE, confirmed in Step 4): `/app/campaigns-classic.html` serves the old console with its live endpoints intact.

### Step 2 — Build the standalone cockpit page
- The artefact file is an **artifact fragment** (head-type tags, but no `<!doctype>`, `<html>`, or `<body>`). Wrap it in a **standards-mode standalone document** so it renders identically to the published artifact (no quirks mode): prepend `<!doctype html><html lang="en">` with a real `<head>` and `<body>`, and keep the fragment's own `<style>`, content, and `<script>` intact. Write the result to `app/campaigns.html` (overwrite).
- Keep the app auth model: `campaigns.html` stays auth-gated. Do **not** add it to `_AUTH_PUBLIC_GET` in `server.py`.
- Done-rule: `app/campaigns.html` starts with `<!doctype html>`, is a complete document (`<html>...</html>`), and contains the cockpit title ("The cockpit") plus a distinctive cockpit marker.

### Step 3 — Ship it
- Stage **only** `app/campaigns.html` and `app/campaigns-classic.html` (explicit paths, never `git add -A`; confirm no `.env`, `app/data`, or secrets staged). Commit, then `git push origin main`. Render auto-deploys. Wait for the redeploy to finish.
- Done-rule: push succeeds and the Render redeploy completes.

### Step 4 — Verify LIVE in a browser (the required verification)
The app is behind a Supabase login gate, and the in-app Browser pane does not carry the session, so verify in the user's authenticated Chrome (claude-in-chrome):
  1. Open `https://navreo-signals.onrender.com/app/campaigns.html`. Confirm the **cockpit** renders (title "The cockpit · Navreo daily briefing", the list-first campaign view), **not** the old console. Screenshot.
  2. Open `https://navreo-signals.onrender.com/app/campaigns-classic.html`. Confirm the **old console** still renders (fallback intact). Screenshot.
- Done-rule: live `campaigns.html` equals the cockpit **and** live `campaigns-classic.html` equals the old console, both shown in screenshots.

---

## THE VERIFICATION (LIVE on navreo-signals.onrender.com, in a real authenticated browser)

1. `/app/campaigns.html` renders the Lilly Optimizer cockpit (title plus cockpit UI), not the old console.
2. `/app/campaigns-classic.html` still renders the old live campaigns console.
3. Both confirmed by rendered DOM or screenshot in the user's authenticated Chrome, never by a source grep or a local render.

All three, or it isn't done.

---

## ROLLBACK (one line)

Restore the console: `cp app/campaigns-classic.html app/campaigns.html` (or `git revert` the ship commit), push to `main`, let Render redeploy.

## HOW TO RUN

1. Read the mode line above. If **ON** (default): do **Step 0 first**, then work one step at a time and stop for approval after each; skip any step whose LIVE done-rule already passes. If **OFF**: run Step 0, then Steps 1 to 4 in order without pausing.
2. Ship each change to `~/navreo-signals`, push `main`, let Render redeploy, then verify the done-rule against the **live host** in the user's authenticated Chrome. Never accept a local render or a source grep as proof. Retry up to 3x on live-failure, then mark FAILED and continue.
3. Interruptions count as redeploys: re-confirm the live page after any interruption before calling a step done.

## OVERALL DONE-RULE

- Live `/app/campaigns.html` equals the Lilly Optimizer cockpit; live `/app/campaigns-classic.html` equals the preserved old console. Both verified in a real authenticated browser.
- Only `campaigns.html` and `campaigns-classic.html` changed; no secrets or data committed; the auth model is unchanged.
- Final report: one line per step (0 to 4), each DONE / SKIPPED (already passed) / FAILED (with reason), plus the three verification ticks.
