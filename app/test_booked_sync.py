#!/usr/bin/env python3
"""Unit tests for sync_booked's pure planners — the safety rules live here.

Run:  python app/test_booked_sync.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_booked import plan_categories, plan_pauses, plan_reverse  # noqa: E402

CFG = {
    "booked_values": ["4. Meeting-Booked", "Call Attended", "Paid"],
    "human_only_values": ["Call Attended", "Paid"],
    "ratchet_target": "4. Meeting-Booked",
}


def row(page_id, status):
    return {"page_id": page_id, "status": status, "status_type": "select"}


def test_reverse_ratchets_below_booked():
    updates, unmatched, noops = plan_reverse(
        {"a@x.com"}, {"a@x.com": row("p1", "2. Responded")}, CFG)
    assert updates == [("a@x.com", "p1", "select", "2. Responded")]
    assert not unmatched and noops == 0


def test_reverse_never_downgrades_booked_tier():
    """Rows already at Meeting-Booked / Call Attended / Paid are untouched —
    the human-owned billing statuses must never be overwritten."""
    notion = {
        "b@x.com": row("p2", "4. Meeting-Booked"),
        "c@x.com": row("p3", "Call Attended"),
        "d@x.com": row("p4", "Paid"),
    }
    updates, unmatched, noops = plan_reverse({"b@x.com", "c@x.com", "d@x.com"}, notion, CFG)
    assert updates == [] and unmatched == [] and noops == 3


def test_reverse_unmatched_is_logged_not_invented():
    updates, unmatched, noops = plan_reverse({"ghost@x.com"}, {}, CFG)
    assert updates == [] and unmatched == ["ghost@x.com"] and noops == 0


def test_reverse_idempotent_second_pass():
    """After the first pass ratchets a row, the same inputs re-run must plan nothing."""
    notion = {"a@x.com": row("p1", "1. Not responded")}
    updates, _, _ = plan_reverse({"a@x.com"}, notion, CFG)
    assert len(updates) == 1
    notion["a@x.com"]["status"] = CFG["ratchet_target"]  # state after first pass
    updates2, _, noops2 = plan_reverse({"a@x.com"}, notion, CFG)
    assert updates2 == [] and noops2 == 1


CLIENT_ID = 429350


def mem(cid, client_id=CLIENT_ID, cat=None):
    """Shape as returned by Smartlead's /leads/?email= lead_campaign_data."""
    return {"campaign_id": cid, "client_id": client_id, "lead_category_id": cat}


def test_pauses_only_sendable_campaigns_of_this_client():
    memberships = [
        mem(1),                        # client campaign, ACTIVE -> pause
        mem(2),                        # client campaign, COMPLETED -> leave
        mem(3),                        # client campaign, ARCHIVED -> leave
        mem(4, client_id=999),         # someone else's campaign -> never touch
        mem(5),                        # client campaign, DRAFTED (could launch) -> pause
        mem(6),                        # client campaign, unknown status -> pause (fail safe)
        mem(7, client_id=None),        # null client_id but in our known set -> pause
        mem(8, client_id=None),        # null client_id, NOT in our set -> leave
    ]
    status = {1: "ACTIVE", 2: "COMPLETED", 3: "ARCHIVED", 4: "ACTIVE", 5: "DRAFTED"}
    got = plan_pauses(memberships, status, CLIENT_ID, {1, 2, 3, 5, 6, 7}, set())
    assert got == [1, 5, 6, 7], got


def test_pauses_second_pass_empty():
    """Campaign status never changes after we pause the lead — idempotence comes
    from the already_paused state, which must suppress the re-pause."""
    memberships = [mem(1)]
    assert plan_pauses(memberships, {1: "ACTIVE"}, CLIENT_ID, {1}, {1}) == []


def test_categories_only_on_real_reply_campaigns():
    memberships = [mem(1), mem(2), mem(3, cat=83039)]
    # replied on 2 and 3; 3 already Call Booked -> only 2 gets the write
    got = plan_categories(memberships, {2, 3}, 83039, CLIENT_ID, {1, 2, 3})
    assert got == [2], got
    # no reply campaign at all -> no category write (attribution must be real)
    assert plan_categories(memberships, set(), 83039, CLIENT_ID, {1, 2, 3}) == []


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
