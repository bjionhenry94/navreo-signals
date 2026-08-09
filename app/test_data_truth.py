"""Campaign data truth tests — PARITY RULING (Bjion 2026-08-09): per-variant
positives are served exactly as Smartlead reports them, never raised for booked
meetings and never subtracted to rebalance; meetings are attributed only with
evidence (archive vpath stamps) and booked-journey variants are never called
losers. Pure python, NO network — server.sb and build_notifications.sb/sl_get
are monkeypatched. Run: python3 app/test_data_truth.py"""
import inspect
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server  # noqa: E402
import build_notifications as bn  # noqa: E402

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1


# ---------------------------------------------------------------------------
# 1 — Best-path zero-fill never fabricates a journey through a deleted-only
#     copy cluster (the "B→A" ghost row: opener B deleted, zero sends).
# ---------------------------------------------------------------------------
SEQS = [
    {"seq_number": 1, "sequence_variants": [
        {"variant_label": "A", "is_deleted": False,
         "email_body": "quick one about growing outbound pipeline with a small focused team this quarter"},
        {"variant_label": "B", "is_deleted": True,
         "email_body": "completely different angle here про booking sales calls through cold video walkthroughs instead"},
    ]},
    {"seq_number": 2, "sequence_variants": [
        {"variant_label": "A", "is_deleted": False,
         "email_body": "just floating this back up in case the timing works better for you now"},
    ]},
]
_orig_sb = server.sb
server.sb = lambda *a, **k: []  # empty archive: paths come from zero-fill only
try:
    vp = server._variant_paths(999999, seqs=SEQS)
finally:
    server.sb = _orig_sb
pk = set((vp or {}).get("paths") or {})
check("live opener journey zero-filled", "A>A" in pk, pk)
check("deleted-only opener gets NO ghost row", not any(k.startswith("B>") for k in pk), pk)

# ---------------------------------------------------------------------------
# 2 — PARITY: the messaging fold contains no positive-count mutation. The
#     2026-08-04 bump and the 2026-08-09 subtraction are both gone; deleting
#     this guarantee (or reintroducing a reconcile at the fold) is the
#     regression these checks catch.
# ---------------------------------------------------------------------------
check("_reconcile_meeting_positive is deleted",
      not hasattr(server, "_reconcile_meeting_positive"))
src = inspect.getsource(server._cockpit_messaging)
check("_cockpit_messaging never rewrites positives",
      "positives_include_booked" not in src and 'v["positives"] =' not in src
      and "_reconcile_meeting_positive" not in src)

# ---------------------------------------------------------------------------
# 3 — Builder parity: fetch_variant_stats keeps counts at Smartlead's grain.
#     A booker who replied at Email 2 counts there, NOT on their opener —
#     the Latka corruption started with exactly this move.
# ---------------------------------------------------------------------------
ROWS = [
    {"seq_variant_id": 101, "lead_email": "kor@x.com"},
    {"seq_variant_id": 100, "lead_email": "jonas@x.com"},
    {"seq_variant_id": 100, "lead_email": "jonas@x.com", "reply_time": "2026-07-20",
     "lead_category": "Meeting Request"},
    {"seq_variant_id": None, "lead_email": "kor@x.com", "reply_time": "2026-07-21",
     "lead_category": "Call Booked"},
]
_orig_sl_get = bn.sl_get
bn.sl_get = lambda path, params=None: (
    {"data": ROWS, "total_stats": len(ROWS)} if (params or {}).get("offset", 0) == 0
    else {"data": []})
try:
    agg = bn.fetch_variant_stats(3710654)
finally:
    bn.sl_get = _orig_sl_get
check("booker counts at the step they replied (parity)",
      (agg.get("__email2__") or {}).get("positives") == 1
      and (agg.get(101) or {}).get("positives", 0) == 0, agg)
check("non-booker positive stays at its reply row",
      (agg.get(100) or {}).get("positives") == 1, agg)

# ---------------------------------------------------------------------------
# 4 — Booked-journey evidence: vpath stamps parse into (step, label) pairs;
#     unstamped/exhausted rows contribute nothing.
# ---------------------------------------------------------------------------
_orig_bn_sb = bn.sb
bn.sb = lambda *a, **k: [
    {"vp": '{"1": "D", "_x": ["2"]}'},
    {"vp": None},
    {"vp": "not json"},
]
try:
    bj = bn.fetch_booked_journey_labels(3649281)
finally:
    bn.sb = _orig_bn_sb
check("stamps parse to (step,label) evidence", bj == {("1", "D")}, bj)

# ---------------------------------------------------------------------------
# 5 — Drop guard: a booked-journey opener at 0 Smartlead positives is never
#     flagged failing in the receipts; a genuinely dry sibling still is.
# ---------------------------------------------------------------------------
ctx = {
    "variant_stats": {
        7057838: {"sent": 1012, "positives": 0, "replies": 17, "meetings": 0},
        7057837: {"sent": 1018, "positives": 0, "replies": 10, "meetings": 0},
    },
    "variant_index": {
        7057838: {"seq_number": 1, "label": "D", "distribution_pct": 33,
                  "is_deleted": False, "angle": "d"},
        7057837: {"seq_number": 1, "label": "C", "distribution_pct": 33,
                  "is_deleted": False, "angle": "c"},
    },
    "booked_journeys": {("1", "D")},
}
vl = {v["variant"]: v for v in bn.build_variants_list(ctx)}
check("booked-journey variant never flagged failing",
      "failing" not in (vl.get("D") or {}).get("flags", []), vl)
check("dry sibling still flagged failing",
      "failing" in (vl.get("C") or {}).get("flags", []), vl)

print("FAIL" if _fail else "ALL PASS")
sys.exit(1 if _fail else 0)
