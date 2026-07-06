#!/usr/bin/env python3
"""Next-day simulation: run EXACTLY what the daily run would for one source,
without waiting 24 hours.

The daily run = pull the source (fresh companies only - the 90-day scan window
plus signal_leads dedupe make re-runs equivalent to tomorrow's run) and then
AUTO-PUSH every new lead through the email-exclusive router (email -> Smartlead,
no email -> HeyReach). No manual ticks anywhere.

Usage:
  python3 app/simulate_daily.py --source <id> [--heyreach-proof]

--heyreach-proof: hiring leads are email-gated so they all route to Smartlead;
this flag additionally pushes ONE lead with its email withheld so the no-email
-> HeyReach rail is proven live too (clearly reported, removable via unpush).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--heyreach-proof", action="store_true")
    a = ap.parse_args()

    drafts = server.read_drafts()
    src = next((d for d in drafts if d.get("id") == a.source), None)
    if not src:
        print(f"source {a.source} not found"); sys.exit(1)

    # ── tomorrow's pull ────────────────────────────────────────────────
    r = server.pull_source({"id": a.source})
    print(f"pull ok={r.get('ok')} · {r.get('note') or r.get('message') or ''}")
    if not r.get("ok"):
        sys.exit(0 if "No live job posts" in str(r.get("message")) else 1)

    # reload - the pull rewrote the drafts file
    drafts = server.read_drafts()
    src = next(d for d in drafts if d.get("id") == a.source)
    prospects = src.get("prospects") or []
    dest = server.resolve_destination(src)
    print(f"destination: {dest}")

    # ── auto-push every new lead (zero user intervention) ─────────────
    pushed = []
    for i, pr in enumerate(prospects):
        if pr.get("pushed"):
            continue
        push = server.push_prospect(pr, dest)
        sent = [k for k, v in push["tools"].items() if v.get("ok")]
        if sent:
            pr["verdict"] = "keep"
            pr["pushed_to"] = "+".join(
                f"smartlead:{dest.get('smartlead_campaign_id')}" if k == "smartlead"
                else f"heyreach:{dest.get('heyreach_list_id')}" for k in sent)
            if pr.get("linkedin"):
                server.sb("PATCH", f"signal_leads?source_id=eq.{a.source}&linkedin_url=eq.{pr['linkedin']}",
                          {"status": "pushed", "pushed_to": pr["pushed_to"]})
        pushed.append({"name": pr.get("name"), "company": pr.get("company"),
                       "email": pr.get("email"), "linkedin": pr.get("linkedin"),
                       "tools": {k: v.get("message") for k, v in push["tools"].items()}})

    # ── optional: prove the no-email -> HeyReach rail with one lead ───
    if a.heyreach_proof and prospects:
        probe = dict(prospects[0])
        probe.pop("email", None); probe.pop("pushed", None); probe.pop("push_fail", None)
        orig_find = server.find_email
        server.find_email = lambda pr: None  # withhold the email -> router goes HeyReach
        try:
            hp = server.push_prospect(probe, dest)
        finally:
            server.find_email = orig_find
        print(f"heyreach rail proof ({probe.get('name')}): {json.dumps(hp['tools'])}")

    server.DRAFTS.write_text(json.dumps(drafts, indent=1))
    print(f"\n{len(pushed)} leads auto-pushed:")
    for p in pushed:
        print(f"  - {p['name']} @ {p['company']} · {p['email'] or 'no email'} · {json.dumps(p['tools'])}")


if __name__ == "__main__":
    main()
