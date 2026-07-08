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
    stub_meter_and_cap(spent_today=server.THEIRSTACK_DAILY_CAP)
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
    finally:
        server.http_json = orig


if __name__ == "__main__":
    print("TheirStack credit-cursor regression lock\n")
    for t in (test_cursor_round_trip, test_filtered_page_still_advances_cursor, test_daily_cap_blocks):
        print(t.__name__)
        t()
        print()
    print(f"{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
