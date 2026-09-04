"""Ledger accuracy gate (Bjion approved, 2026-09-04): _am_splits must record a
NULL variant_distribution_percentage as its FACTUAL even share, not 0.

The live bug (campaign 3343012, 2 Sep 2026): B and C were both live at a null
split — really 50/50 — but _am_splits read null as 0, so the ledger stored
pcts_before {B:0, C:0}. That "before" reads like both versions were switched
off, which then feeds the General page, the Change Logs tab and R4's
human-owned comparison. The DOOR was never wrong — _find_step normalises before
any mutation — so this is a number-accuracy fix, not a behaviour change.

Run: NAVREO_NO_BG=1 python3 app/test_am_splits_null.py
"""
import copy
import os

os.environ.setdefault("NAVREO_NO_BG", "1")
import server  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def seq_payload(variants):
    """A GET /campaigns/{id}/sequences shape: one Email-1 step + a step 2."""
    return [
        {"seq_number": 1, "sequence_variants": variants},
        {"seq_number": 2, "sequence_variants": [
            {"id": 900, "variant_label": "A", "variant_distribution_percentage": 100,
             "is_deleted": False}]},
    ]


def am_splits_with(variants):
    real = server._smartlead_json
    server._smartlead_json = lambda *a, **k: seq_payload(copy.deepcopy(variants))
    try:
        return server._am_splits("123")
    finally:
        server._smartlead_json = real


# THE regression: two non-deleted null-split variants, both with send history.
two_null = [
    {"id": 6262926, "variant_label": "B", "variant_distribution_percentage": None, "is_deleted": False},
    {"id": 6262927, "variant_label": "C", "variant_distribution_percentage": None, "is_deleted": False},
]
res = am_splits_with(two_null)
check("two null-split live variants record 50/50, not 0/0", res == {"B": 50, "C": 50}, repr(res))

# Three nulls -> 34/33/33 (the remainder rides the first), summing to 100.
three_null = [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": None, "is_deleted": False},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": None, "is_deleted": False},
    {"id": 3, "variant_label": "C", "variant_distribution_percentage": None, "is_deleted": False},
]
res = am_splits_with(three_null)
check("three null-split variants sum to 100", sum(res.values()) == 100, repr(res))
check("three null-split variants each get ~a third", sorted(res.values()) == [33, 33, 34], repr(res))

# An EXPLICIT 0 is a human decision (off) — it must STAY 0, never become a share.
explicit_off = [
    {"id": 10, "variant_label": "A", "variant_distribution_percentage": 100, "is_deleted": False},
    {"id": 20, "variant_label": "B", "variant_distribution_percentage": 0, "is_deleted": False},
]
res = am_splits_with(explicit_off)
check("an explicit 0 (human-off) stays 0", res == {"A": 100, "B": 0}, repr(res))

# A null ALONGSIDE an explicit share takes only the remainder (mirrors the live
# 3343012 current state: C=100 explicit, B=null -> B gets 0).
mixed = [
    {"id": 30, "variant_label": "C", "variant_distribution_percentage": 100, "is_deleted": False},
    {"id": 40, "variant_label": "B", "variant_distribution_percentage": None, "is_deleted": False},
]
res = am_splits_with(mixed)
check("a null beside an explicit 100 takes the remainder (0)", res == {"C": 100, "B": 0}, repr(res))

# Explicit numbers are untouched (60/40 stays 60/40).
explicit = [
    {"id": 50, "variant_label": "A", "variant_distribution_percentage": 60, "is_deleted": False},
    {"id": 60, "variant_label": "B", "variant_distribution_percentage": 40, "is_deleted": False},
]
res = am_splits_with(explicit)
check("explicit splits are passed through untouched", res == {"A": 60, "B": 40}, repr(res))

# A deleted variant is never in the distribution, null or not.
with_deleted = [
    {"id": 70, "variant_label": "A", "variant_distribution_percentage": None, "is_deleted": False},
    {"id": 80, "variant_label": "B", "variant_distribution_percentage": None, "is_deleted": False},
    {"id": 90, "variant_label": "Z", "variant_distribution_percentage": None, "is_deleted": True},
]
res = am_splits_with(with_deleted)
check("a deleted variant is excluded; the live ones split 50/50",
      res == {"A": 50, "B": 50}, repr(res))

# ── The door is UNCHANGED — proven, not just claimed. Same null inputs through
# the real write door still produce the winner-takes-100 result they always did.
def door(pcts, sent_by_label, payload):
    steps = [{"seq_number": 1, "sequence_variants": [
        {"id": (i + 1) * 10, "variant_label": lab, "variant_distribution_percentage": p,
         "is_deleted": False, "subject": "s", "email_body": "b"}
        for i, (lab, p) in enumerate(pcts.items())]}]
    id_of = {v["variant_label"]: v["id"] for v in steps[0]["sequence_variants"]}
    hist = {id_of[l]: n for l, n in sent_by_label.items()}

    def fake_save(campaign_id, mutate_fn, api_key=None, http=None, verify_fn=None):
        work = copy.deepcopy(steps)
        out = mutate_fn(work) or work
        assert verify_fn is None or verify_fn(out)
        return {"ok": True}

    rs, rh = server.save_sequence_ids_intact, server._variant_sent_by_vid
    server.save_sequence_ids_intact = fake_save
    server._variant_sent_by_vid = lambda cid: dict(hist)
    try:
        return server.api_campaign_variant_action("123", dict(payload, email=1))
    finally:
        server.save_sequence_ids_intact, server._variant_sent_by_vid = rs, rh


st, body = door({"B": None, "C": None}, {"B": 14222, "C": 14283},
                {"action": "scale_winner", "variant_label": "C", "confirm": "SCALE"})
check("door scale_winner on null inputs still -> C 100 / B 0 (unchanged)",
      st == 200 and body.get("after") == {"B": 0, "C": 100}, repr(body))
check("door's OWN before already read the true 50/50 (this fix only aligns the ledger)",
      body.get("before") == {"B": 50, "C": 50}, repr(body.get("before")))

print(("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}"))
raise SystemExit(1 if fails else 0)
