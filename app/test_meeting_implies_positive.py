"""MEETING ⟹ POSITIVE — lead-grain tests under the PARITY RULING (Bjion
2026-08-09, supersedes the 2026-08-04 row-level bump). A booked meeting is a
positive PERSON: the overview meetings tile and the Best-path journey rows
carry that truth. Per-variant positive COUNTERS are Smartlead-verbatim and are
never mutated to satisfy the law — the old bump+rebalance falsified Latka
3710654 (Calendly-synced bookings raised one variant while a sibling's genuine
positive was stripped). Run: python3 app/test_meeting_implies_positive.py"""
import inspect
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server  # noqa: E402

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1

# 1 — lead grain: _booked_meeting_steps counts unique PEOPLE, one per email,
#     so the meetings total equals the overview tile (never reply-row counts).
_orig_sb = server.sb
server.sb = lambda *a, **k: [
    {"id": 1, "email": "kor@x.com", "step": "2", "stepbf": None},
    {"id": 2, "email": "kor@x.com", "step": None, "stepbf": "2"},   # same person, 2nd row
    {"id": 3, "email": "omar@x.com", "step": None, "stepbf": None},  # unattributed step
]
try:
    m = server._booked_meeting_steps(123)
finally:
    server.sb = _orig_sb
check("meetings total = unique bookers", m and m.get("total") == 2, m)
check("stamped step counted once", m and m.get("by_step", {}).get("2") == 1, m)
check("stepless booker lands in unattributed, never a guessed cell",
      m and m.get("unattributed") == 1, m)

# 2 — archive unreachable -> None (UI omits the column), never fake zeros.
server.sb = lambda *a, **k: {"error": "down"}
try:
    check("unreachable archive returns None", server._booked_meeting_steps(123) is None)
finally:
    server.sb = _orig_sb

# 3 — the parity clamp: no code path at the messaging fold mutates positives.
check("row-level reconcile is gone", not hasattr(server, "_reconcile_meeting_positive"))
src = inspect.getsource(server._cockpit_messaging)
check("fold serves Smartlead positives verbatim",
      "_reconcile_meeting_positive" not in src and "positives_include_booked" not in src)
check("the ruling is documented at the fold", "PARITY RULING" in src)

# 4 — REPLY-GRAIN MEETINGS (Bjion 2026-08-09b: "how can it have more meetings
#     than positives"): the Meetings cell shares the Positives cell's grain,
#     so no row can show meetings beside a smaller positives count. Journey
#     credit lives only in Best path; the excess goes to the footnote.
VERSIONS = [
    {"step": 1, "label": "G", "inline": False, "sent": 581, "replies": 25, "positives": 0},
    {"step": 1, "label": "B", "inline": False, "sent": 3848, "replies": 26, "positives": 2},
    {"step": 2, "label": "A", "inline": False, "sent": 20648, "replies": 243, "positives": 9},
]
# two bookers opened on G but replied+booked at Email 2 (their positives are
# in E2-A's 9); one booker has no known step at all
rg, untied = server._meetings_reply_grain(
    VERSIONS,
    {"kor@x.com": "2", "omar@x.com": "2", "ghost@x.com": None},
    {"kor@x.com": {"1": "G", "2": "A"}, "omar@x.com": {"1": "G", "2": "A"}})
check("meetings land on the reply variant, not the opener",
      rg.get("2|A") == 2 and "1|G" not in rg, rg)
check("stepless booking goes to the footnote", untied == 1, untied)
check("no cell breaks meetings<=positives",
      all(rg.get(str(v["step"]) + "|" + str(v["label"]), 0) <= v["positives"] for v in VERSIONS), rg)

# 5 — the clamp: a booking placed on a row whose platform positives can't
#     cover it (Smartlead never counted the booker) moves to the footnote.
rg, untied = server._meetings_reply_grain(
    [{"step": 1, "label": "G", "inline": False, "sent": 581, "replies": 25, "positives": 0}],
    {"kor@x.com": "1"},
    {"kor@x.com": {"1": "G"}})
check("uncovered booking clamps to the footnote", rg == {} and untied == 1, (rg, untied))

# 6 — single-variant step resolves without a path stamp; cap still honoured.
rg, untied = server._meetings_reply_grain(
    [{"step": 2, "label": "A", "inline": False, "sent": 100, "replies": 5, "positives": 1}],
    {"a@x.com": "2", "b@x.com": "2"}, {})
check("single-variant step attributes unambiguously, capped by positives",
      rg.get("2|A") == 1 and untied == 1, (rg, untied))

print("FAIL" if _fail else "ALL PASS")
sys.exit(1 if _fail else 0)
