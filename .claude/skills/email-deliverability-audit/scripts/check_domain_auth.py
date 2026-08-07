#!/usr/bin/env python3
"""
Domain Authentication Checker — SPF / DKIM / DMARC

Reads the inboxes CSV produced by audit_inboxes.py, extracts unique sending
domains, and runs `dig TXT` for each:
    - SPF       at <domain>
    - DKIM      at <selector>._domainkey.<domain> (default selector is 'default'
                — pass --dkim-selectors to try multiple, e.g. default,google,k1)
    - DMARC     at _dmarc.<domain>

Outputs CSV: domain, spf_present, spf_strict, spf_record, dkim_present,
             dkim_selector, dkim_record, dmarc_present, dmarc_policy,
             dmarc_record, notes

Usage:
    python3 check_domain_auth.py --from-csv /tmp/audit/inboxes.csv \
        --out /tmp/audit/auth.csv \
        --dkim-selectors default,google,k1,smtpapi
"""
import argparse
import csv
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def dig_txt(name, timeout=10):
    """Returns list of TXT record strings (without the surrounding quotes)."""
    try:
        r = subprocess.run(
            ["dig", "TXT", name, "+short", "+time=5", "+tries=2"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip surrounding quotes; dig +short returns "v=spf1 ..." style
        # Multi-string TXT records come back as "part1" "part2" — join them.
        parts = re.findall(r'"([^"]*)"', line)
        if parts:
            out.append("".join(parts))
        else:
            out.append(line)
    return out


def classify_spf(records):
    spf_recs = [r for r in records if r.lower().startswith("v=spf1")]
    if not spf_recs:
        return False, False, ""
    rec = spf_recs[0]
    # strict = ends with ~all or -all (soft fail / hard fail). +all is wide-open.
    low = rec.lower()
    strict = bool(re.search(r"[~\-]all\b", low)) and "+all" not in low
    return True, strict, rec


def classify_dmarc(records):
    dmarc_recs = [r for r in records if r.lower().startswith("v=dmarc1")]
    if not dmarc_recs:
        return False, "", ""
    rec = dmarc_recs[0]
    m = re.search(r"\bp\s*=\s*(none|quarantine|reject)\b", rec, re.IGNORECASE)
    policy = m.group(1).lower() if m else ""
    return True, policy, rec


def find_dkim(domain, selectors):
    for sel in selectors:
        name = f"{sel}._domainkey.{domain}"
        recs = dig_txt(name)
        dkim = [r for r in recs if "v=dkim1" in r.lower() or "p=" in r.lower()]
        if dkim:
            return True, sel, dkim[0]
    return False, "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-csv", required=True,
                    help="inboxes.csv produced by audit_inboxes.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dkim-selectors", default="default,google,k1,smtpapi,selector1,selector2",
                    help="Comma-separated DKIM selectors to try (in order)")
    ap.add_argument("--workers", type=int, default=20,
                    help="Parallel dig workers (DNS is I/O-bound; safe to push)")
    args = ap.parse_args()

    selectors = [s.strip() for s in args.dkim_selectors.split(",") if s.strip()]

    # Extract unique domains from inboxes CSV
    domains = []
    seen = set()
    with open(args.from_csv) as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = (row.get("domain") or "").strip().lower()
            if not d or d in seen:
                continue
            seen.add(d)
            domains.append(d)

    if not domains:
        print(f"[check_domain_auth] No domains found in {args.from_csv}", file=sys.stderr)
        sys.exit(1)

    print(f"[check_domain_auth] Checking {len(domains)} domains (parallel, {args.workers} workers)...",
          file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    fields = [
        "domain", "spf_present", "spf_strict", "spf_record",
        "dkim_present", "dkim_selector", "dkim_record",
        "dmarc_present", "dmarc_policy", "dmarc_record", "notes",
    ]

    def check_one(domain):
        spf_recs = dig_txt(domain)
        spf_present, spf_strict, spf_record = classify_spf(spf_recs)
        dmarc_recs = dig_txt(f"_dmarc.{domain}")
        dmarc_present, dmarc_policy, dmarc_record = classify_dmarc(dmarc_recs)
        dkim_present, dkim_selector, dkim_record = find_dkim(domain, selectors)

        notes = []
        if not spf_present:
            notes.append("SPF missing")
        elif not spf_strict:
            notes.append("SPF not strict (no ~all/-all)")
        if not dkim_present:
            notes.append(f"DKIM missing (tried selectors: {','.join(selectors)})")
        if not dmarc_present:
            notes.append("DMARC missing")
        elif dmarc_policy == "none":
            notes.append("DMARC p=none (no enforcement)")

        return {
            "domain": domain,
            "spf_present": "TRUE" if spf_present else "FALSE",
            "spf_strict": "TRUE" if spf_strict else "FALSE",
            "spf_record": spf_record,
            "dkim_present": "TRUE" if dkim_present else "FALSE",
            "dkim_selector": dkim_selector,
            "dkim_record": dkim_record[:200],
            "dmarc_present": "TRUE" if dmarc_present else "FALSE",
            "dmarc_policy": dmarc_policy,
            "dmarc_record": dmarc_record,
            "notes": "; ".join(notes),
        }

    rows = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(check_one, d): d for d in domains}
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception as e:
                rows.append({k: "" for k in fields} |
                            {"domain": futures[fut], "notes": f"ERROR: {e}"})
            done += 1
            if done % 50 == 0 or done == len(domains):
                print(f"[check_domain_auth] {done}/{len(domains)}...", file=sys.stderr)

    # Sort by domain for stable output
    rows.sort(key=lambda r: r.get("domain", ""))

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    missing_spf = sum(1 for r in rows if r["spf_present"] == "FALSE")
    missing_dkim = sum(1 for r in rows if r["dkim_present"] == "FALSE")
    missing_dmarc = sum(1 for r in rows if r["dmarc_present"] == "FALSE")
    dmarc_none = sum(1 for r in rows if r["dmarc_policy"] == "none")
    print(f"[check_domain_auth] {len(rows)} domains -> {args.out}", file=sys.stderr)
    print(f"[check_domain_auth] missing: spf={missing_spf} dkim={missing_dkim} "
          f"dmarc={missing_dmarc} | dmarc p=none: {dmarc_none}", file=sys.stderr)


if __name__ == "__main__":
    main()
