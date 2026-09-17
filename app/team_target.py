"""Team Target — the team's shared monthly meetings board.

Read model + writers for /app/team-target.html. Design decisions (owner,
2026-09-17):

  * Target = 4 ATTENDED meetings per active sending client. Only status
    'attended' counts toward the number. 'booked' is shown as still-to-happen;
    no_show / cancelled / not_fit stay visible but never count.
  * "Said yes" (Meeting Request) and "booked" (Call Booked) leads are pulled
    live from the reply archive, client campaigns only — never Navreo's own
    (client label 'Navreo') and never the demo client ('Acme').
  * The human outcome of a meeting (attended / no-show / …), meetings added by
    hand, and who edited what live in the `team_meetings` table and OVERLAY the
    auto leads by (workspace, lead_email).
  * "Avg reply time" = how fast we reply after a lead's positive reply, from
    setter_queue.sent_at - replied_at (the same source the setter answer-speed
    chart uses).

Everything reads through server.sb / server.sb_get_all so a Supabase outage
degrades instead of breaking. No number is invented.
"""
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta

import server

WORKSPACE = "navreo"
_EXCLUDE_LABELS = {"", "Navreo", "Acme"}
_COUNTS = ("attended",)                      # only these count toward target
_GOT_MEETING = {"booked", "attended", "no_show", "cancelled", "not_fit"}
STATUSES = ("said_yes", "booked", "attended", "no_show", "cancelled", "not_fit")
PER_CLIENT_TARGET = 4

_CACHE = {"ts": 0.0, "data": None}
_CACHE_TTL_S = 45


# ── time helpers ────────────────────────────────────────────────────────────
def _month_start(d: date) -> date:
    return d.replace(day=1)


def _weekdays(d: date) -> dict:
    """Mon–Fri counts for the month containing `d` (weekends never send)."""
    first = _month_start(d)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    in_month = gone = 0
    x = first
    while x < nxt:
        if x.weekday() < 5:
            in_month += 1
            if x <= d:
                gone += 1
        x += timedelta(days=1)
    return {"inMonth": in_month, "gone": gone, "left": in_month - gone}


def _iso_month(d: date) -> str:
    return _month_start(d).isoformat()


def _pretty_company(domain: str) -> str:
    dom = (domain or "").strip().lower()
    if not dom or "@" in dom:
        return ""
    core = dom.split("//")[-1].split("/")[0].split(":")[0]
    core = core[4:] if core.startswith("www.") else core
    base = core.split(".")[0]
    return base.replace("-", " ").title() if base else ""


def _days_between(a: str, b: date) -> int:
    try:
        d0 = datetime.fromisoformat(str(a).replace("Z", "+00:00")).date()
    except Exception:  # noqa: BLE001
        return 0
    return max(0, (b - d0).days)


# ── campaign → client label map ─────────────────────────────────────────────
def _campaign_client_map() -> dict:
    """{str(campaign_id): client_label} from the live scorecard, excluding
    DRAFTED campaigns and the Navreo-own / demo labels. This is the same
    resolved label the rest of the app uses (campaign_scorecard.client)."""
    try:
        score = server._inject_demo_scorecard(server._CAMPAIGN_SCORECARD_ALL_SWR.get())
    except Exception as e:  # noqa: BLE001
        print(f"[team_target] scorecard read failed: {e}", file=sys.stderr)
        return {}
    out = {}
    for cid, c in ((score or {}).get("campaigns") or {}).items():
        lbl = (c.get("client") or "").strip()
        if lbl in _EXCLUDE_LABELS:
            continue
        if str(c.get("status") or "").upper() == "DRAFTED":
            continue
        out[str(cid)] = lbl
    return out


def _active_clients(cur_month: str) -> set:
    """Clients that sent this month (client_monthly_stats.sent > 0). Excludes
    Navreo-own and the demo client."""
    rows = server.sb_get_all(
        "client_monthly_stats?select=client,sent&month=eq.%s" % urllib.parse.quote(cur_month)
    ) or []
    active = set()
    for r in rows:
        cl = (r.get("client") or "").strip()
        if cl and cl not in _EXCLUDE_LABELS and int(r.get("sent") or 0) > 0:
            active.add(cl)
    return active


# ── names ───────────────────────────────────────────────────────────────────
def _names_for(emails: set) -> dict:
    """{email: (person, company)} from the people table, best-effort."""
    out = {}
    ems = [e for e in emails if e]
    for i in range(0, len(ems), 200):
        chunk = ems[i:i + 200]
        enc = ",".join(urllib.parse.quote(e, safe="") for e in chunk)
        rows = server.sb("GET", "people?select=email,first_name,last_name,company_domain"
                                "&email=in.(%s)" % enc) or []
        for r in rows or []:
            em = (r.get("email") or "").strip().lower()
            nm = " ".join(x for x in ((r.get("first_name") or "").strip(),
                                      (r.get("last_name") or "").strip()) if x).strip()
            out[em] = (nm, _pretty_company(r.get("company_domain")))
    return out


# ── reply-time (avg speed we reply after a lead's positive reply) ────────────
def _avg_reply_minutes(cur_iso: str) -> float | None:
    rows = server.sb_get_all(
        "setter_queue?select=sent_at,replied_at&status=in.(sent,auto_sent)&is_test=eq.false"
        "&sent_at=not.is.null&replied_at=not.is.null&sent_at=gte.%s" % cur_iso) or []
    mins = []
    for r in rows:
        try:
            st = datetime.fromisoformat(str(r["sent_at"]).replace("Z", "+00:00"))
            rp = datetime.fromisoformat(str(r["replied_at"]).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        m = (st - rp).total_seconds() / 60.0
        if m > 0:
            mins.append(m)
    if not mins:
        return None
    return sum(mins) / len(mins)


def _reply_time_str(mins: float | None) -> str:
    if mins is None:
        return "—"
    if mins < 90:
        return "%d min" % round(mins)
    return "%.1f h" % (mins / 60.0)


# ── the read model ──────────────────────────────────────────────────────────
def _auto_leads(cur_iso: str, cid_client: dict) -> dict:
    """{email: {client, said_yes_on, has_booked, booked_on}} for this month's
    client Meeting-Request / Call-Booked leads, attributed by campaign."""
    cats = urllib.parse.quote("Meeting Request,Call Booked")
    rows = server.sb_get_all(
        "replies?select=smartlead_campaign_id,email,category,replied_at"
        "&category=in.(%s)&replied_at=gte.%s&order=id" % (cats, cur_iso)) or []
    leads: dict = {}
    for r in rows:
        cl = cid_client.get(str(r.get("smartlead_campaign_id")))
        if not cl:                                  # unknown / Navreo-own / subsequence
            continue
        em = (r.get("email") or "").strip().lower()
        if not em:
            continue
        when = str(r.get("replied_at") or "")
        lead = leads.setdefault(em, {"client": cl, "said_yes_on": when,
                                     "has_booked": False, "booked_on": None})
        if when and when < (lead["said_yes_on"] or when):
            lead["said_yes_on"] = when
        if r.get("category") == "Call Booked":
            lead["has_booked"] = True
            if not lead["booked_on"] or when < lead["booked_on"]:
                lead["booked_on"] = when
    return leads


def _team_rows() -> tuple:
    """(overrides {email: row}, hand_adds [row]) from team_meetings."""
    rows = server.sb_get_all("team_meetings?workspace=eq.%s&order=updated_at.desc"
                             % WORKSPACE) or []
    overrides, hand = {}, []
    for r in rows:
        if str(r.get("id") or "").startswith("man:"):
            hand.append(r)
            continue
        em = (r.get("lead_email") or "").strip().lower()
        if em and em not in overrides:              # newest wins (desc order)
            overrides[em] = r
    return overrides, hand


def data(force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL_S:
        return _CACHE["data"]

    today = date.today()
    cur_month = _iso_month(today)
    wk = _weekdays(today)
    cid_client = _campaign_client_map()
    active = _active_clients(cur_month)
    auto = _auto_leads(cur_month, cid_client)
    overrides, hand = _team_rows()

    # Clients in play this month = active senders ∪ anyone with a reply this
    # month. (Stale overrides for churned clients are deliberately NOT unioned
    # here — an override only re-enters a client below if its MEETING is this
    # month; see the orphan-override loop.)
    cur_ym = cur_month[:7]

    def _bucket():
        return {"attended": 0, "booked": 0, "said_yes": 0, "didnt": 0, "waiting": []}

    per = {c: _bucket() for c in (set(active) | {l["client"] for l in auto.values()})
           if c and c not in _EXCLUDE_LABELS}
    meetings = []
    emitted = set()                 # emails already tallied — dedupe across paths
    name_cache = _names_for(set(auto) | set(overrides) |
                            {(r.get("lead_email") or "").strip().lower() for r in hand})

    def _eff(email, auto_lead):
        ov = overrides.get(email)
        if ov:
            return ov.get("status"), ov
        return ("booked" if auto_lead["has_booked"] else "said_yes"), None

    # auto leads (overlaid with team overrides)
    for em, al in auto.items():
        cl = al["client"]
        if cl not in per:
            continue
        status, ov = _eff(em, al)
        person, company = name_cache.get(em, ("", ""))
        if ov:
            person = ov.get("person") or person
            company = ov.get("company") or company
        wait = _days_between(al["said_yes_on"], today)
        meetings.append({"id": "ovr:%s:%s" % (WORKSPACE, em), "email": em, "client": cl,
                         "person": person, "company": company, "status": status,
                         "source": "auto" if not ov else "auto-edited", "waiting_days": wait,
                         "said_yes_on": al["said_yes_on"][:10] if al["said_yes_on"] else "",
                         "booked_on": (al["booked_on"] or "")[:10],
                         "date": (ov.get("meeting_date") if ov else al["booked_on"]) or "",
                         "by": (ov.get("updated_by") if ov else "") or "",
                         "at": (ov.get("updated_at") if ov else "") or ""})
        _tally(per[cl], status, wait, meetings[-1], em)
        emitted.add(em)

    # ORPHAN OVERRIDES — a team outcome for a lead NOT in this month's auto set
    # (said yes in a prior month, met this month). We tally it only when the
    # MEETING itself is this month, so cross-month attended meetings are counted
    # AND stale overrides for old months neither count nor pollute the roster.
    for em, ov in overrides.items():
        if em in auto:
            continue
        cl = (ov.get("client_label") or "").strip()
        if not cl or cl in _EXCLUDE_LABELS:
            continue
        mdate = str(ov.get("meeting_date") or "")
        mmonth = (mdate[:7] if mdate else str(ov.get("updated_at") or "")[:7])
        if mmonth != cur_ym:
            continue
        per.setdefault(cl, _bucket())
        status = ov.get("status") or "booked"
        person, company = name_cache.get(em, ("", ""))
        person = ov.get("person") or person
        company = ov.get("company") or company
        syo = str(ov.get("said_yes_on") or "")
        wait = _days_between(syo or ov.get("updated_at"), today)
        meetings.append({"id": "ovr:%s:%s" % (WORKSPACE, em), "email": em, "client": cl,
                         "person": person, "company": company, "status": status,
                         "source": "auto-edited", "waiting_days": wait,
                         "said_yes_on": syo[:10], "booked_on": "",
                         "date": mdate[:10], "by": ov.get("updated_by") or "",
                         "at": ov.get("updated_at") or ""})
        _tally(per[cl], status, wait, meetings[-1], em)
        emitted.add(em)

    # hand-added meetings (skip excluded clients; dedupe by email vs auto/override)
    for r in hand:
        cl = (r.get("client_label") or "").strip()
        if not cl or cl in _EXCLUDE_LABELS:
            continue
        em = (r.get("lead_email") or "").strip().lower()
        if em and em in emitted:
            continue
        per.setdefault(cl, _bucket())
        status = r.get("status") or "booked"
        wait = _days_between(r.get("said_yes_on") or r.get("created_at"), today)
        meetings.append({"id": r.get("id"), "email": em, "client": cl,
                         "person": r.get("person") or "", "company": r.get("company") or "",
                         "status": status, "source": "hand", "waiting_days": wait,
                         "said_yes_on": str(r.get("said_yes_on") or "")[:10],
                         "booked_on": "", "date": str(r.get("meeting_date") or "")[:10],
                         "by": r.get("updated_by") or r.get("created_by") or "",
                         "at": r.get("updated_at") or r.get("created_at") or ""})
        _tally(per[cl], status, wait, meetings[-1], em or r.get("id"))
        if em:
            emitted.add(em)

    result = _assemble(today, cur_month, wk, active, per, meetings)
    _CACHE.update(ts=now, data=result)
    return result


def _tally(bucket, status, wait, row, key):
    if status == "attended":
        bucket["attended"] += 1
    elif status == "booked":
        bucket["booked"] += 1
    elif status == "said_yes":
        bucket["said_yes"] += 1
        bucket["waiting"].append({"person": row["person"], "company": row["company"],
                                  "client": row["client"], "email": row["email"],
                                  "id": row["id"], "waiting_days": wait})
    else:  # no_show / cancelled / not_fit
        bucket["didnt"] += 1


def _assemble(today, cur_month, wk, active, per, meetings):
    # ONE client base for numerator and denominator: every client in play this
    # month (active senders ∪ anyone with a meeting), so counted/target/avg
    # can't disagree about who is being counted.
    active_clients = len(per) or len(active)
    target = PER_CLIENT_TARGET * active_clients
    counted = sum(b["attended"] for b in per.values())          # ATTENDED only
    booked = sum(b["booked"] for b in per.values())
    said_yes_open = sum(b["said_yes"] for b in per.values())
    gone, in_month = wk["gone"], wk["inMonth"]
    pace = round(counted / gone * in_month) if gone else 0
    should_be = round(target * gone / in_month) if in_month else 0
    behind = should_be - counted
    # "yeses that got booked" = leads that reached a real meeting (attended /
    # booked / no-show / cancelled — it was on the calendar) ÷ everyone who said
    # yes. not_fit stays in the denominator (they said yes) but not the numerator.
    _on_calendar = {"attended", "booked", "no_show", "cancelled"}
    got_booked = sum(1 for m in meetings if m["status"] in _on_calendar)
    total_leads = len(meetings)                                 # one row per lead
    attended_ct = counted
    no_show_ct = sum(1 for m in meetings if m["status"] == "no_show")
    # every open said-yes across clients, longest wait first
    waiting = []
    for c, b in per.items():
        waiting += b["waiting"]
    waiting.sort(key=lambda w: w["waiting_days"], reverse=True)

    clients = []
    for c, b in sorted(per.items(),
                       key=lambda kv: (kv[1]["attended"], -len(kv[1]["waiting"]), kv[0])):
        clients.append({"name": c, "attended": b["attended"], "booked": b["booked"],
                        "said_yes": b["said_yes"], "didnt": b["didnt"],
                        "target": PER_CLIENT_TARGET,
                        "waiting_names": [w["person"] or "(no name)" for w in
                                          sorted(b["waiting"], key=lambda w: w["waiting_days"],
                                                 reverse=True)]})
    reply_min = _avg_reply_minutes(cur_month)
    longest = waiting[0]["waiting_days"] if waiting else 0
    return {
        "month": today.strftime("%B"),
        "month_iso": cur_month[:7],
        "today": today.isoformat(),
        "weekdays": wk,
        "clients_all": [c for c in active],
        "totals": {
            "active_clients": active_clients,
            "target": target,
            "counted": counted,               # attended, the score
            "booked": booked,                 # still to happen
            "said_yes_open": said_yes_open,
            "pace": pace,
            "should_be_today": should_be,
            "behind": behind,
            "avg_per_client": round(counted / active_clients, 1) if active_clients else 0.0,
            "zero_clients": sum(1 for b in per.values() if b["attended"] == 0),
            "clients_on_target": sum(1 for b in per.values()
                                     if b["attended"] >= PER_CLIENT_TARGET),
            "longest_wait": longest,
        },
        "metrics": {
            "reply_time": _reply_time_str(reply_min),
            "reply_time_mins": round(reply_min) if reply_min is not None else None,
            "yes_to_booked_pct": round(100 * got_booked / total_leads) if total_leads else 0,
            "yes_to_booked_num": got_booked,
            "yes_to_booked_den": total_leads,
            "show_up_pct": round(100 * attended_ct / (attended_ct + no_show_ct))
            if (attended_ct + no_show_ct) else None,
            "show_up_num": attended_ct,
            "show_up_den": attended_ct + no_show_ct,
        },
        "clients": clients,
        "chase_next": waiting[:8],
        "meetings": sorted(meetings, key=lambda m: str(m.get("at") or ""), reverse=True),
        "team": server.team_display_names(),
    }


# ── writers ─────────────────────────────────────────────────────────────────
def _uid() -> str:
    import uuid
    return "man:" + uuid.uuid4().hex[:16]


def _write_failed(res) -> bool:
    """sb() returns None on a transport/HTTP failure; a PostgREST error body
    (a dict carrying code/message) can also come back on a 4xx that didn't
    raise. Either way the write did not land."""
    if res is None:
        return True
    if isinstance(res, dict) and (res.get("code") or res.get("message") or res.get("hint")):
        return True
    return False


def add_meeting(payload: dict, who: str) -> tuple:
    client = (payload.get("client") or "").strip()
    person = (payload.get("person") or "").strip()
    if not client or not person:
        return {"error": "client and person are required"}, 400
    if client in _EXCLUDE_LABELS:
        return {"error": "not a client we track"}, 400
    row = {"id": _uid(), "workspace": WORKSPACE, "lead_email": (payload.get("email") or "").strip().lower() or None,
           "client_label": client, "person": person,
           "company": (payload.get("company") or "").strip(),
           "status": "booked", "meeting_date": (payload.get("date") or None),
           "source": "hand", "created_by": who, "updated_by": who}
    res = server.sb("POST", "team_meetings", row, prefer="return=minimal")
    if _write_failed(res):
        return {"error": "could not save"}, 502
    _CACHE["data"] = None
    return {"ok": True, "id": row["id"]}, 200


def set_status(payload: dict, who: str) -> tuple:
    status = (payload.get("status") or "").strip()
    if status not in STATUSES:
        return {"error": "unknown status"}, 400
    if (payload.get("client") or "").strip() in _EXCLUDE_LABELS:
        return {"error": "not a client we track"}, 400
    mid = (payload.get("id") or "").strip()
    now_iso = datetime.utcnow().isoformat() + "Z"
    if mid.startswith("man:"):                       # a hand-added meeting
        patch = {"status": status, "updated_by": who, "updated_at": now_iso}
        if payload.get("date"):
            patch["meeting_date"] = payload["date"]
        res = server.sb("PATCH", "team_meetings?id=eq.%s" % urllib.parse.quote(mid), patch)
        if _write_failed(res):
            return {"error": "could not save"}, 502
        _CACHE["data"] = None
        return {"ok": True}, 200
    # an auto lead → upsert an override keyed by (workspace, lead_email)
    email = (payload.get("email") or "").strip().lower()
    if not email and mid.startswith("ovr:"):
        email = mid.split(":", 2)[2] if mid.count(":") >= 2 else ""
    if not email:
        return {"error": "which lead?"}, 400
    ovid = "ovr:%s:%s" % (WORKSPACE, email)
    row = {"id": ovid, "workspace": WORKSPACE, "lead_email": email,
           "client_label": (payload.get("client") or "").strip() or "?",
           "person": (payload.get("person") or "").strip(),
           "company": (payload.get("company") or "").strip(),
           "status": status, "meeting_date": (payload.get("date") or None),
           "said_yes_on": (payload.get("said_yes_on") or None),
           "source": "auto-override", "updated_by": who, "updated_at": now_iso,
           "created_by": who}
    res = server.sb("POST", "team_meetings?on_conflict=id", row,
                    prefer="resolution=merge-duplicates,return=minimal")
    if _write_failed(res):
        return {"error": "could not save"}, 502
    _CACHE["data"] = None
    return {"ok": True}, 200
