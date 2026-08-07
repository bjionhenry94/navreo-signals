"""Step 4: patch the reply-categoriser Make scenarios.

Changes (and ONLY these):
  1. AI system prompt (module openai-gpt-3:CreateCompletion) -> contents of new_prompt.txt
  2. RouteA "Only if no existing category" gate (module id 2 filter) -> fail-closed,
     once-only-anywhere:
       cond1: {{if(29.statusCode = 200; max(map(29.data.lead_campaign_data; "lead_category_id")); 1)}}  notexist
              - statusCode != 200  -> literal 1 -> exists -> gate BLOCKS (fail closed)
              - any campaign entry already categorised -> max() is a number -> exists -> BLOCKS
              - lead never categorised anywhere -> max(all null) -> null -> notexist -> PASSES
       cond2: {{1.sl_email_lead_id}} exist   (kills /leads//category double-slash)
Preserves: stopOnHttpError:false, dlq, routeB, category-id mapping, Slack routing, scheduling.

Usage: MAKE_TOKEN=... python3 step4_patch_make.py [--dry-run]
"""
import json, os, sys, copy
from pathlib import Path
import requests

SCRATCH = Path(__file__).parent
BASE = "https://eu2.make.com/api/v2"
TOKEN = os.environ.get("MAKE_TOKEN")
SCENARIOS = [9251436, 9187631]  # Navreo, Asteri
DRY = "--dry-run" in sys.argv

# NOTE: Make filter semantics — OUTER list = OR groups, INNER list = AND conditions.
# Both conditions MUST live in ONE inner list (AND). Splitting them into two outer
# groups (the 10 Jul 2026 bug) makes the gate pass EVERY reply, causing duplicate
# alerts + re-categorisation of already-tagged leads. Fixed 11 Jul 2026.
NEW_GATE = [
    [{"a": '{{if(29.statusCode = 200; max(map(29.data.lead_campaign_data; "lead_category_id")); 1)}}',
      "o": "notexist"},
     {"a": "{{1.sl_email_lead_id}}", "o": "exist"}],
]
NEW_PROMPT = (SCRATCH / "new_prompt.txt").read_text()

def walk(mods):
    for m in mods:
        yield m
        for r in (m.get("routes") or []):
            yield from walk(r.get("flow", []))

assert TOKEN, "set MAKE_TOKEN"
h = {"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"}
for sid in SCENARIOS:
    r = requests.get(f"{BASE}/scenarios/{sid}/blueprint", headers=h, timeout=30)
    r.raise_for_status()
    bp = r.json()["response"]["blueprint"]
    orig = copy.deepcopy(bp)
    Path(SCRATCH / f"blueprint_{sid}_before.json").write_text(json.dumps(orig, indent=1))

    changed = []
    for m in walk(bp["flow"]):
        if m.get("id") == 2 and m.get("filter"):
            m["filter"]["name"] = "Only if never categorised anywhere (fail closed)"
            m["filter"]["conditions"] = NEW_GATE
            changed.append("gate")
        if str(m.get("module", "")).startswith("openai") :
            msgs = m.get("mapper", {}).get("messages", [])
            for msg in msgs:
                if msg.get("role") == "system":
                    msg["content"] = NEW_PROMPT
                    changed.append("prompt")
                elif msg.get("role") == "user" and "{{1.reply_message.text}}" in msg.get("content", ""):
                    # Smartlead reply text is newest-first (reply on top, quoted thread below);
                    # the old "THREAD (oldest first)" label misled the model on short replies.
                    msg["content"] = ("EMAIL THREAD — the prospect's LATEST reply is at the TOP; "
                                      "the quoted earlier messages (our outreach) appear BELOW it:\n\n"
                                      "{{1.reply_message.text}}\n\n---\n\n"
                                      "Categorise the prospect's LATEST reply (the top message). Return JSON only.")
                    changed.append("user_template")
    assert "gate" in changed and "prompt" in changed, f"{sid}: expected modules not found: {changed}"

    Path(SCRATCH / f"blueprint_{sid}_after.json").write_text(json.dumps(bp, indent=1))
    if DRY:
        print(f"{sid}: DRY RUN ok, changed={changed}")
        continue
    pr = requests.patch(f"{BASE}/scenarios/{sid}", headers=h,
                        json={"blueprint": json.dumps(bp)}, timeout=60)
    pr.raise_for_status()
    # re-fetch to verify
    v = requests.get(f"{BASE}/scenarios/{sid}/blueprint", headers=h, timeout=30)
    v.raise_for_status()
    vbp = v.json()["response"]["blueprint"]
    ok_gate = any(m.get("id") == 2 and m.get("filter", {}).get("conditions") == NEW_GATE
                  for m in walk(vbp["flow"]))
    print(f"{sid}: PATCHED, verify gate={'OK' if ok_gate else 'MISMATCH'}")
