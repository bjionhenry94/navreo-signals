#!/usr/bin/env python3
"""Score the reply categoriser against the labelled fixture set.

The categoriser itself lives OUTSIDE this repo — it is the gpt-4o-mini step
(module 5) inside Make scenario 9251436, which writes `replies.category`.
This harness reproduces that call exactly (same model, temperature 0,
json_object response) so a prompt change can be scored BEFORE it ships to
Make, and re-scored any time drift is suspected.

Usage:
  python3 scripts/eval_categoriser.py                # prompt fetched live from Make
  python3 scripts/eval_categoriser.py --prompt-file p.txt
  python3 scripts/eval_categoriser.py --only-mr      # just the Meeting Request traps

Pass criteria (setter-platform-stabilise step 9 done-rule): accuracy >= 90%
on the fixture set AND zero false "Meeting Request" labels.

Env: OPENAI_API_KEY required; MAKE_API_TOKEN required unless --prompt-file.
Reads ~/.navreo-keys.env when the vars aren't already exported.
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "app", "fixtures", "categoriser_fixtures.json")
SCENARIO_ID = 9251436
GPT_MODULE_ID = 5
VALID = {"Interested", "Meeting Request", "Call Booked", "Information Request",
         "Out Of Office", "Wrong Person", "Not Interested", "Do Not Contact"}

_CTX = ssl.create_default_context()
try:  # macOS python.org builds often miss the CA bundle — mirror certifi if present
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


def _load_env():
    path = os.path.expanduser("~/.navreo-keys.env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def _http_json(url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "navreo-eval/1.0", **headers}  # Make's API 403s the default urllib UA
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, context=_CTX, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_make_prompt():
    tok = os.environ.get("MAKE_API_TOKEN")
    if not tok:
        sys.exit("MAKE_API_TOKEN missing — pass --prompt-file instead")
    bp = _http_json(f"https://eu2.make.com/api/v2/scenarios/{SCENARIO_ID}/blueprint",
                    {"Authorization": f"Token {tok}"})

    def find(m):
        if m.get("id") == GPT_MODULE_ID:
            return m
        for route in m.get("routes") or []:
            for f in route.get("flow") or []:
                got = find(f)
                if got:
                    return got
        return None
    for m in bp["response"]["blueprint"]["flow"]:
        hit = find(m)
        if hit:
            return hit["mapper"]["messages"][0]["content"]
    sys.exit(f"module {GPT_MODULE_ID} not found in scenario {SCENARIO_ID}")


def categorise(system_prompt, reply_text, key):
    user = ("EMAIL THREAD — the prospect's LATEST reply is at the TOP; the quoted earlier "
            "messages (our outreach) appear BELOW it:\n\n" + reply_text +
            "\n\n---\n\nCategorise the prospect's LATEST reply (the top message). Return JSON only.")
    body = {"model": "gpt-4o-mini", "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user}]}
    out = _http_json("https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, body)
    raw = out["choices"][0]["message"]["content"]
    try:
        return json.loads(raw).get("category")
    except (ValueError, AttributeError):
        m = re.search(r'"category"\s*:\s*"([^"]+)"', raw)
        return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file")
    ap.add_argument("--only-mr", action="store_true")
    args = ap.parse_args()
    _load_env()
    key = os.environ.get("OPENAI_API_KEY") or sys.exit("OPENAI_API_KEY missing")
    prompt = open(args.prompt_file).read() if args.prompt_file else fetch_make_prompt()
    cases = json.load(open(FIXTURES))["cases"]
    if args.only_mr:
        cases = [c for c in cases if "Meeting Request" in c["expected"] or "MR" in c["note"]
                 or "meeting" in c["note"].lower() or "MR" in c.get("note", "")]
    ok = 0
    false_mr = []
    fails = []
    for c in cases:
        got = categorise(prompt, c["reply"], key)
        hit = got in c["expected"]
        ok += hit
        if got == "Meeting Request" and "Meeting Request" not in c["expected"]:
            false_mr.append(c["id"])
        if not hit:
            fails.append((c["id"], got, c["expected"], c["note"]))
        print(f"{'PASS' if hit else 'FAIL'}  {c['id'][:36]:38} got={got!r:24} want={c['expected']}")
    acc = 100.0 * ok / max(len(cases), 1)
    print(f"\naccuracy: {ok}/{len(cases)} = {acc:.0f}%   false Meeting Request: {len(false_mr)} {false_mr}")
    passing = acc >= 90.0 and not false_mr
    print("VERDICT:", "PASS" if passing else "FAIL")
    if fails:
        print("\nfailures:")
        for f in fails:
            print(" -", f)
    sys.exit(0 if passing else 1)


if __name__ == "__main__":
    main()
