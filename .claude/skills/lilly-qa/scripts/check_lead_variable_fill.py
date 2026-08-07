#!/usr/bin/env python3
"""
Lead-Variable Fill Rate Checker

For every custom {{variable}} found in a campaign's copy, scans every lead in
the campaign and verifies that custom_field is populated. Catches the common
failure mode of variables added to copy without backfilling existing leads
(or vice versa).

Default lead fields like {{first_name}} and {{company_name}} are top-level
and skipped here — the analyser already covers their structural use. This
script targets `custom_fields.<name>` lookups.

Usage:
    SMARTLEAD_API_KEY=xxx python check_lead_variable_fill.py \
        --campaign-id 3278743 \
        --variables "Cold Email Video Angle,Why,Icebreaker"

    # Or read variables from analyser stdout:
    python check_lead_variable_fill.py --campaign-id 3278743 \
        --variables "$(grep -oE '\{\{[^}]+\}\}' /tmp/seq.json | sort -u | tr '\n' ',')"

Output: Markdown report to stdout. Exits 0 always (warnings, not errors).
"""

import argparse
import json
import os
import subprocess
import sys
import time

# Default Smartlead lead-level fields — these are top-level on the lead object,
# not in custom_fields. Skip them here.
DEFAULT_LEAD_FIELDS = {
    "first_name", "last_name", "email", "company_name", "phone_number",
    "website", "location", "title", "company_url", "linkedin_profile",
}

# sl_* are Smartlead built-ins (sl_date etc) — also skip
SL_PREFIX = "sl_"


def fetch_batch(api_key, campaign_id, offset, limit=100, timeout=60):
    url = (f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads"
           f"?api_key={api_key}&offset={offset}&limit={limit}")
    r = subprocess.run(["curl", "-sS", url, "--max-time", str(timeout)],
                       capture_output=True, text=True, timeout=timeout + 30)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def fetch_all_leads(api_key, campaign_id, max_offset=20000):
    """Paginate through all leads. Robust against partial-batch quirks: keep
    going until 2 consecutive empty batches."""
    leads = []
    seen = set()
    offset = 0
    consecutive_empty = 0
    while offset < max_offset and consecutive_empty < 2:
        data = fetch_batch(api_key, campaign_id, offset)
        items = []
        if isinstance(data, dict):
            items = data.get("data", []) or []
        elif isinstance(data, list):
            items = data
        if not items:
            consecutive_empty += 1
            offset += 100
            continue
        consecutive_empty = 0
        for item in items:
            lead = item.get("lead", item) if isinstance(item, dict) else item
            em = (lead.get("email") or "").lower().strip()
            if not em or em in seen:
                continue
            seen.add(em)
            leads.append({"item": item, "lead": lead})
        offset += 100
    return leads


def get_custom_field(lead, var_name):
    cf = lead.get("custom_fields") or {}
    if isinstance(cf, str):
        try:
            cf = json.loads(cf)
        except json.JSONDecodeError:
            cf = {}
    if not isinstance(cf, dict):
        return ""
    # Case-insensitive lookup so we surface case-mismatches
    for k, v in cf.items():
        if k == var_name:
            return (str(v) if v is not None else "").strip()
    # case-insensitive fallback for diagnostic purposes
    for k, v in cf.items():
        if k.lower() == var_name.lower():
            return f"__CASEMISMATCH__:{k}:{(str(v) if v is not None else '').strip()}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign-id", type=int, required=True)
    ap.add_argument("--variables", required=True,
                    help="Comma-separated list of custom variables to check")
    ap.add_argument("--api-key", default=os.environ.get("SMARTLEAD_API_KEY"))
    ap.add_argument("--min-len", type=int, default=2,
                    help="Minimum characters to count as 'filled'")
    args = ap.parse_args()

    if not args.api_key:
        print("ERROR: SMARTLEAD_API_KEY not set and --api-key not given", file=sys.stderr)
        sys.exit(1)

    # Parse + filter variables
    raw_vars = [v.strip().strip("{}").strip() for v in args.variables.split(",") if v.strip()]
    custom_vars = [v for v in raw_vars
                   if v.lower() not in DEFAULT_LEAD_FIELDS
                   and not v.startswith(SL_PREFIX)
                   and not v.lower().startswith(SL_PREFIX)]

    print(f"## 🔍 Lead-Variable Fill Check\n")
    print(f"**Campaign:** {args.campaign_id}")
    print(f"**Custom variables in copy:** {', '.join(custom_vars) if custom_vars else '(none — only default fields)'}\n")

    if not custom_vars:
        print("✅ PASS — no custom variables to check.\n")
        return

    print(f"Fetching leads...")
    leads = fetch_all_leads(args.api_key, args.campaign_id)
    print(f"Total leads: **{len(leads)}**\n")

    if not leads:
        print("⚠️ No leads found in campaign — skipping check.\n")
        return

    # Tally per variable
    rows = []
    case_mismatches = {}
    for var in custom_vars:
        filled = 0
        unfilled_samples = []
        case_mismatches[var] = []
        for entry in leads:
            val = get_custom_field(entry["lead"], var)
            if val.startswith("__CASEMISMATCH__:"):
                _, actual_key, actual_val = val.split(":", 2)
                case_mismatches[var].append({"email": entry["lead"].get("email"),
                                              "actual_key": actual_key})
                if len(actual_val) >= args.min_len:
                    filled += 1
                else:
                    if len(unfilled_samples) < 5:
                        unfilled_samples.append(entry["lead"].get("email", ""))
            elif len(val) >= args.min_len:
                filled += 1
            else:
                if len(unfilled_samples) < 5:
                    unfilled_samples.append(entry["lead"].get("email", ""))
        unfilled = len(leads) - filled
        rate = filled / len(leads) if leads else 0
        rows.append({
            "var": var,
            "total": len(leads),
            "filled": filled,
            "unfilled": unfilled,
            "rate": rate,
            "samples": unfilled_samples,
        })

    # Report
    print(f"| Variable | Filled | Unfilled | Fill Rate | Verdict |")
    print(f"|---|---|---|---|---|")
    for r in rows:
        if r["rate"] >= 0.999:
            verdict = "✅ PASS"
        elif r["rate"] >= 0.95:
            verdict = "⚠️ WARN"
        else:
            verdict = "❌ FAIL"
        print(f"| `{{{{{r['var']}}}}}` | {r['filled']:,} | {r['unfilled']:,} | {r['rate']*100:.1f}% | {verdict} |")
    print()

    # Per-variable details for anything < 100%
    for r in rows:
        if r["unfilled"] > 0:
            print(f"### `{{{{{r['var']}}}}}` — {r['unfilled']:,} unfilled lead(s)")
            print(f"Sample unfilled emails (up to 5):")
            for em in r["samples"]:
                print(f"  - {em}")
            print()

    # Case mismatches — these mean the data IS there but under a slightly
    # different key, e.g. "cold email video angle" vs "Cold Email Video Angle"
    any_case = any(case_mismatches[v] for v in custom_vars)
    if any_case:
        print(f"### ⚠️ Case-mismatch warnings")
        print(f"Some leads have the variable's value under a different-cased key. Smartlead's `{{{{var}}}}` lookup is case-sensitive — these will render empty unless fixed.\n")
        for var in custom_vars:
            if case_mismatches[var]:
                print(f"- `{{{{{var}}}}}` expected, but data found under: " +
                      ", ".join(sorted(set(m["actual_key"] for m in case_mismatches[var]))))
        print()


if __name__ == "__main__":
    main()
