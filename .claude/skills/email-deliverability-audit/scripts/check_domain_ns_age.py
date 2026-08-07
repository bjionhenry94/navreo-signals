#!/usr/bin/env python3
"""
Domain NS + age check + actual-vs-expected NS drift detection.

For each unique domain in inboxes.csv, runs:
  - dig NS <domain> +short        (to get current nameservers)
  - rdap.org lookup               (to get registration date + expiry)
  - Cross-reference batches.json  (to get expected NS provider + pair)

Outputs per-domain:
  - ns_records (sorted, joined by ;)
  - ns_provider_hint (inferred from NS pattern: cloudflare / azure-dns / dnsimple / godaddy / porkbun / other)
  - created_date (registration date)
  - expires_date
  - age_days, expiry_days
  - batch                  (batch this domain is assigned to in domain_batches.csv, or empty)
  - expected_ns_provider   (per the batch definition in batches.json, or empty)
  - expected_ns_pair       (specific NS pair if the batch pins one, else empty)
  - ns_match               (TRUE / FALSE / UNKNOWN when no batch assignment or no expected)

Flags:
  - flag_new_domain      = age_days < 30
  - flag_expiring_soon   = expiry_days < 60
  - flag_no_ns           = ns_records empty (broken)
  - flag_ns_drift        = TRUE when batch defines an expected provider and actual doesn't match

Summary printed to stdout:
  - Per-provider distribution
  - Per-batch actual-vs-expected scoreboard (matches / drift / dead / unknown)
  - Detail lines for every drift

Usage:
  python3 check_domain_ns_age.py --from-csv=/tmp/audit/inboxes.csv --out=/tmp/audit/ns_age.csv
  python3 check_domain_ns_age.py --from-csv=/tmp/audit/inboxes.csv --out=/tmp/audit/ns_age.csv --workers=20
  python3 check_domain_ns_age.py --from-csv=/tmp/audit/inboxes.csv --out=/tmp/audit/ns_age.csv --db-dir=<path>
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone


NS_PROVIDER_PATTERNS = [
    ("cloudflare", re.compile(r"\.ns\.cloudflare\.com\.?$", re.I)),
    ("azure-dns",  re.compile(r"\.azure-dns\.(?:com|net|org|info)\.?$", re.I)),
    ("dnsimple",   re.compile(r"dnsimple(?:-edge)?\.(?:com|net|org|io)\.?$", re.I)),
    ("aws-route53",re.compile(r"awsdns-\d+\.(?:com|net|org|co\.uk)\.?$", re.I)),
    ("cloudns",    re.compile(r"\.cloudns\.(?:net|com|uk|org|io|info|club|biz|cc|us|asia|in|eu)\.?$", re.I)),  # Zapmail's NS provider
    ("godaddy",    re.compile(r"\.domaincontrol\.com\.?$", re.I)),
    ("porkbun",    re.compile(r"\.porkbun\.com\.?$", re.I)),
    ("namecheap",  re.compile(r"\.registrar-servers\.com\.?$", re.I)),
    ("google",     re.compile(r"\.googledomains\.com\.?$", re.I)),
    ("hostgator",  re.compile(r"\.hostgator\.com\.?$", re.I)),
    ("namesilo",   re.compile(r"\.namesilo\.com\.?$", re.I)),
    ("vercel",     re.compile(r"\.vercel-dns\.com\.?$", re.I)),
    ("digitalocean",re.compile(r"\.digitalocean\.com\.?$", re.I)),
    ("hypertide",  re.compile(r"hypertide\.", re.I)),
    ("maildoso",   re.compile(r"maildoso\.", re.I)),
    ("hetzner",    re.compile(r"\.your-server\.de\.?$", re.I)),
    ("ovh",        re.compile(r"\.ovh\.(?:net|com)\.?$", re.I)),
]


def classify_ns(ns_records):
    if not ns_records:
        return "none"
    classifications = set()
    for ns in ns_records:
        matched = "other"
        for name, pat in NS_PROVIDER_PATTERNS:
            if pat.search(ns):
                matched = name
                break
        classifications.add(matched)
    if len(classifications) == 1:
        return next(iter(classifications))
    return "mixed:" + ",".join(sorted(classifications))


def dig_ns(domain, timeout=8):
    try:
        out = subprocess.run(
            ["dig", "NS", domain, "+short", "+time=3", "+tries=2"],
            capture_output=True, text=True, timeout=timeout
        )
        recs = [l.strip().lower().rstrip(".") for l in out.stdout.splitlines() if l.strip()]
        return sorted(set(recs))
    except Exception:
        return []


WHOIS_DATE_KEYS = [
    "creation date", "created", "created on", "registered on",
    "registered date", "domain registration date", "domain_dateregistered",
]
WHOIS_EXPIRY_KEYS = [
    "registry expiry date", "registrar registration expiration date",
    "expiration date", "expires on", "expires", "expiry date",
    "domain expiration date", "domain_dateexpires",
]


def parse_whois_date(text, keys):
    """Find LAST matching date in whois output. Returns ISO date string or None.

    Whois output starts with the IANA TLD record (which has the TLD launch date as
    'created:'), and the actual domain-specific record comes after. We walk top to
    bottom and keep the last match — that's the domain record.
    """
    last_match = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        for key in keys:
            if lower.startswith(key + ":") or lower.startswith(key + " :"):
                val = line.split(":", 1)[1].strip()
                # ISO date is most common — try regex first
                m = re.search(r"(\d{4}-\d{2}-\d{2})", val)
                if m:
                    last_match = m.group(1)
                    continue
                # try DD-Mon-YYYY (.biz, .org sometimes)
                m = re.search(r"(\d{1,2})[-/\s]([A-Za-z]{3})[-/\s](\d{4})", val)
                if m:
                    try:
                        d = datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "%d-%b-%Y")
                        last_match = d.date().isoformat()
                        continue
                    except Exception:
                        pass
                # try DD/MM/YYYY
                m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", val)
                if m:
                    try:
                        d = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%d/%m/%Y")
                        last_match = d.date().isoformat()
                        continue
                    except Exception:
                        pass
    return last_match


def rdap_dates(domain, timeout=10):
    """Query rdap.org (an aggregator that proxies to the right registry RDAP
    server based on TLD). Returns (created_date, expires_date) as ISO YYYY-MM-DD strings.

    RDAP is the modern replacement for WHOIS — returns JSON, consistent schema,
    and works on TLDs where WHOIS access has been GDPR-restricted (e.g. .info).
    """
    try:
        out = subprocess.run(
            ["curl", "-sL", "-H", "Accept: application/rdap+json",
             "--max-time", str(timeout),
             f"https://rdap.org/domain/{domain}"],
            capture_output=True, text=True, timeout=timeout + 2
        )
        if not out.stdout.strip():
            return (None, None)
        import json
        data = json.loads(out.stdout)
        created = None
        expires = None
        for ev in data.get("events", []):
            action = ev.get("eventAction", "").lower()
            date = ev.get("eventDate", "")
            if not date:
                continue
            iso = date[:10]  # YYYY-MM-DD
            if action == "registration" and not created:
                created = iso
            elif action == "expiration" and not expires:
                expires = iso
        return (created, expires)
    except Exception:
        return (None, None)


# Backward-compat alias used inside check_one()
whois_dates = rdap_dates


def days_between(iso_date, today):
    try:
        d = datetime.fromisoformat(iso_date).date()
        return (d - today).days
    except Exception:
        return None


def load_batch_lookup(db_dir):
    """Load batches.json + domain_batches.csv. Returns:
      (assignments_by_domain, batches_by_key)
    where each domain → {batch, ...}, each batch → {expected_ns_provider, expected_ns, ...}.

    Returns ({}, {}) if files missing — drift check is then skipped per-domain.
    """
    assignments, batches = {}, {}
    dom_csv = os.path.join(db_dir, "domain_batches.csv")
    batches_json = os.path.join(db_dir, "batches.json")
    if os.path.exists(dom_csv):
        with open(dom_csv) as f:
            for row in csv.DictReader(f):
                d = (row.get("domain") or "").strip().lower()
                if d:
                    assignments[d] = row
    if os.path.exists(batches_json):
        with open(batches_json) as f:
            batches = json.load(f).get("batches", {})
    return assignments, batches


def compute_ns_match(actual_provider, expected_provider, actual_ns, expected_ns_pair):
    """Returns one of: TRUE, FALSE, UNKNOWN.

    UNKNOWN: no expected_provider declared on the batch (nothing to compare against).
    FALSE: provider mismatch, OR provider matches but a specific expected_ns pair was
           declared and the actual NS set doesn't equal it.
    TRUE: provider matches AND (no pinned pair OR pinned pair matches exactly).

    Special sentinels for expected_provider:
      "DEAD" — domain is expected to have ZERO NS records (retired/never-created zone).
               Returns TRUE only if actual NS is empty; FALSE if anything resolves.
      "none" — same as DEAD (alias).
    """
    if not expected_provider:
        return "UNKNOWN"
    # Retired-zone sentinel: expected to return no NS records.
    if expected_provider.upper() in ("DEAD", "NONE"):
        return "TRUE" if not actual_ns else "FALSE"
    if not actual_provider or actual_provider in ("none", "other"):
        return "FALSE"
    # provider hint may be "cloudflare" / "dnsimple" / etc. Compare case-insensitively.
    if actual_provider.lower() != expected_provider.lower():
        return "FALSE"
    if expected_ns_pair:
        if set(n.lower() for n in actual_ns) != set(n.lower() for n in expected_ns_pair):
            return "FALSE"
    return "TRUE"


def check_one(domain, today, assignments, batches):
    ns = dig_ns(domain)
    created, expires = whois_dates(domain)
    age_days = -days_between(created, today) if created else None
    expiry_days = days_between(expires, today) if expires else None
    actual_provider = classify_ns(ns)

    # Cross-reference against batches.json
    assignment = assignments.get(domain, {})
    batch_key = assignment.get("batch", "")
    batch = batches.get(batch_key, {}) if batch_key else {}
    expected_provider = batch.get("expected_ns_provider", "")
    expected_pair = batch.get("expected_ns") or []  # list of NS, may be None/[]
    ns_match = compute_ns_match(actual_provider, expected_provider, ns, expected_pair)

    return {
        "domain": domain,
        "ns_records": ";".join(ns),
        "ns_count": len(ns),
        "ns_provider_hint": actual_provider,
        "created_date": created or "",
        "expires_date": expires or "",
        "age_days": age_days if age_days is not None else "",
        "expiry_days": expiry_days if expiry_days is not None else "",
        "batch": batch_key,
        "expected_ns_provider": expected_provider,
        "expected_ns_pair": ";".join(expected_pair) if expected_pair else "",
        "ns_match": ns_match,
        "flag_no_ns": "TRUE" if not ns else "FALSE",
        "flag_new_domain": "TRUE" if (age_days is not None and age_days < 30) else "FALSE",
        "flag_expiring_soon": "TRUE" if (expiry_days is not None and expiry_days < 60) else "FALSE",
        "flag_ns_drift": "TRUE" if ns_match == "FALSE" else "FALSE",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--db-dir", default=None,
                    help="Path to the skill's database/ directory (batches.json + domain_batches.csv). "
                         "Defaults to ../database relative to this script.")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    db_dir = args.db_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database")
    assignments, batches = load_batch_lookup(db_dir)
    if assignments:
        print(f"[ns_age] Loaded batch lookup: {len(assignments)} domains, {len(batches)} batches")
    else:
        print(f"[ns_age] No batch lookup found at {db_dir} — drift check will be UNKNOWN for every domain")

    with open(args.from_csv) as f:
        reader = csv.DictReader(f)
        domains = sorted({(r.get("domain") or "").strip().lower() for r in reader if r.get("domain")})

    domains = [d for d in domains if d]
    print(f"[ns_age] Checking {len(domains)} domains (parallel, {args.workers} workers)...")

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_to_dom = {ex.submit(check_one, d, today, assignments, batches): d for d in domains}
        for fut in as_completed(fut_to_dom):
            results.append(fut.result())
            done += 1
            if done % 50 == 0 or done == len(domains):
                print(f"[ns_age]   {done}/{len(domains)} done...")

    results.sort(key=lambda r: r["domain"])

    cols = ["domain","ns_records","ns_count","ns_provider_hint","created_date","expires_date",
            "age_days","expiry_days","batch","expected_ns_provider","expected_ns_pair","ns_match",
            "flag_no_ns","flag_new_domain","flag_expiring_soon","flag_ns_drift"]
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow(r)

    # Summary
    no_ns = sum(1 for r in results if r["flag_no_ns"] == "TRUE")
    new_d = sum(1 for r in results if r["flag_new_domain"] == "TRUE")
    exp_s = sum(1 for r in results if r["flag_expiring_soon"] == "TRUE")
    no_age = sum(1 for r in results if not r["created_date"])
    no_exp = sum(1 for r in results if not r["expires_date"])
    drift = sum(1 for r in results if r["flag_ns_drift"] == "TRUE")
    print(f"[ns_age] wrote {args.out}")
    print(f"[ns_age] no_ns={no_ns}  new_domain(<30d)={new_d}  expiring_soon(<60d)={exp_s}  "
          f"no_rdap_age={no_age}  no_rdap_expiry={no_exp}  ns_drift={drift}")

    # NS provider breakdown
    from collections import Counter
    pc = Counter(r["ns_provider_hint"] for r in results)
    print(f"[ns_age] NS provider distribution:")
    for p, c in pc.most_common():
        print(f"           {p:30} {c}")

    # Per-batch actual-vs-expected scoreboard
    if assignments:
        print(f"\n[ns_age] Per-batch NS drift scoreboard (actual vs expected):")
        by_batch = {}
        for r in results:
            b = r["batch"] or "UNCLASSIFIED"
            by_batch.setdefault(b, []).append(r)
        for batch_key in sorted(by_batch):
            rows = by_batch[batch_key]
            ok = sum(1 for r in rows if r["ns_match"] == "TRUE")
            drift_c = sum(1 for r in rows if r["ns_match"] == "FALSE" and r["flag_no_ns"] == "FALSE")
            dead = sum(1 for r in rows if r["flag_no_ns"] == "TRUE")
            unk = sum(1 for r in rows if r["ns_match"] == "UNKNOWN")
            exp_prov = batches.get(batch_key, {}).get("expected_ns_provider") or "(none)"
            print(f"           {batch_key:50} expected={exp_prov:12} ✓{ok:3} ✗drift={drift_c:3} ☠dead={dead:3} ?unknown={unk:3}")
            # Detail lines for drift + dead
            for r in rows:
                if r["ns_match"] == "FALSE" or r["flag_no_ns"] == "TRUE":
                    actual = r["ns_provider_hint"] if r["flag_no_ns"] == "FALSE" else "DEAD"
                    print(f"             - {r['domain']:40} actual={actual:20} ns={r['ns_records'] or '(empty)'}")


if __name__ == "__main__":
    main()
