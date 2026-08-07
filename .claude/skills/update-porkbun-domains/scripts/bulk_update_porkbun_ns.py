#!/usr/bin/env python3
"""Bulk-update Porkbun authoritative nameservers from a CSV.

Usage:
    PORKBUN_API_KEY=pk1_... PORKBUN_SECRET_API_KEY=sk1_... \
        python3 bulk_update_porkbun_ns.py /path/to/domains.csv

CSV format (header row required):
    Domain,Nameserver 1,Nameserver 2[,Nameserver 3,Nameserver 4]

Column names are case-insensitive and space-tolerant. The first column matching
`domain` is treated as the domain; any column whose name starts with
`nameserver` or `ns` (case-insensitive) is treated as a nameserver column.

Each domain must have API access enabled in the Porkbun control panel
(Domain Management → toggle API ACCESS per domain). Without this, that row's
call returns an error.

Exit codes:
    0  - all rows updated successfully
    1  - one or more rows failed (see per-row output for which)
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

CSV_FILE = sys.argv[1] if len(sys.argv) > 1 else "domains.csv"
BASE_URL = "https://api.porkbun.com/api/json/v3"
SLEEP_SECONDS = 1.0


def update_ns(domain, nameservers):
    url = f"{BASE_URL}/domain/updateNs/{domain}"
    payload = {
        "apikey": API_KEY,
        "secretapikey": SECRET_KEY,
        "ns": nameservers,
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        return 0, {"exception": str(e)}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text}


def collect_nameservers(row):
    ns = []
    for key, val in row.items():
        if key is None or val is None:
            continue
        k = key.strip().lower().replace(" ", "")
        if k.startswith("nameserver") or (k.startswith("ns") and k != "ns"):
            v = val.strip()
            if v:
                ns.append(v)
    return ns


def main():
    ok = 0
    fail = 0
    failed_rows = []

    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain = (row.get("Domain") or row.get("domain") or "").strip()
            nameservers = collect_nameservers(row)

            if not domain or len(nameservers) < 2:
                print(f"SKIP {domain or '(blank)'}: need domain + >=2 nameservers (got {nameservers})")
                fail += 1
                failed_rows.append(domain or "(blank)")
                continue

            status_code, data = update_ns(domain, nameservers)

            if status_code == 200 and data.get("status") == "SUCCESS":
                print(f"OK   {domain}: {nameservers}")
                ok += 1
            else:
                print(f"FAIL {domain} [{status_code}]: {data}")
                fail += 1
                failed_rows.append(domain)

            time.sleep(SLEEP_SECONDS)

    print()
    print(f"Total OK:   {ok}")
    print(f"Total FAIL: {fail}")
    if failed_rows:
        print()
        print("Failed domains (rerun after fixing root cause, e.g. enable API access):")
        for d in failed_rows:
            print(f"  {d}")

    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
