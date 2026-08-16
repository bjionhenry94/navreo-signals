#!/usr/bin/env python3
"""Unit tests for sync_booked's pure planners — the safety rules live here.

Run:  python app/test_booked_sync.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_booked import plan_categories, plan_pauses, plan_reverse, rank_of  # noqa: E402

CFG = json.loads((Path(__file__).resolve().parent / "booked_sync_clients.json"
                  ).read_text())["amplifyy"]
CLIENT_ID = CFG["smartlead_client_id"]


def row(page_id, status):
    return {"page_id": page_id, "status": status, "status_type": "select"}


def reverse(targets, notion, last_pushed=None):
    wrapped = {e: (v if isinstance(v, tuple) else (v, True)) for e, v in targets.items()}
    return plan_reverse(wrapped, notion, last_pushed or {}, CFG)


def test_reverse_moves_up_the_ladder():
    notion = {
        "a@x.com": row("p1", "Not responded"),      # -> Positive Response
        "b@x.com": row("p2", "Positive Response"),  # -> Meeting-Ready
        "c@x.com": row("p3", "Meeting-Ready"),      # -> Meeting-Booked
        "d@x.com": row("p4", "Positive Response"),  # -> Disqualified (categoriser negative)
        "e@x.com": row("p5", "Not responded"),      # -> Contact in the future
    }
    targets = {"a@x.com": "Positive Response", "b@x.com": "Meeting-Ready",
               "c@x.com": "Meeting-Booked", "d@x.com": "Disqualified",
               "e@x.com": "Contact in the future"}
    updates, creates, unmatched, lower, noops = reverse(targets, notion)
    assert [(u[0], u[4]) for u in updates] == [
        ("a@x.com", "Positive Response"), ("b@x.com", "Meeting-Ready"),
        ("c@x.com", "Meeting-Booked"), ("d@x.com", "Disqualified"),
        ("e@x.com", "Contact in the future")], updates
    assert not unmatched and lower == 0 and noops == 0


def test_reverse_never_moves_down_or_touches_human_tier():
    """Ladder is one-way up: equal-or-lower targets are noops, and the human
    statuses (Called / No-Showed / Call Attended / Paid) are untouchable."""
    notion = {
        "a@x.com": row("p1", "Meeting-Booked"),   # Positive Response is below
        "b@x.com": row("p2", "Meeting-Ready"),    # equal target
        "c@x.com": row("p3", "Paid"),             # human tier
        "d@x.com": row("p4", "Called"),           # human tier
        "e@x.com": row("p5", "Disqualified"),     # Positive Response is below
    }
    targets = {"a@x.com": "Positive Response", "b@x.com": "Meeting-Ready",
               "c@x.com": "Meeting-Booked", "d@x.com": "Meeting-Booked",
               "e@x.com": "Positive Response"}
    updates, creates, unmatched, lower, noops = reverse(targets, notion)
    assert updates == [] and noops == 5, (updates, noops)


def test_reverse_human_downgrade_sticks():
    """We pushed Meeting-Booked once; the human moved the row back down.
    Same evidence must NOT re-push — only genuinely higher evidence would."""
    notion = {"a@x.com": row("p1", "Positive Response")}
    last = {"a@x.com": "Meeting-Booked"}
    updates, _, _, _, noops = reverse({"a@x.com": "Meeting-Booked"}, notion, last)
    assert updates == [] and noops == 1
    # lower prior push + higher new evidence -> fires
    updates2, _, _, _, _ = reverse({"a@x.com": "Meeting-Booked"}, notion,
                                {"a@x.com": "Meeting-Ready"})
    assert [(updates2[0][0], updates2[0][4])] == [("a@x.com", "Meeting-Booked")]


def test_reverse_parked_states_need_a_real_booking():
    """A human-set Disqualified / Contact-in-the-future is terminal against
    reply-category evidence; only an actual booking lifts it."""
    notion = {"a@x.com": row("p1", "Disqualified"),
              "b@x.com": row("p2", "Contact in the future"),
              "c@x.com": row("p3", "Disqualified")}
    targets = {"a@x.com": "Meeting-Ready", "b@x.com": "Positive Response",
               "c@x.com": "Meeting-Booked"}
    updates, _, _, _, noops = reverse(targets, notion)
    assert [(u[0], u[4]) for u in updates] == [("c@x.com", "Meeting-Booked")]
    assert noops == 2


def test_reverse_no_row_leads_split_by_positivity():
    """Positive evidence with no Notion row auto-creates (Bjion ruling); a
    non-positive booked-tier no-row is named unmatched; non-positive lower-tier
    is only counted."""
    targets = {"pos@x.com": ("Meeting-Ready", True),
               "ghost@x.com": ("Meeting-Booked", False),
               "dq@x.com": ("Disqualified", False)}
    updates, creates, unmatched, lower, noops = reverse(targets, {})
    assert creates == [("pos@x.com", "Meeting-Ready")], creates
    assert updates == [] and unmatched == ["ghost@x.com"] and lower == 1


def test_reverse_idempotent_second_pass():
    notion = {"a@x.com": row("p1", "Positive Response")}
    updates, _, _, _, _ = reverse({"a@x.com": "Meeting-Ready"}, notion)
    assert len(updates) == 1
    notion["a@x.com"]["status"] = "Meeting-Ready"      # state after first pass
    last = {"a@x.com": "Meeting-Ready"}
    updates2, _, _, _, noops2 = reverse({"a@x.com": "Meeting-Ready"}, notion, last)
    assert updates2 == [] and noops2 == 1


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
    got = plan_categories(memberships, {2, 3}, 83039, CLIENT_ID, {1, 2, 3}, {})
    assert got == [2], got
    # no reply campaign at all -> no category write (attribution must be real)
    assert plan_categories(memberships, set(), 83039, CLIENT_ID, {1, 2, 3}, {}) == []


def test_categories_never_reassert_over_human_change():
    """We set the target once (recorded); a human then changed it in Smartlead.
    The mismatch alone must not trigger a re-write."""
    memberships = [mem(2, cat=1)]  # live category now Interested
    got = plan_categories(memberships, {2}, 83039, CLIENT_ID, {2}, {"2": 83039})
    assert got == [], got
    # but a NEW target (Notion status advanced) does fire
    got2 = plan_categories(memberships, {2}, 86206, CLIENT_ID, {2}, {"2": 83039})
    assert got2 == [2], got2


def test_ladder_sanity():
    order = ["Not responded", "Positive Response", "Disqualified",
             "Meeting-Ready", "Meeting-Booked", "Called", "Paid"]
    ranks = [rank_of(s, CFG) for s in order]
    assert ranks == sorted(ranks), ranks
    assert rank_of("Contact in the future", CFG) == rank_of("Disqualified", CFG)
    assert rank_of(None, CFG) == -1 and rank_of("garbage", CFG) == -1


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
