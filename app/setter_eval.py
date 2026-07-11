"""Corpus eval for the Setter pipeline's classifier + decision gate.

NETWORK: hits real Supabase (read-only) and real OpenAI. The orchestrator runs
this script - lane C only writes and py_compiles it (per the build spec, this
file is dry-checked for correct SQL/PostgREST query shapes against the
`replies` schema, not executed here).

Usage:
    python3 setter_eval.py --n 120 --out eval_report.json
    python3 setter_eval.py --n 120 --out eval_report.json --drafts 20

What it measures: classify() + decide() ONLY (no Smartlead hydration, no real
Calendly call, no draft unless --drafts is given) against a stratified sample
of real replies pulled from Supabase's `replies` table:
  - hard negatives : category in (Not Interested, Do Not Contact, Out Of
                     Office, Wrong Person, Sender Originated Bounce)
  - positives      : category in (Interested, Information Request,
                     [Manual] Send resource), reply_body under 400 chars
  - meeting_request: category in (Meeting Request, Call Booked)
  - loom_video     : reply_body mentions "loom" or "video" (any category)

A synthetic autopilot agent is used for scoring: allowed_intents = every
intent the pipeline can ever auto-answer (send_resource, pricing,
scheduling), confidence_threshold 0.9, non-empty pricing_notes (so pricing
questions are exercised rather than trivially vetoed), slots stubbed to
slot_status "ok" with two dummy times, timezone stubbed to Europe/London, and
- per the spec - the CATEGORY VETO IS DISABLED for scoring (ctx["category"]
is always None here) so the report measures the classifier + decide() gate on
their own merits, not Smartlead's own categoriser agreeing with them.

Report (written to --out):
  {
    "generated_at": iso timestamp,
    "n_requested": int, "n_sampled": int,
    "agent": {... the synthetic scoring agent ...},
    "buckets": {bucket_name: {"n", "auto_count", "auto_rate", "mean_confidence"}},
    "hard_negative_auto_count": int,   # MUST be 0
    "bespoke_auto_count": int,         # MUST be 0 (bespoke_request is never in allowed_intents)
    "positive_simple_ask_auto_rate": float|null,
    "mean_confidence_overall": float|null,
    "disagreements": [ {bucket, primary_intent, decision, confidence, reason, body_snippet} ],
    "draft_samples": [ {reply_body, category, draft_subject, draft_html, lint_ok, lint_reason} ]  # only with --drafts
  }
"""

import argparse
import datetime as dt
import json
import os
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402

WORKSPACE = "navreo"

HARD_NEGATIVE_CATEGORIES = [
    "Not Interested", "Do Not Contact", "Out Of Office", "Wrong Person", "Sender Originated Bounce",
]
POSITIVE_CATEGORIES = ["Interested", "Information Request", "[Manual] Send resource"]
MEETING_CATEGORIES = ["Meeting Request", "Call Booked"]
POSITIVE_BODY_LEN_CAP = 400

BUCKET_ORDER = ["hard_negative", "positive", "meeting_request", "loom_video"]


# ── keys + tiny Supabase/OpenAI clients (self-contained, no import of server.py) ──

def load_keys() -> dict:
    """Mirrors server.py's load_keys(): env-first, ~/.navreo-keys.env fallback.
    Deliberately reimplemented here rather than importing server.py, per spec
    ("Reads keys via setter.configure-style loading of ~/.navreo-keys.env")."""
    keys = {}
    env_file = Path.home() / ".navreo-keys.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        if v:
            keys[k] = v
    return keys


def http_json(method: str, url: str, headers: dict, body: dict = None, timeout: float = 60):
    """Minimal stdlib HTTP JSON client matching server.py's http_json() shape,
    reimplemented locally so this eval script has zero dependency on server.py."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "navreo-setter-eval/1.0", "Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        import certifi, ssl  # same trust store server.py uses (macOS python lacks system certs)
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return {"error": json.loads(raw)}
        except Exception:  # noqa: BLE001
            return {"error": raw.decode(errors="replace")}


def make_sb(keys: dict):
    url = keys.get("SUPABASE_URL")
    key = keys.get("SUPABASE_SERVICE_ROLE_KEY")

    def sb(method: str, path: str, body=None, prefer: str = ""):
        if not url or not key:
            return None
        return http_json(method, f"{url}/rest/v1/{path}",
                         {"apikey": key, "Authorization": f"Bearer {key}",
                          "Prefer": prefer or "return=minimal"}, body)
    return sb


def _pg_in_filter(values):
    """Build a PostgREST `in.(...)` filter value for string values that may
    contain spaces (our category names do, e.g. "Not Interested"). Each value
    is double-quoted per PostgREST's own quoting rule for values containing
    reserved/space characters, then the whole filter value is percent-encoded
    for safe embedding in a query string, keeping the operator's own
    parens/commas/quotes/periods unescaped (safe=...) since those characters
    are PostgREST filter syntax, not data."""
    quoted = ",".join('"' + v.replace('"', '\\"') + '"' for v in values)
    return quote(f"in.({quoted})", safe='(),."')


def _pg_or_ilike(column: str, needles: list):
    """Build a PostgREST `or=(...)` filter matching column ILIKE any of the
    given substrings, e.g. reply_body mentions "loom" or "video"."""
    parts = ",".join(f"{column}.ilike.*{n}*" for n in needles)
    return quote(f"({parts})", safe="(),.*")


REPLIES_SELECT = "id,workspace,smartlead_campaign_id,email,replied_at,category,reply_subject,reply_body,smartlead_message_id"


def fetch_bucket(sb, category_values=None, ilike_needles=None, limit=200, offset=0):
    """One Supabase GET against `replies`, dry-checked shape (spec's schema:
    workspace, smartlead_campaign_id, email, replied_at, category,
    reply_subject, reply_body, smartlead_message_id - see db/schema.sql)."""
    filt = f"replies?workspace=eq.{WORKSPACE}&select={REPLIES_SELECT}&order=replied_at.desc&limit={limit}"
    if offset:
        filt += f"&offset={offset}"
    if category_values:
        filt += f"&category={_pg_in_filter(category_values)}"
    if ilike_needles:
        filt += f"&or={_pg_or_ilike('reply_body', ilike_needles)}"
    rows = sb("GET", filt)
    return rows if isinstance(rows, list) else []


def sample_corpus(sb, n_total: int, offset_rows: int = 0, pos_offset: int = None):
    """Stratified pull: roughly even split across the four buckets, then
    trimmed/filtered to the requested totals. Over-fetches the positive
    bucket because the <400-char filter is applied client-side (PostgREST has
    no plain `length(col) < n` filter operator without a custom RPC).

    offset_rows: skip this many rows per bucket, scaled by each bucket's
    over-fetch factor, so a holdout run (--offset <round-1 per-bucket n>)
    samples rows fully disjoint from the earlier run's raw fetches."""
    per_bucket = max(1, n_total // len(BUCKET_ORDER))
    buckets = {}

    hard_neg = fetch_bucket(sb, category_values=HARD_NEGATIVE_CATEGORIES,
                            limit=per_bucket * 2, offset=offset_rows * 2)
    buckets["hard_negative"] = hard_neg[:per_bucket]

    positive_raw = fetch_bucket(sb, category_values=POSITIVE_CATEGORIES,
                                limit=per_bucket * 24)
    positive_short = [r for r in positive_raw if len(r.get("reply_body") or "") < POSITIVE_BODY_LEN_CAP]
    # holdout freshness for positives is taken in FILTERED space (skip the
    # short-positives an earlier run consumed), because raw-space offsets
    # exhaust the short-positive supply far too fast. --pos-offset decouples
    # the positive slice from the other buckets' raw offset.
    p_off = offset_rows if pos_offset is None else pos_offset
    buckets["positive"] = positive_short[p_off:p_off + per_bucket]

    meeting = fetch_bucket(sb, category_values=MEETING_CATEGORIES,
                           limit=per_bucket * 2, offset=offset_rows * 2)
    buckets["meeting_request"] = meeting[:per_bucket]

    loom_video = fetch_bucket(sb, ilike_needles=["loom", "video"],
                              limit=per_bucket * 2, offset=offset_rows * 2)
    buckets["loom_video"] = loom_video[:per_bucket]

    return buckets


# ── synthetic scoring agent + stubbed ctx ───────────────────────────────────

def scoring_agent() -> dict:
    # Realistic config: an earlier judging round tanked every draft because the
    # placeholder resource_name ("Sample resource ... eval scoring only") leaked
    # into customer-facing anchor text - the drafter USES these fields verbatim,
    # so the eval agent must look like a production agent.
    return {
        "id": "agent-eval0000", "name": "Eval scoring agent", "enabled": True, "mode": "autopilot",
        "campaign_ids": [], "resource_name": "The Ultimate Claude Code Guide for Sales Leaders",
        "resource_link": "https://navreo.notion.site/The-Ultimate-Claude-Code-Guide-for-Sales-Leaders-Run-your-GTM-inside-of-Claude-36a6e75598d98047b5ecd20c2c6e1280",
        "resource_description": "A written breakdown of how Navreo moved its GTM from Clay into Claude Code. The fixed asset for anyone asking for more information, the guide, or the breakdown.",
        # the REAL house pricing block - draft judges cross-reference the
        # human-sent replies, so a fictional price reads as a fabrication
        "pricing_notes": ("Our pay-per-lead pricing has two parts:\n"
                          "1. Setup and infrastructure: $1,000 (at cost). This covers everything needed to run "
                          "your campaigns: Enterprise Microsoft (Azure) mailboxes plus Gmail mailboxes giving you "
                          "up to 50,000 sends per month, email enrichment, verification of that data, and "
                          "personalisation plus intent/signal data. All billed at cost, no markup.\n"
                          "2. Performance: $300 per qualified meeting attended. You only pay when a genuinely "
                          "qualified prospect actually shows up to the meeting."),
        "allowed_intents": ["send_resource", "pricing", "scheduling"],
        "confidence_threshold": 0.9,
        "booking_link": "https://www.navreo.ai/book-a-call",
        "calendly_event_url": "https://calendly.com/navreo/book-a-call-with-us-clone-2",
        "voice_examples": [
            "Hi Nick, Here is a breakdown I prepared. Would you be free for a call on Thursday, 9th July at 11:00 AM MDT or Friday, 10th July at 11:30 AM, where I could share how I can implement our strategy for you? If those times are not suitable, feel free to book a call here. Bjion",
        ],
        "extra_instructions": "",
    }


STUB_SLOTS = [
    {"iso": "2026-07-15T12:00:00+02:00", "label": "Wednesday, 15th July at 12:00 PM CEST",
     "link": "https://calendly.com/navreo/book-a-call-with-us-clone-2/2026-07-15T12:00:00+02:00"
             "?name=Test%20Lead&email=test%40example.com"},
    {"iso": "2026-07-16T11:00:00+02:00", "label": "Thursday, 16th July at 11:00 AM CEST",
     "link": "https://calendly.com/navreo/book-a-call-with-us-clone-2/2026-07-16T11:00:00+02:00"
             "?name=Test%20Lead&email=test%40example.com"},
]


def score_one(row: dict, agent: dict):
    body = setter.clean_body(row.get("reply_body") or "")  # mirror the pipeline's HTML strip
    reply = {"subject": row.get("reply_subject") or "", "body": body}
    try:
        classification = setter.classify(reply, agent)
    except Exception as e:  # noqa: BLE001 - one bad LLM call must never kill the corpus run
        classification = {"primary_intent": None, "all_intents": [], "simple_ask": False, "confidence": 0.0,
                          "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0, "wants": "",
                          "rationale": f"classify failed: {type(e).__name__}"}
    ctx = {
        "red_flag_hits": setter.lexicon_hits(body),
        "category": None,  # category veto disabled for scoring, per spec
        "first_touch": True,
        "slot_status": "ok",
        "timezone": "Europe/London",
        "lint_ok": True, "lint_reason": "",
        "body_len": len(body),
        "hydrated": True,
        # the eval measures the classifier + gate, so the master switch (which
        # ships OFF in production) is stubbed ON here
        "autopilot_enabled": True,
    }
    decision, reason = setter.decide(classification, agent, ctx)
    return classification, decision, reason


def run_eval(n_total: int, drafts_n: int, offset_rows: int = 0, pos_offset: int = None):
    keys = load_keys()
    sb = make_sb(keys)
    setter.configure(sb=sb, http_json=http_json, keys=keys, log_activity=lambda *a, **k: None)
    agent = scoring_agent()

    buckets_raw = sample_corpus(sb, n_total, offset_rows=offset_rows, pos_offset=pos_offset)
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_requested": n_total, "n_sampled": sum(len(v) for v in buckets_raw.values()),
        "offset_rows": offset_rows,
        "agent": agent, "buckets": {}, "disagreements": [], "rows": [],
    }

    all_confidences = []
    hard_negative_auto_count = 0
    bespoke_auto_count = 0
    positive_simple_asks = 0
    positive_simple_auto = 0

    for bucket_name in BUCKET_ORDER:
        rows = buckets_raw.get(bucket_name) or []
        n = len(rows)
        auto_count = 0
        confidences = []
        for row in rows:
            classification, decision, reason = score_one(row, agent)
            conf = float(classification.get("confidence") or 0)
            confidences.append(conf)
            all_confidences.append(conf)
            is_auto = decision == "auto_send"
            if is_auto:
                auto_count += 1

            report["rows"].append({
                "bucket": bucket_name, "category": row.get("category"),
                "body_snippet": (row.get("reply_body") or "")[:350],
                "primary_intent": classification.get("primary_intent"),
                "all_intents": classification.get("all_intents"),
                "simple_ask": bool(classification.get("simple_ask")),
                "confidence": conf, "decision": decision, "reason": reason,
                "wants": classification.get("wants"),
            })

            if bucket_name == "hard_negative" and is_auto:
                hard_negative_auto_count += 1
                report["disagreements"].append({
                    "bucket": bucket_name, "primary_intent": classification.get("primary_intent"),
                    "decision": decision, "confidence": conf, "reason": reason,
                    "body_snippet": (row.get("reply_body") or "")[:200],
                })
            if classification.get("primary_intent") == "bespoke_request" and is_auto:
                bespoke_auto_count += 1
                report["disagreements"].append({
                    "bucket": bucket_name, "primary_intent": "bespoke_request",
                    "decision": decision, "confidence": conf, "reason": reason,
                    "body_snippet": (row.get("reply_body") or "")[:200],
                })
            if bucket_name == "positive" and classification.get("simple_ask"):
                positive_simple_asks += 1
                if is_auto:
                    positive_simple_auto += 1

        report["buckets"][bucket_name] = {
            "n": n, "auto_count": auto_count,
            "auto_rate": round(auto_count / n, 3) if n else None,
            "mean_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        }

    report["hard_negative_auto_count"] = hard_negative_auto_count
    report["bespoke_auto_count"] = bespoke_auto_count
    report["positive_simple_ask_auto_rate"] = (
        round(positive_simple_auto / positive_simple_asks, 3) if positive_simple_asks else None
    )
    report["mean_confidence_overall"] = (
        round(sum(all_confidences) / len(all_confidences), 3) if all_confidences else None
    )

    if drafts_n:
        positive_rows = buckets_raw.get("positive") or []
        sample_rows = positive_rows if len(positive_rows) <= drafts_n else random.sample(positive_rows, drafts_n)
        draft_samples = []
        for row in sample_rows:
            body = setter.clean_body(row.get("reply_body") or "")  # mirror the pipeline's HTML strip
            reply = {"first_name": "there", "subject": row.get("reply_subject") or "", "body": body}
            try:
                classification = setter.classify({"subject": reply["subject"], "body": body}, agent)
            except Exception as e:  # noqa: BLE001
                classification = {"primary_intent": "send_resource", "all_intents": ["send_resource"],
                                  "wants": "", "rationale": f"classify failed: {type(e).__name__}"}
            # mirror production: clear negatives never get a draft
            if classification.get("primary_intent") in setter.CLEAR_NEGATIVE_INTENTS:
                continue
            try:
                d = setter.draft_reply(reply, agent, classification, STUB_SLOTS, "ok", sender_first="Sam")
            except Exception as e:  # noqa: BLE001
                d = {"subject": "", "html": ""}
            lint_ctx = {
                "subject": d.get("subject"), "first_name": reply["first_name"],
                "needs_resource_link": "send_resource" in (classification.get("all_intents") or []),
                "resource_link": agent.get("resource_link") or "", "slot_status": "ok",
                "slot_links": [s["link"] for s in STUB_SLOTS], "slot_labels": [s["label"] for s in STUB_SLOTS],
                "pricing_notes": agent.get("pricing_notes") or "", "thread_text": body,
            }
            lint_ok, lint_reason = setter.lint_draft(d.get("html") or "", lint_ctx)
            draft_samples.append({
                "reply_body": body, "category": row.get("category"),
                "primary_intent": classification.get("primary_intent"),
                "simple_ask": bool(classification.get("simple_ask")),
                "draft_subject": d.get("subject"), "draft_html": d.get("html"),
                "lint_ok": lint_ok, "lint_reason": lint_reason,
            })
        report["draft_samples"] = draft_samples

    return report


def main():
    ap = argparse.ArgumentParser(description="Setter classifier + decide() corpus eval (real network).")
    ap.add_argument("--n", type=int, default=120, help="total replies to sample across the four buckets")
    ap.add_argument("--out", type=str, default="eval_report.json", help="output JSON report path")
    ap.add_argument("--drafts", type=int, default=0, help="also generate this many draft samples from the positive bucket")
    ap.add_argument("--offset", type=int, default=0,
                    help="skip this many rows per bucket (scaled by over-fetch factor) - use the earlier run's per-bucket n for a disjoint holdout sample")
    ap.add_argument("--pos-offset", type=int, default=None,
                    help="positive-bucket skip in FILTERED space, decoupled from --offset")
    args = ap.parse_args()

    report = run_eval(args.n, args.drafts, offset_rows=args.offset, pos_offset=args.pos_offset)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Sampled {report['n_sampled']} replies (requested {args.n}).")
    for name, b in report["buckets"].items():
        print(f"  {name}: n={b['n']} auto_rate={b['auto_rate']} mean_confidence={b['mean_confidence']}")
    print(f"hard_negative_auto_count={report['hard_negative_auto_count']} (must be 0)")
    print(f"bespoke_auto_count={report['bespoke_auto_count']} (must be 0)")
    print(f"positive_simple_ask_auto_rate={report['positive_simple_ask_auto_rate']}")
    print(f"mean_confidence_overall={report['mean_confidence_overall']}")
    print(f"disagreements: {len(report['disagreements'])}")
    if args.drafts:
        print(f"draft_samples: {len(report.get('draft_samples') or [])}")
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
