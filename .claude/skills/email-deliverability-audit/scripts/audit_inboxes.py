#!/usr/bin/env python3
"""
Smartlead Inbox Inventory + Health Audit

Pulls all email accounts from Smartlead and writes a CSV with per-inbox health
fields and flags. Used as the input for check_domain_auth.py and as one of the
inputs for generate_report.py.

Usage:
    SMARTLEAD_API_KEY=xxx python3 audit_inboxes.py --out /tmp/audit/inboxes.csv

    # Filter by sub-client:
    python3 audit_inboxes.py --client-id 1417c9a6-... --out /tmp/audit/inboxes.csv

    # Filter to a specific campaign's inboxes:
    python3 audit_inboxes.py --campaign-id 3343012 --out /tmp/audit/inboxes.csv

    # Filter to a specific sender domain:
    python3 audit_inboxes.py --domain navreocampaign.info --out /tmp/audit/inboxes.csv

Output columns:
    id, email, domain, from_name, smtp_host, warmup_status, warmup_reputation_pct,
    blocked_reason, max_per_day, daily_sent_today, smtp_ok, imap_ok,
    campaign_count, client_id, signature, sig_name_match, flag_blocked,
    flag_smtp_fail, flag_imap_fail, flag_low_reputation, flag_sig_missing,
    flag_sig_name_mismatch, flag_sig_live_link
"""
import argparse
import csv
import html as _html
import json
import os
import re
import subprocess
import sys
import time

API_BASE = "https://server.smartlead.ai/api/v1"
PAGE_SIZE = 100

# Pagination robustness. The Smartlead API intermittently rate-limits or returns a
# transient empty/None page that is indistinguishable from genuine end-of-data, so a
# single blip once under-counted an 8,438-inbox fleet to 1,400 (2026-05-21). Retry each
# page before believing an empty, and require several consecutive post-retry empties to
# stop.
FETCH_RETRIES = 5          # attempts per page before counting it empty
FETCH_BACKOFF = 1.2        # seconds; sleep = FETCH_BACKOFF * attempt between retries
STOP_AFTER_EMPTY = 4       # consecutive post-retry empty pages = true end-of-data


def fetch_page(api_key, offset, limit, client_id=None, timeout=60):
    qs = f"api_key={api_key}&offset={offset}&limit={limit}"
    if client_id:
        qs += f"&client_id={client_id}"
    url = f"{API_BASE}/email-accounts/?{qs}"
    try:
        r = subprocess.run(["curl", "-sS", url, "--max-time", str(timeout)],
                           capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _page_items(page):
    """Normalize a page response. Returns None on transport failure (so the caller can
    tell a rate-limit blip apart from a genuinely empty page), else the list of records
    (possibly empty)."""
    if page is None:
        return None
    if isinstance(page, list):
        return page
    if isinstance(page, dict):
        return page.get("data", []) or []
    return []


def fetch_all(api_key, client_id=None, max_offset=200000):
    inboxes = []
    seen = set()
    offset = 0
    consecutive_empty = 0
    while offset < max_offset and consecutive_empty < STOP_AFTER_EMPTY:
        items = []
        had_transport_failure = False
        for attempt in range(1, FETCH_RETRIES + 1):
            parsed = _page_items(fetch_page(api_key, offset, PAGE_SIZE, client_id=client_id))
            if parsed is None:
                had_transport_failure = True
            elif parsed:
                items = parsed
                break
            if attempt < FETCH_RETRIES:
                time.sleep(FETCH_BACKOFF * attempt)
        if not items:
            consecutive_empty += 1
            if had_transport_failure:
                print(f"[audit_inboxes] WARNING: no data at offset {offset} after "
                      f"{FETCH_RETRIES} retries with transport failures: possible "
                      f"rate-limit/truncation (consecutive_empty="
                      f"{consecutive_empty}/{STOP_AFTER_EMPTY})", file=sys.stderr)
            offset += PAGE_SIZE
            continue
        consecutive_empty = 0
        for it in items:
            iid = it.get("id")
            if iid in seen:
                continue
            seen.add(iid)
            inboxes.append(it)
        offset += PAGE_SIZE
    return inboxes


def fetch_campaign_inboxes(api_key, campaign_id, timeout=60):
    url = f"{API_BASE}/campaigns/{campaign_id}/email-accounts?api_key={api_key}"
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            r = subprocess.run(["curl", "-sS", url, "--max-time", str(timeout)],
                               capture_output=True, text=True, timeout=timeout + 30)
        except subprocess.TimeoutExpired:
            r = None
        if r is not None and r.returncode == 0:
            try:
                d = json.loads(r.stdout)
                return d if isinstance(d, list) else d.get("data", []) or []
            except json.JSONDecodeError:
                pass
        if attempt < FETCH_RETRIES:
            time.sleep(FETCH_BACKOFF * attempt)
    return []


def parse_reputation_pct(rep):
    """Smartlead returns warmup_reputation as a string like '89%'. Strip and parse."""
    if rep is None:
        return None
    s = str(rep).strip().rstrip("%").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


# --- Signature audit -------------------------------------------------------
# Two things are checked on every inbox's signature:
#   1. Does the sender's display name (from_name) actually appear in the
#      signature? A signature signing off as a *different* person than the
#      From-name is the classic copy-paste-across-mailboxes bug (recipient sees
#      "From: Jane Smithson" but the sign-off says "Kevin Dormer").
#   2. Does the signature follow our standard format for the website line —
#      "Visit our website at <domain>(.)<tld>" with the dot in brackets so the
#      mail client does NOT auto-render it as a clickable link. A bare/clickable
#      link (http(s)://, www., <a href>, or a real dot before a web TLD) is a
#      deliverability risk in cold email and breaks the house style.

_WEB_TLDS = ("com|net|io|info|biz|org|co|xyz|online|site|dev|ai|me|us|uk|"
             "digital|click|one|pro|app|tech|email")


def signature_to_text(sig):
    """Strip a signature's HTML to plain text (one line per block)."""
    if not sig:
        return ""
    s = _html.unescape(sig)
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.I)
    s = re.sub(r"</\s*(div|p|tr|li|h[1-6])\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())


def signature_name_match(from_name, sig_text):
    """Return MATCH / PARTIAL / MISMATCH / NO_SIG / NO_FROM_NAME."""
    if not sig_text:
        return "NO_SIG"
    toks = [t for t in _norm(from_name).split() if len(t) > 1]
    if not toks:
        return "NO_FROM_NAME"
    hay = " " + _norm(sig_text) + " "
    present = [t for t in toks if (" " + t + " ") in hay]
    if len(present) == len(toks):
        return "MATCH"
    return "PARTIAL" if present else "MISMATCH"


def signature_has_live_link(sig_html):
    """True if the signature contains a clickable/bare website link instead of
    the defused '<domain>(.)<tld>' house format."""
    if not sig_html:
        return False
    low = _html.unescape(sig_html).lower()
    if "<a " in low or "href=" in low or "http://" in low or "https://" in low or "www." in low:
        return True
    # bare domain: a real dot directly between a word char and a web TLD.
    # Strip email addresses first so a mailto-style address isn't mistaken for a
    # website link, and the defused 'amplifyy(.)com' form never matches (the dot
    # there is wrapped in parens, not adjacent to the TLD).
    text = re.sub(r"[a-z0-9._%+-]+@[a-z0-9.-]+", " ", low)
    return bool(re.search(r"[a-z0-9-]\.(?:%s)\b" % _WEB_TLDS, text))


def normalize_row(inbox):
    email = (inbox.get("from_email") or inbox.get("username") or "").strip()
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    wd = inbox.get("warmup_details") or {}
    rep = parse_reputation_pct(wd.get("warmup_reputation"))
    status = (wd.get("status") or "").upper()
    blocked = wd.get("blocked_reason")
    smtp_ok = bool(inbox.get("is_smtp_success"))
    imap_ok = bool(inbox.get("is_imap_success"))

    from_name = inbox.get("from_name") or ""
    sig_raw = inbox.get("signature")
    sig_text = signature_to_text(sig_raw)
    sig_match = signature_name_match(from_name, sig_text)
    live_link = signature_has_live_link(sig_raw)

    return {
        "id": inbox.get("id"),
        "email": email,
        "domain": domain,
        "from_name": from_name,
        "smtp_host": inbox.get("smtp_host") or "",
        "warmup_status": status,
        "warmup_reputation_pct": rep if rep is not None else "",
        "blocked_reason": blocked or "",
        "max_per_day": inbox.get("message_per_day") or "",
        "daily_sent_today": inbox.get("daily_sent_count") if inbox.get("daily_sent_count") is not None else "",
        "smtp_ok": "TRUE" if smtp_ok else "FALSE",
        "imap_ok": "TRUE" if imap_ok else "FALSE",
        "campaign_count": inbox.get("campaign_count") if inbox.get("campaign_count") is not None else "",
        "client_id": inbox.get("client_id") or "",
        "signature": sig_text.replace("\n", " | "),
        "sig_name_match": sig_match,
        "flag_blocked": "TRUE" if (status == "BLOCKED" or bool(blocked)) else "FALSE",
        "flag_smtp_fail": "TRUE" if not smtp_ok else "FALSE",
        "flag_imap_fail": "TRUE" if not imap_ok else "FALSE",
        "flag_low_reputation": "TRUE" if (rep is not None and rep < 80) else "FALSE",
        "flag_sig_missing": "TRUE" if sig_match == "NO_SIG" else "FALSE",
        "flag_sig_name_mismatch": "TRUE" if sig_match == "MISMATCH" else "FALSE",
        "flag_sig_live_link": "TRUE" if live_link else "FALSE",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key", default=os.environ.get("SMARTLEAD_API_KEY"))
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--campaign-id", default=None)
    ap.add_argument("--domain", default=None,
                    help="Filter to inboxes on this sender domain (e.g. example.com)")
    args = ap.parse_args()

    if not args.api_key:
        print("ERROR: SMARTLEAD_API_KEY not set and --api-key not given", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    print(f"[audit_inboxes] Fetching inboxes...", file=sys.stderr)
    if args.campaign_id:
        inboxes = fetch_campaign_inboxes(args.api_key, args.campaign_id)
    else:
        inboxes = fetch_all(args.api_key, client_id=args.client_id)

    rows = [normalize_row(ib) for ib in inboxes]
    if args.domain:
        rows = [r for r in rows if r["domain"] == args.domain.lower()]

    fields = list(rows[0].keys()) if rows else [
        "id", "email", "domain", "from_name", "smtp_host", "warmup_status",
        "warmup_reputation_pct", "blocked_reason", "max_per_day",
        "daily_sent_today", "smtp_ok", "imap_ok", "campaign_count", "client_id",
        "signature", "sig_name_match",
        "flag_blocked", "flag_smtp_fail", "flag_imap_fail", "flag_low_reputation",
        "flag_sig_missing", "flag_sig_name_mismatch", "flag_sig_live_link",
    ]

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Stderr summary so a calling shell can `tee` the CSV to stdout if needed
    flagged_blocked = sum(1 for r in rows if r["flag_blocked"] == "TRUE")
    flagged_smtp = sum(1 for r in rows if r["flag_smtp_fail"] == "TRUE")
    flagged_imap = sum(1 for r in rows if r["flag_imap_fail"] == "TRUE")
    flagged_rep = sum(1 for r in rows if r["flag_low_reputation"] == "TRUE")
    flagged_sig_miss = sum(1 for r in rows if r["flag_sig_missing"] == "TRUE")
    flagged_sig_mm = sum(1 for r in rows if r["flag_sig_name_mismatch"] == "TRUE")
    flagged_sig_link = sum(1 for r in rows if r["flag_sig_live_link"] == "TRUE")
    n_domains = len({r["domain"] for r in rows if r["domain"]})
    print(f"[audit_inboxes] {len(rows)} inboxes across {n_domains} domains -> {args.out}",
          file=sys.stderr)
    print(f"[audit_inboxes] flags: blocked={flagged_blocked} smtp_fail={flagged_smtp} "
          f"imap_fail={flagged_imap} low_rep={flagged_rep}", file=sys.stderr)
    print(f"[audit_inboxes] signature: missing={flagged_sig_miss} "
          f"name_mismatch={flagged_sig_mm} live_link={flagged_sig_link}", file=sys.stderr)


if __name__ == "__main__":
    main()
