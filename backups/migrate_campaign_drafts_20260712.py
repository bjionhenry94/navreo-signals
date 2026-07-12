"""One-shot additive migration (2026-07-12): campaign_drafts platform-identity rework.

Platform identity becomes the campaign key: one doc per Smartlead campaign
(camp-sl-<id>) and one per HeyReach LIST (camp-hr-<list_id>). Old cdraft-* docs
are kept and marked superseded_by — nothing is deleted. The dual-destination
Arnic doc splits into two campaigns, its sources attached to BOTH. Two drafts
pointing at the same HeyReach list merge into one campaign doc. Destination-less
drafts stay untouched (they render as "Unlinked").

Idempotent: re-running skips docs that already exist.
"""
import json, re, urllib.request, time
from pathlib import Path

KEYS = {}
for line in (Path.home() / ".navreo-keys.env").read_text().splitlines():
    m = re.match(r"^(?:export\s+)?([A-Z0-9_]+)=(\S+)", line.strip())
    if m:
        KEYS[m.group(1)] = m.group(2).strip("\"'")
BASE = KEYS["SUPABASE_URL"].rstrip("/") + "/rest/v1/campaign_drafts"
HDRS = {"apikey": KEYS["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {KEYS['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json"}


def req(method, url, body=None):
    r = urllib.request.Request(url, method=method, headers={**HDRS, "Prefer": "return=representation"},
                               data=json.dumps(body).encode() if body is not None else None)
    import ssl, certifi
    with urllib.request.urlopen(r, context=ssl.create_default_context(cafile=certifi.where())) as resp:
        return json.loads(resp.read() or "[]")


docs = {d["id"]: d["doc"] for d in req("GET", BASE + "?select=id,doc")}
now = time.strftime("%Y-%m-%dT%H:%M:%S")
new_docs, supersede = {}, {}   # new_id -> doc ; old_id -> [new_ids]

for old_id, doc in sorted(docs.items()):
    dest = doc.get("destination") or {}
    sl, hr = dest.get("smartlead_campaign_id"), dest.get("heyreach_list_id")
    if not sl and not hr:
        continue  # destination-less -> stays an Unlinked draft, untouched
    targets = []
    if sl:
        targets.append((f"camp-sl-{sl}", {"platform": "smartlead", "smartlead_campaign_id": str(sl)}))
    if hr:
        targets.append((f"camp-hr-{hr}", {"platform": "heyreach", "heyreach_list_id": int(hr),
                                          "heyreach_list_name": dest.get("heyreach_list_name") or ""}))
    for new_id, plat in targets:
        if new_id in new_docs:  # two drafts on the same platform entity -> merge
            nd = new_docs[new_id]
            nd["migrated_from"].append(old_id)
            nd["sources"] = (nd.get("sources") or []) + (doc.get("sources") or [])
        else:
            nd = {k: v for k, v in doc.items() if k not in ("destination", "id", "deleted_at")}
            nd.update({"id": new_id, **plat, "migrated_from": [old_id], "migrated_at": now})
            new_docs[new_id] = nd
        supersede.setdefault(old_id, []).append(new_id)

existing = {d["id"] for d in req("GET", BASE + "?select=id")}
for new_id, nd in new_docs.items():
    if new_id in existing:
        print(f"skip (exists): {new_id}")
        continue
    req("POST", BASE, [{"id": new_id, "doc": nd}])
    print(f"created: {new_id}  sources={len(nd.get('sources') or [])}  from={nd['migrated_from']}")

for old_id, new_ids in supersede.items():
    doc = docs[old_id]
    if doc.get("superseded_by"):
        print(f"skip (already superseded): {old_id}")
        continue
    doc["superseded_by"] = new_ids
    doc["migrated_at"] = now
    req("PATCH", BASE + f"?id=eq.{old_id}", {"doc": doc})
    print(f"superseded: {old_id} -> {new_ids}")

print("done")
