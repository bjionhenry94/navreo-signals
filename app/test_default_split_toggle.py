"""Default-split normalisation tests (Bjion, 2026-08-04: toggle view on every
variant row). Smartlead serves NULL variant_distribution_percentage on a step
whose A/B split was never explicitly configured — the default equal share.
Run: python3 app/test_default_split_toggle.py"""
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

def dists(step):
    return [v.get("variant_distribution_percentage") for v in step["sequence_variants"]]

# 1 — all-null live variants -> equal shares summing to 100
step = {"seq_number": 1, "sequence_variants": [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": None},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": None},
    {"id": 3, "variant_label": "C", "variant_distribution_percentage": None},
]}
server._normalise_default_split(step)
check("3-way all-null -> equal shares", sorted(dists(step)) == [33, 33, 34], dists(step))

# 2 — sole survivor (siblings deleted) -> 100; deleted stay null
step = {"seq_number": 1, "sequence_variants": [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": None, "is_deleted": True},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": None},
]}
server._normalise_default_split(step)
check("sole live variant -> 100", step["sequence_variants"][1]["variant_distribution_percentage"] == 100)
check("deleted sibling untouched", step["sequence_variants"][0]["variant_distribution_percentage"] is None)

# 3 — mixed step: nulls split the REMAINING share; explicit numbers untouched
#     (the 3612092 shape: A=25, B=25 explicit, C/D null -> 25 each)
step = {"seq_number": 1, "sequence_variants": [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": 25},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": 25},
    {"id": 3, "variant_label": "C", "variant_distribution_percentage": None},
    {"id": 4, "variant_label": "D", "variant_distribution_percentage": None},
]}
server._normalise_default_split(step)
check("nulls take the remaining share equally", dists(step) == [25, 25, 25, 25], dists(step))

# 3b — explicit shares already sum to 100 -> null variants are off (0)
#      (the 3642940 shape: A=80, B=20, C/D null with zero sends)
step = {"seq_number": 1, "sequence_variants": [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": 80},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": 20},
    {"id": 3, "variant_label": "C", "variant_distribution_percentage": None},
]}
server._normalise_default_split(step)
check("null gets 0 when explicit sums to 100", dists(step) == [80, 20, 0], dists(step))

# 3c — explicit 0 stays 0 (switched off on purpose); null sibling takes the rest
step = {"seq_number": 1, "sequence_variants": [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": 0},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": None},
]}
server._normalise_default_split(step)
check("explicit 0 kept; null takes remainder", dists(step) == [0, 100], dists(step))

# 4 — _find_step normalises, so every action path sees real numbers and the
#     disable guard no longer refuses a default-split variant as "already 0%"
steps = [{"seq_number": 1, "sequence_variants": [
    {"id": 1, "variant_label": "A", "variant_distribution_percentage": None},
    {"id": 2, "variant_label": "B", "variant_distribution_percentage": None},
]}]
s = server._find_step(steps, 1)
check("_find_step stamps default shares", dists(s) == [50, 50], dists(s))
res = {}
p = server._disable_variant_pcts(steps, 1, "B", None, res, winner_label="A")
check("disable works on a default-split step (B -> 0, A -> 100)",
      p == {1: 100, 2: 0}, p)

print("FAIL" if _fail else "ALL PASS")
sys.exit(1 if _fail else 0)
