"""Auto-mover maintenance gate (2026-09-04):

  B2  auto_mover_refile_issues — the R14 backstop that files the Notion Client
      Task for every failed/issue move that never got one, idempotently. Notion
      is mocked at http_json (the one HTTP call point behind both the dedupe
      query and the page create); Supabase is mocked at sb. No network.
  B3  _auto_mover_run_route — "Run now" must ACK a full sweep at 202 without
      waiting for the (minutes-long) runner, answer {busy:true} when a run is
      already going, and stay INLINE for a single-campaign probe.

Run: NAVREO_NO_BG=1 python3 app/test_auto_mover_maintenance.py
"""
import os
import threading
import time

os.environ.setdefault("NAVREO_NO_BG", "1")
os.environ.setdefault("NOTION_API_KEY", "test-key")  # _notion_task_headers, never networked
import server  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ── B2: a mocked Notion + Supabase harness ──────────────────────────────────
class Notion:
    """Records every page create; answers the dedupe query from `open_marker`."""
    def __init__(self):
        self.pages = []          # each POST .../pages body
        self.open_marker = {}    # marker -> existing url (dedupe hit)
        self.queries = 0

    def http_json(self, method, url, headers, body=None, timeout=60):
        if url.endswith("/query"):                     # notion_open_task_with_marker
            self.queries += 1
            flt = ((body or {}).get("filter") or {}).get("and") or []
            marker = ""
            for cl in flt:
                t = (cl.get("title") or {})
                if "contains" in t:
                    marker = t["contains"]
            hit = self.open_marker.get(marker)
            return {"object": "list", "results": ([{"url": hit, "archived": False}] if hit else [])}
        if url.endswith("/pages"):                     # notion_create_task
            n = len(self.pages) + 1
            self.pages.append(body)
            return {"object": "page", "id": f"pg_{n}", "url": f"https://www.notion.so/pg_{n}"}
        raise AssertionError(f"unexpected Notion call {method} {url}")


def make_sb(ledger_rows, meta_by_cid, patched):
    def fake_sb(method, path, body=None, *a, **k):
        if method == "GET" and path.startswith("auto_mover_moves"):
            return list(ledger_rows)
        if method == "GET" and path.startswith("campaign_scorecard"):
            cid = path.split("smartlead_campaign_id=eq.", 1)[1].split("&", 1)[0]
            m = meta_by_cid.get(cid)
            return [m] if m else []
        if method == "PATCH" and path.startswith("auto_mover_moves?id=eq."):
            rid = path.split("id=eq.", 1)[1]
            patched.append((rid, body))
            return []
        raise AssertionError(f"unexpected sb call {method} {path}")
    return fake_sb


def run_refile(ledger_rows, meta_by_cid, notion, limit=100):
    patched = []
    real_sb, real_http = server.sb, server.http_json
    server.sb = make_sb(ledger_rows, meta_by_cid, patched)
    server.http_json = notion.http_json
    try:
        return server.auto_mover_refile_issues(limit=limit), patched
    finally:
        server.sb, server.http_json = real_sb, real_http


META = {"3343012": {"name": "Arnic - Sales Leaders [May]", "client": "Arnic"}}

# 1 — the real single qualifying row (3343012 / save_failed): one High task filed
row = {"id": 17, "campaign_id": "3343012", "step": 1, "action": "scale_winner",
       "winner": "C", "mode": "full", "outcome": "failed", "issue_kind": "save_failed",
       "notion_task_url": None, "created_at": "2026-09-02T16:05:24+00:00"}
n = Notion()
res, patched = run_refile([row], META, n)
check("save_failed row -> ok", res.get("ok") is True, repr(res))
check("exactly one task filed", len(res.get("filed") or []) == 1, repr(res.get("filed")))
check("nothing skipped", not res.get("skipped"), repr(res.get("skipped")))
f0 = (res.get("filed") or [{}])[0]
check("filed row names the campaign + client", f0.get("campaign_id") == "3343012" and f0.get("client") == "Arnic", repr(f0))
check("save_failed is High priority", f0.get("priority") == "High", repr(f0))
check("exactly one Notion page created", len(n.pages) == 1, f"{len(n.pages)} pages")
check("the ledger row got its url written back", patched and patched[0][0] == "17"
      and patched[0][1].get("notion_task_url") == "https://www.notion.so/pg_1", repr(patched))
check("filed row reports stored_on_row", f0.get("stored_on_row") is True, repr(f0))

# the created page's Notion properties are exactly right
props = n.pages[0]["properties"]
check("Client key has the trailing space, value = Arnic",
      props.get("Client ", {}).get("select", {}).get("name") == "Arnic", repr(props.get("Client ")))
check("Status is Not started",
      props.get("Status", {}).get("status", {}).get("name") == "Not started", repr(props.get("Status")))
check("Priority is High", props.get("Priority", {}).get("select", {}).get("name") == "High", repr(props.get("Priority")))
due = props.get("Due Date", {}).get("date", {}).get("start")
check("Due Date is set", bool(due), repr(due))
import datetime as _dt
try:
    _wd = _dt.date.fromisoformat(due).weekday()
except Exception:
    _wd = 9
check("Due Date is a working day (not Sat/Sun)", _wd < 5, repr(due))
title = props.get("Name", {}).get("title", [{}])[0].get("text", {}).get("content", "")
check("title carries the dedupe marker", "[auto-mover:3343012:save_failed]" in title, repr(title))
heads = [b.get("heading_2", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
         for b in n.pages[0]["children"] if b.get("type") == "heading_2"]
check("body has What / Why / Where / How", heads == ["What", "Why", "Where", "How"], repr(heads))

# 2 — idempotency: an already-open task is reused, NO new page created
n2 = Notion()
n2.open_marker["[auto-mover:3343012:save_failed]"] = "https://www.notion.so/existing"
res2, patched2 = run_refile([row], META, n2)
check("idempotent: still reported filed", len(res2.get("filed") or []) == 1, repr(res2))
check("idempotent: reuses the open task's url",
      (res2.get("filed") or [{}])[0].get("notion_task_url") == "https://www.notion.so/existing", repr(res2))
check("idempotent: no NEW page created", len(n2.pages) == 0, f"{len(n2.pages)} pages")

# 3 — thin_evidence is NOT filed (R14: it goes to the General digest)
thin = dict(row, id=18, issue_kind="thin_evidence")
n3 = Notion()
res3, _ = run_refile([thin], META, n3)
check("thin_evidence is skipped, not filed", not res3.get("filed") and len(res3.get("skipped")) == 1, repr(res3))
check("thin_evidence creates no Notion page", len(n3.pages) == 0, f"{len(n3.pages)} pages")

# 4 — a row with no campaign id is skipped, never crashes
noid = dict(row, id=19, campaign_id="")
n4 = Notion()
res4, _ = run_refile([noid], META, n4)
check("no-campaign-id row is skipped", not res4.get("filed") and len(res4.get("skipped")) == 1, repr(res4))

# 5 — priorities by kind: counter_drop High, flap Medium
cd = dict(row, id=20, issue_kind="counter_drop")
fl = dict(row, id=21, outcome="issue", issue_kind="flap")
n5 = Notion()
res5, _ = run_refile([cd, fl], META, n5)
byid = {f["id"]: f for f in res5.get("filed") or []}
check("two rows -> two tasks", len(res5.get("filed") or []) == 2 and len(n5.pages) == 2, repr(res5))
check("counter_drop is High", byid.get(20, {}).get("priority") == "High", repr(byid.get(20)))
check("flap is Medium", byid.get(21, {}).get("priority") == "Medium", repr(byid.get(21)))

# 6 — a ledger read error degrades to ok:false, files nothing
def boom_sb(method, path, *a, **k):
    if path.startswith("auto_mover_moves"):
        return {"code": "500", "message": "down"}  # PostgREST error = truthy dict
    raise AssertionError("should not reach meta")
n6 = Notion()
real_sb, real_http = server.sb, server.http_json
server.sb, server.http_json = boom_sb, n6.http_json
try:
    res6 = server.auto_mover_refile_issues()
finally:
    server.sb, server.http_json = real_sb, real_http
check("an unreadable ledger -> ok:false, nothing filed",
      res6.get("ok") is False and not res6.get("filed") and len(n6.pages) == 0, repr(res6))


# ── B3: _auto_mover_run_route ────────────────────────────────────────────────
# A sweep must return 202 {started:true} BEFORE the (slow) runner finishes.
def test_sweep_non_blocking():
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def slow_runner(*a, **k):
        entered.set()
        release.wait(5)          # hold the "run" open
        completed.set()
        return {"ok": True, "started": True, "reviewed": 3, "moved": 1}

    real_run, real_log = server.auto_move_run, server.log_activity
    server.auto_move_run = slow_runner
    server.log_activity = lambda *a, **k: None
    try:
        t0 = time.time()
        status, body = server._auto_mover_run_route("", None, "bjion@navreo.ai")
        dt = time.time() - t0
        check("sweep acks fast (<1s), never blocks on the runner", dt < 1.0, f"{dt:.2f}s")
        check("sweep returns 202", status == 202, repr(status))
        check("sweep body is started:true", body.get("started") is True, repr(body))
        check("the runner had NOT completed when the route returned", not completed.is_set(),
              "runner finished before ack — route blocked")
        entered.wait(5)
        check("the runner really was started in the background", entered.is_set())
    finally:
        release.set()
        completed.wait(5)
        server.auto_move_run, server.log_activity = real_run, real_log


test_sweep_non_blocking()

# A sweep while a run is already going -> busy, no second run started
def test_sweep_busy():
    real_run = server.auto_move_run
    started = []
    server.auto_move_run = lambda *a, **k: started.append(1) or {"ok": True}
    server._AUTO_MOVE_LOCK.acquire()
    try:
        status, body = server._auto_mover_run_route("", None, "bjion@navreo.ai")
        check("busy sweep returns 200", status == 200, repr(status))
        check("busy sweep is busy:true, started:false", body.get("busy") is True and body.get("started") is False, repr(body))
        check("busy sweep starts no runner", not started, repr(started))
    finally:
        server._AUTO_MOVE_LOCK.release()
        server.auto_move_run = real_run


test_sweep_busy()

# A single-campaign probe stays INLINE (returns the runner's own disposition)
def test_probe_inline():
    seen = {}

    def probe_runner(campaign_id=None, max_moves=None, **k):
        seen["cid"] = campaign_id
        return {"ok": True, "started": False, "reason": "per_campaign_off",
                "campaign_id": campaign_id, "disposition": []}

    real_run, real_log = server.auto_move_run, server.log_activity
    server.auto_move_run = probe_runner
    server.log_activity = lambda *a, **k: None
    try:
        status, body = server._auto_mover_run_route("3343012", None, "bjion@navreo.ai")
        check("probe returns 200 inline", status == 200, repr(status))
        check("probe carries the runner's exact disposition",
              body.get("reason") == "per_campaign_off", repr(body))
        check("probe passes the campaign id straight to the runner", seen.get("cid") == "3343012", repr(seen))
    finally:
        server.auto_move_run, server.log_activity = real_run, real_log


test_probe_inline()

print(("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}"))
raise SystemExit(1 if fails else 0)
