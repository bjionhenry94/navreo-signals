"""Regression lock for Step 4 (signals-launch-hardening): push must be
idempotent, respect client suppression, and never stamp a failed/suppressed
push as sent. Deterministic — providers and the suppression RPC are stubbed.

Run:  python3 app/test_push_reliability.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILS.append(name)


# stub the outbound provider calls so nothing hits the network
SL_CALLS = {"n": 0}


def fake_smartlead(pr, cid):
    SL_CALLS["n"] += 1
    return {"ok": True, "message": "added"}


server.push_to_smartlead = fake_smartlead
server.push_to_heyreach = lambda pr, lid: {"ok": True, "message": "added"}
server.find_email = lambda pr: pr.get("email")  # email present -> smartlead route
server.heyreach_lists = lambda refresh=False: []

DEST = {"smartlead_campaign_id": "3591996"}


# ── Idempotency: pushing the same prospect twice must not double-send
def not_suppressed(*a, **k):
    return []  # RPC returns no exclusion rows
server.sb = lambda method, path, body=None, **k: not_suppressed()

pr = {"name": "Ada Lovelace", "email": "ada@acme.com", "company": "Acme", "domain": "acme.com"}
r1 = server.push_prospect(pr, DEST, client_id="c1")
r2 = server.push_prospect(pr, DEST, client_id="c1")  # re-push
check("first push succeeds", r1.get("ok") is True)
check("re-push still ok (idempotent)", r2.get("ok") is True)
check("provider called exactly once for two pushes", SL_CALLS["n"] == 1)
check("second push reports 'already sent'", r2["tools"]["smartlead"]["message"] == "already sent")

# ── Failed push must NOT stamp pushed
SL_CALLS["n"] = 0
server.push_to_smartlead = lambda pr, cid: {"ok": False, "message": "smartlead 500"}
pr2 = {"name": "Bad Push", "email": "b@fail.com", "domain": "fail.com"}
rf = server.push_prospect(pr2, DEST, client_id="c1")
check("failed push returns ok:false", rf.get("ok") is False)
check("failed push did NOT stamp pushed", not pr2.get("pushed"))

# ── Suppression: a suppressed prospect is skipped (not sent, not stamped)
server.push_to_smartlead = fake_smartlead
SL_CALLS["n"] = 0
server.sb = lambda method, path, body=None, **k: [{"hit": 1}]  # RPC says: excluded
prs = {"name": "Already Contacted", "email": "seen@acme.com", "domain": "acme.com"}
rs = server.push_prospect(prs, DEST, client_id="c1")
check("suppressed prospect returns ok:false", rs.get("ok") is False)
check("suppressed prospect flagged suppressed", rs.get("suppressed") is True)
check("suppressed prospect NOT sent to provider", SL_CALLS["n"] == 0)
check("suppressed prospect NOT stamped pushed", not prs.get("pushed"))

# ── No client_id -> suppression check is skipped (unchanged behaviour)
server.sb = lambda method, path, body=None, **k: [{"hit": 1}]
SL_CALLS["n"] = 0
prn = {"name": "No Client", "email": "x@acme.com", "domain": "acme.com"}
rn = server.push_prospect(prn, DEST, client_id=None)
check("no client_id -> still sends (suppression needs a client)", rn.get("ok") is True and SL_CALLS["n"] == 1)

print()
if FAILS:
    print(f"REGRESSION FAILED: {len(FAILS)} check(s) — {', '.join(FAILS)}")
    sys.exit(1)
print("ALL PUSH-RELIABILITY CHECKS PASSED")
