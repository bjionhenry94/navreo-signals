"""Gate for the campaign "Change Logs" tab feed (Bjion, 4 Sep 2026).

`campaign_change_log(cid)` is the one read behind `#/c/<id>/changes`. Three
things must hold or the tab lies to the client:

  * `_clog_from_activity` turns each raw app_activity_log row into ONE
    plain-English line — and returns None for rows that are not a change
    (an unknown action, a status we do not narrate, a no-op removal).
  * `_clog_pcts` renders a traffic move as "A 80% -> 100%, B 20% -> 0%", the
    exact line the 2 Sep move on 3445988 shows, and stays quiet when there is
    nothing to compare.
  * a non-numeric campaign id is a 400 before any Supabase read happens.
"""
import os
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ── _clog_from_activity ──────────────────────────────────────────────────────
ev = server._clog_from_activity(
    {"action": "variant-action",
     "payload": {"action": "scale_winner", "variant_label": "A", "email": 1}})
check("variant-action/scale_winner -> variant kind", ev and ev[0] == "variant", repr(ev))
check("variant-action/scale_winner reads in plain English",
      ev and ev[1] == "Sent all of Email 1 to version A", repr(ev))
check("variant-action carries the 'Version edit' tag", ev and ev[3] == "Version edit", repr(ev))

ev = server._clog_from_activity(
    {"action": "variant-action",
     "payload": {"action": "back_winner", "variant_label": "C", "email": 2}})
check("back_winner names the step it touched and the kept test",
      ev and ev[1] == "Sent most of Email 2 to version C, kept testing the rest", repr(ev))

ev = server._clog_from_activity(
    {"action": "variant-action", "payload": {"action": "split_leaders", "email": 1}})
check("split_leaders narrates the even split",
      ev and ev[1] == "Split Email 1 evenly between the leading versions", repr(ev))

ev = server._clog_from_activity({"action": "variant-action", "payload": {}})
check("an unknown variant action still yields a line, never a crash",
      ev and ev[0] == "variant" and "version split" in ev[1], repr(ev))

# campaign-status: only the three statuses we narrate produce a line
ev = server._clog_from_activity({"action": "campaign-status", "payload": {"status": "PAUSED"}})
check("campaign-status PAUSED -> status kind", ev and ev[0] == "status", repr(ev))
check("campaign-status PAUSED reads 'Paused the campaign'",
      ev and ev[1] == "Paused the campaign" and ev[3] == "Status", repr(ev))
ev = server._clog_from_activity({"action": "campaign-status", "payload": {"status": "start"}})
check("campaign-status is case-insensitive (start -> live)",
      ev and ev[1] == "Set the campaign live", repr(ev))
check("an unnarrated status is dropped, not guessed",
      server._clog_from_activity(
          {"action": "campaign-status", "payload": {"status": "DELETED"}}) is None)

# auto-move switch flips
ev = server._clog_from_activity({"action": "auto-move", "payload": {"mode": "on"}})
check("auto-move on -> switch kind, Auto Optimise tag",
      ev and ev[0] == "switch" and ev[3] == "Auto Optimise", repr(ev))
check("auto-move on reads as turned on",
      ev and ev[1] == "Auto Optimise turned on for this campaign", repr(ev))
ev = server._clog_from_activity({"action": "auto-move", "payload": {"mode": "off"}})
check("auto-move off reads as turned off",
      ev and ev[1] == "Auto Optimise turned off for this campaign", repr(ev))
ev = server._clog_from_activity({"action": "auto-move", "payload": {"mode": "inherit"}})
check("auto-move inherit reads as following the tool-wide switch",
      ev and ev[1] == "Auto Optimise set to follow the tool-wide switch", repr(ev))
check("an unknown auto-move mode is dropped",
      server._clog_from_activity({"action": "auto-move", "payload": {"mode": "??"}}) is None)

# verify_run (the list deliverability audit)
ev = server._clog_from_activity(
    {"action": "verify_run", "payload": {"total": 12500, "bad": 340, "removed": 340}})
check("verify_run -> audit kind with the List audit tag",
      ev and ev[0] == "audit" and ev[3] == "List audit", repr(ev))
check("verify_run counts are thousands-separated",
      ev and ev[1] == "Audited the list for deliverability — checked 12,500, 340 flagged", repr(ev))
check("verify_run detail names the removals",
      ev and ev[2] == "340 risky leads removed", repr(ev))
ev = server._clog_from_activity({"action": "verify_run", "payload": {"total": 10, "bad": 0}})
check("verify_run with no 'removed' key carries no detail", ev and ev[2] == "", repr(ev))

check("remove_bad with nothing removed is not an event",
      server._clog_from_activity({"action": "remove_bad", "payload": {"removed": 0}}) is None)
ev = server._clog_from_activity({"action": "remove_bad", "payload": {"removed": 7}})
check("remove_bad reports the removal", ev and ev[1] == "Removed 7 risky leads from the list", repr(ev))

check("an action we do not narrate is dropped",
      server._clog_from_activity({"action": "login", "payload": {}}) is None)
check("a row with no payload never raises",
      server._clog_from_activity({"action": "campaign-status"}) is None)

# ── _clog_pcts ───────────────────────────────────────────────────────────────
check("the 2 Sep 3445988 move renders as 'A 80% → 100%, B 20% → 0%'",
      server._clog_pcts({"A": 80, "B": 20}, {"A": 100, "B": 0})
      == "A 80% → 100%, B 20% → 0%",
      server._clog_pcts({"A": 80, "B": 20}, {"A": 100, "B": 0}))
check("labels are ordered, not left in dict order",
      server._clog_pcts({"B": 20, "A": 80}, {"B": 0, "A": 100}).startswith("A "))
check("an unchanged label shows one number, not an arrow",
      server._clog_pcts({"A": 50, "B": 50}, {"A": 50, "B": 50}) == "A 50%, B 50%",
      server._clog_pcts({"A": 50, "B": 50}, {"A": 50, "B": 50}))
check("a label with no before value shows only its after",
      server._clog_pcts({}, {"C": 100}) == "C 100%")
check("string percentages from the ledger are read as numbers",
      server._clog_pcts({"A": "20"}, {"A": "80"}) == "A 20% → 80%",
      server._clog_pcts({"A": "20"}, {"A": "80"}))
check("no after-split -> no line", server._clog_pcts({"A": 80}, None) == "")
check("empty after-split -> no line", server._clog_pcts({"A": 80}, {}) == "")
check("a junk before-split degrades to after-only",
      server._clog_pcts("nope", {"A": 100}) == "A 100%")
check("an unreadable percentage is skipped, never printed raw",
      server._clog_pcts({"A": 80}, {"A": None}) == "")

# ── the endpoint's input guard ───────────────────────────────────────────────
calls = []
_real_sb = server.sb
server.sb = lambda *a, **k: calls.append(a) or []
try:
    status, body = server.campaign_change_log("abc")
    check("a non-numeric campaign id is a 400", status == 400, repr(status))
    check("the 400 body says not-ok", body.get("ok") is False, repr(body))
    check("a bad id never reaches Supabase", not calls, repr(calls))

    status, body = server.campaign_change_log("")
    check("an empty campaign id is a 400 too", status == 400, repr(status))

    # a numeric id reads every lane and always answers ok, even with no rows
    calls.clear()
    status, body = server.campaign_change_log("3445988")
    check("a numeric id answers 200 ok", status == 200 and body.get("ok") is True, repr(status))
    check("the id is echoed back as an int", body.get("campaign_id") == 3445988, repr(body.get("campaign_id")))
    check("an empty feed is an empty event list, never None", body.get("events") == [], repr(body.get("events")))
    check("every lane was queried", len(calls) >= 4, f"{len(calls)} sb calls")
finally:
    server.sb = _real_sb

# a lane that blows up must drop only itself
def _boom(method, path, *a, **k):
    if "auto_mover_moves" in path:
        raise RuntimeError("supabase down")
    if "app_activity_log" in path:
        return [{"ts": "2026-09-02T16:05:00+00:00", "actor": "auto-mover@navreo.ai",
                 "action": "campaign-status", "payload": {"status": "PAUSED"}}]
    return []


server.sb = _boom
try:
    status, body = server.campaign_change_log("3445988")
    check("one dead lane never kills the feed", status == 200 and body.get("ok") is True, repr(status))
    check("the surviving lane still renders",
          [e["title"] for e in body.get("events", [])] == ["Paused the campaign"],
          repr(body.get("events")))
finally:
    server.sb = _real_sb

print(("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}"))
raise SystemExit(1 if fails else 0)
