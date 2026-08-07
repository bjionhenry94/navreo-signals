#!/usr/bin/env python3
"""
Smartlead Campaign + Domain Performance Audit

For each ACTIVE / PAUSED campaign, pulls aggregate sent / replies / bounces
over a lookback window and applies the 1% rule (campaign-level flag). Then
rolls campaign sends down to the sender DOMAIN level by attributing them
across the campaign's bound inboxes (proportional to inbox count per domain).

Note: Smartlead's public /statistics endpoint returns message-level rows but
does NOT include email_account_id, so we can't compute true per-inbox stats.
Domain-level attribution is the closest workable approximation.

Usage:
    SMARTLEAD_API_KEY=xxx python3 audit_performance.py \
        --days 30 \
        --out-campaigns /tmp/audit/campaigns.csv \
        --out-domains /tmp/audit/domains.csv

    # Scope filters:
    python3 audit_performance.py --days 30 \
        --campaign-id 3343012 \
        --out-campaigns /tmp/audit/campaigns.csv \
        --out-domains /tmp/audit/domains.csv

    python3 audit_performance.py --days 14 --client-id 1417c9a6-... \
        --out-campaigns /tmp/audit/c.csv --out-domains /tmp/audit/d.csv

Statuses included by default: ACTIVE, PAUSED, COMPLETED.
Use --statuses ACTIVE,PAUSED to restrict.
"""
import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections import defaultdict

API_BASE = "https://server.smartlead.ai/api/v1"
DEFAULT_STATUSES = ["ACTIVE", "STOPPED"]  # PAUSED + COMPLETED excluded by default per user rule 2026-05-19. Override with --statuses if needed.

# Pagination robustness. The Smartlead API intermittently rate-limits or returns a
# transient None/empty response that looks identical to genuine end-of-data, so a blip
# once reported "0 campaigns" on a run that really had 63. Retry each fetch before
# believing an empty, and require several consecutive post-retry empties to stop.
FETCH_RETRIES = 5          # attempts per request before counting it empty
FETCH_BACKOFF = 1.2        # seconds; sleep = FETCH_BACKOFF * attempt between retries
STOP_AFTER_EMPTY = 4       # consecutive post-retry empty pages = true end-of-data
LOW_REPLY_MIN_SENT = 200
LOW_REPLY_THRESHOLD_PCT = 1.0
HIGH_BOUNCE_MIN_SENT = 50
HIGH_BOUNCE_THRESHOLD_PCT = 3.0


def curl_json(url, timeout=60):
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


def curl_json_retry(url, timeout=60):
    """curl_json with retry on transient transport failure (None response from a
    timeout, non-zero exit, or undecodable body). A successfully parsed-but-empty
    response is returned as-is: that is a legitimate value, not a blip."""
    for attempt in range(1, FETCH_RETRIES + 1):
        data = curl_json(url, timeout=timeout)
        if data is not None:
            return data
        if attempt < FETCH_RETRIES:
            time.sleep(FETCH_BACKOFF * attempt)
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


def fetch_campaigns_page(api_key, offset, limit, client_id=None):
    qs = f"api_key={api_key}&offset={offset}&limit={limit}"
    if client_id:
        qs += f"&client_id={client_id}"
    return curl_json(f"{API_BASE}/campaigns?{qs}")


def fetch_all_campaigns(api_key, client_id=None):
    campaigns = []
    seen = set()
    offset = 0
    consecutive_empty = 0
    while consecutive_empty < STOP_AFTER_EMPTY and offset < 50000:
        items = []
        had_transport_failure = False
        for attempt in range(1, FETCH_RETRIES + 1):
            parsed = _page_items(fetch_campaigns_page(api_key, offset, 100, client_id=client_id))
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
                print(f"[audit_performance] WARNING: no campaigns at offset {offset} after "
                      f"{FETCH_RETRIES} retries with transport failures: possible "
                      f"rate-limit/truncation (consecutive_empty="
                      f"{consecutive_empty}/{STOP_AFTER_EMPTY})", file=sys.stderr)
            offset += 100
            continue
        consecutive_empty = 0
        for c in items:
            cid = c.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            campaigns.append(c)
        offset += 100
    return campaigns


def fetch_analytics(api_key, campaign_id, start_date, end_date):
    url = (f"{API_BASE}/campaigns/{campaign_id}/analytics-by-date"
           f"?api_key={api_key}&start_date={start_date}&end_date={end_date}")
    return curl_json_retry(url)


def fetch_campaign_inboxes(api_key, campaign_id):
    url = f"{API_BASE}/campaigns/{campaign_id}/email-accounts?api_key={api_key}"
    d = curl_json_retry(url)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("data", []) or []
    return []


def to_int(x, default=0):
    if x is None or x == "":
        return default
    try:
        return int(float(x))
    except (ValueError, TypeError):
        return default


def pct(num, denom):
    if not denom:
        return 0.0
    return round(100.0 * num / denom, 3)


def domain_of(email):
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out-campaigns", required=True)
    ap.add_argument("--out-domains", required=True)
    ap.add_argument("--api-key", default=os.environ.get("SMARTLEAD_API_KEY"))
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--campaign-id", default=None,
                    help="If set, audits only this campaign")
    ap.add_argument("--statuses", default=",".join(DEFAULT_STATUSES),
                    help="Comma-separated campaign statuses to include")
    args = ap.parse_args()

    if not args.api_key:
        print("ERROR: SMARTLEAD_API_KEY not set and --api-key not given", file=sys.stderr)
        sys.exit(1)

    statuses_filter = {s.strip().upper() for s in args.statuses.split(",") if s.strip()}
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=args.days)

    os.makedirs(os.path.dirname(os.path.abspath(args.out_campaigns)) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_domains)) or ".", exist_ok=True)

    print(f"[audit_performance] Window: {start_date} → {end_date} ({args.days}d)",
          file=sys.stderr)

    if args.campaign_id:
        # Fetch the single campaign metadata (so we have its name/status)
        single = curl_json_retry(f"{API_BASE}/campaigns/{args.campaign_id}?api_key={args.api_key}")
        if isinstance(single, list):
            campaigns = single
        elif isinstance(single, dict) and "id" in single:
            campaigns = [single]
        else:
            campaigns = [{"id": int(args.campaign_id), "name": "", "status": "UNKNOWN"}]
    else:
        print(f"[audit_performance] Fetching campaigns list...", file=sys.stderr)
        campaigns = fetch_all_campaigns(args.api_key, client_id=args.client_id)
        campaigns = [c for c in campaigns
                     if (c.get("status") or "").upper() in statuses_filter]

    print(f"[audit_performance] Auditing {len(campaigns)} campaigns...", file=sys.stderr)

    campaign_rows = []
    # domain -> {sent, replies, bounces, n_inboxes (max seen), n_campaigns (count)}
    domain_agg = defaultdict(lambda: {"sent": 0, "replies": 0, "bounces": 0,
                                       "inboxes": set(), "campaigns": set()})

    for i, c in enumerate(campaigns, 1):
        cid = c.get("id")
        if cid is None:
            continue
        analytics = fetch_analytics(args.api_key, cid, start_date.isoformat(), end_date.isoformat())
        if not isinstance(analytics, dict):
            print(f"[audit_performance]   skip campaign {cid}: bad analytics response",
                  file=sys.stderr)
            continue

        sent = to_int(analytics.get("sent_count"))
        replies = to_int(analytics.get("reply_count"))
        bounces = to_int(analytics.get("bounce_count"))

        inboxes = fetch_campaign_inboxes(args.api_key, cid)
        # Group inboxes by domain
        domain_to_inboxes = defaultdict(set)
        for ib in inboxes:
            email = (ib.get("from_email") or ib.get("username") or "").strip()
            dom = domain_of(email)
            if dom:
                domain_to_inboxes[dom].add(ib.get("id"))
        n_inboxes = sum(len(s) for s in domain_to_inboxes.values())
        n_domains = len(domain_to_inboxes)

        rrate = pct(replies, sent)
        brate = pct(bounces, sent)
        flag_low_reply = (sent >= LOW_REPLY_MIN_SENT and rrate < LOW_REPLY_THRESHOLD_PCT)
        flag_high_bounce = (sent >= HIGH_BOUNCE_MIN_SENT and brate > HIGH_BOUNCE_THRESHOLD_PCT)

        campaign_rows.append({
            "campaign_id": cid,
            "name": (c.get("name") or analytics.get("name") or "").replace("\n", " "),
            "status": (c.get("status") or analytics.get("status") or "").upper(),
            "days": args.days,
            "sent": sent,
            "replies": replies,
            "bounces": bounces,
            "reply_rate_pct": rrate,
            "bounce_rate_pct": brate,
            "n_inboxes": n_inboxes,
            "n_domains": n_domains,
            "flag_low_reply": "TRUE" if flag_low_reply else "FALSE",
            "flag_high_bounce": "TRUE" if flag_high_bounce else "FALSE",
        })

        # Domain attribution: split sends proportionally to inbox count per domain.
        # Smartlead's send queue is roughly round-robin across the campaign's inboxes,
        # so inbox-count weighting is a reasonable approximation.
        if n_inboxes > 0:
            for dom, ib_ids in domain_to_inboxes.items():
                weight = len(ib_ids) / n_inboxes
                domain_agg[dom]["sent"] += sent * weight
                domain_agg[dom]["replies"] += replies * weight
                domain_agg[dom]["bounces"] += bounces * weight
                domain_agg[dom]["inboxes"].update(ib_ids)
                domain_agg[dom]["campaigns"].add(cid)

        if i % 10 == 0:
            print(f"[audit_performance]   {i}/{len(campaigns)} campaigns processed...",
                  file=sys.stderr)

    # Write campaigns CSV
    campaign_fields = ["campaign_id", "name", "status", "days", "sent", "replies",
                       "bounces", "reply_rate_pct", "bounce_rate_pct", "n_inboxes",
                       "n_domains", "flag_low_reply", "flag_high_bounce"]
    with open(args.out_campaigns, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campaign_fields)
        w.writeheader()
        w.writerows(campaign_rows)

    # Write domains CSV
    domain_rows = []
    for dom, agg in sorted(domain_agg.items()):
        sent = round(agg["sent"])
        replies = round(agg["replies"])
        bounces = round(agg["bounces"])
        rrate = pct(replies, sent)
        brate = pct(bounces, sent)
        flag_low_reply = (sent >= LOW_REPLY_MIN_SENT and rrate < LOW_REPLY_THRESHOLD_PCT)
        flag_high_bounce = (sent >= HIGH_BOUNCE_MIN_SENT and brate > HIGH_BOUNCE_THRESHOLD_PCT)
        domain_rows.append({
            "domain": dom,
            "n_inboxes": len(agg["inboxes"]),
            "n_campaigns": len(agg["campaigns"]),
            "sent_attributed": sent,
            "replies_attributed": replies,
            "bounces_attributed": bounces,
            "reply_rate_pct": rrate,
            "bounce_rate_pct": brate,
            "flag_low_reply": "TRUE" if flag_low_reply else "FALSE",
            "flag_high_bounce": "TRUE" if flag_high_bounce else "FALSE",
        })

    domain_fields = ["domain", "n_inboxes", "n_campaigns", "sent_attributed",
                     "replies_attributed", "bounces_attributed", "reply_rate_pct",
                     "bounce_rate_pct", "flag_low_reply", "flag_high_bounce"]
    with open(args.out_domains, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=domain_fields)
        w.writeheader()
        w.writerows(domain_rows)

    # Summary to stderr
    cflag_low = sum(1 for r in campaign_rows if r["flag_low_reply"] == "TRUE")
    cflag_high = sum(1 for r in campaign_rows if r["flag_high_bounce"] == "TRUE")
    dflag_low = sum(1 for r in domain_rows if r["flag_low_reply"] == "TRUE")
    dflag_high = sum(1 for r in domain_rows if r["flag_high_bounce"] == "TRUE")
    total_sent = sum(r["sent"] for r in campaign_rows)
    total_replies = sum(r["replies"] for r in campaign_rows)
    total_bounces = sum(r["bounces"] for r in campaign_rows)
    print(f"[audit_performance] {len(campaign_rows)} campaigns, {len(domain_rows)} domains",
          file=sys.stderr)
    print(f"[audit_performance] fleet: sent={total_sent:,} replies={total_replies:,} "
          f"bounces={total_bounces:,} reply%={pct(total_replies, total_sent)} "
          f"bounce%={pct(total_bounces, total_sent)}", file=sys.stderr)
    print(f"[audit_performance] flagged campaigns: low_reply={cflag_low} high_bounce={cflag_high}",
          file=sys.stderr)
    print(f"[audit_performance] flagged domains:   low_reply={dflag_low} high_bounce={dflag_high}",
          file=sys.stderr)
    print(f"[audit_performance] wrote {args.out_campaigns} and {args.out_domains}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
