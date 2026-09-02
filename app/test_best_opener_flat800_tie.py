"""Fair-test law v3 (Bjion 2026-09-02) — regression fixtures for
build_notifications.pill_best_opener. Every case below was approved live in the
harness deck. Run: python3 app/test_best_opener_flat800_tie.py

Rules under test: flat 800 floor · meetings-first ranking (sent/meeting), then
sent/positive · meeting-leader override (>=2 mtg may win under the bar) ·
ties split evenly, past-bar losers dropped · never-starve (nothing under 800
is dropped) · human-off (0% with sends) is sticky and excluded."""
import build_notifications as bn


def V(label, sent, positives=0, meetings=0, live=True, human_off=False):
    # live=False models a SYSTEM/never-provisioned off (split 0, no sends
    # assumed unless human_off). human_off=True models "switched off on
    # purpose": split 0 WITH send history — the codebase's provenance rule.
    split = 100 if live else 0
    if human_off:
        split = 0
    return {"step": 1, "label": label, "sent": sent, "positives": positives,
            "meetings": meetings, "inline": False, "disabled": False, "split": split}


def M(versions):
    by_variant = {f"1|{v['label']}": v["meetings"] for v in versions if v.get("meetings")}
    return {"versions": versions, "paths": None,
            "meetings": {"by_variant": by_variant, "clusters": {}},
            "judge_bars": {"1": 800}}


def run(m):
    lab, has_scale, ev = bn.pill_best_opener(m)
    if ev is None:
        return ("NONE",)
    if ev["mode"] == "tie":
        return ("tie", tuple(ev["leaders"]), tuple(ev["laggards"]), tuple(ev["dropped"]))
    return (ev["mode"], lab, tuple(ev["laggards"]), tuple(ev["dropped"]), ev["override"])


# (tag, versions, expected)
# full/partial expected = (mode, winner, laggards, dropped, override)
# tie expected          = ("tie", leaders, laggards, dropped)
CASES = [
    # --- deck 1 ---
    ("coin-flip under bar",      [V("A", 362, 1), V("B", 361, 1)],
     ("NONE",)),
    ("clear winner past bar",    [V("A", 900, 3), V("B", 920, 9, meetings=1)],
     ("full", "B", (), ("A",), False)),
    ("winner + live laggard",    [V("A", 850, 8, meetings=1), V("B", 410, 2)],
     ("partial", "A", ("B",), (), False)),
    ("small list, flat 800",     [V("A", 420, 5), V("B", 400, 2)],
     ("NONE",)),
    ("dead heat -> 50/50",       [V("A", 1000, 10), V("B", 1000, 10)],
     ("tie", ("A", "B"), (), ())),
    ("meeting = positive",       [V("A", 900, 3), V("B", 900, 0, meetings=4)],
     ("full", "B", (), ("A",), False)),
    ("thin winner crowns",       [V("A", 1000, 6), V("B", 1000, 5)],
     ("full", "A", (), ("B",), False)),
    # --- deck 2 ---
    ("3-way one winner",         [V("A", 900, 11), V("B", 500, 3), V("C", 480, 2)],
     ("partial", "A", ("B", "C"), (), False)),
    ("3 all past bar",           [V("A", 900, 5), V("B", 900, 12), V("C", 900, 6)],
     ("full", "B", (), ("A", "C"), False)),
    ("equal pos, rate wins",     [V("A", 800, 8), V("B", 1000, 8)],
     ("full", "A", (), ("B",), False)),
    # --- v3 deck: override / tie / never-starve / human-off ---
    ("meeting override 2 mtg",   [V("A", 900, 4), V("B", 500, 0, meetings=2)],
     ("partial", "B", ("A",), (), True)),
    ("1 meeting: no override",   [V("A", 900, 4), V("B", 500, 0, meetings=1)],
     ("partial", "A", ("B",), (), False)),
    ("tie top, third dropped",   [V("A", 1000, 10), V("B", 1000, 10), V("C", 1000, 5)],
     ("tie", ("A", "B"), (), ("C",))),
    ("tie + under-bar laggard",  [V("A", 1000, 10), V("B", 1000, 10), V("D", 400, 1)],
     ("tie", ("A", "B"), ("D",), ())),
    ("human-off stays off",      [V("A", 900, 7), V("C", 300, 1, human_off=True)],
     ("full", "A", (), (), False)),
    ("human-off even if winning", [V("A", 900, 5), V("C", 1000, 2, meetings=2, human_off=True)],
     ("full", "A", (), (), False)),
    # --- meeting-metrics deck ---
    ("meetings beat positives",  [V("A", 900, 6, meetings=2), V("B", 950, 5, meetings=5)],
     ("full", "B", (), ("A",), False)),
    ("12 pos lose to meetings",  [V("A", 1000, 12, meetings=1), V("B", 1000, 4, meetings=4)],
     ("full", "B", (), ("A",), False)),
    ("tie on sent/meeting",      [V("A", 800, 4, meetings=4), V("B", 1000, 5, meetings=5)],
     ("tie", ("A", "B"), (), ())),
    ("3-way leader past bar",    [V("A", 900, 8, meetings=6), V("B", 500, 3, meetings=2), V("C", 480, 2)],
     ("partial", "A", ("B", "C"), (), False)),
    ("laggard single meeting",   [V("A", 900, 7, meetings=3), V("B", 400, 2, meetings=1)],
     ("partial", "A", ("B",), (), False)),
    ("no meetings: positives",   [V("A", 900, 9), V("B", 900, 5)],
     ("full", "A", (), ("B",), False)),
]

fails = 0
for tag, vs, exp in CASES:
    got = run(M(vs))
    ok = got == exp
    print(f"  {'ok  ' if ok else 'FAIL'}  {tag:26s} {'' if ok else 'expected ' + str(exp) + '  got ' + str(got)}")
    fails += 0 if ok else 1
print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'} ({len(CASES)} cases)")
raise SystemExit(1 if fails else 0)
