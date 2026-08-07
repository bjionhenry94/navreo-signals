#!/usr/bin/env python3
"""Bulk-check Porkbun domain availability via /domain/checkDomain.

Usage:
    PORKBUN_API_KEY=pk1_... PORKBUN_SECRET_API_KEY=sk1_... \
        python3 bulk_check_porkbun.py /path/to/candidates.txt

Input: one domain per line. Blank lines and lines starting with `#` are skipped.

Output:
    - Per-domain stdout line: status code, AVAIL/TAKEN/PREMIUM/FAIL, prices
    - JSON sidecar at <input>.results.json with full per-domain detail

Exit codes:
    0  - all candidates checked (some may be TAKEN or FAIL — that's normal)
    1  - credentials invalid, network error, or empty input
"""

import json
import os
import re
import sys
import time

import requests

API_KEY = os.environ.get("PORKBUN_API_KEY")
SECRET_KEY = os.environ.get("PORKBUN_SECRET_API_KEY")

if not API_KEY or not SECRET_KEY:
    sys.exit("Missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY env vars")

INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "candidates.txt"
BASE_URL = "https://api.porkbun.com/api/json/v3"
# Porkbun's /checkDomain endpoint is rate-limited to 1 call per 10 seconds (sliding window).
# Going below 11s causes most calls to return "1 out of 1 checks within 10 seconds used".
SLEEP_SECONDS = 11.0
TIMEOUT = 30

DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def ping():
    try:
        r = requests.post(
            f"{BASE_URL}/ping",
            json={"apikey": API_KEY, "secretapikey": SECRET_KEY},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        sys.exit(f"NETWORK ERROR on /ping: {e}")
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"PING FAIL [{r.status_code}]: {r.text}")
    if not (r.ok and data.get("status") == "SUCCESS"):
        sys.exit(f"PING FAIL [{r.status_code}]: {data}")
    print(f"OK ping (your IP: {data.get('yourIp')})")


def check_domain(domain):
    url = f"{BASE_URL}/domain/checkDomain/{domain}"
    payload = {"apikey": API_KEY, "secretapikey": SECRET_KEY}
    try:
        r = requests.post(url, json=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        return 0, {"exception": str(e)}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text}


def classify(data):
    """Return (label, summary_dict) from a checkDomain response."""
    if data.get("status") != "SUCCESS":
        return "FAIL", {"message": data.get("message", str(data))}
    resp = data.get("response", {})
    avail = resp.get("avail")
    premium = resp.get("premium") == "yes"
    if avail != "yes":
        return "TAKEN", {}
    return ("PREMIUM" if premium else "AVAIL"), {
        "price": resp.get("price"),
        "regular_price": resp.get("regularPrice"),
        "first_year_promo": resp.get("firstYearPromo") == "yes",
        "premium": premium,
        "renewal": (resp.get("additional") or {}).get("renewal", {}).get("price"),
        "transfer": (resp.get("additional") or {}).get("transfer", {}).get("price"),
    }


def main():
    if not os.path.exists(INPUT_FILE):
        sys.exit(f"Input file not found: {INPUT_FILE}")

    candidates = []
    with open(INPUT_FILE) as f:
        for line in f:
            d = line.strip().lower()
            if not d or d.startswith("#"):
                continue
            if not DOMAIN_RE.match(d):
                print(f"SKIP invalid syntax: {d}")
                continue
            candidates.append(d)

    if not candidates:
        sys.exit("No valid candidates in input")

    print(f"Checking {len(candidates)} candidates (rate-limited 1s/call, ~{len(candidates)}s)...")
    ping()
    print()

    results = []
    counts = {"AVAIL": 0, "PREMIUM": 0, "TAKEN": 0, "FAIL": 0}

    for i, domain in enumerate(candidates, 1):
        status, data = check_domain(domain)
        label, summary = classify(data)
        counts[label] = counts.get(label, 0) + 1
        record = {"domain": domain, "label": label, "http_status": status, **summary, "raw": data}
        results.append(record)

        prefix = f"[{i:>3}/{len(candidates)}]"
        if label == "AVAIL":
            print(f"{prefix} AVAIL    {domain:40s}  Y1 ${summary['price']:<6}  renew ${summary['renewal']}")
        elif label == "PREMIUM":
            print(f"{prefix} PREMIUM  {domain:40s}  Y1 ${summary['price']:<6}  renew ${summary['renewal']}")
        elif label == "TAKEN":
            print(f"{prefix} TAKEN    {domain}")
        else:
            print(f"{prefix} FAIL     {domain}  {summary.get('message','')}")

        time.sleep(SLEEP_SECONDS)

    sidecar = INPUT_FILE.rsplit(".", 1)[0] + ".results.json"
    with open(sidecar, "w") as f:
        json.dump({"counts": counts, "results": results}, f, indent=2)

    print()
    print(f"Results: AVAIL={counts['AVAIL']}  PREMIUM={counts['PREMIUM']}  TAKEN={counts['TAKEN']}  FAIL={counts['FAIL']}")
    print(f"Sidecar: {sidecar}")


if __name__ == "__main__":
    main()
