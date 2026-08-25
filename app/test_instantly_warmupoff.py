"""Unit tests for the Instantly-truth reconciliation of the Not-warming tab.

Imports the LIVE server module and drives the production helper
`_deliv_apply_instantly_warmupoff` (the exact code the bundle refresh calls)
so the assertions cover the real path, not a mirror.

Run:  cd app && python3 test_instantly_warmupoff.py
Exits non-zero on the first failure.
"""
import sys
sys.argv = ["test"]
import server as s  # noqa: E402


def _iwarming(accounts):
    """Rebuild the warming-email set exactly as the bundle loop does."""
    w = set()
    for a in accounts:
        if a.get("warmup_status") == 1:
            w.add(str(a.get("email") or "").lower())
    return w


def case(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        sys.exit(1)


# --- Maildoso: Smartlead says all not-warming; Instantly says 2 warming, 1 off,
#     with mixed-case + duplicate emails on the Instantly side.
out = {"views": {"warmupoff": {"rows": [
    {"email": "bhenry@appliftapps.info"},
    {"email": "B-Henry@AppliftAnalytics.info"},
    {"email": "x@appliftmedia.info"},
]}}, "instantly": {}}
accounts = [
    {"email": "bhenry@appliftapps.info", "warmup_status": 1},
    {"email": "BHenry@AppliftApps.info", "warmup_status": 1},  # duplicate, mixed case
    {"email": "b-henry@appliftanalytics.info", "warmup_status": 1},
    {"email": "x@appliftmedia.info", "warmup_status": 0},      # genuinely off
]
removed = s._deliv_apply_instantly_warmupoff(out, _iwarming(accounts))
kept = [r["email"] for r in out["views"]["warmupoff"]["rows"]]
case("mixed-case+duplicate warming boxes dropped, off box kept",
     removed == 2 and kept == ["x@appliftmedia.info"]
     and out["instantly"]["warmupoffRemoved"] == 2)

# --- Instantly outage: caller passes empty iwarming -> nothing filtered.
out2 = {"views": {"warmupoff": {"rows": [{"email": "a@b.info"}, {"email": "c@d.info"}]}},
        "instantly": {}}
r2 = s._deliv_apply_instantly_warmupoff(out2, set())
case("outage (empty iwarming) leaves rows untouched",
     r2 == 0 and len(out2["views"]["warmupoff"]["rows"]) == 2)

# --- Unmatched: a warmupoff box Instantly has never heard of stays put.
out3 = {"views": {"warmupoff": {"rows": [{"email": "unknown@client.com"}]}},
        "instantly": {}}
r3 = s._deliv_apply_instantly_warmupoff(out3, {"someoneelse@maildoso.info"})
case("box absent from Instantly is not dropped",
     r3 == 0 and out3["views"]["warmupoff"]["rows"][0]["email"] == "unknown@client.com")

# --- Client-workspace safety: rows carry no email match, so even with a warming
#     set they survive (mirrors that _deliv_merge_client_ws appends AFTER this).
out4 = {"views": {"warmupoff": {"rows": [
    {"email": "cw@grout.io", "workspace": "grout"}]}}, "instantly": {}}
r4 = s._deliv_apply_instantly_warmupoff(out4, {"maildosobox@appliftapps.info"})
case("client-workspace row (no Instantly match) survives", r4 == 0)

# --- Missing view: no warmupoff key -> no crash, zero removed.
case("missing warmupoff view is a no-op",
     s._deliv_apply_instantly_warmupoff({"views": {}}, {"x@y.z"}) == 0)

print("\nALL INSTANTLY WARMUPOFF TESTS PASS")
