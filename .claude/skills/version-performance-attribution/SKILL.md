---
name: version-performance-attribution
description: Make the Version-performance table's per-variant meetings AND best-combination table FULLY FUNCTIONAL and LIVE across the whole platform — every reported meeting traced to the variant(s) the booker actually saw wherever the data allows, and a best-combination table on every campaign whose follow-up varies. The variant a lead was sent is deduced from the copy they quote back in their reply (stored in Supabase) matched to the variant bodies (raw Smartlead /sequences, incl disabled), with a message-history fallback for bookers who didn't quote. Audits attribution coverage across every meeting-bearing campaign, closes the coverage leaks, and proves it with at least 10 live authenticated-browser checks. Use when the user says "fix the meetings-per-variant", "why can't I see meetings per variant / the best combination", "make the attribution work for all campaigns", or "/version-performance-attribution".
---

# Version Performance — Meeting Attribution 🎯

> ## ⚙️ LOOP TRAINING MODE  =  **ON**   (default)
> Flip this one line to `OFF` to run autonomously with no pauses. Nothing else changes.
>
> | Mode | Behaviour |
> |------|-----------|
> | **ON** (default) | Pause at **every step** and wait for the user's approval before continuing. **Skip** any step that already passes its done-rule. Only **re-run** steps that fail. Respect the retry cap. |
> | **OFF** | Run **autonomously**, no pauses. Still enforce **every done-rule** and the **retry cap**. |
>
> **Retry cap:** each step may be attempted at most **3 times**. On the 3rd failure, STOP and report the blocker — never loop forever.

---

## The Goal
On `campaigns.html` (Messaging tab, the **Version performance** section), make it TRUE that:
1. Every meeting the campaign reports can be **traced to the variant(s) the booker saw** — shown per variant row (Meetings + Sent/meeting), wherever the data can prove it.
2. A **Best-combination table** (opener → follow-up, sent counts both emails) appears on **every** campaign whose follow-up genuinely varies.
3. It is **live on the tool** (deployed + verified in a real authenticated browser), not a mockup.

The variant a lead received is recovered by matching the sent copy the lead **quotes back in their reply** (in the Supabase `replies` archive) against the variant bodies from the raw Smartlead `/campaigns/{id}/sequences` (which includes disabled/deleted variants). This already works (`_variant_paths` in `server.py`). This skill's job is to **close the coverage leaks** and **prove it everywhere**.

## LOCKED — never break these
- **Never fake an attribution.** A meeting is credited to a variant ONLY when the copy the booker quoted (or their fetched sent email) matches that variant's copy. No proportional guessing, no defaulting.
- **Honest remainder.** A meeting that genuinely can't be traced — the booker left no quotable/fetchable trace, or two variants share **identical** copy (nothing to tell apart) — stays **unattributed and labelled with the reason** in the footnote. This is a correct outcome, not a bug.
- **Combinations only where the follow-up varies.** When Email 2+ is a single inline step, there is nothing to combine — the table is correctly absent. Never invent a combination.
- **Every number is live/real** (Smartlead variant-statistics + the Supabase reply archive). Disabled variants stay in, flagged.

## The Done-Rule (single source of truth)
1. **Coverage maximised.** After the fix, every booker who left ANY recoverable trace of the copy they were sent (quoted in their reply OR present in their Smartlead message-history) is attributed. The only unattributed meetings are (a) genuinely traceless or (b) identical-copy variants — and each is counted + named in the audit.
2. **Combinations everywhere applicable.** The best-combination table renders on every campaign whose follow-up has a real (labelled) variant; absent only where the follow-up is a lone inline step.
3. **Live, and the render equals the data.** For every checked campaign, the DOM the browser shows == the `/api/cockpit/messaging` payload (per-variant Meetings, combinations, footnote counts all match).
4. **≥10 live authenticated-browser checks pass**, spanning diverse shapes (see Step 5). Each recorded with campaign id + what was seen.
5. **Nothing faked** (LOCKED intact).
The loop is DONE only when all five hold.

---

## Steps (each has its own done-rule; skip if already passing)

**Step 1 — Audit the background, platform-wide.**
Run the deduction (`/api/cockpit/messaging`) against **every meeting-bearing campaign** (find them: `replies` where `category=Call Booked`, group by `smartlead_campaign_id`). For each, record: total meetings, attributed, unattributed, and the **reason** per shortfall — booker's reply didn't quote the step / the step's variants share identical copy / a deleted variant's body is missing from `/sequences`. Note whether the follow-up varies (should have combos) and whether combos are present.
_Done-rule:_ a written coverage table across all meeting-bearing campaigns — attributed-vs-total per campaign, the leak reason for every shortfall, and the combos-expected-vs-present flag.

**Step 2 — Close the coverage leaks (`_variant_paths` in `server.py`).**
- **Message-history fallback:** for a booked lead whose reply doesn't quote a step, fetch that lead's Smartlead `message-history` (the SENT items carry the actual sent `email_body`) and match THAT to the variant copy. Bounded per call + cached back onto the reply row so a lookup never repeats.
- **Deleted-copy recovery:** where a deleted variant's body is absent from `/sequences`, recover its copy by clustering the distinct sent-copies quoted across the campaign's replies (Supabase), so bookers of a purged variant still resolve to a distinct cluster.
- Keep it defensive: any failure leaves today's result; never break the tab.
_Done-rule:_ re-running Step 1's audit shows every booker with a recoverable trace now attributed; the only remaining unattributed are traceless or identical-copy, each still counted.

**Step 3 — Combinations on every applicable campaign.**
Confirm the payload's `combinations` is non-empty for every campaign whose follow-up varies (≥1 labelled Email-2+ variant) and stays empty only for lone-inline follow-ups.
_Done-rule:_ combos present on every follow-up-varies campaign in the audit; absent only where genuinely nothing to combine.

**Step 4 — Frontend equals data.**
The version table shows per-variant Meetings + Sent/meeting on each variant row (from `meetings.by_variant`); the combinations table shows opener→follow-up with Sent (both emails) + Meetings + Sent/meeting; the footnote states attributed-vs-total honestly; on/off dots correct (green active, grey off). For one sampled campaign, the rendered DOM numbers must equal the payload exactly.
_Done-rule:_ DOM == payload for a sampled campaign (per-variant meetings, combos, footnote).

**Step 5 — Deploy + ≥10 live authenticated-browser checks.**
Deploy (push to `main` → Render; confirm `/api/version` shows the new commit). Then, in a **real authenticated browser**, load the Messaging tab of **≥10 campaigns** chosen to span the shapes: inline-only follow-up, single follow-up variant, multi follow-up variant, all-disabled openers, identical-copy openers, high-meeting, low-meeting, and at least two where combinations must appear. For each: per-variant Meetings render and sum sensibly; combinations render where applicable; the DOM numbers equal the `/api/cockpit/messaging` payload; the unattributed remainder is honestly labelled.
_Done-rule:_ ≥10 checks recorded (campaign id + pass/fail + what was seen); all pass.

**Step 6 — Hand over.**
Report coverage **before vs after** (platform attribution rate), the 10 checks, and every campaign where attribution is honestly capped by identical copy or traceless bookers (named). Nothing is "done" until Step 5 holds.
_Done-rule:_ before/after coverage stated; ≥10 checks all green; honesty caveats named; Done-Rule (1–5) confirmed.

---

## Loop control (how the modes actually run)
```
for step in 1..6:
    if step already passes its done-rule:  SKIP
    else:
        attempt = 0
        while not done-rule and attempt < 3:
            attempt += 1
            do the step
            if TRAINING MODE == ON:  pause → wait for approval
        if still not passing after 3 attempts:  STOP + report blocker
```
Global finish = **every meeting with a recoverable trace is attributed, combinations render on every follow-up-varies campaign, the live render equals the data, ≥10 live browser checks pass, and nothing is faked.** Never declare done otherwise.
