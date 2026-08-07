#!/usr/bin/env python3
"""
Deliverability Audit Report Synthesizer

Reads the CSVs produced by audit_inboxes.py, check_domain_auth.py and
audit_performance.py (plus optional spam-test.json from run_spam_test.py),
then writes a single Markdown report with prioritized action items.

Usage:
    python3 generate_report.py --audit-dir /tmp/audit --out /tmp/audit/report.md

Expects these files inside --audit-dir (any missing files are skipped, but
inboxes.csv is the minimum):
    inboxes.csv         (required)
    auth.csv            (optional but recommended)
    campaigns.csv       (optional)
    domains.csv         (optional)
    spam-test.json      (optional)
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None


def truthy(v):
    return str(v).strip().upper() == "TRUE"


def pct(num, denom):
    if not denom:
        return 0.0
    return round(100.0 * num / denom, 2)


def fmt_pct(v):
    try:
        return f"{float(v):.2f}%"
    except (ValueError, TypeError):
        return "—"


def section(title, level=2):
    return f"\n{'#' * level} {title}\n"


def build_summary(inboxes, auth_rows, campaigns, domains, spam_test, lookback_days):
    n_inboxes = len(inboxes)
    n_domains = len({(r.get("domain") or "").lower() for r in inboxes if r.get("domain")})
    blocked = sum(1 for r in inboxes if truthy(r.get("flag_blocked")))
    smtp_fail = sum(1 for r in inboxes if truthy(r.get("flag_smtp_fail")))
    imap_fail = sum(1 for r in inboxes if truthy(r.get("flag_imap_fail")))
    low_rep = sum(1 for r in inboxes if truthy(r.get("flag_low_reputation")))

    missing_dkim = sum(1 for r in auth_rows if not truthy(r.get("dkim_present")))
    missing_dmarc = sum(1 for r in auth_rows if not truthy(r.get("dmarc_present")))
    dmarc_none = sum(1 for r in auth_rows if (r.get("dmarc_policy") or "").lower() == "none")
    missing_spf = sum(1 for r in auth_rows if not truthy(r.get("spf_present")))

    sent_total = sum(int(r.get("sent") or 0) for r in campaigns)
    replies_total = sum(int(r.get("replies") or 0) for r in campaigns)
    bounces_total = sum(int(r.get("bounces") or 0) for r in campaigns)
    overall_rr = pct(replies_total, sent_total)
    overall_br = pct(bounces_total, sent_total)

    camps_low_reply = sum(1 for r in campaigns if truthy(r.get("flag_low_reply")))
    camps_high_bounce = sum(1 for r in campaigns if truthy(r.get("flag_high_bounce")))
    doms_low_reply = sum(1 for r in domains if truthy(r.get("flag_low_reply")))
    doms_high_bounce = sum(1 for r in domains if truthy(r.get("flag_high_bounce")))

    lines = []
    lines.append(f"- {n_inboxes} inboxes audited across {n_domains} domains")
    lines.append(f"- {blocked} inboxes blocked, {smtp_fail} SMTP fail, {imap_fail} IMAP fail, "
                 f"{low_rep} below 80% warmup reputation")
    if auth_rows:
        lines.append(f"- DNS: {missing_spf} missing SPF, {missing_dkim} missing DKIM, "
                     f"{missing_dmarc} missing DMARC, {dmarc_none} with DMARC p=none")
    if campaigns:
        lines.append(f"- Fleet performance (last {lookback_days}d):")
        lines.append(f"    Sent (across active campaigns):  {sent_total:,}")
        lines.append(f"    Replies:                         {replies_total:,}")
        verdict_rr = "PASS — above 1% threshold" if overall_rr >= 1.0 and sent_total >= 200 \
            else ("BELOW 1% — flagged" if sent_total >= 200 else "below 1% rule sample size")
        lines.append(f"    Overall reply rate:              {overall_rr}% ({verdict_rr})")
        lines.append(f"    Bounces:                         {bounces_total:,}")
        verdict_br = "PASS — below 2%" if overall_br < 2.0 \
            else ("YELLOW — 2-3% range" if overall_br < 3.0 else "RED — above 3%")
        lines.append(f"    Bounce rate:                     {overall_br}% ({verdict_br})")
        lines.append(f"- {camps_low_reply} campaigns failed the 1% reply rule "
                     f"({camps_high_bounce} also high bounce)")
        lines.append(f"- {doms_low_reply} domains failed the 1% reply rule "
                     f"({doms_high_bounce} also high bounce)")
    if spam_test:
        status = spam_test.get("status") or "—"
        if status == "API_NOT_ACCESSIBLE":
            lines.append(f"- Spam placement: API not available on this tier — run via dashboard")
        else:
            lines.append(f"- Spam placement: status={status} (see spam-test.json for breakdown)")
    return "\n".join(lines)


def build_critical(inboxes, auth_rows, campaigns, domains):
    items = []
    # Blocked inboxes
    blocked = [r for r in inboxes if truthy(r.get("flag_blocked"))]
    if blocked:
        items.append(f"**{len(blocked)} inboxes blocked.** Rotate out of campaigns immediately. "
                     f"First 5: " + ", ".join(r.get("email", "") for r in blocked[:5]))
    # Missing DKIM on actively-sending domains
    actively_sending_domains = {r["domain"]: int(r.get("sent_attributed") or 0)
                                for r in domains if int(r.get("sent_attributed") or 0) > 0}
    missing_dkim = [r for r in auth_rows
                    if not truthy(r.get("dkim_present"))
                    and r.get("domain") in actively_sending_domains]
    if missing_dkim:
        # Sort by sent volume descending
        missing_dkim.sort(key=lambda r: -actively_sending_domains.get(r.get("domain"), 0))
        names = ", ".join(r["domain"] for r in missing_dkim[:5])
        items.append(f"**{len(missing_dkim)} actively-sending domains missing DKIM.** "
                     f"Top 5 by send volume: {names}. Fix at the email provider.")
    # Missing DMARC on actively-sending domains
    missing_dmarc = [r for r in auth_rows
                     if not truthy(r.get("dmarc_present"))
                     and r.get("domain") in actively_sending_domains]
    if missing_dmarc:
        names = ", ".join(r["domain"] for r in missing_dmarc[:5])
        items.append(f"**{len(missing_dmarc)} actively-sending domains missing DMARC.** "
                     f"Top 5: {names}. Add `v=DMARC1; p=none; rua=mailto:dmarc@<domain>` to start.")
    # Campaigns failing the 1% rule
    fail_camps = [r for r in campaigns if truthy(r.get("flag_low_reply"))]
    if fail_camps:
        fail_camps.sort(key=lambda r: -int(r.get("sent") or 0))
        sub = []
        for c in fail_camps[:5]:
            sub.append(f"- **{c.get('name') or c.get('campaign_id')}** "
                       f"(id {c.get('campaign_id')}): {int(c.get('sent') or 0):,} sent, "
                       f"{int(c.get('replies') or 0)} replies "
                       f"({fmt_pct(c.get('reply_rate_pct'))})")
        items.append(f"**{len(fail_camps)} campaigns failed the 1% reply rule** "
                     f"(sent ≥200, reply rate <1%). Top 5 by volume:\n" + "\n".join(sub))
    # Domains failing the 1% rule
    fail_doms = [r for r in domains if truthy(r.get("flag_low_reply"))]
    if fail_doms:
        fail_doms.sort(key=lambda r: -int(r.get("sent_attributed") or 0))
        sub = []
        for d in fail_doms[:5]:
            sub.append(f"- **{d.get('domain')}**: ~{int(d.get('sent_attributed') or 0):,} "
                       f"sent attributed, {int(d.get('replies_attributed') or 0)} replies "
                       f"({fmt_pct(d.get('reply_rate_pct'))})")
        items.append(f"**{len(fail_doms)} domains failed the 1% reply rule.** Top 5:\n"
                     + "\n".join(sub))
    if not items:
        return "_No critical issues detected._"
    return "\n\n".join(f"{i+1}. {item}" for i, item in enumerate(items))


def build_warnings(inboxes, auth_rows, campaigns, domains):
    items = []
    low_rep = [r for r in inboxes if truthy(r.get("flag_low_reputation"))]
    if low_rep:
        items.append(f"{len(low_rep)} inboxes below 80% warmup reputation. "
                     f"Don't use for critical sends until they recover.")
    smtp_fail = [r for r in inboxes if truthy(r.get("flag_smtp_fail"))]
    imap_fail = [r for r in inboxes if truthy(r.get("flag_imap_fail"))]
    if smtp_fail:
        items.append(f"{len(smtp_fail)} inboxes failing SMTP. Re-check credentials.")
    if imap_fail:
        items.append(f"{len(imap_fail)} inboxes failing IMAP — replies won't sync to Smartlead.")
    dmarc_none = [r for r in auth_rows if (r.get("dmarc_policy") or "").lower() == "none"]
    if dmarc_none:
        items.append(f"{len(dmarc_none)} domains have DMARC `p=none` (no enforcement). "
                     f"After 2 weeks of clean `rua=` reports, tighten to `p=quarantine`.")
    no_spf_strict = [r for r in auth_rows
                     if truthy(r.get("spf_present")) and not truthy(r.get("spf_strict"))]
    if no_spf_strict:
        items.append(f"{len(no_spf_strict)} domains have SPF but not strict "
                     f"(no `~all` / `-all`). Tighten to soft-fail or hard-fail.")
    fail_doms_bounce = [r for r in domains if truthy(r.get("flag_high_bounce"))]
    if fail_doms_bounce:
        names = ", ".join(r.get("domain") for r in fail_doms_bounce[:5])
        items.append(f"{len(fail_doms_bounce)} domains have bounce rate >3%. "
                     f"Top 5: {names}. Verify lead lists before next batch.")
    if not items:
        return "_No warnings._"
    return "\n".join(f"- {item}" for item in items)


def build_action_items(critical, warnings):
    actions = []
    if "blocked" in critical.lower():
        actions.append("**[HIGH]** Rotate out blocked inboxes; tag them `retired` in Smartlead UI")
    if "missing DKIM" in critical:
        actions.append("**[HIGH]** Add missing DKIM records at `default._domainkey.<domain>` "
                       "(or your provider's selector)")
    if "missing DMARC" in critical:
        actions.append("**[HIGH]** Add DMARC records: start with "
                       "`v=DMARC1; p=none; rua=mailto:dmarc@<domain>`")
    if "1% reply rule" in critical:
        actions.append("**[MED]** Investigate flagged campaigns: copy review via `/lilly-qa`, "
                       "spam placement test, list quality check")
    if "p=none" in warnings:
        actions.append("**[MED]** Tighten DMARC to `p=quarantine` once `rua=` reports look clean")
    if "bounce rate >3" in warnings:
        actions.append("**[MED]** Verify lead lists via `lilly-email-verification` before "
                       "next batch import on high-bounce domains")
    if "warmup reputation" in warnings:
        actions.append("**[LOW]** Pause low-reputation inboxes from active campaigns; keep in warmup")
    if not actions:
        return "_No actions needed — fleet looks healthy._"
    return "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lookback-days", type=int, default=30,
                    help="Lookback window used in audit_performance (for the summary text)")
    args = ap.parse_args()

    inboxes = load_csv(os.path.join(args.audit_dir, "inboxes.csv"))
    auth = load_csv(os.path.join(args.audit_dir, "auth.csv"))
    campaigns = load_csv(os.path.join(args.audit_dir, "campaigns.csv"))
    domains = load_csv(os.path.join(args.audit_dir, "domains.csv"))
    spam_test = load_json(os.path.join(args.audit_dir, "spam-test.json"))

    if not inboxes:
        print(f"ERROR: inboxes.csv not found or empty at {args.audit_dir}/inboxes.csv",
              file=sys.stderr)
        sys.exit(1)

    today = dt.date.today().isoformat()
    lines = []
    lines.append(f"# Deliverability Audit — {today}")
    lines.append("")
    lines.append("Generated by `email-deliverability-audit` skill. Apply the 1% rule: any "
                 "domain or campaign that has sent ≥200 emails and is replying at <1% is broken.")
    lines.append(section("Summary"))
    lines.append(build_summary(inboxes, auth, campaigns, domains, spam_test, args.lookback_days))

    lines.append(section("Critical issues (fix within 24h)"))
    crit = build_critical(inboxes, auth, campaigns, domains)
    lines.append(crit)

    lines.append(section("Warnings (fix within 1 week)"))
    warn = build_warnings(inboxes, auth, campaigns, domains)
    lines.append(warn)

    lines.append(section("Action items (prioritized)"))
    lines.append(build_action_items(crit, warn))

    if spam_test:
        lines.append(section("Spam placement test"))
        if spam_test.get("status") == "API_NOT_ACCESSIBLE":
            lines.append(f"Smart Delivery isn't exposed via API on this Smartlead tier.")
            lines.append(f"Run from the dashboard: <{spam_test.get('dashboard_url')}>")
        else:
            lines.append("```json")
            lines.append(json.dumps(spam_test, indent=2)[:2000])
            lines.append("```")

    lines.append(section("Source files"))
    lines.append(f"- `{args.audit_dir}/inboxes.csv` — {len(inboxes)} rows")
    if auth:
        lines.append(f"- `{args.audit_dir}/auth.csv` — {len(auth)} rows")
    if campaigns:
        lines.append(f"- `{args.audit_dir}/campaigns.csv` — {len(campaigns)} rows")
    if domains:
        lines.append(f"- `{args.audit_dir}/domains.csv` — {len(domains)} rows")
    if spam_test:
        lines.append(f"- `{args.audit_dir}/spam-test.json`")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[generate_report] Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
