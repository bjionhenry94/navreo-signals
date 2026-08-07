#!/usr/bin/env python3
"""Validate Porkbun API credentials via /ping.

Usage:
    PORKBUN_API_KEY=pk1_... PORKBUN_SECRET_API_KEY=sk1_... \
        python3 porkbun_ping.py

Exit codes:
    0  - credentials valid (response includes credentialsValid: true)
    1  - credentials invalid, IP-locked, or network error
"""

import os
import sys

import requests

API_KEY = os.environ.get("PORKBUN_API_KEY")
SECRET_KEY = os.environ.get("PORKBUN_SECRET_API_KEY")

if not API_KEY or not SECRET_KEY:
    sys.exit("Missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY env vars")

try:
    r = requests.post(
        "https://api.porkbun.com/api/json/v3/ping",
        json={"apikey": API_KEY, "secretapikey": SECRET_KEY},
        timeout=30,
    )
except requests.RequestException as e:
    print(f"NETWORK ERROR: {e}")
    sys.exit(1)

print(r.status_code, r.text)

try:
    data = r.json()
except ValueError:
    sys.exit(1)

sys.exit(0 if r.ok and data.get("status") == "SUCCESS" and data.get("credentialsValid") else 1)
