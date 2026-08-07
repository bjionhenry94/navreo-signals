#!/usr/bin/env python3
"""List all Porkbun domains on the account with registration + expiry dates.

Calls POST /api/json/v3/domain/listAll, paginating via the `start` offset
(Porkbun returns up to 1000 domains per page). Prints a TSV to stdout:

    domain<TAB>createDate<TAB>expireDate<TAB>status

and writes the same rows to a CSV next to the script's logs dir.

Usage:
    PORKBUN_API_KEY=pk1_... PORKBUN_SECRET_API_KEY=sk1_... \
        python3 list_porkbun_domains.py

Exit codes:
    0  - listed successfully (>=1 domain)
    1  - credential/network error or zero domains
"""

import csv
import os
import sys
import time

import requests

API_KEY = os.environ.get("PORKBUN_API_KEY")
SECRET_KEY = os.environ.get("PORKBUN_SECRET_API_KEY")

if not API_KEY or not SECRET_KEY:
    sys.exit("Missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY env vars")

BASE_URL = "https://api.porkbun.com/api/json/v3"
PAGE = 1000
OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "logs", "porkbun_domains.csv")


def fetch_page(start):
    r = requests.post(
        f"{BASE_URL}/domain/listAll",
        json={
            "apikey": API_KEY,
            "secretapikey": SECRET_KEY,
            "start": str(start),
            "includeLabels": "yes",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def main():
    all_domains = []
    start = 0
    while True:
        try:
            data = fetch_page(start)
        except requests.RequestException as e:
            sys.exit(f"NETWORK ERROR at start={start}: {e}")

        if data.get("status") != "SUCCESS":
            sys.exit(f"API ERROR at start={start}: {data}")

        batch = data.get("domains", [])
        all_domains.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE
        time.sleep(1.0)

    # de-dupe by domain, keep first
    seen = set()
    rows = []
    for d in all_domains:
        name = (d.get("domain") or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(
            {
                "domain": name,
                "createDate": d.get("createDate", ""),
                "expireDate": d.get("expireDate", ""),
                "status": d.get("status", ""),
            }
        )

    rows.sort(key=lambda x: x["domain"])

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["domain", "createDate", "expireDate", "status"])
        w.writeheader()
        w.writerows(rows)

    for r in rows:
        print(f"{r['domain']}\t{r['createDate']}\t{r['expireDate']}\t{r['status']}")

    print(f"\n# {len(rows)} domains on the Porkbun account", file=sys.stderr)
    print(f"# saved to {os.path.abspath(OUT_CSV)}", file=sys.stderr)

    sys.exit(0 if rows else 1)


if __name__ == "__main__":
    main()
