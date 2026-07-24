#!/usr/bin/env python3
"""Smartlead -> Supabase mailbox sync — Render Cron Job.

Ports the proven Node script (mailbox-db-sync/scripts/sync-mailboxes.mjs) to
Python so it can run as a Render Cron Job instead of Windows Task Scheduler
(no dependency on a machine being logged in).

Pulls EVERY Smartlead mailbox + its 30-day health metrics + its ACTIVE-campaign
attachment count (per-campaign email-accounts sweep — the list endpoint never
returns campaign_count), transforms each into a `mailboxes` snapshot row and a
`mailbox_stats_daily` row keyed on today's date, and upserts both tables in
Supabase via PostgREST
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


# ---------- pull 3: ACTIVE-campaign attachment counts ----------
def _get_json_retry(url: str, attempts: int = 3, timeout: int = 120):
    """GET url expecting a JSON array/object; returns parsed value or None
    after exhausting retries."""
    import json as _json

    for attempt in range(1, attempts + 1):
        try:
            status, text, _ = _request("GET", url, {"User-Agent": server.UA}, timeout=timeout)
            if 200 <= status < 300:
                try:
                    return _json.loads(text)
                except ValueError:
                    log(f"GET attempt={attempt}: invalid JSON, retrying")
            else:
                log(f"GET attempt={attempt}: HTTP {status}, retrying")
        except Exception as e:  # noqa: BLE001 — transport error, retry
            log(f"GET attempt={attempt}: fetch error ({e}), retrying")
        if attempt < attempts:
            time.sleep(PAGE_RETRY_BASE_SEC * attempt)
    return None


def pull_campaign_counts(smartlead_key: str):
    """Smartlead's /email-accounts/ list endpoint never returns campaign_count
    (verified 2026-07-11 — the field is simply absent, which left the column at
    0 across the whole fleet). The only source of truth for campaign membership
    is GET /campaigns/{id}/email-accounts per ACTIVE campaign — the same sweep
    server.py's restore path uses live (~1 call per active campaign, throttled
    well under the 200/min cap).

    Returns {from_email(lower): number of ACTIVE campaigns attached}, or None
    if the sweep could not complete. On None the caller must OMIT
    campaign_count from the upsert payload entirely so merge-duplicates
    preserves the last-known values instead of overwriting them with zeros."""
    camps = _get_json_retry(f"{SMARTLEAD_BASE}/campaigns?api_key={smartlead_key}", timeout=60)
    if not isinstance(camps, list):
        log("Campaign sweep: could not fetch /campaigns list")
        return None
    active = [c for c in camps if isinstance(c, dict) and c.get("status") == "ACTIVE"]
    log(f"Campaign sweep: {len(active)} ACTIVE campaigns (of {len(camps)} total)")

    counts = {}
    failed = 0
    for i, c in enumerate(active, 1):
        rows = _get_json_retry(
            f"{SMARTLEAD_BASE}/campaigns/{c['id']}/email-accounts?api_key={smartlead_key}")
        if not isinstance(rows, list):
            failed += 1
            log(f"Campaign sweep: campaign {c['id']} failed all attempts "
                f"({failed} failed so far)")
        else:
            for a in rows:
                email = (a.get("from_email") or "").lower() if isinstance(a, dict) else ""
                if email:
                    counts[email] = counts.get(email, 0) + 1
        if i % 25 == 0:
            log(f"Campaign sweep: {i}/{len(active)} campaigns swept")
        time.sleep(0.35)

    if failed:
        # A partial sweep would write undercounts that look just as authoritative
        # as real ones — preserve yesterday's values instead.
        log(f"Campaign sweep: {failed}/{len(active)} campaigns failed — treating sweep as incomplete")
        return None
    return counts


# ---------- transform ----------
def transform_mailbox(m: dict, metrics_map: dict, campaign_counts, today_str: str, now_iso_str: str):
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
        "client_id": m.get("client_id"),
        "last_synced_at": now_iso_str,
    }
    if campaign_counts is not None:
        # Omitted uniformly when the sweep failed: merge-duplicates then leaves
        # the column's last-known values untouched.
        mailbox_row["campaign_count"] = campaign_counts.get(email, 0)

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
    # PostgREST bulk upserts demand identical key sets across every row in a
    # request (PGRST102 "All object keys must match"). Rows legitimately differ
    # in shape — e.g. campaign_count is omitted for a workspace whose campaign
    # sweep was incomplete — so group rows by their exact key set and batch
    # within each group. Never pad missing keys with nulls: a null would
    # overwrite the last-known value merge-duplicates is meant to preserve.
    groups: dict = {}
    for row in rows:
        groups.setdefault(frozenset(row.keys()), []).append(row)
    if len(groups) > 1:
        log(f"{table}: {len(groups)} distinct row shapes — batching each shape separately "
            f"(sizes: {', '.join(str(len(g)) for g in groups.values())})")
    batches = 0
    for shaped in groups.values():
        for i in range(0, len(shaped), BATCH_SIZE):
            batch = shaped[i:i + BATCH_SIZE]
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

    supabase_url = server.KEYS.get("SUPABASE_URL")
    supabase_key = server.KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    # Federated (client-workspaces-hub): one sweep per enabled workspace —
    # navreo (env key) + every connected client Smartlead (key from the
    # workspaces table). Rows are workspace-stamped.
    workspaces = [w for w in server.ws_enabled() if server.ws_key(w.get("id"))]

    if not workspaces or not supabase_url or not supabase_key:
        log("FATAL: need SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and at least one workspace key")
        sys.exit(1)
    log(f"Workspaces: {', '.join(w.get('id') for w in workspaces)} | SUPABASE_URL={supabase_url}")

    now = datetime.now(timezone.utc)
    now_iso_str = now.isoformat()
    today_str = local_date_str(now)
    start_date_str = local_date_str(now - timedelta(days=30))
    log(f"Today (UTC): {today_str}. Metrics window: {start_date_str} -> {today_str}")

    try:
        mailbox_rows, stats_rows = [], []
        ws_pulled: dict = {}
        ws_failed: list = []
        no_metrics_count = 0
        warmup_statuses_seen = set()
        for w in workspaces:
            wid = w.get("id")
            wkey = server.ws_key(wid)
            try:
                # Pull 1
                log(f"[{wid}] Pulling all mailboxes from /email-accounts/ ...")
                mailboxes, pages_fetched = pull_all_mailboxes(wkey)
                log(f"[{wid}] Pull 1 complete: {pages_fetched} pages fetched, "
                    f"{len(mailboxes)} unique mailboxes pulled")

                # Pull 2
                log(f"[{wid}] Pulling 30d name-wise health metrics ...")
                metrics_list = pull_metrics(wkey, start_date_str, today_str)
                log(f"[{wid}] Pull 2 complete: {len(metrics_list)} metrics entries returned")

                metrics_map = {}
                for entry in metrics_list:
                    if entry and entry.get("from_email"):
                        metrics_map[str(entry["from_email"]).lower()] = entry

                # Pull 3
                log(f"[{wid}] Pulling ACTIVE-campaign attachment counts (per-campaign email-accounts sweep) ...")
                campaign_counts = pull_campaign_counts(wkey)
                if campaign_counts is None:
                    log(f"[{wid}] WARNING: campaign sweep incomplete — campaign_count omitted this run, "
                        "last-known values preserved in Supabase")
                else:
                    attached = sum(1 for v in campaign_counts.values() if v)
                    log(f"[{wid}] Pull 3 complete: {attached} mailboxes attached to >=1 ACTIVE campaign, "
                        f"{sum(campaign_counts.values())} total attachments")

                # Transform — every row stamped with its owner workspace
                for m in mailboxes:
                    mailbox_row, stats_row, has_metrics = transform_mailbox(
                        m, metrics_map, campaign_counts, today_str, now_iso_str)
                    mailbox_row["workspace"] = wid
                    stats_row["workspace"] = wid
                    mailbox_rows.append(mailbox_row)
                    stats_rows.append(stats_row)
                    if not has_metrics:
                        no_metrics_count += 1
                    if mailbox_row["warmup_status"]:
                        warmup_statuses_seen.add(mailbox_row["warmup_status"])
                ws_pulled[wid] = len(mailboxes)
            except Exception as we:  # noqa: BLE001 — a client-workspace failure must never kill the navreo sweep
                if wid == "navreo":
                    raise
                ws_failed.append(wid)
                log(f"[{wid}] WARNING: workspace sweep FAILED ({we!r}) — continuing with the others")
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

        # Verification — per workspace: filtered counts must equal that
        # workspace's own pulled count (a whole-table count would mix
        # workspaces and could never reconcile)
        log("Verifying row counts in Supabase ...")
        ver_ok = True
        for wid, pulled in ws_pulled.items():
            # Verify what THIS RUN wrote, not the whole table: the mailboxes
            # table legitimately keeps rows for accounts since deleted from
            # Smartlead (upserts never delete), so a whole-table equality check
            # can never pass once the fleet shrinks — and a check that can't
            # pass is a bug. Anchor on this run's last_synced_at stamp; for the
            # per-day stats table (keyed smartlead_id+stat_date, no such stamp)
            # require at least the pulled count — other same-day writers may
            # add rows, but ours must all be present.
            # URL-encode the timestamp: its "+00:00" offset reads as a space
            # in a query string and 400s the request.
            from urllib.parse import quote as _q
            m_run = verify_count("mailboxes",
                                 f"workspace=eq.{wid}&last_synced_at=eq.{_q(now_iso_str)}",
                                 supabase_url, supabase_key)
            s_total = verify_count("mailbox_stats_daily",
                                   f"stat_date=eq.{today_str}&workspace=eq.{wid}",
                                   supabase_url, supabase_key)
            log(f"[{wid}] pulled={pulled} mailboxes_written_this_run={m_run} stats_total_today={s_total}")
            if not (m_run == pulled and (s_total or 0) >= pulled):
                ver_ok = False

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

        # Exit contract: the NAVREO fleet is the paging signal — its failure is
        # exit 1. A client-workspace failure logs LOUDLY above but does not
        # page as a fleet failure (a revoked client key must not read as our
        # fleet breaking); verified workspaces must still reconcile exactly.
        success = ver_ok and "navreo" in ws_pulled
        if ws_failed:
            log(f"WARNING: {len(ws_failed)} client workspace sweep(s) FAILED this run: {', '.join(ws_failed)}")
        if success:
            log("Verification PASSED: per-workspace mailboxes and mailbox_stats_daily counts equal pulled counts")
            log("=== Smartlead -> Supabase mailbox sync: END (exit 0) ===")
            sys.exit(0)
        else:
            log("Verification FAILED: per-workspace counts above do not reconcile")
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
