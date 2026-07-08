"""stage_trigify_engagers(): cost must be proportional to what's NEW.

Regression for the 2026-07-08 watchdog timeouts. Two defects, both pinned here:
  1. every Trigify layer ran serially (47 searches x 2.8s = 131s of listing alone)
  2. a post that yielded no NEW engagers was never recorded as processed, so its
     comments were re-fetched on every 3-hourly tick, forever

Trigify + Supabase are stubbed; the code path is the production one.
Run:  python3 app/test_engagement_staging.py
"""
import sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


# ── stub Trigify: 20 searches x 10 posts; only post #0 of each has a commenter ──
N_SEARCHES, POSTS_PER_SEARCH, LATENCY = 20, 10, 0.05
EVENTS = []          # rows staged into engagement_events
CALLS = {"list": 0, "comments": 0, "enrich": 0}
PEAK = {"list": 0, "comments": 0, "enrich": 0}
_live = {"list": 0, "comments": 0, "enrich": 0}
_lock = threading.Lock()


def _track(kind):
    with _lock:
        CALLS[kind] += 1
        _live[kind] += 1
        PEAK[kind] = max(PEAK[kind], _live[kind])
    time.sleep(LATENCY)          # stand in for the ~2.5s network round-trip
    with _lock:
        _live[kind] -= 1


def fake_recent_posts(search_id, days):
    _track("list")
    s = int(search_id.split("-")[1])
    return [{"post_url": f"https://li/post/{s}-{i}", "post_urn": f"urn{s}-{i}",
             "published_at": f"2026-07-0{(i % 8) + 1}T00:00:00+00:00",
             "post_author": f"author{s}", "post_text": "t"} for i in range(POSTS_PER_SEARCH)]


def fake_post_engagers(post_urn, limit):
    _track("comments")
    s, i = post_urn.removeprefix("urn").split("-")
    if i != "0":
        return []                # 9 of 10 posts yield nothing -> the re-sweep trap
    return [{"name": f"P{s}", "linkedin": f"https://li/in/p{s}", "headline": "h",
             "comment_text": "c", "comment_permalink": "pl", "engaged_at": ""}]


def fake_enrich(url):
    _track("enrich")
    return {"full_name": "Full Name", "job_title": "CEO", "job_company_name": "Co"}


def fake_sb(method, path, body=None, prefer=""):
    if method == "GET" and path.startswith("engagement_events?source_id"):
        return [{"post_url": r["post_url"], "engager_linkedin_url": r["engager_linkedin_url"]}
                for r in EVENTS]
    if method == "POST" and path.startswith("engagement_events?on_conflict"):
        EVENTS.extend(body)
        return []
    return []


server._trigify_recent_posts = fake_recent_posts
server._trigify_post_engagers = fake_post_engagers
server._trigify_enrich = fake_enrich
server.sb = fake_sb


def fresh_src():
    return {"id": "draft-test", "campaign_id": "c1",
            "config": {"engagement": {"trigify": [{"search_id": f"s-{i}"} for i in range(N_SEARCHES)]}}}


def run(src):
    cfg = {**(src.get("config") or {}), **(src.get("params") or {})}
    t0 = time.monotonic()
    n = server.stage_trigify_engagers(src, cfg)
    return n, time.monotonic() - t0


TOTAL_POSTS = N_SEARCHES * POSTS_PER_SEARCH

print("\nfirst pull (cold: nothing staged, nothing swept)")
src = fresh_src()
staged1, secs1 = run(src)
c1 = dict(CALLS)
swept1 = len(server._swept_posts(src["config"]["engagement"]))
print(f"    staged={staged1}  {secs1:.2f}s  calls={c1}  swept={swept1}")
check("stages every post that has a commenter", staged1 == N_SEARCHES, f"{staged1} vs {N_SEARCHES}")
check("one enrich per PERSON, not per comment", c1["enrich"] == N_SEARCHES, f"{c1['enrich']}")
check("listings ran concurrently", PEAK["list"] > 1, f"peak in-flight = {PEAK['list']}")
check("comment fetches ran concurrently", PEAK["comments"] > 1, f"peak in-flight = {PEAK['comments']}")
check("enrichment ran concurrently", PEAK["enrich"] > 1, f"peak in-flight = {PEAK['enrich']}")
check("every in-window post recorded as swept", swept1 == TOTAL_POSTS, f"{swept1} vs {TOTAL_POSTS}")

print("\nsecond pull (warm: same posts, nothing new)  <- the bug")
CALLS.update(list=0, comments=0, enrich=0)
staged2, secs2 = run(src)
c2 = dict(CALLS)
print(f"    staged={staged2}  {secs2:.2f}s  calls={c2}")
check("stages nothing new", staged2 == 0)
check("re-fetches ZERO post comments", c2["comments"] == 0,
      f"{c2['comments']} calls (old code: {TOTAL_POSTS - N_SEARCHES} every tick, forever)")
check("burns ZERO enrichment credits", c2["enrich"] == 0, f"{c2['enrich']}")
check("still lists the searches (new posts must be discoverable)", c2["list"] == N_SEARCHES)
check("warm pull is far cheaper than cold", secs2 < secs1 / 2, f"{secs2:.2f}s vs {secs1:.2f}s")

print("\nthird pull, but the swept set was lost (legacy source, pre-fix doc)")
legacy = fresh_src()                       # no swept_posts, but the events exist
CALLS.update(list=0, comments=0, enrich=0)
staged3, _ = run(legacy)
c3 = dict(CALLS)
print(f"    staged={staged3}  calls={c3}")
check("seeds swept from engagement_events, so posts WITH events aren't re-fetched",
      c3["comments"] == TOTAL_POSTS - N_SEARCHES,
      f"{c3['comments']} = only the {TOTAL_POSTS - N_SEARCHES} that never produced a row")
check("and records them, so the NEXT tick is free",
      len(server._swept_posts(legacy["config"]["engagement"])) == TOTAL_POSTS)

print("\nfourth pull: cap honoured, uncapped posts left for the next tick")
EVENTS.clear()
capped = fresh_src()
CALLS.update(list=0, comments=0, enrich=0)
cfg = {**capped["config"]}
n = server.stage_trigify_engagers(capped, cfg, per_run=5)
swept_c = len(server._swept_posts(capped["config"]["engagement"]))
print(f"    staged={n}  swept={swept_c}  calls={dict(CALLS)}")
check("never stages more than the credit cap", n <= 5, f"{n}")
check("marks ONLY the posts it actually fetched as swept",
      swept_c < TOTAL_POSTS and swept_c > 0,
      f"{swept_c} of {TOTAL_POSTS} — the rest stay for the next tick")

print("\n" + ("ALL PASS" if not FAILS else f"FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
