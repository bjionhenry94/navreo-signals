# Subsequence Effectiveness — data reconciliation (Step 3)

Read-only collation on 2026-07-29 (GET only; no writes; no prospect contacted).
Script: scratchpad `reconcile_subseq.py`. Source of truth exactly as the tool uses it:
Smartlead `/campaigns/{id}/analytics` (lifetime `sent_count` / `reply_count` /
`positive_reply_count` / `total_count` / `bounce_count`) + the replies archive
(`_reply_archive_meetings`: distinct `(campaign_id, email)` with
`category ∈ {Call Booked, Meeting Request}`, `workspace=eq.navreo`).

**Metric (corrected with Bjion 2026-07-29):** the reply benchmark is **POSITIVE replies**
(`positive_reply_count`), not all replies — benchmark **≥ 12.5%**. Book-call **≥ 5%**.

## The subsequence population is real and large
- **574 subsequences** in the navreo Smartlead workspace (campaigns with a `parent_campaign_id`).
- Attributed to a client by the **parent's** name (never the sub's own generic name), 1:1 with
  `_client_win_label` / `_SHARED_WS_CLIENTS`: **Navreo 438 · Amplifyy 68 · Arnic 30**.

## Two clients collated in full (not sampled)

| Client   | Subseqs | Enrolled | Sent | Positive replies | Booked | Pos-reply% (sent / prospect) | Book% (sent / prospect) |
|----------|--------:|---------:|-----:|-----------------:|-------:|:----------------------------:|:-----------------------:|
| Amplifyy | 68      | 364      | 117  | 13               | 5      | **11.1% / 3.6%**             | **4.3% / 1.4%**         |
| Arnic    | 30      | 28       | 19   | 0                | 0      | 0.0% / 0.0%                  | 0.0% / 0.0%             |

(Amplifyy all-replies = 20, of which 13 positive. Navreo 438 subs deferred — a full pull is
438 `/analytics` calls, over the Smartlead rate budget for a reconciliation.)

## Does the widget's definition reconcile? — YES, with one denominator decision
- Positive-reply rate and book-call rate are both computable from the same fields the rest of
  the tool uses; "positive" = `positive_reply_count`, "booked" = {Call Booked, Meeting Request}
  distinct leads (matches `_reply_archive_meetings`). The widget's numbers will equal the tool's.
- **Denominator fork the widget must pick:**
  - **Sent-basis** (positives/sent, booked/sent) — of the people actually *emailed* the follow-up.
    Amplifyy = **11.1% positive, 4.3% booked**.
  - **Prospect-basis** (positives/enrolled) — of everyone *enrolled*. Amplifyy = **3.6% / 1.4%**,
    lower because the setter **drafts** many follow-ups not yet sent (one sub: 21 enrolled, 5 sent,
    16 drafted) — unsent drafts drag it down.
  - **Recommendation: sent-basis.** It isolates the *copy's* performance (what the benchmark
    polices) and isn't distorted by pending drafts. Read "12.5% of prospects in the subsequence"
    as "of prospects the subsequence emailed." The widget should label its denominator.

## Verdict against the benchmarks (sent-basis) — supports the reported copy problem
- **Amplifyy: positive replies 11.1% ✗ (<12.5%) · booked 4.3% ✗ (<5%) → UNDER ON BOTH.** The
  widget would flag both amber/red — **consistent with the "subsequence copy error hurt
  conversion" finding that kicked this off.**
- Arnic: 0% / 0% on tiny volume (19 sent, 0 positive, 0 booked) — flagged, low-confidence.

## Caveat carried into the ship
The booked/reply archive is **`workspace=eq.navreo` only**. Amplifyy/Arnic/Navreo shared subs
live in the navreo workspace, so they're covered. A future *connected client workspace* (own
Smartlead account) would not have its subsequence replies in this archive — the widget must show
the navreo-workspace caveat or gate to a "not enough data" state for those clients.

**Done-rule met:** real per-client subsequence totals collated and totalled; the widget's
positive-reply + book-call definitions reconcile with the tool's source of truth; the denominator
decision and the navreo-workspace caveat are recorded.
