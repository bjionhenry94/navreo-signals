#!/usr/bin/env python3
"""
Lead Field Hygiene Checker — first_name + company_name

Scans every lead in a Smartlead campaign and verifies the standard fields
that render directly in email copy (`{{first_name}}` and `{{company_name}}`):

  1. Fill-rate — every lead has a non-empty value (the user's just-asked check).
     Empty / single-char / junk-marker values render as broken sentences in the
     email (e.g. `Hi ,` or `recorded a video for Unknown ...`).

  2. Hygiene — values are clean per the rules in
     references/lead-field-hygiene.md. Legal suffixes ("Acme Inc."), profession
     tails ("Pereira Dabul Advogados"), shouting ("ACME"), auto-hyperlinking
     TLDs ("Immersa.ai"), and similar issues are flagged.

Default behaviour: detection only. Use `--apply` to enter dry-run + push mode
after the report has been reviewed by the user.

Usage:
    SMARTLEAD_API_KEY=xxx python check_lead_field_hygiene.py \
        --campaign-id 3278743

    # With apply (still dry-runs first, requires confirmation):
    SMARTLEAD_API_KEY=xxx python check_lead_field_hygiene.py \
        --campaign-id 3278743 --apply

Output: Markdown report to stdout. Exits 0 always (warnings, not errors).
Manual-review rows are written to /tmp/lilly_qa_manual_review_{campaign}.csv.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional

API_BASE = "https://server.smartlead.ai/api/v1"

# ------------------------------ Cleaner ------------------------------

ROLE_MAILBOXES = {
    "info", "contact", "sales", "hello", "office", "admin", "enquiries",
    "support", "marketing", "team", "help", "noreply",
}

TITLES_RE = re.compile(
    r"^(dr|mr|mrs|ms|miss|prof|rev|sir|herr|frau|ing|dipl\.?-ing|mme?|sr|sra)\.?\s+",
    re.IGNORECASE,
)

JUNK_NAMES = {"test", "unknown", "user", "n/a", "na", "none", "-", ".", ""}
JUNK_COMPANIES = {
    "unknown", "-", "n/a", "na", "none", "tbd", "self",
    "self-employed", "freelance", "",
}

LEGAL_SUFFIXES = [  # longest first to avoid partial matches
    r"gmbh\s*&\s*co\.?\s*kg", r"s\.?a\.?\s+de\s+c\.?v\.?", r"sp\.?\s*z\s*o\.?o\.?",
    r"pvt\.?\s*ltd\.?", r"private\s+limited", r"co\.?\s*ltd\.?",
    r"l\.?l\.?c\.?", r"l\.?l\.?p\.?", r"p\.?l\.?c\.?", r"b\.?v\.?", r"n\.?v\.?",
    r"s\.?r\.?l\.?", r"s\.?l\.?", r"s\.?a\.?", r"s\.?a\.?s\.?u?", r"s\.?p\.?a\.?",
    r"gmbh", r"mbh", r"ag", r"ug", r"kg", r"ohg", r"e\.?g\.?",
    r"ltd\.?", r"limited", r"inc\.?", r"incorporated", r"corp\.?", r"corporation",
    r"pty", r"co\.?", r"company", r"holdings?", r"group",
    r"ltda\.?", r"limitada", r"me", r"eireli",
    r"apS", r"a/s", r"as", r"ab", r"oy", r"oyj",
    r"k\.?k\.?", r"s\.?r\.?o\.?", r"kft\.?", r"ooo",
    r"sarl", r"sas(u)?", r"eurl", r"v\.?o\.?f\.?",
]
LEGAL_RE = re.compile(
    r"[,\s]*\b(" + "|".join(LEGAL_SUFFIXES) + r")\s*\.?\s*$",
    re.IGNORECASE,
)

PROFESSION_TAILS = [
    r"advogados?", r"avvocati", r"avocats?", r"abogados?", r"rechtsanw[aä]lte",
    r"advocates", r"attorneys", r"law\s+(office|firm)", r"kancelaria",
    r"studio\s+legale", r"commercialisti", r"chartered\s+accountants",
]
PROF_RE = re.compile(r"\s+(" + "|".join(PROFESSION_TAILS) + r")\s*$", re.IGNORECASE)

# Generic reach/scale descriptors that trail a brand but are never the brand
# itself ("Advantage Group International" → "Advantage", "Fraser Dove
# International" → "Fraser Dove", "Jex Global" → "Jex"). Kept SEPARATE from
# PROFESSION_TAILS and deliberately conservative: only scope words, NOT
# industry nouns (Talent, Solutions, Associates, Search, Partners) which are
# frequently the brand. Applied as trailing tokens only, interleaved with the
# legal-suffix strip so "... Group International" peels both layers.
DESCRIPTIVE_TAILS = [r"international", r"worldwide", r"global"]
DESC_RE = re.compile(r"\s+(" + "|".join(DESCRIPTIVE_TAILS) + r")\s*$", re.IGNORECASE)

NON_LATIN_TAIL = re.compile(r"\s+[^\x00-\x7FÀ-ɏḀ-ỿ]+\s*$")
PARENTHETICAL = re.compile(r"\s*\([^)]+\)\s*$")
# Acronym-shaped parenthetical (2-6 uppercase letters): when present, the
# acronym IS the brand (e.g. "UK Power Engineers (UKPE)" → "UKPE").
PARENTHETICAL_ACRONYM = re.compile(r"\(([A-Z]{2,6})\)\s*$")
URL_RE = re.compile(r"^https?://|/", re.IGNORECASE)

EMAIL_AUTOLINK_TLDS = (
    "com", "org", "net", "io", "ai", "co", "app", "dev", "tech", "digital",
    "ly", "tv", "fm", "me", "biz", "info", "online", "shop", "store", "cloud",
    "studio", "agency", "club", "live", "life", "world", "global", "group",
    "tools", "space", "site", "page", "xyz", "pro", "plus", "gg", "health",
    "law", "media", "works", "finance", "capital", "consulting", "partners",
    "new", "ninja", "rocks", "wtf", "fyi", "click", "link", "one",
    "us", "eu", "uk", "de", "fr", "it", "es", "nl", "ca", "au", "nz", "jp",
    "br", "mx", "in", "ie", "pl", "be", "ch", "at", "se", "no", "dk", "fi",
    "is", "cz", "ru", "ws", "cc",
)
TLD_RE = re.compile(
    r"\.(" + "|".join(EMAIL_AUTOLINK_TLDS) + r")\b\s*$",
    re.IGNORECASE,
)


def clean_first_name(first_name: Optional[str], email: Optional[str] = None) -> str:
    s = (first_name or "").strip()
    s = TITLES_RE.sub("", s)
    # Always take the first whitespace-separated token. Compound first names
    # written with a space ("Mary Jane") collapse to the first token; hyphenated
    # names ("Jean-Pierre") are already a single token and stay intact.
    parts = re.split(r"\s+", s)
    if len(parts) > 1:
        s = parts[0]
    s = "-".join(p.capitalize() for p in s.split("-"))
    if s.lower() in JUNK_NAMES or len(s) < 2 or s.isdigit():
        if email:
            prefix = email.split("@")[0].split(".")[0]
            if prefix.lower() not in ROLE_MAILBOXES and len(prefix) >= 2:
                return prefix.capitalize()
        return "there"
    return s


def clean_company_name(company: Optional[str], fallback: bool = True) -> Optional[str]:
    s = (company or "").strip()
    if not s or s.lower() in JUNK_COMPANIES:
        return company if fallback else None
    if URL_RE.search(s):
        # Full URL — flag, don't auto-clean
        return company if fallback else None
    # If a trailing parenthetical IS an acronym (2-6 uppercase letters), use it
    # as the brand: "UK Power Engineers (UKPE)" → "UKPE".
    m = PARENTHETICAL_ACRONYM.search(s)
    if m:
        return m.group(1)
    s = NON_LATIN_TAIL.sub("", s).strip()
    s = PARENTHETICAL.sub("", s).strip()
    # Interleave legal + descriptive strips so multi-layer tails peel fully
    # ("Advantage Group International" → International → Group → "Advantage").
    for _ in range(4):
        before = s
        s = LEGAL_RE.sub("", s).strip(" .,")
        s = DESC_RE.sub("", s).strip(" .,")
        if s == before:
            break
    s = PROF_RE.sub("", s).strip()
    new = TLD_RE.sub("", s).strip()
    if len(new) >= 2:
        s = new
    # All-caps shouting → Title Case, but only when longer than 4 chars
    # (anything ≤4 chars is likely a real acronym: IBM, SAP, KPMG, etc.).
    if s.isupper() and len(s) > 4:
        s = " ".join(w.capitalize() for w in s.split())
    if len(s) < 2:
        return company if fallback else None
    return s


# ------------------------------ Detectors ------------------------------

def is_missing_first_name(value: Optional[str]) -> bool:
    s = (value or "").strip()
    return not s or s.lower() in JUNK_NAMES or len(s) < 2 or s.isdigit()


def is_missing_company_name(value: Optional[str]) -> bool:
    s = (value or "").strip()
    return not s or s.lower() in JUNK_COMPANIES


def diagnose_first_name(raw: str) -> Optional[str]:
    """Return a one-word reason if dirty, None if clean.

    Multi-word first names ("Mary Jane", "Burcu Culpan") are NOT flagged —
    they're silently collapsed to the first token by `clean_first_name`. Same
    for lowercase brand-style names — uncommon for first names but harmless.
    """
    s = (raw or "").strip()
    if TITLES_RE.match(s):
        return "title-prefix"
    if s.isupper() and len(s) >= 3:
        return "all-caps"
    return None


def diagnose_company_name(raw: str) -> Optional[str]:
    """Return a one-word reason if dirty, None if clean.

    Lowercase-start company names are NOT flagged — `iCrossing`, `iFrog`,
    `inBLUME`, `eBay` etc. use intentional brand casing. Flagging them would
    rewrite real brand styling into something the prospect doesn't recognise.
    """
    s = (raw or "").strip()
    if URL_RE.search(s):
        return "url"
    if s.isdigit():
        return "all-numeric"
    if "—" in s:
        return "em-dash"
    if LEGAL_RE.search(s):
        return "legal-suffix"
    if DESC_RE.search(s):
        return "descriptive-tail"
    if TLD_RE.search(s):
        # A trailing TLD makes the brand auto-link in the rendered email and
        # turns a sentence like "recorded a video for Navreo.ai" into a
        # clickable mid-sentence link. FAIL — strip the TLD before sending.
        return "website-as-name"
    if PROF_RE.search(s):
        return "profession-tail"
    if PARENTHETICAL.search(s):
        return "parenthetical"
    if NON_LATIN_TAIL.search(s):
        return "non-latin-tail"
    if s.isupper() and len(s) > 4:
        return "all-caps"
    return None


# Severity by pattern. FAIL findings block launch when ≥1% of leads affected.
SEVERITY_FIRST = {
    "title-prefix": "FAIL",
    "all-caps": "WARN",
}
SEVERITY_COMPANY = {
    "url": "FAIL",
    "all-numeric": "FAIL",
    "em-dash": "FAIL",
    "legal-suffix": "FAIL",
    "website-as-name": "FAIL",
    "descriptive-tail": "WARN",
    "profession-tail": "WARN",
    "parenthetical": "WARN",
    "non-latin-tail": "WARN",
    "all-caps": "WARN",
}


# ------------------------------ Smartlead I/O ------------------------------

def fetch_leads(campaign_id: str, api_key: str) -> list:
    leads = []
    offset = 0
    limit = 100
    while True:
        url = f"{API_BASE}/campaigns/{campaign_id}/leads?api_key={api_key}&offset={offset}&limit={limit}"
        try:
            out = subprocess.check_output(
                ["curl", "-s", "--max-time", "60", "--retry", "2", url],
                timeout=120,
            )
            page = json.loads(out)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            sys.stderr.write(f"Fetch failed at offset {offset}: {e}\n")
            break
        rows = page.get("data") or page.get("leads") or page if isinstance(page, list) else []
        if isinstance(page, dict):
            rows = page.get("data") or page.get("leads") or []
        if not rows:
            break
        leads.extend(rows)
        if len(rows) < limit:
            break
        offset += limit
        time.sleep(0.1)
    return leads


def push_lead_updates(campaign_id: str, api_key: str, updates: list, batch_size: int = 200) -> dict:
    """Push cleaned lead values back to Smartlead. Each update is
    {"email": ..., "first_name": ..., "company_name": ...}."""
    summary = {"pushed": 0, "updated": 0, "blocked": 0, "invalid": 0, "batches": 0}
    for i in range(0, len(updates), batch_size):
        chunk = updates[i:i + batch_size]
        payload = {"lead_list": chunk}
        url = f"{API_BASE}/campaigns/{campaign_id}/leads?api_key={api_key}"
        try:
            out = subprocess.check_output(
                [
                    "curl", "-s", "-X", "POST", url,
                    "-H", "Content-Type: application/json",
                    "-d", json.dumps(payload),
                    "--max-time", "60", "--retry", "2",
                ],
                timeout=180,
            )
            resp = json.loads(out)
            summary["pushed"] += len(chunk)
            summary["updated"] += resp.get("already_added_to_campaign", 0) or 0
            summary["blocked"] += resp.get("block_count", 0) or 0
            summary["invalid"] += resp.get("invalid_email_count", 0) or 0
            summary["batches"] += 1
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            sys.stderr.write(f"Push failed for batch {i // batch_size}: {e}\n")
        time.sleep(0.5)
    return summary


# ------------------------------ Main ------------------------------

def lead_value(lead: dict, field: str) -> Optional[str]:
    """Extract field value from a lead record. Smartlead's lead shape varies
    slightly between endpoints — try the common locations."""
    if field in lead:
        return lead.get(field)
    if "lead" in lead and isinstance(lead["lead"], dict):
        return lead["lead"].get(field)
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign-id", required=True)
    p.add_argument("--api-key", default=os.environ.get("SMARTLEAD_API_KEY"))
    p.add_argument(
        "--apply",
        action="store_true",
        help="After detection, prompt for confirmation then push cleaned values via API.",
    )
    p.add_argument(
        "--manual-review-out",
        default=None,
        help="Path for the manual-review CSV (default: /tmp/lilly_qa_manual_review_{campaign}.csv).",
    )
    args = p.parse_args()

    if not args.api_key:
        sys.stderr.write("Set SMARTLEAD_API_KEY or pass --api-key.\n")
        return 1

    leads = fetch_leads(args.campaign_id, args.api_key)
    if not leads:
        print(f"No leads found for campaign {args.campaign_id}.")
        return 0

    total = len(leads)
    missing_first = []
    dirty_first = []  # tuples of (email, raw, cleaned, reason, severity)
    missing_company = []
    dirty_company = []
    manual_review = []  # rows we won't auto-clean — flag for human

    updates = {}  # email -> partial update dict

    for lead in leads:
        email = lead_value(lead, "email") or ""
        raw_first = lead_value(lead, "first_name") or ""
        raw_company = lead_value(lead, "company_name") or ""

        # First name
        if is_missing_first_name(raw_first):
            cleaned = clean_first_name(raw_first, email=email)
            missing_first.append((email, raw_first, cleaned))
            if cleaned and cleaned.lower() != "there" and cleaned != raw_first:
                updates.setdefault(email, {})["first_name"] = cleaned
            else:
                manual_review.append({
                    "email": email,
                    "field": "first_name",
                    "raw": raw_first,
                    "reason": "missing-or-junk",
                })
        else:
            reason = diagnose_first_name(raw_first)
            if reason:
                cleaned = clean_first_name(raw_first, email=email)
                severity = SEVERITY_FIRST.get(reason, "WARN")
                dirty_first.append((email, raw_first, cleaned, reason, severity))
                if cleaned and cleaned != raw_first and len(cleaned) >= 2:
                    updates.setdefault(email, {})["first_name"] = cleaned

        # Company name
        if is_missing_company_name(raw_company):
            missing_company.append((email, raw_company))
            manual_review.append({
                "email": email,
                "field": "company_name",
                "raw": raw_company,
                "reason": "missing-or-junk",
            })
        else:
            reason = diagnose_company_name(raw_company)
            if reason == "url":
                manual_review.append({
                    "email": email,
                    "field": "company_name",
                    "raw": raw_company,
                    "reason": "url-in-field",
                })
            elif reason:
                cleaned = clean_company_name(raw_company)
                severity = SEVERITY_COMPANY.get(reason, "WARN")
                dirty_company.append((email, raw_company, cleaned, reason, severity))
                if cleaned and cleaned != raw_company and len(cleaned) >= 2:
                    updates.setdefault(email, {})["company_name"] = cleaned

    # ---------- Report ----------

    def pct(n: int) -> str:
        return f"{(n / total * 100):.1f}%" if total else "0.0%"

    fail_first = sum(1 for r in dirty_first if r[4] == "FAIL") + len(missing_first)
    warn_first = sum(1 for r in dirty_first if r[4] == "WARN")
    fail_company = sum(1 for r in dirty_company if r[4] == "FAIL") + len(missing_company)
    warn_company = sum(1 for r in dirty_company if r[4] == "WARN")

    print(f"# Lead Field Hygiene — Campaign {args.campaign_id}")
    print(f"\nTotal leads scanned: **{total}**\n")
    print("## first_name\n")
    print(f"- ❌ FAIL (missing or dirty-FAIL): {fail_first} ({pct(fail_first)})")
    print(f"- ⚠️ WARN (dirty-WARN): {warn_first} ({pct(warn_first)})")
    print(f"- ✅ Clean: {total - fail_first - warn_first} ({pct(total - fail_first - warn_first)})")
    print("\n## company_name\n")
    print(f"- ❌ FAIL (missing or dirty-FAIL): {fail_company} ({pct(fail_company)})")
    print(f"- ⚠️ WARN (dirty-WARN): {warn_company} ({pct(warn_company)})")
    print(f"- ✅ Clean: {total - fail_company - warn_company} ({pct(total - fail_company - warn_company)})")

    # Sample dirty findings grouped by reason
    def sample_group(rows: list, label: str) -> None:
        if not rows:
            return
        from collections import Counter
        groups = Counter(r[3] for r in rows)
        print(f"\n### {label} — patterns")
        for reason, count in groups.most_common():
            sev = SEVERITY_FIRST.get(reason) or SEVERITY_COMPANY.get(reason) or "WARN"
            print(f"\n**{reason}** ({sev}, {count} leads):")
            samples = [r for r in rows if r[3] == reason][:5]
            for email, raw, cleaned, _, _ in samples:
                print(f"- `{email}`: `{raw}` → `{cleaned}`")

    sample_group(dirty_first, "first_name dirty findings")
    sample_group(dirty_company, "company_name dirty findings")

    if missing_first:
        print(f"\n### Missing first_name — sample (first 5 of {len(missing_first)})")
        for email, raw, cleaned in missing_first[:5]:
            print(f"- `{email}`: raw=`{raw}` → fallback=`{cleaned}`")
    if missing_company:
        print(f"\n### Missing company_name — sample (first 5 of {len(missing_company)})")
        for email, raw in missing_company[:5]:
            print(f"- `{email}`: raw=`{raw}`")

    # Manual review CSV
    mr_path = args.manual_review_out or f"/tmp/lilly_qa_manual_review_{args.campaign_id}.csv"
    if manual_review:
        with open(mr_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["email", "field", "raw", "reason"])
            w.writeheader()
            for row in manual_review:
                w.writerow(row)
        print(f"\n📋 Manual review needed for {len(manual_review)} leads — see `{mr_path}`")

    # Verdict
    print("\n## Verdict")
    block = (fail_first / total > 0.01) if total else False
    block = block or ((fail_company / total > 0.01) if total else False)
    if block:
        print("❌ **BLOCK LAUNCH** — FAIL findings affect ≥1% of leads. Fix before sending.")
    elif fail_first or fail_company or warn_first or warn_company:
        print("⚠️ **Review before launch** — issues found, but below the launch-block threshold.")
    else:
        print("✅ **Clean** — no hygiene issues found.")

    # ---------- Apply ----------
    if args.apply:
        print(f"\n---\n\n## Apply mode\n")
        print(f"Proposed updates: **{len(updates)}** leads.")
        if not updates:
            print("Nothing to push.")
            return 0
        # Show 10 sample diffs
        print("\nSample (first 10):")
        for email, diff in list(updates.items())[:10]:
            parts = ", ".join(f"{k}=`{v}`" for k, v in diff.items())
            print(f"- `{email}`: {parts}")
        print(
            "\n**Confirm push?** This script does not auto-confirm — re-run with the\n"
            "user's explicit OK in the conversation, OR set `LILLY_QA_CONFIRMED=1` in\n"
            "the environment to bypass this gate.\n"
        )
        if os.environ.get("LILLY_QA_CONFIRMED") != "1":
            print("Aborted: confirmation gate active. Re-run with `LILLY_QA_CONFIRMED=1` once user confirms.")
            return 0
        update_list = [{"email": e, **diff} for e, diff in updates.items()]
        result = push_lead_updates(args.campaign_id, args.api_key, update_list)
        print(f"\nPush complete: {result}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
