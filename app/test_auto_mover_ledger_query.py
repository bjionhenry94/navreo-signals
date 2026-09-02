"""Regression gate: the R4/flap ledger lookup must survive a PostgREST error
and must not hand Postgres an unencoded "+00:00" offset.

The live bug (2026-09-02): _am_recent_ledger built `created_at=gte.<iso>` with
a bare "+" offset. In a query string "+" decodes to a SPACE, so PostgREST asked
for "…T15:06:09 00:00" and Postgres answered 22007. sb() returned that error as
a truthy DICT, `rows[0]` raised KeyError(0), and because the call site sits
outside any try, the FIRST candidate killed the entire auto-mover run — six
ticks a day, zero moves, silent.
"""
import os
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


seen = {}


def fake_sb(method, path, *a, **k):
    seen["path"] = path
    return {"code": "22007", "message": "invalid input syntax for type timestamp"}


_real = server.sb
server.sb = fake_sb
try:
    row = server._am_recent_ledger("3445988", 1, 48)
    check("error dict never indexed -> {}", row == {}, repr(row))
    check("timestamp offset is percent-encoded, no bare '+'",
          "%2B00%3A00" in seen["path"] or "+" not in seen["path"].split("created_at=gte.")[1],
          seen["path"])

    # _am_moves_today must read an error dict as "unreadable", i.e. full, not 4.
    n = server._am_moves_today()
    check("_am_moves_today on error dict -> daily cap (not len(dict))",
          n == server._AM_MAX_MOVES_DAY, repr(n))
finally:
    server.sb = _real

# And a well-formed list still works.
server.sb = lambda *a, **k: [{"id": "x", "winner": "A", "pcts_after": {"A": 100}}]
try:
    check("list result returns the newest row",
          server._am_recent_ledger("1", 1, 48).get("winner") == "A")
finally:
    server.sb = _real

print(("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}"))
raise SystemExit(1 if fails else 0)
