"""Regression lock for the 2026-07-08 credit burn: 7 hiring sources x ~100 jobs
x 8 ticks/day re-bought the same 30-day window every 3 hours (~12k credits ->
~350 companies), because TheirStack bills 1 credit per job RETURNED and charges
again for jobs already downloaded.

Locks four properties of the fix:
  1. first pull (no cursor) buys the window and records the discovered_at watermark
  2. second pull sends discovered_at_gte + job_id_not -> pays only for new jobs
  3. a page whose jobs are ALL dropped client-side still advances the cursor
     (otherwise that page is re-bought forever)
  4. the daily credit cap stops calls dead, and never silently reports "no jobs"

Deterministic: no live network, no credits, no Supabase.
Run:  python3 app/test_theirstack_credits.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

server.KEYS.setdefault("THEIRSTACK_API_KEY", "test-key")
FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def job(jid, discovered_at, domain="acme.com", title="Account Executive", company="Acme"):
    return {"id": jid, "discovered_at": discovered_at, "job_title": title,
            "date_posted": "2026-07-07", "url": f"https://x/{jid}", "country_code": "US",
            "company_object": {"domain": domain, "name": company, "industry": "Software Development",
                               "employee_count": 50}}


class Recorder:
    """Captures the request bodies TheirStack would have been sent."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.bodies = []

    def __call__(self, method, url, headers, body=None):
        self.bodies.append(body)
        return {"data": self.pages.pop(0) if self.pages else [],
                "metadata": {"total_results": 999}}


def stub_meter_and_cap(spent_today=0):
    """Neutralise Supabase: metering is a no-op, spend is whatever we say."""
    server._theirstack_meter = lambda *a, **k: None
    server.theirstack_credits_today = lambda: spent_today


# ── 1 + 2: cursor is recorded, then spent ────────────────────────────────
def test_cursor_round_trip():
    stub_meter_and_cap()
    orig = server.http_json
    try:
        rec = Recorder([[job(1, "2026-07-07T10:00:00Z"), job(2, "2026-07-07T12:00:00Z", "beta.com")],
                        [job(3, "2026-07-07T15:00:00Z", "gamma.com")]])
        server.http_json = rec

        jobs, meta = server.theirstack_jobs(["AE"], ["US"], 11, 500, 30, limit=100)
        check("first pull sends no discovered_at_gte", "discovered_at_gte" not in rec.bodies[0])
        check("first pull is billed for every job returned", meta["_credits"] == 2, meta["_credits"])
        check("watermark = newest discovered_at", meta["_max_discovered_at"] == "2026-07-07T12:00:00Z",
              meta["_max_discovered_at"])
        check("watermark ids = jobs on that exact stamp", meta["_max_discovered_ids"] == [2],
              meta["_max_discovered_ids"])
        check("both jobs kept", len(jobs) == 2)

        # second pull, cursor applied exactly as pull_hiring_source builds it
        extra = {"discovered_at_gte": meta["_max_discovered_at"], "job_id_not": meta["_max_discovered_ids"]}
        _jobs2, meta2 = server.theirstack_jobs(["AE"], ["US"], 11, 500, 30, limit=100, extra=extra)
        b = rec.bodies[1]
        check("second pull cursors on discovered_at_gte", b.get("discovered_at_gte") == "2026-07-07T12:00:00Z")
        check("second pull excludes the boundary job id", b.get("job_id_not") == [2])
        check("second pull orders oldest-first (never strands a full page)",
              b.get("order_by") == [{"field": "discovered_at", "desc": False}], b.get("order_by"))
        check("second pull pays only for the new job", meta2["_credits"] == 1, meta2["_credits"])
        check("cursor advances again", meta2["_max_discovered_at"] == "2026-07-07T15:00:00Z")
    finally:
        server.http_json = orig


# ── 3: a fully-filtered page must STILL advance the cursor ───────────────
def test_filtered_page_still_advances_cursor():
    stub_meter_and_cap()
    orig = server.http_json
    try:
        # every job is killed client-side (staffing agency), so jobs == []
        rec = Recorder([[job(9, "2026-07-07T18:00:00Z", "hire.com", company="Talent Staffing Co")]])
        server.http_json = rec
        jobs, meta = server.theirstack_jobs(["AE"], ["US"], 11, 500, 30, limit=100)
        check("filtered page yields no usable jobs", jobs == [])
        check("but it WAS billed", meta["_credits"] == 1)
        check("and the cursor still advances (page never re-bought)",
              meta["_max_discovered_at"] == "2026-07-07T18:00:00Z", meta["_max_discovered_at"])
    finally:
        server.http_json = orig


# ── 4: the daily cap is a hard stop, and says so ─────────────────────────
def test_daily_cap_blocks():
    """The credit cap is an OPT-IN emergency brake (default 0 = off). Spend is
    normally governed by SIGNAL_DAILY_LEADS, not by a credit ceiling."""
    orig_cap = server.THEIRSTACK_DAILY_CAP
    server.THEIRSTACK_DAILY_CAP = 500          # arm it
    stub_meter_and_cap(spent_today=500)
    called = []
    orig = server.http_json
    try:
        server.http_json = lambda *a, **k: called.append(1) or {"data": [job(1, "2026-07-07T10:00:00Z")]}
        jobs, meta = server.theirstack_jobs(["AE"], ["US"], 11, 500, 30, limit=100)
        check("cap prevents the HTTP call entirely", not called)
        check("cap returns zero jobs", jobs == [])
        check("cap surfaces an _error (not a silent 'no jobs today')", bool(meta.get("_error")))
        check("cap is flagged for the caller", meta.get("_capped") is True)

        # and it must not fire when Supabase can't be read (unknown spend != blocked)
        server.theirstack_credits_today = lambda: None
        called.clear()
        server.theirstack_jobs(["AE"], ["US"], 11, 500, 30, limit=100)
        check("unknown spend does not block the pull", len(called) == 1)

        # disarmed (0) -> the ledger is never even consulted
        server.THEIRSTACK_DAILY_CAP = 0
        server.theirstack_credits_today = lambda: (_ for _ in ()).throw(AssertionError("consulted"))
        called.clear()
        server.theirstack_jobs(["AE"], ["US"], 11, 500, 30, limit=100)
        check("cap off by default: spend governed by leads, not credits", len(called) == 1)
    finally:
        server.http_json = orig
        server.THEIRSTACK_DAILY_CAP = orig_cap


# ── 5-7: pull_hiring_source pages until the DAILY lead budget is filled ──
class FakeSB:
    """Just enough PostgREST to run pull_hiring_source offline."""

    def __init__(self, leads_today=0):
        self.signals = []          # {id, company_domain, detail, enriched_at}
        self.leads = []
        self.leads_today = leads_today
        self._next = 1

    def __call__(self, method, path, body=None, prefer=""):
        t = path.split("?")[0]
        if method == "GET" and t == "signal_leads" and "select=count" in path:
            return [{"count": self.leads_today}]
        if method == "GET" and t == "signals" and "select=count" in path:
            return [{"count": sum(1 for s in self.signals if s["enriched_at"] is None)}]
        if method == "GET" and t == "signals" and "enriched_at=is.null" in path:
            lim = int(path.split("limit=")[1].split("&")[0])
            return [s for s in self.signals if s["enriched_at"] is None][:lim]
        if method == "GET" and t == "signals":               # the 90-day re-touch skip
            return [{"company_domain": s["company_domain"]} for s in self.signals]
        if method == "POST" and t == "signals":
            if any(s["company_domain"] == body["company_domain"] for s in self.signals):
                return []                                     # ignore-duplicates
            self.signals.append({"id": self._next, "company_domain": body["company_domain"],
                                 "detail": body["detail"], "enriched_at": None})
            self._next += 1
            return []
        if method == "PATCH" and t == "signals":
            ids = {int(x) for x in path.split("in.(")[1].rstrip(")").split(",") if x}
            for s in self.signals:
                if s["id"] in ids:
                    s["enriched_at"] = "now"
            return []
        if method == "POST" and t == "signal_leads":
            self.leads += body if isinstance(body, list) else [body]
            return []
        return []                                             # companies / sources / signal_sources


def build_source(leads_per_day=None):
    params = {"job_titles": ["Account Executive"], "countries": ["United States"],
              "headcount": "11-200", "days": 30}
    if leads_per_day:
        params["leads_per_day"] = leads_per_day
    return {"id": "src-test", "campaign_id": "camp-1", "mechanism": "hiring",
            "icebreaker": "Saw {{company}} hiring a {{job_title}}.",
            "titles": ["VP Sales"], "config": params}


def run_pull(fake, pages, dm_hit_rate=2):
    """Drive pull_hiring_source with stubbed providers. dm_hit_rate=2 -> every 2nd
    company yields one decision-maker, mirroring the ~55% no-DM reality."""
    saved = {k: getattr(server, k) for k in
             ("sb", "http_json", "dm_find_by_domain", "find_email", "is_suppressed",
              "write_drafts", "sb_sync_source", "read_json_list", "theirstack_credits_today",
              "_theirstack_meter")}
    server.sb = fake
    server.http_json = Recorder(pages)
    server.theirstack_credits_today = lambda: 0
    server._theirstack_meter = lambda *a, **k: None
    server.is_suppressed = lambda *a, **k: False
    server.write_drafts = lambda *a, **k: None
    server.sb_sync_source = lambda *a, **k: None
    server.read_json_list = lambda *a, **k: []
    seen = {"n": 0}

    def dm(domain, dm_titles, max_dms):
        seen["n"] += 1
        if max_dms <= 0 or seen["n"] % dm_hit_rate:
            return []
        return [{"name": f"P{seen['n']}", "title": "VP Sales", "company": "Acme",
                 "domain": domain, "linkedin": f"https://li/{seen['n']}"}]

    server.dm_find_by_domain = dm
    server.find_email = lambda p: f"{p['name'].lower()}@{p['domain']}"
    try:
        src = build_source(10)
        return server.pull_hiring_source(src, [src]), src, server.http_json
    finally:
        for k, v in saved.items():
            setattr(server, k, v)


def test_pages_until_budget_filled():
    # 3 pages x 100 jobs, unique domains. Only every 2nd company yields a DM, so
    # 10 leads needs ~20 companies: one page must NOT be enough to stop early...
    # ...but 100 companies/page IS enough, so exactly one page should be bought.
    pages = [[job(i, f"2026-07-07T{10 + p:02d}:00:00Z", f"co{p}-{i}.com") for i in range(p * 100, p * 100 + 100)]
             for p in range(3)]
    fake = FakeSB(leads_today=0)
    res, src, rec = run_pull(fake, pages)
    check("pull succeeds", res.get("ok") is True, res.get("message"))
    check("stops at exactly the daily lead budget", len(res["prospects"]) == 10, len(res.get("prospects", [])))
    check("buys only the pages it needed", src["jobs_bought"] == 100, src["jobs_bought"])
    check("banks every bought company as a signal", len(fake.signals) == 100, len(fake.signals))
    unenriched = sum(1 for s in fake.signals if s["enriched_at"] is None)
    check("un-enriched remainder is kept as backlog, not discarded", unenriched > 0, unenriched)
    check("reported backlog matches", src["left_for_next_run"] == unenriched)
    check("cursor persisted for the next tick", bool(src.get("last_discovered_at")))


def test_daily_leads_split_evenly():
    """SIGNAL_DAILY_LEADS is a fleet TOTAL, divided evenly across active hiring
    sources. Adding a source narrows everyone's share instead of multiplying the
    bill, and a source's own leads_per_day can only ask for LESS than its share."""
    orig = server.SIGNAL_DAILY_LEADS
    server.SIGNAL_DAILY_LEADS = 160
    try:
        def src(i, lpd=None, **kw):
            s = {"id": f"s{i}", "mechanism": "hiring", "config": {}}
            if lpd:
                s["config"]["leads_per_day"] = lpd
            s.update(kw)
            return s

        four = [src(i) for i in range(4)]
        check("160 across 4 active sources -> 40 each",
              server._daily_lead_share(four[0], four) == 40, server._daily_lead_share(four[0], four))

        five = [src(i) for i in range(5)]
        check("adding a 5th source narrows the share, not the bill",
              server._daily_lead_share(five[0], five) == 32, server._daily_lead_share(five[0], five))

        one = [src(0)]
        check("a lone source takes the whole budget", server._daily_lead_share(one[0], one) == 160)

        # a stale/oversized per-source number must not be able to exceed the share
        greedy = [src(0, lpd=300)] + [src(i) for i in range(1, 4)]
        check("per-source leads_per_day cannot exceed its even share",
              server._daily_lead_share(greedy[0], greedy) == 40, server._daily_lead_share(greedy[0], greedy))

        modest = [src(0, lpd=5)] + [src(i) for i in range(1, 4)]
        check("but a source may ask for less", server._daily_lead_share(modest[0], modest) == 5)

        # deleted / inactive sources don't dilute the split
        mixed = [src(0), src(1), src(2, deleted_at="2026-07-07"), src(3, active=False)]
        check("deleted and inactive sources are excluded from the split",
              server._daily_lead_share(mixed[0], mixed) == 80, server._daily_lead_share(mixed[0], mixed))
    finally:
        server.SIGNAL_DAILY_LEADS = orig


def test_preview_stays_free():
    """The preview must remain a blurred sample: 0 credits, no cursor, no pagination.
    Only the live pull is allowed to purchase."""
    orig = server.http_json
    try:
        rec = Recorder([[job(1, "2026-07-07T10:00:00Z")]])
        server.http_json = rec
        server.preview_hiring({"job_titles": ["Account Executive"], "countries": ["United States"],
                               "headcount": "11-200", "days": 14})
        b = rec.bodies[0]
        check("preview is blurred (TheirStack bills 0 for blurred rows)",
              b.get("blur_company_data") is True, b.get("blur_company_data"))
        check("preview never cursors", "discovered_at_gte" not in b)
        check("preview asks for a sample, not a page", int(b.get("limit", 999)) <= 25, b.get("limit"))
        check("preview makes exactly one call", len(rec.bodies) == 1, len(rec.bodies))
    finally:
        server.http_json = orig


def test_goes_beyond_page_one():
    """THE regression this whole change exists for: one 100-job page yields nowhere
    near leads_per_day, so the pull must keep buying pages until the budget is met.
    Here only every 25th company has a reachable DM -> page 1 gives 4 leads, so it
    has to walk on to pages 2 and 3."""
    pages = [[job(i, f"2026-07-07T{10 + p:02d}:00:00Z", f"co{p}-{i}.com") for i in range(p * 100, p * 100 + 100)]
             for p in range(3)]
    fake = FakeSB(leads_today=0)
    res, src, rec = run_pull(fake, pages, dm_hit_rate=12)
    check("pull succeeds", res.get("ok") is True, res.get("message"))
    check("walked past page one", len(rec.bodies) >= 2, f"{len(rec.bodies)} calls")
    check("bought more than 100 jobs", src["jobs_bought"] > 100, src["jobs_bought"])
    check("filled the full daily budget", len(res["prospects"]) == 10, len(res["prospects"]))
    check("each page cursored forward, never re-bought page one",
          [b.get("discovered_at_gte") for b in rec.bodies] == sorted(
              b.get("discovered_at_gte") for b in rec.bodies),
          [b.get("discovered_at_gte") for b in rec.bodies])
    check("every page after the first excludes the previous boundary id",
          all("job_id_not" in b for b in rec.bodies[1:]))


def test_budget_spent_buys_nothing():
    """The 3-hourly tick must be FREE once the day's leads are in. This is the bug
    that made leads_per_day an 8x-per-day allowance instead of a daily one."""
    fake = FakeSB(leads_today=10)   # budget already filled today
    res, src, rec = run_pull(fake, [[job(1, "2026-07-07T10:00:00Z")]])
    check("pull declines to run", res.get("ok") is False)
    check("says the budget is full", "budget" in (res.get("message") or "").lower())
    check("ZERO TheirStack calls made", len(rec.bodies) == 0, len(rec.bodies))


def test_backlog_drained_before_buying():
    """Companies already paid for must be enriched before a single new job is bought."""
    fake = FakeSB(leads_today=0)
    for i in range(40):  # yesterday's unenriched remainder
        fake.signals.append({"id": i + 1, "company_domain": f"old{i}.com",
                             "detail": {"job_title": "AE", "job_url": "", "company": "Old",
                                        "source_id": "src-test"}, "enriched_at": None})
        fake._next = i + 2
    res, src, rec = run_pull(fake, [[job(1, "2026-07-07T10:00:00Z")]])
    check("budget filled entirely from the backlog", len(res.get("prospects") or []) == 10,
          len(res.get("prospects") or []))
    check("no new jobs bought", src["jobs_bought"] == 0, src["jobs_bought"])
    check("ZERO TheirStack calls made", len(rec.bodies) == 0, len(rec.bodies))
    tried = sum(1 for s in fake.signals if s["enriched_at"] is not None)
    check("every attempted company marked enriched (never retried)", tried == 20, tried)


if __name__ == "__main__":
    print("TheirStack credit-cursor + daily-budget regression lock\n")
    for t in (test_cursor_round_trip, test_filtered_page_still_advances_cursor, test_daily_cap_blocks,
              test_daily_leads_split_evenly, test_preview_stays_free, test_pages_until_budget_filled, test_goes_beyond_page_one, test_budget_spent_buys_nothing,
              test_backlog_drained_before_buying):
        print(t.__name__)
        t()
        print()
    print(f"{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
