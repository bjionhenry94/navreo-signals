"""signal-push-uxlab reset: empty the live test targets + clear local verdicts.

Removes every lead from Smartlead campaign 3591996 and HeyReach list 768931
("Arna test"), then resets verdict/pushed stamps on cdraft-1's sources so the
next tester starts from a clean slate. Cached emails are kept (cost guard —
re-enrichment would burn Prospeo credits for the same answer).
"""
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

SMARTLEAD_CAMPAIGN = 3591996
HEYREACH_LIST = 768931
DRAFTS = Path(__file__).resolve().parent / "data" / "draft_sources.json"
CTX = ssl.create_default_context(cafile=certifi.where())

KEYS = {}
for line in (Path.home() / ".navreo-keys.env").read_text().splitlines():
    m = re.match(r"^(?:export\s+)?([A-Z_]+)=(\S+)", line.strip())
    if m:
        KEYS[m.group(1)] = m.group(2).strip("\"'")


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "User-Agent": "navreo-prototype/1.0 (curl-compatible)",  # default urllib UA gets blocked
                 **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            raw = r.read().decode(errors="replace")
            try:
                return json.loads(raw or "{}")
            except ValueError:  # smartlead DELETE returns literal "success"
                return {"ok": True, "_raw": raw[:300]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return json.loads(raw or "{}")
        except ValueError:
            raise RuntimeError(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {raw[:200]}") from e


def reset_smartlead():
    base = "https://server.smartlead.ai/api/v1"
    key = KEYS["SMARTLEAD_API_KEY"]
    removed = 0
    for _ in range(10):  # loop until the campaign reads empty
        d = call("GET", f"{base}/campaigns/{SMARTLEAD_CAMPAIGN}/leads?api_key={key}")
        rows = d.get("data") or []
        if not rows:
            break
        for r in rows:
            lid = (r.get("lead") or {}).get("id")
            out = call("DELETE", f"{base}/campaigns/{SMARTLEAD_CAMPAIGN}/leads/{lid}?api_key={key}")
            print(f"smartlead: deleted lead {lid} -> {out.get('ok', out)}")
            removed += 1
    print(f"smartlead: {removed} lead(s) removed, campaign now empty: {not rows}")


def reset_heyreach():
    hdr = {"X-API-KEY": KEYS["HEYREACH_API_KEY"]}
    d = call("POST", "https://api.heyreach.io/api/public/list/GetLeadsFromList",
             {"listId": HEYREACH_LIST, "limit": 100, "offset": 0}, hdr)
    urls = [x.get("profileUrl") for x in (d.get("items") or []) if x.get("profileUrl")]
    if urls:
        out = call("DELETE", "https://api.heyreach.io/api/public/list/DeleteLeadsFromListByProfileUrl",
                   {"listId": HEYREACH_LIST, "profileUrls": urls}, hdr)
        print(f"heyreach: deleted {len(urls)} -> {out}")
    left = call("POST", "https://api.heyreach.io/api/public/list/GetLeadsFromList",
                {"listId": HEYREACH_LIST, "limit": 10, "offset": 0}, hdr)
    print(f"heyreach: {len(urls)} lead(s) removed, list now empty: {not (left.get('items') or [])}")


def reset_supabase():
    """signal_leads rows for cdraft-1 sources back to status=new (keeps emails)."""
    url, key = KEYS.get("SUPABASE_URL"), KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("supabase: no keys, skipped")
        return
    drafts = json.loads(DRAFTS.read_text())
    ids = ",".join(d["id"] for d in drafts if d.get("campaign_id") == "cdraft-1")
    out = call("PATCH", f"{url}/rest/v1/signal_leads?source_id=in.({ids})&status=neq.new",
               {"status": "new", "pushed_to": None},
               {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=representation"})
    print(f"supabase: {len(out) if isinstance(out, list) else out} rows reset to new")


def reset_local():
    drafts = json.loads(DRAFTS.read_text())
    n = 0
    for d in drafts:
        if d.get("campaign_id") != "cdraft-1":
            continue
        for pr in (d.get("prospects") or []):
            for k in ("verdict", "pushed", "pushed_to", "push_fail"):
                if pr.pop(k, None) is not None:
                    n += 1
            pr["verdict"] = None
    DRAFTS.write_text(json.dumps(drafts, indent=1))
    print(f"local: cleared stamps on cdraft-1 prospects ({n} fields)")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "smartlead"):
        reset_smartlead()
    if which in ("all", "heyreach"):
        reset_heyreach()
    if which in ("all", "local"):
        reset_local()
    if which in ("all", "supabase"):
        reset_supabase()
