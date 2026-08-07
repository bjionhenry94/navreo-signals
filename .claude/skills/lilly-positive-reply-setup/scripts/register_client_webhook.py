#!/usr/bin/env python3
"""
register_client_webhook.py :: lilly-positive-reply-setup (external / client-workspace mode)

Registers the new Make scenario's hook URL as an EMAIL_REPLY webhook on every ACTIVE campaign
in the CLIENT's OWN Smartlead workspace, using the client's API key. This is what makes their
replies reach the scenario built by build_external_scenario.py.

USAGE
  python3 register_client_webhook.py "<CLIENT_SMARTLEAD_KEY>" "<MAKE_HOOK_URL>" [--dry-run]

Idempotent-ish: re-running re-posts the same webhook (Smartlead upserts by name). Prints each
campaign + the API response so failures are visible. Run again after the client launches NEW
campaigns (a webhook is per-campaign).
"""
import json, sys, subprocess

BASE = "https://server.smartlead.ai/api/v1"
WEBHOOK_NAME = "Navreo positive-reply router"

def get(url):
    return subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=120).stdout

def post(url, body):
    return subprocess.run(["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json",
                           "-d", body], capture_output=True, text=True, timeout=120).stdout

def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    dry = "--dry-run" in sys.argv
    if len(args) < 2:
        sys.exit("usage: register_client_webhook.py <SMARTLEAD_KEY> <MAKE_HOOK_URL> [--dry-run]")
    key, hook_url = args[0], args[1]

    raw = get("%s/campaigns?api_key=%s" % (BASE, key))
    try:
        data = json.loads(raw)
    except Exception:
        sys.exit("! could not list campaigns; check the API key. Response: %s" % raw[:200])
    camps = data if isinstance(data, list) else (data.get("data") or data.get("campaigns") or [])
    active = [c for c in camps if str(c.get("status", "")).upper() == "ACTIVE"]
    print("Found %d campaigns (%d active) in this workspace." % (len(camps), len(active)))

    # NOTE: do NOT send "categories" — Smartlead rejects an empty array ("does not contain 1
    # required value(s)"). Omitting the key entirely makes EMAIL_REPLY fire on ALL replies.
    body = json.dumps({"id": None, "name": WEBHOOK_NAME, "webhook_url": hook_url,
                       "event_types": ["EMAIL_REPLY"]})
    done = 0
    for c in active:
        cid, name = c.get("id"), c.get("name", "")
        if dry:
            print("  [dry-run] would register on %s  %s" % (cid, name))
            continue
        r = post("%s/campaigns/%s/webhooks?api_key=%s" % (BASE, cid, key), body)
        ok = ('"ok"' in r) or ('success' in r.lower()) or ('"id"' in r)
        print("  %s  %-45.45s -> %s" % ("OK " if ok else "!! ", name, r[:120]))
        done += 1 if ok else 0
    if not dry:
        print("Registered EMAIL_REPLY webhook on %d/%d active campaigns." % (done, len(active)))
        print("NOTE: webhooks are per-campaign — re-run this after the client launches new campaigns.")

if __name__ == "__main__":
    main()
