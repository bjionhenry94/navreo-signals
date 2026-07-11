"""Appointment-setter pipeline (Setter tab).

Owns the whole reply -> classify -> draft -> decide -> (auto-send | review) loop
for Smartlead campaign replies, plus the setter_agents / setter_queue CRUD the
Setter tab talks to. Deliberately standalone (no `import server`) - server.py
imports THIS module and calls `configure()` once at startup so there is no
circular import.

Conventions mirrored from server.py: stdlib only, defensive try/except at every
route boundary (a crash here must never kill the connection), plain-English
user-visible strings, no em-dashes, no emoji.

See the build spec for the full pipeline description. Pinned public names (so
server.py wiring and app/test_setter.py agree on the contract):
  configure, GET_ROUTES, POST_ROUTES, process_reply, decide, guess_timezone,
  pick_slots, lint_draft, lexicon_hits, run_poll.
"""

import datetime as _dt
import json
import os
import re
import sys
import uuid
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

# ── wiring (set once by server.py at startup) ────────────────────────────────

_SB = None
_HTTP = None
_KEYS: dict = {}
_LOG = None


def configure(sb, http_json, keys, log_activity):
    """Called once by server.py: setter.configure(sb=sb, http_json=http_json,
    keys=KEYS, log_activity=log_activity). Stores the app's own helpers in
    module globals so this file never has to `import server`."""
    global _SB, _HTTP, _KEYS, _LOG
    _SB = sb
    _HTTP = http_json
    _KEYS = keys or {}
    _LOG = log_activity


WORKSPACE = "navreo"
AGENTS_TABLE = "setter_agents"
QUEUE_TABLE = "setter_queue"
SETTINGS_ID = "__settings__"
SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
OPENAI_MODEL = "gpt-5-mini"

INTENTS = [
    "send_resource", "pricing", "scheduling", "bespoke_request", "objection_or_question",
    "not_interested", "unsubscribe_dnc", "ooo", "wrong_person", "bounce_or_system", "other",
]
CLEAR_NEGATIVE_INTENTS = {"not_interested", "unsubscribe_dnc", "ooo", "wrong_person", "bounce_or_system"}

# Independent veto: Smartlead's OWN categoriser output. Never auto-send over
# these regardless of what our classifier thinks.
CATEGORY_VETO = {
    "Not Interested", "Do Not Contact", "Out Of Office", "Wrong Person",
    "Sender Originated Bounce", "Not right now",
}

# Categoriser labels that read positive. If our classifier calls a reply a
# clear negative while the categoriser called it one of these, the two systems
# disagree - a person breaks the tie instead of silently dropping a lead.
POSITIVE_CATEGORIES = {
    "Interested", "Information Request", "Meeting Request",
    "[Manual] Send resource", "Call Booked",
}

# Deterministic red-flag lexicon (case-insensitive substring match on the
# reply body with quoted history stripped). Any hit is a hard veto - never
# auto, regardless of what the classifier says.
LEXICON = [
    "unsubscribe", "remove me", "take me off", "stop emailing", "not interested", "no thanks",
    "cease", "lawyer", "legal", "gdpr", "complaint", "spam", "out of office",
    "auto-reply", "auto reply", "undeliver", "wasn't delivered", "was not delivered", "mailbox full",
]

# Pattern vetoes for opt-outs the phrase list can't catch, e.g. "Remove Phil
# Lowe" (a removal request naming the person instead of saying "me"). Only
# scanned near the start of the stripped body, where an opt-out lives - a
# mid-email "remove the bottleneck" shouldn't trip it (and if one ever does,
# the cost is a forced human review, never a lost send).
_LEXICON_PATTERNS = [
    (re.compile(r"^\W{0,10}(please\s+|pls\s+|kindly\s+)?remove\b", re.IGNORECASE), "removal request"),
    (re.compile(r"\bdelete\s+(me|my\s+(email|address|details|data))\b", re.IGNORECASE), "delete request"),
    (re.compile(r"\bdo\s+not\s+(contact|email)\b", re.IGNORECASE), "do-not-contact request"),
]

_QUOTE_MARKERS = [
    r"\n\s*On .{0,100} wrote:\s*\n",
    r"\n-{2,}\s*Original Message\s*-{2,}",
    r"\n>",
]


def _strip_quoted(body: str) -> str:
    text = body or ""
    cut = None
    for pat in _QUOTE_MARKERS:
        m = re.search(pat, text, re.IGNORECASE)
        if m and (cut is None or m.start() < cut):
            cut = m.start()
    return text[:cut] if cut is not None else text


def lexicon_hits(body: str) -> list:
    """Deterministic guardrail veto - case-insensitive phrase match on the
    reply body, quoted history stripped first, plus a few opt-out patterns."""
    stripped = _strip_quoted(body or "")
    text = stripped.lower()
    hits = [phrase for phrase in LEXICON if phrase in text]
    for pat, label in _LEXICON_PATTERNS:
        if pat.search(stripped) and label not in hits:
            hits.append(label)
    return hits


_PHONE_RE = re.compile(r"\+\s?\d[\d\s().\-]{6,}")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_BLOCK_RE = re.compile(r"<(style|script|head)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def clean_body(body: str) -> str:
    """Reply text with HTML markup stripped and whitespace collapsed. Outlook
    and Gmail replies often arrive as full HTML documents; markup must never
    count toward the length veto or blur what the classifier reads."""
    text = body or ""
    if "<" in text and _HTML_TAG_RE.search(text):
        import html as _html
        text = _STYLE_BLOCK_RE.sub(" ", text)
        text = _HTML_TAG_RE.sub(" ", text)
        text = _html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()

# Same-day scheduling asks ("can we chat today / in an hour?") can't be
# answered by two fixed future slots - deterministic veto, judged from the
# unquoted reply text only.
_SAME_DAY_RE = re.compile(
    r"\b(today|tonight|right now|asap|as soon as possible|in an hour|"
    r"this (morning|afternoon|evening)|earlier today)\b", re.IGNORECASE)


def _extract_phone(text: str) -> str:
    """First international-format phone number in the text ('+44 7732 728478'),
    or ''. guess_timezone matches the country code at the START of its phone
    hint, so the hint must be the number itself, never the whole body."""
    m = _PHONE_RE.search(text or "")
    return m.group(0).strip() if m else ""


# ── timezone guessing (deterministic first, LLM fallback in process_reply) ──

COUNTRY_TZ = {
    "GB": "Europe/London", "UK": "Europe/London", "UNITED KINGDOM": "Europe/London",
    "IE": "Europe/Dublin", "IRELAND": "Europe/Dublin",
    "DE": "Europe/Berlin", "GERMANY": "Europe/Berlin",
    "FR": "Europe/Paris", "FRANCE": "Europe/Paris",
    "ES": "Europe/Madrid", "SPAIN": "Europe/Madrid",
    "IT": "Europe/Rome", "ITALY": "Europe/Rome",
    "NL": "Europe/Amsterdam", "NETHERLANDS": "Europe/Amsterdam",
    "PT": "Europe/Lisbon", "PORTUGAL": "Europe/Lisbon",
    "BE": "Europe/Brussels", "BELGIUM": "Europe/Brussels",
    "CH": "Europe/Zurich", "SWITZERLAND": "Europe/Zurich",
    "AT": "Europe/Vienna", "AUSTRIA": "Europe/Vienna",
    "SE": "Europe/Stockholm", "SWEDEN": "Europe/Stockholm",
    "NO": "Europe/Oslo", "NORWAY": "Europe/Oslo",
    "DK": "Europe/Copenhagen", "DENMARK": "Europe/Copenhagen",
    "FI": "Europe/Helsinki", "FINLAND": "Europe/Helsinki",
    "PL": "Europe/Warsaw", "POLAND": "Europe/Warsaw",
    "HK": "Asia/Hong_Kong", "HONG KONG": "Asia/Hong_Kong",
    "SG": "Asia/Singapore", "SINGAPORE": "Asia/Singapore",
    "JP": "Asia/Tokyo", "JAPAN": "Asia/Tokyo",
    "IN": "Asia/Kolkata", "INDIA": "Asia/Kolkata",
    "AE": "Asia/Dubai", "UAE": "Asia/Dubai",
    "ZA": "Africa/Johannesburg", "SOUTH AFRICA": "Africa/Johannesburg",
    "MX": "America/Mexico_City", "MEXICO": "America/Mexico_City",
    "NZ": "Pacific/Auckland", "NEW ZEALAND": "Pacific/Auckland",
}

US_STATE_TZ = {
    "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "OR": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "NY": "America/New_York", "NJ": "America/New_York", "MA": "America/New_York", "FL": "America/New_York",
    "GA": "America/New_York", "VA": "America/New_York", "PA": "America/New_York", "NC": "America/New_York",
    "IL": "America/Chicago", "TX": "America/Chicago", "MN": "America/Chicago", "MO": "America/Chicago",
    "CO": "America/Denver", "UT": "America/Denver", "AZ": "America/Phoenix",
    "HI": "Pacific/Honolulu", "AK": "America/Anchorage",
}
US_CITY_TZ = {
    "san francisco": "America/Los_Angeles", "los angeles": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "san diego": "America/Los_Angeles", "portland": "America/Los_Angeles",
    "new york": "America/New_York", "boston": "America/New_York", "miami": "America/New_York",
    "atlanta": "America/New_York", "washington": "America/New_York", "philadelphia": "America/New_York",
    "chicago": "America/Chicago", "dallas": "America/Chicago", "houston": "America/Chicago", "austin": "America/Chicago",
    "denver": "America/Denver", "phoenix": "America/Phoenix", "honolulu": "Pacific/Honolulu",
}
CA_PROV_TZ = {
    "ON": "America/Toronto", "QC": "America/Toronto", "BC": "America/Vancouver", "AB": "America/Edmonton",
    "MB": "America/Winnipeg", "SK": "America/Regina", "NS": "America/Halifax", "NB": "America/Halifax",
}
CA_CITY_TZ = {
    "toronto": "America/Toronto", "montreal": "America/Toronto", "vancouver": "America/Vancouver",
    "calgary": "America/Edmonton", "edmonton": "America/Edmonton", "ottawa": "America/Toronto",
}
AU_STATE_TZ = {
    "NSW": "Australia/Sydney", "VIC": "Australia/Melbourne", "QLD": "Australia/Brisbane",
    "WA": "Australia/Perth", "SA": "Australia/Adelaide", "TAS": "Australia/Hobart",
    "NT": "Australia/Darwin", "ACT": "Australia/Sydney",
}
AU_CITY_TZ = {
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth", "adelaide": "Australia/Adelaide",
}
BR_CITY_TZ = {
    "sao paulo": "America/Sao_Paulo", "rio de janeiro": "America/Sao_Paulo", "brasilia": "America/Sao_Paulo",
    "manaus": "America/Manaus", "recife": "America/Recife",
}
RU_CITY_TZ = {
    "moscow": "Europe/Moscow", "st petersburg": "Europe/Moscow", "novosibirsk": "Asia/Novosibirsk",
    "yekaterinburg": "Asia/Yekaterinburg", "vladivostok": "Asia/Vladivostok",
}

# ccTLD -> tz, longest-suffix-first matching (so "com.br" beats a bare "br").
TLD_TZ = {
    "co.uk": "Europe/London", "com.au": "Australia/Sydney", "com.br": "America/Sao_Paulo",
    "com.mx": "America/Mexico_City",
    "uk": "Europe/London", "de": "Europe/Berlin", "fr": "Europe/Paris", "es": "Europe/Madrid",
    "it": "Europe/Rome", "nl": "Europe/Amsterdam", "ie": "Europe/Dublin", "pt": "Europe/Lisbon",
    "be": "Europe/Brussels", "ch": "Europe/Zurich", "at": "Europe/Vienna", "se": "Europe/Stockholm",
    "no": "Europe/Oslo", "dk": "Europe/Copenhagen", "fi": "Europe/Helsinki", "pl": "Europe/Warsaw",
    "ca": "America/Toronto", "au": "Australia/Sydney", "br": "America/Sao_Paulo", "in": "Asia/Kolkata",
    "sg": "Asia/Singapore", "hk": "Asia/Hong_Kong", "jp": "Asia/Tokyo", "ae": "Asia/Dubai",
    "za": "Africa/Johannesburg", "nz": "Pacific/Auckland", "mx": "America/Mexico_City",
}
_PHONE_CC = [
    ("+852", "HK"), ("+971", "AE"), ("+353", "IE"), ("+61", "AU"), ("+44", "GB"), ("+49", "DE"),
    ("+33", "FR"), ("+34", "ES"), ("+31", "NL"), ("+27", "ZA"), ("+65", "SG"), ("+1", "US"),
]


def _big_country(cc: str, state: str, city: str):
    if cc in ("US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"):
        if state and state in US_STATE_TZ:
            return US_STATE_TZ[state], 0.75
        if city and city in US_CITY_TZ:
            return US_CITY_TZ[city], 0.75
        return "America/New_York", 0.4
    if cc in ("CA", "CANADA"):
        if state and state in CA_PROV_TZ:
            return CA_PROV_TZ[state], 0.7
        if city and city in CA_CITY_TZ:
            return CA_CITY_TZ[city], 0.7
        return "America/Toronto", 0.4
    if cc in ("AU", "AUSTRALIA"):
        if state and state in AU_STATE_TZ:
            return AU_STATE_TZ[state], 0.7
        if city and city in AU_CITY_TZ:
            return AU_CITY_TZ[city], 0.7
        return "Australia/Sydney", 0.4
    if cc in ("BR", "BRAZIL"):
        if city and city in BR_CITY_TZ:
            return BR_CITY_TZ[city], 0.7
        return "America/Sao_Paulo", 0.55
    if cc in ("RU", "RUSSIA"):
        if city and city in RU_CITY_TZ:
            return RU_CITY_TZ[city], 0.7
        return "Europe/Moscow", 0.4
    return None


def guess_timezone(hints: dict):
    """Deterministic country/state/city/TLD/phone -> IANA tz guess.
    hints: {country, state, city, phone, tld, body}. Returns (tz|None, confidence)."""
    hints = hints or {}
    country = (hints.get("country") or "").strip()
    state = (hints.get("state") or "").strip().upper()
    city = (hints.get("city") or "").strip().lower()
    phone = (hints.get("phone") or "").strip()
    tld = (hints.get("tld") or "").strip().lower().lstrip(".")
    body = (hints.get("body") or "")

    if not country and phone:
        compact = phone.replace(" ", "").replace("-", "").replace(".", "")
        for cc, cn in sorted(_PHONE_CC, key=lambda x: -len(x[0])):
            if compact.startswith(cc):
                country = cn
                break

    cn = country.upper()
    if cn:
        big = _big_country(cn, state, city)
        if big:
            return big
        tz = COUNTRY_TZ.get(cn)
        if tz:
            return tz, 0.75

    if not tld:
        m = re.search(
            r"[\w-]+\.(com\.br|com\.au|com\.mx|co\.uk|de|fr|es|it|nl|ie|ca|au|br|in|sg|hk|jp|ae|za|nz|mx|pt|"
            r"se|no|dk|fi|pl|ch|at|be)\b", body, re.IGNORECASE)
        if m:
            tld = m.group(1).lower()

    if tld:
        for suf, tz in sorted(TLD_TZ.items(), key=lambda x: -len(x[0])):
            if tld == suf or tld.endswith("." + suf):
                return tz, 0.6

    text = (body or "").lower()
    for table in (US_CITY_TZ, CA_CITY_TZ, AU_CITY_TZ, BR_CITY_TZ, RU_CITY_TZ):
        for name, tz in table.items():
            if name in text:
                return tz, 0.55

    return None, 0.0


# ── slot picking + labelling ─────────────────────────────────────────────────

_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{_ORDINAL_SUFFIX.get(n % 10, 'th')}"


def _slot_label(local_dt) -> str:
    time_txt = local_dt.strftime("%I:%M %p").lstrip("0")
    tzabbrev = local_dt.tzname() or ""
    return f"{local_dt.strftime('%A')}, {_ordinal(local_dt.day)} {local_dt.strftime('%B')} at {time_txt} {tzabbrev}".strip()


def _slot_link(agent: dict, lead: dict, iso_with_offset: str) -> str:
    base = (agent or {}).get("calendly_event_url") or (agent or {}).get("booking_link") or ""
    first = (lead or {}).get("first_name") or ""
    last = (lead or {}).get("last_name") or ""
    email = (lead or {}).get("email") or ""
    name = f"{first} {last}".strip()
    return f"{base}/{iso_with_offset}?name={quote(name)}&email={quote(email)}"


def _parse_iso(s):
    if isinstance(s, _dt.datetime):
        return s if s.tzinfo else s.replace(tzinfo=_dt.timezone.utc)
    text = str(s).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    d = _dt.datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def pick_slots(avail_iso: list, tz: str, settings: dict, now_utc) -> list:
    """avail_iso: raw ISO8601 UTC availability from Calendly. Filters to
    workdays, [work_start, work_end) lead-local hours, within the next
    horizon_working_days working days, >= 20h out, then picks 2 spread slots
    (different days; late-morning + mid-afternoon where available). Returns
    [{iso, label, link}]. link uses settings['_agent'] (calendly_event_url)
    and settings['_lead'] (first_name/last_name/email)."""
    settings = settings or {}
    agent = settings.get("_agent") or {}
    lead = settings.get("_lead") or {}
    tzname = tz or "Europe/London"
    try:
        zi = ZoneInfo(tzname)
    except Exception:  # noqa: BLE001 - a bad tz string must never crash the pipeline
        zi = ZoneInfo("Europe/London")

    try:
        work_start = int(settings.get("work_start", 9))
        work_end = int(settings.get("work_end", 17))
        horizon_days = int(settings.get("horizon_working_days", 5))
    except (TypeError, ValueError):
        work_start, work_end, horizon_days = 9, 17, 5

    now_utc = _parse_iso(now_utc) if not isinstance(now_utc, _dt.datetime) else (
        now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=_dt.timezone.utc))

    local_now = now_utc.astimezone(zi)
    window_end_date = local_now.date()
    added = 0
    d = window_end_date
    while added < horizon_days:
        d = d + _dt.timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    window_end_date = d

    candidates = []
    for iso in (avail_iso or []):
        try:
            utc_dt = _parse_iso(iso)
        except (ValueError, TypeError):
            continue
        local = utc_dt.astimezone(zi)
        if local.weekday() >= 5:
            continue
        if not (work_start <= local.hour < work_end):
            continue
        if local.date() > window_end_date:
            continue
        if (utc_dt - now_utc) < _dt.timedelta(hours=20):
            continue
        candidates.append((local, utc_dt))

    candidates.sort(key=lambda x: x[0])
    if not candidates:
        return []

    used_dates = set()
    chosen = []

    def _take(pred):
        for local, utc_dt in candidates:
            if local.date() in used_dates:
                continue
            if pred(local):
                return (local, utc_dt)
        return None

    morning = _take(lambda l: 10 <= l.hour < 13)
    if morning:
        chosen.append(morning)
        used_dates.add(morning[0].date())
    afternoon = _take(lambda l: 13 <= l.hour < work_end)
    if afternoon:
        chosen.append(afternoon)
        used_dates.add(afternoon[0].date())

    # Only one date has availability? Two adjacent times read badly ("11:00 or
    # 11:30") - prefer a same-day afternoon slot at least 2 hours after the
    # first pick before falling back to whatever's next.
    if len(chosen) == 1:
        first_local = chosen[0][0]
        for local, utc_dt in candidates:
            if local.date() == first_local.date() and local.hour >= max(13, first_local.hour + 2) \
                    and (local, utc_dt) not in chosen:
                chosen.append((local, utc_dt))
                break

    for local, utc_dt in candidates:
        if len(chosen) >= 2:
            break
        if local.date() not in used_dates:
            chosen.append((local, utc_dt))
            used_dates.add(local.date())
    for cand in candidates:
        if len(chosen) >= 2:
            break
        if cand not in chosen:
            chosen.append(cand)

    chosen.sort(key=lambda x: x[0])
    out = []
    for local, utc_dt in chosen[:2]:
        local_iso = local.isoformat()
        out.append({"iso": local_iso, "label": _slot_label(local), "link": _slot_link(agent, lead, local_iso)})
    return out


# ── draft lint ────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def lint_draft(html: str, ctx: dict):
    """Deterministic pre-send checks. Returns (ok, reason)."""
    ctx = ctx or {}
    text = html or ""
    if not text.strip():
        return False, "No draft was produced."
    if "{{" in text:
        return False, "The draft still has an unfilled placeholder."
    if "—" in text:
        return False, "The draft uses an em dash, which house style forbids."
    if ctx.get("subject") is not None and not str(ctx.get("subject") or "").strip():
        return False, "The draft has no subject line."
    first = (ctx.get("first_name") or "").strip()
    # No reliable name to check against ("there" is the drafter's own
    # fallback placeholder): the drafter may legitimately greet by a name it
    # found in the reply's signature instead.
    if first and first.lower() != "there" and first.lower() not in text.lower():
        return False, "The draft doesn't greet the lead by their first name."
    if ctx.get("needs_resource_link") and (ctx.get("resource_link") or "") not in text:
        return False, "The draft is missing the resource link."
    if ctx.get("slot_status") == "ok":
        for link in (ctx.get("slot_links") or []):
            if link and link not in text:
                return False, "The draft is missing one of the suggested call times."

    allowed_text = " ".join([
        str(ctx.get("pricing_notes") or ""),
        str(ctx.get("thread_text") or ""),
        " ".join(str(x) for x in (ctx.get("slot_labels") or [])),
        " ".join(str(x) for x in (ctx.get("slot_links") or [])),
    ])
    allowed_digits = set(re.findall(r"\d+", allowed_text))
    plain = _TAG_RE.sub(" ", text)  # strip tags/hrefs - only visible text is scanned
    for run in re.findall(r"\d+", plain):
        if run not in allowed_digits:
            return False, "The draft invents a number that isn't in the pricing notes, the thread, or the call times."
    return True, ""


# ── decision gate ────────────────────────────────────────────────────────────

_INTENT_REASON = {
    "bespoke_request": "Held for review: the lead is asking for custom or bespoke work, which needs a person.",
    "objection_or_question": "Held for review: the lead has a nuanced question this agent can't answer safely alone.",
    "not_interested": "Held for review: a person should see this reply.",
    "unsubscribe_dnc": "Held for review: a person should handle this opt-out.",
    "ooo": "Held for review: this is an out-of-office reply.",
    "wrong_person": "Held for review: the lead says they're not the right contact.",
    "bounce_or_system": "Held for review: this looks like a bounce or system notice.",
    "other": "Held for review: the lead is asking for something this agent isn't allowed to answer alone.",
}


def decide(classification: dict, agent: dict, ctx: dict):
    """The gate. Returns (decision, plain_english_reason).
    decision in {"auto_send", "review", "no_action"}.
    ctx: {red_flag_hits, category, first_touch, slot_status, timezone, lint_ok,
          lint_reason, body_len, hydrated}."""
    classification = classification or {}
    agent = agent or {}
    ctx = ctx or {}

    primary = classification.get("primary_intent")
    all_intents = classification.get("all_intents") or ([primary] if primary else [])
    simple_ask = bool(classification.get("simple_ask"))
    try:
        confidence = float(classification.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    llm_red_flags = classification.get("red_flags") or []
    category = ctx.get("category")
    red_flag_hits = list(ctx.get("red_flag_hits") or [])

    # Clear negatives never need a draft - short-circuit straight to no_action,
    # UNLESS Smartlead's categoriser read the same reply as positive (the two
    # systems disagree) or the reply still contains a live opening (a named
    # replacement contact, a "not now, try me later") - a person sees those.
    if primary in CLEAR_NEGATIVE_INTENTS and confidence >= 0.8:
        if category in POSITIVE_CATEGORIES:
            return "review", ("Held for review: the AI read this as a "
                              f"{str(primary).replace('_', ' ')} but Smartlead categorised it as "
                              f"{category}, so a person should decide.")
        if classification.get("live_lead"):
            return "review", ("Held for review: the reply is a no for now, but it points at a "
                              "live opening (a referral or a later date) worth a look.")
        return "no_action", f"Clear {str(primary).replace('_', ' ')} reply - no action needed."

    # Someone (a person, in Smartlead) already answered this reply in the
    # thread - don't draft over them, and never double-reply.
    if ctx.get("answered_since_reply"):
        return "no_action", "Someone already replied to this lead in Smartlead."

    if not ctx.get("hydrated", True):
        return "review", "Held for review: couldn't load the Smartlead thread."

    # 2. intent(s) within what this agent is allowed to answer alone
    if not primary:
        return "review", "Held for review: couldn't tell what the lead is asking for."
    allowed = set(agent.get("allowed_intents") or []) | {"scheduling"}
    off_intent = next((i for i in all_intents if i not in allowed), None)
    if off_intent:
        return "review", _INTENT_REASON.get(off_intent,
                                            "Held for review: the lead is asking for something this agent isn't allowed to answer alone.")
    if "pricing" in all_intents and not (agent.get("pricing_notes") or "").strip():
        return "review", "Held for review: no pricing notes are set for this agent, so pricing questions need a person."

    # 3. simple ask + confidence
    try:
        threshold = float(agent.get("confidence_threshold") or 0.9)
    except (TypeError, ValueError):
        threshold = 0.9
    if not simple_ask or confidence < threshold:
        return "review", "Held for review: not confident enough this is a simple ask."

    # 3b. same-day scheduling asks can't be met by two fixed future slots
    if ctx.get("same_day_ask") and "scheduling" in all_intents:
        return "review", "Held for review: the lead wants to talk today, which needs a person right now."

    # 4. no red flags, ours or the model's
    if llm_red_flags or red_flag_hits:
        return "review", "Held for review: the reply contains language that needs a careful human read."

    # 5. Smartlead's own categoriser veto (independent check)
    if category in CATEGORY_VETO:
        return "review", f"Held for review: Smartlead already categorised this as {category}."

    # 6. first touch only - a second reply from the same lead always goes to a human
    if not ctx.get("first_touch", True):
        return "review", "Held for review: this lead has replied before, so a person should take it."

    # 7. slots + timezone must both be ready
    if ctx.get("timezone") is None:
        return "review", "Held for review: couldn't work out the lead's timezone."
    slot_status = ctx.get("slot_status")
    if slot_status != "ok":
        reason_map = {
            "not_configured": "Held for review: Calendly is not connected.",
            "none_available": "Held for review: no Calendly availability inside the next few working days.",
            "error": "Held for review: couldn't load Calendly availability.",
        }
        return "review", reason_map.get(slot_status, "Held for review: call times aren't ready.")

    # 8. length + lint
    if int(ctx.get("body_len") or 0) > 1500:
        return "review", "Held for review: the reply is long and detailed, better for a human."
    if not ctx.get("lint_ok", False):
        return "review", ctx.get("lint_reason") or "Held for review: the draft didn't pass its checks."

    # 9. mode + the global master switch, checked LAST on purpose: a held row
    # then carries its most informative reason, and in review mode (switch
    # off) the user can see exactly which drafts WOULD have sent themselves.
    if agent.get("mode") != "autopilot" or not agent.get("enabled", True):
        return "review", "Held for review: every check passed, but this agent is set to draft only."
    if not ctx.get("autopilot_enabled", False):
        return "review", "Held for review: every check passed, but the autopilot master switch is off."

    return "auto_send", "Meets every autopilot condition."


# ── OpenAI calls (classify + draft) ─────────────────────────────────────────

CLASSIFY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "primary_intent": {"type": "string", "enum": INTENTS},
        "all_intents": {"type": "array", "items": {"type": "string", "enum": INTENTS}},
        "simple_ask": {"type": "boolean"},
        "confidence": {"type": "number"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "timezone_guess": {"type": ["string", "null"]},
        "tz_confidence": {"type": "number"},
        "live_lead": {"type": "boolean"},
        "wants": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["primary_intent", "all_intents", "simple_ask", "confidence", "red_flags",
                "timezone_guess", "tz_confidence", "live_lead", "wants", "rationale"],
}

CLASSIFY_SYSTEM = """You classify one inbound cold-email reply for an appointment-setter agent that can ONLY do three things: send a fixed resource link, quote fixed pricing text verbatim, or propose two fixed call-time slots plus a booking link. Nothing else is answerable without a human.

Intents (pick exactly one primary_intent; list every intent that genuinely applies in all_intents):
- send_resource: the lead wants more info, wants the resource, or gave an unqualified yes ("sure", "send it", "interested", "know more"). The resource IS the "more info".
- pricing: a pricing question, ONLY when the agent's pricing_notes (given to you below) literally already contains the answer. If pricing_notes is empty, or doesn't cover what's specifically asked, this is objection_or_question instead, not pricing. A plain, unconditional "what's the price?" / "how much does it cost?" with non-empty pricing_notes IS pricing with simple_ask=true - quoting the notes verbatim answers it fully.
- scheduling: wants to book a call, gave availability, or asked to schedule, AND a plain two-slot-plus-booking-link answer would be a faithful reply. Scheduling is a simple ask ONLY when the lead is flexible about timing (several days offered, "sometime next week", "send me some options" with no date named). If they name ONE specific day, date, or time ("Friday after 2:30", "the 24th", "next Thursday"), or ask for TODAY/tonight/"earlier"/"asap", set simple_ask=false - our two fixed slots may not match what they asked for.
- bespoke_request: wants something made specifically for them - a Loom or video recorded for them, an audit or breakdown OF THEIR company or website, anything "specific to us". EXCEPTION: if the agent's own resource_name/resource_description below says the fixed resource already IS that video/audit, sending it is send_resource, not bespoke_request.
- objection_or_question: needs judgement or nuance - a direct question not answerable purely from pricing_notes, a fit/commission/industry question, "where are you based", a conditional commitment ("if X then we'd try it" - a CONDITION anywhere always means simple_ask=false, even when pricing_notes seems to answer it), or ANY report that a link, video, or resource did not work or arrive ("link didn't work", "couldn't watch the video", "can you send it again?" after a failure) - something may genuinely be broken, so a person must check before anything is re-sent.
- not_interested: a plain no or decline, not hostile.
- unsubscribe_dnc: asks to be removed, to stop contacting them, to cease, or is hostile/legal in tone (lawyer, GDPR, complaint). ALWAYS this intent even if the message is short and looks polite, e.g. "kindly cease" or "remove me" - never send_resource just because it reads politely.
- ooo: an out-of-office autoreply.
- wrong_person: says they are not the right contact (may name a colleague instead).
- bounce_or_system: a bounce, spam-block, or other system notice, not a human reply.
- other: none of the above fit.

simple_ask is true ONLY if the ENTIRE reply is satisfiable by (a) sending the resource, (b) quoting pricing_notes verbatim, or (c) proposing our two call slots plus the booking link - with nothing else needed, no unanswered question, no invented fact. If the reply contains ANY question, condition, or ask outside those three things, set simple_ask=false even if the primary intent looks simple. When genuinely ambiguous, simple_ask=false.

Two further rules:
- IGNORE the sender's own email signature when working out the ask: their phone numbers, their own booking/calendar links, social handles, follower counts, taglines, and legal footers are not part of the request. Never treat a link in THEIR signature as them asking us to schedule.
- A bare one-word or near-bare affirmation ("Yes", "OK", "sure") is a simple send_resource ask ONLY when the last message WE sent (given to you as last_outbound below, when available) makes the referent unmistakable - e.g. we asked "want me to send the breakdown?" and they said "Yes". If last_outbound is missing or its ask is not unmistakable, set simple_ask=false.

live_lead: true when a reply that is otherwise a negative still contains a real opening someone should act on - a named replacement contact or referral ("Nick left, contact wim@..."), an explicit later-date opening ("not a priority right now, try me in Q3", "maybe later"), or a request to follow up at some point. Plain "no", plain opt-outs, plain out-of-office autoreplies with generic reception redirects are live_lead=false.

confidence: 0 to 1, your own honest confidence in this call - not a proxy for how short the message is.
red_flags: list any hostile/legal/opt-out language you notice (a second deterministic pass also checks this; do not rely on this list alone).
timezone_guess: an IANA tz name if the reply or signature strongly implies one (city, area code, country), else null. tz_confidence 0 to 1.
wants: one plain-English line - what the lead is actually asking for.
rationale: one line - why you chose this intent.

Replies in ANY language get the same rules ("Oui pourquoi ne pas essayer, mais je n'ai pas encore le site web" contains a caveat - simple_ask=false). If you cannot fully understand the reply, simple_ask=false.

Never invent facts. Examples of the exact reasoning to apply (do not copy their wording, just the logic):
- "Wrong on all counts. Victoria Parkin is heading that division." -> wrong_person AND live_lead=true (a named better contact is an opening someone should act on).
- "sure!" -> send_resource, simple_ask=true, high confidence.
- "Kindly cease" -> unsubscribe_dnc, simple_ask=false, even though it is short and polite.
- "No thanks, Bjion." -> not_interested.
- "Can you share the video?" -> send_resource ONLY if the agent's resource description says it already is that video; otherwise bespoke_request.
- "Could you record a quick Loom walking through how this would work for our agency specifically?" -> bespoke_request, simple_ask=false.
- "So you work on commission?" -> objection_or_question, UNLESS pricing_notes literally answers commission structure, then pricing.
- "Your message ... couldn't be delivered ... spam block list" -> bounce_or_system.
- A reply that reports a broken link AND asks a separate out-of-scope question -> simple_ask=false (the extra question is not answerable from fixed resources)."""


def classify(reply: dict, agent: dict) -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    reply = reply or {}
    agent = agent or {}
    user = json.dumps({
        "reply_subject": reply.get("subject") or "",
        "reply_body": (reply.get("body") or "")[:4000],
        # the last message WE sent before this reply - lets the model resolve
        # a bare "Yes" against what was actually offered
        "last_outbound": (reply.get("last_outbound") or "")[:800],
        "agent": {
            "resource_name": agent.get("resource_name") or "",
            "resource_description": agent.get("resource_description") or "",
            "pricing_notes": agent.get("pricing_notes") or "",
            "allowed_intents": agent.get("allowed_intents") or [],
        },
    })
    r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
             {"Authorization": f"Bearer {key}"},
             {"model": OPENAI_MODEL,
              "messages": [{"role": "system", "content": CLASSIFY_SYSTEM},
                          {"role": "user", "content": user}],
              "response_format": {"type": "json_schema", "json_schema": {
                  "name": "setter_classification", "strict": True, "schema": CLASSIFY_SCHEMA}}})
    if not isinstance(r, dict):
        raise RuntimeError("OpenAI: empty response")
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {str(r['error'].get('message', r['error']))[:200]}")
    return json.loads(r["choices"][0]["message"]["content"])


DRAFT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"subject": {"type": "string"}, "html": {"type": "string"}},
    "required": ["subject", "html"],
}

DRAFT_SYSTEM = """You write the reply for a cold-email appointment-setter agent, in this exact house style. Mirror the shape precisely, filling in the brackets:

Hi {First},

{one short ack line, e.g. "Of course." or "Great to hear from you."}

<a href="{resource_link}">{natural anchor text describing the resource}</a>

Would you be free for a call on {day 1} at {time 1} or {day 2} at {time 2}, so that I can walk you through how it applies to {their context}?

If neither works, feel free to book in here: {booking_link}

Best,
{SenderFirst}

Rules:
- No em dashes anywhere, ever - use a comma or period instead.
- No emoji.
- Plain English, under 160 words total.
- Only include the resource link/anchor when send_resource is one of the intents to answer.
- Anchor text reads like the real examples: "Here's the breakdown I prepared." or "Here's a case study I put together." - natural, first-person, never the bare resource title.
- When the intent is bespoke_request, objection_or_question, or wrong_person, the ack line must acknowledge the lead's SPECIFIC ask honestly (e.g. "Happy to put a video together for you.") - never a generic "Of course." that ignores what they asked for, and never a promise of a date or deadline for the bespoke work.
- Never say you are sharing, attaching, or sending something the draft does not actually contain. If the asked-for asset is not the agent's fixed resource, acknowledge the ask ("Happy to get that over to you.") without implying it is included in this email.
- The ack must answer the SHAPE of the question. A yes/no question ("So you work on commission?") gets a direct, truthful opener grounded ONLY in the pricing notes ("Good question - it is a flat monthly fee rather than commission."), never "Of course."
- BEFORE writing anything, decide the greeting name: use lead_first_name if given; otherwise LOOK AT THE END OF THEIR REPLY for a signed name ("Thanks, Cole" / "Kelly, Head of Partnerships" means greet "Hi Cole" / "Hi Kelly"); only if no name exists anywhere use "Hi there". NEVER greet the lead with SenderFirst - that is OUR name, used only in the sign-off.
- If they ask for "the video" and the agent's fixed resource is NOT a video, never present the resource link as if it were the video. Acknowledge the video ask specifically and honestly; the human reviewer will attach the right asset.
- If a question's answer is NOT in the pricing notes or the resource, do not improvise one. Acknowledge it and make it the reason for the call: "That's exactly what I'd walk you through on a quick call." Guessing at policies, capabilities, or processes is worse than not answering.
- If SenderFirst is empty, end with just "Best," and no name on the line after.
- Only include the two call-time links (as anchors on the day/time text) when slots are supplied and slot_status is "ok"; otherwise skip the two-slot paragraph and instead ask "How does this week look for a quick call?" and include only the booking link.
- If pricing is one of the intents, quote the pricing_notes content verbatim (the actual numbers/structure) rather than paraphrasing them away.
- If the intent needs a human (bespoke, objection, other, wrong_person, etc.) still write a warm, honest best-effort draft for a human to edit - never invent a fact, number, or promise not present in the resource, pricing notes, or thread; keep it short and let the human add specifics.
- Never invent a number, date, or fact that isn't in the pricing notes, the reply thread, or the call-time slots given to you.
- Match the tone of the voice examples given.
- Output STRICT JSON: {"subject": "...", "html": "..."}. subject should read "Re: {original subject}" (or a sensible one if none given). html is the full reply body as described above, using <a href="..."> for links, no markdown."""


def draft_reply(reply: dict, agent: dict, classification: dict, slots: list, slot_status: str, sender_first: str) -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    reply = reply or {}
    agent = agent or {}
    classification = classification or {}
    user = json.dumps({
        "lead_first_name": reply.get("first_name") or "there",
        "original_subject": reply.get("subject") or "",
        "reply_body": (reply.get("body") or "")[:3000],
        "wants": classification.get("wants") or "",
        "primary_intent": classification.get("primary_intent") or "",
        "all_intents": classification.get("all_intents") or [],
        "resource_name": agent.get("resource_name") or "",
        "resource_link": agent.get("resource_link") or "",
        "resource_description": agent.get("resource_description") or "",
        "pricing_notes": agent.get("pricing_notes") or "",
        "booking_link": agent.get("booking_link") or "",
        "voice_examples": agent.get("voice_examples") or [],
        "extra_instructions": agent.get("extra_instructions") or "",
        "slots": slots or [],
        "slot_status": slot_status or "not_configured",
        "sender_first": sender_first or "",
    })
    r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
             {"Authorization": f"Bearer {key}"},
             {"model": OPENAI_MODEL,
              "messages": [{"role": "system", "content": DRAFT_SYSTEM},
                          {"role": "user", "content": user}],
              "response_format": {"type": "json_schema", "json_schema": {
                  "name": "setter_draft", "strict": True, "schema": DRAFT_SCHEMA}}})
    if not isinstance(r, dict):
        raise RuntimeError("OpenAI: empty response")
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {str(r['error'].get('message', r['error']))[:200]}")
    data = json.loads(r["choices"][0]["message"]["content"])
    html_body = (data.get("html") or "").replace("—", ", ")
    # The model occasionally emits a C0 control byte where an apostrophe
    # belongs (seen live: U+0019 inside "Here's") - it renders as a broken
    # glyph in a real inbox. Scrub every control char except newline/tab.
    html_body = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "'", html_body)
    subject = data.get("subject") or f"Re: {reply.get('subject') or ''}"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return {"subject": subject, "html": html_body}


# ── Smartlead helpers ────────────────────────────────────────────────────────

def _sl_key():
    return _KEYS.get("SMARTLEAD_API_KEY")


def _sl_get(path: str, params: dict = None):
    key = _sl_key()
    if not key:
        return None
    qs = dict(params or {})
    qs["api_key"] = key
    return _HTTP("GET", f"{SMARTLEAD_BASE}{path}?{urlencode(qs)}", {})


def _sl_post(path: str, body: dict, params: dict = None):
    key = _sl_key()
    if not key:
        return None
    qs = dict(params or {})
    qs["api_key"] = key
    return _HTTP("POST", f"{SMARTLEAD_BASE}{path}?{urlencode(qs)}", {}, body)


def hydrate_lead(campaign_id, email: str, message_id: str):
    """Mirrors db/smartlead_daily_sync.ts's slGet('/leads/', {email}) + per-lead
    message-history usage, defensively (Smartlead's exact wrapper shape isn't
    pinned). Returns (ok, data, error)."""
    try:
        lead_resp = _sl_get("/leads/", {"email": email})
        lead = None
        if isinstance(lead_resp, dict):
            lead = lead_resp.get("lead") if isinstance(lead_resp.get("lead"), dict) else lead_resp
        elif isinstance(lead_resp, list) and lead_resp:
            first = lead_resp[0]
            lead = first.get("lead") if isinstance(first, dict) and isinstance(first.get("lead"), dict) else first
        if not isinstance(lead, dict) or not lead.get("id"):
            return False, {}, "Couldn't find this lead in Smartlead."
        lead_id = lead["id"]

        hist_resp = _sl_get(f"/campaigns/{campaign_id}/leads/{lead_id}/message-history")
        if hist_resp is None:
            return False, {}, "Couldn't load the Smartlead thread."
        hist = hist_resp.get("history") if isinstance(hist_resp, dict) else hist_resp
        if not isinstance(hist, list):
            hist = []

        norm = []
        for m in hist:
            if not isinstance(m, dict):
                continue
            frm = m.get("from") if isinstance(m.get("from"), dict) else {}
            norm.append({
                "type": str(m.get("type") or "").upper(),
                "time": m.get("time") or m.get("sent_time") or m.get("created_at"),
                "subject": m.get("subject"),
                "body": m.get("email_body") or m.get("body") or "",
                "stats_id": m.get("stats_id"),
                "message_id": m.get("message_id"),
                "from_name": m.get("from_name") or m.get("sender_name") or frm.get("name"),
            })
        norm.sort(key=lambda x: x["time"] or "")
        replies = [m for m in norm if m["type"] == "REPLY"]
        target = None
        if message_id:
            target = next((m for m in replies
                          if str(m.get("stats_id")) == str(message_id) or str(m.get("message_id")) == str(message_id)),
                         None)
        if not target and replies:
            target = replies[-1]
        if not target:
            return False, {}, "Couldn't find the reply in the Smartlead thread."

        sent = [m for m in norm if m["type"] == "SENT"]
        sender_first = ""
        if sent:
            name = sent[-1].get("from_name") or ""
            sender_first = name.split()[0] if name else ""

        # Was this reply already answered in the thread (by a person in
        # Smartlead, or an earlier run)? If so the pipeline must not draft
        # over them, and must never double-reply.
        answered_since_reply = False
        try:
            t_dt = _parse_iso(target.get("time")) if target.get("time") else None
            if t_dt:
                for m in sent:
                    if m.get("time") and _parse_iso(m["time"]) > t_dt:
                        answered_since_reply = True
                        break
        except Exception:  # noqa: BLE001 - unparseable times must not break hydration
            answered_since_reply = False

        return True, {
            "smartlead_lead_id": lead_id,
            "first_name": lead.get("first_name") or "",
            "last_name": lead.get("last_name") or "",
            "email_stats_id": target.get("stats_id"),
            "reply_message_id": target.get("message_id") or message_id,
            "reply_email_time": target.get("time"),
            "reply_email_body": target.get("body") or "",
            "reply_subject": target.get("subject") or "",
            "thread": norm[-3:],
            "sender_first": sender_first,
            "answered_since_reply": answered_since_reply,
        }, ""
    except Exception as e:  # noqa: BLE001 - a hydration crash must degrade to review, never kill the run
        return False, {}, f"Couldn't load the Smartlead thread ({type(e).__name__})."


# ── Calendly ─────────────────────────────────────────────────────────────────

def get_calendly_availability(agent: dict, settings: dict, now_utc):
    """Returns (slot_status, avail_iso_list, error). slot_status in
    {ok, not_configured, none_available, error}. Caches the resolved Calendly
    user uri onto settings['_calendly_user_uri'] for the caller to persist."""
    agent = agent or {}
    settings = settings or {}
    token = settings.get("calendly_token")
    if not token:
        return "not_configured", [], ""
    try:
        user_uri = settings.get("_calendly_user_uri")
        headers = {"Authorization": f"Bearer {token}"}
        if not user_uri:
            me = _HTTP("GET", "https://api.calendly.com/users/me", headers)
            user_uri = isinstance(me, dict) and (me.get("resource") or {}).get("uri")
            if not user_uri:
                return "error", [], "Couldn't connect to Calendly with this token."
            settings["_calendly_user_uri"] = user_uri

        ev = _HTTP("GET", f"https://api.calendly.com/event_types?user={quote(user_uri, safe='')}", headers)
        items = (ev or {}).get("collection") or [] if isinstance(ev, dict) else []
        target_slug = (agent.get("calendly_event_url") or "").rstrip("/").rsplit("/", 1)[-1]
        event_type_uri = None
        for it in items:
            uri = it.get("uri") or ""
            slug = it.get("slug") or uri.rstrip("/").rsplit("/", 1)[-1]
            if target_slug and (slug == target_slug or target_slug in uri):
                event_type_uri = uri
                break
        if not event_type_uri:
            return "error", [], "Couldn't find this agent's Calendly event type."

        now_utc = _parse_iso(now_utc) if not isinstance(now_utc, _dt.datetime) else (
            now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=_dt.timezone.utc))
        horizon_days = int(settings.get("horizon_working_days") or 5)
        span_days = max(horizon_days + 4, 7)
        # Calendly rejects a start_time that isn't strictly in the future -
        # starting at "now" exactly made the first (and usually only) chunk
        # 400 silently, which read back as "no availability" while real slots
        # existed. Start a few minutes ahead, and surface chunk errors.
        cursor = now_utc + _dt.timedelta(minutes=5)
        end_of_range = now_utc + _dt.timedelta(days=span_days)
        avail = []
        chunk_days = 7
        chunk_errors = []
        while cursor < end_of_range:
            chunk_end = min(cursor + _dt.timedelta(days=chunk_days), end_of_range)
            params = {
                "event_type": event_type_uri,
                "start_time": cursor.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                "end_time": chunk_end.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            }
            data = _HTTP("GET", f"https://api.calendly.com/event_type_available_times?{urlencode(params)}", headers)
            if isinstance(data, dict) and isinstance(data.get("collection"), list):
                for slot in data["collection"]:
                    st = slot.get("start_time")
                    if st:
                        avail.append(st)
            else:
                chunk_errors.append(str(data)[:150])
            cursor = chunk_end
        if chunk_errors and not avail:
            return "error", [], f"Calendly availability lookup failed: {chunk_errors[0]}"
        if not avail:
            return "none_available", [], ""
        return "ok", avail, ""
    except Exception as e:  # noqa: BLE001 - Calendly outage must degrade to review, never kill the run
        return "error", [], f"Couldn't load Calendly availability ({type(e).__name__})."


# ── Supabase-backed agent/settings/queue CRUD ───────────────────────────────

def _load_settings() -> dict:
    if not _SB:
        return {}
    try:
        rows = _SB("GET", f"{AGENTS_TABLE}?id=eq.{SETTINGS_ID}&select=doc")
        if isinstance(rows, list) and rows:
            return dict(rows[0].get("doc") or {})
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_settings(doc: dict):
    if not _SB:
        return
    _SB("POST", f"{AGENTS_TABLE}?on_conflict=id", {"id": SETTINGS_ID, "doc": doc},
       prefer="resolution=merge-duplicates,return=minimal")


def _load_agents() -> list:
    if not _SB:
        return []
    try:
        rows = _SB("GET", f"{AGENTS_TABLE}?id=neq.{SETTINGS_ID}&select=doc")
        if isinstance(rows, list):
            return [r.get("doc") or {} for r in rows if isinstance(r, dict)]
    except Exception:  # noqa: BLE001
        pass
    return []


def _load_agent(agent_id):
    if not agent_id:
        return None
    for a in _load_agents():
        if a.get("id") == agent_id:
            return a
    return None


def _agent_for_campaign(campaign_id, require_enabled: bool = True, agents=None):
    agents = agents if agents is not None else _load_agents()
    want = str(campaign_id)
    for a in agents:
        if require_enabled and not a.get("enabled", True):
            continue
        if want in [str(c) for c in (a.get("campaign_ids") or [])]:
            return a
    return None


def _save_agent(doc: dict) -> dict:
    doc = dict(doc or {})
    if not doc.get("id"):
        doc["id"] = f"agent-{uuid.uuid4().hex[:8]}"
    else:
        # Merge onto the stored doc so a partial payload (an API caller that
        # only sends the fields it changed) can never silently wipe the rest -
        # a mode-only re-save once erased an agent's pricing notes this way.
        existing = _load_agent(doc["id"])
        if existing:
            doc = {**existing, **doc}
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    doc.setdefault("created_at", now)
    doc["updated_at"] = now
    doc.setdefault("mode", "draft_only")
    doc.setdefault("enabled", True)
    doc.setdefault("campaign_ids", [])
    doc.setdefault("allowed_intents", [])
    doc.setdefault("confidence_threshold", 0.9)
    doc.setdefault("voice_examples", [])
    doc.setdefault("pricing_notes", "")
    doc.setdefault("extra_instructions", "")
    # Stamp when each campaign was first assigned - the poll only processes
    # replies received after this, so activating an agent never sweeps an
    # already-handled backlog into the queue.
    stamps = dict(doc.get("campaign_assigned_at") or {})
    for cid in (doc.get("campaign_ids") or []):
        stamps.setdefault(str(cid), now)
    doc["campaign_assigned_at"] = {k: v for k, v in stamps.items()
                                   if k in {str(c) for c in (doc.get("campaign_ids") or [])}}
    if _SB:
        _SB("POST", f"{AGENTS_TABLE}?on_conflict=id", {"id": doc["id"], "doc": doc},
           prefer="resolution=merge-duplicates,return=minimal")
    return doc


def _existing_row(workspace: str, campaign_id, email: str, message_id: str):
    if not _SB:
        return None
    try:
        rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{workspace}&smartlead_campaign_id=eq.{campaign_id}"
                          f"&lead_email=eq.{email}&message_id=eq.{message_id}&select=*&limit=1")
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001
        return None


def _apply_patch(row: dict, patch: dict):
    if _SB and row.get("id") is not None:
        try:
            _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{row['id']}", patch)
        except Exception:  # noqa: BLE001
            pass


def _company_hints(domain: str) -> dict:
    if not domain or not _SB:
        return {}
    try:
        rows = _SB("GET", f"companies?domain=eq.{domain}&select=city,state,country&limit=1")
        if isinstance(rows, list) and rows:
            r = rows[0]
            return {"city": r.get("city"), "state": r.get("state"), "country": r.get("country")}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _dry_run() -> bool:
    # Honoured from the environment at CALL time (not import time) so tests
    # can flip it mid-run: `SETTER_DRY_RUN=1` skips every real Smartlead send.
    return os.environ.get("SETTER_DRY_RUN") == "1"


def _send_reply(row: dict, agent: dict, subject: str, html_body: str, is_test: bool = False,
                success_status: str = "sent") -> dict:
    """Sends (or stub-sends) one reply. Returns {"ok": bool, "row": <patch dict>}.
    is_test rows NEVER hit Smartlead regardless of SETTER_DRY_RUN."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    dry = bool(is_test) or _dry_run()
    if dry:
        patch = {"status": success_status, "sent_at": now, "sent_body": html_body, "error": None,
                 "draft_subject": subject, "draft_body": html_body}
        _apply_patch(row, patch)
        if _LOG:
            try:
                _LOG("/api/setter/queue/action", {"id": row.get("id"), "action": "send", "sent_via": "dry_run"},
                    action="send", entity="setter_queue", entity_id=row.get("id"))
            except Exception:  # noqa: BLE001
                pass
        patch["sent_via"] = "dry_run"
        return {"ok": True, "row": patch}
    try:
        body = {
            "email_stats_id": row.get("email_stats_id"),
            "email_body": html_body,
            "reply_message_id": row.get("message_id"),
            "reply_email_time": row.get("replied_at"),
            "reply_email_body": row.get("reply_body"),
            "to_email": row.get("lead_email"),
            "to_first_name": row.get("lead_first_name") or "",
            "add_signature": False,
        }
        resp = _sl_post(f"/campaigns/{row.get('smartlead_campaign_id')}/reply-email-thread", body)
        ok = isinstance(resp, dict) and not resp.get("error")
        if not ok:
            patch = {"status": "needs_review", "error": str(resp)[:300]}
            _apply_patch(row, patch)
            return {"ok": False, "row": patch}
        patch = {"status": success_status, "sent_at": now, "sent_body": html_body, "error": None,
                 "draft_subject": subject, "draft_body": html_body}
        _apply_patch(row, patch)
        if _LOG:
            try:
                _LOG("/api/setter/queue/action", {"id": row.get("id"), "action": "send"},
                    action="send", entity="setter_queue", entity_id=row.get("id"))
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "row": patch}
    except Exception as e:  # noqa: BLE001 - a send crash must land as needs_review, never raise
        patch = {"status": "needs_review", "error": str(e)[:300]}
        _apply_patch(row, patch)
        return {"ok": False, "row": patch}


def _finalize_row(row: dict) -> dict:
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    row.setdefault("created_at", now_iso)
    row["updated_at"] = now_iso
    if not _SB:
        row.setdefault("id", None)
        return row
    try:
        if row.get("id") is not None:
            # The pipeline claimed this row at intake - finish it in place.
            _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{row['id']}",
                {k: v for k, v in row.items() if k not in ("id", "created_at")})
            return row
        ins = _SB("POST", f"{QUEUE_TABLE}?on_conflict=workspace,smartlead_campaign_id,lead_email,message_id",
                  {k: v for k, v in row.items() if k != "id"},
                  prefer="resolution=ignore-duplicates,return=representation")
        if isinstance(ins, list) and ins:
            return ins[0]
        existing = _existing_row(row.get("workspace"), row.get("smartlead_campaign_id"),
                                 row.get("lead_email"), row.get("message_id"))
        return existing or row
    except Exception as e:  # noqa: BLE001
        row["error"] = row.get("error") or f"db insert failed: {type(e).__name__}"
        return row


# ── the pipeline ─────────────────────────────────────────────────────────────

def process_reply(reply: dict, agent: dict, settings: dict) -> dict:
    """Runs the full intake -> hydrate -> classify -> slots -> draft -> lint ->
    decide -> (send | leave queued) pipeline for one reply. Returns the
    finished setter_queue row dict. Never raises - a crash lands as a best-
    effort needs_review row instead of killing the poll/route."""
    try:
        return _process_reply_inner(reply or {}, agent or {}, settings or {})
    except Exception as e:  # noqa: BLE001 - the pipeline must never crash its caller
        reply = reply or {}
        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        err_row = {
            "workspace": reply.get("workspace") or WORKSPACE,
            "smartlead_campaign_id": reply.get("campaign_id"),
            "agent_id": (agent or {}).get("id"),
            "lead_email": (reply.get("email") or "").strip().lower(),
            "message_id": str(reply.get("message_id") or ""),
            "reply_body": reply.get("body") or "",
            "status": "error", "decision": "review",
            "decision_reason": "Held for review: something went wrong processing this reply.",
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "is_test": bool(reply.get("is_test")),
            "created_at": now_iso, "updated_at": now_iso,
        }
        # If the pipeline had already claimed a DB row, mark it errored so it
        # can't sit invisible in status "new" forever.
        claimed = reply.get("_claimed_id")
        if claimed is not None and _SB:
            try:
                _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{claimed}",
                    {"status": "error", "decision": "review",
                     "decision_reason": err_row["decision_reason"], "error": err_row["error"],
                     "updated_at": now_iso})
                err_row["id"] = claimed
            except Exception:  # noqa: BLE001
                pass
        return err_row


def _process_reply_inner(reply: dict, agent: dict, settings: dict) -> dict:
    workspace = reply.get("workspace") or WORKSPACE
    campaign_id = reply.get("campaign_id")
    email = (reply.get("email") or "").strip().lower()
    message_id = str(reply.get("message_id") or "")
    is_test = bool(reply.get("is_test"))

    if not is_test:
        existing = _existing_row(workspace, campaign_id, email, message_id)
        if existing:
            return existing

    now = _dt.datetime.now(_dt.timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    domain = (reply.get("company_domain") or (email.split("@", 1)[1] if "@" in email else "")).lower()

    row = {
        "workspace": workspace, "smartlead_campaign_id": campaign_id, "agent_id": agent.get("id"),
        "lead_email": email, "lead_first_name": reply.get("first_name") or "",
        "lead_last_name": reply.get("last_name") or "", "company_domain": domain,
        "message_id": message_id, "reply_subject": reply.get("subject") or "",
        "reply_body": reply.get("body") or "", "replied_at": reply.get("replied_at") or now_iso,
        "category": reply.get("category"), "thread": [], "smartlead_lead_id": None,
        "email_stats_id": None, "classification": None, "guardrails": None,
        "timezone": None, "slots": [], "draft_subject": None, "draft_body": None,
        "decision": None, "decision_reason": None, "status": "new",
        "added_to_subsequence": False, "sent_at": None, "sent_body": None, "error": None,
        "is_test": is_test,
    }

    # Claim the row BEFORE any slow work. Two intake paths can race on the
    # same reply (the Smartlead webhook and the cron poll); the unique key +
    # ignore-duplicates insert makes exactly one claimant win, so a reply can
    # never be classified twice or, worse, auto-sent twice.
    if not is_test and _SB:
        try:
            claim = {k: row[k] for k in (
                "workspace", "smartlead_campaign_id", "agent_id", "lead_email", "lead_first_name",
                "lead_last_name", "company_domain", "message_id", "reply_subject", "reply_body",
                "replied_at", "category", "is_test")}
            claim["status"] = "new"
            ins = _SB("POST", f"{QUEUE_TABLE}?on_conflict=workspace,smartlead_campaign_id,lead_email,message_id",
                      claim, prefer="resolution=ignore-duplicates,return=representation")
            if isinstance(ins, list):
                if not ins:  # someone else already claimed it
                    existing = _existing_row(workspace, campaign_id, email, message_id)
                    if existing:
                        return existing
                else:
                    row["id"] = ins[0].get("id")
                    reply["_claimed_id"] = row["id"]  # lets the crash handler mark this row errored
        except Exception:  # noqa: BLE001 - claim is an optimisation; the final upsert still dedupes
            pass

    sender_first = reply.get("sender_first") or ""
    hydrated = True
    answered_since_reply = False
    if not is_test:
        ok, hyd, herr = hydrate_lead(campaign_id, email, message_id)
        if not ok:
            row.update({
                "status": "needs_review", "decision": "review",
                "decision_reason": herr or "Couldn't load the Smartlead thread",
                "error": herr or "hydration failed",
            })
            return _finalize_row(row)
        row["smartlead_lead_id"] = hyd.get("smartlead_lead_id")
        row["email_stats_id"] = hyd.get("email_stats_id")
        row["message_id"] = str(hyd.get("reply_message_id") or message_id)
        row["reply_subject"] = hyd.get("reply_subject") or row["reply_subject"]
        row["reply_body"] = hyd.get("reply_email_body") or row["reply_body"]
        row["replied_at"] = hyd.get("reply_email_time") or row["replied_at"]
        row["thread"] = hyd.get("thread") or []
        row["lead_first_name"] = hyd.get("first_name") or row["lead_first_name"]
        row["lead_last_name"] = hyd.get("last_name") or row["lead_last_name"]
        sender_first = hyd.get("sender_first") or sender_first
        answered_since_reply = bool(hyd.get("answered_since_reply"))
        # Hydration can resolve a different (real) message id than the one we
        # claimed under. If another row already owns the real key, the other
        # intake path (webhook vs poll) got here first - stand down rather
        # than process the same reply twice.
        if row["message_id"] != message_id:
            other = _existing_row(workspace, campaign_id, email, row["message_id"])
            if other and other.get("id") != row.get("id"):
                if row.get("id") is not None:
                    _apply_patch(row, {"status": "dismissed", "decision": "no_action",
                                       "decision_reason": "Duplicate intake of the same reply."})
                return other

    # Everything the pipeline READS uses the cleaned text (HTML stripped) -
    # a two-word Outlook reply must not fail the length veto because of its
    # markup. The row keeps the original body for the audit trail and the
    # Smartlead send payload.
    body_text = clean_body(row["reply_body"])

    # the last message WE sent before their reply (classification context for
    # bare "Yes"-style answers); thread is newest-last after hydration
    last_outbound = ""
    for m in reversed(row.get("thread") or []):
        if str(m.get("type") or "").upper() == "SENT":
            last_outbound = _TAG_RE.sub(" ", str(m.get("body") or ""))[:800]
            break

    # timezone hints
    comp_hints = _company_hints(domain)
    tld = domain.rsplit(".", 2)[-1] if domain else ""
    two_part = ".".join(domain.split(".")[-2:]) if domain.count(".") >= 1 else ""
    hints = {
        "country": comp_hints.get("country"), "state": comp_hints.get("state"), "city": comp_hints.get("city"),
        "phone": _extract_phone(body_text), "tld": two_part or tld, "body": body_text,
    }
    tz, _tz_conf = guess_timezone(hints)

    lex_hits = lexicon_hits(body_text)

    try:
        classification = classify({"subject": row["reply_subject"], "body": body_text,
                                   "last_outbound": last_outbound}, agent)
    except Exception as e:  # noqa: BLE001 - a classify outage must degrade to review, never crash
        classification = {
            "primary_intent": None, "all_intents": [], "simple_ask": False, "confidence": 0.0,
            "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0, "wants": "",
            "rationale": f"classification failed: {type(e).__name__}",
        }
        row["error"] = row.get("error") or f"classify failed: {type(e).__name__}"
    row["classification"] = classification

    if not tz and classification.get("timezone_guess"):
        try:
            if float(classification.get("tz_confidence") or 0) >= 0.5:
                tz = classification.get("timezone_guess")
        except (TypeError, ValueError):
            pass
    row["timezone"] = tz

    row["guardrails"] = {"lexicon_hits": lex_hits, "llm_red_flags": classification.get("red_flags") or []}

    category = reply.get("category")
    first_touch = True
    if not is_test:
        try:
            prior = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{workspace}&smartlead_campaign_id=eq.{campaign_id}"
                                f"&lead_email=eq.{email}&status=in.(auto_sent,sent)&select=id&limit=1") if _SB else None
            first_touch = not (isinstance(prior, list) and prior)
        except Exception:  # noqa: BLE001
            first_touch = True

    primary = classification.get("primary_intent")
    try:
        conf = float(classification.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    is_clear_negative = primary in CLEAR_NEGATIVE_INTENTS and conf >= 0.8

    slots, slot_status = [], "not_configured"
    if not is_clear_negative:
        eff_settings = dict(settings)
        eff_settings["_agent"] = agent
        eff_settings["_lead"] = {"first_name": row["lead_first_name"], "last_name": row["lead_last_name"], "email": email}
        # Unknown timezone still gets TENTATIVE slots built in London time so
        # the human reviewer sees concrete times to edit. decide() vetoes
        # auto-send on timezone=None regardless, so this can't mis-send.
        slot_tz = tz or "Europe/London"
        slot_status, avail, serr = get_calendly_availability(agent, eff_settings, now)
        if slot_status == "ok":
            slots = pick_slots(avail, slot_tz, eff_settings, now)
            if not slots:
                slot_status = "none_available"
        if serr and not row.get("error"):
            row["error"] = serr
    row["slots"] = slots

    draft_subject, draft_body = None, None
    if not is_clear_negative:
        try:
            d = draft_reply(
                {"first_name": row["lead_first_name"], "subject": row["reply_subject"], "body": body_text},
                agent, classification, slots, slot_status, sender_first)
            draft_subject, draft_body = d.get("subject"), d.get("html")
        except Exception as e:  # noqa: BLE001 - a draft outage falls back to no draft -> lint fails -> review
            if not row.get("error"):
                row["error"] = f"draft failed: {type(e).__name__}"
    row["draft_subject"], row["draft_body"] = draft_subject, draft_body

    thread_text = " ".join(str(m.get("body") or "") for m in (row.get("thread") or []))
    lint_ok, lint_reason = False, "No draft was produced."
    if draft_body:
        needs_resource_link = "send_resource" in (classification.get("all_intents") or [])
        ctx_lint = {
            "subject": draft_subject, "first_name": row["lead_first_name"],
            "needs_resource_link": needs_resource_link, "resource_link": agent.get("resource_link") or "",
            "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
            "slot_labels": [s.get("label") for s in slots],
            "pricing_notes": agent.get("pricing_notes") or "",
            "thread_text": f"{body_text} {thread_text}",
        }
        lint_ok, lint_reason = lint_draft(draft_body, ctx_lint)

    ctx = {
        "red_flag_hits": lex_hits, "category": category, "first_touch": first_touch,
        "slot_status": slot_status, "timezone": tz, "lint_ok": lint_ok, "lint_reason": lint_reason,
        "body_len": len(body_text or ""), "hydrated": hydrated,
        "answered_since_reply": answered_since_reply,
        "autopilot_enabled": bool(settings.get("autopilot_enabled")),
        "same_day_ask": bool(_SAME_DAY_RE.search(_strip_quoted(body_text or ""))),
    }
    decision, reason = decide(classification, agent, ctx)
    row["decision"], row["decision_reason"] = decision, reason

    if decision == "no_action":
        row["status"] = "no_action"
        row["draft_subject"], row["draft_body"] = None, None
    elif decision == "auto_send":
        result = _send_reply(row, agent, draft_subject or f"Re: {row['reply_subject']}", draft_body or "",
                             is_test=is_test, success_status="auto_sent")
        row.update(result.get("row") or {})
        if not result.get("ok"):
            row["decision"] = "review"
            row["decision_reason"] = "Held for review: the send failed, please check manually."
    else:
        row["status"] = "needs_review"

    return _finalize_row(row)


# ── poll (cron + "check now") ────────────────────────────────────────────────

def run_poll() -> dict:
    """Sweeps recent `replies` rows across every enabled agent's campaigns,
    skips anything already queued, and runs process_reply on up to 15 per
    tick. Never raises."""
    summary = {"checked": 0, "queued": 0, "auto_sent": 0, "needs_review": 0, "no_action": 0, "errors": 0}
    try:
        if not _SB:
            return summary
        agents = _load_agents()
        enabled_agents = [a for a in agents if a.get("enabled", True) and (a.get("campaign_ids") or [])]
        campaign_ids = sorted({str(c) for a in enabled_agents for c in (a.get("campaign_ids") or [])})
        if not campaign_ids:
            return summary
        settings = _load_settings()
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat()
        ids_csv = ",".join(campaign_ids)
        replies = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&smartlead_campaign_id=in.({ids_csv})"
                             f"&replied_at=gte.{since}&order=replied_at.asc&limit=200"
                             f"&select=id,smartlead_campaign_id,email,replied_at,category,"
                             f"reply_subject,reply_body,smartlead_message_id")
        if not isinstance(replies, list):
            return summary
        processed = 0
        for r in replies:
            if processed >= 15:
                break
            if not isinstance(r, dict):
                continue
            cid = r.get("smartlead_campaign_id")
            email = (r.get("email") or "").strip().lower()
            mid = str(r.get("smartlead_message_id") or r.get("message_id") or r.get("id") or "")
            if not cid or not email or not mid:
                continue
            agent = _agent_for_campaign(cid, require_enabled=True, agents=enabled_agents)
            if not agent:
                continue
            # Only replies received AFTER this campaign was assigned to the
            # agent. Without this, first activation would sweep up to 48h of
            # already-humanly-handled backlog into the queue.
            assigned_at = (agent.get("campaign_assigned_at") or {}).get(str(cid))
            if assigned_at and r.get("replied_at"):
                try:
                    if _parse_iso(r["replied_at"]) < _parse_iso(assigned_at):
                        continue
                except (ValueError, TypeError):
                    pass
            if _existing_row(WORKSPACE, cid, email, mid):
                continue
            processed += 1
            summary["checked"] += 1
            reply = {
                "workspace": WORKSPACE, "campaign_id": cid, "email": email,
                "first_name": r.get("first_name"), "last_name": r.get("last_name"),
                "company_domain": r.get("company_domain"), "subject": r.get("reply_subject") or r.get("subject"),
                "body": r.get("reply_body") or r.get("body") or "",
                "replied_at": r.get("replied_at"), "message_id": mid,
                "category": r.get("category"), "is_test": False,
            }
            try:
                row = process_reply(reply, agent, settings)
                summary["queued"] += 1
                status = (row or {}).get("status")
                if status == "auto_sent":
                    summary["auto_sent"] += 1
                elif status == "needs_review":
                    summary["needs_review"] += 1
                elif status == "no_action":
                    summary["no_action"] += 1
            except Exception as e:  # noqa: BLE001 - one bad reply must never stop the sweep
                summary["errors"] += 1
                print(f"[setter] poll error for {email}/{cid}: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - run_poll itself must never raise
        summary["errors"] += 1
        print(f"[setter] run_poll crashed: {e}", file=sys.stderr)
    return summary


# ── live intake: Smartlead EMAIL_REPLY webhook ──────────────────────────────

DEFAULT_BASE_URL = "https://navreo-signals.onrender.com"


def _cron_token() -> str:
    """Same token the /api/cron/* endpoints accept: SIGNAL_PULL_TOKEN, or a
    stable derivation from the service-role key. Used both to guard
    /api/setter/inbound and inside the webhook URL we register."""
    tok = os.environ.get("SIGNAL_PULL_TOKEN") or _KEYS.get("SIGNAL_PULL_TOKEN")
    if tok:
        return tok
    import hashlib
    srk = _KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    return hashlib.sha256((srk + ":signal-pull-v1").encode()).hexdigest()[:40] if srk else ""


def handle_inbound(payload: dict) -> dict:
    """Smartlead EMAIL_REPLY webhook -> the same pipeline as the poll, but
    instant. Defensive across payload shapes; anything it can't read is left
    for the poll sweep to pick up. Never raises."""
    try:
        payload = payload or {}
        et = str(payload.get("event_type") or payload.get("webhook_event_type") or "").upper()
        if et and "REPLY" not in et:
            return {"ignored": f"event {et}"}
        cid = payload.get("campaign_id") or payload.get("campaignId")
        lead = payload.get("lead_data") if isinstance(payload.get("lead_data"), dict) else {}
        email = (payload.get("sl_lead_email") or payload.get("lead_email") or lead.get("email")
                 or payload.get("to_email") or "").strip().lower()
        if not cid or not email:
            return {"ignored": "missing campaign or lead email"}
        agent = _agent_for_campaign(cid)
        if not agent:
            return {"ignored": "no agent assigned to this campaign"}
        rm = payload.get("reply_message") if isinstance(payload.get("reply_message"), dict) else {}
        body = rm.get("text") or _TAG_RE.sub(" ", str(rm.get("html") or "")) or payload.get("reply_body") or ""
        # Key on the email Message-ID (what the poll's `replies` rows also
        # carry) so webhook and poll claim the SAME row. Without a message id
        # we leave the reply to the poll rather than risk a duplicate claim.
        mid = str(rm.get("message_id") or payload.get("message_id") or "")
        if not mid:
            return {"ignored": "no message id in payload - the poll sweep will pick this reply up"}
        reply = {
            "workspace": WORKSPACE, "campaign_id": cid, "email": email,
            "first_name": lead.get("first_name") or payload.get("to_first_name"),
            "last_name": lead.get("last_name") or payload.get("to_last_name"),
            "subject": payload.get("subject") or rm.get("subject") or "",
            "body": body,
            "replied_at": rm.get("time") or payload.get("event_timestamp") or None,
            "message_id": mid, "category": payload.get("lead_category") or None, "is_test": False,
        }
        row = process_reply(reply, agent, _load_settings())
        return {"processed": True, "status": (row or {}).get("status"), "id": (row or {}).get("id")}
    except Exception as e:  # noqa: BLE001 - a webhook must never take the server down
        print(f"[setter] handle_inbound crashed: {e}", file=sys.stderr)
        return {"error": str(e)[:200]}


def ensure_webhooks(agent: dict) -> list:
    """Additively registers the Setter EMAIL_REPLY webhook on each of the
    agent's campaigns that doesn't have one yet. NEVER modifies or removes an
    existing webhook, and verifies the pre-existing list is intact after
    adding (byte-compare by webhook id). Skipped in dry-run mode. Returns a
    per-campaign result list for the UI."""
    agent = agent or {}
    cids = agent.get("campaign_ids") or []
    if _dry_run():
        return [{"campaign_id": c, "ok": True, "skipped": "dry run"} for c in cids]
    if not _sl_key():
        return [{"campaign_id": c, "ok": False, "error": "Smartlead key missing"} for c in cids]
    settings = _load_settings()
    registered = dict(settings.get("webhooks") or {})
    hook_url = f"{(settings.get('public_base_url') or DEFAULT_BASE_URL).rstrip('/')}/api/setter/inbound?token={_cron_token()}"
    results, changed = [], False
    for cid in cids:
        scid = str(cid)
        if scid in registered:
            results.append({"campaign_id": cid, "ok": True, "already": True})
            continue
        try:
            before = _sl_get(f"/campaigns/{cid}/webhooks")
            before = before if isinstance(before, list) else []
            mine = next((w for w in before if isinstance(w, dict)
                        and "/api/setter/inbound" in str(w.get("webhook_url") or "")), None)
            if mine:
                registered[scid] = {"webhook_id": mine.get("id"), "url": mine.get("webhook_url")}
                changed = True
                results.append({"campaign_id": cid, "ok": True, "already": True})
                continue
            # NOTE: no "categories" key - Smartlead 400s on an empty list
            # ("categories does not contain 1 required value(s)"); omitting it
            # means "all categories", which is what we want here.
            resp = _sl_post(f"/campaigns/{cid}/webhooks", {
                "id": None, "name": "Navreo Setter", "webhook_url": hook_url,
                "event_types": ["EMAIL_REPLY"],
            })
            after = _sl_get(f"/campaigns/{cid}/webhooks")
            after = after if isinstance(after, list) else []
            before_by_id = {w.get("id"): json.dumps(w, sort_keys=True) for w in before if isinstance(w, dict)}
            after_by_id = {w.get("id"): json.dumps(w, sort_keys=True) for w in after if isinstance(w, dict)}
            intact = all(after_by_id.get(i) == v for i, v in before_by_id.items())
            new_ids = [i for i in after_by_id if i not in before_by_id]
            wid = (resp.get("id") if isinstance(resp, dict) else None) or (new_ids[0] if len(new_ids) == 1 else None)
            registered_now = wid is not None or any(
                "/api/setter/inbound" in str(w.get("webhook_url") or "") for w in after if isinstance(w, dict))
            ok = intact and registered_now
            if ok:
                registered[scid] = {"webhook_id": wid, "url": hook_url}
                changed = True
            results.append({"campaign_id": cid, "ok": ok, "existing_intact": intact, "webhook_id": wid,
                            "error": None if ok else "couldn't confirm the webhook was added safely"})
        except Exception as e:  # noqa: BLE001 - one campaign failing must not stop the rest
            results.append({"campaign_id": cid, "ok": False, "error": str(e)[:200]})
    if changed:
        settings["webhooks"] = registered
        _save_settings(settings)
    return results


# ── HTTP routes ──────────────────────────────────────────────────────────────

def _qp(params: dict, key: str, default: str = ""):
    v = (params or {}).get(key)
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default


def route_agents_get(_params):
    try:
        agents = _load_agents()
        s = _load_settings()
        return 200, {"agents": agents, "settings": {
            "calendly_connected": bool(s.get("calendly_token")),
            "work_start": s.get("work_start", 9),
            "work_end": s.get("work_end", 17),
            "autopilot_enabled": bool(s.get("autopilot_enabled")),
            "webhooks": s.get("webhooks") or {},
        }}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_agents_save(payload):
    try:
        payload = payload or {}
        doc = payload.get("doc") if isinstance(payload.get("doc"), dict) else payload
        if not isinstance(doc, dict) or not str(doc.get("name") or "").strip():
            return 400, {"error": "Give this agent a name."}
        saved = _save_agent(doc)
        webhooks = ensure_webhooks(saved)
        return 200, {"doc": saved, "webhooks": webhooks}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_agents_delete(payload):
    try:
        aid = (payload or {}).get("id")
        if not aid:
            return 400, {"error": "id is required"}
        if _SB:
            _SB("DELETE", f"{AGENTS_TABLE}?id=eq.{aid}")
        return 200, {"ok": True}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_settings_save(payload):
    try:
        payload = payload or {}
        s = _load_settings()
        if payload.get("clear_token"):
            s.pop("calendly_token", None)
            s.pop("_calendly_user_uri", None)
        elif str(payload.get("calendly_token") or "").strip():
            s["calendly_token"] = payload["calendly_token"].strip()
            s.pop("_calendly_user_uri", None)  # token changed -> re-resolve next use
        for k in ("work_start", "work_end", "horizon_working_days"):
            if payload.get(k) is not None:
                try:
                    s[k] = int(payload[k])
                except (TypeError, ValueError):
                    pass
        if payload.get("autopilot_enabled") is not None:
            s["autopilot_enabled"] = bool(payload["autopilot_enabled"])
        _save_settings(s)
        return 200, {"ok": True, "calendly_connected": bool(s.get("calendly_token")),
                    "work_start": s.get("work_start", 9), "work_end": s.get("work_end", 17),
                    "autopilot_enabled": bool(s.get("autopilot_enabled"))}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


# Smartlead subsequences are stored in `campaigns` too, under generic names
# like "Meeting Request" / "Interested Reply". They are not assignable
# targets, and ~300 of them would bury the real campaigns in the picker.
_SUBSEQUENCE_NAME = re.compile(r"^\s*(meeting request|interested reply|information request)\b", re.IGNORECASE)


def route_campaigns_get(_params):
    try:
        if not _SB:
            return 200, []
        rows = _SB("GET", f"campaigns?workspace=eq.{WORKSPACE}&select=smartlead_campaign_id,name,status"
                          f"&status=in.(ACTIVE,PAUSED,STOPPED)&order=created_at_smartlead.desc")
        out = []
        if isinstance(rows, list):
            for r in rows:
                name = (r.get("name") or "").strip()
                if not name or _SUBSEQUENCE_NAME.match(name):
                    continue
                out.append({"id": r.get("smartlead_campaign_id"), "name": name, "status": r.get("status")})
        return 200, out
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _compute_kpis() -> dict:
    kpis = {"needs_review": 0, "auto_sent_today": 0, "sent_today": 0,
           "avg_response_mins_7d": None, "no_action_today": 0}
    if not _SB:
        return kpis
    try:
        today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        nr = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=eq.needs_review&is_test=eq.false&select=id")
        kpis["needs_review"] = len(nr) if isinstance(nr, list) else 0
        for out_key, status in (("auto_sent_today", "auto_sent"), ("sent_today", "sent"), ("no_action_today", "no_action")):
            rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=eq.{status}&is_test=eq.false"
                              f"&created_at=gte.{today}&select=id")
            kpis[out_key] = len(rows) if isinstance(rows, list) else 0
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)).isoformat()
        rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=in.(auto_sent,sent)&is_test=eq.false"
                          f"&sent_at=gte.{since}&select=replied_at,sent_at")
        mins = []
        if isinstance(rows, list):
            for r in rows:
                try:
                    ra, sa = r.get("replied_at"), r.get("sent_at")
                    if ra and sa:
                        d1 = _parse_iso(ra)
                        d2 = _parse_iso(sa)
                        mins.append((d2 - d1).total_seconds() / 60)
                except Exception:  # noqa: BLE001
                    continue
        if mins:
            kpis["avg_response_mins_7d"] = round(sum(mins) / len(mins), 1)
    except Exception:  # noqa: BLE001
        pass
    return kpis


def route_queue_get(params):
    try:
        status = _qp(params, "status", "")
        try:
            limit = int(_qp(params, "limit", "200") or 200)
        except ValueError:
            limit = 200
        limit = max(1, min(limit, 500))
        rows = []
        if _SB:
            filt = f"workspace=eq.{WORKSPACE}&order=created_at.desc&limit={limit}&select=*"
            if status:
                filt += f"&status=eq.{status}"
            fetched = _SB("GET", f"{QUEUE_TABLE}?{filt}")
            rows = fetched if isinstance(fetched, list) else []
        return 200, {"rows": rows, "kpis": _compute_kpis()}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_queue_action(payload):
    try:
        payload = payload or {}
        qid = payload.get("id")
        action = payload.get("action")
        if not qid or not action:
            return 400, {"error": "id and action are required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        if action == "dismiss":
            _apply_patch(row, {"status": "dismissed"})
            return 200, {"ok": True, "status": "dismissed"}
        if action == "subsequence":
            checked = bool(payload.get("checked"))
            _apply_patch(row, {"added_to_subsequence": checked})
            return 200, {"ok": True, "added_to_subsequence": checked}
        if action == "send":
            if row.get("status") in ("sent", "auto_sent"):
                return 409, {"error": "This reply was already sent."}
            agent = _load_agent(row.get("agent_id")) or {}
            subject = payload.get("subject_override") or row.get("draft_subject") or f"Re: {row.get('reply_subject') or ''}"
            body_html = payload.get("body_override") or row.get("draft_body") or ""
            result = _send_reply(row, agent, subject, body_html, is_test=bool(row.get("is_test")), success_status="sent")
            return 200, {"ok": result.get("ok"), "row": {**row, **(result.get("row") or {})}}
        return 400, {"error": f"Unknown action '{action}'."}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_queue_redraft(payload):
    try:
        payload = payload or {}
        qid = payload.get("id")
        if not qid:
            return 400, {"error": "id is required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        agent = _load_agent(row.get("agent_id")) or {}
        settings = _load_settings()
        classification = row.get("classification") or {}
        tz = row.get("timezone")
        now = _dt.datetime.now(_dt.timezone.utc)
        eff_settings = dict(settings)
        eff_settings["_agent"] = agent
        eff_settings["_lead"] = {"first_name": row.get("lead_first_name"), "last_name": row.get("lead_last_name"),
                                 "email": row.get("lead_email")}
        slots, slot_status = [], "not_configured"
        if tz:
            slot_status, avail, _serr = get_calendly_availability(agent, eff_settings, now)
            if slot_status == "ok":
                slots = pick_slots(avail, tz, eff_settings, now)
                if not slots:
                    slot_status = "none_available"
        d = draft_reply(
            {"first_name": row.get("lead_first_name"), "subject": row.get("reply_subject"), "body": row.get("reply_body")},
            agent, classification, slots, slot_status, sender_first="")
        patch = {"draft_subject": d.get("subject"), "draft_body": d.get("html"), "slots": slots}
        _apply_patch(row, patch)
        return 200, {"row": {**row, **patch}}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_test_inject(payload):
    try:
        payload = payload or {}
        campaign_id = payload.get("campaign_id")
        if not campaign_id:
            return 400, {"error": "campaign_id is required"}
        agent = _agent_for_campaign(campaign_id, require_enabled=False)
        if not agent:
            return 400, {"error": "No agent is assigned to this campaign."}
        settings = _load_settings()
        email = (payload.get("email") or "test@example.com").strip().lower()
        reply = {
            "workspace": WORKSPACE, "campaign_id": campaign_id, "email": email,
            "first_name": payload.get("first_name") or "Test",
            "last_name": payload.get("last_name") or "",
            "company_domain": payload.get("company_domain") or (email.split("@", 1)[1] if "@" in email else ""),
            "subject": payload.get("subject") or "Re: our email",
            "body": payload.get("body") or "",
            "replied_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "message_id": f"test-{uuid.uuid4().hex[:10]}",
            "category": None, "is_test": True,
        }
        row = process_reply(reply, agent, settings)
        return 200, {"row": row}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


GET_ROUTES = {
    "/api/setter/agents": route_agents_get,
    "/api/setter/campaigns": route_campaigns_get,
    "/api/setter/queue": route_queue_get,
}

POST_ROUTES = {
    "/api/setter/agents/save": route_agents_save,
    "/api/setter/agents/delete": route_agents_delete,
    "/api/setter/settings/save": route_settings_save,
    "/api/setter/queue/action": route_queue_action,
    "/api/setter/queue/redraft": route_queue_redraft,
    "/api/setter/test/inject": route_test_inject,
}
