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
from datetime import date, datetime, timedelta, timezone

import server

WORKSPACE = "navreo"
_EXCLUDE_LABELS = {"", "Navreo", "Acme", "navreo", "acme",    # Navreo-own / demo, any case
                   "Asteri", "asteri", "Acquird", "acquird"}  # clients we don't book meetings for
_COUNTS = ("attended",)                      # only these count toward target
_GOT_MEETING = {"booked", "attended", "no_show", "cancelled", "not_fit"}
STATUSES = ("said_yes", "booked", "attended", "no_show", "cancelled", "not_fit")
PER_CLIENT_TARGET = 4
# App-wide positive-reply set (mirrors server._AH_POSITIVE_CATS). Feeds the
# Scoreboard's per-client "Positives" column + the cross-agency positive→booked
# rate — a unique-lead count, not the meetings pipeline.
_POSITIVE_CATS = ("Interested", "Call Booked", "Meeting Request", "Information Request")

_CACHE = {"ts": 0.0, "data": None}
# Lazy request-driven cache (no background timer): re-reads Supabase only when the
# page is loaded AND the cached copy is older than this. 5 min trims repeat reads
# on active refresh; a new meeting request shows within this window (owner 2026-09-22).
_CACHE_TTL_S = 300
_SB_CACHE = {"ts": 0.0, "data": None}         # scoreboard read model (shares _CACHE_TTL_S)


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
    """Every client we run campaigns for — the SAME roster the Analytics page
    shows (distinct campaign_scorecard.client), so the board lists all clients,
    not just this month's senders (owner ask 2026-09-17). Excludes Navreo-own,
    the demo client, and the unassigned bucket."""
    rows = server.sb_get_all("campaign_scorecard?select=client&client=not.is.null") or []
    out = set()
    for r in rows:
        cl = (r.get("client") or "").strip()
        if cl and cl not in _EXCLUDE_LABELS and cl != "__unassigned":
            out.add(cl)
    return out


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


def _attach_phones(meetings: list) -> None:
    """Surface the phone numbers we ALREADY hold for each lead (the setter
    enrichment cache) onto the board cards, so a setter can one-tap dial from the
    card. No new provider spend — reads the cache and reuses the setter's own
    `_harvest_phones`. Sets m['phones'] = [{number, kind, source}] (may be []),
    plus m['notes'] = the setter's shared note on the lead (may be '')."""
    for m in meetings:
        m["phones"] = []
        m["notes"] = ""
    emails = sorted({(m.get("email") or "").strip().lower() for m in meetings if m.get("email")})
    if not emails:
        return
    try:
        from setter import _harvest_phones
    except Exception:
        return
    enr_by = {}
    for i in range(0, len(emails), 200):
        enc = ",".join(urllib.parse.quote(e, safe="") for e in emails[i:i + 200])
        rows = server.sb("GET", "setter_lead_enrichment"
                                "?select=lead_email,phone,phone_source,payload,notes"
                                "&lead_email=in.(%s)" % enc) or []
        for r in rows or []:
            enr_by[(r.get("lead_email") or "").strip().lower()] = r
    for m in meetings:
        enr = enr_by.get((m.get("email") or "").strip().lower())
        if enr:
            # The setter sidebar's shared free-text note on this lead.
            m["notes"] = str(enr.get("notes") or "").strip()
            try:
                m["phones"] = _harvest_phones(enr, "") or []
            except Exception:
                m["phones"] = []


# ── reply-time (avg speed we reply after a lead's positive reply) ────────────
def _et_tz():
    """US Eastern tz (DST-aware); falls back to a fixed EDT offset without tzdata."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=-4))


def _business_minutes(start_utc, end_utc) -> float:
    """Minutes between two instants that fall inside 9am–6pm ET, Mon–Fri, so a
    reply answered the next morning counts only the working-hours gap, not the
    overnight / weekend clock (owner ask 2026-09-19)."""
    tz = _et_tz()
    a, b = start_utc.astimezone(tz), end_utc.astimezone(tz)
    if b <= a:
        return 0.0
    total, d, last = 0.0, a.date(), b.date()
    while d <= last:
        if d.weekday() < 5:                     # Mon–Fri only
            lo = max(a, datetime(d.year, d.month, d.day, 9, 0, tzinfo=tz))
            hi = min(b, datetime(d.year, d.month, d.day, 18, 0, tzinfo=tz))
            if hi > lo:
                total += (hi - lo).total_seconds() / 60.0
        d += timedelta(days=1)
    return total


def _avg_reply_minutes(cur_iso: str) -> float | None:
    """Avg BUSINESS-HOURS minutes from a lead's positive reply to our send — time
    outside 9am–6pm ET, Mon–Fri is not counted, so overnight / weekend gaps don't
    skew the number (owner ask 2026-09-19)."""
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
        m = _business_minutes(rp, st)
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


def _avg_reply_minutes_by_client(cur_iso: str, cid_client: dict) -> dict:
    """{client: avg BUSINESS-HOURS minutes from a lead's positive reply to our
    send}, attributed by campaign — the per-client version of
    _avg_reply_minutes. Same 9am–6pm ET Mon–Fri rule, so overnight / weekend
    gaps don't skew any client's number (owner ask 2026-09-20)."""
    rows = server.sb_get_all(
        "setter_queue?select=sent_at,replied_at,smartlead_campaign_id"
        "&status=in.(sent,auto_sent)&is_test=eq.false"
        "&sent_at=not.is.null&replied_at=not.is.null&sent_at=gte.%s" % cur_iso) or []
    acc: dict = {}                                   # client -> [sum_mins, n]
    for r in rows:
        cl = cid_client.get(str(r.get("smartlead_campaign_id")))
        if not cl or cl in _EXCLUDE_LABELS:
            continue
        try:
            st = datetime.fromisoformat(str(r["sent_at"]).replace("Z", "+00:00"))
            rp = datetime.fromisoformat(str(r["replied_at"]).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        m = _business_minutes(rp, st)
        if m > 0:
            a = acc.setdefault(cl, [0.0, 0])
            a[0] += m
            a[1] += 1
    return {cl: (s / n) for cl, (s, n) in acc.items() if n}


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
        return {"attended": 0, "booked": 0, "said_yes": 0, "didnt": 0,
                "no_show": 0, "cancelled": 0, "not_fit": 0, "waiting": []}

    per = {c: _bucket() for c in (set(active) | {l["client"] for l in auto.values()})
           if c and c not in _EXCLUDE_LABELS}
    meetings = []
    removed = []                    # dismissed leads (status "removed"), for restore
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
        if status == "removed":         # dismissed from the board — hide, don't tally
            emitted.add(em)
            continue
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
        status = ov.get("status") or "booked"
        if status == "removed":         # dismissed — never resurface as active
            continue
        per.setdefault(cl, _bucket())
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
        status = r.get("status") or "booked"
        if status == "removed":         # a soft-removed hand-add (rare; normally hard-deleted)
            continue
        per.setdefault(cl, _bucket())
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

    # "overdue" = a booked meeting whose date has passed and is still unconfirmed
    # (attended / no-show not yet marked). Any booked meeting is flagged the day
    # after its date, whatever its source — surfacing these is the board's job.
    today_iso = today.isoformat()
    for m in meetings:
        d10 = str(m.get("date") or "")[:10]
        m["overdue"] = bool(d10) and m.get("status") == "booked" and d10 < today_iso

    # dismissed (status "removed") auto leads that belong to THIS month — surfaced
    # so the Board can restore them; they are hidden from the active tallies above.
    for em, ov in overrides.items():
        if ov.get("status") != "removed" or em not in auto:
            continue
        person, company = name_cache.get(em, ("", ""))
        removed.append({"id": ov.get("id") or ("ovr:%s:%s" % (WORKSPACE, em)),
                        "email": em, "client": auto[em]["client"],
                        "person": ov.get("person") or person,
                        "company": ov.get("company") or company, "source": "auto"})

    _attach_phones(meetings)
    result = _assemble(today, cur_month, wk, active, per, meetings, removed)
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
        if status in ("no_show", "cancelled", "not_fit"):
            bucket[status] += 1


def _assemble(today, cur_month, wk, active, per, meetings, removed=None):
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
                        "no_show": b["no_show"], "cancelled": b["cancelled"],
                        "not_fit": b["not_fit"],
                        # meetings that reached the calendar (a no-show was still a
                        # booking); not_fit never was a real meeting so it is out.
                        "meetings": b["attended"] + b["booked"] + b["no_show"] + b["cancelled"],
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
        "removed": removed or [],
        "team": server.team_display_names(),
    }


# ── scoreboard read model (Scoreboard tab) ──────────────────────────────────
def _positive_counts(cur_iso: str, cid_client: dict) -> dict:
    """{client: N} — UNIQUE leads with a positive-category reply this month,
    attributed by campaign (client campaigns only, same as the meetings pull).
    Mirrors the app-wide positive set so the number agrees with Analytics."""
    cats = urllib.parse.quote(",".join(_POSITIVE_CATS))
    rows = server.sb_get_all(
        "replies?select=smartlead_campaign_id,email,category,replied_at"
        "&category=in.(%s)&replied_at=gte.%s&order=id" % (cats, cur_iso)) or []
    seen: dict = {}
    for r in rows:
        cl = cid_client.get(str(r.get("smartlead_campaign_id")))
        if not cl or cl in _EXCLUDE_LABELS:
            continue
        em = (r.get("email") or "").strip().lower()
        if not em:
            continue
        seen.setdefault(cl, set()).add(em)
    return {cl: len(s) for cl, s in seen.items()}


def _cal_days(d: date) -> dict:
    """Calendar days for the human-facing 'days left' card + KPI subtitle
    (the pace MARK stays weekday-based to agree with the hero bar)."""
    first = _month_start(d)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    total = (nxt - first).days
    gone = (d - first).days + 1                # today counts as elapsed
    return {"total": total, "gone": gone, "left": max(0, total - gone)}


def _client_status(meetings: int, positives: int, pace_mark: float) -> tuple:
    """(label, tone) ladder for a client row. tone ∈ good|warn|bad|muted."""
    if positives == 0 and meetings == 0:
        return "Not scored yet", "muted"          # launched, nothing landed yet
    if meetings >= PER_CLIENT_TARGET:
        return "On target", "good"
    if meetings == 0:
        return "No meetings yet", "bad"           # positives but nothing booked
    if meetings >= pace_mark:
        return "On pace", "good"
    return "Behind pace", "warn"


def scoreboard(force: bool = False) -> dict:
    """Read model for /app/scoreboard.html. Reuses data() for the meetings
    pipeline (so the hero bar and Team Target never disagree) and adds the
    per-client positive-reply count + the scoreboard aggregates/charts."""
    now = time.time()
    if not force and _SB_CACHE["data"] is not None and (now - _SB_CACHE["ts"]) < _CACHE_TTL_S:
        return _SB_CACHE["data"]

    base = data(force=force)
    today = date.fromisoformat(base["today"])
    cur_iso = _iso_month(today)
    cid_client = _campaign_client_map()
    pos = _positive_counts(cur_iso, cid_client)
    reply_by_client = _avg_reply_minutes_by_client(cur_iso, cid_client)
    wk = base["weekdays"]
    cal = _cal_days(today)
    pace_mark = round(PER_CLIENT_TARGET * wk["gone"] / wk["inMonth"], 1) if wk["inMonth"] else 0.0

    rows = []
    for c in base["clients"]:
        meetings = c["meetings"]
        positives = pos.get(c["name"], 0)
        label, tone = _client_status(meetings, positives, pace_mark)
        rmins = reply_by_client.get(c["name"])
        rows.append({
            "name": c["name"], "positives": positives, "meetings": meetings,
            "attended": c["attended"], "booked": c["booked"], "said_yes": c["said_yes"],
            "no_show": c["no_show"], "target": PER_CLIENT_TARGET,
            # per-client avg business-hours reply time (mins); None when we've
            # sent no replies for them this month
            "reply_mins": round(rmins) if rmins is not None else None,
            "scored": bool(positives or meetings), "status": label, "tone": tone,
        })
    # scored clients first (most meetings, then most positives), not-scored last
    rows.sort(key=lambda r: (0 if r["scored"] else 1, -r["meetings"], -r["positives"],
                             r["name"].lower()))

    scored = [r for r in rows if r["scored"]]
    total_meetings = sum(r["meetings"] for r in rows)
    return_data = {
        "month": base["month"],
        "month_iso": base["month_iso"],
        "today": base["today"],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "per_client_target": PER_CLIENT_TARGET,
        "pace_mark": pace_mark,
        "cal_days": cal,
        "weekdays": wk,
        # hero bar reuses the SAME totals as Team Target (attended / booked /
        # said-yes-open pipeline against the 4×clients target)
        "totals": base["totals"],
        "cards": {
            "clients_on_target": sum(1 for r in rows if r["meetings"] >= PER_CLIENT_TARGET),
            "scored_clients": len(scored),
            "total_clients": len(rows),
            "total_meetings": total_meetings,
            "zero_meeting_clients": sum(1 for r in scored if r["meetings"] == 0),
            "days_left": cal["left"],
            # the four headline stat cards. avg is ATTENDED per client (owner
            # 2026-09-20) — matches the "of 4" attended target + the hero count,
            # not the broader meetings metric (which no-shows/cancelled inflate).
            "avg_meetings_per_client": round(base["totals"]["counted"] / len(rows), 1) if rows else 0.0,
            "attended": base["totals"]["counted"],
            # run-rate differential: where this month's pace projects us to finish
            # minus the target (negative = short of target at today's pace)
            "runrate_diff": base["totals"]["pace"] - base["totals"]["target"],
            "avg_response_mins": base["metrics"]["reply_time_mins"],
            # cross-agency conversion rates (aggregate across every client)
            "total_positives": sum(r["positives"] for r in rows),
            "pos_to_booked_pct": (round(100 * total_meetings / sum(r["positives"] for r in rows))
                                  if sum(r["positives"] for r in rows) else None),
            "show_up_pct": base["metrics"]["show_up_pct"],
            "show_up_num": base["metrics"]["show_up_num"],
            "show_up_den": base["metrics"]["show_up_den"],
        },
        # "clients" carries per-client attended/booked/said_yes — the Scoreboard's
        # "Meetings attended vs target" chart builds its stacked bars from these,
        # so there's no separate chart array.
        "clients": rows,
        "team": base.get("team", {}),
    }
    _SB_CACHE.update(ts=now, data=return_data)
    return return_data


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
    # the Board can add a lead in any stage; default stays "booked"
    status = (payload.get("status") or "booked").strip()
    if status not in ("said_yes", "booked", "attended", "no_show", "cancelled"):
        status = "booked"
    when = (payload.get("date") or None)
    row = {"id": _uid(), "workspace": WORKSPACE, "lead_email": (payload.get("email") or "").strip().lower() or None,
           "client_label": client, "person": person,
           "company": (payload.get("company") or "").strip(),
           "status": status,
           "meeting_date": when if status in ("booked", "attended", "no_show", "cancelled") else None,
           "said_yes_on": when if status == "said_yes" else None,
           "source": "hand", "created_by": who, "updated_by": who}
    res = server.sb("POST", "team_meetings", row, prefer="return=minimal")
    if _write_failed(res):
        return {"error": "could not save"}, 502
    _CACHE["data"] = None
    _SB_CACHE["data"] = None
    return {"ok": True, "id": row["id"]}, 200


def dismiss(payload: dict, who: str) -> tuple:
    """Remove a lead from the board. Hand-added rows (man:) are hard-deleted;
    auto-pulled leads are soft-removed via an override (status "removed") so they
    don't reappear on the next reply sync — restorable from the Board."""
    mid = (payload.get("id") or "").strip()
    if mid.startswith("man:"):
        res = server.sb("DELETE", "team_meetings?id=eq.%s" % urllib.parse.quote(mid))
        if _write_failed(res):
            return {"error": "could not remove"}, 502
        _CACHE["data"] = None
        _SB_CACHE["data"] = None
        return {"ok": True, "mode": "deleted"}, 200
    email = (payload.get("email") or "").strip().lower()
    if not email and mid.startswith("ovr:"):
        email = mid.split(":", 2)[2] if mid.count(":") >= 2 else ""
    if not email:
        return {"error": "which lead?"}, 400
    now_iso = datetime.utcnow().isoformat() + "Z"
    row = {"id": "ovr:%s:%s" % (WORKSPACE, email), "workspace": WORKSPACE, "lead_email": email,
           "client_label": (payload.get("client") or "").strip() or "?",
           "person": (payload.get("person") or "").strip(),
           "company": (payload.get("company") or "").strip(),
           "status": "removed", "said_yes_on": (payload.get("said_yes_on") or None),
           "source": "auto-override", "updated_by": who, "updated_at": now_iso, "created_by": who}
    res = server.sb("POST", "team_meetings?on_conflict=id", row,
                    prefer="resolution=merge-duplicates,return=minimal")
    if _write_failed(res):
        return {"error": "could not remove"}, 502
    _CACHE["data"] = None
    _SB_CACHE["data"] = None
    return {"ok": True, "mode": "removed"}, 200


def set_note(payload: dict, who: str) -> tuple:
    """Edit the lead's shared setter note from a board card. Writes through the
    setter's own endpoint (same setter_lead_enrichment row the setter sidebar
    edits), then patches the cached board in place so a reload inside the cache
    window shows the new note instead of the old one."""
    from setter import route_lead_note_post
    email = (payload.get("email") or "").strip().lower()
    notes = str(payload.get("notes") or "")
    status, body = route_lead_note_post({"email": email, "notes": notes})
    if status == 200:
        for cache in (_CACHE, _SB_CACHE):
            d = cache.get("data") or {}
            for m in (d.get("meetings") or []) if isinstance(d, dict) else []:
                if (m.get("email") or "").strip().lower() == email:
                    m["notes"] = notes.strip()
    return body, status


def restore(payload: dict, who: str) -> tuple:
    """Undo a soft-remove: delete the override so the auto lead reverts to its
    live status. (Hand-added rows were hard-deleted and can't be restored.)"""
    mid = (payload.get("id") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    if not email and mid.startswith("ovr:"):
        email = mid.split(":", 2)[2] if mid.count(":") >= 2 else ""
    if not email:
        return {"error": "which lead?"}, 400
    res = server.sb("DELETE", "team_meetings?id=eq.%s"
                    % urllib.parse.quote("ovr:%s:%s" % (WORKSPACE, email)))
    if _write_failed(res):
        return {"error": "could not restore"}, 502
    _CACHE["data"] = None
    _SB_CACHE["data"] = None
    return {"ok": True}, 200


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
        # a full edit (from the card dialog) also carries person / company / client
        if payload.get("client"):
            patch["client_label"] = payload["client"].strip()
        if payload.get("person") is not None:
            patch["person"] = (payload.get("person") or "").strip()
        if payload.get("company") is not None:
            patch["company"] = (payload.get("company") or "").strip()
        if payload.get("date"):
            patch["meeting_date"] = payload["date"]
        if payload.get("said_yes_on") is not None:
            patch["said_yes_on"] = payload.get("said_yes_on") or None
        res = server.sb("PATCH", "team_meetings?id=eq.%s" % urllib.parse.quote(mid), patch)
        if _write_failed(res):
            return {"error": "could not save"}, 502
        _CACHE["data"] = None
        _SB_CACHE["data"] = None
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
    _SB_CACHE["data"] = None
    return {"ok": True}, 200
