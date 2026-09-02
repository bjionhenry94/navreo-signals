"""Door-side fair-test law v3 (Bjion 2026-09-02): the split_leaders TIE action
and the never-starve / human-off gate on back_winner. Smartlead is never
touched — save_sequence_ids_intact is replaced by a fake that runs the
caller's mutate + verify on fixture steps, and the send-history read is
stubbed. Run: NAVREO_NO_BG=1 python3 app/test_variant_door_v3.py"""
import copy
import os

os.environ.setdefault("NAVREO_NO_BG", "1")
import server  # noqa: E402


def steps_fixture(pcts: dict):
    """One Email-1 step; pcts = {label: pct}. ids are 10, 20, 30, ..."""
    vs = []
    for i, (lab, p) in enumerate(pcts.items(), start=1):
        vs.append({"id": i * 10, "variant_label": lab, "variant_distribution_percentage": p,
                   "is_deleted": False, "subject": "s", "email_body": "b"})
    return [{"seq_number": 1, "sequence_variants": vs}]


def door(pcts: dict, sent_by_label: dict, payload: dict):
    """Run api_campaign_variant_action against the fixture. Returns (status, body)."""
    steps = steps_fixture(pcts)
    id_of = {v["variant_label"]: v["id"] for v in steps[0]["sequence_variants"]}
    hist = {id_of[l]: n for l, n in sent_by_label.items()}

    def fake_save(campaign_id, mutate_fn, api_key=None, http=None, verify_fn=None):
        work = copy.deepcopy(steps)
        out = mutate_fn(work) or work
        assert verify_fn is None or verify_fn(out), "verify_fn rejected the mutated steps"
        return {"ok": True}

    real_save, real_hist = server.save_sequence_ids_intact, server._variant_sent_by_vid
    server.save_sequence_ids_intact = fake_save
    server._variant_sent_by_vid = lambda cid: dict(hist)
    try:
        return server.api_campaign_variant_action("123", dict(payload, email=1))
    finally:
        server.save_sequence_ids_intact, server._variant_sent_by_vid = real_save, real_hist


fails = 0


def check(tag, cond, detail=""):
    global fails
    print(f"  {'ok  ' if cond else 'FAIL'}  {tag}{('  ' + detail) if (detail and not cond) else ''}")
    fails += 0 if cond else 1


# 1. TIE, no laggards: A/B tied, C a past-bar loser -> 50/50, C dropped
st, body = door({"A": 60, "B": 20, "C": 20}, {"A": 1000, "B": 1000, "C": 1000},
                {"action": "split_leaders", "leaders": ["A", "B"], "confirm": "SPLITLEADERS"})
check("split_leaders 2-way -> 50/50, loser 0", st == 200 and body.get("after") == {"A": 50, "B": 50, "C": 0}, str(body))

# 2. TIE + under-bar laggard D keeps 20: A/B share 80 -> 40/40/20, C dropped
st, body = door({"A": 40, "B": 30, "C": 20, "D": 10}, {"A": 1000, "B": 1000, "C": 1000, "D": 400},
                {"action": "split_leaders", "leaders": ["A", "B"], "laggards": ["D"], "confirm": "SPLITLEADERS"})
check("split_leaders + laggard -> 40/40/0/20", st == 200 and body.get("after") == {"A": 40, "B": 40, "C": 0, "D": 20}, str(body))

# 3. A leader at 0% WITH sends is human-off -> refused, nothing saved
st, body = door({"A": 100, "B": 0}, {"A": 1000, "B": 1000},
                {"action": "split_leaders", "leaders": ["A", "B"], "confirm": "SPLITLEADERS"})
check("split_leaders refuses a human-off leader", st == 400 and "switched off on purpose" in body.get("message", ""), str(body))

# 4. Fewer than two leaders -> 400 before any Smartlead work
st, body = door({"A": 100, "B": 0}, {}, {"action": "split_leaders", "leaders": ["A"], "confirm": "SPLITLEADERS"})
check("split_leaders needs >=2 leaders", st == 400 and "at least two" in body.get("message", ""), str(body))

# 5. back_winner: never-configured 0% laggard (zero sends) may join the 20% lane
st, body = door({"A": 100, "B": 0}, {"A": 900, "B": 0},
                {"action": "back_winner", "variant_label": "A", "laggards": ["B"], "confirm": "BACK"})
check("back_winner lets a never-configured 0% laggard in", st == 200 and body.get("after") == {"A": 80, "B": 20}, str(body))

# 6. back_winner: 0% laggard WITH sends is human-off -> refused
st, body = door({"A": 100, "B": 0}, {"A": 900, "B": 300},
                {"action": "back_winner", "variant_label": "A", "laggards": ["B"], "confirm": "BACK"})
check("back_winner refuses a human-off laggard", st == 400 and "switched off on purpose" in body.get("message", ""), str(body))

# 7. back_winner unchanged on the common path (live laggard, no history read needed)
st, body = door({"A": 50, "B": 50}, {},
                {"action": "back_winner", "variant_label": "A", "laggards": ["B"], "confirm": "BACK"})
check("back_winner common path -> 80/20", st == 200 and body.get("after") == {"A": 80, "B": 20}, str(body))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'} (7 cases)")
raise SystemExit(1 if fails else 0)
