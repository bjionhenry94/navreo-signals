#!/usr/bin/env python3
"""Fetch a Smartlead client's numeric Client ID by name (substring, case-insensitive).
Usage: python3 get_smartlead_client.py "Arnic"
Prints matching clients as: <id>\t<name>\t<email>. Empty output = no match (set the client up in Smartlead first).
Env: SMARTLEAD_API_KEY (from ~/.navreo-keys.env)."""
import os, sys, json, subprocess
KEY = os.environ["SMARTLEAD_API_KEY"]
q = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
out = subprocess.run(["curl", "-s", f"https://server.smartlead.ai/api/v1/client/?api_key={KEY}"],
                     capture_output=True, text=True, timeout=60).stdout
try:
    clients = json.loads(out)
except Exception:
    print("ERROR: could not parse Smartlead /client response:", out[:300]); sys.exit(1)
clients = clients if isinstance(clients, list) else clients.get("data", [])
def blob(c):
    return " ".join(str(c.get(k, "") or "") for k in ("name", "logo", "email")).lower()
hits = [c for c in clients if q in blob(c)] if q else clients
for c in hits:
    print(f"{c.get('id')}\t{c.get('name')}\t(logo: {c.get('logo','')})\t{c.get('email','')}")
if not hits:
    print(f"(no Smartlead client matches '{sys.argv[1] if len(sys.argv)>1 else ''}' — create the client in Smartlead first)")
