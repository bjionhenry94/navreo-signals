#!/usr/bin/env python3
"""
Quick lookup: given a domain (or list of domains), return its infrastructure
batch (registrar + mailbox provider + expected NS provider).

Usage:
    python3 lookup_batch.py <domain>
    python3 lookup_batch.py <domain> --check-ns   # also compare current NS to expected
    python3 lookup_batch.py --batch hypertide-dnsimple  # list all domains in a batch
    cat domains.txt | python3 lookup_batch.py     # bulk via stdin

Reads from:
    ./batches.json
    ./domain_batches.csv
"""
import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BATCHES_JSON = os.path.join(HERE, "batches.json")
DOMAIN_CSV = os.path.join(HERE, "domain_batches.csv")


def load_batches():
    with open(BATCHES_JSON) as f:
        return json.load(f).get("batches", {})


def load_domain_assignments():
    d = {}
    with open(DOMAIN_CSV) as f:
        for row in csv.DictReader(f):
            d[row["domain"].strip().lower()] = row
    return d


def current_ns(domain, timeout=10):
    """Returns list of current public NS records for a domain via dig."""
    r = subprocess.run(
        ["dig", "@8.8.8.8", "NS", domain, "+short", "+time=5", "+tries=2"],
        capture_output=True, text=True, timeout=timeout,
    )
    return [line.strip().rstrip(".") for line in r.stdout.strip().splitlines() if line.strip()]


def classify_ns_provider(ns_list):
    if not ns_list:
        return "DEAD/SERVFAIL"
    if any("cloudflare" in n.lower() for n in ns_list):
        return "Cloudflare"
    if any("dnsimple" in n.lower() for n in ns_list):
        return "DNSimple"
    if any("porkbun" in n.lower() for n in ns_list):
        return "Porkbun"
    return "Other: " + ns_list[0]


def report_domain(domain, assignments, batches, check_ns=False):
    row = assignments.get(domain.strip().lower())
    if not row:
        print(f"[NOT-FOUND] {domain}  (not in database — would default to hypertide-dnsimple)")
        return
    batch = batches.get(row["batch"], {})
    print(f"  {domain}")
    print(f"    batch:              {row['batch']}")
    print(f"    registrar:          {batch.get('registrar', '?')}")
    print(f"    mailbox_provider:   {batch.get('mailbox_provider', '?')}")
    print(f"    expected_ns:        {batch.get('expected_ns_provider', '?')}", end="")
    if batch.get("expected_ns"):
        print(f"  ({', '.join(batch['expected_ns'])})")
    else:
        print("  (per-domain pair)")
    print(f"    inbox_count:        {row.get('inbox_count', '?')}")
    print(f"    source:             {row.get('source', '?')}")
    if row.get("notes"):
        print(f"    notes:              {row['notes']}")
    if check_ns:
        actual = current_ns(domain)
        actual_provider = classify_ns_provider(actual)
        expected_provider = batch.get("expected_ns_provider", "?")
        match = "✓ matches" if actual_provider == expected_provider else f"✗ MISMATCH (expected {expected_provider})"
        print(f"    actual_ns:          {actual_provider}  {match}")
        if actual:
            print(f"      raw: {actual}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", nargs="?")
    ap.add_argument("--check-ns", action="store_true",
                    help="Also dig current NS and flag mismatches vs expected")
    ap.add_argument("--batch", default=None, help="List all domains in this batch")
    args = ap.parse_args()

    batches = load_batches()
    assignments = load_domain_assignments()

    if args.batch:
        ds = [d for d, row in assignments.items() if row["batch"] == args.batch]
        if not ds:
            print(f"No domains in batch '{args.batch}'.")
            print(f"Known batches: {list(batches.keys())}")
            sys.exit(1)
        print(f"Batch '{args.batch}' contains {len(ds)} domains:")
        for d in sorted(ds):
            print(f"  {d}")
        return

    if args.domain:
        report_domain(args.domain, assignments, batches, check_ns=args.check_ns)
    elif not sys.stdin.isatty():
        for line in sys.stdin:
            d = line.strip()
            if d and not d.startswith("#"):
                report_domain(d, assignments, batches, check_ns=args.check_ns)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
