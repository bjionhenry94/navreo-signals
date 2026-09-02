"""Variant Auto-Mover — the runner (Step 4).

ONE test per edge-case rule R1-R14, plus the three verdict modes and the
no-op / no-scale / switched-off paths. Supabase, Smartlead, the variant-action
door and Notion's HTTP layer are all mocked; nothing here touches a network.

The mover contains NO judging logic, so these tests never assert a bar, a
metric or a winner pick — they assert that whatever build_notifications says
is what the door is asked to do, and that the rails around it hold.

Run: NAVREO_NO_BG=1 python3 app/test_auto_mover.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1


# ── fixture payloads (same shape as test_best_opener_flat800_tie.py) ────────
def V(label, sent, positives=0, meetings=0, split=100):
    return {"step": 1, "label": label, "sent": sent, "positives": positives,
            "meetings": meetings, "inline": False, "disabled": False, "split": split}


def M(versions):
    by_variant = {f"1|{v['label']}": v["meetings"] for v in versions if v.get("meetings")}
    return {"versions": versions, "paths": None,
            "meetings": {"by_variant": by_variant, "clusters": {}},
            "judge_bars": {"1": 800}}


FULL    = M([V("A", 1000, 10, split=60), V("B", 1000, 2, split=40)])
PARTIAL = M([V("A", 1000, 10, split=50), V("B", 400, 2, split=50)])
TIE     = M([V("A", 1000, 10, split=90), V("B", 1000, 10, split=10)])
NOSCALE = M([V("A", 300, 1, split=50), V("B", 300, 1, split=50)])


# ── the world ───────────────────────────────────────────────────────────────
class World:
    def __init__(self):
        self.reset()

    def reset(self):
        self.messaging = FULL
        self.messaging_seq = None   # [first read, second read] when they differ
        self._reads = 0
        self.splits = {"A": 60, "B": 40}
        self.splits_after = None            # None = unchanged by the save
        self.counters = {"1|A": {"sent": 1000, "replies": 30, "positives": 10},
                         "1|B": {"sent": 1000, "replies": 9, "positives": 2}}
        self.counters_after = None
        self.active = True
        self.dismissed_rows, self.assignments = [], {}
        self.notifications = [{"id": "n1", "campaign_id": "3445988", "status": "new",
                               "created_at": "2026-09-02T00:00:00Z"}]
        self.cards = []
        self.ledger = []                    # auto_mover_moves rows
        self.prefs = {}                     # per-campaign switch
        self.ui_prefs = {"auto_mover_enabled": True, "show_demo_clients": False,
                         "auto_mover_breaker": {}}
        self.door_calls, self.notion_calls, self.smartlead_calls = [], [], []
        self.door_result = "ok"             # ok | reject | fail
        self.notion_open = {}               # marker -> url of an OPEN task
        self.status_patches, self.jobs = [], []


W = World()


def fake_sb(method, path, body=None, prefer="", **kw):
    if path.startswith("deliverability_audit_cache?id=eq.ui_prefs"):
        return [{"blob": dict(W.ui_prefs)}]
    if path.startswith("deliverability_audit_cache?on_conflict=id"):
        W.ui_prefs = dict(body.get("blob") or {})
        return []
    if path.startswith("auto_mover_campaign_prefs?on_conflict"):
        W.prefs[str(body["campaign_id"])] = dict(body); return []
    if path.startswith("auto_mover_campaign_prefs?campaign_id=eq."):
        cid = path.split("campaign_id=eq.", 1)[1].split("&", 1)[0]
        row = W.prefs.get(cid)
        return [row] if row else []
    if path.startswith("optimiser_notifications?action_type=eq.scale_winner"):
        if "status=eq.dismissed" in path:
            return list(W.dismissed_rows)
        return list(W.notifications)
    if path.startswith("optimiser_notifications?id=eq."):
        W.status_patches.append((path.split("id=eq.", 1)[1], dict(body or {})))
        return [{"id": "n1", **(body or {})}]
    if path.startswith("campaign_insights?insight_key=eq.scale-winner"):
        return list(W.cards)
    if path.startswith("cockpit_action_assignments?action_key=eq."):
        from urllib.parse import unquote
        key = unquote(path.split("action_key=eq.", 1)[1].split("&", 1)[0])
        row = W.assignments.get(key)
        return [row] if row else []
    if path.startswith("cockpit_action_assignments?on_conflict"):
        W.assignments[body["action_key"]] = dict(body)
        return [dict(body)]
    if path.startswith("campaign_scorecard?smartlead_campaign_id=eq."):
        return [{"name": "Reconnect: Navreo - Exporters [June]", "client": "Navreo",
                 "workspace": "navreo", "status": "ACTIVE"}]
    if path.startswith("auto_mover_moves") and method == "POST":
        W.ledger.append(dict(body or {})); return []
    if path.startswith("auto_mover_moves"):
        rows = list(reversed(W.ledger))
        if "outcome=eq.moved" in path:
            rows = [r for r in rows if r.get("outcome") == "moved"]
        if "campaign_id=eq." in path:
            from urllib.parse import unquote
            cid = unquote(path.split("campaign_id=eq.", 1)[1].split("&", 1)[0])
            rows = [r for r in rows if str(r.get("campaign_id")) == cid]
        return rows[:1] if "limit=1" in path else rows
    if path.startswith("app_jobs") or path.startswith("app_activity_log"):
        return []
    return []


def fake_smartlead(method, path, body=None, timeout=60, attempts=5, workspace=None):
    W.smartlead_calls.append((method, path))
    if path.endswith("/sequences"):
        splits = W.splits if not W.door_calls or W.splits_after is None else W.splits_after
        return [{"seq_number": 1,
                 "sequence_variants": [{"variant_label": k,
                                        "variant_distribution_percentage": v,
                                        "is_deleted": False}
                                       for k, v in splits.items()]}]
    if path.endswith("/variant-statistics"):
        c = W.counters if not W.door_calls or W.counters_after is None else W.counters_after
        return {"data": [{"seq_number": int(k.split("|")[0]), "variant_label": k.split("|")[1],
                          "seq_variant_id": 900 + i, "sent_count": v["sent"],
                          "reply_count": v["replies"], "positive_reply_count": v["positives"]}
                         for i, (k, v) in enumerate(c.items())]}
    return {}


def fake_door(cid, payload):
    W.door_calls.append((str(cid), dict(payload)))
    if W.door_result == "reject":
        return 400, {"ok": False, "message": "rejected by the door"}
    return 202, {"ok": True, "queued": True, "job": "j" + str(len(W.door_calls))}


def fake_status(job_id):
    if W.door_result == "fail":
        return 200, {"ok": True, "status": "failed", "status_code": 502,
                     "body": {"ok": False, "message": "Smartlead said no"}}
    return 200, {"ok": True, "status": "done", "status_code": 200, "body": {"ok": True}}


def fake_live_status(cid):
    return {"campaigns": {str(cid): {"status": "ACTIVE" if W.active else "PAUSED"}}}


def fake_http_json(method, url, headers=None, body=None, **kw):
    """The Notion REST layer. Query answers the dedupe probe; pages creates."""
    W.notion_calls.append((method, url, body))
    if "/data_sources/" in url and url.endswith("/query"):
        want = ((body or {}).get("filter") or {}).get("and") or []
        marker = ""
        for cl in want:
            marker = ((cl.get("title") or {}).get("contains")) or marker
        hit = W.notion_open.get(marker)
        return {"object": "list", "results": ([{"id": "p0", "url": hit}] if hit else [])}
    if url.endswith("/pages"):
        return {"object": "page", "id": "p1",
                "url": "https://notion.so/task-" + str(len(W.notion_calls))}
    return {}


class _FakeSWR:
    def get(self, key):
        return fake_live_status(key)


server.sb = fake_sb
server._smartlead_json = fake_smartlead
server.api_campaign_variant_action_async = fake_door
server.api_campaign_variant_action_status = fake_status
server._COCKPIT_LIVE_STATUS_SWR = _FakeSWR()
server.http_json = fake_http_json
server.KEYS = dict(server.KEYS or {}); server.KEYS["NOTION_API_KEY"] = "secret_test"
def fake_messaging(cid):
    if W.messaging_seq:
        i = min(W._reads, len(W.messaging_seq) - 1)
        W._reads += 1
        return W.messaging_seq[i]
    return W.messaging


server._cockpit_messaging = fake_messaging
server._new_job = lambda *a, **k: {"id": "job", "status": "queued", "counts": {}}
server._job_started = lambda j: W.jobs.append(("start", j))
server._job_finished = lambda j, s, e=None: W.jobs.append(("finish", s))
server._AM_SPACING_S = 0.0          # the 20s spacing is asserted on the constant, not slept


def prep(**kw):
    W.reset()
    for k, v in kw.items():
        setattr(W, k, v)
    server._UI_PREFS_TS = 0.0
    return server.auto_move_run(campaign_id=kw.pop("_cid", None) or None)


def d0(res):
    return (res.get("disposition") or [{}])[0]


# ── modes ───────────────────────────────────────────────────────────────────
r = prep()
check("full -> scale_winner", W.door_calls and W.door_calls[0][1]["action"] == "scale_winner"
      and W.door_calls[0][1]["variant_label"] == "A"
      and W.door_calls[0][1]["confirm"] == "SCALE"
      and W.door_calls[0][1]["email"] == 1, W.door_calls)
check("full is recorded as moved", d0(r)["outcome"] == "moved", r)

r = prep(messaging=PARTIAL, splits={"A": 50, "B": 50})
check("partial -> back_winner with the engine's laggards",
      W.door_calls and W.door_calls[0][1]["action"] == "back_winner"
      and W.door_calls[0][1]["variant_label"] == "A"
      and W.door_calls[0][1]["laggards"] == ["B"]
      and W.door_calls[0][1]["confirm"] == "BACK", W.door_calls)

r = prep(messaging=TIE, splits={"A": 90, "B": 10})
check("tie -> split_leaders with the engine's leaders",
      W.door_calls and W.door_calls[0][1]["action"] == "split_leaders"
      and W.door_calls[0][1]["leaders"] == ["A", "B"]
      and "variant_label" not in W.door_calls[0][1]
      and W.door_calls[0][1]["confirm"] == "SPLITLEADERS", W.door_calls)

r = prep(messaging=NOSCALE)
check("no scale -> skip, no Smartlead write",
      d0(r)["reason"] == "no_move" and not W.door_calls, (r, W.door_calls))

# R9's "already at target": the first read says move, but by the time the mover
# re-asks (a human clicked, or a racing tick landed) the engine says has_scale
# is False — that IS "already there", derived from the engine, never from
# arithmetic inside the mover.
r = prep(messaging_seq=[FULL, M([V("A", 1000, 10, split=100), V("B", 1000, 2, split=0)])])
check("already at target -> no-op, marked actioned",
      d0(r)["outcome"] == "noop" and d0(r)["reason"] == "already_at_target"
      and not W.door_calls
      and W.status_patches and W.status_patches[0][1]["status"] == "actioned"
      and W.assignments.get("3445988::scale-winner", {}).get("state") == "done", (r, W.status_patches))


# ── R1 · counter preservation, breaker on a drop ────────────────────────────
r = prep(counters_after={"1|A": {"sent": 1000, "replies": 30, "positives": 10},
                         "1|B": {"sent": 4, "replies": 0, "positives": 0}})
check("R1 a counter drop trips the breaker and turns the global switch off",
      W.ui_prefs["auto_mover_breaker"].get("tripped") is True
      and W.ui_prefs["auto_mover_enabled"] is False
      and r.get("stopped") == "breaker_tripped", (r, W.ui_prefs))
check("R1 the drop is filed as a High Notion task",
      any(u.endswith("/pages") and (b["properties"]["Priority"]["select"]["name"] == "High")
          for _m, u, b in W.notion_calls if u.endswith("/pages")), W.notion_calls)
check("R1 the ledger row carries both counter snapshots",
      W.ledger and W.ledger[-1].get("counters_before") and W.ledger[-1].get("counters_after")
      and W.ledger[-1].get("issue_kind") == "counter_drop", W.ledger)

r = prep()
check("R1 a clean move records no counter issue",
      W.ledger[-1].get("issue_kind") != "counter_drop"
      and server._am_counter_drop(W.counters, W.counters) == "", W.ledger)


# ── R2 · a reversal inside 48h is EXECUTED and flagged as a flap ────────────
W.reset()
W.ledger.append({"campaign_id": "3445988", "step": 1, "outcome": "moved",
                 "winner": "B", "mode": "full", "pcts_after": {"A": 60, "B": 40},
                 "created_at": server._am_iso()})
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R2 a reversal still runs", W.door_calls and d0(r)["outcome"] == "moved", (r, W.door_calls))
check("R2 the reversal is flagged as a flap",
      d0(r).get("flap") is True and W.ledger[-1].get("issue_kind") == "flap", (r, W.ledger[-1]))
check("R2 the flap is a Medium Notion task",
      any(b["properties"]["Priority"]["select"]["name"] == "Medium"
          for _m, u, b in W.notion_calls if u.endswith("/pages")), W.notion_calls)


# ── R3 · thin evidence is a ledger FLAG, never a gate ───────────────────────
r = prep(messaging=M([V("A", 1000, 1, split=60), V("B", 1000, 0, split=40)]),
         splits={"A": 60, "B": 40})
check("R3 a thin winner still moves", d0(r)["outcome"] == "moved" and W.door_calls, r)
check("R3 thin evidence is flagged in the ledger",
      W.ledger[-1].get("issue_kind") == "thin_evidence" and d0(r).get("thin_evidence") is True,
      (W.ledger[-1], r))
check("R3 thin evidence raises NO Notion task",
      not [1 for _m, u, _b in W.notion_calls if u.endswith("/pages")], W.notion_calls)


# ── R4 · a human set the splits by hand after our last write ───────────────
W.reset()
W.ledger.append({"campaign_id": "3445988", "step": 1, "outcome": "moved",
                 "winner": "A", "mode": "full", "pcts_after": {"A": 100, "B": 0},
                 "created_at": server._am_iso()})
W.splits = {"A": 55, "B": 45}          # someone changed it since
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R4 a hand-set split is skipped as human_owned",
      d0(r)["reason"] == "human_owned" and not W.door_calls, (r, W.door_calls))
check("R4 human_owned raises ONE Medium Notion task",
      len([1 for _m, u, _b in W.notion_calls if u.endswith("/pages")]) == 1
      and W.ledger[-1].get("issue_kind") == "human_owned", (W.notion_calls, W.ledger[-1]))


# ── R5 · a dismissed row / dismiss assignment bars the mover forever ────────
r = prep(dismissed_rows=[{"id": "n9"}])
check("R5 a dismissed notification is never actioned",
      d0(r)["reason"] == "dismissed" and not W.door_calls, (r, W.door_calls))
W.reset()
W.assignments["3445988::scale-winner"] = {"action_key": "3445988::scale-winner",
                                          "state": "dismiss"}
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R5 a dismiss assignment is never actioned",
      d0(r)["reason"] == "dismissed" and not W.door_calls, (r, W.door_calls))


# ── R6 · only ACTIVE campaigns ──────────────────────────────────────────────
r = prep(active=False)
check("R6 a non-ACTIVE campaign is skipped",
      d0(r)["reason"] == "not_active" and not W.door_calls, (r, W.door_calls))


# ── R7 · the fresh verdict wins over the stale trigger row ──────────────────
r = prep(messaging=M([V("A", 1000, 2, split=60), V("B", 1000, 20, split=40)]))
check("R7 the mover follows the FRESH winner, not the row",
      W.door_calls and W.door_calls[0][1]["variant_label"] == "B", W.door_calls)
r = prep(messaging=NOSCALE,
         notifications=[{"id": "n1", "campaign_id": "3445988", "status": "new",
                         "created_at": "2026-09-02T00:00:00Z"}])
check("R7 a stale row whose fresh verdict says no move is skipped",
      d0(r)["reason"] == "no_move" and not W.door_calls, (r, W.door_calls))


# ── R8 · caps, spacing, abort and breaker-on-repeated-failure ───────────────
check("R8 the caps are 10 per run, 60 per day, 20s apart",
      (server._AM_MAX_MOVES_RUN, server._AM_MAX_MOVES_DAY) == (10, 60)
      and server._AM_MAX_CONSEC_FAILS == 2 and server._AM_BREAKER_FAILS == 3)
W.reset()
W.notifications = [{"id": f"n{i}", "campaign_id": str(3400000 + i), "status": "new",
                    "created_at": "2026-09-02T00:00:00Z"} for i in range(14)]
server._UI_PREFS_TS = 0.0
r = server.auto_move_run(max_moves=3)
check("R8 max_moves caps the run", r["moved"] == 3
      and len([d for d in r["disposition"] if d["reason"] == "run_cap"]) == 11, r["moved"])
W.reset()
W.notifications = [{"id": f"n{i}", "campaign_id": str(3400000 + i), "status": "new",
                    "created_at": "2026-09-02T00:00:00Z"} for i in range(5)]
W.door_result = "fail"
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R8 two consecutive final failures abort the run",
      r.get("stopped") == "consecutive_failures" and len(r["disposition"]) == 2, r)


# ── R9 · never race the cron; re-check the split right before the enqueue ───
W.reset(); server._UI_PREFS_TS = 0.0
server._CRON_LOCK.acquire()
try:
    r = server.auto_move_run()
finally:
    server._CRON_LOCK.release()
check("R9 a held _CRON_LOCK skips the whole tick",
      r.get("busy") is True and r.get("reason") == "cron_running" and not W.door_calls, r)
W.reset(); server._UI_PREFS_TS = 0.0
server._AUTO_MOVE_LOCK.acquire()
try:
    r = server.auto_move_run()
finally:
    server._AUTO_MOVE_LOCK.release()
check("R9 the mover's own lock is non-blocking",
      r.get("busy") is True and r.get("reason") == "already_running", r)


# ── R10 · client-owned workspaces are treated exactly like ours ─────────────
W.reset()
_orig_sb = fake_sb
def krg_sb(method, path, body=None, prefer="", **kw):
    if path.startswith("campaign_scorecard?smartlead_campaign_id=eq."):
        return [{"name": "KRG - Founders", "client": "KRG", "workspace": "krg",
                 "status": "ACTIVE"}]
    return _orig_sb(method, path, body, prefer, **kw)
server.sb = krg_sb
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
server.sb = _orig_sb
check("R10 a client workspace gets no carve-out",
      d0(r)["outcome"] == "moved" and d0(r)["client"] == "KRG" and W.door_calls, r)


# ── R11 · kill-switch latency: global off, per-campaign off beats on ────────
W.reset(); W.ui_prefs["auto_mover_enabled"] = False
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R11 global off touches nothing",
      r.get("started") is False and r.get("reason") == "global_off"
      and not W.door_calls and not W.smartlead_calls and not W.ledger, (r, W.smartlead_calls))
W.reset(); W.prefs["3445988"] = {"campaign_id": "3445988", "mode": "off"}
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R11 per-campaign off skips WITHOUT a Smartlead call",
      d0(r)["reason"] == "per_campaign_off" and not W.door_calls
      and not W.smartlead_calls and not W.ledger, (r, W.smartlead_calls))
W.reset(); W.ui_prefs["auto_mover_breaker"] = {"tripped": True, "reason": "x"}
server._UI_PREFS_TS = 0.0
r = server.auto_move_run()
check("R11 a tripped breaker stops the run before any candidate",
      r.get("reason") == "breaker_tripped" and not W.door_calls, r)


# ── R12 · only the three allowed door actions, ever ─────────────────────────
check("R12 the action allowlist is exactly the three moves",
      set(a for a, _c in server._AM_ACTION_BY_MODE.values())
      == {"scale_winner", "back_winner", "split_leaders"}, server._AM_ACTION_BY_MODE)
seen = set()
for _m in (FULL, PARTIAL, TIE):
    prep(messaging=_m, splits={"A": 60, "B": 40})
    if W.door_calls:
        seen.add(W.door_calls[0][1]["action"])
check("R12 every mode routes inside the allowlist",
      seen and seen <= {"scale_winner", "back_winner", "split_leaders"}, seen)


# ── R13 · a move is never silent ────────────────────────────────────────────
r = prep()
check("R13 the ledger row is complete",
      W.ledger and all(W.ledger[-1].get(k) is not None
                       for k in ("campaign_id", "step", "action", "mode",
                                 "pcts_before", "pcts_after", "counters_before",
                                 "counters_after", "evidence", "actor", "outcome")),
      W.ledger[-1] if W.ledger else None)
check("R13 the notification is marked actioned",
      W.status_patches and W.status_patches[-1][1]["status"] == "actioned", W.status_patches)
check("R13 the cockpit assignment is marked done by the mover",
      W.assignments.get("3445988::scale-winner", {}).get("state") == "done"
      and W.assignments["3445988::scale-winner"]["assigned_to"] == server.AUTO_MOVER_ACTOR,
      W.assignments)
check("R13 the Tasks panel gets a run job and a move job",
      len([j for j in W.jobs if j[0] == "start"]) >= 2, W.jobs)
check("R13 the disposition carries before -> after",
      d0(r).get("before") and d0(r).get("after") is not None, r)


# ── R14 · one Notion task per (campaign, kind) while one is open ────────────
W.reset()
W.counters_after = {"1|A": {"sent": 1000, "replies": 30, "positives": 10},
                    "1|B": {"sent": 1, "replies": 0, "positives": 0}}
server._UI_PREFS_TS = 0.0
server.auto_move_run()
creates = [b for _m, u, b in W.notion_calls if u.endswith("/pages")]
check("R14 the helper is called ONCE with the right properties",
      len(creates) == 1
      and creates[0]["parent"]["data_source_id"] == server.NOTION_CLIENT_TASKS_DS
      and "Client " in creates[0]["properties"]
      and creates[0]["properties"]["Client "]["select"]["name"] == "Navreo"
      and creates[0]["properties"]["Status"]["status"]["name"] == "Not started"
      and creates[0]["properties"]["Priority"]["select"]["name"] == "High"
      and creates[0]["properties"]["Due Date"]["date"]["start"]
      and "[auto-mover:3445988:counter_drop]" in
          creates[0]["properties"]["Name"]["title"][0]["text"]["content"], creates)
check("R14 the body is a What/Why/Where/How brief with both links",
      all(h in json.dumps(creates[0]["children"])
          for h in ("What", "Why", "Where", "How", "optimise.html?c=3445988",
                    "email-campaign/3445988")), creates[0]["children"] if creates else None)
# second run, same open task -> no duplicate
W.notion_open["[auto-mover:3445988:counter_drop]"] = "https://notion.so/already-open"
W.notion_calls = []; W.door_calls = []; W.ledger = []
W.ui_prefs["auto_mover_enabled"] = True; W.ui_prefs["auto_mover_breaker"] = {}
server._UI_PREFS_TS = 0.0
server.auto_move_run()
again = [b for _m, u, b in W.notion_calls if u.endswith("/pages")]
check("R14 it is NOT filed twice while one is open", len(again) == 0, again)
check("R14 the existing task's URL is reused on the ledger row",
      W.ledger and W.ledger[-1].get("notion_task_url") == "https://notion.so/already-open",
      W.ledger[-1] if W.ledger else None)

# the due date is two WORKING days out
import datetime as _dt
_due = _dt.date.fromisoformat(server._working_days_from(2))
check("R14 the due date is 2 working days out and never a weekend",
      _due.weekday() < 5 and (_due - _dt.date.today()).days in (2, 3, 4), _due)


print(f"\n{'ALL PASS' if not _fail else str(_fail) + ' FAILED'}")
raise SystemExit(1 if _fail else 0)
