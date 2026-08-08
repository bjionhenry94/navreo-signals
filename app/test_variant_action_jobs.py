"""Background variant-action job tests (Messaging readability loop,
2026-08-09): the POST route validates cheaply and 202s with a job id; ONE
daemon worker runs the real Smartlead write; the status route reports
running/done/failed. Run: python3 app/test_variant_action_jobs.py"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1

# 1 — cheap validations still refuse synchronously (no job minted)
s, b = server.api_campaign_variant_action_async("42", {"action": "nope"})
check("unknown action -> sync 400", s == 400 and not b.get("ok"))
s, b = server.api_campaign_variant_action_async("42", {"action": "disable", "email": 1, "variant_label": "A"})
check("missing confirm -> sync 400", s == 400)
s, b = server.api_campaign_variant_action_async("x", {"action": "disable", "email": 1, "variant_label": "A", "confirm": server._VARIANT_ACTION_CONFIRM["disable"]})
check("non-numeric cid -> sync 400", s == 400)
s, b = server.api_campaign_variant_action_async("42", {"action": "disable", "email": 1, "confirm": server._VARIANT_ACTION_CONFIRM["disable"]})
check("missing variant_label -> sync 400", s == 400)

# 2 — valid payload -> 202 + job id, worker runs the (stubbed) write
server._job_persist = lambda job: None  # keep test runs out of the app_jobs ledger
_real = server.api_campaign_variant_action
calls = []
def _stub_ok(cid, payload):
    calls.append((cid, payload))
    time.sleep(0.05)
    return 200, {"ok": True, "executed": payload.get("action"), "after": {"A": 0}}
server.api_campaign_variant_action = _stub_ok
try:
    s, b = server.api_campaign_variant_action_async("42", {
        "action": "disable", "email": 1, "variant_label": "A",
        "confirm": server._VARIANT_ACTION_CONFIRM["disable"]})
    check("valid payload -> 202 queued", s == 202 and b.get("queued") and b.get("job"), (s, b))
    job = b.get("job")
    s2, b2 = server.api_campaign_variant_action_status(job)
    check("status route knows the job", s2 == 200 and b2.get("status") in ("running", "done"), (s2, b2))
    deadline = time.time() + 5
    while time.time() < deadline:
        s2, b2 = server.api_campaign_variant_action_status(job)
        if b2.get("status") != "running":
            break
        time.sleep(0.05)
    check("job completes -> done with the write's body", b2.get("status") == "done"
          and b2.get("status_code") == 200 and (b2.get("body") or {}).get("after") == {"A": 0}, b2)
    check("worker actually ran the real action fn", len(calls) == 1 and calls[0][0] == "42")

    # 2b — the write is mirrored into the house JOBS registry (Tasks bar)
    shell = [j for j in server.JOBS.values() if j.get("kind") == "variant_action"]
    check("Tasks-bar job created + finished done", any(
        j.get("status") == "done" and "Switch off Version A" in (j.get("label") or "")
        for j in shell), [(j.get("status"), j.get("label")) for j in shell])

    # 3 — a refused write surfaces as failed, body carried through
    server.api_campaign_variant_action = lambda cid, p: (404, {"ok": False, "message": "variant Z not found"})
    s, b = server.api_campaign_variant_action_async("42", {
        "action": "enable", "email": 1, "variant_label": "Z",
        "confirm": server._VARIANT_ACTION_CONFIRM["enable"]})
    job = b.get("job")
    deadline = time.time() + 5
    while time.time() < deadline:
        s2, b2 = server.api_campaign_variant_action_status(job)
        if b2.get("status") != "running":
            break
        time.sleep(0.05)
    check("refused write -> failed + message kept", b2.get("status") == "failed"
          and "not found" in ((b2.get("body") or {}).get("message") or ""), b2)

    # 4 — a crashing write still resolves the job (never a stuck 'running')
    def _boom(cid, p):
        raise RuntimeError("smartlead exploded")
    server.api_campaign_variant_action = _boom
    s, b = server.api_campaign_variant_action_async("42", {
        "action": "even_split", "email": 1,
        "confirm": server._VARIANT_ACTION_CONFIRM["even_split"]})
    job = b.get("job")
    deadline = time.time() + 5
    while time.time() < deadline:
        s2, b2 = server.api_campaign_variant_action_status(job)
        if b2.get("status") != "running":
            break
        time.sleep(0.05)
    check("crashing write -> failed, not stuck", b2.get("status") == "failed"
          and "crashed" in ((b2.get("body") or {}).get("message") or ""), b2)
finally:
    server.api_campaign_variant_action = _real

# 5 — unknown job id
s, b = server.api_campaign_variant_action_status("deadbeef")
check("unknown job -> 404 unknown", s == 404 and b.get("status") == "unknown")

print()
print("ALL PASS" if _fail == 0 else f"{_fail} FAILED")
sys.exit(1 if _fail else 0)
