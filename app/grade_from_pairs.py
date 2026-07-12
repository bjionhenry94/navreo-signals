"""Fast grading-case builder: real reply + real first email, both straight
from Supabase (no live Smartlead calls). Pairs each recent inbound reply with
the earliest outbound we archived for that lead (sent_messages), then runs the
REAL pipeline (classify -> tz -> slots -> draft -> decide) over the pair, with
the LLM calls parallelised. Every stored case is guaranteed to have a first
email. Nothing sends anything.

Usage: python3 grade_from_pairs.py [--target N]
"""

import datetime
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import certifi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
UA = "navreo-prototype/1.0 (curl-compatible)"
TARGET = 50
for a in sys.argv:
    if a.startswith("--target="):
        TARGET = int(a.split("=", 1)[1])


def load_keys():
    keys = {}
    env = Path.home() / ".navreo-keys.env"
    for line in env.read_text().splitlines() if env.exists() else []:
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
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < 3:
                continue
            try:
                return {"error": json.loads(e.read())}
            except Exception:  # noqa: BLE001
                return {"error": f"http {e.code}"}


KEYS = load_keys()
URL, SRK = KEYS["SUPABASE_URL"], KEYS["SUPABASE_SERVICE_ROLE_KEY"]


def sb(method, path, body=None, prefer=""):
    h = {"apikey": SRK, "Authorization": f"Bearer {SRK}"}
    if prefer:
        h["Prefer"] = prefer
    return http_json(method, f"{URL}/rest/v1/{path}", h, body)


def rest_get(table, query):
    return sb("GET", f"{table}?{query}")


BUCKETS = {
    "positive": '("Interested","Information Request","[Manual] Send resource")',
    "meeting": '("Meeting Request","Call Booked")',
    "negative": '("Not Interested","Do Not Contact","Out Of Office","Wrong Person")',
}


def build_pairs():
    # Only replies to Navreo's OWN outreach (which pitches the same Clay->Claude
    # offer this agent handles) - so the first email, the reply, and the agent's
    # drafted offer all cohere. Client campaigns (Amplifyy Amazon etc.) would
    # make the draft offer the wrong thing.
    camps = rest_get("campaigns", "select=smartlead_campaign_id&workspace=eq.navreo"
                                  "&or=(name.ilike.*navreo*,name.ilike.*clay*)")
    allowed = [str(c["smartlead_campaign_id"]) for c in (camps or []) if c.get("smartlead_campaign_id")]
    cfilter = ("&smartlead_campaign_id=in.(" + ",".join(allowed) + ")") if allowed else ""

    reps = []
    for name, cats in BUCKETS.items():
        want = {"positive": 22, "meeting": 13, "negative": 13}[name]
        rows = rest_get("replies", "select=email,smartlead_campaign_id,category,reply_subject,reply_body,replied_at"
                                   f"&workspace=eq.navreo&category=in.{cats.replace(' ', '%20')}{cfilter}"
                                   "&order=replied_at.desc&limit=" + str(want * 4))
        rows = [r for r in (rows or []) if 5 <= len(r.get("reply_body") or "") <= 400][:want * 3]
        for r in rows:
            r["bucket"] = name
        reps += rows
    # loom/video within Navreo's own outreach
    lv = rest_get("replies", "select=email,smartlead_campaign_id,category,reply_subject,reply_body,replied_at"
                             f"&workspace=eq.navreo&reply_body=ilike.*video*{cfilter}&order=replied_at.desc&limit=40")
    for r in (lv or [])[:16]:
        r["bucket"] = "loom_video"
        reps.append(r)

    emails = sorted({(r.get("email") or "").lower() for r in reps if r.get("email")})
    first_by = {}
    for i in range(0, len(emails), 40):
        chunk = emails[i:i + 40]
        inlist = ",".join('"' + e.replace('"', '') + '"' for e in chunk)
        sm = rest_get("sent_messages", "select=email,smartlead_campaign_id,body,sent_at,is_manual_reply,sent_at"
                                       f"&workspace=eq.navreo&email=in.({inlist})&order=sent_at.asc")
        for m in (sm or []):
            if m.get("is_manual_reply"):
                continue
            key = ((m.get("email") or "").lower(), m.get("smartlead_campaign_id"))
            if key in first_by:
                continue
            body = setter.clean_body(m.get("body") or "")
            if len(body) >= 80:
                first_by[key] = body[:1400]

    pairs = []
    seen = set()
    for r in reps:
        key = ((r.get("email") or "").lower(), r.get("smartlead_campaign_id"))
        fe = first_by.get(key)
        if not fe:
            continue
        dk = (key[0], (r.get("reply_body") or "")[:80])
        if dk in seen:
            continue
        seen.add(dk)
        r["first_email"] = fe
        pairs.append(r)
    # interleave buckets so a target cutoff keeps variety
    from collections import defaultdict
    byb = defaultdict(list)
    for p in pairs:
        byb[p["bucket"]].append(p)
    order = ["positive", "meeting", "negative", "loom_video"]
    out = []
    while any(byb[b] for b in order):
        for b in order:
            if byb[b]:
                out.append(byb[b].pop(0))
    return out


def process(row, agent, avail, slot_status0, now):
    email = (row.get("email") or "").strip().lower()
    body = setter.clean_body(row.get("reply_body") or "")
    fe = row.get("first_email") or ""
    domain = email.split("@", 1)[1] if "@" in email else ""
    try:
        cls = setter.classify({"subject": row.get("reply_subject") or "", "body": body,
                               "last_outbound": fe, "first_outbound": fe}, agent)
    except Exception as e:  # noqa: BLE001
        return None
    hints = {"phone": setter._extract_phone(body), "tld": ".".join(domain.split(".")[-2:]), "body": body}
    comp = setter._company_hints(domain)
    hints.update({k: comp.get(k) for k in ("country", "state", "city")})
    tz, _ = setter.guess_timezone(hints)
    if not tz and cls.get("timezone_guess") and float(cls.get("tz_confidence") or 0) >= 0.5:
        tz = cls.get("timezone_guess")
    eff = {"work_start": 9, "work_end": 17, "_agent": agent,
           "_lead": {"first_name": "", "last_name": "", "email": email}}
    slots = setter.pick_slots(avail, tz or "Europe/London", eff, now) if slot_status0 == "ok" else []
    st = slot_status0 if (slot_status0 != "ok" or slots) else "none_available"
    primary = cls.get("primary_intent")
    is_neg = primary in setter.CLEAR_NEGATIVE_INTENTS and float(cls.get("confidence") or 0) >= 0.8
    draft_html, lint_ok, lint_reason = None, False, "No draft was produced."
    if not is_neg:
        try:
            d = setter.draft_reply({"first_name": "", "subject": row.get("reply_subject") or "",
                                    "body": body, "first_outbound": fe}, agent, cls, slots, st, sender_first="Bjion")
            draft_html = d.get("html")
            lint_ok, lint_reason = setter.lint_draft(draft_html, {
                "subject": d.get("subject"), "first_name": "",
                "needs_resource_link": "send_resource" in (cls.get("all_intents") or []),
                "resource_link": agent.get("resource_link") or "", "slot_status": st,
                "slot_links": [s.get("link") for s in slots], "slot_labels": [s.get("label") for s in slots],
                "pricing_notes": setter._agent_instructions(agent), "thread_text": body})
        except Exception:  # noqa: BLE001
            pass
    ctx = {"red_flag_hits": setter.lexicon_hits(body), "category": row.get("category"), "first_touch": True,
           "slot_status": st, "timezone": tz, "lint_ok": lint_ok, "lint_reason": lint_reason,
           "body_len": len(body), "hydrated": True, "answered_since_reply": False, "autopilot_enabled": True,
           "same_day_ask": bool(setter._SAME_DAY_RE.search(setter._strip_quoted(body)))}
    decision, reason = setter.decide(cls, agent, ctx)
    return {
        "bucket": row.get("bucket"), "inbound": body[:1200], "lead_first_name": "",
        "company_domain": domain, "hydrated": True, "thread": [], "first_email": fe,
        "category": row.get("category"), "intent": primary, "confidence": cls.get("confidence"),
        "decision": decision, "reason": reason, "draft_html": draft_html,
        "would_auto": decision == "auto_send",
        "_ctx": {"category": row.get("category"), "timezone": tz, "slot_status": st, "body_len": len(body),
                 "same_day_ask": ctx["same_day_ask"], "subject": row.get("reply_subject") or "",
                 "last_outbound": fe, "first_outbound": fe},
    }


def main():
    setter.configure(sb=sb, http_json=http_json, keys=KEYS, log_activity=lambda *a, **k: None)
    agent = next(a for a in setter._load_agents() if a.get("id") == "agent-d403bbcd")
    agent = {**agent, "mode": "autopilot", "enabled": True}
    settings = setter._load_settings()
    now = datetime.datetime.now(datetime.timezone.utc)
    ss, avail, serr = setter.get_calendly_availability(agent, {**settings, "_agent": agent}, now)
    print(f"calendly: {ss} ({len(avail)} slots) {serr}")
    pairs = build_pairs()
    print(f"built {len(pairs)} real reply+first-email pairs; processing to target {TARGET}...")

    cases = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(lambda r: process(r, agent, avail, ss, now), pairs):
            if res and (res.get("first_email") or "").strip():
                cases.append(res)
            if len(cases) >= TARGET:
                break
    for j, c in enumerate(cases):
        c["id"] = f"case-{j:02d}"
    doc = {"cases": cases, "answers": {}, "agent_snapshot": agent, "feedback_log": [], "relearn": {"status": "idle"}}
    sb("POST", f"{setter.AGENTS_TABLE}?on_conflict=id", {"id": "__grading__", "doc": doc},
       prefer="resolution=merge-duplicates,return=minimal")
    n_auto = sum(1 for c in cases if c["would_auto"])
    from collections import Counter
    print(f"stored {len(cases)} cases ({n_auto} would auto-send) buckets={dict(Counter(c['bucket'] for c in cases))}")


if __name__ == "__main__":
    main()
