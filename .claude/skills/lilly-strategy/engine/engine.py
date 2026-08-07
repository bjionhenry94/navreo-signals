#!/usr/bin/env python3
"""lilly-strategy back-end engine — the deterministic machinery behind /lilly-strategy.

The session (LLM) does the CREATIVE work: idea names, offers, who-lines, pains,
angles, evidence sentences. This engine does everything that must be exact:

    retro     what worked / what died, from the Supabase campaign scorecard (free)
    probe     gross count for one idea from the provider named in its pull_spec
              (Prospeo /search-person|company = 1 cr · TheirStack preview = free
               · AI Ark count = ~1 cr) — page-1 counts only, never pulls
    net       the 30-day cooldown suppression router (free Supabase SQL):
              terminal / cooldown / free-from-records / new + net ratio
    validate  run.json schema + house rules (probe-confirmed numbers only,
              vector mixture, no audits, DM-only language)
    hydrate   splice run.json into wizard-template.html → the artifact file
    handoff   per-idea /lilly-tam brief rendered from the idea's pull_spec

Contract: run.json (schema in README.md next to this file). Keys load from
~/.navreo-keys.env automatically. All HTTP via curl subprocess (macOS Python
urllib fails SSL verification — house gotcha).

Usage:
    python3 engine.py retro --client navreo
    python3 engine.py probe --run run.json --idea exporters       # or --spec spec.json
    python3 engine.py net --client navreo --domains a.com,b.com [--emails ...]
    python3 engine.py validate --run run.json
    python3 engine.py hydrate --run run.json --out wizard-navreo.html
    python3 engine.py handoff --run run.json --idea exporters
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(ENGINE_DIR)
TEMPLATE = os.path.join(SKILL_DIR, "wizard-template.html")
sys.path.insert(0, os.path.join(os.path.dirname(SKILL_DIR), "_shared"))

KEYS_FILE = os.path.expanduser("~/.navreo-keys.env")
COOLDOWN_DAYS = 30
# lead categories that make a contact permanently off-limits (positive repliers
# + explicit do-not-contact). "Not Interested" is deliberately NOT terminal.
# contact_history stores BOTH names and numeric Smartlead category ids —
# 1=Interested 2=Meeting Request 3=Not Interested 4=Do Not Contact
# 5=Information Request 6=Out of Office 7=Wrong Person.
TERMINAL_CATEGORIES = {"interested", "meeting request", "meeting booked",
                       "call booked", "positive", "do not contact", "dnc",
                       "unsubscribed", "1", "2", "4"}
# news_intent DROPPED 2026-08-04 (Bjion) — news/funding/expansion is no longer a
# targeting vector; funding/hiring survive only as icebreaker angles (Phase 2b).
VECTORS = {"targeted_list", "hiring_signal", "engagement_signal", "events",
           "followers", "lookalike", "prospeo_signal",
           "recontact"}
PROBE_PROVIDERS = ("prospeo_person", "prospeo_company", "theirstack",
                   "aiark_people", "aiark_company")


def load_keys():
    if not os.path.exists(KEYS_FILE):
        return
    for line in open(KEYS_FILE, encoding="utf-8"):
        m = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


def curl_json(method, url, headers=None, body=None, timeout=60, retries=1):
    """HTTP via curl; parses JSON with strict=False (providers emit raw control chars)."""
    cmd = ["curl", "-sS", "-X", method, url, "-H", "Content-Type: application/json",
           "-H", "Accept: application/json"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if body is not None:
        cmd += ["--data-binary", json.dumps(body)]
    last = None
    for attempt in range(retries + 1):
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = p.stdout.strip()
        try:
            data = json.loads(out, strict=False)
        except Exception:
            last = RuntimeError(f"non-JSON response ({p.returncode}): {out[:300]}")
            time.sleep(2)
            continue
        if isinstance(data, dict) and str(data.get("error", "")).lower() in ("429", "rate_limit"):
            time.sleep(10)
            continue
        return data
    raise last or RuntimeError("curl failed")


def db():
    import navreo_db
    return navreo_db


def today():
    return dt.date.today().isoformat()


# ---------------------------------------------------------------- retro
def cmd_retro(args):
    """Campaign scorecard summary: totals, winners, dead list, in-flight."""
    rows = db().rest("GET", "/rest/v1/campaign_scorecard",
                     params={"select": "name,sent,positives,replied,status,smartlead_campaign_id,updated_at",
                             "limit": "2000"})
    rows = [r for r in rows if r.get("sent") is not None]
    # reply-subsequences share names across campaigns ("Meeting Request" ×258);
    # real campaigns are uniquely named — drop any name appearing 3+ times
    from collections import Counter
    name_counts = Counter((r.get("name") or "").strip().lower() for r in rows)
    subsequences = sum(1 for r in rows if name_counts[(r.get("name") or "").strip().lower()] >= 3)
    rows = [r for r in rows if name_counts[(r.get("name") or "").strip().lower()] < 3]
    total_sent = sum(r["sent"] or 0 for r in rows)
    total_pos = sum(r.get("positives") or 0 for r in rows)

    def rate(r):
        return (r.get("positives") or 0) / r["sent"] * 1000 if r["sent"] else 0.0

    readable = [r for r in rows if (r["sent"] or 0) >= 500]
    winners = sorted([r for r in readable if rate(r) >= 1.0], key=rate, reverse=True)
    dead = sorted([r for r in readable if (r["sent"] or 0) >= 1500 and rate(r) < 0.5],
                  key=lambda r: r["sent"], reverse=True)
    inflight = [r for r in rows if str(r.get("status", "")).upper() in
                ("ACTIVE", "START", "STARTED", "DRAFTED", "PAUSED") and (r["sent"] or 0) < 500]

    out = {
        "generated": today(),
        "totals": {"campaigns": len(rows), "sent": total_sent, "positives": total_pos,
                   "subsequence_rows_excluded": subsequences},
        "winners": [{"name": r["name"], "id": r["smartlead_campaign_id"], "sent": r["sent"],
                     "positives": r.get("positives"), "per_1k": round(rate(r), 2)} for r in winners[:20]],
        "dead": [{"name": r["name"], "id": r["smartlead_campaign_id"], "sent": r["sent"],
                  "positives": r.get("positives"), "per_1k": round(rate(r), 2)} for r in dead[:25]],
        "inflight_small": [{"name": r["name"], "id": r["smartlead_campaign_id"],
                            "sent": r["sent"], "status": r.get("status")} for r in inflight[:15]],
    }
    emit(out, args)


# ---------------------------------------------------------------- probe
def probe_prospeo(kind, filters):
    key = os.environ["PROSPEO_API_KEY"]
    ep = "search-person" if kind == "prospeo_person" else "search-company"
    data = curl_json("POST", f"https://api.prospeo.io/{ep}",
                     headers={"X-KEY": key}, body={"page": 1, "filters": filters})
    if data.get("error"):
        raise RuntimeError(f"prospeo {ep} error: {json.dumps(data)[:300]}")
    pag = data.get("pagination") or {}
    sample = data.get("results") or []
    # cache productive company rows + ledger (lilly-tam law: every paid page lands)
    n = db()
    for r in sample:
        comp = r.get("company") or (r if kind == "prospeo_company" else {})
        comp = comp.get("company", comp) if isinstance(comp, dict) else {}
        dom = n.canonical_domain((comp or {}).get("domain") or "")
        if dom:
            try:
                n.put_enrichment("company", dom, "prospeo", comp, endpoint=ep,
                                 source_skill="lilly-strategy-engine")
            except Exception:
                pass
    try:
        n.log_provider_usage("prospeo", 1, endpoint=ep, source_id="lilly-strategy-engine")
    except Exception:
        pass
    domains = []
    for r in sample:
        c = r.get("company") or {}
        c = c.get("company", c) if isinstance(c, dict) else {}
        d = (c or {}).get("domain")
        if d:
            domains.append(d)
    return {"provider": kind, "gross": pag.get("total_count"), "credits": 1,
            "sample_size": len(sample), "sample_domains": sorted(set(domains))}


def probe_theirstack(filters):
    key = os.environ["THEIRSTACK_API_KEY"]
    body = dict(filters)
    body.setdefault("posted_at_max_age_days", 30)
    body.update({"blur_company_data": True, "include_total_results": True, "limit": 10})
    data = curl_json("POST", "https://api.theirstack.com/v1/jobs/search",
                     headers={"Authorization": f"Bearer {key}"}, body=body)
    meta = data.get("metadata") or data
    return {"provider": "theirstack", "gross": meta.get("total_results"),
            "companies": meta.get("total_companies"), "credits": 0,
            "window_days": body["posted_at_max_age_days"]}


def probe_aiark(kind, filters):
    key = os.environ["AI_ARK_API_KEY"]
    ep = "people" if kind == "aiark_people" else "companies"
    body = {"page": 0, "size": 1}
    body.update(filters)
    data = curl_json("POST", f"https://api.ai-ark.com/api/developer-portal/v1/{ep}",
                     headers={"X-TOKEN": key}, body=body)
    total = data.get("totalElements")
    if total is None:
        raise RuntimeError(f"aiark {ep}: no totalElements in {json.dumps(data)[:300]}")
    try:
        db().log_provider_usage("ai_ark", 1, endpoint=ep, source_id="lilly-strategy-engine")
    except Exception:
        pass
    flag = " (round-10K reading — may be a display floor, flag it)" if total in (10000,) else ""
    return {"provider": kind, "gross": total, "credits": 1, "note": flag.strip() or None}


def cmd_probe(args):
    if args.run and args.idea:
        run = json.load(open(args.run, encoding="utf-8"))
        idea = next((i for i in run["ideas"] if i["id"] == args.idea), None)
        if not idea:
            sys.exit(f"idea '{args.idea}' not in {args.run}")
        spec = idea.get("pull_spec") or {}
    elif args.spec:
        spec = json.load(open(args.spec, encoding="utf-8"))
    else:
        sys.exit("probe needs --run + --idea, or --spec")
    provider, filters = spec.get("provider"), spec.get("filters") or {}
    if provider not in PROBE_PROVIDERS:
        sys.exit(f"pull_spec.provider must be one of {PROBE_PROVIDERS}, got {provider!r}")
    if provider.startswith("prospeo"):
        res = probe_prospeo(provider, filters)
    elif provider == "theirstack":
        res = probe_theirstack(filters)
    else:
        res = probe_aiark(provider, filters)
    res["date"] = today()
    emit(res, args)


# ---------------------------------------------------------------- net (cooldown router)
def cmd_net(args):
    n = db()
    domains = [n.canonical_domain(d) for d in (args.domains or "").split(",") if d.strip()]
    emails = [e.strip().lower() for e in (args.emails or "").split(",") if e.strip()]
    if not domains and not emails:
        sys.exit("net needs --domains and/or --emails")
    client = args.client
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=COOLDOWN_DAYS)).isoformat()

    hist = []
    for field, values in (("company_domain", domains), ("email", emails)):
        for i in range(0, len(values), 80):
            chunk = ",".join(f'"{v}"' for v in values[i:i + 80])
            hist += n.rest("GET", "/rest/v1/contact_history",
                           params={"select": "client_id,company_domain,email,first_contacted_at,last_event_at,lead_category,status",
                                   field: f"in.({chunk})", "limit": "5000"}) or []
    supp = []
    for field, values in (("domain", domains), ("email", emails)):
        for i in range(0, len(values), 80):
            chunk = ",".join(f'"{v}"' for v in values[i:i + 80])
            supp += n.rest("GET", "/rest/v1/suppressions",
                           params={"select": "client_id,domain,email",
                                   field: f"in.({chunk})", "limit": "5000"}) or []

    def keys_of(row):
        ks = set()
        if row.get("company_domain"):
            ks.add(("d", n.canonical_domain(row["company_domain"])))
        if row.get("domain"):
            ks.add(("d", n.canonical_domain(row["domain"])))
        if row.get("email"):
            ks.add(("e", row["email"].lower()))
        return ks

    suppressed = set()
    for row in supp:
        if row.get("client_id") in (client, None):
            suppressed |= keys_of(row)

    verdicts = {}
    candidates = [("d", d) for d in domains] + [("e", e) for e in emails]
    hist_by_key = {}
    for row in hist:
        for k in keys_of(row):
            hist_by_key.setdefault(k, []).append(row)

    for cand in candidates:
        rows = hist_by_key.get(cand, [])
        if cand in suppressed:
            verdicts[cand] = "terminal"
            continue
        verdict = "new" if not rows else "free_from_records"
        for row in rows:
            cat = (row.get("lead_category") or "").strip().lower()
            if cat in TERMINAL_CATEGORIES:
                verdict = "terminal"
                break
            last = row.get("last_event_at") or row.get("first_contacted_at") or ""
            if row.get("client_id") == client and last >= cutoff:
                verdict = "cooldown"
        verdicts[cand] = verdict

    counts = {v: 0 for v in ("terminal", "cooldown", "free_from_records", "new")}
    for v in verdicts.values():
        counts[v] += 1
    checked = len(candidates)
    reachable = counts["free_from_records"] + counts["new"]
    out = {
        "client": client, "checked": checked, "cooldown_days": COOLDOWN_DAYS,
        **counts,
        "net_ratio": round(reachable / checked, 3) if checked else None,
        "per_candidate": {f"{t}:{v}": verdicts[(t, v)] for (t, v) in candidates},
        "note": "terminal = suppression list or positive-replier category; cooldown = same-client contact within 30 days; free_from_records = older contact, data already ours (never re-purchase); new = paid pull.",
    }
    emit(out, args)


# ---------------------------------------------------------------- validate
IDEA_REQUIRED = ["id", "campaignNo", "name", "net", "gross", "emails", "who", "offer",
                 "caption", "tag", "shortTag", "firstName", "company", "pain", "moment",
                 "videoAngle", "why", "repliesLine", "vector", "probe", "pull_spec"]
PERSON_REQUIRED = ["first", "title", "company", "detail", "colleague", "lines"]


def _check_fixed_opener(i, iid, errors, expected):
    """Fixed-opener types: the recommended/first angle example is EXACTLY the fixed line
    (capital S included — Bjion correction 2026-08-03)."""
    angles = (i.get("icebreaker") or {}).get("angles") or []
    a = next((a for a in angles if a.get("recommended")), angles[0] if angles else None)
    got = (a or {}).get("example", "")
    if got != expected:
        errors.append(f"idea {iid}: fixed opener must be exactly {expected!r}, got {got!r}")


# merge tokens the BOARD resolves globally; anything else must come from the person
_KNOWN_TOKENS = {"first", "first_name", "company", "icebreaker", "colleague"}
_TOKEN_RE = re.compile(r"\{\{?([A-Za-z_][A-Za-z0-9_ ]*)\}?\}")

_NAVREO_VOICE = None  # cached module (False = tried and unavailable)


def _voice_module():
    """The house copy framework's runtime validator (navreo_voice.validate_email,
    the same code the Offer Maker ships with). Best-effort import from the repo."""
    global _NAVREO_VOICE
    if _NAVREO_VOICE is None:
        try:
            import os
            import importlib.util
            p = os.path.expanduser("~/navreo-signals/app/navreo_voice.py")
            spec = importlib.util.spec_from_file_location("navreo_voice", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _NAVREO_VOICE = mod
        except Exception:
            _NAVREO_VOICE = False
    return _NAVREO_VOICE


def _resolve_sample(text, i):
    """Resolve merge tokens the way the board/preview would, with sample values,
    so the voice validator sees the email a real lead receives."""
    ib = i.get("icebreaker") or {}
    angles = ib.get("angles") or []
    rec = next((a for a in angles if a.get("recommended")), angles[0] if angles else None)
    opener = (rec or {}).get("example") or "Saw what you are building and thought I'd reach out."
    out = re.sub(r"\{\{?icebreaker\}?\}", opener, str(text), flags=re.I)
    out = re.sub(r"\{\{?first(_name)?\}?\}", "Alex", out, flags=re.I)
    out = re.sub(r"\{\{?company\}?\}", "Acme Agency", out, flags=re.I)
    out = re.sub(r"\{\{?colleague\}?\}", "Sam", out, flags=re.I)
    out = out.replace("%signature%", "Bjion\nFounder\nNavreo\nVisit our website at navreo(.)ai")
    return _TOKEN_RE.sub("Example", out)


_SP_RE = re.compile(r"\bIf (?:we|I) could\b", re.I)          # Service Pitch (lilly-copywriter 1a)
_OSP_RE = re.compile(r"(?mi)^\s*We help\b")                   # One Sentence Punch (1b) positioning line


def _validate_voice(i, iid, errors, warnings):
    """Every email-1 version must pass the Navreo voice framework's machine check
    (Bjion 2026-08-03: 'the copywriting frameworks aren't being included').
    The Service Pitch template (lilly-copywriter 1a) is intentionally compact — 2
    blocks — so the Offer-Maker validator's >=3-block structure rule yields to it;
    every other shape stays a hard gate. Follow-ups are exempt."""
    nv = _voice_module()
    if not nv:
        warnings.append(f"idea {iid}: navreo_voice.py unavailable — copy NOT machine-checked "
                        f"against the house framework")
        return
    seq = i.get("sequence") or []
    v1 = (seq[0].get("versions") if seq and isinstance(seq[0], dict) else None) or []
    for vi, v in enumerate(v1):
        raw = str(v.get("email", ""))
        email = _resolve_sample(raw, i)
        try:
            nv.validate_email(email, lead_magnet=False)
        except ValueError as e:
            msg = str(e)
            if _SP_RE.search(raw) and "structure" in msg:
                continue  # expected for the compact Service Pitch shape
            if "opens with the CTA" in msg and re.search(r"(is that right|is that correct|is that you)\?", email, re.I):
                continue  # proven soft-confirmation opener (Amplifyy top performer), not a hard CTA
            errors.append(f"idea {iid}: email 1 version {vi + 1} fails the Navreo voice framework — {e}")


def _validate_framework(i, iid, errors):
    """Followers & Events email copy uses the Lilly Copywriter Email-1 shapes
    (Bjion 2026-08-03) — across the 4 versions, at least one Service Pitch (1a) and
    at least one One Sentence Punch (1b). Every followers/events email-1 version
    carries a P.S (proof/sweetener). Lookalike keeps its own fixed template (already
    the OSP family) and carries NO P.S at all (Bjion 2026-08-05) — the no-P.S rule is
    enforced in _validate_type_contracts."""
    vec = i.get("vector")
    if vec not in ("followers", "events"):
        return
    seq = i.get("sequence") or []
    v1 = (seq[0].get("versions") if seq and isinstance(seq[0], dict) else None) or []
    bodies = [str(v.get("email", "")) for v in v1]
    for vi, b in enumerate(bodies):
        if not re.search(r"(?mi)^\s*p\.s\s*-", b):
            errors.append(f"idea {iid}: email 1 version {vi + 1} needs a 'P.S -' line "
                          f"(proof or sweetener — Lilly Copywriter)")
    if vec in ("followers", "events"):
        if not any(_SP_RE.search(b) and "?" in b for b in bodies):
            errors.append(f"idea {iid}: {vec} email 1 needs a Service Pitch version "
                          f"('If we could ... would you ...?') — Lilly Copywriter framework")
        if not any(_OSP_RE.search(b) for b in bodies):
            errors.append(f"idea {iid}: {vec} email 1 needs a One Sentence Punch version "
                          f"(binary question + a 'We help ...' line) — Lilly Copywriter framework")


def _validate_copy_rules(run, i, iid, errors):
    """Global copy rules (Bjion 2026-08-03, every idea, every type):
    1. Email 1 has FOUR distinct versions (sequence[0].versions).
    2. Every custom {token} in copy/openers resolves in the Summary tab — each person in
       people[id] carries the field (p.<token> or p.vars.<token>)."""
    seq = i.get("sequence") or []
    v1 = (seq[0].get("versions") if seq and isinstance(seq[0], dict) else None) or []
    if len(v1) < 2:
        errors.append(f"idea {iid}: email 1 needs at least 2 versions (sequence[0].versions has {len(v1)})")
    else:
        bodies = [str(v.get("email", "")) for v in v1]
        if len(set(bodies)) < len(v1):
            errors.append(f"idea {iid}: email 1's versions must be DISTINCT")
    # collect custom tokens from all copy the preview renders
    texts = [str(i.get("email", "")), str(i.get("subject", ""))]
    for step in seq:
        for v in (step.get("versions") or []) if isinstance(step, dict) else []:
            texts += [str(v.get("email", "")), str(v.get("subject", ""))]
    # only what the Summary tab actually resolves: the recommended/first angle + the
    # fallback (non-recommended angles render as templates on the Icebreaker page).
    ib = i.get("icebreaker") or {}
    angles = ib.get("angles") or []
    rec = next((a for a in angles if a.get("recommended")), angles[0] if angles else None)
    if rec:
        texts.append(str(rec.get("example", "")))
    texts.append(str(ib.get("fallback", "")))
    custom = {t.strip() for txt in texts for t in _TOKEN_RE.findall(txt)
              if t.strip().lower() not in _KNOWN_TOKENS}
    if not custom:
        return
    people = (run.get("people") or {}).get(i.get("id")) or []
    if not people:
        errors.append(f"idea {iid}: copy uses custom token(s) {sorted(custom)} but has no preview "
                      f"people to resolve them — the Summary tab would show raw tokens")
    for p in people:
        pv = p.get("vars") or {}
        for t in custom:
            if t in pv or t.lower() in pv or isinstance(p.get(t.lower()), (str, int)) or isinstance(p.get(t), (str, int)):
                continue
            errors.append(f"idea {iid}: person {p.get('first','?')} missing '{t}' — every preview "
                          f"person must carry each custom token so the Summary resolves it")


def _validate_type_contracts(i, iid, errors):
    """Fixed contracts for the three Bjion 2026-08-03 campaign types.
    Company Followers: reach = 5% of summed page followers, pages hyperlinked, fixed opener.
    Event Exhibitors: NO reach number, exhibitors-not-attendees note, events hyperlinked, fixed opener.
    Look-a-like: the fixed email-1 template shape + fixed opener."""
    vec = i.get("vector")
    ice = i.get("icebreaker") or {}

    if vec == "followers":
        pages = i.get("followerPages") or []
        if not pages:
            errors.append(f"idea {iid}: followers idea needs followerPages [{{name,url,followers}}] "
                          f"— the pages + counts the 5% reach is computed from")
        else:
            total = 0
            for pi, p in enumerate(pages):
                if not p.get("url"):
                    errors.append(f"idea {iid}: followerPages[{pi}] needs a LinkedIn 'url' (pages are hyperlinked)")
                f = p.get("followers")
                if not isinstance(f, (int, float)):
                    errors.append(f"idea {iid}: followerPages[{pi}] needs a numeric 'followers' count")
                else:
                    total += f
            expected = round(0.05 * total)
            if i.get("net") != expected:
                errors.append(f"idea {iid}: followers net {i.get('net')} != 5% of summed followers "
                              f"({total}) = {expected} — reach is exactly Sum(followers) x 0.05")
        if ice.get("kind") != "fixed":
            errors.append(f"idea {iid}: followers opener must be icebreaker.kind 'fixed' (never a waterfall)")
        _check_fixed_opener(i, iid, errors,
                            "Saw you were following {page} and thought I'd reach out.")

    elif vec == "events":
        evs = i.get("events") or []
        if not evs:
            errors.append(f"idea {iid}: events idea needs events [{{name,url}}] — the events we scrape, hyperlinked")
        for ei, ev in enumerate(evs):
            if not ev.get("url"):
                errors.append(f"idea {iid}: events[{ei}] needs a 'url' (events are hyperlinked)")
        # reach is an ESTIMATE: about 100 decision makers per event (Bjion rule
        # 2026-08-03, supersedes the earlier no-number rule)
        expected = 100 * len(evs)
        if evs and i.get("net") != expected:
            errors.append(f"idea {iid}: events net {i.get('net')} != ~100 decision makers x "
                          f"{len(evs)} events = {expected} — the estimate is 100 per event")
        note = str((i.get("targeting") or {}).get("note", "")).lower()
        if "exhibit" not in note or "attend" not in note:
            errors.append(f"idea {iid}: events targeting.note must state the 'exhibitors, not attendees' rule")
        if ice.get("kind") != "fixed":
            errors.append(f"idea {iid}: events opener must be icebreaker.kind 'fixed'")
        _check_fixed_opener(i, iid, errors,
                            "Saw you exhibiting at {events} and thought I'd reach out.")

    elif vec == "lookalike":
        email = str(i.get("email", ""))
        kind = ice.get("kind")
        # Bjion 2026-08-05 (fidelity loop): Look-a-like carries NO P.S line — the
        # template is exact both ways, so flag any P.S that sneaks back in.
        la_seq = i.get("sequence") or []
        la_v1 = (la_seq[0].get("versions") if la_seq and isinstance(la_seq[0], dict) else None) or []
        la_bodies = [(f"email 1 version {vi + 1}", str(v.get("email", ""))) for vi, v in enumerate(la_v1)] \
            or [("primary email", email)]
        # Bjion 2026-08-05: the pain line must BE a problem framed as a question the reader
        # answers in their head — never a statement with a soft empathy tag slapped on the
        # end ("... hard to tell what's working. Sound familiar?"). Flag the tag.
        soft_tag = re.compile(r"(?i)\b(sound familiar|ring true|run into that|is that fair"
                              r"|fair for you|sound about right|does that resonate|notice that"
                              r"|make sense|sound right|fair)\s*\?")
        for la_where, la_b in la_bodies:
            if re.search(r"(?mi)^\s*p\.s\s*-", la_b):
                errors.append(f"idea {iid}: lookalike carries a 'P.S -' line ({la_where}) — "
                              f"Look-a-like has no P.S (Bjion 2026-08-05)")
            m = soft_tag.search(la_b)
            if m:
                errors.append(f"idea {iid}: lookalike pain line uses a tacked-on soft tag "
                              f"'{m.group(0)}' ({la_where}) — frame the problem AS the question, "
                              f"not a statement + 'sound familiar?' (Bjion 2026-08-05)")
        if kind == "dynamic":
            # original lookalike template: dynamic opener, pain question is copy
            if "question for" not in str(i.get("subject", "")).lower():
                errors.append(f"idea {iid}: lookalike subject must be 'question for {{first}}'")
            if "{icebreaker}" not in email.lower():
                errors.append(f"idea {iid}: lookalike email-1 must carry its own {{icebreaker}} line")
            if "fit for the same" not in email.lower():
                errors.append(f"idea {iid}: lookalike email missing the fixed spine '...fit for the same.'")
        elif kind == "fixed":
            # fixed proven-opener style (Bjion 2026-08-04): the Amazon-status opener IS the
            # icebreaker; copy follows the lilly-copywriter framework, so the pain-question
            # spine and "question for" subject do not apply. Require the opener(s) present.
            if len(ice.get("angles") or []) < 1:
                errors.append(f"idea {iid}: fixed lookalike needs the proven opener(s) in icebreaker.angles")
        else:
            errors.append(f"idea {iid}: lookalike icebreaker.kind must be 'dynamic' or 'fixed'")


def validate_run(run):
    errors, warnings = [], []
    ideas = run.get("ideas") or []
    if not ideas:
        errors.append("run.ideas is empty")
    seen_vectors = set()
    for i in ideas:
        iid = i.get("id", "?")
        # Event Exhibitors reach is the 100-per-event estimate (net), not a probe:
        # gross/emails don't apply to it.
        required = [f for f in IDEA_REQUIRED if f not in ("gross", "emails")] \
            if i.get("vector") == "events" else IDEA_REQUIRED
        for f in required:
            if f not in i:
                errors.append(f"idea {iid}: missing field '{f}'")
        if i.get("vector") not in VECTORS:
            errors.append(f"idea {iid}: vector {i.get('vector')!r} not in {sorted(VECTORS)}")
        else:
            seen_vectors.add(i["vector"])
        if isinstance(i.get("net"), (int, float)) and isinstance(i.get("gross"), (int, float)):
            if i["net"] > i["gross"]:
                errors.append(f"idea {iid}: net {i['net']} > gross {i['gross']}")
        probe = i.get("probe") or {}
        if not probe.get("provider") or not probe.get("date"):
            errors.append(f"idea {iid}: probe must carry provider+date — numbers are probe-confirmed ONLY")
        spec = i.get("pull_spec") or {}
        if spec.get("provider") not in PROBE_PROVIDERS + ("manual", "trigify", "porkbun_export"):
            errors.append(f"idea {iid}: pull_spec.provider {spec.get('provider')!r} unknown")
        # targeting block (page-visible) — the showcase renders it for every use-case.
        # groups/kind are optional; when present they must be well-formed so the
        # dynamic renderer never hits a missing chips list or an unknown kind.
        trg = i.get("targeting") or {}
        if trg.get("kind") and trg["kind"] not in VECTORS:
            warnings.append(f"idea {iid}: targeting.kind {trg['kind']!r} not a known vector "
                            f"— no type eyebrow / default label will show")
        for gi, grp in enumerate(trg.get("groups") or []):
            if not isinstance(grp, dict) or not grp.get("chips"):
                errors.append(f"idea {iid}: targeting.groups[{gi}] needs a non-empty 'chips' list")
        text = " ".join(str(i.get(k, "")) for k in ("offer", "who", "why", "pain", "moment", "videoAngle"))
        if re.search(r"\baudit", text, re.I):
            errors.append(f"idea {iid}: 'audit' offers are banned (service-based magnets only)")
        if re.search(r"\b\d[\d,]* compan(y|ies)\b", text):
            warnings.append(f"idea {iid}: company-count language — sizes are decision makers ONLY")
        if "—" in text:
            warnings.append(f"idea {iid}: em-dash in copy-facing text")
        _validate_type_contracts(i, iid, errors)
        _validate_copy_rules(run, i, iid, errors)
        _validate_framework(i, iid, errors)
        _validate_voice(i, iid, errors, warnings)
    # An explicit all-lookalike board (e.g. one idea per case study — Bjion 2026-08-04)
    # is a deliberate single-mechanism ask, not a lazy collapse, so it's exempt. The
    # guard still bites the generic case, which collapses to targeted_list, never lookalike.
    if len(ideas) >= 5 and len(seen_vectors) < 3 and seen_vectors != {"lookalike"}:
        errors.append(f"vector mixture rule: {len(ideas)} ideas but only {len(seen_vectors)} "
                      f"vector(s) {sorted(seen_vectors)} — a board needs >=3 campaign types")
    for iid, people in (run.get("people") or {}).items():
        for p in people:
            for f in PERSON_REQUIRED:
                if f not in p:
                    errors.append(f"people[{iid}]: person missing '{f}'")
            if not (p.get("lines") or {}).get("safe"):
                errors.append(f"people[{iid}]: every person needs lines.safe")
    return errors, warnings


def cmd_validate(args):
    run = json.load(open(args.run, encoding="utf-8"))
    errors, warnings = validate_run(run)
    out = {"ok": not errors, "errors": errors, "warnings": warnings,
           "ideas": len(run.get("ideas") or []),
           "vectors": sorted({i.get("vector") for i in run.get("ideas") or [] if i.get("vector")})}
    emit(out, args)
    if errors:
        sys.exit(1)


# ---------------------------------------------------------------- hydrate
def js(obj, indent=2):
    return json.dumps(obj, ensure_ascii=False, indent=indent)


def splice_block(src, start_pat, out_lines):
    """Replace lines from the one matching start_pat through the closing '];' or '};'."""
    lines = src.split("\n")
    for i, ln in enumerate(lines):
        if re.match(start_pat, ln):
            closer = "];" if "[" in ln else "};"
            for j in range(i, len(lines)):
                if lines[j].strip() == closer:
                    return "\n".join(lines[:i] + out_lines + lines[j + 1:])
            raise RuntimeError(f"no closer for block {start_pat}")
    raise RuntimeError(f"block not found: {start_pat}")


def cmd_hydrate(args):
    run = json.load(open(args.run, encoding="utf-8"))
    errors, warnings = validate_run(run)
    if errors:
        sys.exit("hydrate refused — validate failed:\n  " + "\n  ".join(errors))
    template_path = args.template or TEMPLATE
    src = open(template_path, encoding="utf-8").read()

    # strip engine-only fields from ideas before serialising (page code doesn't use them)
    page_ideas = []
    for i in run["ideas"]:
        clean = {k: v for k, v in i.items() if k not in ("vector", "probe", "pull_spec", "netting")}
        page_ideas.append(clean)
    header = (f"// ============== run data — {run.get('client','?')} strategy run "
              f"{run.get('date', today())} (lilly-strategy engine) ==============")
    ideas_block = [header, "const IDEAS = " + js(page_ideas) + ";"]
    src = splice_block(src, r"^const IDEAS = \[", ideas_block)

    if run.get("validation_card"):
        src = splice_block(src, r"^const VALIDATION_CARD = \{",
                           ["const VALIDATION_CARD = " + js(run["validation_card"]) + ";"])
    if run.get("colleagues"):
        src = re.sub(r"^const COLLEAGUES = .*$",
                     "const COLLEAGUES = " + js(run["colleagues"], indent=None) + ";",
                     src, count=1, flags=re.M)
    if run.get("people"):
        src = splice_block(src, r"^const PEOPLE = \{",
                           ["const PEOPLE = " + js(run["people"]) + ";"])
    if run.get("footer"):
        src = re.sub(r'(<footer id="board-footer">).*?(</footer>)',
                     r"\1" + run["footer"].replace("\\", r"\\") + r"\2", src, count=1, flags=re.S)
    carries = run.get("carry") or []
    if carries:
        lines = ["// Carried in-flight state (previous runs' builds keep their live status)."]
        for c in carries:
            lines.append(f"Object.assign(cardState.{c['idea']}, {js(c['state'], indent=None)});")
        anchor = "\nlet activeId"
        if anchor not in src:
            raise RuntimeError("carry anchor 'let activeId' not found in template")
        src = src.replace(anchor, "\n" + "\n".join(lines) + anchor, 1)

    out_path = args.out or os.path.join(os.getcwd(), f"wizard-{run.get('client','run')}.html")
    open(out_path, "w", encoding="utf-8").write(src)
    emit({"ok": True, "out": out_path, "bytes": len(src.encode()),
          "ideas": len(page_ideas), "warnings": warnings}, args)


# ---------------------------------------------------------------- handoff
def cmd_handoff(args):
    run = json.load(open(args.run, encoding="utf-8"))
    idea = next((i for i in run["ideas"] if i["id"] == args.idea), None)
    if not idea:
        sys.exit(f"idea '{args.idea}' not in {args.run}")
    spec = idea.get("pull_spec") or {}
    netting = idea.get("netting") or {}
    lines = [
        f"## Approved: {idea['name']} ({run.get('client','?')}, {run.get('date', today())})",
        "",
        f"- **Vector:** {idea.get('vector')}",
        f"- **Net decision makers:** {idea.get('net'):,} (gross {idea.get('gross'):,}, "
        f"probe {idea.get('probe',{}).get('provider')} {idea.get('probe',{}).get('date')})",
        f"- **Free from records:** {idea.get('freeFromRecords', 'n/a')} · new (paid): {idea.get('newPeople', 'n/a')}",
        f"- **Offer:** {idea.get('offer')}",
        f"- **Who:** {idea.get('who')}",
        "",
        "### /lilly-tam pull spec (execute EXACTLY this shape — it is the probe-confirmed one)",
        "```json",
        js({"provider": spec.get("provider"), "filters": spec.get("filters"),
            "notes": spec.get("notes")}),
        "```",
        "",
        "### Build rules (house law)",
        "- Suppression-FIRST: run `engine.py net` on every wave's candidates before any paid call.",
        "- Waves of ~300: free-from-records rows first, then cached, then paid fill.",
        f"- 30-day same-client cooldown (client: {run.get('client')}); terminal categories never recontacted.",
        "- Cache every paid row (navreo_db) + provider ledger; full-fidelity upload via list_upload.py.",
        "- Then: lilly-strategy Single-campaign mode walkthrough (build to launch-ready; send switch untouched).",
    ]
    print("\n".join(lines))


# ---------------------------------------------------------------- main
def emit(obj, args):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if getattr(args, "out_json", None):
        open(args.out_json, "w", encoding="utf-8").write(text)
    print(text)


def main():
    load_keys()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("retro"); p.add_argument("--client", default="navreo"); p.add_argument("--out-json")
    p = sub.add_parser("probe")
    p.add_argument("--run"); p.add_argument("--idea"); p.add_argument("--spec"); p.add_argument("--out-json")
    p = sub.add_parser("net")
    p.add_argument("--client", required=True); p.add_argument("--domains", default="")
    p.add_argument("--emails", default=""); p.add_argument("--out-json")
    p = sub.add_parser("validate"); p.add_argument("--run", required=True); p.add_argument("--out-json")
    p = sub.add_parser("hydrate")
    p.add_argument("--run", required=True); p.add_argument("--template"); p.add_argument("--out")
    p.add_argument("--out-json")
    p = sub.add_parser("handoff"); p.add_argument("--run", required=True); p.add_argument("--idea", required=True)

    args = ap.parse_args()
    {"retro": cmd_retro, "probe": cmd_probe, "net": cmd_net,
     "validate": cmd_validate, "hydrate": cmd_hydrate, "handoff": cmd_handoff}[args.cmd](args)


if __name__ == "__main__":
    main()
