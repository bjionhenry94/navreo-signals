"""Freed-share-goes-to-the-winner tests (Bjion, 2026-08-02).
Run: python3 app/test_disable_to_winner.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1

def step_3way():
    # Email 1 with A=34, C=33, D=33 (B deleted/off) — the real shape of the
    # two live losers' campaigns.
    return [{"id": 10, "seq_number": 1, "sequence_variants": [
        {"id": 101, "variant_label": "A", "variant_distribution_percentage": 34},
        {"id": 102, "variant_label": "B", "variant_distribution_percentage": 0, "is_deleted": True},
        {"id": 103, "variant_label": "C", "variant_distribution_percentage": 33},
        {"id": 104, "variant_label": "D", "variant_distribution_percentage": 33},
    ]}]

# 1 — winner-take-all: disable D, freed 33 -> winner C (33 -> 66), A unchanged
steps = step_3way(); res = {}
p = server._disable_variant_pcts(steps, 1, "D", None, res, winner_label="C")
check("target D -> 0", p[104] == 0, p)
check("winner C gets the whole freed share (33 -> 66)", p[103] == 66, p)
check("other sibling A unchanged (34)", p[101] == 34, p)
check("shares still sum to 100", p[101] + p[103] + p[104] == 100, p)
check("receipt names the winner", res.get("winner_id") == 103 and res.get("winner_label") == "C", res)

# 2 — fallback: no winner label -> proportional split, target 0, sums to 100
steps = step_3way(); res = {}
p = server._disable_variant_pcts(steps, 1, "D", None, res, winner_label=None)
check("fallback: target D -> 0", p[104] == 0, p)
check("fallback: sums to 100", p[101] + p[103] == 100, p)
check("fallback: winner_id is None", res.get("winner_id") is None, res)

# 3 — winner not among active others -> None (caller falls back)
others = [{"id": 101, "pct": 34, "label": "A"}, {"id": 103, "pct": 33, "label": "C"}]
check("_pcts_to_winner returns None for absent winner", server._pcts_to_winner(others, 33, "Z") is None)
check("_pcts_to_winner returns None for empty label", server._pcts_to_winner(others, 33, None) is None)

# 4 — _best_sibling_label ranks positives/sent when there are no meetings; skips off/self
server._cockpit_messaging = lambda cid: {"meetings": {"by_variant": {}}, "versions": [
    {"step": 1, "label": "A", "sent": 1009, "replies": 8,  "positives": 2, "split": 34},
    {"step": 1, "label": "C", "sent": 1014, "replies": 9,  "positives": 1, "split": 33},  # the loser
    {"step": 1, "label": "D", "sent": 1006, "replies": 17, "positives": 0, "split": 33},
    {"step": 1, "label": "B", "sent": 0, "replies": 0, "positives": 9, "split": 0},        # off: ignored
    {"step": 2, "label": "A", "sent": 999, "replies": 5,  "positives": 5, "split": 100},   # other step: ignored
]}
check("no meetings -> winner by positives/sent, excludes loser + off + other-step",
      server._best_sibling_label(3649281, 1, "C") == "A")

# 4b — meetings/sent OUTRANKS positives/sent: D has 1 meeting, A has more positives but 0 meetings
server._cockpit_messaging = lambda cid: {"meetings": {"by_variant": {"1|D": 1}}, "versions": [
    {"step": 1, "label": "A", "sent": 1000, "replies": 8, "positives": 5, "split": 34},   # more positives, 0 meetings
    {"step": 1, "label": "C", "sent": 1000, "replies": 9, "positives": 1, "split": 33},   # the loser
    {"step": 1, "label": "D", "sent": 1000, "replies": 6, "positives": 0, "split": 33},   # 1 meeting -> winner
]}
check("meetings/sent beats positives/sent (D's meeting wins over A's positives)",
      server._best_sibling_label(3649281, 1, "C") == "D")

# degraded payload -> None (safe fallback)
server._cockpit_messaging = lambda cid: {"degraded": True}
check("degraded stats -> None winner (fallback)", server._best_sibling_label(1, 1, "C") is None)

print()
print(f"{'ALL PASS' if _fail == 0 else str(_fail) + ' FAILED'}")
sys.exit(1 if _fail else 0)
