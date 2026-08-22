# Capacity vs Sent — Metric Contract

Authoritative definition of the two series behind "Capacity used %" on the analytics/
deliverability hub, and the invariant that must hold. This is the spec the writer,
the RPC, and the frontend must conform to.

## Canonical key

Every capacity row and every sent row is keyed by **`(client_label, day)`** where:

- **`client_label`** — the workspace slug for connected workspaces, else the shared-
  workspace client label (`_client_win_label`). One label space for both series.
- **`day`** — a **single day boundary for BOTH series**. Chosen boundary =
  **the Smartlead account timezone calendar date** (the timezone `sent` is already
  bucketed in). Capacity, which is currently keyed by UTC `date.today()`, MUST be
  re-keyed to this same boundary. Mixing UTC (capacity) with account-TZ (sent) is a
  contract violation.

## CAPACITY (authoritative)

`capacity(client_label, day)` = the **maximum emails that could have been sent that
day** = Σ over every mailbox that was **attached to that client's campaigns on that
day**, of the mailbox's `message_per_day` **as it stood at the end of that day**
(the highest cap the box was permitted to send at during the day — see "high-water"
rule below). Raw `message_per_day`; warm-up is a separate track and is never added.

- Source of truth: `mailbox_stats_daily.message_per_day` for the historical per-day
  cap; `mailboxes.message_per_day` mirror only for **today**.
- Membership MUST be the roster **as of `day`**, not the current roster. A box that
  sent on `day` but is now detached still counts toward `day`'s capacity.
- **High-water rule:** if the tiering engine lowered a box's cap during the day,
  capacity records the **higher** (pre-cut) cap, because sends already went out under
  it. Capacity is the ceiling that was actually in force while sending, never a
  post-cut number that sits below the day's realized sends.
- Storage: blob `client_capacity_hist_v1` in `deliverability_audit_cache`, per-client
  + pool, ~120 days.

## SENT (authoritative)

`sent(client_label, day)` = Smartlead `day-wise-overall-stats
.email_engagement_metrics.sent`, scoped to that client's campaign-id list, bucketed by
the account-TZ day. Stored in the `client_windows` blob. Same `(client_label, day)`
key as capacity.

## Invariant

    for every (client_label, day):  capacity(client_label, day) >= sent(client_label, day)

- The invariant is a **data-quality guarantee about capacity accuracy**, not a re-write
  of history: it is satisfied by making capacity reflect the true ceiling in force
  (correct day boundary + correct-as-of-day roster + high-water cap), NOT by clamping
  capacity up to sent.
- A genuine over-send (real config allowed more than the intended hard cap) is a
  DIFFERENT event and must remain visible: it is flagged, not hidden, by an explicit
  invariant check that records `(client, day, capacity, sent, excess, reason)`.

## Enforcement point

An invariant check runs after both blobs refresh. For each `(client_label, day)` it
asserts `capacity >= sent`. Any violation is either (a) a capacity-data defect →
recompute per the rules above, or (b) a true over-send → surfaced in the audit with its
root cause. No day silently ships with `sent > capacity`.
