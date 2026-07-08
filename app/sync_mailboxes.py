#!/usr/bin/env python3
"""Smartlead -> Supabase mailbox sync — Render Cron Job.

Ports the proven Node script (mailbox-db-sync/scripts/sync-mailboxes.mjs) to
Python so it can run as a Render Cron Job instead of Windows Task Scheduler
(no dependency on a machine being logged in).

Pulls EVERY Smartlead mailbox + its 30-day health metrics, transforms each
into a `mailboxes` snapshot row and a `mailbox_stats_daily` row keyed on
today's date, and upserts both tables in Supabase via PostgREST
(resolution=merge-duplicates). Verifies the write by re-reading both tables'
counts afterwards.

Logs via print() only — Render captures stdout for cron job logs, and the
filesystem is ephemeral on Render (no local log file, unlike the Node
original).

Run:  python app/sync_mailboxes.py
Exit: 0 on success (verification passed), 1 on any unrecoverable failure.
"""

import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402 — reuse KEYS / http_json / SSL_CTX conventions

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
PAGE_SIZE = 100
MAX_OFFSET = 200000
CONSECUTIVE_EMPTY_STOP = 4
PAGE_RETRY_ATTEMPTS = 5
PAGE_RETRY_BASE_SEC = 1.2
INTER_PAGE_DELAY_SEC = 0.25
BATCH_SIZE = 500


# ---------- logging ----------
def log(msg: str):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ---------- low-level HTTP (need raw status/text/headers, not just http_json's parsed JSON) ----------
def _request(method: str, url: str, headers: dict, body=None, timeout: int = 60):
    """Returns (status, text, headers) — never raises on HTTP error status,
    only on transport-level failures (DNS, connect, timeout)."""
    import json as _json

    data = _json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=server.SSL_CTX) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", "replace")
        return e.code, body_text, dict(e.headers or {})


def to_num(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return 0 if v != v else v  # NaN guard
    if isinstance(v, str):
        cleaned = v.replace("%", "").strip()
        try:
            n = float(cleaned)
            return int(n) if n.is_integer() else n
        except ValueError:
            return 0
    return 0


def local_date_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ---------- pull 1: all mailboxes ----------
def fetch_mailboxes_page(offset: int, smartlead_key: str) -> list:
    url = f"{SMARTLEAD_BASE}/email-accounts/?api_key={smartlead_key}&offset={offset}&limit={PAGE_SIZE}"
    for attempt in range(1, PAGE_RETRY_ATTEMPTS + 1):
        try:
            status, text, _ = _request("GET", url, {"User-Agent": server.UA})
            if 200 <= status < 300:
                import json as _json
                try:
                    parsed = _json.loads(text)
                    if isinstance(parsed, list):
                        return parsed
                    log(f"Page offset={offset} attempt={attempt}: response not a JSON array, retrying")
                except ValueError as e:
                    log(f"Page offset={offset} attempt={attempt}: invalid JSON ({e}), retrying")
            else:
                log(f"Page offset={offset} attempt={attempt}: HTTP {status}, retrying")
        except Exception as e:  # noqa: BLE001 — transport error, retry
            log(f"Page offset={offset} attempt={attempt}: fetch error ({e}), retrying")
        if attempt < PAGE_RETRY_ATTEMPTS:
            time.sleep(PAGE_RETRY_BASE_SEC * attempt)
    log(f"Page offset={offset}: all {PAGE_RETRY_ATTEMPTS} attempts failed, treating page as EMPTY")
    return []


def pull_all_mailboxes(smartlead_key: str):
    by_id = {}
    offset = 0
    consecutive_empty = 0
    pages_fetched = 0

    while offset <= MAX_OFFSET:
        page = fetch_mailboxes_page(offset, smartlead_key)
        pages_fetched += 1

        if len(page) == 0:
            consecutive_empty += 1
            log(f"Page offset={offset}: 0 records (consecutive empty={consecutive_empty}/{CONSECUTIVE_EMPTY_STOP})")
            if consecutive_empty >= CONSECUTIVE_EMPTY_STOP:
                log(f"Reached {CONSECUTIVE_EMPTY_STOP} consecutive empty pages, stopping pagination at offset={offset}")
                break
        else:
            consecutive_empty = 0
            new_count = 0
            for m in page:
                mid = m.get("id") if isinstance(m, dict) else None
                if mid is not None:
                    if mid not in by_id:
                        new_count += 1
                    by_id[mid] = m
            log(f"Page offset={offset}: {len(page)} records ({new_count} new; running unique total={len(by_id)})")

        offset += PAGE_SIZE
        time.sleep(INTER_PAGE_DELAY_SEC)

    if offset > MAX_OFFSET:
        log(f"WARNING: reached MAX_OFFSET={MAX_OFFSET} without hitting {CONSECUTIVE_EMPTY_STOP} consecutive empty pages")

    return list(by_id.values()), pages_fetched


# ---------- pull 2: per-mailbox 30d metrics ----------
def pull_metrics(smartlead_key: str, start_date_str: str, end_date_str: str) -> list:
    url = (f"{SMARTLEAD_BASE}/analytics/mailbox/name-wise-health-metrics"
           f"?api_key={smartlead_key}&start_date={start_date_str}&end_date={end_date_str}&full_data=true")
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            # full_data=true on an ~9k-mailbox account can take well over 60s to
            # compute server-side (observed 20-90s+); give it generous headroom
            # rather than the default 60s used for the paginated mailbox pulls.
            status, text, _ = _request("GET", url, {"User-Agent": server.UA}, timeout=180)
            if 200 <= status < 300:
                import json as _json
                try:
                    parsed = _json.loads(text)
                except ValueError:
                    parsed = None
                lst = ((parsed or {}).get("data") or {}).get("email_health_metrics") if isinstance(parsed, dict) else None
                if isinstance(lst, list):
                    return lst
                log(f"Metrics pull attempt={attempt}: unexpected response shape, retrying")
            else:
                log(f"Metrics pull attempt={attempt}: HTTP {status} body={text[:300]}, retrying")
        except Exception as e:  # noqa: BLE001
            log(f"Metrics pull attempt={attempt}: fetch error ({e}), retrying")
        if attempt < attempts:
            time.sleep(2)
    raise RuntimeError("Failed to pull name-wise-health-metrics after 3 attempts")


# ---------- transform ----------
def transform_mailbox(m: dict, metrics_map: dict, today_str: str, now_iso_str: str):
    email = (m.get("from_email") or "").lower()
    domain = email.split("@")[1] if "@" in email else None
    wd = m.get("warmup_details") or {}

    warmup_enabled = wd.get("status") == "ACTIVE"
    warmup_status = wd.get("status")
    wr = wd.get("warmup_reputation")
    warmup_reputation_pct = None
    if wr is not None:
        try:
            warmup_reputation_pct = int(float(str(wr).replace("%", "").strip()))
        except ValueError:
            warmup_reputation_pct = None
    blocked_reason = wd.get("blocked_reason")

    metrics = metrics_map.get(email)
    sent_30d = replies_30d = bounces_30d = positive_replies_30d = 0
    open_rate_pct = reply_rate_pct = bounce_rate_pct = 0
    has_metrics = metrics is not None
    if metrics:
        sent_30d = to_num(metrics.get("sent"))
        replies_30d = to_num(metrics.get("replied"))
        bounces_30d = to_num(metrics.get("bounced"))
        positive_replies_30d = to_num(metrics.get("positive_replied"))
        open_rate_pct = to_num(metrics.get("open_rate"))
        reply_rate_pct = to_num(metrics.get("reply_rate"))
        bounce_rate_pct = to_num(metrics.get("bounce_rate"))

    tags = m.get("tags") if isinstance(m.get("tags"), list) else []

    mailbox_row = {
        "smartlead_id": m.get("id"),
        "email": email,
        "domain": domain,
        "from_name": m.get("from_name"),
        "smtp_host": m.get("smtp_host"),
        "account_type": m.get("type"),
        "tags": tags,
        "message_per_day": m.get("message_per_day"),
        "warmup_enabled": warmup_enabled,
        "warmup_status": warmup_status,
        "warmup_reputation_pct": warmup_reputation_pct,
        "blocked_reason": blocked_reason,
        "smtp_ok": m.get("is_smtp_success"),
        "imap_ok": m.get("is_imap_success"),
        "campaign_count": m.get("campaign_count"),
        "client_id": m.get("client_id"),
        "last_synced_at": now_iso_str,
    }

    stats_row = {
        "smartlead_id": m.get("id"),
        "stat_date": today_str,
        "daily_sent_count": m.get("daily_sent_count"),
        "message_per_day": m.get("message_per_day"),
        "warmup_enabled": warmup_enabled,
        "warmup_status": warmup_status,
        "warmup_reputation_pct": warmup_reputation_pct,
        "sent_30d": sent_30d,
        "replies_30d": replies_30d,
        "bounces_30d": bounces_30d,
        "open_rate_pct": open_rate_pct,
        "reply_rate_pct": reply_rate_pct,
        "bounce_rate_pct": bounce_rate_pct,
        "positive_replies_30d": positive_replies_30d,
        "smtp_ok": m.get("is_smtp_success"),
        "imap_ok": m.get("is_imap_success"),
        "tags": tags,
    }

    return mailbox_row, stats_row, has_metrics


# ---------- supabase writes ----------
def _sb_headers(supabase_key: str, prefer: str) -> dict:
    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
        "User-Agent": server.UA,
    }


def upsert_once(table: str, rows: list, supabase_url: str, supabase_key: str):
    endpoint = f"{supabase_url}/rest/v1/{table}"
    headers = _sb_headers(supabase_key, "resolution=merge-duplicates,return=minimal")
    return _request("POST", endpoint, headers, rows)


def upsert_batch(table: str, rows: list, batch_index: int, supabase_url: str, supabase_key: str):
    status, text, _ = upsert_once(table, rows, supabase_url, supabase_key)
    if not (200 <= status < 300):
        log(f"Batch {batch_index} for {table} ({len(rows)} rows) FAILED status={status} body={text[:500]}")
        time.sleep(2)
        status2, text2, _ = upsert_once(table, rows, supabase_url, supabase_key)
        if not (200 <= status2 < 300):
            log(f"Batch {batch_index} for {table} ({len(rows)} rows) FAILED AGAIN status={status2} body={text2[:500]}")
            raise RuntimeError(f"Aborting: batch {batch_index} for {table} failed twice")
        log(f"Batch {batch_index} for {table} succeeded on retry")


def write_batches(table: str, rows: list, supabase_url: str, supabase_key: str) -> int:
    batches = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batches += 1
        upsert_batch(table, batch, batches, supabase_url, supabase_key)
    log(f"{table}: wrote {batches} batch(es) totalling {len(rows)} rows")
    return batches


# ---------- verification ----------
def verify_count(table: str, filter_query: str | None, supabase_url: str, supabase_key: str):
    qs = f"&{filter_query}" if filter_query else ""
    url = f"{supabase_url}/rest/v1/{table}?select=smartlead_id{qs}&limit=1"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Prefer": "count=exact",
        "Range": "0-0",
        "User-Agent": server.UA,
    }
    status, _, resp_headers = _request("GET", url, headers)
    # header dict keys may vary in case; normalise
    cr = next((v for k, v in resp_headers.items() if k.lower() == "content-range"), None)
    if not cr:
        log(f"Verification query for {table} returned no content-range header (status={status})")
        return None
    try:
        total = int(cr.split("/")[1])
        return total
    except (IndexError, ValueError):
        return None


# ---------- main ----------
def main():
    log("=== Smartlead -> Supabase mailbox sync: START ===")

    smartlead_key = server.KEYS.get("SMARTLEAD_API_KEY")
    supabase_url = server.KEYS.get("SUPABASE_URL")
    supabase_key = server.KEYS.get("SUPABASE_SERVICE_ROLE_KEY")

    if not smartlead_key or not supabase_url or not supabase_key:
        log("FATAL: missing one or more required keys: SMARTLEAD_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    log(f"SMARTLEAD_API_KEY={smartlead_key[:6]}... SUPABASE_URL={supabase_url} "
        f"SUPABASE_SERVICE_ROLE_KEY={supabase_key[:6]}...")

    now = datetime.now(timezone.utc)
    now_iso_str = now.isoformat()
    today_str = local_date_str(now)
    start_date_str = local_date_str(now - timedelta(days=30))
    log(f"Today (UTC): {today_str}. Metrics window: {start_date_str} -> {today_str}")

    try:
        # Pull 1
        log("Pulling all mailboxes from /email-accounts/ ...")
        mailboxes, pages_fetched = pull_all_mailboxes(smartlead_key)
        log(f"Pull 1 complete: {pages_fetched} pages fetched, {len(mailboxes)} unique mailboxes pulled")

        # Pull 2
        log("Pulling 30d name-wise health metrics ...")
        metrics_list = pull_metrics(smartlead_key, start_date_str, today_str)
        log(f"Pull 2 complete: {len(metrics_list)} metrics entries returned")

        metrics_map = {}
        for entry in metrics_list:
            if entry and entry.get("from_email"):
                metrics_map[str(entry["from_email"]).lower()] = entry

        # Transform
        mailbox_rows, stats_rows = [], []
        no_metrics_count = 0
        warmup_statuses_seen = set()
        for m in mailboxes:
            mailbox_row, stats_row, has_metrics = transform_mailbox(m, metrics_map, today_str, now_iso_str)
            mailbox_rows.append(mailbox_row)
            stats_rows.append(stats_row)
            if not has_metrics:
                no_metrics_count += 1
            if mailbox_row["warmup_status"]:
                warmup_statuses_seen.add(mailbox_row["warmup_status"])
        log(f"Transform complete: {len(mailbox_rows)} mailbox rows, {len(stats_rows)} stats rows")
        log(f"Mailboxes without a 30d metrics entry: {no_metrics_count}")
        log(f"Distinct warmup_details.status values observed: "
            f"{', '.join(sorted(warmup_statuses_seen)) if warmup_statuses_seen else '(none)'}")

        # Write mailboxes FIRST (mailbox_stats_daily has FK -> mailboxes.smartlead_id)
        log("Writing mailboxes table ...")
        mailbox_batches = write_batches("mailboxes", mailbox_rows, supabase_url, supabase_key)

        log("Writing mailbox_stats_daily table ...")
        stats_batches = write_batches("mailbox_stats_daily", stats_rows, supabase_url, supabase_key)

        total_batches = mailbox_batches + stats_batches
        log(f"Total batches written: {total_batches} (mailboxes={mailbox_batches}, "
            f"mailbox_stats_daily={stats_batches})")

        # Verification
        log("Verifying row counts in Supabase ...")
        mailboxes_total = verify_count("mailboxes", None, supabase_url, supabase_key)
        stats_total = verify_count("mailbox_stats_daily", f"stat_date=eq.{today_str}", supabase_url, supabase_key)
        log(f"Supabase mailboxes total: {mailboxes_total}")
        log(f"Supabase mailbox_stats_daily total for stat_date={today_str}: {stats_total}")
        log(f"Pulled unique mailbox count: {len(mailboxes)}")

        # Null-rate check (in-memory, matches what was written)
        null_counts = {"message_per_day": 0, "warmup_enabled": 0, "reply_rate_pct": 0,
                        "bounce_rate_pct": 0, "tags": 0}
        for row in stats_rows:
            for field in null_counts:
                if row.get(field) is None:
                    null_counts[field] += 1
        total = len(stats_rows) or 1
        def pct(n):
            return f"{(n / total) * 100:.2f}"
        log(f"Null-rate check (of {len(stats_rows)} stats rows): "
            f"message_per_day null={null_counts['message_per_day']} ({pct(null_counts['message_per_day'])}%), "
            f"warmup_enabled null={null_counts['warmup_enabled']} ({pct(null_counts['warmup_enabled'])}%), "
            f"reply_rate_pct null={null_counts['reply_rate_pct']} ({pct(null_counts['reply_rate_pct'])}%), "
            f"bounce_rate_pct null={null_counts['bounce_rate_pct']} ({pct(null_counts['bounce_rate_pct'])}%), "
            f"tags null={null_counts['tags']} ({pct(null_counts['tags'])}%)")

        success = mailboxes_total == len(mailboxes) and stats_total == len(mailboxes)
        if success:
            log("Verification PASSED: mailboxes and mailbox_stats_daily counts both equal pulled count")
            log("=== Smartlead -> Supabase mailbox sync: END (exit 0) ===")
            sys.exit(0)
        else:
            log(f"Verification FAILED: pulled={len(mailboxes)}, mailboxes_total={mailboxes_total}, "
                f"stats_total={stats_total}")
            log("=== Smartlead -> Supabase mailbox sync: END (exit 1) ===")
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — top-level catch, matches Node's main().catch()
        log(f"FATAL ERROR: {e!r}")
        log("=== Smartlead -> Supabase mailbox sync: END (exit 1) ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
