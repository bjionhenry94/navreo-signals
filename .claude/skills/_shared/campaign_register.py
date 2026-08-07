"""Register a Smartlead campaign in the signals tool. One call, three writes.

Why this exists
---------------
Creating a campaign in Smartlead is only half the job. For the tool to show it with
its provenance — the Leads tab, the Sources list, and the "pull more" button — three
records have to exist:

    campaigns          the row the cockpit lists
    campaign_drafts    doc id `camp-sl-<smartlead_id>`, joins draft -> Smartlead
    sources            doc with campaign_id = the draft id, carrying the pull spec,
                       the prospects, the list_id, and how much pool is left

That wiring used to live inside the campaign-building skills, so any ad-hoc build
(raw Smartlead API calls from a python heredoc) created a campaign the tool could not
explain: no source, no provenance, no pull-more. Exactly the failure mode the list
auto-upload rule already had, and fixed the same way — move the rule out of the skills
and into the act itself, with a Stop hook (campaign-register-guard.sh) as the backstop.

Bjion, 2026-07-27: "Whenever we create these campaigns this should be automatic."

Usage
-----
    import sys; sys.path.insert(0, '/Users/bjionhenry/.claude/skills/_shared')
    import campaign_register
    campaign_register.register(
        smartlead_campaign_id=3723684,
        name="Navreo | Hiring for growth | Jul 2026",
        client="navreo",
        mechanism="hiring",
        source_name="Companies hiring for growth roles",
        list_id="b1d64adc-...",           # the Lists-tool id from list_upload
        prospects=[{...}],                 # the rows actually pushed
        pull_spec={...},                   # the exact provider filter shape
        pool_total=2777, pool_pulled=708,  # so pull-more knows what is left
        icebreaker="Saw you're hiring...",
        status="DRAFTED",
    )
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import navreo_db  # noqa: E402

RECEIPTS = os.path.expanduser("~/.claude/state/campaign_registrations.jsonl")

# What actually feeds the campaign. The first four are SIGNALS — something
# happened out there and the source goes back daily for the next one; the tool
# gives them a live toggle and a daily pull. `fixed_list` is a one-off pull: a
# finite set of people bought once on a set of filters, which never refreshes.
# Passing `mechanism="hiring"` for a fixed list is what put a HIRING badge and
# an armed Live toggle on three one-off Prospeo pulls on 27 Jul 2026 (Bjion: a
# fixed list must never be dressed up as a signal), hence the check below.
MECHANISMS = ("hiring", "engagement", "followers", "lookalike", "fixed_list")


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def register(smartlead_campaign_id, name, client="navreo", *, mechanism="hiring",
             source_name=None, list_id=None, prospects=None, pull_spec=None,
             pool_total=None, pool_pulled=None, icebreaker=None, goal=None,
             status="DRAFTED", workspace=None, dm_titles=None, geos=None,
             sizes=None, industries=None, repull_spec=None):
    """Write the three records. Idempotent: re-running upserts by id.

    `mechanism` must be one of MECHANISMS — use "fixed_list" for a one-off
    pulled list, never a signal name. `repull_spec` is the provider filter dict
    a fixed list can be pulled again with; it lands at params.repull and is the
    ONLY thing that arms "Find people again" on a fixed list. Leave it None
    when the list can't be re-pulled.

    Returns {"campaign": id, "draft": id, "source": id, "campaign_url": url}.
    """
    if mechanism not in MECHANISMS:
        raise ValueError(f"mechanism must be one of {MECHANISMS}, got {mechanism!r}. "
                         "A one-off pulled list is 'fixed_list', not a signal name.")
    sid = str(smartlead_campaign_id)
    draft_id = f"camp-sl-{sid}"
    src_id = source_name and f"src-{sid}" or f"src-{sid}"
    prospects = prospects or []
    n = navreo_db.db() if hasattr(navreo_db, "db") else navreo_db

    def rest(method, path, **kw):
        return n.rest(method, path, **kw)

    # 1 — the campaigns row the cockpit lists
    rest("POST", "/rest/v1/campaigns",
         prefer="resolution=merge-duplicates,return=minimal",
         payload=[{"workspace": workspace or client, "smartlead_campaign_id": int(sid),
                   "client_id": client, "name": name, "status": status,
                   "created_at_smartlead": _now()}])

    # 2 — the draft doc that joins the tool's campaign to Smartlead
    icp = {"geos": geos or [], "sizes": sizes or [], "titles": dm_titles or [],
           "domains": [], "excludes": [], "keywords": "", "industries": industries or []}
    draft = {"id": draft_id, "name": name, "client_id": client,
             "goal": goal or "", "paused": status != "ACTIVE", "platform": "smartlead",
             "autopilot": False, "smartlead_campaign_id": sid,
             "destination": {"smartlead_campaign_id": sid, "platform": "smartlead"},
             "created_at": _now(), "total_matched": len(prospects), "icp": icp,
             "sources": [{"dms": len(prospects), "idea": source_name or name,
                          "params": pull_spec or {}, "source_id": src_id,
                          "list_id": list_id}]}
    rest("POST", "/rest/v1/campaign_drafts?on_conflict=id",
         prefer="resolution=merge-duplicates,return=minimal",
         payload=[{"id": draft_id, "doc": draft}])

    # 3 — the source doc: provenance + what is left to pull
    left = None
    if pool_total is not None and pool_pulled is not None:
        left = max(int(pool_total) - int(pool_pulled), 0)
    params = dict(pull_spec or {})
    if repull_spec:
        params["repull"] = repull_spec
    src = {"id": src_id, "campaign_id": draft_id, "client_id": client,
           "name": source_name or name, "type": mechanism, "mechanism": mechanism,
           "list_id": list_id, "total": len(prospects),
           "signals_found": pool_pulled, "companies_scanned": pool_pulled,
           "left_for_next_run": left, "window_exhausted": left == 0 if left is not None else False,
           "last_pull": _now(), "icebreaker": icebreaker or "",
           "titles": dm_titles or [], "config": {"countries": geos or [], "headcount": sizes or [],
                                                 "industries": industries or [], "keywords": ""},
           "params": params, "prospects": prospects}
    if mechanism == "fixed_list":
        src["active"] = False  # nothing to keep running; the daily pull skips it

    rest("POST", "/rest/v1/sources?on_conflict=id",
         prefer="resolution=merge-duplicates,return=minimal",
         payload=[{"id": src_id, "doc": src}])

    os.makedirs(os.path.dirname(RECEIPTS), exist_ok=True)
    with open(RECEIPTS, "a") as f:
        f.write(json.dumps({"smartlead_campaign_id": sid, "draft_id": draft_id,
                            "source_id": src_id, "list_id": list_id,
                            "rows": len(prospects), "at": _now()}) + "\n")

    return {"campaign": sid, "draft": draft_id, "source": src_id,
            "campaign_url": f"https://navreo-signals.onrender.com/app/campaigns.html#/c/{sid}"}


def is_registered(smartlead_campaign_id) -> bool:
    """True when the draft AND at least one source exist for this Smartlead id."""
    sid = str(smartlead_campaign_id)
    n = navreo_db.db() if hasattr(navreo_db, "db") else navreo_db
    draft = n.rest("GET", "/rest/v1/campaign_drafts",
                   params={"select": "id", "id": f"eq.camp-sl-{sid}"}) or []
    if not draft:
        return False
    srcs = n.rest("GET", "/rest/v1/sources", params={"select": "id,doc", "limit": "500"}) or []
    return any((s.get("doc") or {}).get("campaign_id") == f"camp-sl-{sid}" for s in srcs)
