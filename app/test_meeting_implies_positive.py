"""MEETING ⟹ POSITIVE invariant tests (Bjion's standing ruling, 2026-08-04).
A booked meeting IS a positive: no numeric row may ever serve meetings >
positives. Run: python3 app/test_meeting_implies_positive.py"""
import inspect
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1

# 1 — the screenshot case: G has 0 positives, cluster meetings 2 -> raised to 2
versions = [
    {"step": 1, "label": "G", "inline": False, "sent": 581, "replies": 25, "positives": 0, "bounces": 0},
    {"step": 1, "label": "H", "inline": False, "sent": 942, "replies": 27, "positives": 1, "bounces": 0},
]
meetings = {"by_variant": {"1|G": 2}}
raised = server._reconcile_meeting_positive(versions, meetings)
check("G raised to 2 positives", versions[0]["positives"] == 2, versions)
check("G flagged positives_include_booked", versions[0].get("positives_include_booked") is True)
check("H untouched", versions[1]["positives"] == 1 and "positives_include_booked" not in versions[1])
check("one row reconciled", raised == 1, raised)

# 2 — already-satisfied row is never touched (no double count, no lowering)
versions = [{"step": 1, "label": "A", "inline": False, "sent": 100, "replies": 9, "positives": 5, "bounces": 0}]
raised = server._reconcile_meeting_positive(versions, {"by_variant": {"1|A": 3}})
check("positives >= meetings stays as-is", versions[0]["positives"] == 5 and raised == 0)

# 3 — replies ordering: raising positives never leaves positives > replies
versions = [{"step": 2, "label": "B", "inline": False, "sent": 40, "replies": 1, "positives": 0, "bounces": 0}]
server._reconcile_meeting_positive(versions, {"by_variant": {"2|B": 3}})
check("replies raised to keep replies >= positives", versions[0]["replies"] == 3 and versions[0]["positives"] == 3)

# 4 — purged rows render '—', carry no numbers, and are never reconciled
versions = [{"step": 1, "label": "C", "inline": False, "sent": 0, "replies": 0, "positives": 0,
             "bounces": 0, "disabled": True, "stats_purged": True}]
raised = server._reconcile_meeting_positive(versions, {"by_variant": {"1|C": 1}})
check("stats_purged row skipped", versions[0]["positives"] == 0 and raised == 0)

# 5 — inline / unlabeled rows skipped; empty by_variant is a no-op
versions = [{"step": 1, "label": None, "inline": True, "sent": 10, "replies": 0, "positives": 0, "bounces": 0}]
check("inline row skipped", server._reconcile_meeting_positive(versions, {"by_variant": {"1|None": 2}}) == 0)
check("no by_variant -> no-op", server._reconcile_meeting_positive([], {"by_variant": {}}) == 0)
check("bad meetings shape -> no-op", server._reconcile_meeting_positive([], None) == 0)

# 6 — the invariant, property-style: after reconcile NO numeric row violates it
versions = [
    {"step": 1, "label": "A", "inline": False, "sent": 500, "replies": 2, "positives": 0, "bounces": 0},
    {"step": 1, "label": "B", "inline": False, "sent": 500, "replies": 8, "positives": 3, "bounces": 0},
    {"step": 2, "label": "A", "inline": False, "sent": 900, "replies": 12, "positives": 1, "bounces": 0},
]
bv = {"1|A": 4, "1|B": 1, "2|A": 6}
server._reconcile_meeting_positive(versions, {"by_variant": bv})
ok = all((bv.get(str(v["step"]) + "|" + str(v["label"]), 0) <= v["positives"]) for v in versions)
check("invariant holds on every row", ok, versions)

# 7 — the clamp is wired at the fold: _cockpit_messaging must call the
#     reconcile. Deleting the call site is a regression this test catches.
src = inspect.getsource(server._cockpit_messaging)
check("_cockpit_messaging calls _reconcile_meeting_positive", "_reconcile_meeting_positive" in src)

print("FAIL" if _fail else "ALL PASS")
sys.exit(1 if _fail else 0)
