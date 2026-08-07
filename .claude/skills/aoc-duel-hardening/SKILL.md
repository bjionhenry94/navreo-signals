---
name: aoc-duel-hardening
description: Static orchestration skill that makes Age of Conquest duels harder to beat by mining Bjion's own exported game records, rebuilding each of his winning tactics as a faithful mimic bot, and hardening the duel AI (skill/structure only, never stat bonuses) until every mimic is beaten 80-100% of the time — while honest skilled play stays winnable and duels still resolve. One fixed step list, checkable done-rules, retry cap, Loop Training Mode toggle (ON by default). Use when the user says "harden the duel AI", "study my games and defend them", "make the duel harder", "train the computer to beat my tactics", or "/aoc-duel-hardening".
---

# Age of Conquest: Duel Hardening Loop

## ⚙ Loop Training Mode: **OFF**   ← flip this line to ON to pause at every step

**ON (default):** pause at EVERY step boundary and wait for the user's explicit approval
before continuing. Before starting a step, check its done-rule FIRST — if it already
passes, report "Step N already passes, skipping" and move to the next pause. Only re-run
steps whose done-rule fails. Show what you're about to do before doing it.

**OFF:** run all steps end-to-end with no pauses. The done-rule checks, skip-if-passing
behaviour, and retry caps stay exactly the same — only the pauses go.

**Retry cap (both modes):** each step retries **max 3** times against its done-rule.
On cap-hit: record the step as FAILED with the reason, continue to the next step if it
doesn't depend on the failed one, and surface every FAILED step in the final report.
Never silently exceed the cap. Never declare the skill done on a cap-hit.

## Goal

Bjion beats the duel with the same handful of tactics every time. Make the computer
defend them.

**Done when:** every mimic bot rebuilt from his real game records is **beaten 80-100%
of the time** (each bot wins ≤20% over ≥20 paired seeds per map size), AND all three
guard-rails below still hold. Harder to beat — not impossible, not a stalemate machine.

**Guard-rails (equal weight to the goal — a win that breaks these is a FAIL):**
1. **Still winnable by legit skill.** The honest-play proxy (below) wins ≥15%.
2. **Duels still resolve.** ≥70% of duels finish inside 200 turns.
3. **Other modes untouched.** Sandbox/survival/laststand/blitz behave as before.

## Ground truth (verified to v=152 — re-verify in Step 1, versions drift)

- Game: `~/Library/Mobile Documents/com~apple~CloudDocs/Bjion [2023]/Navreo/Claude/Navreo/age-of-conquest/`
  Plain JS, no build. `js/ai.js` (all AI), `js/game.js` (engine, MODES, combat,
  `captureProvince`, `defenseMods`), `js/recorder.js` (game recorder).
- **Run it:** `preview_start` name `age-of-conquest` (port 4173), then drive sims with
  `preview_eval`. Never open the game with Bash.
- **Cache-bust:** 8 `?v=N` refs in `index.html`. Bump with
  `sed -i '' 's/?v=152/?v=153/g' index.html`, then reload — the browser caches by URL.
- **Records:** `~/Downloads/aoc-games*.json` (highest number = newest). Same shape as
  `localStorage.aoc_games`. Each game has `mode/size/difficulty/seed`, `moves[]`,
  per-turn `turns[]`, and a `fingerprint` (`meanFrontPct`, `singleAxisFocus`,
  `breakthroughTurn`, `peakFronts`, `peakShare`). In-page helpers: `aocGames()`,
  `aocStrategySummary()`, `aocClearGames()`, `aocExportGames()`.
- **Live AI knobs:** `window.DUEL_TUNE = {keep, strike, send, antMargin, comeback,
  cbCap, skillFloor, intel}` — read fresh each turn by `duelTune()`, so a sim can sweep
  them without an edit/reload cycle. Bake winners in as the defaults afterwards.
- **The `master` gate:** grandmaster behaviour (lateral line-stripping, riding a
  breakthrough, axis relocation, convergent assault, intel dossier, threshold wobble)
  is gated on `master = totalWar && n.duelistFloor !== false`. A human proxy must set
  `n.duelistFloor = false` — it plays those moves by hand, so leaving it on
  double-counts and silently inverts the result.
- **Already shipped (don't re-invent, do re-verify):** anticipation w/ 3-hop deep read
  + anomaly gate, counter-punch on `unrest>0` retakes, anti-bait storm-cost, palace
  guard + raider watch, realm integrity (king flees one step, cornered = realm falls),
  punish-the-pool, patience timer, convergent assault, oddsFloor wobble.

## The measurement harness (use this exact shape — the numbers are worthless otherwise)

```js
// paired seeds: identical maps across configs, or the noise buries every signal
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);
  t=t+Math.imul(t^t>>>7,61|t)^t;return ((t^t>>>14)>>>0)/4294967296;};}
const real = Math.random; Math.random = mulberry32(BASE_SEED + s*7919);
newGame({mode:'duel', size, difficulty:'nightmare'});
// ... bot plays nation 0 via doMove(), then endTurn() ...
Math.random = real;                       // ALWAYS restore
```

- **Honest-play proxy** (guard-rail 1): run the AI's own logic as the player at reduced
  skill — `G.nations[0].anticipate=false; G.nations[0].duelistFloor=false;` then each
  turn `DIFF=Object.assign({},baseDiff,{skill:0.75}); G.nations[0].isPlayer=false;
  aiTurn(0); G.nations[0].isPlayer=true; DIFF=baseDiff; endTurn();`
  Hand-coded heuristic bots are NOT a competent-player proxy — they measure ~0-7% and
  will fool you into thinking the AI is unbeatable.
- **Storage discipline:** snapshot `localStorage.aoc_games`, run, restore. Sim games
  must never pollute the user's real records (the intel dossier reads them).

## Steps

### Step 1 — Harvest the win-plans from the real records
Read the newest `~/Downloads/aoc-games*.json`. For every WON duel, extract the tactic
from the data, not from memory: opening move pattern (`moves[]` turns 1-8), where troops
pooled (`frontPct`, and whether the staging province was on the border or behind it),
`breakthroughTurn`, `singleAxisFocus`, province-count trajectory, and whether the player
ever LOST ground. Cluster into a named win-plan list. Cross-check against the tactics the
user has stated in his own words (mass-and-roll, stealth staging one-to-three provinces
back, threshold camping under the AI's attack bar, exploiting no-collusion, capital
snipe, kamikaze fort-bait). Record which build (`v` field) each game was played on —
tactics beaten on an older build may already be dead.
- **Done-rule:** a written list of ≥4 named win-plans, each with the concrete signature
  that identifies it in the data (turn window, pooling location, breakthrough turn,
  axis focus) and the game(s) it came from.

### Step 2 — Rebuild each win-plan as a mimic bot
One JS bot function per win-plan, playing nation 0, faithful to the record's signature
(same pooling depth, same patience window, same lunge trigger, same target choice). A
bot is faithful when replaying it produces a fingerprint in the same neighbourhood as
the real game (`meanFrontPct` ±15, similar `breakthroughTurn` band). Keep them in one
scratch harness file so later steps re-run them unchanged.
- **Done-rule:** every win-plan from Step 1 has a runnable bot; each bot's replayed
  fingerprint lands in the same band as the game it mimics; the suite runs end-to-end
  on both `medium` and `large` without console errors.

### Step 3 — Baseline: which tactics still win?
Run every bot vs the current AI, ≥20 paired seeds per size, `difficulty:'nightmare'`.
Load the user's REAL records into `localStorage.aoc_games` first so the intel dossier
sees the same history it would in his games — that is the honest test. Report a table:
bot × size → win %, mean win turn, provinces lost during the pooling window. Also record
the three guard-rail baselines.
- **Done-rule:** a win-rate table covering every bot × both sizes, plus current
  guard-rail numbers (honest-proxy win %, duel resolution %, and a sandbox smoke).
  Any bot ≤20% is already defended — mark it PASS and leave it alone.

### Step 4 — Diagnose and patch (skill only), one failing bot at a time
For each bot still winning >20%, take the WORST offender first. Trace one full game and
find the actual mechanism it exploits (print per-turn province/troop counts and the AI's
responses — do NOT theorise from the code alone; every prior misdiagnosis in this project
came from skipping the trace). Then patch `js/ai.js` (or `js/game.js` for a genuine rule
gap) so the AI *out-plays* it: better board reading, better concentration, better timing,
better coordination. Prefer a `DUEL_TUNE` sweep to find the right value before baking it
in. Re-run that bot after each patch.
- **Done-rule:** the targeted bot is ≤20% on both sizes, the trace that motivated the
  patch is recorded, and no previously-passing bot regressed above 20%.

### Step 5 — Full re-verify (the real done-rule)
Re-run the WHOLE suite plus all three guard-rails on fresh seed sets (different base
seeds from Step 3 — a fix tuned into one seed set proves nothing).
- **Done-rule:** every bot ≤20% on both sizes (aggregate ≤20%), honest proxy ≥15%,
  duel resolution ≥70%, sandbox/survival smoke clean, zero console errors. Any miss
  sends you back to Step 4 (within the retry cap).

### Step 6 — Ship and record
Bump `?v=`, reload, browser-verify a real duel starts and plays (screenshot). Append a
paragraph to `project_age_of_conquest_game.md` in this project's memory dir
(`~/.claude/projects/-Users-bjionhenry-Library-Mobile-Documents-com-apple-CloudDocs-Bjion--2023--Navreo-Claude-Navreo/memory/`)
— it's one long paragraph-per-version log, so append with a heredoc, never rewrite it:
new version, each win-plan and how it's now defended, the final table, and any knob
whose default changed. Tell the user which of HIS tactics are now dead and what the
honest path to a win looks like.
- **Done-rule:** new version live in the browser with no console errors, memory
  paragraph appended, and a plain-English summary delivered naming each defeated tactic.

## Final report (always, both modes)
Steps passed/skipped/FAILED; the win-rate table before → after per bot per size; the
three guard-rail numbers; every AI change made (file + what it reads, not just what it
does); knob defaults changed; anything deferred.

## Hard don'ts
- **Never give the AI stat bonuses.** No extra income, combat multipliers, cheaper
  recruits/forts, or vision the player lacks. Skill, structure and coordination ONLY —
  this is the user's standing rule across the whole project. Symmetric structural
  changes (both realms) are fine.
- Never measure with hand-coded heuristic bots as the "competent player" — use the
  aiTurn-at-reduced-skill proxy for guard-rail 1.
- Never leave `duelistFloor` unset on a player proxy (it hands the proxy the AI's
  grandmaster kit and inverts the measurement).
- Never compare configs on unpaired seeds, and never conclude from N<20 — duel variance
  is huge; a 30-point swing between seed sets is normal.
- Never leave sim games in `localStorage.aoc_games`; always snapshot and restore.
- Never let a fix push duel resolution below 70% (the anti-snowball brake has stalemated
  this game twice) or leak into non-duel modes (gate on `totalWar`/`master`).
- Never patch from a code reading alone — trace a real losing game first.
- Never exceed a retry cap or report done while any done-rule or guard-rail fails.
