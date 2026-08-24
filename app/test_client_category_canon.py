"""Canonicalisation of client-workspace positive categories.

analytics_hub_v1 counts positives by CORE_FOUR name; a client that renamed its
positive category in its own Smartlead account would otherwise leave those
replies uncounted. _canon_client_category maps every known-positive Smartlead id
to a CORE_FOUR name so the hub still counts them. Pure-python, no network.
"""
import setter

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + ": " + name)
    if not cond:
        fails.append(name)


# Every id the resweep treats as positive must canonicalise INTO CORE_FOUR,
# regardless of the workspace's own (possibly renamed) label.
for cid in setter.POSITIVE_CATEGORY_IDS:
    got = setter._canon_client_category(cid, "Some Client Custom Name")
    check(f"positive id {cid} -> CORE_FOUR ({got})", got in setter.CORE_FOUR)

# Smartlead default ids keep their true meaning.
check("id 1 -> Interested", setter._canon_client_category(1, "renamed") == "Interested")
check("id 2 -> Meeting Request", setter._canon_client_category(2, "x") == "Meeting Request")
check("id 5 -> Information Request", setter._canon_client_category(5, "x") == "Information Request")

# Non-positive ids keep the workspace's own name untouched.
check("non-positive keeps ws name",
      setter._canon_client_category(3, "Not Interested") == "Not Interested")
check("unknown id keeps ws name",
      setter._canon_client_category(99999, "Out Of Office") == "Out Of Office")

# Bad / missing id => ws name (never crashes).
check("None id -> ws name", setter._canon_client_category(None, "Neutral") == "Neutral")
check("garbage id -> ws name", setter._canon_client_category("abc", "Neutral") == "Neutral")
check("None id, no name -> ''", setter._canon_client_category(None, "") == "")

# The canon map must stay a subset of CORE_FOUR (guards future edits).
check("canon values subset of CORE_FOUR",
      set(setter._POSITIVE_ID_CANON.values()) <= set(setter.CORE_FOUR))

print()
if fails:
    print(f"{len(fails)} FAILED")
    import sys
    sys.exit(1)
print("all pass")
