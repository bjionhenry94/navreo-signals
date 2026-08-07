#!/usr/bin/env python3
"""
Shared Smart Delivery API wrapper.

Smartlead's Smart Delivery (inbox-placement test) endpoints live at
/api/v1/smart-delivery/* on server.smartlead.ai but are NOT consistently
exposed for API-key auth across all account tiers — they often require
session-cookie auth (i.e. logged-in dashboard). This module:

  1. probes a small set of endpoints to detect whether Smart Delivery is
     reachable via the API key on the caller's account, and
  2. provides thin wrappers that return {ok: bool, data: ..., error: ...}
     dicts so callers can degrade gracefully when the API isn't exposed.

If Smart Delivery is gated behind the dashboard for your tier, callers
should fall back to printing the UI link:
    https://app.smartlead.ai/app/smart-delivery
"""
import json
import os
import subprocess

API_BASE = "https://server.smartlead.ai/api/v1"
DASHBOARD_URL = "https://app.smartlead.ai/app/smart-delivery"

# Known Smart Delivery endpoint variants observed in Smartlead's evolving
# API surface. Probed in order. First one to return 200 with JSON is treated
# as the canonical path.
PROBE_PATHS = [
    "/smart-delivery/manual-placement-tests",
    "/smart-delivery/tests",
    "/sd/spam_test",
    "/sd/manual-placement-tests",
]


def _curl(method, url, body=None, timeout=30):
    cmd = ["curl", "-sS", "-X", method, url, "--max-time", str(timeout),
           "-w", "\n__HTTP_STATUS__:%{http_code}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return None, 0
    raw = r.stdout
    status = 0
    body_str = raw
    if "\n__HTTP_STATUS__:" in raw:
        body_str, _, status_str = raw.rpartition("\n__HTTP_STATUS__:")
        try:
            status = int(status_str.strip())
        except ValueError:
            status = 0
    return body_str, status


def detect_endpoint(api_key):
    """Returns the first reachable Smart Delivery endpoint, or None."""
    for path in PROBE_PATHS:
        url = f"{API_BASE}{path}?api_key={api_key}"
        body, status = _curl("GET", url)
        if status == 200:
            try:
                json.loads(body)
                return path
            except (json.JSONDecodeError, TypeError):
                continue
        # POST-only endpoints sometimes 405 but still confirm presence
        if status in (400, 405) and body and "Cannot" not in (body or ""):
            return path
    return None


def is_accessible(api_key):
    """Returns True if Smart Delivery looks reachable via API key on this tier."""
    return detect_endpoint(api_key) is not None


def create_placement_test(api_key, payload, endpoint=None):
    """
    POST a new manual placement test. Returns dict:
       {"ok": True, "data": <response_json>}  or
       {"ok": False, "error": "<message>", "status": <http_status>, "raw": "<body>"}
    """
    if endpoint is None:
        endpoint = detect_endpoint(api_key) or PROBE_PATHS[0]
    url = f"{API_BASE}{endpoint}?api_key={api_key}"
    body, status = _curl("POST", url, body=payload, timeout=60)
    if status == 200:
        try:
            return {"ok": True, "data": json.loads(body), "endpoint": endpoint}
        except json.JSONDecodeError:
            return {"ok": False, "error": "non-JSON response", "status": status, "raw": body}
    return {"ok": False, "error": f"HTTP {status}", "status": status, "raw": body[:500]}


def get_test_result(api_key, test_id, endpoint=None):
    """GET a placement test's current result. Same return shape as create_placement_test."""
    if endpoint is None:
        endpoint = detect_endpoint(api_key) or PROBE_PATHS[0]
    url = f"{API_BASE}{endpoint}/{test_id}?api_key={api_key}"
    body, status = _curl("GET", url, timeout=30)
    if status == 200:
        try:
            return {"ok": True, "data": json.loads(body), "endpoint": endpoint}
        except json.JSONDecodeError:
            return {"ok": False, "error": "non-JSON response", "status": status, "raw": body}
    return {"ok": False, "error": f"HTTP {status}", "status": status, "raw": body[:500]}


def ui_fallback_instructions(campaign_id=None):
    """Returns paste-ready instructions for running the test from the dashboard."""
    lines = [
        "Smart Delivery API isn't accessible via your API key on this Smartlead",
        "tier. Run the test from the dashboard instead:",
        "",
        f"  1. Open: {DASHBOARD_URL}",
        "  2. Click '+ New Test' → 'Manual Placement Test'",
        "  3. Provider pool: leave default (G Suite + Office365)",
    ]
    if campaign_id:
        lines += [
            f"  4. Pick the campaign: {campaign_id}",
            "  5. Select ~100 of its senders (or 'All' if the campaign has <100)",
        ]
    else:
        lines += [
            "  4. Pick the campaign you want to test",
            "  5. Select ~100 of its senders",
        ]
    lines += [
        "  6. Run → wait 5–20 minutes for completion",
        "  7. Export the result JSON if you want it joined into the audit report",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    api_key = os.environ.get("SMARTLEAD_API_KEY")
    if not api_key:
        print("ERROR: SMARTLEAD_API_KEY not set")
        raise SystemExit(1)
    ep = detect_endpoint(api_key)
    if ep:
        print(f"Smart Delivery accessible at: {API_BASE}{ep}")
    else:
        print("Smart Delivery is NOT accessible via API key on this tier.")
        print()
        print(ui_fallback_instructions())
