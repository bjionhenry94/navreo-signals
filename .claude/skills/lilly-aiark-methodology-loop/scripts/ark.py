#!/usr/bin/env python3
"""Compact AI Ark caller for the methodology loop.
company mode -> MCP JSON-RPC (flat params, the validated transport)
people mode  -> REST developer-portal (nested body, current-role filter)
Prints one compact line per row + totalElements. Keeps LLM context small.
"""
import json, os, subprocess, sys

def _key():
    k = os.environ.get("AI_ARK_API_KEY")
    if not k:
        for line in open(os.path.expanduser("~/.navreo-keys.env")):
            if line.startswith("export AI_ARK_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("no AI_ARK_API_KEY")
    return k

def post(url, body, headers):
    cmd = ["curl", "-sS", "--max-time", "120", "-X", "POST", url, "-H", "Content-Type: application/json"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["-d", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out)

def company(args):
    key = _key()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "company_search", "arguments": args}}
    resp = post(f"https://api.ai-ark.com/v1/mcp?token={key}", body,
                {"Accept": "application/json, text/event-stream"})
    txt = resp["result"]["content"][0]["text"]
    data = json.loads(txt)
    print(f"totalElements: {data.get('totalElements')}  page: {data.get('number')}  rows: {len(data.get('content', []))}")
    for c in data.get("content", []):
        s = c.get("summary", {})
        loc = (c.get("location", {}).get("headquarter", {}) or {})
        desc = (s.get("description") or s.get("overview") or s.get("seo") or "")[:220].replace("\n", " ")
        kw = ",".join((c.get("keywords") or [])[:8])
        print(f"- {s.get('name')} | {c.get('link',{}).get('domain_ltd')} | {loc.get('country')} | staff:{(s.get('staff') or {}).get('total')} | ind:{s.get('industry')} | kw:{kw} | {desc}")

def people(args):
    key = _key()
    data = post("https://api.ai-ark.com/api/developer-portal/v1/people", args, {"X-TOKEN": key})
    print(f"totalElements: {data.get('totalElements')}  rows: {len(data.get('content', []))}")
    for p in data.get("content", []):
        name = p.get("fullName") or ((p.get("firstName") or "") + " " + (p.get("lastName") or "")).strip()
        comp = p.get("company") or {}
        cid = comp.get("id")
        # collect current positions (date.end null) grouped by whether at matched company
        cur_at_target, cur_other = [], []
        for g in p.get("position_groups") or p.get("positionGroups") or []:
            gcid = (g.get("company") or {}).get("id")
            for pos in g.get("profile_positions") or g.get("profilePositions") or g.get("positions") or []:
                d = pos.get("date") or {}
                if d.get("end") is None:
                    t = pos.get("title")
                    (cur_at_target if gcid == cid else cur_other).append(t)
        headline = p.get("headline") or p.get("title") or ""
        print(f"- {name} | company:{comp.get('name')} ({comp.get('domain') or ''}) | curr@target:{cur_at_target} | currOther:{cur_other[:3]} | headline:{str(headline)[:80]}")

if __name__ == "__main__":
    mode = sys.argv[1]
    args = json.loads(sys.argv[2])
    (company if mode == "company" else people)(args)
