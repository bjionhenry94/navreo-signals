"""Fair-test law amendments (Bjion 2026-09-02): flat 800 floor + ties hold.
Drives build_notifications.pill_best_opener directly with the harness-approved
scenarios. Run: python3 app/test_best_opener_flat800_tie.py"""
import build_notifications as bn


def V(label, sent, positives=0, meetings=0, live=True):
    # live=False models a SWITCHED-OFF version: split 0 but not deleted, so it
    # still counts as crownable once past the bar (Bjion B-5). Deleted versions
    # (disabled=True) are a different state and are never modelled here.
    return {"step": 1, "label": label, "sent": sent, "positives": positives,
            "meetings": meetings, "inline": False,
            "disabled": False, "split": (100 if live else 0)}


def M(versions, bar=800):
    by_variant = {f"1|{v['label']}": v["meetings"]
                  for v in versions if v.get("meetings")}
    return {"versions": versions, "paths": None,
            "meetings": {"by_variant": by_variant, "clusters": {}},
            "judge_bars": {"1": bar}}


def verdict(m):
    lab, has_scale, ev = bn.pill_best_opener(m)
    if lab is None:
        return "NONE", None
    return (ev or {}).get("mode"), lab


CASES = [
    # tag, versions, expected (mode, winner|None)
    ("coin-flip under bar", [V("A", 362, 1), V("B", 361, 1)], ("NONE", None)),
    ("clear winner past bar", [V("A", 900, 3), V("B", 920, 9, meetings=1)], ("full", "B")),
    ("winner + live laggard", [V("A", 850, 8, meetings=1), V("B", 410, 2)], ("partial", "A")),
    ("small list, flat 800", [V("A", 420, 5), V("B", 400, 2)], ("NONE", None)),
    ("dead heat holds", [V("A", 1000, 10), V("B", 1000, 10)], ("NONE", None)),
    ("meeting = positive", [V("A", 900, 3), V("B", 900, 0, meetings=4)], ("full", "B")),
    ("switched-off winner", [V("A", 900, 4), V("C", 1100, 14, meetings=1, live=False)], ("full", "C")),
    ("thin winner crowns", [V("A", 1000, 6), V("B", 1000, 5)], ("full", "A")),
    # second deck
    ("3-way one winner", [V("A", 900, 11), V("B", 500, 3), V("C", 480, 2)], ("partial", "A")),
    ("3 all past bar", [V("A", 900, 5), V("B", 900, 12), V("C", 900, 6)], ("full", "B")),
    ("meeting under bar", [V("A", 900, 4), V("B", 500, 0, meetings=2)], ("partial", "A")),
    ("equal pos, rate wins", [V("A", 800, 8), V("B", 1000, 8)], ("full", "A")),
    ("tie at top, 3rd trails", [V("A", 1000, 10), V("B", 1000, 10), V("C", 1000, 5)], ("NONE", None)),
    ("off laggard ignored", [V("A", 900, 7), V("C", 300, 1, live=False)], ("full", "A")),
]

fails = 0
for tag, vs, exp in CASES:
    got = verdict(M(vs))
    ok = got == exp
    print(f"  {'ok  ' if ok else 'FAIL'}  {tag:24s} expected {exp}  got {got}")
    if not ok:
        fails += 1
print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'} ({len(CASES)} cases)")
raise SystemExit(1 if fails else 0)
