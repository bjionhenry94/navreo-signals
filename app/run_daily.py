#!/usr/bin/env python3
"""The daily signals run — what the launchd schedule fires every morning.

For every ACTIVE source on every signal campaign:
  1. pull (fresh companies only: 90-day scan window + lead dedupe + exclusions
     + verified-email gate, paced by the source's leads-per-day)
  2. campaign autopilot ON  -> auto-push every new lead (email -> Smartlead,
     no email -> HeyReach), zero user intervention
     campaign autopilot OFF -> leads wait in the Leads tab for ✓ review

Each run appends a summary to app/data/daily_log.json (last 60 runs kept).
Manual invocation is safe any time - every layer is idempotent.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402
import build_notifications  # noqa: E402 — Lilly Optimiser notifications generator
import campaign_register  # noqa: E402 — server-side auto-registration reconcile
import subsequence_optimisations  # noqa: E402 — "no live campaign without a subsequence" audit
import scale_winner_insights  # noqa: E402 — Messaging-tab BEST pill → campaign-view card mirror

LOG = Path(__file__).parent / "data" / "daily_log.json"

# The cron ticks every 3h (see render.yaml's "0 */3 * * *"), but the Optimiser
# report is a ~26-40 min Smartlead pull that only needs to refresh once a day.
# Gate it here rather than in render.yaml so this file is the single source of
# truth for "how often" — reuses the same signal_cron_runs table run_daily's
# own batch-pull summaries already land in (server.cron_pull_all -> sb("POST",
# "signal_cron_runs", ...)), tagging optimiser rows with
# summary.kind == "optimiser_notifications" so they're distinguishable from
# the batch-pull rows without a schema change.
OPTIMISER_KIND = "optimiser_notifications"
OPTIMISER_MIN_AGE = timedelta(hours=20)  # daily cadence with headroom under 24h


def _last_optimiser_success_ts():
    """Best-effort read of the most recent successful optimiser run's
    timestamp from signal_cron_runs. Returns None (== "never ran" == "gate
    opens") on any failure, so a Supabase hiccup fails toward running the
    generation rather than silently never running it again."""
    try:
        rows = server.sb("GET", "signal_cron_runs?select=summary&order=id.desc&limit=50")
        for row in rows or []:
            summary = row.get("summary") if isinstance(row, dict) else None
            if isinstance(summary, dict) and summary.get("kind") == OPTIMISER_KIND and summary.get("ok"):
                ts = summary.get("ts")
                if ts:
                    return datetime.fromisoformat(ts)
        return None
    except Exception as e:  # noqa: BLE001 — never let observability block the gate
        print(f"  ! could not read last optimiser run ({str(e)[:150]}) - treating as due")
        return None


def _record_optimiser_run(ok: bool, rows=None, error: str | None = None) -> None:
    """Durable, queryable record of the optimiser generation, same
    best-effort shape as server.cron_pull_all's own signal_cron_runs write."""
    summary = {"kind": OPTIMISER_KIND, "ok": ok, "ts": datetime.now().isoformat(timespec="seconds")}
    if rows is not None:
        summary["rows"] = rows
    if error:
        summary["error"] = error[:200]
    try:
        server.sb("POST", "signal_cron_runs", {"summary": summary})
    except Exception:  # noqa: BLE001
        pass


def run_optimiser_refresh() -> None:
    """Gate: only regenerate optimiser_notifications if the last SUCCESSFUL
    run is older than OPTIMISER_MIN_AGE (or there has never been one). A
    failed generation is never recorded as a success, so the very next
    3-hourly tick retries it rather than waiting another day."""
    last_ok = _last_optimiser_success_ts()
    if last_ok is not None and datetime.now() - last_ok < OPTIMISER_MIN_AGE:
        print(f"optimiser refresh · skipped (last success {last_ok.isoformat(timespec='seconds')}, "
              f"under {OPTIMISER_MIN_AGE.total_seconds() / 3600:.0f}h old)")
        return
    print("optimiser refresh · due - running build_notifications ...")
    try:
        rows = build_notifications.main()
        _record_optimiser_run(ok=True, rows=rows)
        print(f"optimiser refresh · done ({rows} rows upserted)")
    except Exception as e:  # noqa: BLE001 — one bad generation must not kill run_daily
        _record_optimiser_run(ok=False, error=str(e))
        print(f"optimiser refresh · FAILED: {str(e)[:200]}")


def main():
    campaigns = {str(c.get("id")): c for c in server.read_json_list(server.CAMPAIGN_DRAFTS)
                 if not c.get("deleted_at")}  # soft-deleted campaigns never pull
    source_ids = [d["id"] for d in server.read_drafts()
                  if d.get("active", True) and not d.get("deleted_at")
                  and str(d.get("campaign_id")) in campaigns]
    run = {"ts": datetime.now().isoformat(timespec="seconds"), "sources": []}
    print(f"daily run · {len(source_ids)} active sources")

    for sid in source_ids:
        entry = {"id": sid}
        try:
            with server.drafts_lock():  # same mutex the HTTP writers use
                r = server.pull_source({"id": sid})
            entry["pull"] = r.get("note") or r.get("message") or ""
            entry["ok"] = bool(r.get("ok"))
            drafts = server.read_drafts()  # the pull rewrote the file
            src = next((d for d in drafts if d.get("id") == sid), None)
            camp = campaigns.get(str((src or {}).get("campaign_id"))) or {}
            entry["campaign"] = camp.get("name")
            if src and camp.get("autopilot"):
                with server.drafts_lock():
                    drafts = server.read_drafts()  # re-read under the lock
                    src = next((d for d in drafts if d.get("id") == sid), src)
                    pushed = server.auto_push_new_leads(src)
                    server.write_source(src)  # only this source's push stamps changed
                entry["autopushed"] = [p for p in pushed if p["ok"]]
                entry["push_failed"] = [p for p in pushed if not p["ok"]]
            else:
                entry["autopilot"] = False  # leads wait for manual ✓
        except Exception as e:  # noqa: BLE001 — one bad source must not kill the run
            entry["error"] = str(e)[:200]
        run["sources"].append(entry)
        n_push = len(entry.get("autopushed") or [])
        print(f"  {sid} · {entry.get('pull') or entry.get('error') or ''}"
              + (f" · {n_push} auto-pushed" if n_push else "")
              + (" · manual (awaiting review)" if entry.get("autopilot") is False else ""))

    prior = json.loads(LOG.read_text()).get("runs", []) if LOG.exists() else []
    LOG.write_text(json.dumps({"runs": (prior + [run])[-60:]}, indent=1))
    print("run logged.")

    run_optimiser_refresh()  # gated to once/day; never blocks/kills the source pulls above

    # Variant-path + meeting-step stamping (Supabase-first messaging tab): the
    # web request path never crawls Smartlead message history, so this cron
    # stamps vpath2 / step backfills for any unresolved booked leads. Cheap
    # once stamped — the unstamped set only shrinks.
    try:
        bf = server.vpath_backfill()
        print(f"vpath backfill · {len(bf)} campaign(s): "
              + (", ".join(f"{k}: {v}" for k, v in list(bf.items())[:8]) or "none"))
    except Exception as e:  # noqa: BLE001 — stamping must never kill the run
        print(f"vpath backfill · FAILED: {str(e)[:200]}")

    # Auto-register any freshly-built Smartlead campaign the tool doesn't yet
    # know about (Bjion 2026-08-03: "happens automatically from server-side").
    # Cheap in steady state — one /campaigns list per workspace, a leads export
    # only for genuinely new campaigns — so it runs every tick, no gate.
    try:
        r = campaign_register.reconcile()
        names = ", ".join(x["id"] for x in r["registered"][:8]) or "none"
        print(f"campaign register · checked {r['checked']}, registered "
              f"{len(r['registered'])} ({names})"
              + (f", {len(r['errors'])} error(s)" if r["errors"] else ""))
    except Exception as e:  # noqa: BLE001 — registration must never kill the run
        print(f"campaign register · FAILED: {str(e)[:200]}")

    # No live campaign without a subsequence (Bjion 2026-08-10): put an "Add a
    # subsequence" card on every ACTIVE campaign that has no Interested Reply /
    # Meeting Request child, and clear it the moment one appears. Cheap — one
    # /campaigns list — so it runs every tick, no gate. Runs AFTER the crunch so
    # a same-tick optimiser regen of a 1,500+ scope can't leave the card wiped.
    try:
        s = subsequence_optimisations.refresh()
        print(f"subsequence audit · {s.get('missing', 0)} missing "
              f"(+{s.get('added', 0)} new, {s.get('refreshed', 0)} refreshed, "
              f"{s.get('cleared', 0)} cleared)")
    except Exception as e:  # noqa: BLE001 — the audit must never kill the run
        print(f"subsequence audit · FAILED: {str(e)[:200]}")

    # Scale-winner parity, campaign-view leg (Bjion 2026-08-16): mirror the live
    # scale_winner optimiser_notifications rows (maintained by the optimiser
    # refresh above, pill-rule parity) into campaign_insights cards so the
    # campaigns page's "Review N" badge + action cards carry them too. Cheap —
    # two Supabase reads — so it runs every tick, no gate. Runs AFTER the
    # optimiser refresh so a same-tick verdict flip mirrors in the same tick.
    try:
        s = scale_winner_insights.refresh()
        print(f"scale-winner cards · {s.get('wanted', 0)} wanted "
              f"(+{s.get('added', 0)} new, {s.get('refreshed', 0)} refreshed, "
              f"{s.get('cleared', 0)} cleared, {s.get('skipped_crunch_dupe', 0)} crunch-owned)")
    except Exception as e:  # noqa: BLE001 — the mirror must never kill the run
        print(f"scale-winner cards · FAILED: {str(e)[:200]}")

    # Analytics client-windows blob (the Analytics page's day-by-day + window
    # source): built HERE, on the cron's own instance, and persisted to
    # Supabase for the web to adopt. The ~7-min 500+-call sweep OOM-killed the
    # 512MB web box mid-build (2026-08-12: every client's "yesterday" read 0
    # sent off a 29h-stale blob, and each Analytics visit crash-looped the
    # instance). Every tick, no gate — freshness IS the point.
    try:
        r = server.client_windows_cron_refresh()
        print("client windows · " + ("ok" if r["ok"] else "GATED (not persisted)")
              + f" in {r.get('secs')}s"
              + (f" · errors: {r['errors']}" if r.get("errors") else ""))
    except Exception as e:  # noqa: BLE001 — the sweep must never kill the run
        print(f"client windows · FAILED: {str(e)[:200]}")


if __name__ == "__main__":
    main()
