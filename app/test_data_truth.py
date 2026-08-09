"""Campaign data truth tests (audit 2026-08-09): the numbers every campaign
surface shows must foot to each other and to the platform. Pure python, NO
network — server.sb and build_notifications.sl_get are monkeypatched.
Run: python3 app/test_data_truth.py"""
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
# 2 — Builder journey credit: a booker's positive + meeting land on the
#     Email-1 variant they first saw, not the follow-up bucket — so Section 4
#     can never tell a founder to drop the opener that booked the meetings
#     while the Messaging table beside it crowns the same opener.
# ---------------------------------------------------------------------------
VARIANT_INDEX = {
    101: {"seq_number": 1, "label": "D", "distribution_pct": 33, "is_deleted": False, "angle": "d"},
    100: {"seq_number": 1, "label": "A", "distribution_pct": 34, "is_deleted": False, "angle": "a"},
}
ROWS = [
    # openers sent (no replies on these rows)
    {"seq_variant_id": 101, "lead_email": "kor@x.com"},
    {"seq_variant_id": 101, "lead_email": "omar@x.com"},
    {"seq_variant_id": 100, "lead_email": "jonas@x.com"},
    # jonas replies positively at Email 1 on A — stays reply-grain credit
    {"seq_variant_id": 100, "lead_email": "jonas@x.com", "reply_time": "2026-07-20",
     "lead_category": "Meeting Request"},
    # kor + omar book after Email 2 (null variant id -> "__email2__" bucket)
    {"seq_variant_id": None, "lead_email": "kor@x.com", "reply_time": "2026-07-21",
     "lead_category": "Call Booked"},
    {"seq_variant_id": None, "lead_email": "omar@x.com", "reply_time": "2026-07-22",
     "lead_category": "Call Booked"},
    # a non-booker positive at Email 2 keeps its reply-step credit
    {"seq_variant_id": None, "lead_email": "deborah@x.com", "reply_time": "2026-07-23",
     "lead_category": "Information Request"},
]
_orig_sl_get = bn.sl_get
bn.sl_get = lambda path, params=None: {"data": ROWS, "total_stats": len(ROWS)} \
    if str(params or {}).find("'offset': 0") != -1 or (params or {}).get("offset", 0) == 0 else {"data": []}
try:
    agg = bn.fetch_variant_stats(3649281, VARIANT_INDEX)
finally:
    bn.sl_get = _orig_sl_get
d, e2 = agg.get(101) or {}, agg.get("__email2__") or {}
check("booker positives credited to their opener", d.get("positives") == 2, agg)
check("booker meetings credited to their opener", d.get("meetings") == 2, agg)
check("follow-up bucket keeps only non-booker credit", e2.get("positives") == 1 and e2.get("meetings") == 0, agg)
check("total positives still unique people", sum(a.get("positives", 0) for a in agg.values()) == 4, agg)
check("the drop-the-winner call can no longer fire",
      not (bn.is_failing(1012, d.get("positives", 0)) and d.get("positives", 0) == 0))

# ---------------------------------------------------------------------------
# 3 — Cross-surface foot: reconciled variant rows sum to the same positives
#     total the Overview serves (the 7-vs-5 bug shape, end to end in-memory).
# ---------------------------------------------------------------------------
versions = [
    {"step": 1, "label": "A", "inline": False, "sent": 1022, "replies": 8, "positives": 2, "bounces": 39},
    {"step": 1, "label": "C", "inline": False, "sent": 1018, "replies": 10, "positives": 1, "bounces": 42},
    {"step": 1, "label": "D", "inline": False, "sent": 1012, "replies": 17, "positives": 0, "bounces": 28},
    {"step": 2, "label": "A", "inline": False, "sent": 2149, "replies": 26, "positives": 2, "bounces": 3},
]
meetings = {"by_variant": {"1|D": 2}, "by_step": {"2": 2}, "total": 2}
server._reconcile_meeting_positive(versions, meetings)
table_total = sum(v["positives"] for v in versions)
check("table positives foot to the campaign total (5, not 7)", table_total == 5, versions)
check("no numeric row violates meeting<=positives",
      all((meetings["by_variant"].get(str(v["step"]) + "|" + str(v["label"]), 0) <= v["positives"])
          for v in versions), versions)

print("FAIL" if _fail else "ALL PASS")
sys.exit(1 if _fail else 0)
