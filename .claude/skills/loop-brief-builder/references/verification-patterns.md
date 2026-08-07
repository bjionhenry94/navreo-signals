# Verification pattern library

Mined from the existing loop briefs. Select every pattern that applies to the task — a typical brief uses 4–7. For each selected pattern, the brief must say *where* it lives (which step's done-rule) and *what observation* satisfies it. The design question behind all of them: **how would this fail silently, and what would catch it?**

## Ground-truth patterns

**1. Re-verify ground truth (always Step 1).** Line numbers drift, keys expire, endpoints change. The loop's first act is confirming every Ground-truth bullet against reality. Done-rule shape: "you can name (a) the function that…, (b) the file+line where…, (c) that both keys resolve in the server's env, (d) a captured real API response for one test call."

**2. Prove the API before building on it.** One live request with the real key, captured request/response shape, before any code depends on it. Never guess endpoints in production code — only use shapes proven in Step 1.

## Anti-fake patterns (catch code that lies)

**3. Independent read-back.** Never verify a write through the writer. If the loop pushes leads to Smartlead, the check is *fetching the campaign's leads from Smartlead* and asserting presence — the app's "✓ sent" label is not proof. If it deletes, assert absence.

**4. Numbers-must-match triangulation.** When the same fact lives in ≥2 places (destination tool, activity log, UI), the done-rule is that the numbers match EXACTLY across all of them. Any mismatch = a lying layer.

**5. Grep-negative on removed paths.** When replacing a mock/old path: `grep` for the old symbol returns nothing, AND the old path is not reachable as a silent fallback — if the new thing is down, it fails loudly with the real error.

**6. Browser-verified rendered page (UI work).** The only acceptable done-evidence for UI is the rendered page observed in a browser (screenshot + zero console errors), on the pages it ships to, ideally after a reload mid-state. A grep of deployed JS proves the deploy, not the feature.

## Behaviour-under-fire patterns

**7. Failure-matrix replay.** Enumerate every failure that HAS happened plus every one you can anticipate (missing field, empty array, non-array response, malformed AI output, downstream 500…), then feed each one and assert the system survives. Done-rule: "all N cases run with zero throwing executions and the system still ACTIVE after the full matrix."

**8. Idempotency proof.** Run the same operation twice; assert no duplicate side effects (no second lead, no double-charge). Required whenever a scheduled/daily path can re-fire.

**9. Simulated mixed-ability testers (UX work).** N personas from non-technical to power-user attempt the flow cold, using only the UI. Each yields a transcript, a simplicity score /10, and pass/fail on the core action. Confused personas must actually get stuck, not be rescued. Done bar: average score threshold AND every tester completes.

**10. Real-failure injection.** Force one failure on purpose (kill a key, feed a bad id) and assert the user sees the REAL error, not a fake success or "aborted without reason".

## Blast-radius patterns

**11. Dry-run before destructive.** First pass with `dry_run: true` (or equivalent) proves classification; only then the real action, gated. The dry-run's would-affect list is shown before the real run affects it.

**12. Smallest-blast-radius first.** Run the live proof on the smallest/cheapest real target first (fewest leads, cheapest campaign). If it proves clean, OFFER the rest as a batch — never auto-run the fleet.

**13. Reset between runs.** After each verification pass, remove the test artifacts from live systems so the next pass starts clean — a stale lead makes the next result a false pass. Never skip; resets are part of the done-rule.

**14. Budget ledger.** Hard numeric cap on spend (credits, sends, £). Every spending step debits the ledger; the done-rule includes "ledger ≤ cap".

## Ship patterns

**15. Deploy-verify.** After push: production endpoint returns 200 with expected shape, a marker-grep of the deployed artifact finds the new code, and (this repo) the repo↔iCloud diff for touched files is empty.

**16. Consistency-across-N.** For methodology/accuracy work, one success is luck. The done bar is a rate across a fixed test set ("≥70% on at least 16 of 20 briefs"), with per-case results recorded — FAILED rows count as complete rows.

**17. Survives-navigation/reload.** For anything stateful in a UI: the state survives scrolling away, switching pages, and reloading mid-operation — because it lives server-side, not in the tab.

## Choosing the done bar

Propose specific numbers, then confirm in the question round:
- UX flows: N testers (3 for quick, 10 for thorough), avg simplicity ≥8/10, 100% completion.
- Accuracy/methodology: fixed test set of 20, ≥70% pass, magnitude sanity bands.
- Hardening: failure matrix of everything-that-happened + anticipated, zero throws.
- Pipelines: 1 smallest-real-target end-to-end with triangulated numbers, then offer the batch.
