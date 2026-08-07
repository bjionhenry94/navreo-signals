#!/usr/bin/env python3
"""
Smart Delivery Spam Placement Test (runner)

Creates a manual placement test via Smartlead's Smart Delivery API, polls
until the test completes (5–20 minutes typical), and writes the result JSON.

If Smart Delivery isn't accessible via API key on this tier, prints the
dashboard URL + paste-ready checklist so the audit step still produces an
actionable next step.

Usage:
    SMARTLEAD_API_KEY=xxx python3 run_spam_test.py \
        --campaign-id 12345 \
        --senders 100 \
        --out /tmp/audit/spam-test.json

    # API-availability probe only:
    python3 run_spam_test.py --probe-only
"""
import argparse
import json
import os
import sys
import time

# Import shared wrapper from sibling file
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _smart_delivery as sd  # noqa: E402


POLL_INTERVAL_SEC = 30
POLL_TIMEOUT_SEC = 25 * 60  # 25 min ceiling — typical test takes 5–20 min

# Smartlead Smart Delivery provider pools (observed from public docs):
# 20 = G Suite, 21 = Office365. These are the only two consistently
# available in the manual test flow.
DEFAULT_PROVIDER_IDS = [20, 21]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign-id", type=int)
    ap.add_argument("--senders", type=int, default=100,
                    help="Number of senders from the campaign to include in the test")
    ap.add_argument("--out", default=None,
                    help="Where to write the result JSON (only when API path works)")
    ap.add_argument("--api-key", default=os.environ.get("SMARTLEAD_API_KEY"))
    ap.add_argument("--probe-only", action="store_true",
                    help="Only check API availability, don't create a test")
    ap.add_argument("--providers", default=",".join(str(p) for p in DEFAULT_PROVIDER_IDS),
                    help="Comma-separated provider IDs (default: G Suite + Office365)")
    args = ap.parse_args()

    if not args.api_key:
        print("ERROR: SMARTLEAD_API_KEY not set and --api-key not given", file=sys.stderr)
        sys.exit(1)

    print(f"[run_spam_test] Probing Smart Delivery API access...", file=sys.stderr)
    endpoint = sd.detect_endpoint(args.api_key)

    if endpoint is None:
        print(f"[run_spam_test] Smart Delivery NOT accessible via API on this tier.",
              file=sys.stderr)
        print(sd.ui_fallback_instructions(campaign_id=args.campaign_id))
        # Write a small marker file so generate_report.py knows the test wasn't run
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
            with open(args.out, "w") as f:
                json.dump({
                    "status": "API_NOT_ACCESSIBLE",
                    "fallback": "dashboard",
                    "dashboard_url": sd.DASHBOARD_URL,
                    "campaign_id": args.campaign_id,
                }, f, indent=2)
        sys.exit(0)

    print(f"[run_spam_test] Smart Delivery endpoint: {endpoint}", file=sys.stderr)

    if args.probe_only:
        print(f"OK — Smart Delivery is reachable at {endpoint}")
        sys.exit(0)

    if not args.campaign_id:
        print("ERROR: --campaign-id required when actually creating a test", file=sys.stderr)
        sys.exit(1)
    if not args.out:
        print("ERROR: --out required when actually creating a test", file=sys.stderr)
        sys.exit(1)

    providers = [int(p.strip()) for p in args.providers.split(",") if p.strip()]
    payload = {
        "campaign_id": args.campaign_id,
        "provider_ids": providers,
        "sender_count": args.senders,
        "test_name": f"Audit_C{args.campaign_id}_{int(time.time())}",
    }

    print(f"[run_spam_test] Creating placement test for campaign {args.campaign_id} "
          f"({args.senders} senders, providers={providers})...", file=sys.stderr)
    res = sd.create_placement_test(args.api_key, payload, endpoint=endpoint)
    if not res.get("ok"):
        print(f"[run_spam_test] create failed: {res.get('error')}", file=sys.stderr)
        print(f"[run_spam_test] raw: {res.get('raw', '')[:300]}", file=sys.stderr)
        print("\nFalling back to dashboard:", file=sys.stderr)
        print(sd.ui_fallback_instructions(campaign_id=args.campaign_id))
        sys.exit(1)

    test_data = res.get("data") or {}
    # The test ID field name varies — try common variants
    test_id = (test_data.get("id") or test_data.get("test_id")
               or (test_data.get("data") or {}).get("id"))
    if not test_id:
        print("[run_spam_test] could not extract test ID from response — full payload:",
              file=sys.stderr)
        print(json.dumps(test_data, indent=2)[:1000], file=sys.stderr)
        sys.exit(1)

    print(f"[run_spam_test] Test created: id={test_id}. Polling for completion "
          f"(every {POLL_INTERVAL_SEC}s, timeout {POLL_TIMEOUT_SEC // 60} min)...",
          file=sys.stderr)

    started = time.time()
    last_status = None
    final = None
    while time.time() - started < POLL_TIMEOUT_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        poll = sd.get_test_result(args.api_key, test_id, endpoint=endpoint)
        if not poll.get("ok"):
            print(f"[run_spam_test]   poll error: {poll.get('error')}", file=sys.stderr)
            continue
        d = poll.get("data") or {}
        status = (d.get("status") or d.get("test_status") or "").upper()
        if status != last_status:
            print(f"[run_spam_test]   status={status} elapsed={int(time.time() - started)}s",
                  file=sys.stderr)
            last_status = status
        if status in ("COMPLETED", "FINISHED", "DONE", "SUCCESS"):
            final = d
            break
        if status in ("FAILED", "ERROR", "CANCELLED"):
            print(f"[run_spam_test]   terminal failure status: {status}", file=sys.stderr)
            final = d
            break

    if final is None:
        print(f"[run_spam_test] Timed out waiting for test {test_id}", file=sys.stderr)
        sys.exit(2)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(final, f, indent=2)
    print(f"[run_spam_test] Wrote result to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
