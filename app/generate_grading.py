"""One-off: build the __grading__ case set for setter-grade.html.

Runs the REAL pipeline pieces (clean_body -> classify -> tz -> live Calendly
slots -> draft -> decide) over a stratified JSON of real inbound replies and
stores the finished cases in the settings-table doc row id "__grading__".
Decisions are computed AS IF the master switch were ON and the agent in
autopilot, because the question being graded is "should this have auto-sent".
Nothing here sends anything anywhere.

Usage: python3 generate_grading.py <inbounds.json>
"""

import datetime
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import certifi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
UA = "navreo-prototype/1.0 (curl-compatible)"


def load_keys():
    keys = {}
    env = Path.home() / ".navreo-keys.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.strip().partition("=")
                keys[k.replace("export ", "").strip()] = v.strip().strip("\"'")
    for k, v in os.environ.items():
        if v and (k in keys or k.endswith(("_KEY", "_TOKEN", "_URL"))):
            keys[k] = v
    return keys


def http_json(method, url, headers, body=None, timeout=90):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": UA, "Content-Type": "application/json", **headers}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read())}
        except Exception:  # noqa: BLE001
            return {"error": f"http {e.code}"}


def main():
    append = "--append" in sys.argv
    inbounds = json.load(open(sys.argv[1]))
    keys = load_keys()
    url, srk = keys["SUPABASE_URL"], keys["SUPABASE_SERVICE_ROLE_KEY"]

    def sb(method, path, body=None, prefer=""):
        h = {"apikey": srk, "Authorization": f"Bearer {srk}"}
        if prefer:
            h["Prefer"] = prefer
        return http_json(method, f"{url}/rest/v1/{path}", h, body)

    setter.configure(sb=sb, http_json=http_json, keys=keys, log_activity=lambda *a, **k: None)
    agents = setter._load_agents()
    agent = next(a for a in agents if a.get("id") == "agent-d403bbcd")
    # The grading question is "should this have auto-sent", so decisions are
    # computed with the agent forced into autopilot regardless of its live
    # mode (the master switch is likewise forced on via ctx below).
    agent = {**agent, "mode": "autopilot", "enabled": True}
    settings = setter._load_settings()

    now = datetime.datetime.now(datetime.timezone.utc)
    eff = dict(settings)
    eff["_agent"] = agent
    slot_status, avail, serr = setter.get_calendly_availability(agent, eff, now)
    print(f"calendly: {slot_status} ({len(avail)} slots) {serr}")

    cases = []
    for i, row in enumerate(inbounds):
        body = setter.clean_body(row.get("reply_body") or "")
        email = row.get("email") or f"case{i}@example.com"
        first = ""
        try:
            cls = setter.classify({"subject": row.get("reply_subject") or "", "body": body, "last_outbound": ""}, agent)
        except Exception as e:  # noqa: BLE001
            print(f"  case {i}: classify failed {e}")
            continue
        domain = email.split("@", 1)[1] if "@" in email else ""
        hints = {"phone": setter._extract_phone(body), "tld": ".".join(domain.split(".")[-2:]), "body": body}
        comp = setter._company_hints(domain)
        hints.update({k: comp.get(k) for k in ("country", "state", "city")})
        tz, _ = setter.guess_timezone(hints)
        if not tz and cls.get("timezone_guess") and float(cls.get("tz_confidence") or 0) >= 0.5:
            tz = cls.get("timezone_guess")

        eff["_lead"] = {"first_name": first, "last_name": "", "email": email}
        slots = setter.pick_slots(avail, tz or "Europe/London", eff, now) if slot_status == "ok" else []
        st = slot_status if (slot_status != "ok" or slots) else "none_available"

        primary = cls.get("primary_intent")
        is_clear_neg = primary in setter.CLEAR_NEGATIVE_INTENTS and float(cls.get("confidence") or 0) >= 0.8
        draft_html = None
        lint_ok, lint_reason = False, "No draft was produced."
        if not is_clear_neg:
            try:
                d = setter.draft_reply({"first_name": first, "subject": row.get("reply_subject") or "", "body": body},
                                       agent, cls, slots, st, sender_first="Bjion")
                draft_html = d.get("html")
                lint_ok, lint_reason = setter.lint_draft(draft_html, {
                    "subject": d.get("subject"), "first_name": first,
                    "needs_resource_link": "send_resource" in (cls.get("all_intents") or []),
                    "resource_link": agent.get("resource_link") or "",
                    "slot_status": st, "slot_links": [s.get("link") for s in slots],
                    "slot_labels": [s.get("label") for s in slots],
                    "pricing_notes": setter._agent_instructions(agent), "thread_text": body,
                })
            except Exception as e:  # noqa: BLE001
                print(f"  case {i}: draft failed {e}")
        ctx = {
            "red_flag_hits": setter.lexicon_hits(body), "category": row.get("category"),
            "first_touch": True, "slot_status": st, "timezone": tz,
            "lint_ok": lint_ok, "lint_reason": lint_reason,
            "body_len": len(body), "hydrated": True,
            "answered_since_reply": False, "autopilot_enabled": True,
            "same_day_ask": bool(setter._SAME_DAY_RE.search(setter._strip_quoted(body))),
        }
        decision, reason = setter.decide(cls, agent, ctx)
        cases.append({
            "id": f"case-{i:02d}", "bucket": row.get("bucket"), "inbound": body[:1200],
            "category": row.get("category"), "intent": primary,
            "confidence": cls.get("confidence"), "decision": decision, "reason": reason,
            "draft_html": draft_html, "would_auto": decision == "auto_send",
        })
        print(f"  case {i:02d} [{row.get('bucket')}] -> {decision} ({primary})")

    if append:
        rows = sb("GET", f"{setter.AGENTS_TABLE}?id=eq.__grading__&select=doc")
        old = (rows[0]["doc"] if isinstance(rows, list) and rows else {}) or {}
        prior = old.get("cases") or []
        for j, c in enumerate(cases):
            c["id"] = f"case-{len(prior) + j:02d}"
        cases = prior + cases
        answers = old.get("answers") or {}
    else:
        answers = {}
    doc = {"cases": cases, "answers": answers}
    sb("POST", f"{setter.AGENTS_TABLE}?on_conflict=id", {"id": "__grading__", "doc": doc},
       prefer="resolution=merge-duplicates,return=minimal")
    n_auto = sum(1 for c in cases if c["would_auto"])
    print(f"stored {len(cases)} cases ({n_auto} would auto-send)")


if __name__ == "__main__":
    main()
