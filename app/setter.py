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

import concurrent.futures
import copy
import datetime as _dt
import json
import os
import random
import re
import sys
import threading
import time as _time
import uuid
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

# ── wiring (set once by server.py at startup) ────────────────────────────────

_SB = None
_SB_COUNT = None
_HTTP = None
_KEYS: dict = {}
_LOG = None


def configure(sb, http_json, keys, log_activity, sb_count=None):
    """Called once by server.py: setter.configure(sb=sb, http_json=http_json,
    keys=KEYS, log_activity=log_activity, sb_count=sb_count). Stores the app's
    own helpers in module globals so this file never has to `import server`.
    sb_count is a header-only row counter (transfers ~100B instead of the rows)
    used to size the queue filter pills."""
    global _SB, _SB_COUNT, _HTTP, _KEYS, _LOG
    _SB = sb
    _SB_COUNT = sb_count
    _HTTP = http_json
    _KEYS = keys or {}
    _LOG = log_activity
    # The subsequence->parent map is keyed off whatever Smartlead account the
    # keys point at, so a re-configure (boot, or a test swapping in fresh
    # fakes) must drop it rather than answer from the previous account's data.
    _PARENT_CACHE.update({"at": 0.0, "map": None})
    # Boot warm-up (perf pass 2026-07-16): pre-compute the queue read caches
    # in the background so even the FIRST /api/setter/queue GET after a
    # deploy/restart is served warm (~300ms) instead of paying the cold
    # rows+KPI compute (~4s measured live). Daemon threads; failures are
    # swallowed - the request path just computes cold as before.
    try:
        _kick_kpi_refresh()
        _kick_rows_refresh(("needs_review", 200))
        _kick_rows_refresh(("", 200))
    except Exception:  # noqa: BLE001 - warm-up must never block boot
        pass


WORKSPACE = "navreo"
AGENTS_TABLE = "setter_agents"
QUEUE_TABLE = "setter_queue"
SETTINGS_ID = "__settings__"
GRADING_ID = "__grading__"
SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
OPENAI_MODEL = "gpt-5-mini"

# Only these Smartlead/Make categories may enter setter_queue (ruling
# 2026-07-14) - everything else (Call Booked, Contact Forward, Contact In
# Future, all negatives, uncategorised) stays out of both intake paths.
CORE_FOUR = frozenset({"Interested", "Information Request", "Meeting Request", "positive-re-reply"})

# PostgREST `category=in.(...)` filter built FROM CORE_FOUR (sorted for a
# deterministic query string) instead of hardcoding the label list a second
# time. Values contain spaces, so each option is double-quoted THEN percent-
# encoded (quote() turns the quote marks into %22 and the spaces into %20) -
# PostgREST needs the quotes to treat "Information Request" as one value
# instead of splitting on its internal space.
CORE_FOUR_CATEGORY_FILTER = "in.(" + ",".join(quote(f'"{c}"', safe="") for c in sorted(CORE_FOUR)) + ")"

# Internal search window for Calendly availability, in working days. v2:
# no longer a settings-drawer field - the slot rule is fixed (earliest
# qualifying slots inside work hours), so this is just how far ahead the
# pipeline looks for them.
HORIZON_WORKING_DAYS = 10


def _agent_instructions(agent: dict) -> str:
    """What this agent may share verbatim - the `instructions` field,
    falling back to the legacy `pricing_notes` key so agent docs saved
    before the v2 simplification keep working unchanged."""
    agent = agent or {}
    val = str(agent.get("instructions") or "").strip()
    if val:
        return val
    return str(agent.get("pricing_notes") or "")


def _booking_link(agent: dict) -> str:
    """The single Calendly link used when no two-slot answer applies.
    Derived from calendly_event_url (trailing slash stripped) unless an
    explicit legacy booking_link is still set on the doc."""
    agent = agent or {}
    explicit = str(agent.get("booking_link") or "").strip()
    if explicit:
        return explicit
    calendly = str(agent.get("calendly_event_url") or "").strip()
    return calendly.rstrip("/") if calendly else ""


_URL_RE = re.compile(r'https?://[^\s"\'<>]+', re.IGNORECASE)


def _norm_url(url: str) -> str:
    """Lowercase, trailing-slash/punctuation-stripped form of a URL, so the
    same link written with or without a trailing slash, or with trailing
    prose punctuation stuck to it, still compares equal."""
    return str(url or "").strip().rstrip(".,;:!?)]}\"'/").lower()


def _extract_urls(text: str) -> list:
    """Every distinct http(s) URL in text, normalised. One regex catches both
    href="..." attributes and bare URLs in plain text (an href value is just
    quoted text, so the same pattern matches it too). Order preserved,
    de-duplicated case-insensitively."""
    seen = []
    seen_set = set()
    for m in _URL_RE.findall(text or ""):
        norm = _norm_url(m)
        if norm and norm not in seen_set:
            seen_set.add(norm)
            seen.append(norm)
    return seen


def _instruction_urls(agent: dict) -> list:
    """Every distinct http(s) URL the agent's instructions mention - the v3
    single-source-of-truth read used by lint_draft's URL allow-list and by
    decide()'s gate 6b (send_resource + 2+ links + no original outreach ->
    a person should pick)."""
    return _extract_urls(_agent_instructions(agent))


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
# Tags that end a visual line/paragraph become newlines (not spaces), so a
# Gmail/Outlook HTML reply keeps its paragraph structure after the tag strip.
_BREAK_TAG_RE = re.compile(
    r"<\s*(?:br\s*/?|/p|/div|/tr|/li|/h[1-6]|/blockquote|/pre)\s*>", re.IGNORECASE)
# HTML-level quoted-history containers: everything from the first reply-quote
# wrapper onward is the older thread, not the lead's new message. In cold-email
# replies a <blockquote> is quoted history for all practical purposes.
_HTML_QUOTE_RE = re.compile(
    r"<blockquote[^>]*>.*$"
    r"|<div[^>]*(?:gmail_quote|OutlookMessageHeader|yahoo_quoted|moz-cite-prefix)[^>]*>.*$",
    re.IGNORECASE | re.DOTALL)


def clean_body(body: str) -> str:
    """Reply text with HTML markup stripped, PARAGRAPH BREAKS KEPT, and quoted
    history removed. Outlook and Gmail replies often arrive as full HTML
    documents dragging the whole earlier thread along; markup and quoted
    history must never count toward the length veto or blur what the
    classifier reads — only the lead's actual new message survives.
    Stored bodies stay raw; this is read/render-time only."""
    text = body or ""
    if "<" in text and _HTML_TAG_RE.search(text):
        import html as _html
        text = _STYLE_BLOCK_RE.sub(" ", text)
        text = _HTML_QUOTE_RE.sub(" ", text)
        text = _BREAK_TAG_RE.sub("\n", text)
        text = _HTML_TAG_RE.sub(" ", text)
        text = _html.unescape(text)
    text = _strip_quoted(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

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


def resolve_timezone(hints: dict, classification: dict):
    """Best-effort IANA timezone plus whether it is CONFIDENT enough to
    auto-send at. A deterministic hit (company country/state/city, phone
    country code, ccTLD) is always confident. Otherwise the model's educated
    guess (inferred from the company/domain/signature, like a person glancing
    at LinkedIn) is used for DISPLAY even when weak - so a held draft still
    shows a plausible local time instead of defaulting to London - but only
    counts as confident for AUTO-SENDING at tz_confidence >= 0.7, so a real
    send never fires at a guessed-wrong hour. Returns (tz|None, confident)."""
    tz, _ = guess_timezone(hints or {})
    if tz:
        return tz, True
    classification = classification or {}
    guess = classification.get("timezone_guess")
    try:
        gc = float(classification.get("tz_confidence") or 0)
    except (TypeError, ValueError):
        gc = 0.0
    if guess:
        return guess, gc >= 0.7
    return None, False


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
    HORIZON_WORKING_DAYS working days, >= 20h out. Earliest-slot rule: the
    first slot offered is simply the earliest qualifying one; the second is
    the same day at least 2 hours later if one exists, else the next
    available day's earliest slot. Returns [{iso, label, link}]. link uses
    settings['_agent'] (calendly_event_url) and settings['_lead']
    (first_name/last_name/email)."""
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
    except (TypeError, ValueError):
        work_start, work_end = 9, 17
    horizon_days = HORIZON_WORKING_DAYS

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

    first = candidates[0]
    second = None
    for local, utc_dt in candidates[1:]:
        if local.date() == first[0].date() and (local - first[0]) >= _dt.timedelta(hours=2):
            second = (local, utc_dt)
            break
    if second is None:
        for local, utc_dt in candidates:
            if local.date() > first[0].date():
                second = (local, utc_dt)
                break

    chosen = [first] + ([second] if second else [])
    out = []
    for local, utc_dt in chosen:
        local_iso = local.isoformat()
        out.append({"iso": local_iso, "label": _slot_label(local), "link": _slot_link(agent, lead, local_iso)})
    return out


# ── draft lint ────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_TAG_RE = re.compile(r"<(?:div|p)\b", re.IGNORECASE)
_ANCHOR_HREF_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*"([^"]*)"', re.IGNORECASE)


def lint_draft(html: str, ctx: dict):
    """Deterministic pre-send checks. Returns (ok, reason)."""
    ctx = ctx or {}
    text = html or ""
    if not text.strip():
        return False, "No draft was produced."
    # Email shape: the draft must read as short block paragraphs (<div>/<p>
    # separated by <br>), never one run-on line - at least 2 paragraph
    # separators, counting <br> tags between blocks, or (if the drafter used
    # no <br> at all) at least 3 block elements (2 gaps between them).
    br_count = len(_BR_RE.findall(text))
    block_count = len(_BLOCK_TAG_RE.findall(text))
    paragraph_seps = br_count if br_count else max(block_count - 1, 0)
    if paragraph_seps < 2:
        return False, "The draft isn't formatted like an email yet."
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
    # URL discipline (instructions-only brain, v3): the ONLY links a draft may
    # ever contain are ones already known to the pipeline - every URL the
    # agent's instructions mention, the call-time slot links (Calendly deep
    # links count as slot links), the booking link, or a URL already present
    # in the thread. Anything else is an invented or wrong link.
    instruction_urls = set(_extract_urls(str(ctx.get("instructions") or "")))
    allowed_urls = set(instruction_urls)
    allowed_urls.update(_norm_url(u) for u in (ctx.get("slot_links") or []) if u)
    booking = str(ctx.get("booking_link") or "").strip()
    if booking:
        allowed_urls.add(_norm_url(booking))
    allowed_urls.update(_extract_urls(str(ctx.get("thread_text") or "")))

    draft_urls = _extract_urls(text)
    for u in draft_urls:
        if u not in allowed_urls:
            return False, "The draft contains a link that isn't in the instructions."
    if ctx.get("needs_resource_link") and not (set(draft_urls) & instruction_urls):
        return False, "The draft is missing the resource link from the instructions."
    if ctx.get("slot_status") == "ok":
        for link in (ctx.get("slot_links") or []):
            if link and link not in text:
                return False, "The draft is missing one of the suggested call times."
    elif ctx.get("slots_fallback") and ctx.get("needs_availability_ask"):
        # Owner ruling 2026-07-14: when Calendly can't offer real times, the
        # fallback draft must still give the lead a real hyperlink to pick a
        # time - never just bare text pasted into the body. The fallback
        # ladder (see DRAFT_SYSTEM) means that link may be EITHER the fixed
        # booking_link OR a scheduling/calendar link the instructions
        # themselves state - so this only requires at least one anchor whose
        # href normalises into the SAME allow-list the URL discipline check
        # above already enforces (instructions/booking/thread - never a slot
        # deep-link, since slot_links is empty in fallback mode, so any
        # calendly.com/.../<iso> anchor is already caught above, not here).
        anchor_hrefs = {_norm_url(h) for h in _ANCHOR_HREF_RE.findall(text) if h}
        if not (anchor_hrefs & allowed_urls):
            return False, "The draft doesn't link a calendar for the lead to pick a time."

    allowed_text = " ".join([
        str(ctx.get("instructions") or ""),
        str(ctx.get("thread_text") or ""),
        " ".join(str(x) for x in (ctx.get("slot_labels") or [])),
        " ".join(str(x) for x in (ctx.get("slot_links") or [])),
    ])
    allowed_digits = set(re.findall(r"\d+", allowed_text))
    plain = _TAG_RE.sub(" ", text)  # strip tags/hrefs - only visible text is scanned
    for run in re.findall(r"\d+", plain):
        if run not in allowed_digits:
            return False, "The draft invents a number that isn't in the instructions, the thread, or the call times."
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
    ctx: {red_flag_hits, category, first_touch, slot_status, slots_fallback, timezone, lint_ok,
          lint_reason, body_len, hydrated}. slots_fallback (owner ruling 2026-07-14) means
          real call times aren't available for any reason, so the drafter proposes no times
          and gate 7's timezone/slot holds don't apply."""
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
    if "pricing" in all_intents and not _agent_instructions(agent).strip():
        return "review", "Held for review: no instructions cover pricing, so a person should answer."

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

    # 6. multi-turn autonomy (user ruling 2026-07-13): a later-turn reply no
    # longer always drops to a human. Gates 2 ("intent(s) within what this
    # agent is allowed to answer alone") and 3 ("simple ask + confidence")
    # above already ran UNCONDITIONALLY, first touch or not, and would
    # already have returned "review" for an off-intent or non-simple ask -
    # so by the time execution reaches here, a later-turn reply is guaranteed
    # simple_ask and fully allowed (ctx["hydrated"] and answered_since_reply
    # were likewise already enforced, at gates 3/1). It may continue past
    # this gate exactly like a first-touch reply would. The explicit re-check
    # below is a defensive safety net (kept in case gates above this one are
    # ever reordered) with its own, more specific reason.
    if not ctx.get("first_touch", True):
        if off_intent or not simple_ask or confidence < threshold:
            return "review", ("Held for review: this lead has replied before and the ask "
                              "isn't simple enough to answer alone.")

    # 6b. multi-link ambiguity: the instructions offer more than one link and
    # send_resource is in play, but the original outreach (the offer the
    # lead's reply is actually answering) couldn't be loaded - there's no
    # reliable way to tell WHICH link they mean, so a person picks.
    if ("send_resource" in all_intents and len(_instruction_urls(agent)) >= 2
            and not ctx.get("first_outbound_present")):
        return "review", ("Held for review: the instructions offer more than one link and the "
                          "original outreach couldn't be loaded, so a person should pick.")

    # 7. slots + timezone. A guessed timezone is fine for showing a draft,
    # but PROPOSING actual times needs to be CONFIDENT of the hour, or we
    # might offer 2pm when it is 2am for them. Owner ruling 2026-07-14:
    # when real call times aren't available for ANY reason (Calendly not
    # connected, an API error, no free slots, or the lead's timezone
    # couldn't be worked out at all), the agent no longer holds the reply -
    # it drafts the fallback ask instead ("When would be a good time for us
    # to talk? Here is my availability", hyperlinked to the booking link).
    # That fallback proposes zero times, so the timezone-risk this gate
    # exists to catch is zero too, and none of the three holds below apply.
    # slots_fallback is set at every ctx build site as (slot_status != "ok");
    # falling back to deriving it here keeps direct decide() calls (tests,
    # older callers) that never set the key working exactly as before.
    slot_status = ctx.get("slot_status")
    slots_fallback = ctx.get("slots_fallback")
    if slots_fallback is None:
        slots_fallback = slot_status != "ok"
    if not slots_fallback:
        if ctx.get("timezone") is None:
            return "review", "Held for review: couldn't work out the lead's timezone."
        if not ctx.get("tz_confident", True):
            return "review", "Held for review: not sure enough of the lead's timezone to pick a time for them."

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

CLASSIFY_SYSTEM = """You classify one inbound cold-email reply for an appointment-setter agent that can ONLY do three things: send one of the agent's fixed resources, quote fixed pricing text verbatim, or propose two fixed call-time slots plus a booking link. Nothing else is answerable without a human.

Intents (pick exactly one primary_intent; list every intent that genuinely applies in all_intents):
- send_resource: the lead wants more info or the resource/link the agent's instructions provide, or gave an unqualified yes ("sure", "send it", "interested", "know more"). The resource IS the "more info".
- pricing: a pricing question, ONLY when the agent's instructions (given to you below) literally already contains the answer. If instructions is empty, or doesn't cover what's specifically asked, this is objection_or_question instead, not pricing. A plain, unconditional "what's the price?" / "how much does it cost?" with non-empty instructions IS pricing with simple_ask=true - quoting the instructions verbatim answers it fully.
- scheduling: wants to book a call, gave availability, or asked to schedule, AND a plain two-slot-plus-booking-link answer would be a faithful reply. Scheduling is a simple ask ONLY when the lead is flexible about timing (several days offered, "sometime next week", "send me some options" with no date named). If they name ONE specific day, date, or time ("Friday after 2:30", "the 24th", "next Thursday"), or ask for TODAY/tonight/"earlier"/"asap", set simple_ask=false - our two fixed slots may not match what they asked for.
- bespoke_request: wants something made specifically for them - a Loom or video recorded for them, an audit or breakdown OF THEIR company or website, anything "specific to us". EXCEPTION: if the agent's instructions say the offered resource already IS that video/audit, sending it is send_resource, not bespoke_request.
- objection_or_question: needs judgement or nuance - a direct question not answerable purely from instructions, a fit/commission/industry question, "where are you based", a conditional commitment ("if X then we'd try it" - a CONDITION anywhere always means simple_ask=false, even when instructions seems to answer it), or ANY report that a link, video, or resource did not work or arrive ("link didn't work", "couldn't watch the video", "can you send it again?" after a failure) - something may genuinely be broken, so a person must check before anything is re-sent.
- not_interested: a plain no or decline, not hostile.
- unsubscribe_dnc: asks to be removed, to stop contacting them, to cease, or is hostile/legal in tone (lawyer, GDPR, complaint). ALWAYS this intent even if the message is short and looks polite, e.g. "kindly cease" or "remove me" - never send_resource just because it reads politely.
- ooo: an out-of-office autoreply.
- wrong_person: says they are not the right contact (may name a colleague instead).
- bounce_or_system: a bounce, spam-block, or other system notice, not a human reply.
- other: none of the above fit.

simple_ask is true ONLY if the ENTIRE reply is satisfiable by (a) sending the resource, (b) quoting instructions verbatim, or (c) proposing our two call slots plus the booking link - with nothing else needed, no unanswered question, no invented fact. If the reply contains ANY question, condition, or ask outside those three things, set simple_ask=false even if the primary intent looks simple. When genuinely ambiguous, simple_ask=false.

Two further rules:
- IGNORE the sender's own email signature when working out the ask: their phone numbers, their own booking/calendar links, social handles, follower counts, taglines, and legal footers are not part of the request. Never treat a link in THEIR signature as them asking us to schedule.
- A bare one-word or near-bare affirmation ("Yes", "OK", "sure") is a simple send_resource ask ONLY when the last message WE sent (given to you as last_outbound below, when available) makes the referent unmistakable - e.g. we asked "want me to send the breakdown?" and they said "Yes". If last_outbound is missing or its ask is not unmistakable, set simple_ask=false.

live_lead: true when a reply that is otherwise a negative still contains a real opening someone should act on - a named replacement contact or referral ("Nick left, contact wim@..."), an explicit later-date opening ("not a priority right now, try me in Q3", "maybe later"), or a request to follow up at some point. Plain "no", plain opt-outs, plain out-of-office autoreplies with generic reception redirects are live_lead=false.

confidence: 0 to 1, your own honest confidence in this call - not a proxy for how short the message is.
red_flags: list any hostile/legal/opt-out language you notice (a second deterministic pass also checks this; do not rely on this list alone).
timezone_guess: your best educated guess of the lead's IANA timezone, the way a person would by glancing at their LinkedIn. Infer it from lead_email_domain (a ccTLD like .co.uk / .com.au / .de, or where a company with that domain or name is typically headquartered), company_location when given, the email signature (a phone country code, an address, a city), and the language used. Give an actual IANA name whenever you have ANY reasonable basis - only use null if you genuinely cannot tell at all. When only the country is clear, use that country's primary business timezone (US -> America/New_York, Canada -> America/Toronto, Australia -> Australia/Sydney, Germany -> Europe/Berlin). tz_confidence 0 to 1: 0.9+ for an explicit signal (a stated city, a +country-code phone, a ccTLD); 0.6-0.8 for a strong inference from a clearly-regional company; 0.3-0.5 for a weak lean.
wants: one plain-English line - what the lead is actually asking for.
rationale: one line - why you chose this intent.
original_outreach is the first email we sent this lead - the offer their reply is answering. ALWAYS read it first: it tells you what "sure", "send it", "yes please", "how much", or "not interested" actually refers to. A bare "yes" is only a simple send_resource ask when the outreach (or last_outbound) offered exactly that one thing; if the outreach pitched a call, "yes" is scheduling; if it asked a question, "yes" answers that question and may need a person. When original_outreach is empty, judge from the reply alone and lean toward review on anything ambiguous.
owner_corrections, when present, are standing corrections the business owner has given while reviewing this tool's calls - apply them faithfully when judging intent and simple_ask (they refine, never loosen, the safety rules above).
owner_corrections/feedback may contain a LATEST OWNER RULES block: those rules are the owner's newest teaching and take priority over everything else, including older instructions - obey them exactly.

Replies in ANY language get the same rules ("Oui pourquoi ne pas essayer, mais je n'ai pas encore le site web" contains a caveat - simple_ask=false). If you cannot fully understand the reply, simple_ask=false.

Never invent facts. Examples of the exact reasoning to apply (do not copy their wording, just the logic):
- "Wrong on all counts. Victoria Parkin is heading that division." -> wrong_person AND live_lead=true (a named better contact is an opening someone should act on).
- "sure!" -> send_resource, simple_ask=true, high confidence.
- "Kindly cease" -> unsubscribe_dnc, simple_ask=false, even though it is short and polite.
- "No thanks, Bjion." -> not_interested.
- "Can you share the video?" -> send_resource ONLY if the agent's instructions say the offered resource already is that video; otherwise bespoke_request.
- "Could you record a quick Loom walking through how this would work for our agency specifically?" -> bespoke_request, simple_ask=false.
- "So you work on commission?" -> objection_or_question, UNLESS instructions literally answers commission structure, then pricing.
- "Your message ... couldn't be delivered ... spam block list" -> bounce_or_system.
- A reply that reports a broken link AND asks a separate out-of-scope question -> simple_ask=false (the extra question is not answerable from fixed resources)."""


def classify(reply: dict, agent: dict, owner_hints: str = "") -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    reply = reply or {}
    agent = agent or {}
    payload = {
        "reply_subject": reply.get("subject") or "",
        "reply_body": (reply.get("body") or "")[:4000],
        # so the model can make an educated timezone guess (LinkedIn-style)
        "lead_email_domain": reply.get("email_domain") or "",
        "company_location": reply.get("company_location") or "",
        # the ORIGINAL outreach this is a reply to - the offer/pitch that gives
        # "sure, send it" / "what's the price" / "not for us" their meaning
        "original_outreach": (reply.get("first_outbound") or "")[:1500],
        # the last message WE sent before this reply - lets the model resolve
        # a bare "Yes" against what was actually offered
        "last_outbound": (reply.get("last_outbound") or "")[:800],
        "agent": {
            # The single brain: pricing, resource links, and when-to-send
            # rules all live in the instructions text, passed in full so the
            # model can answer pricing and judge the bespoke_request
            # exception (see CLASSIFY_SYSTEM) from it directly.
            "instructions": _agent_instructions(agent),
            "allowed_intents": agent.get("allowed_intents") or [],
        },
    }
    if (owner_hints or "").strip():
        payload["owner_corrections"] = owner_hints.strip()[:2000]
    user = json.dumps(payload)
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
    "properties": {"subject": {"type": "string"}, "html": {"type": "string"},
                   "feedback_note": {"type": "string"}},
    "required": ["subject", "html", "feedback_note"],
}

# Single budget for the reviewer_feedback payload field - draft_reply enforces
# it as a backstop, and route_queue_redraft allocates within it feedback-first
# (owner ruling 2026-07-16: the typed feedback is never the part that gets cut).
REVIEWER_FEEDBACK_CAP = 4000

DRAFT_SYSTEM = """You write the reply for a cold-email appointment-setter agent, in the team's OWN voice. It must read as if the same person who sent these real replies wrote it. Output real, sendable HTML: short paragraphs, each its own <div>...</div>, separated by <br>. Sign off with just the sender's first name on its own line: <div>{SenderFirst}</div> (NO "Best,", no "Kind regards" - the real replies just sign the name). NEVER write one run-on line.

These are REAL replies the team sent. Match this voice, structure, and exact phrasing precisely (swap in the actual name, resource link, times, and booking link you are given):

RESOURCE + CALL:
<div>Hi Donald,</div><br><div><a href="RESOURCE_LINK">Here's the breakdown I prepared.</a></div><br><div>Would you be free for a call on <a href="SLOT_1">Wednesday, 14th July at 2:00 PM BST</a> or <a href="SLOT_2">Thursday, 15th July at 2:30 PM BST</a>, where I could share how I would implement our strategy for you?</div><br><div>If those times aren't suitable, feel free to <a href="BOOKING_LINK">book a call here</a>.</div><br><div>Bjion</div>

PRICING (quote the instructions verbatim). Shown here with no live slots - when slot_status is "ok" this same reply also carries the two call-time paragraph and the booking-link paragraph:
<div>Hi Parag,</div><br><div>Our pay-per-lead pricing has two parts:</div><br><div>1. Setup and infrastructure: $1,000 (at cost). This covers everything needed to run your campaigns: enterprise Microsoft (Azure) mailboxes plus Gmail mailboxes giving you up to 50,000 sends per month, email enrichment, verification of that data, and personalisation plus intent and signal data. All billed at cost, no markup.</div><br><div>2. Performance: $300 per qualified meeting attended. You only pay when a genuinely qualified prospect actually shows up to the meeting.</div><br><div>Bjion</div>

A QUESTION WE CAN'T FULLY ANSWER IN AN EMAIL. Shown here with no live slots - when slot_status is "ok", replace the "book a call here" paragraph with the two call-time paragraph plus the "If those times aren't suitable" booking-link paragraph:
<div>Hi Gustavo,</div><br><div>Good question. That's exactly what I'd walk you through on a quick call, where I could show how it applies to you.</div><br><div>If you're open to it, feel free to <a href="BOOKING_LINK">book a call here</a>.</div><br><div>Bjion</div>

CALL ASK, NO LIVE SLOTS BUT THE INSTRUCTIONS LIST CONCRETE AVAILABLE TIMES (fallback ladder step ONE-A - slot_status is anything but "ok" AND the instructions contain a concrete list of available times or time ranges, e.g. an auto-updated "Current Available Times" block):
<div>Hi Priya,</div><br><div>Would you be free for a call on Wednesday, 16th July at 1:00 PM EST or Thursday, 17th July at 10:30 AM EST, where I could share how I would implement our strategy for you?</div><br><div>If those times aren't suitable, you're welcome to <a href="INSTRUCTIONS_CALENDAR_LINK">grab a slot here</a>.</div><br><div>Bjion</div>

CALL ASK, NO LIVE SLOTS BUT THE INSTRUCTIONS GIVE ONLY A GENERAL WINDOW (fallback ladder step ONE-B - slot_status is anything but "ok" AND the instructions state only a general availability window or a scheduling/calendar link, with no concrete times listed):
<div>Hi Priya,</div><br><div>Would love to find a time that works for you.</div><br><div>I'm generally free WINDOW_FROM_INSTRUCTIONS, or you're welcome to grab a slot directly on <a href="INSTRUCTIONS_CALENDAR_LINK">my calendar</a>.</div><br><div>Bjion</div>

CALL ASK, NO TIMES AVAILABLE ANYWHERE (fallback ladder step TWO - slot_status is anything but "ok" AND the instructions say nothing at all about availability):
<div>Hi Priya,</div><br><div>Would love to find a time that works for you.</div><br><div>When would be a good time for us to talk? Here is <a href="BOOKING_LINK">my availability</a>.</div><br><div>Bjion</div>

Rules:
- Every draft must be built from short <div> paragraphs separated by <br>, exactly like the examples above. A single-line reply with no paragraph breaks will be rejected.
- Use the team's exact recurring phrases where they fit: the resource anchor is "Here's the breakdown I prepared." (or "Here's a case study I put together." when it's a case study); the call ask is "Would you be free for a call on {day, date at time TZ} or {day2, date2 at time2 TZ}, where I could share how I would implement our strategy for you?"; the fallback is "If those times aren't suitable, feel free to book a call here." with the link on "book a call here".
- No em dashes anywhere, ever - use a comma or period instead.
- No emoji.
- Plain English, under 150 words total. The team's replies are short - do not pad.
- Only include the resource link/anchor when send_resource is one of the intents to answer.
- Resource links and when to send each one are in the instructions. When the lead should get a link, use the exact link from the instructions that matches the original_outreach and their ask. Never invent a link, never paste a link the instructions don't contain.
- Anchor text reads like the examples above - natural, first-person, never the bare resource title.
- When the intent is bespoke_request, objection_or_question, or wrong_person, the ack paragraph must acknowledge the lead's SPECIFIC ask honestly (e.g. "Happy to put a video together for you.") - never a generic "Of course." that ignores what they asked for, and never a promise of a date or deadline for the bespoke work.
- Never say you are sharing, attaching, or sending something the draft does not actually contain. If the asked-for asset is not the agent's fixed resource, acknowledge the ask ("Happy to get that over to you.") without implying it is included in this email.
- The ack paragraph must answer the SHAPE of the question. A yes/no question ("So you work on commission?") gets a direct, truthful opener grounded ONLY in the instructions ("Good question, it is a flat monthly fee rather than commission."), never "Of course."
- BEFORE writing anything, decide the greeting name: use lead_first_name if given; otherwise LOOK AT THE END OF THEIR REPLY for a signed name ("Thanks, Cole" / "Kelly, Head of Partnerships" means greet "Hi Cole" / "Hi Kelly"); only if no name exists anywhere use "Hi there". NEVER greet the lead with SenderFirst - that is OUR name, used only in the sign-off.
- If they ask for "the video" and the agent's fixed resource is NOT a video, never present the resource link as if it were the video. Acknowledge the video ask specifically and honestly; the human reviewer will attach the right asset.
- If a question's answer is NOT in the instructions or the resource, do not improvise one. Acknowledge it and make it the reason for the call: "That's exactly what I'd walk you through on a quick call." Guessing at policies, capabilities, or processes is worse than not answering.
- If SenderFirst is empty, end with no sign-off line at all.
- Whenever slots are supplied and slot_status is "ok" you MUST include the two call-time paragraph, with each day/time as an anchor whose href is that slot's own link, exactly as in the RESOURCE + CALL example, followed by the "If those times aren't suitable" booking-link paragraph. This is not optional and does not depend on the intent: a resource send, a pricing answer, or a question we can't fully answer all still get the two call times when live slots exist. Use every slot link you were given, verbatim, and never drop a slot in favour of the booking link alone. Conversely, never propose call times from live slots when slot_status is anything but "ok". When call times are NOT available (slot_status is anything but "ok"), follow this fallback ladder, in order, and never skip a step that applies: ONE-A, if the instructions contain a CONCRETE list of available times or time ranges (for example an auto-updated "Current Available Times" block), pick exactly TWO different times from that list (two different days when possible) and propose them in the same phrasing as the normal two-call-times ask, as plain text (no per-slot deep links exist here). current_datetime_utc tells you when NOW is: never propose a listed time that is already in the past or later today - only listed times from tomorrow (in the lead's timezone) onwards count. When the list contains two or more future times you MUST propose exactly two, never just one; only when it holds a single future time may you propose one, and when it holds none treat the instructions as giving only the calendar link (step ONE-B). Obey any timezone rule the instructions state: when you know the lead's timezone, convert each proposed time into it and label it with that timezone; when you don't, send the times exactly as listed with the timezone label the instructions use. Then hyperlink the scheduling/calendar link the instructions give in its own short follow-up paragraph ("grab a slot here"). ONE-B, if the instructions state only a general availability window or just a scheduling/calendar link, propose a meeting using exactly what the instructions say, their own words for the window, and hyperlink the calendar link the instructions give, as its own paragraph. TWO, only when the instructions say nothing at all about availability, ask exactly this, as its own paragraph: "When would be a good time for us to talk? Here is <a href="BOOKING_LINK">my availability</a>." using the real booking_link value you were given as the href. Never invent a time, day, or window that isn't in the slots you were given or literally stated in the instructions - and never copy an example's availability wording from this prompt (the windows and times in the examples above are placeholders, not facts). Never mention that a calendar, tool, or booking system failed or wasn't available - the lead should never sense anything went wrong.
- If pricing is one of the intents, quote the instructions content verbatim (the actual numbers/structure) rather than paraphrasing them away.
- If the intent needs a human (bespoke, objection, other, wrong_person, etc.) still write a warm, honest best-effort draft for a human to edit - never invent a fact, number, or promise not present in the resource, instructions, or thread; keep it short and let the human add specifics.
- Never invent a number, date, or fact that isn't in the instructions, the reply thread, or the call-time slots given to you.
- Match the tone AND the exact recurring phrasing of the real examples above - the goal is a reply indistinguishable from what the team actually sends.
- original_outreach is the first email we sent this lead. Keep the reply consistent with what it actually offered - answer the thing they were pitched, and echo the lead's own wording where natural, so the message reads like a real continuation of that thread, not a generic template.
- recent_thread, when present, is the last few messages in this thread (our sends and their replies, oldest first) - a later-turn reply must read as a natural continuation of it, never repeating something already said or re-introducing yourself.
- reviewer_feedback, when present, is the human reviewer's instruction for THIS regeneration ("shorter", "don't offer times", "mention the guide is free") - follow it faithfully while keeping every rule above. It never overrides the never-invent rules.
- reviewer_feedback/owner_corrections may contain a LATEST OWNER RULES block: those rules are the owner's newest teaching and take priority over everything else, including older instructions - obey them exactly.
- feedback_note is ONLY about reviewer_feedback, and only about the part you could NOT honour. When reviewer_feedback asks for something you have NO source for (a resource link when the instructions contain none, a fact or asset not present in the instructions, thread, or slots), do NOT invent it and do NOT silently ignore the ask - write one plain-English sentence in feedback_note saying what you couldn't do and why, plus what would unblock it (e.g. "No agent is assigned to this campaign, so I have no resource links to include - assign an agent or paste the link into the draft manually."). Never use feedback_note for gaps the reviewer didn't raise: a missing booking link, missing call slots, empty instructions, or any other limitation is NOT feedback_note material unless reviewer_feedback itself asked for that thing. When you honoured the feedback fully, or there is no reviewer_feedback, feedback_note must be exactly "".
- Output STRICT JSON: {"subject": "...", "html": "...", "feedback_note": "..."}. subject should read "Re: {original subject}" (or a sensible one if none given). html is the full reply body, written as the div/br block-paragraph shape shown above, using <a href="..."> for links, never markdown, never one run-on line."""


def draft_reply(reply: dict, agent: dict, classification: dict, slots: list, slot_status: str, sender_first: str,
                regen_feedback: str = "") -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    reply = reply or {}
    agent = agent or {}
    classification = classification or {}
    payload = {
        "lead_first_name": reply.get("first_name") or "there",
        "original_subject": reply.get("subject") or "",
        "original_outreach": (reply.get("first_outbound") or "")[:1500],
        "reply_body": (reply.get("body") or "")[:3000],
        "wants": classification.get("wants") or "",
        "primary_intent": classification.get("primary_intent") or "",
        "all_intents": classification.get("all_intents") or [],
        # The single brain: pricing, resource links, and when-to-send-which
        # rules all live in the instructions text (see the DRAFT_SYSTEM rule
        # above), passed in full - never a separate resource/resources field.
        "instructions": _agent_instructions(agent),
        "booking_link": _booking_link(agent),
        "slots": slots or [],
        "slot_status": slot_status or "not_configured",
        "sender_first": sender_first or "",
        # The drafter can't know when NOW is, so instruction-listed availability
        # (fallback ladder ONE-A) was being proposed from stale/past entries -
        # proven by the slot audit 2026-07-15 ("Tuesday, 14 July" offered on the
        # 15th). Times drawn from instructions must be filtered against this.
        "current_datetime_utc": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%A, %d %B %Y, %H:%M UTC"),
    }
    # Thread continuity (multi-turn autonomy): when the reply dict carries the
    # recent thread text (hydrate_lead already collects it - norm[-6:] - the
    # caller just needs to pass it through), give the drafter that context so
    # a later-turn reply reads as a continuation, not a repeat.
    thread_raw = str(reply.get("thread_text") or "").strip()
    if thread_raw:
        thread_clean = re.sub(r"\s+", " ", _TAG_RE.sub(" ", thread_raw)).strip()[:1200]
        if thread_clean:
            payload["recent_thread"] = thread_clean
    if (regen_feedback or "").strip():
        # 4000, not 500: the feedback carries the LATEST OWNER RULES block
        # (~1600 chars) plus the session digest (~2000). The old 500-char cap
        # silently discarded almost all teaching before the drafter saw it -
        # the root cause of "it keeps repeating the same mistakes".
        payload["reviewer_feedback"] = regen_feedback.strip()[:REVIEWER_FEEDBACK_CAP]
    user = json.dumps(payload)
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
    # Warn only, never inject (owner ruling 2026-07-16): when the reviewer's
    # feedback asked for something this draft has no source for, the model
    # explains itself here instead of silently ignoring the ask. Only
    # meaningful on a feedback redraft - blank it everywhere else.
    feedback_note = (str(data.get("feedback_note") or "").strip()
                     if payload.get("reviewer_feedback") else "")
    return {"subject": subject, "html": html_body, "feedback_note": feedback_note}


PROOFREAD_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"html": {"type": "string"}},
    "required": ["html"],
}

PROOFREAD_SYSTEM = ("You are a meticulous copy editor for short sales emails. Fix grammar, spelling, "
                    "duplicated words or sentences, awkward or broken phrasing, and formatting slips. "
                    "Keep the meaning, structure, every link href, every number, every date and time, "
                    "and every name EXACTLY as they are. Keep the same div/br HTML shape. No em dashes. "
                    "Return the full corrected HTML.")


def _visible_digit_runs(html: str) -> set:
    """Digit runs found in the VISIBLE text only (tags/hrefs stripped first)
    - the same discipline lint_draft's own invented-number check uses, reused
    here so a proofread pass can never silently change a number, date, or
    time even though its wording changed."""
    plain = _TAG_RE.sub(" ", html or "")
    return set(re.findall(r"\d+", plain))


def proofread_draft(html: str):
    """Second sweep (owner brief 2026-07-14: "drafts need a second sweep so
    they read correctly without errors") - one extra gpt-5-mini call that
    proofreads an already-drafted email body for grammar, spelling,
    duplicated words/sentences, and formatting slips, without touching its
    meaning. Called right after draft_reply() and BEFORE lint_draft(), at
    every draft call site, so lint checks the FINAL text.

    SAFETY GUARDS - any failure at all returns the ORIGINAL html unchanged
    (changed=False): the OpenAI call must succeed and return a non-empty
    result; the result's URL set must equal the original's URL set exactly
    (_extract_urls, as sets - a proofread must never add, drop, or rewrite a
    link); the result's visible-text digit-run set must equal the
    original's (_visible_digit_runs - never a changed number, date, or
    time); and the result's length must fall within 0.5x-1.6x of the
    original's length (a wildly shorter or longer result is a bad edit, not
    a proofread). Never raises. Returns (html, changed): changed is True
    only when the (guard-passed) result actually differs from the input."""
    original = html or ""
    if not original.strip():
        return original, False
    try:
        key = _KEYS.get("OPENAI_API_KEY")
        if not key:
            return original, False
        r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                 {"Authorization": f"Bearer {key}"},
                 {"model": OPENAI_MODEL,
                  "messages": [{"role": "system", "content": PROOFREAD_SYSTEM},
                              {"role": "user", "content": json.dumps({"html": original})}],
                  "response_format": {"type": "json_schema", "json_schema": {
                      "name": "setter_proofread", "strict": True, "schema": PROOFREAD_SCHEMA}}})
        if not isinstance(r, dict) or r.get("error"):
            return original, False
        data = json.loads(r["choices"][0]["message"]["content"])
        result = str(data.get("html") or "").strip()
        if not result:
            return original, False
        if set(_extract_urls(result)) != set(_extract_urls(original)):
            return original, False
        if _visible_digit_runs(result) != _visible_digit_runs(original):
            return original, False
        orig_len = len(original)
        if orig_len and not (0.5 * orig_len <= len(result) <= 1.6 * orig_len):
            return original, False
        return result, result != original
    except Exception:  # noqa: BLE001 - a proofread outage must degrade to the original draft, never crash
        return original, False


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
    try:
        return _HTTP("POST", f"{SMARTLEAD_BASE}{path}?{urlencode(qs)}", {}, body)
    except ValueError:
        # Smartlead sometimes answers a successful POST (e.g. reply-email-thread)
        # with a non-JSON 2xx body such as a bare "OK". http_json's json.loads then
        # raises JSONDecodeError (a ValueError) even though the HTTP call SUCCEEDED,
        # which used to land the reply as needs_review + "Expecting value: line 1
        # column 1 (char 0)" while the email had actually gone out - risking a
        # double-send on the next click. A 2xx IS success, so treat it as an
        # accepted, empty-JSON response. (4xx/5xx still raise HTTPError, unchanged.)
        return {}


def _sl_campaign_lead_map_id(campaign_id, lead_email: str, smartlead_lead_id=None, max_pages: int = 20):
    """Resolves the Smartlead `campaign_lead_map_id` for a lead inside a
    specific campaign - this is the id the push-to-subsequence endpoint calls
    `email_lead_map_id`. Source: GET /campaigns/{campaign_id}/leads, docs at
    https://api.smartlead.ai/api-reference/leads/get-by-campaign - each row of
    the paginated `data` list carries a top-level `campaign_lead_map_id` plus
    a nested `lead` object ({id, email, ...}). That endpoint has no documented
    email/lead_id filter, so this pages through (100/lead, capped at
    max_pages*100 leads) matching by Smartlead lead id first, email second.
    Returns the id, or None if not found / on any failure."""
    if not campaign_id:
        return None
    email_l = (lead_email or "").strip().lower()
    offset = 0
    try:
        for _ in range(max_pages):
            resp = _sl_get(f"/campaigns/{campaign_id}/leads", {"offset": offset, "limit": 100})
            if not isinstance(resp, dict):
                return None
            page = resp.get("data")
            if not isinstance(page, list) or not page:
                return None
            for entry in page:
                if not isinstance(entry, dict):
                    continue
                lead = entry.get("lead") if isinstance(entry.get("lead"), dict) else {}
                if smartlead_lead_id and str(lead.get("id")) == str(smartlead_lead_id):
                    return entry.get("campaign_lead_map_id")
                if email_l and str(lead.get("email") or "").strip().lower() == email_l:
                    return entry.get("campaign_lead_map_id")
            if len(page) < 100:
                return None
            offset += 100
    except Exception:  # noqa: BLE001
        return None
    return None


def _push_to_subsequence(campaign_id, lead_email: str, smartlead_lead_id, sub_sequence_id):
    """Real Smartlead sub-sequence enrolment.
    Endpoint: POST /master-inbox/push-to-subsequence, docs at
    https://api.smartlead.ai/reference/push-lead-to-subsequence (same shape
    Smartlead's own MCP tool `push_to_master_inbox_subsequence` wraps).
    Body: {email_lead_map_id, sub_sequence_id, sub_sequence_delay_time,
    stop_lead_on_parent_campaign_reply}. `email_lead_map_id` is resolved via
    _sl_campaign_lead_map_id() above. Never raises - always returns
    (ok: bool, detail) where detail is Smartlead's response dict on success,
    or a plain-English string on failure."""
    try:
        if not _sl_key():
            return False, "Smartlead isn't connected (no API key configured)."
        if not campaign_id or not sub_sequence_id:
            return False, "Missing campaign or subsequence id."
        map_id = _sl_campaign_lead_map_id(campaign_id, lead_email, smartlead_lead_id)
        if not map_id:
            return False, "Couldn't find this lead in that Smartlead campaign."
        resp = _sl_post("/master-inbox/push-to-subsequence", {
            "email_lead_map_id": map_id,
            "sub_sequence_id": sub_sequence_id,
            "sub_sequence_delay_time": 0,
            "stop_lead_on_parent_campaign_reply": True,
        })
        if not isinstance(resp, dict):
            return False, "Smartlead didn't respond (timeout or network error)."
        # Smartlead answers HTTP 200 for rejections too (live-proven: a bad
        # sub_sequence_id returns {"ok": false, "message": "Invalid
        # subsequence or not related to the parent campaign"}), so success
        # must be an EXPLICIT positive - anything else is a failure.
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        ok = resp.get("ok") is True or resp.get("success") is True or data.get("success") is True
        if not ok:
            msg = resp.get("message") or resp.get("error") or "Smartlead rejected the request."
            return False, str(msg)[:300]
        return True, resp
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


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

        # The FIRST email we sent this lead - the original outreach that their
        # reply is answering. Without it, "sure, send it" / "what's the price"
        # are un-interpretable. Taken from the full history (not the truncated
        # thread window), so it survives even on a deep sequence.
        first_outbound = clean_body(sent[0].get("body") or "")[:1500] if sent else ""

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
            # Full conversation, not a keyhole: the owner reads this thread in
            # the UI, so a 6-message cap silently hid earlier replies. 50
            # bounds the payload without ever clipping a real sales thread.
            "thread": norm[-50:],
            "sender_first": sender_first,
            "answered_since_reply": answered_since_reply,
            "first_outbound": first_outbound,
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
        horizon_days = HORIZON_WORKING_DAYS
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


def _load_grading() -> dict:
    """Grading page (temporary): stored in the same settings-doc table under
    the reserved id __grading__, same pattern as __settings__."""
    default = {"cases": [], "answers": {}}
    if not _SB:
        return default
    try:
        rows = _SB("GET", f"{AGENTS_TABLE}?id=eq.{GRADING_ID}&select=doc")
        if isinstance(rows, list) and rows:
            doc = dict(rows[0].get("doc") or {})
            doc.setdefault("cases", [])
            doc.setdefault("answers", {})
            return doc
    except Exception:  # noqa: BLE001
        pass
    return default


def _save_grading(doc: dict):
    if not _SB:
        return
    _SB("POST", f"{AGENTS_TABLE}?on_conflict=id", {"id": GRADING_ID, "doc": doc},
       prefer="resolution=merge-duplicates,return=minimal")


def _load_agents() -> list:
    if not _SB:
        return []
    try:
        # Reserved doc rows (__settings__, __grading__, training-<agent_id>)
        # live in the same table but are never real agents - filtered out
        # client-side so they can never leak into the agents list or
        # campaign assignment lookups.
        rows = _SB("GET", f"{AGENTS_TABLE}?select=id,doc")
        if isinstance(rows, list):
            return [r.get("doc") or {} for r in rows
                   if isinstance(r, dict) and r.get("id") not in (SETTINGS_ID, GRADING_ID)
                   and not str(r.get("id") or "").startswith(TRAINING_ID_PREFIX)]
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


# Parent lookup for subsequence campaigns. A Smartlead subsequence IS its own
# campaign row (see _sl_find_subsequences), so a reply that lands while a lead
# is enrolled in "Interested Reply" carries the SUBSEQUENCE's campaign id, not
# the parent's. Nobody assigns an agent to a subsequence - they assign it to
# the parent - so those replies used to fall through to agentless intake ("No
# agent is assigned to this campaign"). GET /campaigns/ is the only place the
# parent link lives (the Supabase `campaigns` mirror has no parent_campaign_id
# column), and it returns the whole workspace in one call, so the id->parent
# map is built once and cached rather than fetched per reply: a poll tick
# resolves up to 15 replies and would otherwise re-list every campaign 15 times.
_PARENT_CACHE = {"at": 0.0, "map": None}
_PARENT_TTL = 600


def _parent_map(force: bool = False) -> dict:
    """{str(subsequence_campaign_id): str(parent_campaign_id)} for the whole
    workspace, cached for _PARENT_TTL seconds. Returns {} (and does NOT cache
    the failure) when Smartlead is unreachable, so a transient outage degrades
    to "no parent found" for one call instead of poisoning the cache for 10
    minutes."""
    if not force and _PARENT_CACHE["map"] is not None \
            and (_time.time() - _PARENT_CACHE["at"]) < _PARENT_TTL:
        return _PARENT_CACHE["map"]
    try:
        resp = _sl_get("/campaigns/")
        if not isinstance(resp, list):
            return _PARENT_CACHE["map"] or {}
        out = {}
        for r in resp:
            if isinstance(r, dict) and r.get("id") and r.get("parent_campaign_id"):
                out[str(r["id"])] = str(r["parent_campaign_id"])
        _PARENT_CACHE.update({"at": _time.time(), "map": out})
        return out
    except Exception:  # noqa: BLE001 - never let a Smartlead blip break agent lookup
        return _PARENT_CACHE["map"] or {}


def _parent_campaign_id(campaign_id):
    """The campaign `campaign_id` is a subsequence of, or None when it is a
    top-level campaign (or Smartlead can't be reached)."""
    if not campaign_id:
        return None
    return _parent_map().get(str(campaign_id))


def _agent_for_campaign(campaign_id, require_enabled: bool = True, agents=None):
    """The agent assigned to `campaign_id`, or - when `campaign_id` is a
    Smartlead subsequence - the agent assigned to its parent campaign (owner
    ruling 2026-07-17: a subsequence inherits its parent's agent, because a
    lead replying from "Interested Reply" is the same lead in the same
    campaign as far as the setter is concerned). Direct assignment always
    wins; the parent hop only runs when nothing matches directly, so the
    extra Smartlead call never touches the common top-level-campaign path."""
    agents = agents if agents is not None else _load_agents()

    def _match(want):
        for a in agents:
            if require_enabled and not a.get("enabled", True):
                continue
            if want in [str(c) for c in (a.get("campaign_ids") or [])]:
                return a
        return None

    direct = _match(str(campaign_id))
    if direct:
        return direct
    parent = _parent_campaign_id(campaign_id)
    return _match(str(parent)) if parent else None


def _save_agent(doc: dict) -> dict:
    doc = dict(doc or {})
    existing = None
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
    doc.setdefault("instructions", "")
    # Canonical sign-off identity (owner bug report 2026-07-14: the agent was
    # signing off with three different names depending on which code path
    # drafted the reply). A first name only, e.g. "Kevin" - see
    # _sender_first_for, the single resolver every draft_reply call site uses.
    # Left empty until either the owner sets it in the agent modal, or the
    # live pipeline self-learns it from the campaign's own sent emails
    # (process_reply's hydrate handling).
    doc.setdefault("sender_first", "")
    # Legacy fields kept so agent docs saved before the v2 simplification keep
    # working (pricing_notes is still read as the instructions fallback) -
    # just no longer shown or written to by the v2 editor UI.
    doc.setdefault("voice_examples", [])
    doc.setdefault("pricing_notes", "")
    doc.setdefault("extra_instructions", "")
    # Persistent learning layer, v3 (owner ruling 2026-07-14): a "remember"
    # correction is merged straight into `instructions` (the single living
    # manual - see merge_correction_into_instructions) instead of growing a
    # separate memory list. `memory` and `feedback_log` are kept only so
    # agent docs saved before this ruling keep reading correctly (memory
    # still feeds _agent_memory_digest into every pipeline call; feedback_log
    # is still audit-only) - nothing writes NEW entries into memory any more.
    doc.setdefault("memory", [])
    doc.setdefault("feedback_log", [])
    # Audit trail for every instructions edit merge_correction_into_instructions
    # makes (or falls back to appending) - {note, at, source, how} newest last.
    # The training page's memory viewer reads this (route_training_get).
    doc.setdefault("instruction_edits", [])
    # Stamp when each campaign was first assigned - the poll only processes
    # replies received after this, so activating an agent never sweeps an
    # already-handled backlog into the queue.
    # The ORIGINAL stored stamp wins over anything the incoming payload carries:
    # an editor that round-trips an empty/stale campaign_assigned_at, or a caller
    # that re-saves only the instructions, must NEVER re-stamp a pre-existing
    # campaign. A re-stamp silently disqualifies every reply received before the
    # re-save (run_poll only intakes replies newer than the stamp) - this is the
    # leak that re-stamped all 30 of an agent's campaigns to one timestamp.
    # Existing campaign ids keep this original-stamp-wins protection exactly
    # as before. Genuinely-NEW campaign ids (never seen in stamps before) get
    # backdated 7 days instead of stamped `now` (owner ruling 2026-07-15): a
    # freshly-attached campaign deliberately opens a 7-day backlog window so
    # recent positive replies already sitting in `replies` get self-healed
    # into the queue as drafts (see _self_heal_campaigns), rather than the
    # attach silently starting the clock from a blank slate.
    prior_stamps = dict((existing or {}).get("campaign_assigned_at") or {})
    stamps = {**(doc.get("campaign_assigned_at") or {}), **prior_stamps}
    backdated = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)).isoformat(timespec="seconds")
    for cid in (doc.get("campaign_ids") or []):
        key = str(cid)
        if key not in stamps:
            stamps[key] = backdated
    doc["campaign_assigned_at"] = {k: v for k, v in stamps.items()
                                   if k in {str(c) for c in (doc.get("campaign_ids") or [])}}
    # v3 simplification (owner ruling 2026-07-14): agents have no resource
    # fields at all - instructions is the single brain. A doc saved before
    # this ruling may still CARRY legacy resources/resource_name/resource_link/
    # resource_description keys; they are left exactly as given (never
    # normalised, capped, or mirrored here) and every read of an agent
    # elsewhere in this file ignores them.
    if _SB:
        _SB("POST", f"{AGENTS_TABLE}?on_conflict=id", {"id": doc["id"], "doc": doc},
           prefer="resolution=merge-duplicates,return=minimal")
        # Adopt orphaned agentless rows (owner follow-up 2026-07-14): assigning
        # a campaign to an agent must also claim the campaign's already-intaken
        # agentless queue rows - otherwise they keep the "No agent" pill and
        # the assign-an-agent decision_reason forever, telling the reviewer to
        # do something they already did. agent_id + reason only: status,
        # decision, drafts and bodies stay untouched (backlog never auto-
        # drafts, let alone auto-sends - Regenerate runs the brain on demand).
        # Idempotent (agent_id=is.null filter) and best-effort: adoption
        # failing must never fail the save.
        if doc.get("enabled") and doc.get("campaign_ids"):
            try:
                ids_csv = ",".join(str(c) for c in doc["campaign_ids"])
                _SB("PATCH", f"{QUEUE_TABLE}?agent_id=is.null&status=eq.needs_review"
                             f"&is_test=eq.false&smartlead_campaign_id=in.({ids_csv})",
                    {"agent_id": doc["id"],
                     "decision_reason": "Agent assigned after intake - hit Regenerate for a "
                                        "drafted reply, or reply manually.",
                     "updated_at": now})
            except Exception:  # noqa: BLE001 - adoption is follow-through, not the save itself
                pass
    return doc


def _sender_first_for(agent: dict, thread_name: str = "") -> str:
    """Single canonical resolver for whose first name a draft signs off with -
    every draft_reply call site (live pipeline, queue redraft, training real-
    case building, synthetic training, retrain, recheck, grading relearn)
    routes through this one function instead of deriving or hardcoding its
    own value (owner bug report 2026-07-14: the same agent was signing off
    with three different names - thread-derived, hardcoded "Bjion", or a
    blank sign-off - depending on which surface drafted the reply).

    Precedence: a non-empty `thread_name` (the live Smartlead thread's last
    SENT from_name - per-lead ground truth, since the sending mailbox may not
    literally be the agent owner) always wins. Otherwise falls back to the
    agent's own configured `sender_first`. Otherwise "" - draft_reply's
    DRAFT_SYSTEM rule ("If SenderFirst is empty, end with no sign-off line at
    all") already handles that case correctly; this resolver never invents a
    name."""
    thread_name = str(thread_name or "").strip()
    if thread_name:
        return thread_name
    return str((agent or {}).get("sender_first") or "").strip()


def _agent_memory_digest(agent: dict, limit_chars: int = 2000) -> str:
    """Plain-English digest of everything the owner has told this agent to
    REMEMBER (agent['memory'], newest-first "- {text}" lines, capped to
    roughly limit_chars) - same shape as _feedback_digest below. Fed into
    every live classify()/draft_reply() call so a remembered correction is
    actually applied on every future pass, not just recorded. One-off
    corrections never reach here - those live only in agent['feedback_log']."""
    agent = agent or {}
    lines = []
    for entry in reversed(list(agent.get("memory") or [])):
        text = str((entry or {}).get("text") or "").strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)[:limit_chars]


_LATEST_RULES_HEADER = ("LATEST OWNER RULES - newest first. These are the owner's most recent "
                        "corrections and they OVERRIDE anything older in the instructions or below. "
                        "A rule that mentions a specific reply applies only to closely similar "
                        "situations, never to every reply.")


def _latest_owner_rules(agent: dict, doc: dict = None, max_rules: int = 8, limit_chars: int = 1600) -> str:
    """Recency-weighting (owner brief 2026-07-14: "newest trainings must be
    weighted much more heavily"). Newest-first list of the owner's OWN words
    from two sources: (a) the agent's instruction_edits entries - PREFERRING
    the timeless general_rule merge_correction_into_instructions stored as
    `rule` (Feature C, 2026-07-14: a raw note is often case-specific - "this
    reply was in Spanish" - and injecting that verbatim as a top-priority
    rule can misfire on an unrelated reply; `rule` is the generalised
    restatement, with entries saved before this feature, which carry no
    `rule` key, falling back to their raw `note`) - and (b), when a training
    doc is given, that doc's answers' notes, which stay verbatim (a
    session's own answer notes are not yet merged/generalised - the header
    itself now warns the model to scope a reply-specific rule narrowly, see
    _LATEST_RULES_HEADER). Combined, deduped by exact text (the newest
    occurrence wins), cut to max_rules, and capped to roughly limit_chars.
    Returns "" when there is nothing to say (no instruction_edits, no doc,
    or no doc notes) so a caller with nothing to teach stays byte-identical
    to before this feature - see _prefix_latest_rules."""
    agent = agent or {}
    items = []  # (at, note) - not yet ordered
    for entry in (agent.get("instruction_edits") or []):
        entry = entry or {}
        note = str(entry.get("rule") or entry.get("note") or "").strip()
        if note:
            items.append((str(entry.get("at") or ""), note))
    if doc:
        for ans in (doc.get("answers") or {}).values():
            note = str((ans or {}).get("note") or "").strip()
            if note:
                items.append((str((ans or {}).get("at") or ""), note))

    items.sort(key=lambda kv: kv[0], reverse=True)  # newest first
    seen = set()
    newest_first = []
    for _at, note in items:
        if note in seen:
            continue
        seen.add(note)
        newest_first.append(note)
        if len(newest_first) >= max_rules:
            break

    if not newest_first:
        return ""
    lines = [f"{i}. {note}" for i, note in enumerate(newest_first, start=1)]
    block = _LATEST_RULES_HEADER + "\n" + "\n".join(lines)
    return block[:limit_chars]


def _prefix_latest_rules(rules_block: str, digest: str) -> str:
    """Joins the LATEST OWNER RULES block (when there is one) as a PREFIX
    onto an existing feedback/memory digest (when there is one) - block
    first, digest after, the ordering every call site below uses."""
    return "\n\n".join([x for x in (rules_block, digest) if x])


def _append_agent_memory(agent_id: str, text: str, source: str = "manual") -> dict:
    """Appends one standing correction to agent['memory'] via _save_agent's
    own partial-payload merge (only the 'memory' key is sent, so every other
    field on the doc is left exactly as it was). Returns the saved doc."""
    existing = _load_agent(agent_id) or {}
    memory = list(existing.get("memory") or [])
    memory.append({
        "text": text, "source": source or "manual", "scope": "remember",
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    })
    return _save_agent({"id": agent_id, "memory": memory})


def _append_agent_feedback_log(agent_id: str, text: str, source: str = "manual") -> dict:
    """Appends one one-off correction to agent['feedback_log'] - audit trail
    only, never fed into classify()/draft_reply(). Same merge-safe pattern as
    _append_agent_memory."""
    existing = _load_agent(agent_id) or {}
    log = list(existing.get("feedback_log") or [])
    log.append({
        "text": text, "source": source or "manual", "scope": "one_off",
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    })
    return _save_agent({"id": agent_id, "feedback_log": log})


# ── instructions merge (owner ruling 2026-07-14, single living manual) ──────

MERGE_INSTRUCTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"instructions": {"type": "string"}, "general_rule": {"type": "string"}},
    "required": ["instructions", "general_rule"],
}

MERGE_INSTRUCTIONS_SYSTEM = """You maintain an AI appointment setter's instruction manual. This manual is the ONLY brain the setter reads: every price, resource link, and rule for when to send what lives in this one text. The owner is giving you one correction from reviewing the setter's work, and your job is to integrate it into the manual.

Rules:
- Make the SMALLEST edit that makes future replies obey the correction. Do not rewrite paragraphs that are not affected.
- Keep every existing link, price, and rule in the manual unless the correction explicitly overrides one of them.
- Never invent a new link, price, or rule that the correction did not state.
- Write in plain text, short paragraphs. No em dashes anywhere, ever, use a comma or period instead.
- Return the FULL updated manual, not just the changed part and not a summary of the change.
- If the correction is unclear or does not obviously belong anywhere in the manual, add it as its own short paragraph near the end rather than guessing where it fits.

You must also produce general_rule: a single sentence that restates the correction as a TIMELESS, situation general rule, with every case specific reference removed. The owner's correction usually describes ONE reply or ONE lead (for example "this reply was in Spanish, so the whole answer must be in Spanish"); general_rule must generalise that into a standing rule that applies whenever the same underlying condition holds again (for example "Reply in the same language as the lead's most recent message."). Where the original correction was situational, phrase general_rule as a conditional: "when X, do Y". general_rule must be self-contained and must never contain the words "this reply", "this lead", or "this case".

Output STRICT JSON: {"instructions": "...", "general_rule": "..."}"""


def merge_correction_into_instructions(agent: dict, note: str, source: str = "manual"):
    """Feature A (owner ruling 2026-07-14): a "remember" correction no longer
    grows a separate memory list - it is merged straight into the agent's own
    `instructions` text, so instructions stays the single living manual every
    classify()/draft_reply() call already reads in full. Calls gpt-5-mini
    (same _HTTP/OpenAI idiom as classify()) to rewrite the manual with the
    smallest edit that makes the correction stick.

    SAFETY VALIDATION on the model's answer: every URL already in the old
    instructions must still be present in the new text (via _extract_urls -
    a merge must never silently drop a real link), the new text must be
    non-empty, and it must not have grown past max(20000, old_len*1.5) chars
    (an unbounded rewrite is a bug, not a correction). Any validation
    failure - including the call itself failing - falls back to a dumb,
    always-safe append of the note as its own dated line.

    On success (merged or appended), saves via _save_agent({id, name,
    instructions}) and appends {note, rule, at, source, how} to the agent
    doc's `instruction_edits` list - `note` is the owner's raw words (kept
    verbatim, for audit), `rule` is the timeless, situation-general
    restatement the model returns alongside instructions (general_rule -
    see MERGE_INSTRUCTIONS_SCHEMA/SYSTEM). This is Feature C's guardrail
    against a case-specific fragment ("this reply was in Spanish...")
    leaking into _latest_owner_rules verbatim and misfiring on unrelated
    replies: when general_rule is missing, empty, or still contains a
    case-specific token ("this reply"/"this lead"/"this case"), `rule`
    falls back to the raw note (today's behaviour) rather than trusting a
    bad generalisation. On the append-fallback path (no merge ever ran, or
    the merge failed validation) `rule` is always the raw note - there is no
    model output to generalise from. Never raises. Returns (ok,
    new_instructions, detail): ok is False only when the agent has no id to
    save against; detail is "merged" or "appended"."""
    agent = agent or {}
    agent_id = agent.get("id")
    note = str(note or "").strip()
    old = _agent_instructions(agent)
    if not agent_id:
        return False, old, "agent has no id"
    if not note:
        return True, old, "empty note"

    at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    def _append_fallback():
        line = f"Training note ({at[:10]}): {note}"
        return (old + "\n\n" + line).strip() if old else line

    _CASE_SPECIFIC_TOKENS = ("this reply", "this lead", "this case")

    new_text = None
    how = "appended"
    rule = note
    try:
        key = _KEYS.get("OPENAI_API_KEY")
        if key:
            payload = {"current_instructions": old, "correction": note}
            r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {key}"},
                     {"model": OPENAI_MODEL,
                      "messages": [{"role": "system", "content": MERGE_INSTRUCTIONS_SYSTEM},
                                  {"role": "user", "content": json.dumps(payload)}],
                      "response_format": {"type": "json_schema", "json_schema": {
                          "name": "setter_instructions_merge", "strict": True,
                          "schema": MERGE_INSTRUCTIONS_SCHEMA}}})
            if isinstance(r, dict) and not r.get("error"):
                data = json.loads(r["choices"][0]["message"]["content"])
                candidate = str(data.get("instructions") or "").strip()
                old_urls = set(_extract_urls(old))
                cand_urls = set(_extract_urls(candidate))
                max_len = max(20000, int(len(old) * 1.5))
                if candidate and old_urls.issubset(cand_urls) and len(candidate) <= max_len:
                    new_text = candidate
                    how = "merged"
                    general_rule = str(data.get("general_rule") or "").strip()
                    lowered = general_rule.lower()
                    if general_rule and not any(t in lowered for t in _CASE_SPECIFIC_TOKENS):
                        rule = general_rule
    except Exception:  # noqa: BLE001 - any failure here just falls back to append
        new_text = None

    if new_text is None:
        new_text = _append_fallback()
        how = "appended"
        rule = note

    edits = list(agent.get("instruction_edits") or [])
    edits.append({"note": note, "rule": rule, "at": at, "source": source or "manual", "how": how})
    saved = _save_agent({"id": agent_id, "name": agent.get("name"), "instructions": new_text,
                         "instruction_edits": edits})
    return True, saved.get("instructions") or new_text, how


LESSON_FROM_EDIT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_lesson", "rule", "reason"],
    "properties": {
        "is_lesson": {"type": "boolean"},
        "rule": {"type": "string"},
        "reason": {"type": "string"},
    },
}

LESSON_FROM_EDIT_SYSTEM = """An AI appointment setter drafted a reply. A human reviewer edited it before approving. You are given both versions. Decide whether the edit teaches a rule worth applying to EVERY future reply, and if so, state that rule.

Almost all edits are NOT lessons. Default to is_lesson=false. A missed lesson costs nothing - the reviewer can always say it in words. A wrong rule silently corrupts every future draft, which is far worse. When in any doubt at all, answer false.

THE DECIDING TEST - apply it first, and let it overrule everything else:

Does the edit change HOW the reply is written, or WHAT it claims to be true?

- HOW = style, structure, length, tone, ordering, what to leave out. The reviewer worked with the same facts the setter had and expressed them differently. This CAN be a lesson.
- WHAT = information. The reviewer added, changed, or corrected a fact the setter did not have: a price, an availability, a circumstance, a name, a date, a link, a detail about this person or this deal. This is NEVER a lesson, no matter how general it sounds when you write it down. The reviewer was supplying knowledge about one conversation, not teaching a writing preference.

Beware the trap: almost any WHAT edit can be dressed up as a plausible-sounding general rule. "They're away until August, so I'll suggest September" becomes "acknowledge when the recipient is unavailable and propose a time after they return". "For your volume we'd do $2,400" becomes "quote a price matched to the lead's volume". Both READ like sensible advice and both are catastrophic: taught as rules, they make the setter invent availability it cannot know and prices it was never given. If the reviewer's edit introduced information that is not in the setter's draft, answer false - however reasonable the generalisation seems.

It IS a lesson only when the edit shows a durable PREFERENCE about how replies should be written - something that would read as sensible advice to someone drafting a reply to a completely different lead tomorrow, using facts they already have. Examples of real lessons: the reviewer cuts a stock closing line the setter always adds; the reviewer shortens rambling paragraphs; the reviewer strips hedging words; the reviewer moves the booking link after the value; the reviewer deletes an internal placeholder that leaked into the text.

It is NOT a lesson when the edit is:
- Any WHAT edit, per the deciding test above.
- A per-lead fact: a person's name, a company name, a job title, a specific date, a specific time, a timezone, a price for this one deal, a link pasted for this one lead.
- Anything true only of this conversation ("they're away until August", "they already have the deck").
- Formatting, whitespace, HTML, punctuation, or typo repair with no preference behind it.
- A change so small or so specific that you cannot restate it without naming something from this particular reply.

The rule you return must be TIMELESS: an imperative sentence about how to write replies in general. It must NOT contain any person's name, any company name, any date, any time, any URL, any price, or the words "this reply", "this lead", or "this case". If you cannot state the rule without one of those, it is not a lesson - answer false.

You are also given the setter's current instruction manual. Read it before deciding. If the edit undoes something the manual deliberately asks for, the reviewer was making a one-off exception for this conversation - they were NOT rewriting the manual. Answer false. A reviewer who genuinely wants to change a standing instruction says so in words; they do not signal it by silently deleting it once. Never return a rule that contradicts the manual.

Keep the rule under 200 characters. Put your justification in `reason`, never in `rule`."""


_LESSON_CASE_TOKENS = ("this reply", "this lead", "this case", "this one", "this email", "this thread")
# A rule that names a date, a clock time, or a link is by definition about one
# conversation, not about how to write replies. The model is told all of this;
# these checks exist because it will sometimes say so anyway.
_LESSON_DATE_RE = re.compile(
    r"\b(\d{1,2}[:.]\d{2}\s*(am|pm)?|\d{1,2}\s*(am|pm)|"
    r"mon|tues?|wed(nes)?|thur?s?|fri|sat(ur)?|sun)(day)?\b|"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", re.I)


def _draft_text(html: str) -> str:
    """The visible words of a draft, with markup and whitespace noise gone -
    so a diff compares what the lead would READ, not what the editor emitted.
    A contenteditable rewraps tags constantly; comparing raw HTML would call
    every reload an edit."""
    txt = re.sub(r"<br\s*/?>|</p>|</div>", "\n", html or "", flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = (txt.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", txt).strip()


def lesson_from_edit(generated_html: str, sent_html: str, context: dict | None = None,
                    instructions: str = ""):
    """The reviewer rewrote a draft and approved it. Returns a timeless rule to
    teach the agent, or None to teach nothing.

    Owner ask 2026-07-17: editing a draft IS feedback - the reviewer showing
    rather than telling. Typed feedback already teaches via
    merge_correction_into_instructions; this closes the far more common path
    where someone just fixes the text and hits Approve.

    Returning None is the DEFAULT and the safe answer. An edit-diff is far
    more case-specific than a typed note - it is full of names, times and
    links - and a case-specific fragment reaching the rules block is not a
    hypothetical: it shipped once, and an English lead got a Spanish draft
    (commit af9c1dd). So the model's own is_lesson verdict is never trusted on
    its own; every rule it proposes must also survive the checks below, and
    anything that smells of one conversation is dropped. Never raises: any
    failure means teach nothing.

    context may carry lead_first_name / lead_last_name / company_domain, used
    only to reject a rule that names them.

    instructions is the agent's current manual. It is passed so the model can
    refuse an edit that merely undoes something the manual deliberately asks
    for. Live proof 2026-07-17: the Navreo manual says in as many words to
    leave a "[PASTE LOOM LINK HERE]" placeholder for a human to fill; a
    reviewer deleting that placeholder once produced the rule "remove internal
    placeholders and editorial notes", which flatly contradicts it. Undoing an
    instruction once is an exception for one lead, not a rewrite of the manual
    - someone who wants the standing rule changed says so in words."""
    try:
        gen, sent = _draft_text(generated_html), _draft_text(sent_html)
        # Free rejections before spending a token: an untouched draft, a
        # cosmetic-only change, or an edit with nothing left to compare.
        if not gen or not sent or gen == sent:
            return None
        if gen.lower() == sent.lower():
            return None
        key = _KEYS.get("OPENAI_API_KEY")
        if not key:
            return None
        payload = {"setter_draft": gen, "reviewer_final": sent,
                   "instruction_manual": (instructions or "")[:12000]}
        r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                 {"Authorization": f"Bearer {key}"},
                 {"model": OPENAI_MODEL,
                  "messages": [{"role": "system", "content": LESSON_FROM_EDIT_SYSTEM},
                              {"role": "user", "content": json.dumps(payload)}],
                  "response_format": {"type": "json_schema", "json_schema": {
                      "name": "setter_lesson_from_edit", "strict": True,
                      "schema": LESSON_FROM_EDIT_SCHEMA}}})
        if not isinstance(r, dict) or r.get("error"):
            return None
        data = json.loads(r["choices"][0]["message"]["content"])
        if not data.get("is_lesson"):
            return None
        rule = str(data.get("rule") or "").strip()
        if not rule or len(rule) > 200:
            return None
        lowered = rule.lower()
        if any(t in lowered for t in _LESSON_CASE_TOKENS):
            return None
        if _extract_urls(rule):
            return None
        if _LESSON_DATE_RE.search(rule):
            return None
        # A rule that names the person or company in front of it is describing
        # one conversation, whatever the model claims.
        ctx = context or {}
        for field in ("lead_first_name", "lead_last_name"):
            name = str(ctx.get(field) or "").strip()
            if len(name) > 2 and re.search(rf"\b{re.escape(name.lower())}\b", lowered):
                return None
        domain = str(ctx.get("company_domain") or "").strip().lower()
        if domain:
            if domain in lowered:
                return None
            stem = domain.split(".")[0]
            if len(stem) > 3 and re.search(rf"\b{re.escape(stem)}\b", lowered):
                return None
        return rule
    except Exception:  # noqa: BLE001 - a learning outage must never touch the send
        return None


def _existing_row(workspace: str, campaign_id, email: str, message_id: str):
    if not _SB:
        return None
    try:
        # quote(): both key values routinely carry "+" (synthetic ids embed
        # "+00:00", real Message-IDs allow it), and an unencoded "+" reaches
        # PostgREST as a space - the filter then never matches and intake
        # re-claims the same reply every poll tick.
        em, mid = quote(str(email), safe=""), quote(str(message_id), safe="")
        base = (f"{QUEUE_TABLE}?workspace=eq.{workspace}&smartlead_campaign_id=eq.{campaign_id}"
                f"&lead_email=eq.{em}")
        rows = _SB("GET", f"{base}&message_id=eq.{mid}&select=*&limit=1")
        if isinstance(rows, list) and rows:
            return rows[0]
        # Hydration swaps message_id to the real RFC Message-ID from the
        # thread, so the key the row was CLAIMED under survives only in
        # source_message_id - without this second check the poll re-intakes
        # every already-processed reply on every tick.
        rows = _SB("GET", f"{base}&source_message_id=eq.{mid}&select=*&limit=1")
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001
        return None


def _apply_patch(row: dict, patch: dict):
    if _SB and row.get("id") is not None:
        try:
            _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{row['id']}", patch)
        except Exception:  # noqa: BLE001
            pass
    # A row changed under the read caches (status moves it between pills;
    # thread/draft edits change its content) - hard-drop them all and start a
    # rewarm so the reload the UI fires right after an action reads fresh
    # (perf pass 2026-07-16: queue GETs are served from short-TTL caches now).
    # No-op patches skip the bust: route_thread_get re-persists the thread on
    # EVERY conversation open, and an unchanged thread must not thrash caches.
    if any(row.get(k) != v for k, v in patch.items()):
        _bust_read_caches()


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


def _resolve_stats_id(row: dict):
    """Returns (stats_id_str, error_msg). Smartlead's reply-email-thread rejects a
    non-string email_stats_id with a raw Joi 400 ('"email_stats_id" must be a
    string'), which is exactly what a reviewer saw when hydration at intake had
    left the column NULL.

    Intake hydration is best-effort and its Smartlead call can fail transiently
    (live rows carried 'Couldn't load the Smartlead thread (HTTPError)' and
    '(TimeoutError)'). Nothing retried, so the row sat in Needs-review looking
    sendable with no stats_id forever. Re-hydrating here fixes it at the only
    moment it matters, and the recovered id is persisted so the next send is free.
    Verified 2026-07-16: all six affected rows re-hydrated on retry.
    """
    sid = row.get("email_stats_id")
    if sid is not None and str(sid).strip():
        return str(sid), ""
    ok, hyd, herr = hydrate_lead(row.get("smartlead_campaign_id"), row.get("lead_email"),
                                 row.get("message_id"))
    sid = hyd.get("email_stats_id") if ok else None
    if sid is None or not str(sid).strip():
        # Never hand Smartlead a null and never relay its Joi text to a human.
        return "", ("Couldn't match this reply to its Smartlead thread, so it can't be "
                    "replied to from here. Reply in Smartlead directly."
                    + (f" ({herr})" if herr else ""))
    patch = {"email_stats_id": str(sid)}
    # smartlead_lead_id goes NULL in the same failed hydration - take it back too
    # while we have it, so the row stops being half-hydrated.
    if row.get("smartlead_lead_id") is None and hyd.get("smartlead_lead_id") is not None:
        patch["smartlead_lead_id"] = hyd.get("smartlead_lead_id")
    _apply_patch(row, patch)
    return str(sid), ""


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
    stats_id, sid_err = _resolve_stats_id(row)
    if not stats_id:
        patch = {"status": "needs_review", "error": sid_err}
        _apply_patch(row, patch)
        return {"ok": False, "row": patch}
    try:
        body = {
            "email_stats_id": stats_id,
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


def _self_heal_campaigns(agent: dict, cids: list) -> None:
    """Backlog sweep for campaigns just newly attached to `agent` (called from
    a daemon thread by route_agents_save - see the 7-day backdated stamp in
    _save_agent). Owner ruling 2026-07-15: attaching a campaign shouldn't
    silently start the clock from zero - recent positives already sitting
    in Supabase should get swept into the queue as drafts. Never raises -
    this runs detached from any request/response cycle, so an uncaught
    exception here would just vanish silently instead of surfacing anywhere.
    """
    adopted = swept = errors = 0
    try:
        if not _SB or not cids:
            return
        # SEND-SAFETY GATE (non-negotiable): this function must NEVER be able
        # to auto-send, even if the real agent doc is in autopilot mode - a
        # backlog sweep running unattended in a background thread is exactly
        # the kind of blast-radius a bug here should not have. Every
        # downstream pipeline call below uses `snapshot`, never `agent`.
        snapshot = {**agent, "mode": "draft_only"}
        csv = ",".join(str(c) for c in cids)

        # Step 1: adopt stranded rows - queue rows already sitting in
        # needs_review for these campaigns without a draft get classified/
        # drafted now that there is a brain for them. Matched on
        # draft_body=is.null rather than agent_id=is.null because _save_agent
        # itself already claims agentless rows synchronously during the save
        # (agent_id + "hit Regenerate" reason, 2026-07-14) - by the time this
        # background thread runs, those rows are no longer agentless, and the
        # owner ruling 2026-07-15 upgrades adoption to retro-assign + DRAFT.
        # The or= keeps it scoped to rows that are ours to draft: still
        # agentless, or already claimed by this same agent. Status stays
        # needs_review either way - this only fills in the draft, it never
        # auto-decides or auto-sends.
        try:
            aid = quote(str(agent.get("id") or ""), safe="")
            stranded = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&smartlead_campaign_id=in.({csv})"
                                  f"&status=eq.needs_review&draft_body=is.null"
                                  f"&or=(agent_id.is.null,agent_id.eq.{aid})&select=*")
        except Exception:  # noqa: BLE001
            stranded = None
        if isinstance(stranded, list):
            for row in stranded:
                if not isinstance(row, dict):
                    continue
                try:
                    body_text = clean_body(row.get("reply_body") or "")
                    last_outbound = ""
                    for m in reversed(row.get("thread") or []):
                        if str(m.get("type") or "").upper() == "SENT":
                            last_outbound = _TAG_RE.sub(" ", str(m.get("body") or ""))[:800]
                            break
                    first_outbound = row.get("first_outbound") or ""
                    if not first_outbound:
                        for m in (row.get("thread") or []):
                            if str(m.get("type") or "").upper() == "SENT":
                                first_outbound = clean_body(str(m.get("body") or ""))[:1500]
                                break
                    domain = (row.get("company_domain") or "").lower()
                    comp_hints = _company_hints(domain)
                    company_location = ", ".join([v for v in (comp_hints.get("country"), comp_hints.get("state"),
                                                              comp_hints.get("city")) if v])
                    mem_hints = _prefix_latest_rules(_latest_owner_rules(snapshot), _agent_memory_digest(snapshot))
                    classification = classify({"subject": row.get("reply_subject"), "body": body_text,
                                               "last_outbound": last_outbound, "first_outbound": first_outbound,
                                               "email_domain": domain, "company_location": company_location},
                                              snapshot, owner_hints=mem_hints)
                    now = _dt.datetime.now(_dt.timezone.utc)
                    tz = row.get("timezone")
                    slots, slot_status = [], "not_configured"
                    if tz:
                        eff_settings = dict(_load_settings())
                        eff_settings["_agent"] = snapshot
                        eff_settings["_lead"] = {"first_name": row.get("lead_first_name"),
                                                 "last_name": row.get("lead_last_name"),
                                                 "email": row.get("lead_email")}
                        slot_status, avail, _serr = get_calendly_availability(snapshot, eff_settings, now)
                        if slot_status == "ok":
                            slots = pick_slots(avail, tz, eff_settings, now)
                            if not slots:
                                slot_status = "none_available"
                    thread_text = " ".join(str(m.get("body") or "") for m in (row.get("thread") or []))
                    d = draft_reply(
                        {"first_name": row.get("lead_first_name"), "subject": row.get("reply_subject"),
                         "body": row.get("reply_body"), "first_outbound": first_outbound,
                         "thread_text": thread_text},
                        snapshot, classification, slots, slot_status,
                        sender_first=_sender_first_for(snapshot))
                    draft_html = d.get("html")
                    if draft_html:
                        draft_html, _changed = proofread_draft(draft_html)
                    patch = {"agent_id": agent.get("id"), "classification": classification,
                             "draft_subject": d.get("subject"), "draft_body": draft_html,
                             "original_draft_body": draft_html, "slots": slots}
                    if tz:
                        patch["timezone"] = tz
                    _apply_patch(row, patch)
                    adopted += 1
                except Exception as e:  # noqa: BLE001 - one bad stranded row must never stop the rest
                    errors += 1
                    print(f"[setter] self-heal: adopt failed for row {row.get('id')}: {e}", file=sys.stderr)

        # Step 2: sweep the 7-day backlog window this attach just opened (see
        # the backdated campaign_assigned_at stamp in _save_agent). Mirrors
        # run_poll's replies query/field-list exactly, scoped to just these
        # campaign ids instead of the whole workspace, capped at 30 so a
        # heavily-backlogged campaign can't run away in a background thread.
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)).isoformat()
        try:
            replies = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&smartlead_campaign_id=in.({csv})"
                                 f"&replied_at=gte.{quote(since, safe='')}&order=replied_at.asc&limit=200"
                                 f"&select=id,smartlead_campaign_id,email,replied_at,category,"
                                 f"reply_subject,reply_body,smartlead_message_id")
        except Exception:  # noqa: BLE001
            replies = None
        if isinstance(replies, list):
            settings = _load_settings()
            for r in replies:
                if swept >= 30:
                    break
                if not isinstance(r, dict):
                    continue
                if r.get("category") not in CORE_FOUR:
                    continue
                cid = r.get("smartlead_campaign_id")
                email = (r.get("email") or "").strip().lower()
                mid = str(r.get("smartlead_message_id") or r.get("message_id") or r.get("id") or "")
                if not cid or not email or not mid:
                    continue
                # Rows adopted in step 1 (and anything else already queued)
                # correctly match here and get skipped - that is intentional,
                # not a bug: it means no reply is processed twice.
                if _existing_row(WORKSPACE, cid, email, mid):
                    continue
                reply = {
                    "workspace": WORKSPACE, "campaign_id": cid, "email": email,
                    "first_name": r.get("first_name"), "last_name": r.get("last_name"),
                    "company_domain": r.get("company_domain"),
                    "subject": r.get("reply_subject") or r.get("subject"),
                    "body": r.get("reply_body") or r.get("body") or "",
                    "replied_at": r.get("replied_at"), "message_id": mid,
                    "category": r.get("category"), "is_test": False,
                }
                try:
                    process_reply(reply, snapshot, settings)
                    swept += 1
                except Exception as e:  # noqa: BLE001 - one bad reply must never stop the sweep
                    errors += 1
                    print(f"[setter] self-heal: sweep error for {email}/{cid}: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - this whole function must never raise, it runs unattended
        errors += 1
        print(f"[setter] self-heal: crashed for campaigns {cids}: {e}", file=sys.stderr)
    finally:
        print(f"[setter] self-heal: campaigns={cids} adopted={adopted} swept={swept} errors={errors}",
             file=sys.stderr)


def _intake_agentless(reply: dict) -> dict:
    """Agentless intake (owner ruling 2026-07-14): "we shouldn't need to
    assign an agent to a campaign to be able to receive the positives - it
    should come in regardless." A core-four reply on a campaign with no
    agent still reaches setter_queue, just flagged for manual review - the
    UI is responsible for surfacing the missing-agent state subtly, not this
    pipeline. Deliberately skips classify/draft/decide: there is no agent
    brain to run those with. It DOES hydrate the Smartlead thread (owner
    follow-up 2026-07-14) - manual review needs the conversation context and
    the original outreach just as much as the agented path does. Shared by
    run_poll and handle_inbound so both intake paths insert the identical
    row shape. Never raises - mirrors process_reply."""
    try:
        workspace = reply.get("workspace") or WORKSPACE
        campaign_id = reply.get("campaign_id")
        email = (reply.get("email") or "").strip().lower()
        message_id = str(reply.get("message_id") or "")
        is_test = bool(reply.get("is_test"))

        if not is_test:
            existing = _existing_row(workspace, campaign_id, email, message_id)
            if existing:
                return existing

        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        domain = (reply.get("company_domain") or (email.split("@", 1)[1] if "@" in email else "")).lower()
        row = {
            "workspace": workspace, "smartlead_campaign_id": campaign_id, "agent_id": None,
            "lead_email": email, "lead_first_name": reply.get("first_name") or "",
            "lead_last_name": reply.get("last_name") or "", "company_domain": domain,
            "message_id": message_id, "source_message_id": message_id,
            "reply_subject": reply.get("subject") or "",
            "reply_body": reply.get("body") or "", "replied_at": reply.get("replied_at") or now_iso,
            "category": reply.get("category"), "thread": [], "smartlead_lead_id": None,
            "email_stats_id": None, "classification": None, "guardrails": None,
            "timezone": None, "slots": [], "draft_subject": None, "draft_body": None,
            "decision": "review",
            "decision_reason": "No agent is assigned to this campaign yet - review and reply "
                               "manually, or assign an agent.",
            "status": "needs_review",
            "added_to_subsequence": False, "sent_at": None, "sent_body": None, "error": None,
            "is_test": is_test,
        }
        # Context hydration (owner follow-up 2026-07-14): a review-only row is
        # useless without the thread - "send the video, I'll look at it" can't
        # be answered manually when the original outreach isn't shown, which is
        # exactly what the reviewer sees on every agentless row. classify/
        # draft/decide stay skipped (there is no agent brain to run them), but
        # the Smartlead history is agent-independent, so fetch it here just
        # like the agented pipeline does. Best-effort: hydration failure never
        # blocks the intake - the reply still lands, just without the thread.
        if not is_test:
            try:
                ok, hyd, _herr = hydrate_lead(campaign_id, email, message_id)
                if ok:
                    row["smartlead_lead_id"] = hyd.get("smartlead_lead_id")
                    row["email_stats_id"] = hyd.get("email_stats_id")
                    # Real RFC Message-ID replaces the synthetic claim key;
                    # source_message_id keeps the original so _existing_row's
                    # two-key dedupe (d38a301) still recognises this row.
                    row["message_id"] = str(hyd.get("reply_message_id") or message_id)
                    row["reply_subject"] = hyd.get("reply_subject") or row["reply_subject"]
                    row["reply_body"] = hyd.get("reply_email_body") or row["reply_body"]
                    row["replied_at"] = hyd.get("reply_email_time") or row["replied_at"]
                    row["thread"] = hyd.get("thread") or []
                    row["lead_first_name"] = hyd.get("first_name") or row["lead_first_name"]
                    row["lead_last_name"] = hyd.get("last_name") or row["lead_last_name"]
                    row["first_outbound"] = hyd.get("first_outbound") or ""
            except Exception:  # noqa: BLE001 - context is a nice-to-have, intake is the job
                pass
        return _finalize_row(row)
    except Exception as e:  # noqa: BLE001 - agentless intake must never crash its caller
        reply = reply or {}
        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        return {
            "workspace": reply.get("workspace") or WORKSPACE,
            "smartlead_campaign_id": reply.get("campaign_id"), "agent_id": None,
            "lead_email": (reply.get("email") or "").strip().lower(),
            "message_id": str(reply.get("message_id") or ""),
            "reply_body": reply.get("body") or "",
            "status": "error", "decision": "review",
            "decision_reason": "Held for review: something went wrong processing this reply.",
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "is_test": bool(reply.get("is_test")),
            "created_at": now_iso, "updated_at": now_iso,
        }


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
        "message_id": message_id, "source_message_id": message_id,
        "reply_subject": reply.get("subject") or "",
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
                "lead_last_name", "company_domain", "message_id", "source_message_id",
                "reply_subject", "reply_body", "replied_at", "category", "is_test")}
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
    first_outbound = reply.get("first_outbound") or ""
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
        first_outbound = hyd.get("first_outbound") or first_outbound
        # Self-learning (owner bug report 2026-07-14): the thread's real SENT
        # from_name is per-lead ground truth for this agent's sign-off. The
        # first time it shows up for an agent with no sender_first configured
        # yet, stamp it onto the agent doc ONCE so every other surface -
        # training, redraft, retrain, recheck, none of which have a thread to
        # read - inherits the same identity via _sender_first_for instead of
        # guessing or hardcoding "Bjion". Never overwrites a name the owner
        # (or an earlier stamp) already set - _save_agent's merge semantics
        # only fill in fields, they never blank an existing value here since
        # we gate on agent.get("sender_first") being empty first.
        thread_name = hyd.get("sender_first") or ""
        if thread_name and not agent.get("sender_first") and agent.get("id"):
            try:
                _save_agent({"id": agent["id"], "sender_first": thread_name})
                agent["sender_first"] = thread_name
            except Exception:  # noqa: BLE001 - the stamp is a nice-to-have, never worth failing the pipeline
                pass
        # Hydration can resolve a different (real) message id than the one we
        # claimed under. If another row already owns the real key, the other
        # intake path (webhook vs poll) got here first - stand down rather
        # than process the same reply twice.
        if row["message_id"] != message_id:
            other = _existing_row(workspace, campaign_id, email, row["message_id"])
            if other and other.get("id") != row.get("id"):
                # Delete our own claim rather than leaving a dismissed husk -
                # the claim row exists only as this invocation's lock, and a
                # husk per race pollutes the queue forever.
                if row.get("id") is not None:
                    try:
                        _SB("DELETE", f"{QUEUE_TABLE}?id=eq.{row['id']}")
                    except Exception:  # noqa: BLE001 - a leftover husk is not worth a crash
                        pass
                return other

    # Canonical identity resolution (see _sender_first_for): the thread-
    # derived name (or, for a test-injected reply, whatever the caller passed
    # in reply["sender_first"]) always wins when present; an empty hydration
    # falls back to the agent's own configured identity instead of "".
    sender_first = _sender_first_for(agent, sender_first)

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
    # the FIRST email we sent - the original pitch this reply is answering.
    # Hydration provides it from the full history; fall back to the earliest
    # SENT in whatever thread we have (test-inject rows may carry one).
    if not first_outbound:
        for m in (row.get("thread") or []):
            if str(m.get("type") or "").upper() == "SENT":
                first_outbound = clean_body(str(m.get("body") or ""))[:1500]
                break

    # timezone hints
    comp_hints = _company_hints(domain)
    tld = domain.rsplit(".", 2)[-1] if domain else ""
    two_part = ".".join(domain.split(".")[-2:]) if domain.count(".") >= 1 else ""
    hints = {
        "country": comp_hints.get("country"), "state": comp_hints.get("state"), "city": comp_hints.get("city"),
        "phone": _extract_phone(body_text), "tld": two_part or tld, "body": body_text,
    }
    company_location = ", ".join([v for v in (comp_hints.get("country"), comp_hints.get("state"),
                                              comp_hints.get("city")) if v])

    lex_hits = lexicon_hits(body_text)

    # Thread text (for a later-turn draft to read as a continuation - see
    # draft_reply's recent_thread) computed once here so both the draft call
    # below and the lint context further down share the same value.
    thread_text = " ".join(str(m.get("body") or "") for m in (row.get("thread") or []))

    # Persistent learning layer: everything the owner has told this agent to
    # remember, fed automatically into every live classify()/draft_reply()
    # call. Empty memory -> empty digest -> classify()/draft_reply() add
    # nothing to their payload, so behaviour is byte-identical to before this
    # feature existed. The LATEST OWNER RULES block (recency weighting -
    # owner brief 2026-07-14) is always the PREFIX, so the newest corrections
    # dominate even when the standing memory digest is long.
    mem_digest = _prefix_latest_rules(_latest_owner_rules(agent), _agent_memory_digest(agent))

    row["first_outbound"] = first_outbound
    try:
        classification = classify({"subject": row["reply_subject"], "body": body_text,
                                   "last_outbound": last_outbound, "first_outbound": first_outbound,
                                   "email_domain": domain, "company_location": company_location},
                                  agent, owner_hints=mem_digest)
    except Exception as e:  # noqa: BLE001 - a classify outage must degrade to review, never crash
        classification = {
            "primary_intent": None, "all_intents": [], "simple_ask": False, "confidence": 0.0,
            "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0, "wants": "",
            "rationale": f"classification failed: {type(e).__name__}",
        }
        row["error"] = row.get("error") or f"classify failed: {type(e).__name__}"
    row["classification"] = classification

    tz, tz_confident = resolve_timezone(hints, classification)
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
    # Owner ruling (2026-07-15): anything that will actually SURFACE in the
    # queue must carry a draft, even when the agent is unsure — the human
    # wants a starting point, not a blank composer. decide() holds a clear
    # negative for review when Smartlead's categoriser disagrees or the reply
    # points at a live opening; mirror those two conditions here so exactly
    # the rows that surface get drafted, and true no_action negatives keep
    # their no-draft short-circuit.
    negative_but_surfaces = is_clear_negative and (
        (category in POSITIVE_CATEGORIES) or bool(classification.get("live_lead")))
    wants_draft = (not is_clear_negative) or negative_but_surfaces

    slots, slot_status = [], "not_configured"
    if wants_draft:
        eff_settings = dict(settings)
        eff_settings["_agent"] = agent
        eff_settings["_lead"] = {"first_name": row["lead_first_name"], "last_name": row["lead_last_name"], "email": email}
        # Build slots only when we have a timezone (even a low-confidence
        # guess) - so a held draft shows plausible LOCAL times. When the
        # timezone is genuinely unknown we never fabricate London times; the
        # draft falls back to booking-link phrasing instead.
        if tz:
            slot_status, avail, serr = get_calendly_availability(agent, eff_settings, now)
            if slot_status == "ok":
                slots = pick_slots(avail, tz, eff_settings, now)
                if not slots:
                    slot_status = "none_available"
            if serr and not row.get("error"):
                row["error"] = serr
        else:
            slot_status = "tz_unknown"
    row["slots"] = slots

    draft_subject, draft_body = None, None
    if wants_draft:
        try:
            d = draft_reply(
                {"first_name": row["lead_first_name"], "subject": row["reply_subject"], "body": body_text,
                 "first_outbound": first_outbound, "thread_text": thread_text},
                agent, classification, slots, slot_status, sender_first, regen_feedback=mem_digest)
            draft_subject, draft_body = d.get("subject"), d.get("html")
            if draft_body:
                # Second sweep (owner brief 2026-07-14): proofread the draft
                # BEFORE lint_draft below, so lint checks the final text.
                draft_body, _proofread_changed = proofread_draft(draft_body)
        except Exception as e:  # noqa: BLE001 - a draft outage falls back to no draft -> lint fails -> review
            if not row.get("error"):
                row["error"] = f"draft failed: {type(e).__name__}"
    row["draft_subject"], row["draft_body"] = draft_subject, draft_body
    # The pristine generated draft, kept beside the working copy: save_draft
    # overwrites draft_body with the reviewer's hand-edits from the first
    # keystroke on, so this is the only record of what the agent itself wrote
    # and the only thing an Approve-time diff can learn from. Stamped wherever
    # the AGENT drafts (here, self-heal adopt, redraft) and nowhere else -
    # never by save_draft, never by _send_reply.
    row["original_draft_body"] = draft_body

    # Calendly fallback (owner ruling 2026-07-14): whenever real call times
    # aren't available for any reason, slot_status is something other than
    # "ok" and the drafter is asked for the fallback availability-ask
    # instead of two fixed times - see decide() gate 7 and lint_draft().
    slots_fallback = slot_status != "ok"
    needs_availability_ask = "scheduling" in (classification.get("all_intents") or [])

    lint_ok, lint_reason = False, "No draft was produced."
    if draft_body:
        needs_resource_link = "send_resource" in (classification.get("all_intents") or [])
        ctx_lint = {
            "subject": draft_subject, "first_name": row["lead_first_name"],
            "needs_resource_link": needs_resource_link,
            "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
            "slot_labels": [s.get("label") for s in slots],
            "instructions": _agent_instructions(agent), "booking_link": _booking_link(agent),
            "thread_text": f"{body_text} {thread_text}",
            "slots_fallback": slots_fallback, "needs_availability_ask": needs_availability_ask,
        }
        lint_ok, lint_reason = lint_draft(draft_body, ctx_lint)

    ctx = {
        "red_flag_hits": lex_hits, "category": category, "first_touch": first_touch,
        "slot_status": slot_status, "slots_fallback": slots_fallback,
        "timezone": tz, "tz_confident": tz_confident,
        "lint_ok": lint_ok, "lint_reason": lint_reason,
        "body_len": len(body_text or ""), "hydrated": hydrated,
        "answered_since_reply": answered_since_reply,
        "autopilot_enabled": bool(settings.get("autopilot_enabled")),
        "same_day_ask": bool(_SAME_DAY_RE.search(_strip_quoted(body_text or ""))),
        "first_outbound_present": bool((first_outbound or "").strip()),
        "needs_availability_ask": needs_availability_ask,
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

# ── backstop reply-sync: master-inbox pull → categoriser hook ────────────────
# The Smartlead EMAIL_REPLY webhook is the fast-path into the reply-categoriser
# (Make scenario 9251436) but it is lossy: it never fires for subsequence-
# campaign replies ("Interested Reply"/"Meeting Request" subsequences) and lags
# under reply bursts. This cron pulls the master inbox every ~3 min and feeds
# each UNSEEN reply to the SAME categoriser hook so `replies` becomes complete.
# Dedup is EXACT: the categoriser archives on
#   smartlead_message_id = "{sl_email_lead_id}-{reply_message.time}"
# and both fields here come straight off the master-inbox row
# (email_lead_id + last_reply_time, already ".000Z"), so a pull-fed reply and a
# webhook-fed one collapse to ONE `replies` row (unique index replies_dedupe)
# and the categoriser's "no existing category" gate stops a second Slack.
# NEVER re-implements GPT categorisation; NEVER calls an MCP tool.
CATEGORISER_HOOK = "https://hook.eu2.make.com/6mda3nqyrtm8u4x9ihilymra4z70aaug"
REPLY_SYNC_CAP = 300           # replies processed per run; overflow => run FAILED with gap
_REPLY_SYNC_FIRST_WINDOW_H = 2  # a fresh/empty watermark seeds at now-minus-2h


def _reply_sync_watermark():
    """Reads the single-row watermark; seeds now-minus-2h if the table is empty.
    Returns (watermark_dt, seeded: bool)."""
    now = _dt.datetime.now(_dt.timezone.utc)
    rows = _SB("GET", "reply_sync_state?id=eq.1&select=watermark") if _SB else None
    if isinstance(rows, list) and rows and rows[0].get("watermark"):
        wm = _parse_iso(rows[0]["watermark"])
        if wm:
            return wm, False
    seed = now - _dt.timedelta(hours=_REPLY_SYNC_FIRST_WINDOW_H)
    if _SB:
        _SB("POST", "reply_sync_state", {"id": 1, "watermark": seed.isoformat()},
            prefer="resolution=merge-duplicates")
    return seed, True


def _reply_sync_seen(mid: str) -> bool:
    """True if this message_id was already POSTed to the categoriser (belt-and-
    braces on top of the `replies` unique index — stops a re-POST while the
    categoriser is still in-flight, before the row lands in `replies`)."""
    if not _SB or not mid:
        return False
    rows = _SB("GET", f"reply_sync_seen?message_id=eq.{quote(mid, safe='')}&select=message_id&limit=1")
    return isinstance(rows, list) and bool(rows)


def _reply_in_archive(mid: str) -> bool:
    """True if the categoriser has already archived this reply into `replies`
    (e.g. the webhook fast-path beat the pull to it)."""
    if not _SB or not mid:
        return False
    rows = _SB("GET", f"replies?workspace=eq.{WORKSPACE}"
                      f"&smartlead_message_id=eq.{quote(mid, safe='')}&select=id&limit=1")
    return isinstance(rows, list) and bool(rows)


def _mark_reply_seen(mid: str) -> None:
    if _SB and mid:
        _SB("POST", "reply_sync_seen", {"message_id": mid},
            prefer="resolution=merge-duplicates")


def _fetch_master_inbox_window(since_iso: str, until_iso: str, hard_cap: int):
    """Raw Smartlead master-inbox list for replies in [since, until].
    POST /master-inbox/inbox-replies (MCP-free, built on _sl_post — the MCP
    tool `fetch_master_inbox_replies` wraps this same endpoint but cannot be
    called from server code). Paginates newest-first by 20 (the endpoint's
    max), fetching one page PAST hard_cap so an overflow is DETECTED, never
    silently truncated. Returns (rows_oldest_first, overflow: bool)."""
    out, offset, page_size = [], 0, 20
    overflow = False
    ceiling = hard_cap + page_size
    while True:
        resp = _sl_post("/master-inbox/inbox-replies", {
            "limit": page_size, "offset": offset, "sortBy": "REPLY_TIME_DESC",
            "filters": {"emailStatus": "Replied",
                        "replyTimeBetween": [since_iso, until_iso]},
        })
        data = resp.get("data") if isinstance(resp, dict) else None
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
        if len(out) > ceiling:
            overflow = True
            break
    # newest-first -> oldest-first: the watermark then only advances across
    # replies actually handled (gap-free), and an overflow drops the NEWEST
    # tail — which the webhook fast-path is most likely to have caught anyway.
    out.sort(key=lambda r: str(r.get("last_reply_time") or ""))
    return out, overflow


def run_reply_sync() -> dict:
    """Backstop pull: master inbox -> categoriser hook for every unseen reply.
    Never raises. ok=False (report FAILED) on a cap-hit, with `gap` = replies
    left unprocessed this run (a lower bound when `overflow`)."""
    summary = {"ok": True, "checked": 0, "posted": 0, "skipped_seen": 0,
               "skipped_archived": 0, "errors": 0, "gap": 0, "overflow": False,
               "watermark_before": None, "watermark_after": None, "first_run": False}
    if not _SB or not _sl_key():
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = "Supabase or Smartlead not configured"
        return summary
    try:
        wm, seeded = _reply_sync_watermark()
        now = _dt.datetime.now(_dt.timezone.utc)
        summary["first_run"] = seeded
        summary["watermark_before"] = wm.isoformat()
        since_iso = wm.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        until_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        rows, overflow = _fetch_master_inbox_window(since_iso, until_iso, REPLY_SYNC_CAP)
        summary["checked"] = len(rows)
        summary["overflow"] = overflow

        to_process = rows[:REPLY_SYNC_CAP]
        if overflow or len(rows) > REPLY_SYNC_CAP:
            summary["ok"] = False                       # cap-hit: FAILED, never silent
            summary["gap"] = max(0, len(rows) - REPLY_SYNC_CAP)

        advanced_to, frozen = wm, False
        for r in to_process:
            if not isinstance(r, dict):
                continue
            lead_id = r.get("email_lead_id")
            rtime = r.get("last_reply_time")
            cid = r.get("email_campaign_id")
            email = (r.get("lead_email") or "").strip()
            if not lead_id or not rtime or not cid or not email:
                continue
            mid = f"{lead_id}-{rtime}"          # == categoriser archive key (module 60)
            rt_dt = _parse_iso(rtime)
            handled = False
            if _reply_sync_seen(mid):
                summary["skipped_seen"] += 1
                handled = True
            elif _reply_in_archive(mid):
                _mark_reply_seen(mid)           # remember so we skip the archive check next run
                summary["skipped_archived"] += 1
                handled = True
            else:
                ok, data, _err = hydrate_lead(cid, email, None)
                text = clean_body(data.get("reply_email_body") or "") if ok else ""
                if text:
                    payload = {
                        "event_type": "EMAIL_REPLY",
                        "sl_lead_email": email,
                        "sl_email_lead_id": lead_id,
                        "campaign_id": cid,
                        "reply_message": {"text": text, "time": rtime},
                    }
                    try:
                        _HTTP("POST", CATEGORISER_HOOK, {}, payload)
                    except ValueError:
                        pass  # Make hook answers a non-JSON 2xx ("Accepted") = success
                    _mark_reply_seen(mid)
                    summary["posted"] += 1
                    handled = True
                else:
                    # No body yet (thread not indexed) — leave UNSEEN, do not
                    # advance past it; a later tick retries.
                    summary["errors"] += 1
            # Watermark only crosses a CONTIGUOUS run of handled replies, so a
            # gap (unhandled reply) freezes it there and nothing downstream is lost.
            if handled and not frozen:
                if rt_dt and rt_dt > advanced_to:
                    advanced_to = rt_dt
            elif not handled:
                frozen = True

        if _SB and (advanced_to > wm or seeded):
            _SB("PATCH", "reply_sync_state?id=eq.1",
                {"watermark": advanced_to.isoformat(), "updated_at": now.isoformat(),
                 "last_run": summary}, prefer="return=minimal")
        summary["watermark_after"] = advanced_to.isoformat()
        return summary
    except Exception as e:  # noqa: BLE001 — record, never crash the cron thread
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return summary


# ── positive-thread re-reply sweep ───────────────────────────────────────────
# run_reply_sync's watermark window CANNOT see a new reply landing on an old
# thread: Smartlead's inbox-replies replyTimeBetween filter (and its
# REPLY_TIME_DESC sort) index threads by their FIRST reply time, while each
# row's last_reply_time field reports the LATEST reply. Proven live
# 2026-07-16: zayncosmetics@gmail.com re-replied 2026-07-15T22:38:43Z on a
# thread first-replied 2026-07-01 — the row only surfaces in a July-1st
# window, so the 3-min backstop never saw the new reply and no 🚨 Slack
# fired (the EMAIL_REPLY webhook doesn't fire for these either — the lead
# was already Completed). This sweep is the guarantee net for POSITIVE
# leads (the replies a human must never miss): every ~15 min it pulls EVERY
# thread whose per-campaign lead category is positive
# (filters.leadCategories.categoryIdsIn — a bounded set, ~1.5k threads /
# ~75 pages) and feeds any unseen (email_lead_id + last_reply_time) to the
# SAME categoriser hook. The categoriser's routeB then posts the 🚨
# re-reply Slack AND archives the reply (module 61, key
# "{sl_email_lead_id}-{reply_message.time}"), so webhook-fed and sweep-fed
# re-replies dedupe exactly like first replies do.
# FIRST run SEEDS: every current mid is marked seen WITHOUT posting —
# otherwise ~1.5k historic threads would flood Slack in one tick.
POSITIVE_CATEGORY_IDS = [1, 2, 5, 78386, 83039, 83731, 86207, 125938]
RESWEEP_INTERVAL_MIN = 15      # effective cadence, self-throttled off the 3-min tick
RESWEEP_THROTTLE_MIN = 13      # >13 min since last sweep => due (aligns to 3-min grid)
RESWEEP_POST_CAP = 25          # tripwire: never fire more than this many alerts per sweep
RESWEEP_PAGE_CEILING = 200     # 4k threads; hitting it reports FAILED, never silent
_RESWEEP_STATE_ID = 2          # reply_sync_state row (id=1 is run_reply_sync's watermark)


def _resweep_last_run():
    """Timestamp of the last completed sweep, or None if never seeded (the
    id=2 state row is only written after a sweep completes)."""
    if not _SB:
        return None
    rows = _SB("GET", f"reply_sync_state?id=eq.{_RESWEEP_STATE_ID}&select=watermark")
    if isinstance(rows, list) and rows and rows[0].get("watermark"):
        return _parse_iso(rows[0]["watermark"])
    return None


def _fetch_positive_threads(page_ceiling: int):
    """Every master-inbox thread whose per-campaign lead category is positive.
    No time window — the category filter alone bounds the set, and each row's
    last_reply_time is always the thread's true latest reply. Returns
    (rows, overflow)."""
    out, offset, page_size = [], 0, 20
    overflow = False
    while True:
        resp = _sl_post("/master-inbox/inbox-replies", {
            "limit": page_size, "offset": offset, "sortBy": "REPLY_TIME_DESC",
            "filters": {"leadCategories": {"categoryIdsIn": POSITIVE_CATEGORY_IDS}},
        })
        data = resp.get("data") if isinstance(resp, dict) else None
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
        if offset >= page_ceiling * page_size:
            overflow = True
            break
    return out, overflow


def _reply_time_in_archive(campaign_id, email: str, rtime: str) -> bool:
    """True if ANY replies row records this exact reply instant for this
    lead+campaign. Keyed on (campaign, email, replied_at-as-timestamp) rather
    than smartlead_message_id because the mid's time half is format-fluid:
    webhook-fed routeB rows key "...+00:00" while master-inbox mids are
    "....000Z" (both exist live for ONE Gerry reply, 2026-07-15) — a string
    match on one format would re-fire alerts the webhook already sent.
    Postgres compares replied_at as a timestamp, so both formats hit."""
    if not _SB or not email or not rtime:
        return False
    rows = _SB("GET", f"replies?workspace=eq.{WORKSPACE}"
                      f"&smartlead_campaign_id=eq.{campaign_id}"
                      f"&email=ilike.{quote(email, safe='')}"
                      f"&replied_at=eq.{quote(rtime, safe='')}&select=id&limit=1")
    return isinstance(rows, list) and bool(rows)


def _resweep_seen_set(mids):
    """Bulk membership check against reply_sync_seen — chunked in.() GETs (100
    mids/chunk) instead of one GET per mid (a full sweep is ~1.5k mids)."""
    seen = set()
    if not _SB:
        return seen
    mids = [m for m in mids if m]
    for i in range(0, len(mids), 100):
        chunk = mids[i:i + 100]
        inlist = ",".join(quote(m, safe="") for m in chunk)
        rows = _SB("GET", f"reply_sync_seen?message_id=in.({inlist})&select=message_id")
        if isinstance(rows, list):
            seen.update(r.get("message_id") for r in rows if isinstance(r, dict))
    return seen


def _resweep_mark_seen_bulk(mids):
    """Bulk-insert seen mids (idempotent upsert), chunked to keep bodies small."""
    if not _SB:
        return
    mids = [m for m in mids if m]
    for i in range(0, len(mids), 100):
        _SB("POST", "reply_sync_seen",
            [{"message_id": m} for m in mids[i:i + 100]],
            prefer="resolution=merge-duplicates")


def run_positive_resweep(force: bool = False) -> dict:
    """Guarantee net: every reply on a positively-categorised thread reaches
    the categoriser hook (=> routeB 🚨 Slack + archive), even when both the
    EMAIL_REPLY webhook and the watermark backstop missed it. Never raises.
    force=True skips the cadence throttle (tests / manual runs)."""
    summary = {"ok": True, "skipped": False, "seeded": False, "threads": 0,
               "unseen": 0, "posted": 0, "marked_archived": 0, "would_post": 0,
               "would_post_sample": [], "errors": 0, "capped": False,
               "overflow": False}
    if not _SB or not _sl_key():
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = "Supabase or Smartlead not configured"
        return summary
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        last = _resweep_last_run()
        seed_mode = last is None
        if not force and last is not None and \
                (now - last) < _dt.timedelta(minutes=RESWEEP_THROTTLE_MIN):
            summary["skipped"] = True
            return summary
        summary["seeded"] = seed_mode

        rows, overflow = _fetch_positive_threads(RESWEEP_PAGE_CEILING)
        summary["threads"] = len(rows)
        summary["overflow"] = overflow
        if overflow:
            summary["ok"] = False       # partial coverage must be visible, never silent

        mids_by_row = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            lead_id = r.get("email_lead_id")
            rtime = r.get("last_reply_time")
            cid = r.get("email_campaign_id")
            email = (r.get("lead_email") or "").strip()
            if not lead_id or not rtime or not cid or not email:
                continue
            mids_by_row[f"{lead_id}-{rtime}"] = r

        seen = _resweep_seen_set(list(mids_by_row))
        unseen = {m: r for m, r in mids_by_row.items() if m not in seen}
        summary["unseen"] = len(unseen)

        if seed_mode:
            # Seed: never post. Record what WOULD have fired (unseen + not in
            # archive) so the miss this sweep exists to catch is provably
            # visible in the seed run's log, then mark everything seen.
            for mid, r in unseen.items():
                if not _reply_time_in_archive(r.get("email_campaign_id"),
                                              (r.get("lead_email") or "").strip(),
                                              r.get("last_reply_time")):
                    summary["would_post"] += 1
                    if len(summary["would_post_sample"]) < 10:
                        summary["would_post_sample"].append(mid)
            _resweep_mark_seen_bulk(list(unseen))
        else:
            to_mark = []
            for mid, r in unseen.items():
                if _reply_time_in_archive(r.get("email_campaign_id"),
                                          (r.get("lead_email") or "").strip(),
                                          r.get("last_reply_time")):
                    # webhook fast-path already alerted + archived this one
                    to_mark.append(mid)
                    summary["marked_archived"] += 1
                    continue
                if summary["posted"] >= RESWEEP_POST_CAP:
                    summary["capped"] = True
                    summary["ok"] = False   # leftovers retry next sweep, loudly
                    continue
                ok, data, _err = hydrate_lead(r.get("email_campaign_id"),
                                              (r.get("lead_email") or "").strip(), None)
                text = clean_body(data.get("reply_email_body") or "") if ok else ""
                if not text:
                    # thread not hydrated yet — leave unseen, retry next sweep
                    summary["errors"] += 1
                    continue
                payload = {
                    "event_type": "EMAIL_REPLY",
                    "sl_lead_email": (r.get("lead_email") or "").strip(),
                    "sl_email_lead_id": r.get("email_lead_id"),
                    "campaign_id": r.get("email_campaign_id"),
                    "reply_message": {"text": text, "time": r.get("last_reply_time")},
                }
                try:
                    _HTTP("POST", CATEGORISER_HOOK, {}, payload)
                except ValueError:
                    pass  # Make answers a non-JSON 2xx ("Accepted") = success
                to_mark.append(mid)
                summary["posted"] += 1
            _resweep_mark_seen_bulk(to_mark)

        _SB("POST", "reply_sync_state",
            {"id": _RESWEEP_STATE_ID, "watermark": now.isoformat(),
             "updated_at": now.isoformat(), "last_run": summary},
            prefer="resolution=merge-duplicates")
        return summary
    except Exception as e:  # noqa: BLE001 — record, never crash the cron thread
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return summary


def run_poll() -> dict:
    """Sweeps recent core-four `replies` rows across EVERY campaign in the
    workspace (owner ruling 2026-07-14: a positive must reach the queue even
    on a campaign with no agent assigned yet), skips anything already
    queued, and runs process_reply (agented) or the agentless intake
    (unassigned) on up to 15 per tick. Never raises."""
    summary = {"checked": 0, "queued": 0, "auto_sent": 0, "needs_review": 0, "no_action": 0,
               "errors": 0, "agentless": 0}
    try:
        if not _SB:
            return summary
        agents = _load_agents()
        settings = _load_settings()
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat()
        # quote(): `since` ends in "+00:00" and sb() sends the query string
        # raw, so an unencoded "+" reaches PostgREST as a space - the timestamp
        # then fails its timestamptz cast, the GET 400s, _SB returns None, and
        # every tick silently reported checked=0 while eligible replies piled up
        # (same "+"-as-space bug class d38a301 fixed for _existing_row). The
        # category filter (CORE_FOUR_CATEGORY_FILTER) replaces the old
        # campaign_ids=in.(...) filter - agentless campaigns have no agent
        # doc to source campaign ids from, so the workspace itself is the
        # only scope left; the category gate keeps the sweep to positives.
        replies = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&category={CORE_FOUR_CATEGORY_FILTER}"
                             f"&replied_at=gte.{quote(since, safe='')}&order=replied_at.asc&limit=200"
                             f"&select=id,smartlead_campaign_id,email,replied_at,category,"
                             f"reply_subject,reply_body,smartlead_message_id")
        if not isinstance(replies, list):
            # A failed replies GET must never masquerade as a clean "checked 0"
            # sweep - record an error so the poll log shows the trouble instead
            # of a false all-zero success.
            summary["errors"] += 1
            print(f"[setter] run_poll: replies GET returned {type(replies).__name__}, not a "
                  f"list - PostgREST query failed", file=sys.stderr)
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
            # Belt-and-braces (the server-side category filter above already
            # scopes the query to CORE_FOUR): guard again client-side in case
            # the filter is ever loosened. Uncategorised (None/empty) falls
            # out here too - the 48h poll window means it gets retried on a
            # later tick once Make fills replies.category in.
            if r.get("category") not in CORE_FOUR:
                continue
            reply = {
                "workspace": WORKSPACE, "campaign_id": cid, "email": email,
                "first_name": r.get("first_name"), "last_name": r.get("last_name"),
                "company_domain": r.get("company_domain"), "subject": r.get("reply_subject") or r.get("subject"),
                "body": r.get("reply_body") or r.get("body") or "",
                "replied_at": r.get("replied_at"), "message_id": mid,
                "category": r.get("category"), "is_test": False,
            }
            agent = _agent_for_campaign(cid, require_enabled=True, agents=agents)
            if agent:
                # Only replies received AFTER this campaign was assigned to
                # the agent. Without this, first activation would sweep up
                # to 48h of already-humanly-handled backlog into the queue.
                # A subsequence reply carries the subsequence's own id, which
                # is never a key in campaign_assigned_at (only the parent gets
                # assigned) - fall back to the parent's stamp so inherited
                # replies get the same backlog gate as the parent's own,
                # instead of an un-gated free pass.
                stamps = agent.get("campaign_assigned_at") or {}
                assigned_at = stamps.get(str(cid))
                if not assigned_at:
                    _par = _parent_campaign_id(cid)
                    assigned_at = stamps.get(str(_par)) if _par else None
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
            else:
                # Agentless intake (owner ruling 2026-07-14): no campaign_assigned_at
                # concept without an agent doc - the reply just goes straight in.
                if _existing_row(WORKSPACE, cid, email, mid):
                    continue
                processed += 1
                summary["checked"] += 1
                try:
                    row = _intake_agentless(reply)
                    summary["agentless"] += 1
                    if (row or {}).get("status") == "needs_review":
                        summary["needs_review"] += 1
                except Exception as e:  # noqa: BLE001 - one bad reply must never stop the sweep
                    summary["errors"] += 1
                    print(f"[setter] poll agentless-intake error for {email}/{cid}: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - run_poll itself must never raise
        summary["errors"] += 1
        print(f"[setter] run_poll crashed: {e}", file=sys.stderr)
    # New rows changed the queue - drop every read cache and start a rewarm
    # so the post-poll reload (the UI's delayed loadQueue) reads fresh counts
    # and rows (perf pass 2026-07-16). A no-change sweep keeps caches warm.
    if summary.get("queued") or summary.get("needs_review") or summary.get("auto_sent") \
            or summary.get("no_action"):
        _bust_read_caches()
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
        rm = payload.get("reply_message") if isinstance(payload.get("reply_message"), dict) else {}
        body = rm.get("text") or _TAG_RE.sub(" ", str(rm.get("html") or "")) or payload.get("reply_body") or ""
        # Key on the email Message-ID (what the poll's `replies` rows also
        # carry) so webhook and poll claim the SAME row. Without a message id
        # we leave the reply to the poll rather than risk a duplicate claim.
        mid = str(rm.get("message_id") or payload.get("message_id") or "")
        if not mid:
            return {"ignored": "no message id in payload - the poll sweep will pick this reply up"}
        # Positive-only intake gate (ruling 2026-07-14): payload["lead_category"]
        # is Smartlead's own label, NOT the Make categoriser's verdict - the
        # verified source is replies.category, so look that row up by the same
        # key the poll matches on (workspace/campaign/message id) instead of
        # trusting the webhook's own label. A fresh reply's row is often still
        # uncategorised at webhook time (~15min Make lag); a lookup exception
        # is treated exactly like "not found yet" so a transient Supabase
        # hiccup never blocks it - either way the poll sweep retries later.
        cat = None
        try:
            if _SB:
                rows = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&smartlead_campaign_id=eq.{cid}"
                                  f"&smartlead_message_id=eq.{mid}&select=category&limit=1")
                if isinstance(rows, list) and rows:
                    cat = (rows[0] or {}).get("category")
        except Exception:  # noqa: BLE001 - a lookup hiccup is left for the poll, not a crash
            cat = None
        if not cat:
            return {"ignored": "awaiting categorisation - the poll sweep will pick this reply up"}
        if cat not in CORE_FOUR:
            return {"ignored": f"category '{cat}' is not a positive category"}
        reply = {
            "workspace": WORKSPACE, "campaign_id": cid, "email": email,
            "first_name": lead.get("first_name") or payload.get("to_first_name"),
            "last_name": lead.get("last_name") or payload.get("to_last_name"),
            "subject": payload.get("subject") or rm.get("subject") or "",
            "body": body,
            "replied_at": rm.get("time") or payload.get("event_timestamp") or None,
            "message_id": mid, "category": cat, "is_test": False,
        }
        agent = _agent_for_campaign(cid)
        if not agent:
            # Agentless intake (owner ruling 2026-07-14): "we shouldn't need
            # to assign an agent to a campaign to be able to receive the
            # positives - it should come in regardless." Same category gate
            # as the agented path above already ran; this just skips the
            # agent brain (classify/draft/decide/hydrate) and queues the
            # reply straight into manual review.
            row = _intake_agentless(reply)
            return {"processed": True, "status": (row or {}).get("status"), "agentless": True,
                    "id": (row or {}).get("id")}
        row = process_reply(reply, agent, _load_settings())
        return {"processed": True, "status": (row or {}).get("status"), "id": (row or {}).get("id")}
    except Exception as e:  # noqa: BLE001 - a webhook must never take the server down
        print(f"[setter] handle_inbound crashed: {e}", file=sys.stderr)
        return {"error": str(e)[:200]}


def ensure_webhooks(agent: dict) -> list:
    """No-op by design. Setting up or editing an agent must NOT touch a
    campaign's Smartlead webhooks.

    Reply intake is handled entirely by the poll (`/api/setter/poll`, the
    5-minute cron + the "check now" run when the tool is opened), which reads
    each assigned campaign's replies and filters internally by `campaign_ids`
    + `campaign_assigned_at`. It never needs a per-campaign webhook.

    History: we used to register a per-campaign "Navreo Setter" EMAIL_REPLY
    webhook here. Smartlead routes a campaign's replies to its own campaign
    webhook and SUPPRESSES the workspace-level webhook, so this silently
    diverted every Setter campaign away from the reply-categoriser and killed
    #interested-replies Slack alerts across ~73 campaigns (found & reverted
    2026-07-15). The Setter shares the existing intake (poll); it does not add
    webhooks of its own.

    Kept as a no-op (rather than deleted) so the save-agent flow and the UI's
    per-campaign result contract are unchanged; it issues zero Smartlead calls.
    """
    agent = agent or {}
    return [{"campaign_id": c, "ok": True, "skipped": "poll-only"}
            for c in (agent.get("campaign_ids") or [])]


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
        # Snapshot which campaign ids this agent already had BEFORE the save,
        # so we can tell genuinely-new attachments apart from ones that were
        # already there (self-heal below must only fire for the former). A
        # brand-new agent (no id yet) has no prior campaigns.
        prev_cids = {str(c) for c in ((_load_agent(doc.get("id")) or {}).get("campaign_ids") or [])} \
            if doc.get("id") else set()
        saved = _save_agent(doc)
        webhooks = ensure_webhooks(saved)
        # Self-heal (owner ruling 2026-07-15): every campaign id newly
        # attached in this save gets its 7-day backlog swept in the
        # background (see _self_heal_campaigns) so recent positive replies
        # on it land as drafts instead of being silently missed. Runs in a
        # daemon thread so the save response returns immediately.
        new_cids = [c for c in map(str, saved.get("campaign_ids") or []) if c not in prev_cids]
        if new_cids:
            threading.Thread(target=_self_heal_campaigns, args=(saved, new_cids), daemon=True).start()
        return 200, {"doc": saved, "webhooks": webhooks, "self_heal_started": len(new_cids)}
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


def route_agents_correction(payload):
    """Persistent learning layer: one correction the owner (or, since Review
    mode, a share-link trainer teaching from a rechecked case) gives while
    reviewing this agent's calls, outside the grading page's own per-case
    feedback_log. scope="remember" (owner ruling 2026-07-14) merges the
    correction straight into the agent's `instructions` text via
    merge_correction_into_instructions - the single living manual - instead
    of growing agent['memory']; scope="one_off" (the default) is audit-only
    and never fed back into the model (agent['feedback_log']).

    Share-scope enforcement (added for Review mode's "Teach it more", same
    _resolve_share_scope helper the training routes already use) is a no-op
    for every existing owner-session caller (setter.html's Teach-the-agent
    modal never sends a share/___public field) - it only grants a valid
    share token the same "merge into THIS agent's instructions" ability a
    training-page "Remember going forward" note already has via
    route_training_answer -> _kick_off_training_retrain, not a new
    privilege."""
    try:
        payload = payload or {}
        agent_id = payload.get("agent_id")
        share_token = payload.get("share") or ""
        public = bool(payload.get("___public"))
        agent_id, err = _resolve_share_scope(agent_id, share_token, public)
        if err:
            return err
        text = str(payload.get("text") or "").strip()
        scope = payload.get("scope") or "one_off"
        source = payload.get("source") or "manual"
        if not text:
            return 400, {"error": "text is required"}
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        if scope == "remember":
            _ok, _new_instructions, how = merge_correction_into_instructions(agent, text, source)
            saved = _load_agent(agent_id) or agent
            return 200, {
                "ok": True, "agent_id": agent_id, "scope": scope, "how": how,
                "memory_count": len(saved.get("memory") or []),
                "feedback_log_count": len(saved.get("feedback_log") or []),
                "instruction_edits_count": len(saved.get("instruction_edits") or []),
            }
        saved = _append_agent_feedback_log(agent_id, text, source)
        return 200, {
            "ok": True, "agent_id": agent_id, "scope": scope,
            "memory_count": len(saved.get("memory") or []),
            "feedback_log_count": len(saved.get("feedback_log") or []),
        }
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_agents_memory_delete(payload):
    """Removes one remembered correction from an agent's brain, matched by
    its timestamp (and text, defensively). The training page's memory viewer
    uses this so a bad lesson can always be taken back - remembered
    corrections are never write-only.

    Owner-only, always - this route is never added to any public route list,
    but it also never trusts a share token even if one is somehow forwarded
    (e.g. a public caller replaying a captured request): a share only ever
    grants training read/answer/teach-a-correction access to one agent (see
    route_training_answer and route_agents_correction), never a raw memory
    edit like this route performs."""
    try:
        payload = payload or {}
        if payload.get("share") or payload.get("___public"):
            return 403, {"error": "Memory cannot be edited from a training link."}
        agent_id = payload.get("agent_id")
        at = str(payload.get("at") or "")
        text = str(payload.get("text") or "")
        if not agent_id or not at:
            return 400, {"error": "agent_id and at are required"}
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        memory = list(agent.get("memory") or [])
        kept = [m for m in memory
                if not (isinstance(m, dict) and str(m.get("at") or "") == at
                        and (not text or str(m.get("text") or "") == text))]
        if len(kept) == len(memory):
            return 404, {"error": "That remembered note wasn't found (maybe already removed)."}
        saved = _save_agent({"id": agent_id, "memory": kept})
        return 200, {"ok": True, "agent_id": agent_id, "memory_count": len(saved.get("memory") or []),
                     "memory": saved.get("memory") or []}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_agents_duplicate(payload):
    """Brain duplication: deep-copies an agent's whole doc (instructions,
    memory, voice examples, everything) under a brand-new id, so the clone
    can be tuned and tested without touching the live original. Ships
    disabled from any campaign on purpose (draft_only, no campaign_ids) - a
    duplicate must never start auto-sending on its own."""
    try:
        payload = payload or {}
        agent_id = payload.get("agent_id")
        if not agent_id:
            return 400, {"error": "agent_id is required"}
        original = _load_agent(agent_id)
        if not original:
            return 404, {"error": "Agent not found."}
        clone = copy.deepcopy(original)
        new_id = f"agent-{uuid.uuid4().hex[:8]}"
        # Vanishingly unlikely, but never risk landing on (and merging onto)
        # an id that already exists - _save_agent's merge-on-existing-id
        # semantics exist precisely to protect a real agent from being
        # overwritten by an unrelated partial save.
        while _load_agent(new_id):
            new_id = f"agent-{uuid.uuid4().hex[:8]}"
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        clone.update({
            "id": new_id,
            "name": f"{str(original.get('name') or '').strip()} copy".strip(),
            "mode": "draft_only",
            "campaign_ids": [],
            "campaign_assigned_at": {},
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        })
        saved = _save_agent(clone)
        return 200, {"doc": saved}
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
        # horizon_working_days is no longer a settings-drawer field (the slot
        # rule is fixed - see HORIZON_WORKING_DAYS); work_start/work_end
        # remain the only schedule settings.
        for k in ("work_start", "work_end"):
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


def _sl_find_subsequences(parent_campaign_id):
    """Live Smartlead lookup of `parent_campaign_id`'s subsequences. A
    subsequence IS a campaign whose own `parent_campaign_id` field points back
    at the parent (docs: https://api.smartlead.ai/api-reference/campaigns/get-all
    lists `parent_campaign_id` on every campaign object). Read-only GET
    /campaigns/ - never a write. Returns a list of {"id","name","status"}."""
    if not parent_campaign_id:
        return []
    try:
        resp = _sl_get("/campaigns/")
        rows = resp if isinstance(resp, list) else []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("parent_campaign_id") and str(r.get("parent_campaign_id")) == str(parent_campaign_id):
                out.append({"id": r.get("id"), "name": r.get("name"), "status": r.get("status")})
        return out
    except Exception:  # noqa: BLE001
        return []


def _resolve_subsequence_id(campaign_id, sub_sequence_id_override):
    """Picks the subsequence to push a lead into. An explicit override always
    wins (the caller already knows which one, e.g. a picker in the UI for
    campaigns with several). Otherwise looks up campaign_id's subsequences via
    _sl_find_subsequences(): exactly one -> use it; none -> honest 502; more
    than one -> 400 asking the caller to disambiguate (with the list attached
    so a picker can be built from it).
    Returns (sub_sequence_id, error_response) where error_response is None on
    success or a ready-to-return (status, body) tuple otherwise."""
    if sub_sequence_id_override:
        return sub_sequence_id_override, None
    subs = _sl_find_subsequences(campaign_id)
    if len(subs) == 1:
        return subs[0]["id"], None
    if len(subs) > 1:
        return None, (400, {"error": "This campaign has multiple subsequences - pick one.", "subsequences": subs})
    return None, (502, {"error": "No subsequence is configured for this campaign in Smartlead."})


def route_campaigns_get(_params):
    try:
        if not _SB:
            return 200, []
        rows = _SB("GET", f"campaigns?workspace=eq.{WORKSPACE}&select=smartlead_campaign_id,name,status"
                          f"&status=in.(ACTIVE,PAUSED,STOPPED)&order=created_at_smartlead.desc")
        out = []
        seen = set()
        if isinstance(rows, list):
            for r in rows:
                name = (r.get("name") or "").strip()
                if not name or _SUBSEQUENCE_NAME.match(name):
                    continue
                cid = r.get("smartlead_campaign_id")
                out.append({"id": cid, "name": name, "status": r.get("status")})
                seen.add(str(cid))
        # Union in queue-only campaigns (owner fix 2026-07-15, campaign
        # 3477411): a campaign can have a queued reply in setter_queue while
        # being invisible above, either because its `campaigns` mirror row
        # never landed/is stale, or because its name trips _SUBSEQUENCE_NAME
        # (3477411 is literally named "Meeting Request", the exact pattern
        # the mirror query excludes to hide Smartlead's ~300 auto-generated
        # subsequence campaigns). A queued reply is proof-of-life that this
        # is a real reply-bearing campaign the picker must show, so queue-
        # derived ids deliberately BYPASS both the regex exclusion and the
        # empty-name exclusion above. Mirror-only rows are untouched - this
        # only ADDS rows the original query would have dropped or missed.
        # Best-effort: any failure here degrades to the plain mirror-only
        # list rather than 500ing the whole endpoint.
        try:
            qrows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&select=smartlead_campaign_id&limit=2000")
            qids = set()
            if isinstance(qrows, list):
                for qr in qrows:
                    cid = (qr or {}).get("smartlead_campaign_id")
                    if cid is not None:
                        qids.add(str(cid))
            missing = sorted(qids - seen)
            if missing:
                csv = ",".join(missing)
                lookup = _SB("GET", f"campaigns?workspace=eq.{WORKSPACE}&smartlead_campaign_id=in.({csv})"
                                    f"&select=smartlead_campaign_id,name,status")
                by_id = {}
                if isinstance(lookup, list):
                    for lr in lookup:
                        by_id[str((lr or {}).get("smartlead_campaign_id"))] = lr
                for cid in missing:
                    lr = by_id.get(cid)
                    name = ((lr or {}).get("name") or "").strip() or f"Campaign {cid}"
                    status = (lr or {}).get("status") if lr else None
                    out.append({"id": cid, "name": name, "status": status})
                    seen.add(cid)
        except Exception:  # noqa: BLE001 - union is additive; a failure here must not break the endpoint
            pass
        return 200, out
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _pill_count(filt: str) -> int:
    """Real-lead row count for a queue filter pill. Prefers the header-only
    counter (sb_count); falls back to len(select=id) when it isn't wired in."""
    base = f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&is_test=eq.false&{filt}"
    if _SB_COUNT:
        n = _SB_COUNT(f"{base}&select=id")
        if isinstance(n, int):
            return n
    rows = _SB("GET", f"{base}&select=id") if _SB else None
    return len(rows) if isinstance(rows, list) else 0


# Short-TTL cache for the KPI block. The queue endpoint recomputed ~10
# SEQUENTIAL Supabase queries on EVERY GET, which alone made one
# /api/setter/queue call take ~3.7s live (baseline 2026-07-15). The counts
# are chip/headline totals, not per-lead data, so a few seconds of staleness
# is invisible - and the reply-poll refreshes them anyway. Cache the whole
# block for _KPI_TTL seconds and, on a miss, fetch every independent query
# CONCURRENTLY (they share no data) so a cold compute is ~1 round-trip, not 10.
_KPI_TTL = 15.0
_KPI_CACHE = {"at": 0.0, "val": None}
_KPI_LOCK = threading.Lock()      # guards cache writes
_KPI_COMPUTE = threading.Lock()   # single-flight: one KPI compute at a time


def _kick_kpi_refresh():
    """Refresh the KPI cache in the background. Single-flight: if a compute is
    already running, do nothing - concurrent queue GETs stacking parallel
    ~10-query computes is exactly the storm that measured 12.6s live
    (2026-07-16), worse than the serial baseline it replaced."""
    def run():
        if not _KPI_COMPUTE.acquire(blocking=False):
            return
        try:
            _compute_kpis_sync()
        finally:
            _KPI_COMPUTE.release()
    threading.Thread(target=run, daemon=True).start()


def _count_rows(filt: str) -> int:
    """len() of a select=id query, header-counter first when wired in."""
    base = f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&{filt}"
    if _SB_COUNT:
        n = _SB_COUNT(f"{base}&select=id")
        if isinstance(n, int):
            return n
    rows = _SB("GET", f"{base}&select=id") if _SB else None
    return len(rows) if isinstance(rows, list) else 0


def _compute_kpis(force: bool = False) -> dict:
    """Serve-from-cache wrapper around _compute_kpis_sync. Fresh -> cached;
    stale -> cached value NOW plus one background refresh (stale-while-
    revalidate, chip counts tolerate seconds of lag); empty (boot or a hard
    bust after a mutation) -> compute synchronously, single-flight so
    concurrent GETs join one compute instead of stacking storms."""
    cached = _KPI_CACHE.get("val")
    if not force and cached is not None:
        if (_time.time() - _KPI_CACHE.get("at", 0.0)) < _KPI_TTL:
            return cached
        _kick_kpi_refresh()
        return cached
    with _KPI_COMPUTE:
        # A compute may have landed while we waited on the lock - reuse it.
        cached = _KPI_CACHE.get("val")
        if not force and cached is not None and (_time.time() - _KPI_CACHE.get("at", 0.0)) < _KPI_TTL:
            return cached
        return _compute_kpis_sync()


def _compute_kpis_sync() -> dict:
    now = _time.time()
    kpis = {"needs_review": 0, "auto_sent_today": 0, "sent_today": 0,
           "avg_response_mins_7d": None, "no_action_today": 0, "counts": {}}
    if not _SB:
        return kpis
    try:
        today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)).isoformat()

        # Each entry is an independent PostgREST read -> run them all at once.
        # Per-pill totals for the filter chips ("needs_review" = they replied
        # last and it awaits our decision; "sent"/"auto_sent" = we replied
        # last; "all" = every real row). is_test=false everywhere except the
        # pill counts, which keep _pill_count's exact (test-excluded) filter.
        def _pill(filt):  # mirrors _pill_count's is_test=false pill semantics
            return _count_rows(f"is_test=eq.false&{filt}")

        def _avg_response():
            rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=in.(auto_sent,sent)&is_test=eq.false"
                              f"&sent_at=gte.{quote(since, safe='')}&select=replied_at,sent_at")
            mins = []
            if isinstance(rows, list):
                for r in rows:
                    try:
                        ra, sa = r.get("replied_at"), r.get("sent_at")
                        if ra and sa:
                            mins.append((_parse_iso(sa) - _parse_iso(ra)).total_seconds() / 60)
                    except Exception:  # noqa: BLE001
                        continue
            return round(sum(mins) / len(mins), 1) if mins else None

        def _reclass():
            # Read-time direction tally: how many needs_review rows really still
            # await us (newest msg is the lead's) vs have been answered and
            # belong under sent / auto_sent. Mirrors _queue_direction exactly.
            # "dir" maps row id -> (inbound, pill) so the thread-collapsed
            # count below can look up JUST the representative rows; the flat
            # stay/sent/auto tallies stay as the no-collapse fallback.
            rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=eq.needs_review"
                              f"&is_test=eq.false&select=id,thread,sent_at,decision,status")
            stay = m_sent = m_auto = 0
            dirs = {}
            if isinstance(rows, list):
                for r in rows:
                    r = r if isinstance(r, dict) else {}
                    inbound, pill = _queue_direction(r)
                    dirs[r.get("id")] = (inbound, pill)
                    if inbound:
                        stay += 1
                    elif pill == "auto_sent":
                        m_auto += 1
                    else:
                        m_sent += 1
            return {"stay": stay, "sent": m_sent, "auto": m_auto, "dir": dirs}

        def _light():
            # The thread-collapse source: every real row's key fields (no
            # thread blobs - a few KB). Same is_test=false semantics as the
            # pill counts.
            rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&is_test=eq.false&limit=2000"
                              "&select=id,status,smartlead_campaign_id,lead_email,replied_at,created_at")
            return rows if isinstance(rows, list) else None

        tasks = {
            "light": _light,
            "c_needs_review": lambda: _pill("status=eq.needs_review"),
            "c_sent": lambda: _pill("status=eq.sent"),
            "c_auto_sent": lambda: _pill("status=eq.auto_sent"),
            "c_dismissed": lambda: _pill("status=eq.dismissed"),
            "c_all": lambda: _pill("id=not.is.null"),
            "reclass": _reclass,
            "needs_review": lambda: _count_rows("is_test=eq.false&status=eq.needs_review"),
            "auto_sent_today": lambda: _count_rows(f"is_test=eq.false&status=eq.auto_sent&created_at=gte.{today}"),
            "sent_today": lambda: _count_rows(f"is_test=eq.false&status=eq.sent&created_at=gte.{today}"),
            "no_action_today": lambda: _count_rows(f"is_test=eq.false&status=eq.no_action&created_at=gte.{today}"),
            "avg_response_mins_7d": _avg_response,
        }
        results = {}
        # 5 workers, not len(tasks): each worker opens its own TLS connection
        # to Supabase (urllib has no keep-alive) and ~11 simultaneous
        # handshakes visibly choked the small Render instance.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(tasks))) as pool:
            fut_key = {pool.submit(fn): k for k, fn in tasks.items()}
            for fut in concurrent.futures.as_completed(fut_key):
                k = fut_key[fut]
                try:
                    results[k] = fut.result()
                except Exception:  # noqa: BLE001 - one bad query must not sink the block
                    results[k] = None
        # Fold order matches the read path: thread-collapse FIRST (one
        # representative row per conversation, from the light fetch), THEN
        # the who-spoke-last direction on each surviving needs_review row.
        # Every pill counts distinct threads and each thread lands in exactly
        # one bucket. If the light fetch failed, fall back to the pre-collapse
        # tallies; if the reclass read also failed, fall back to the raw
        # status counts (never crash the KPI block).
        rc = results.get("reclass") or {}
        _stay = rc.get("stay")
        _m_sent = rc.get("sent") or 0
        _m_auto = rc.get("auto") or 0
        _c_nr = results.get("c_needs_review") or 0
        _c_sent = results.get("c_sent") or 0
        _c_auto = results.get("c_auto_sent") or 0
        light = results.get("light")
        if isinstance(light, list) and light:
            reps = _collapse_threads(light)
            dirs = rc.get("dir") or {}
            n_nr = n_sent = n_auto = n_dis = 0
            for r in reps:
                st = r.get("status")
                if st == "needs_review":
                    inbound, pill = dirs.get(r.get("id"), (True, None))
                    if inbound:
                        n_nr += 1
                    elif pill == "auto_sent":
                        n_auto += 1
                    else:
                        n_sent += 1
                elif st == "sent":
                    n_sent += 1
                elif st == "auto_sent":
                    n_auto += 1
                elif st == "dismissed":
                    n_dis += 1
            kpis["counts"] = {
                "needs_review": n_nr,
                "sent": n_sent,
                "auto_sent": n_auto,
                "dismissed": n_dis,
                "all": len(reps),
            }
            kpis["needs_review"] = n_nr
        else:
            kpis["counts"] = {
                "needs_review": _stay if _stay is not None else _c_nr,
                "sent": _c_sent + _m_sent,
                "auto_sent": _c_auto + _m_auto,
                "dismissed": results.get("c_dismissed") or 0,
                "all": results.get("c_all") or 0,
            }
            kpis["needs_review"] = _stay if _stay is not None else (results.get("needs_review") or 0)
        kpis["auto_sent_today"] = results.get("auto_sent_today") or 0
        kpis["sent_today"] = results.get("sent_today") or 0
        kpis["no_action_today"] = results.get("no_action_today") or 0
        kpis["avg_response_mins_7d"] = results.get("avg_response_mins_7d")
    except Exception:  # noqa: BLE001
        pass
    with _KPI_LOCK:
        _KPI_CACHE["val"] = kpis
        _KPI_CACHE["at"] = now
    return kpis


# decide()'s exact master-switch hold reason — the read-time ground for
# "this WOULD have auto-sent". Keep in sync with decide().
_MASTER_SWITCH_REASON = "Held for review: every check passed, but the autopilot master switch is off."


def _annotate_queue_row(row: dict) -> dict:
    """READ-TIME annotations for the UI, derived from columns that already
    exist. Returned in GET payloads only — NEVER written back (a setter_queue
    PATCH carrying a key without a real column dies silently, see
    reference_setter_queue_schema_freeze_gotcha)."""
    out = dict(row)
    reason = str(row.get("decision_reason") or "")
    held_by_switch = reason == _MASTER_SWITCH_REASON
    out["held_only_by_master_switch"] = held_by_switch
    out["would_auto_send"] = (row.get("status") == "auto_sent"
                              or row.get("decision") == "auto_send"
                              or held_by_switch)
    slots = row.get("slots") or []
    no_slots = None
    if not slots and row.get("draft_body"):
        r = reason.lower()
        if "timezone" in r:
            no_slots = ("The lead's timezone couldn't be pinned down, so no fixed "
                        "call times were proposed — the draft asks for their availability instead.")
        elif "calendly" in r or "calendar" in r:
            no_slots = reason.replace("Held for review: ", "").strip().capitalize()
        elif str(row.get("error") or "").strip():
            no_slots = f"Call-time lookup hit an error: {str(row.get('error'))[:160]}"
        else:
            no_slots = ("No bookable Calendly slots were available when this was "
                        "processed, so the draft falls back to an availability ask / booking link.")
    out["no_slots_reason"] = no_slots
    return out


def _queue_direction(row: dict):
    """READ-TIME only, never written back. Answers "who spoke last in this
    thread" from the stored `thread` jsonb so the queue pills reflect the real
    conversation state, not just the static `status` column.

    Returns (last_msg_inbound, effective_pill):
      - last_msg_inbound: is the NEWEST thread message a REPLY from the lead?
        (True = the ball is in our court -> belongs in Needs review.)
      - effective_pill: for a row we've already answered (newest message is
        ours), which pill it really belongs in -- "auto_sent" when the setter
        agent sent it (sent_at stamped + decision=auto_send), else "sent"
        (a human replied, typically direct in Smartlead). None when there's no
        evidence to reclassify (empty / unparseable thread) -> keep stored bucket.
    """
    thread = row.get("thread")
    if not isinstance(thread, list) or not thread:
        return True, None
    try:
        # ISO8601 times sort lexicographically (same approach as thread
        # hydration's norm.sort). Missing time -> "" sorts first, so it never
        # wins "newest".
        last = max((m for m in thread if isinstance(m, dict)),
                   key=lambda m: m.get("time") or "", default=None)
    except Exception:  # noqa: BLE001 - a malformed thread must not break the queue
        return True, None
    if not last or str(last.get("type") or "").upper() == "REPLY":
        return True, None
    # Newest message is ours: we replied last.
    is_agent = bool(row.get("sent_at")) and row.get("decision") == "auto_send"
    return False, ("auto_sent" if is_agent else "sent")


def _reclassify_queue(rows: list, requested: str) -> list:
    """Apply read-time direction to a needs_review / sent / auto_sent pill.
    - needs_review: drop rows we've already answered (newest msg is ours).
    - sent / auto_sent: add in the answered rows whose effective pill matches.
    Ordering (created_at desc) is preserved on the merged set. Pure read path."""
    if requested not in ("needs_review", "sent", "auto_sent"):
        return rows
    kept = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("status") == "needs_review":
            inbound, pill = _queue_direction(r)
            if requested == "needs_review":
                if inbound:
                    kept.append(r)
            else:  # sent / auto_sent: only answered rows routed to this pill
                if not inbound and pill == requested:
                    kept.append(r)
        else:
            # already-stored rows for this pill (sent/auto_sent) pass through
            if requested != "needs_review":
                kept.append(r)
    return kept


def _collapse_threads(rows: list) -> list:
    """READ-TIME thread collapse, never written back: one representative row
    per conversation, keyed (smartlead_campaign_id, lower(trim(lead_email)))
    — one thread per lead PER campaign (a lead in two campaigns stays two
    threads; owner ruling 2026-07-16). Intake deliberately stores one row per
    inbound reply (message_id is in the upsert key), so a conversation
    accumulates siblings; the UI must show only the newest one.

    Representative = most recent replied_at, tie-break latest created_at,
    then highest id. ISO8601 strings compare lexicographically; a null stamp
    becomes "" and sorts oldest, so it never wins. Rows with no lead_email
    pass through uncollapsed (never clump into one fake thread), and is_test
    is part of the key so a synthetic training row can never shadow a real
    conversation. Runs BEFORE _reclassify_queue: collapse first, then decide
    who spoke last on the survivor."""
    def rank(r):
        return (str(r.get("replied_at") or ""), str(r.get("created_at") or ""), r.get("id") or 0)
    best = {}
    loose = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        em = str(r.get("lead_email") or "").strip().lower()
        if not em:
            loose.append(r)
            continue
        key = (bool(r.get("is_test")), str(r.get("smartlead_campaign_id") or ""), em)
        cur = best.get(key)
        if cur is None or rank(r) > rank(cur):
            best[key] = r
    return list(best.values()) + loose


# Representative-row ids, cached ~10s. Every pill fetch needs cross-status
# visibility (a needs_review row must vanish when a NEWER dismissed sibling
# exists), so the collapse is computed from one light all-status fetch and
# the winning ids filter each pill's full fetch. Same TTL-dict pattern as
# _POLL_TS_CACHE; _bust_read_caches clears it on mutations.
_REP_IDS_TTL = 10.0
_REP_IDS_CACHE = {"at": 0.0, "val": None}


def _thread_rep_ids():
    """Set of setter_queue ids that are their thread's representative row,
    or None when the light fetch fails (callers then skip the collapse and
    degrade to the uncollapsed view rather than blanking the inbox)."""
    now = _time.time()
    if _REP_IDS_CACHE["val"] is not None and (now - _REP_IDS_CACHE["at"]) < _REP_IDS_TTL:
        return _REP_IDS_CACHE["val"]
    try:
        light = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&limit=2000"
                           "&select=id,smartlead_campaign_id,lead_email,replied_at,created_at,is_test") if _SB else None
        if not isinstance(light, list):
            return None
        val = {r.get("id") for r in _collapse_threads(light) if isinstance(r, dict)}
    except Exception:  # noqa: BLE001 - collapse is best-effort, never sink the queue
        return None
    _REP_IDS_CACHE["val"] = val
    _REP_IDS_CACHE["at"] = now
    return val


_POLL_TS_TTL = 10.0
_POLL_TS_CACHE = {"at": 0.0, "val": None}


def _last_poll_done_at():
    """Timestamp of the last COMPLETED reply-check (the setter_poll_done
    activity row) — what the UI shows as "last checked X ago". None when the
    ledger has no such row yet. Cached ~10s: it rides on EVERY queue GET and
    the display is minutes-granular, so the extra Supabase round-trip per GET
    was pure overhead (perf pass 2026-07-16)."""
    now = _time.time()
    if _POLL_TS_CACHE["val"] is not None and (now - _POLL_TS_CACHE["at"]) < _POLL_TS_TTL:
        return _POLL_TS_CACHE["val"]
    try:
        rows = _SB("GET", "app_activity_log?action=eq.setter_poll_done"
                          "&order=ts.desc&limit=1&select=ts") if _SB else None
        val = rows[0].get("ts") if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001 - a ledger hiccup must never break the queue
        val = None
    if val is not None:
        _POLL_TS_CACHE["val"] = val
        _POLL_TS_CACHE["at"] = now
    return val


# ── Queue-rows read cache (perf pass 2026-07-16) ──────────────────────────
# One /api/setter/queue GET used to re-fetch every row (2MB+ of stored threads)
# from Supabase and re-run the direction reclass on EVERY call - and the
# sent/auto_sent pills fetch TWO row sets each. Cache the finished (fetched +
# reclassified + annotated) row list per (status, limit):
#   fresh  -> serve cached;
#   stale  -> serve cached NOW, refresh once in the background (SWR);
#   absent (boot / hard bust after a mutation) -> compute synchronously,
#            single-flight per key so concurrent GETs join one compute.
# Mutations (_apply_patch status changes, run_poll queuing rows) call
# _bust_read_caches() which drops everything and starts a rewarm, so reads
# right after an action are fresh - never zombie-stale.
_ROWS_TTL = 20.0
_ROWS_CACHE = {}   # (status, limit) -> {"at": ts, "rows": [annotated rows]}
_ROWS_LOCKS = {}   # (status, limit) -> per-key single-flight lock
_ROWS_META = threading.Lock()
# Keys worth rewarming after a bust: the standard pill fetches the UI makes.
_ROWS_REWARM_STATUSES = ("", "needs_review", "sent", "auto_sent", "dismissed")


def _rows_lock(key):
    with _ROWS_META:
        lk = _ROWS_LOCKS.get(key)
        if lk is None:
            lk = _ROWS_LOCKS[key] = threading.Lock()
        return lk


def _fetch_queue_rows(status: str, limit: int) -> list:
    """The uncached read: fetch, direction-reclassify, annotate. Pure read."""
    rows = []
    if _SB:
        base = f"workspace=eq.{WORKSPACE}&order=created_at.desc&limit={limit}&select=*"
        # For the direction-aware pills (needs_review / sent / auto_sent) the
        # membership depends on who spoke last, computed at read time from
        # `thread` (see _queue_direction). The sent/auto_sent pills must also
        # consider needs_review rows we've already answered, so pull both.
        statuses = []
        if status in ("sent", "auto_sent"):
            statuses = [status, "needs_review"]
        elif status:
            statuses = [status]
        if statuses:
            for st in statuses:
                fetched = _SB("GET", f"{QUEUE_TABLE}?{base}&status=eq.{st}")
                if isinstance(fetched, list):
                    rows.extend(fetched)
        else:  # All
            fetched = _SB("GET", f"{QUEUE_TABLE}?{base}")
            rows = fetched if isinstance(fetched, list) else []
        # Thread collapse FIRST (one representative row per conversation),
        # THEN the who-spoke-last reclass on the survivor - the order is
        # load-bearing: a stale needs_review sibling must vanish because a
        # newer dismissed/sent sibling won the thread, and only the winner's
        # own state decides its pill.
        rep_ids = _thread_rep_ids()
        if rep_ids is not None:
            rows = [r for r in rows if isinstance(r, dict) and r.get("id") in rep_ids]
        if status in ("needs_review", "sent", "auto_sent"):
            rows = _reclassify_queue(rows, status)
        rows.sort(key=lambda r: (r or {}).get("created_at") or "", reverse=True)
    return [_annotate_queue_row(r) for r in rows if isinstance(r, dict)]


def _store_rows(key, rows):
    _ROWS_CACHE[key] = {"at": _time.time(), "rows": rows}


def _queue_rows_cached(status: str, limit: int) -> list:
    key = (status, limit)
    ent = _ROWS_CACHE.get(key)
    if ent:
        if (_time.time() - ent["at"]) < _ROWS_TTL:
            return ent["rows"]
        _kick_rows_refresh(key)   # stale-while-revalidate
        return ent["rows"]
    lk = _rows_lock(key)
    with lk:
        ent = _ROWS_CACHE.get(key)   # a waiter's compute may have landed
        if ent:
            return ent["rows"]
        rows = _fetch_queue_rows(status, limit)
        _store_rows(key, rows)
        return rows


def _kick_rows_refresh(key):
    def run():
        lk = _rows_lock(key)
        if not lk.acquire(blocking=False):
            return   # someone is already refreshing this key
        try:
            _store_rows(key, _fetch_queue_rows(*key))
        except Exception:  # noqa: BLE001 - background refresh must never raise
            pass
        finally:
            lk.release()
    threading.Thread(target=run, daemon=True).start()


def _bust_read_caches(rewarm: bool = True):
    """A mutation changed queue rows: drop every read cache so the next GET
    reads fresh, and start rewarming so that GET usually joins a compute
    already in flight instead of starting cold."""
    with _KPI_LOCK:
        _KPI_CACHE["val"] = None
        _KPI_CACHE["at"] = 0.0
    _POLL_TS_CACHE["at"] = 0.0
    _POLL_TS_CACHE["val"] = None
    _REP_IDS_CACHE["at"] = 0.0
    _REP_IDS_CACHE["val"] = None
    stale_keys = [k for k in list(_ROWS_CACHE.keys())
                  if k[0] in _ROWS_REWARM_STATUSES and k[1] == 200]
    _ROWS_CACHE.clear()
    if rewarm:
        _kick_kpi_refresh()
        for k in (stale_keys or [("needs_review", 200)]):
            _kick_rows_refresh(k)


def route_queue_get(params):
    try:
        status = _qp(params, "status", "")
        try:
            limit = int(_qp(params, "limit", "200") or 200)
        except ValueError:
            limit = 200
        limit = max(1, min(limit, 500))
        rows = _queue_rows_cached(status, limit) if _SB else []
        # fields=list: the inbox LIST doesn't need the stored `thread` blobs -
        # they're ~80% of the payload (measured 1.3MB of 1.6MB live). The UI
        # opts in for its fast first paint and hydrates full rows in the
        # background; the default (no param) response is byte-identical to
        # before, so nothing else changes shape.
        if _qp(params, "fields", "") == "list":
            rows = [{k: v for k, v in r.items() if k != "thread"} for r in rows]
        return 200, {"rows": rows, "kpis": _compute_kpis(), "last_checked": _last_poll_done_at()}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_thread_get(params):
    """Fresh thread for one queue row, re-hydrated live from Smartlead when
    the owner OPENS it (owner ruling 2026-07-15: an opened thread must show
    the latest emails, not the intake-time snapshot). The refreshed thread is
    also persisted back to the row (real column - schema-safe) so the list
    stays current even without another open. Test rows have no Smartlead
    lead behind them; they return their stored thread untouched."""
    try:
        qid = _qp(params, "id", "")
        if not qid:
            return 400, {"error": "id is required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        if row.get("is_test"):
            return 200, {"thread": row.get("thread") or [], "refreshed": False}
        mid = row.get("message_id") or row.get("source_message_id") or ""
        ok, hyd, herr = hydrate_lead(row.get("smartlead_campaign_id"), row.get("lead_email"), mid)
        if not ok:
            # Stale beats broken: hand back the stored snapshot with the why.
            return 200, {"thread": row.get("thread") or [], "refreshed": False, "detail": herr}
        thread = hyd.get("thread") or []
        try:
            _apply_patch(row, {"thread": thread})
        except Exception:  # noqa: BLE001 - persisting is best-effort; the response is what matters
            pass
        return 200, {"thread": thread, "refreshed": True}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _instructions_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or "").encode()).hexdigest()


def _learn_from_edit_worker(row: dict, agent: dict, original: str, sent: str):
    """Turns a reviewer's hand-edit into a standing lesson. Runs off the
    request thread - see _learn_from_edit_async. Never raises: this is a
    nice-to-have that must never surface as a failed send.

    On a successful merge it also writes a ONE-SLOT `last_edit_lesson` record
    onto the agent doc (tester panel 2026-07-17: a silent permanent write was
    the whole failure - the reviewer needs to SEE that their edit taught
    something, and be able to take it back). One slot, overwritten by each
    newer lesson, so the doc never grows: undo is only offered for the most
    recent lesson, and only while the instructions haven't changed since
    (post_sha guard - see route_edit_lesson_undo)."""
    try:
        rule = lesson_from_edit(original, sent, {
            "lead_first_name": row.get("lead_first_name"),
            "lead_last_name": row.get("lead_last_name"),
            "company_domain": row.get("company_domain"),
        }, instructions=_agent_instructions(agent))
        if not rule:
            return
        prev = _agent_instructions(agent)
        # Same door typed feedback uses: instructions stay the single living
        # manual, and the edit lands in instruction_edits beside it for audit.
        ok, new_text, _how = merge_correction_into_instructions(agent, rule, source=str(row.get("id") or "edit"))
        if not ok:
            return
        _save_agent({"id": agent.get("id"), "name": agent.get("name"), "last_edit_lesson": {
            "source": str(row.get("id") or "edit"), "rule": rule,
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "prev_instructions": prev, "post_sha": _instructions_sha(new_text),
        }})
    except Exception as e:  # noqa: BLE001
        print(f"[setter] learn-from-edit failed for row {row.get('id')}: {e}", file=sys.stderr)


def _learn_from_edit_async(row: dict, agent: dict, original: str, sent: str, training_on: bool):
    """Decides - cheaply, with no LLM call - whether this send has anything to
    learn from, then hands the work to a daemon thread.

    Deliberately fail-closed on training_on: the review pane defaults the
    switch ON and states the mode explicitly on every send, so a request that
    says nothing is a stale or third-party client, and a silent surprise
    lesson is worse than a missed one."""
    if not training_on:
        return None
    if not row.get("agent_id") or not agent.get("id"):
        return None  # agentless row - there is no brain to teach
    if not (original or "").strip() or not (sent or "").strip():
        return None  # nothing to diff against (pre-migration row, or no draft)
    if _draft_text(original) == _draft_text(sent):
        return None  # approved as written - the setter got it right, teach nothing
    t = threading.Thread(target=_learn_from_edit_worker, args=(row, agent, original, sent),
                        daemon=True, name="setter-learn-from-edit")
    t.start()
    return t


def route_queue_action(payload):
    try:
        payload = payload or {}
        qid = payload.get("id")
        action = payload.get("action")
        if not qid or not action:
            return 400, {"error": "id and action are required"}
        if action == "dismiss":
            # One round-trip (perf ruling 2026-07-16): the old GET-then-PATCH
            # cost two sequential Supabase calls over keep-alive-less urllib.
            # return=representation makes the PATCH itself the existence check.
            updated = _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{qid}",
                          {"status": "dismissed"}, "return=representation") if _SB else None
            if not (isinstance(updated, list) and updated):
                return 404, {"error": "Queue row not found."}
            _bust_read_caches()
            return 200, {"ok": True, "status": "dismissed"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        if action == "subsequence":
            checked = bool(payload.get("checked"))
            if not checked:
                # Smartlead's API has no documented "remove from subsequence"
                # call - unchecking only clears our own flag. Say so honestly
                # rather than implying a Smartlead un-enrol happened.
                _apply_patch(row, {"added_to_subsequence": False})
                return 200, {"ok": True, "added_to_subsequence": False,
                            "detail": "Cleared locally - Smartlead has no API to un-enrol a lead from a "
                                      "subsequence, so nothing was changed on the Smartlead side."}
            campaign_id = row.get("smartlead_campaign_id")
            sub_id, err = _resolve_subsequence_id(campaign_id, payload.get("sub_sequence_id"))
            if err:
                return err
            ok, detail = _push_to_subsequence(campaign_id, row.get("lead_email"), row.get("smartlead_lead_id"), sub_id)
            if not ok:
                return 502, {"ok": False, "added_to_subsequence": False, "subsequence_id": sub_id,
                            "error": detail if isinstance(detail, str) else "Smartlead rejected the request.",
                            "detail": detail}
            _apply_patch(row, {"added_to_subsequence": True})
            return 200, {"ok": True, "added_to_subsequence": True, "subsequence_id": sub_id, "detail": detail}
        if action == "save_draft":
            # Auto-save (owner ask 2026-07-16): a hand-edited draft used to live
            # ONLY in the browser's EDITED_DRAFTS map, so a failed send, a reload
            # or a closed tab threw the edit away. Persist it as it's typed so a
            # send error can never cost the reviewer their work.
            if row.get("status") in ("sent", "auto_sent"):
                return 409, {"error": "This reply was already sent."}
            body_html = payload.get("body")
            if body_html is None:
                return 400, {"error": "body is required"}
            # Schema freeze: draft_body/draft_subject exist, nothing else here.
            patch = {"draft_body": body_html}
            if payload.get("subject"):
                patch["draft_subject"] = payload["subject"]
            _apply_patch(row, patch)
            return 200, {"ok": True, "saved_at": _dt.datetime.now(_dt.timezone.utc)
                         .isoformat(timespec="seconds")}
        if action == "send":
            if row.get("status") in ("sent", "auto_sent"):
                return 409, {"error": "This reply was already sent."}
            agent = _load_agent(row.get("agent_id")) or {}
            subject = payload.get("subject_override") or row.get("draft_subject") or f"Re: {row.get('reply_subject') or ''}"
            body_html = payload.get("body_override") or row.get("draft_body") or ""
            original = row.get("original_draft_body") or ""
            result = _send_reply(row, agent, subject, body_html, is_test=bool(row.get("is_test")), success_status="sent")
            if result.get("ok"):
                # Owner ask 2026-07-17: rewriting the draft IS feedback. Only
                # a SUCCESSFUL send teaches - a reply that never left must not
                # change the brain. Fires after the send, in the background:
                # Approve returns the moment the mail is away, never waiting on
                # the learner's gpt-5-mini call (perf bar, 2026-07-16).
                _learn_from_edit_async(row, agent, original, body_html,
                                      training_on=bool(payload.get("training")))
            return 200, {"ok": result.get("ok"), "row": {**row, **(result.get("row") or {})}}
        return 400, {"error": f"Unknown action '{action}'."}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_subsequence_push(payload):
    """Pushes a lead into a Smartlead subsequence WITHOUT a setter_queue row
    behind it (e.g. a lead the setter never touched). Resolves the lead by
    email within campaign_id, same push path as route_queue_action's
    "subsequence" action."""
    try:
        payload = payload or {}
        campaign_id = payload.get("campaign_id")
        email = str(payload.get("email") or "").strip()
        if not campaign_id or not email:
            return 400, {"error": "campaign_id and email are required"}
        sub_id, err = _resolve_subsequence_id(campaign_id, payload.get("sub_sequence_id"))
        if err:
            return err
        ok, detail = _push_to_subsequence(campaign_id, email, None, sub_id)
        if not ok:
            return 502, {"ok": False, "added_to_subsequence": False, "subsequence_id": sub_id,
                        "error": detail if isinstance(detail, str) else "Smartlead rejected the request.",
                        "detail": detail}
        return 200, {"ok": True, "added_to_subsequence": True, "subsequence_id": sub_id, "detail": detail}
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
        feedback_text = str(payload.get("feedback") or "").strip()
        # Persistent learning layer (owner ruling 2026-07-14): only when the
        # caller explicitly opts in with scope="remember" does this feedback
        # get merged into the agent's instructions (so every FUTURE pass
        # applies it too, not just this regeneration) via
        # merge_correction_into_instructions - the single living manual.
        # Default/absent scope ("one_off") persists nothing, matching
        # pre-existing behaviour exactly. The reload picks up the freshly
        # merged instructions for THIS regeneration too.
        if payload.get("scope") == "remember" and feedback_text and agent.get("id"):
            merge_correction_into_instructions(agent, feedback_text, source=str(qid))
            agent = _load_agent(agent.get("id")) or agent
        settings = _load_settings()
        classification = row.get("classification") or {}
        tz = row.get("timezone")
        # A stored timezone was already vetted at intake; only a fresh
        # resolve below can downgrade confidence.
        tz_confident = bool(tz)
        fresh_classification = None
        # Adopted/agentless rows reach Regenerate with NO stored classification
        # (their intake deliberately skips the brain) - a redraft used to run
        # blind: no intent routing and no original-outreach anchor, which is
        # how a lead's "Sure." to "can I send it over?" drew a generic calendar
        # reply instead of the resource (owner report 2026-07-15). Classify
        # here exactly like the live pipeline and persist the result, so the
        # draft (and the UI's Intent line) see what a pipeline row sees.
        if not classification:
            body_text = clean_body(row.get("reply_body") or "")
            last_outbound = ""
            for m in reversed(row.get("thread") or []):
                if str(m.get("type") or "").upper() == "SENT":
                    last_outbound = _TAG_RE.sub(" ", str(m.get("body") or ""))[:800]
                    break
            if not (row.get("first_outbound") or ""):
                for m in (row.get("thread") or []):
                    if str(m.get("type") or "").upper() == "SENT":
                        row["first_outbound"] = clean_body(str(m.get("body") or ""))[:1500]
                        break
            domain = (row.get("company_domain") or "").lower()
            comp_hints = _company_hints(domain)
            company_location = ", ".join([v for v in (comp_hints.get("country"), comp_hints.get("state"),
                                                      comp_hints.get("city")) if v])
            mem_hints = _prefix_latest_rules(_latest_owner_rules(agent), _agent_memory_digest(agent))
            try:
                classification = classify({"subject": row.get("reply_subject"), "body": body_text,
                                           "last_outbound": last_outbound,
                                           "first_outbound": row.get("first_outbound") or "",
                                           "email_domain": domain, "company_location": company_location},
                                          agent, owner_hints=mem_hints)
                fresh_classification = classification
                if not tz:
                    hints = {"country": comp_hints.get("country"), "state": comp_hints.get("state"),
                             "city": comp_hints.get("city"), "phone": _extract_phone(body_text),
                             "tld": ".".join(domain.split(".")[-2:]) if domain else "", "body": body_text}
                    tz, tz_confident = resolve_timezone(hints, classification)
            except Exception:  # noqa: BLE001 - classify outage: the draft still runs, just without intent routing
                classification = {}
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
        thread_text = " ".join(str(m.get("body") or "") for m in (row.get("thread") or []))
        # Standing memory always applies first, then this specific redraft's
        # feedback on top of it - same order Feature 1's spec sets for every
        # live classify()/draft_reply() call. The LATEST OWNER RULES block
        # (recency weighting) is the outermost prefix, ahead of even the
        # standing memory digest.
        # Feedback-first budget (owner ruling 2026-07-16): draft_reply caps
        # reviewer_feedback at REVIEWER_FEEDBACK_CAP, and the typed feedback
        # used to sit at the truncatable TAIL - after the LATEST OWNER RULES
        # block (~1600 chars) and the memory digest (~2000) - so a big digest
        # silently deleted the very instruction the reviewer just typed.
        # Same ordering as before; the RULES and DIGEST shrink to whatever
        # room remains, the fresh feedback is never cut.
        rules_block = _latest_owner_rules(agent)
        rules_block = rules_block[:max(REVIEWER_FEEDBACK_CAP - len(feedback_text) - 4, 0)]
        mem_digest = _agent_memory_digest(agent)
        mem_digest = mem_digest[:max(REVIEWER_FEEDBACK_CAP - len(rules_block) - len(feedback_text) - 4, 0)]
        combined_feedback = "\n".join([x for x in (mem_digest, feedback_text) if x])
        combined_feedback = _prefix_latest_rules(rules_block, combined_feedback)
        # No live thread re-read on a redraft (the row doesn't keep a from_name
        # separate from its stored thread) - resolves to the agent's own
        # configured identity via _sender_first_for, same as every other
        # non-live surface. See owner bug report 2026-07-14.
        d = draft_reply(
            {"first_name": row.get("lead_first_name"), "subject": row.get("reply_subject"), "body": row.get("reply_body"),
             "first_outbound": row.get("first_outbound") or "",
             "thread_text": thread_text},
            agent, classification, slots, slot_status, sender_first=_sender_first_for(agent),
            regen_feedback=combined_feedback)
        draft_html = d.get("html")
        if draft_html:
            # Second sweep (owner brief 2026-07-14): proofread before this
            # regenerated draft is saved.
            draft_html, _proofread_changed = proofread_draft(draft_html)
        # Re-stamped, not preserved: the baseline for an Approve-time diff is
        # the LATEST thing the agent wrote, not its first attempt. Edits the
        # reviewer makes after this regenerate are measured against this draft.
        patch = {"draft_subject": d.get("subject"), "draft_body": draft_html,
                 "original_draft_body": draft_html, "slots": slots}
        if fresh_classification is not None:
            # Persist what the redraft-classify learned so the UI's Intent
            # line updates and the next Regenerate doesn't re-classify.
            patch["classification"] = fresh_classification
            patch["first_outbound"] = row.get("first_outbound") or ""
            if tz:
                patch["timezone"] = tz
        # Re-run the SAME lint + decision gate the live pipeline applies, so
        # the row's verdict (and the inbox pill, which reads decision_reason)
        # describes THIS draft - not the one it replaced. Owner report
        # 2026-07-15: a row whose first draft failed kept "No draft was
        # produced." beside a perfectly good regenerated draft.
        body_text = clean_body(row.get("reply_body") or "")
        slots_fallback = slot_status != "ok"
        needs_availability_ask = "scheduling" in (classification.get("all_intents") or [])
        lint_ok, lint_reason = False, "No draft was produced."
        if draft_html:
            lint_ok, lint_reason = lint_draft(draft_html, {
                "subject": d.get("subject"), "first_name": row.get("lead_first_name"),
                "needs_resource_link": "send_resource" in (classification.get("all_intents") or []),
                "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
                "slot_labels": [s.get("label") for s in slots],
                "instructions": _agent_instructions(agent), "booking_link": _booking_link(agent),
                "thread_text": f"{body_text} {thread_text}",
                "slots_fallback": slots_fallback, "needs_availability_ask": needs_availability_ask,
            })
        first_touch = True
        if not row.get("is_test") and _SB:
            try:
                prior = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{row.get('workspace')}"
                                   f"&smartlead_campaign_id=eq.{row.get('smartlead_campaign_id')}"
                                   f"&lead_email=eq.{row.get('lead_email')}"
                                   f"&status=in.(auto_sent,sent)&select=id&limit=1")
                first_touch = not (isinstance(prior, list) and prior)
            except Exception:  # noqa: BLE001
                first_touch = True
        decision, reason = decide(classification, agent, {
            "red_flag_hits": lexicon_hits(body_text), "category": row.get("category"),
            "first_touch": first_touch, "slot_status": slot_status, "slots_fallback": slots_fallback,
            "timezone": tz, "tz_confident": tz_confident,
            "lint_ok": lint_ok, "lint_reason": lint_reason,
            "body_len": len(body_text), "hydrated": True, "answered_since_reply": False,
            "autopilot_enabled": bool(settings.get("autopilot_enabled")),
            "same_day_ask": bool(_SAME_DAY_RE.search(_strip_quoted(body_text))),
            "first_outbound_present": bool((row.get("first_outbound") or "").strip()),
            "needs_availability_ask": needs_availability_ask,
        })
        # A redraft NEVER sends (owner ruling 2026-07-16): the human asked for
        # this draft mid-review, so the send stays theirs via Approve.
        if decision == "auto_send":
            decision, reason = "review", "Ready to send: every check passed - approve to send it."
        patch["decision"], patch["decision_reason"] = decision, reason
        if decision == "no_action":
            # Mirror the pipeline (owner ruling 2026-07-16): a no_action
            # verdict keeps no draft and moves the row out of review.
            patch["draft_subject"], patch["draft_body"] = None, None
            patch["original_draft_body"] = None
            patch["status"] = "no_action"
        _apply_patch(row, patch)
        # Transient, response-only (setter_queue schema-freeze: never a new
        # column): the drafter's can't-comply explanation for the TYPED
        # feedback, surfaced only when the reviewer actually typed some.
        return 200, {"row": {**row, **patch},
                     "feedback_note": (d.get("feedback_note") or "") if feedback_text else ""}
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


# ── grading page (temporary) ─────────────────────────────────────────────────
# Cases are generated by the orchestrator elsewhere, not this file - these
# routes only read/write the stored doc. See setter_v2_spec.md section 4.
#
# "Relearn": when the owner leaves a note or marks a call/reply wrong, that
# feedback is turned into a plain-English digest and every still-unanswered
# case is re-classified/re-decided/re-drafted with it, in the background, so
# the owner never has to repeat the same correction case after case. This
# never touches setter_queue, campaigns, webhooks, or any send path - it only
# reads/writes the __grading__ doc row, using the exact same classify/
# decide/draft_reply/lint_draft pipeline pieces app/generate_grading.py used
# to build the cases in the first place.

_GRADING_RELEARN_LOCK = threading.Lock()


def route_grading_get(_params):
    try:
        doc = _load_grading()
        relearn = doc.get("relearn") or {"status": "idle"}
        # Self-heal a stale "running" left behind by a process restart mid-pass
        # (the in-memory thread and lock die with the process): a pass over
        # ~60 cases never legitimately runs longer than ~15 minutes.
        if relearn.get("status") == "running" and not _GRADING_RELEARN_LOCK.locked():
            try:
                started = _parse_iso(relearn.get("started_at"))
                age = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds()
                if age > 900:
                    relearn = {**relearn, "status": "idle", "stale_recovered": True}
            except (TypeError, ValueError):
                relearn = {**relearn, "status": "idle", "stale_recovered": True}
        return 200, {
            "cases": doc.get("cases") or [],
            "answers": doc.get("answers") or {},
            "relearn": relearn,
            "feedback_log": doc.get("feedback_log") or [],
        }
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_grading_answer(payload):
    try:
        payload = payload or {}
        case_id = str(payload.get("id") or "")
        if not case_id:
            return 400, {"error": "id is required"}
        doc = _load_grading()
        answers = dict(doc.get("answers") or {})
        note = str(payload.get("note") or "").strip()
        decision_ok = payload.get("decision_ok")
        reply_ok = payload.get("reply_ok")
        at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        answers[case_id] = {"decision_ok": decision_ok, "reply_ok": reply_ok, "note": note, "at": at}
        doc["answers"] = answers

        # Any note, or an explicit "wrong" on either question, is feedback
        # worth learning from - the owner shouldn't have to repeat it on
        # every other case that has the same problem.
        triggers_relearn = bool(note) or decision_ok is False or reply_ok is False
        if triggers_relearn:
            feedback_log = list(doc.get("feedback_log") or [])
            feedback_log.append({"case_id": case_id, "note": note, "decision_ok": decision_ok,
                                 "reply_ok": reply_ok, "at": at})
            doc["feedback_log"] = feedback_log

        _save_grading(doc)

        relearn_status = _kick_off_relearn() if triggers_relearn else dict(doc.get("relearn") or {"status": "idle"})
        return 200, {"ok": True, "answers": answers, "relearn": relearn_status}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_grading_reset(_payload):
    try:
        doc = _load_grading()
        doc["answers"] = {}
        _save_grading(doc)
        return 200, {"ok": True}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _kick_off_relearn() -> dict:
    """Starts a background relearn pass if none is already running, else just
    marks doc.relearn.queued so the pass already running reruns once more at
    the end with the fuller digest. Never blocks on the actual work - returns
    the relearn status dict immediately for the caller to hand back to the
    browser."""
    if _GRADING_RELEARN_LOCK.acquire(blocking=False):
        try:
            doc = _load_grading()
            relearn = {
                "status": "running",
                "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                "finished_at": None,
                "notes_applied": len(doc.get("feedback_log") or []),
                "cases_updated": 0,
                "queued": False,
            }
            doc["relearn"] = relearn
            _save_grading(doc)
        except Exception:  # noqa: BLE001
            _GRADING_RELEARN_LOCK.release()
            raise
        threading.Thread(target=_grading_relearn_threadmain, daemon=True).start()
        return relearn

    # Already running: just flag that another pass is wanted once this one
    # finishes - never start a second pass concurrently.
    doc = _load_grading()
    relearn = dict(doc.get("relearn") or {"status": "running"})
    relearn["queued"] = True
    doc["relearn"] = relearn
    _save_grading(doc)
    return relearn


def _grading_relearn_threadmain():
    try:
        _grading_relearn()
    finally:
        try:
            _GRADING_RELEARN_LOCK.release()
        except RuntimeError:  # noqa: BLE001 - lock wasn't held (shouldn't happen); never crash a bg thread
            pass


def _is_case_answered(case_id, answers: dict) -> bool:
    a = (answers or {}).get(case_id)
    return isinstance(a, dict) and a.get("decision_ok") is not None


def _feedback_digest(feedback_log: list, cases_by_id: dict, limit_chars: int = 2000) -> str:
    """Plain-English digest of everything the owner has taught the tool so
    far, newest first, capped to roughly limit_chars. Fed into both
    classify()'s owner_hints and draft_reply()'s regen_feedback so a relearn
    pass actually applies the correction instead of just recording it."""
    lines = []
    for entry in reversed(feedback_log or []):
        note = str((entry or {}).get("note") or "").strip()
        if note:
            lines.append(f"- {note}")
            continue
        case = cases_by_id.get(str((entry or {}).get("case_id"))) or {}
        inbound_snip = str(case.get("inbound") or "")[:80]
        if entry.get("decision_ok") is False:
            decision = case.get("decision") or "call"
            lines.append(f"- The owner said the '{decision}' call was wrong for a reply like: '{inbound_snip}'")
        elif entry.get("reply_ok") is False:
            lines.append(f"- The owner disliked the draft written for: '{inbound_snip}'")
    digest = "\n".join(lines)
    return digest[:limit_chars]


_CALENDLY_SLOT_ANCHOR_RE = re.compile(
    r'<a\s+href="([^"]*calendly\.com[^"]*/(20\d{2}-\d{2}-\d{2}T[0-9:]+)[^"]*)"[^>]*>([^<]*)</a>',
    re.IGNORECASE)


def _extract_calendly_slots(draft_html: str) -> list:
    """Pulls the real call-time deep links back out of an EXISTING draft's
    HTML (anchors whose href contains calendly.com and an ISO /2026-07-15T11:00
    path segment), so a relearn re-draft can keep offering the same real times
    instead of inventing new ones or calling Calendly again. Returns up to two
    {iso, label, link} dicts, same shape pick_slots() produces."""
    out = []
    for href, iso, label in _CALENDLY_SLOT_ANCHOR_RE.findall(draft_html or ""):
        out.append({"iso": iso, "label": (label or "").strip(), "link": href})
        if len(out) >= 2:
            break
    return out


def _relearn_one_case(case: dict, agent_snapshot: dict, digest: str):
    """Re-runs classify -> decide -> draft_reply for one grading case using
    the owner's feedback digest, mutating `case` in place. Never raises - a
    failure here just leaves the case exactly as it was."""
    try:
        ctx_src = case.get("_ctx") or {}
        inbound = case.get("inbound") or ""
        first_outbound = ctx_src.get("first_outbound") or case.get("first_email") or ""
        reply_for_classify = {
            "subject": ctx_src.get("subject") or "",
            "body": inbound,
            "last_outbound": ctx_src.get("last_outbound") or "",
            "first_outbound": first_outbound,
            "email_domain": ctx_src.get("email_domain") or "",
            "company_location": ctx_src.get("company_location") or "",
        }
        cls = classify(reply_for_classify, agent_snapshot, owner_hints=digest)

        tz = ctx_src.get("timezone")
        slot_status = ctx_src.get("slot_status")
        slots = []
        if slot_status == "ok":
            slots = _extract_calendly_slots(case.get("draft_html") or "")
        # Calendly fallback (owner ruling 2026-07-14) - see decide() gate 7
        # and lint_draft().
        slots_fallback = slot_status != "ok"
        needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

        primary = cls.get("primary_intent")
        try:
            confidence = float(cls.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        is_clear_neg = primary in CLEAR_NEGATIVE_INTENTS and confidence >= 0.8

        draft_html = None
        lint_ok, lint_reason = False, "No draft was produced."
        if not is_clear_neg:
            try:
                d = draft_reply(
                    {"first_name": case.get("lead_first_name") or "", "subject": ctx_src.get("subject") or "",
                     "body": inbound, "first_outbound": first_outbound},
                    agent_snapshot, cls, slots, slot_status,
                    sender_first=_sender_first_for(agent_snapshot), regen_feedback=digest)
                draft_html = d.get("html")
                lint_ok, lint_reason = lint_draft(draft_html, {
                    "subject": d.get("subject"), "first_name": case.get("lead_first_name") or "",
                    "needs_resource_link": "send_resource" in (cls.get("all_intents") or []),
                    "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
                    "slot_labels": [s.get("label") for s in slots],
                    "instructions": _agent_instructions(agent_snapshot),
                    "booking_link": _booking_link(agent_snapshot), "thread_text": inbound,
                    "slots_fallback": slots_fallback, "needs_availability_ask": needs_availability_ask,
                })
            except Exception:  # noqa: BLE001
                draft_html = None
                lint_ok, lint_reason = False, "No draft was produced."

        ctx = {
            "red_flag_hits": lexicon_hits(inbound), "category": ctx_src.get("category"),
            "first_touch": True, "slot_status": slot_status, "slots_fallback": slots_fallback,
            "timezone": tz,
            "tz_confident": ctx_src.get("tz_confident", tz is not None),
            "lint_ok": lint_ok, "lint_reason": lint_reason,
            "body_len": ctx_src.get("body_len") if ctx_src.get("body_len") is not None else len(inbound),
            "hydrated": True, "answered_since_reply": False, "autopilot_enabled": True,
            "same_day_ask": bool(ctx_src.get("same_day_ask")),
            "first_outbound_present": bool(str(first_outbound or "").strip()),
            "needs_availability_ask": needs_availability_ask,
        }
        decision, reason = decide(cls, agent_snapshot, ctx)

        case["intent"] = primary
        case["confidence"] = cls.get("confidence")
        case["decision"] = decision
        case["reason"] = reason
        case["draft_html"] = draft_html
        case["would_auto"] = decision == "auto_send"
        case["updated_by_feedback"] = True
    except Exception:  # noqa: BLE001 - a single bad case must never abort the whole relearn pass
        pass


def _grading_relearn():
    """Never raises; never touches setter_queue, campaigns, webhooks, or any
    send path. Builds the feedback digest, then re-processes every currently
    unanswered case in position order, persisting after each one so the
    grading page can show progress mid-pass. If another trigger queued a
    fresh pass while this one ran, loops once more with the fresher digest
    before finishing."""
    try:
        while True:
            doc = _load_grading()
            cases = list(doc.get("cases") or [])
            feedback_log = list(doc.get("feedback_log") or [])
            agent_snapshot = doc.get("agent_snapshot") or {}
            answers = dict(doc.get("answers") or {})

            cases_by_id = {str(c.get("id")): c for c in cases}
            digest = _feedback_digest(feedback_log, cases_by_id)

            started_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            relearn = {"status": "running", "started_at": started_at, "finished_at": None,
                      "notes_applied": len(feedback_log), "cases_updated": 0, "queued": False}
            doc["relearn"] = relearn
            _save_grading(doc)

            unanswered_ids = [c.get("id") for c in cases if not _is_case_answered(c.get("id"), answers)]
            cases_updated = 0

            for cid in unanswered_ids:
                case = cases_by_id.get(cid)
                if not isinstance(case, dict):
                    continue
                _relearn_one_case(case, agent_snapshot, digest)
                cases_updated += 1

                # Persist incrementally, re-reading the freshest answers so an
                # answer saved by the user mid-pass is never clobbered - only
                # the cases/relearn/feedback_log fields are ours to write.
                fresh = _load_grading()
                out_doc = {
                    "cases": cases,
                    "answers": fresh.get("answers", answers),
                    "agent_snapshot": agent_snapshot,
                    "feedback_log": fresh.get("feedback_log", feedback_log),
                    "relearn": {**relearn, "cases_updated": cases_updated},
                }
                _save_grading(out_doc)

            fresh = _load_grading()
            queued = bool((fresh.get("relearn") or {}).get("queued"))
            finished_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            final_relearn = {"status": "idle", "started_at": started_at, "finished_at": finished_at,
                             "notes_applied": len(feedback_log), "cases_updated": cases_updated, "queued": False}
            out_doc = {
                "cases": cases,
                "answers": fresh.get("answers", answers),
                "agent_snapshot": agent_snapshot,
                "feedback_log": fresh.get("feedback_log", feedback_log),
                "relearn": final_relearn,
            }
            _save_grading(out_doc)

            if not queued:
                break
            # else: someone left more feedback while this pass ran - loop
            # again, this time reading the fuller feedback_log/digest.
    except Exception:  # noqa: BLE001 - a background thread must never raise
        try:
            doc = _load_grading()
            relearn = dict(doc.get("relearn") or {})
            relearn["status"] = "idle"
            relearn["finished_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            doc["relearn"] = relearn
            _save_grading(doc)
        except Exception:  # noqa: BLE001
            pass


# ── training engine (per-agent, permanent) ──────────────────────────────────
# Turns real archived replies into scenarios one agent can be trained on, in
# the open-ended batches. Every REAL scenario's inbound text is a real reply
# verbatim - the eval realism law applies here exactly like grading: no
# invented pricing, resources, or facts.
#
# SYNTHETIC scenarios (added 2026-07-14, built only when the real corpus
# can't fill a requested batch - see _invent_training_scenarios and
# _training_generate_worker's shortfall top-up) may invent the LEAD side of
# a scenario ONLY: the lead's name, company, and the wording/subject of
# their inbound reply. They must NEVER fabricate an agent-side fact - no
# price, no discount, no specific resource, no link, no availability
# window, no promised date. Every synthetic scenario's decision and draft
# still run through the exact same live classify/decide/draft_reply/
# lint_draft pipeline, with this agent's real brain (instructions) and
# memory, exactly like a real one - only the inbound text is made up.
# Synthetic cases carry "synthetic": true, NEVER touch used_reply_ids
# (there is no real reply to mark used), and never mint a fake reply_id
# (reply_id is always None on a synthetic case).
#
# Doc row id "training-<agent_id>" in the same reserved-row pattern as
# __settings__/__grading__ (see _load_agents's exclusion filter above).
# Uses the exact same classify/decide/draft_reply/lint_draft pipeline
# pieces as generate_grading.py, run as-if the master switch and this
# agent's mode were both ON (the question is "how would this agent have
# handled this", not "is autopilot on right now") - no send path exists
# anywhere in this section, real or synthetic.

TRAINING_ID_PREFIX = "training-"
SENT_MESSAGES_TABLE = "sent_messages"
REPLIES_TABLE = "replies"

TRAINING_BATCH_DEFAULT = 8
TRAINING_BATCH_MAX = 10
TRAINING_MAX_UNANSWERED = 40
# Public share-link trainers get a tighter unanswered-cases cap than the
# owner - a client link left idle for weeks should not silently pile up a
# huge backlog of scenarios.
TRAINING_MAX_UNANSWERED_SHARE = 20
TRAINING_ACTIONABLE_SHARE = 0.8

# Review mode (owner request 2026-07-14): "go back through some of the old
# scenarios and messaging, just to check that it's now been trained to
# actually be good" - re-runs a batch of already-ANSWERED cases through
# today's brain, see route_training_recheck.
TRAINING_RECHECK_DEFAULT = 6
TRAINING_RECHECK_MAX = 10

# Real corpus counts (verified against the live DB 2026-07-13) for the
# actionable reply categories - used only to PROPORTION how many of each
# real category a batch draws, never to invent a scenario.
_TRAINING_ACTIONABLE_WEIGHTS = {
    "Interested": 650, "Information Request": 482, "Meeting Request": 263,
    "Contact Forward": 59, "positive-re-reply": 18,
}
# The majority-of-corpus clear-negative categories - included at ~20% of
# every batch so a trainer also teaches the agent when to correctly LEAVE a
# reply alone, not just when to intervene.
_TRAINING_CLEAR_NEGATIVE_CATEGORIES = ["Not Interested", "Do Not Contact", "Wrong Person", "Out Of Office"]

# Synthetic scenarios (see the doctrine comment above) only ever invent the
# simple, common categories - Contact Forward and positive-re-reply are
# real-corpus-only categories, deliberately excluded here to keep invented
# scenarios simple and common rather than covering every edge case a real
# archived reply might. Not Interested and Out Of Office are the two
# clear-negative categories a synthetic scenario may represent.
_SYNTHETIC_ACTIONABLE_WEIGHTS = {cat: w for cat, w in _TRAINING_ACTIONABLE_WEIGHTS.items()
                                 if cat in ("Interested", "Information Request", "Meeting Request")}
_SYNTHETIC_NEGATIVE_CATEGORIES = ["Not Interested", "Out Of Office"]


def _training_doc_id(agent_id: str) -> str:
    return f"{TRAINING_ID_PREFIX}{agent_id}"


# Per-agent generation locks (mirrors _GRADING_RELEARN_LOCK's single global
# lock, but keyed by agent since two different agents' batches never
# conflict with each other - see route_training_generate). Guarded by their
# own lock purely for the get-or-create race on first use; the per-agent
# lock itself is what serialises actual generation work.
_TRAINING_GEN_LOCKS: dict = {}
_TRAINING_GEN_LOCKS_GUARD = threading.Lock()
# agent_id -> Thread. Production code never reads this map (the route
# returns before the thread finishes); tests join() it for determinism.
_TRAINING_GEN_THREADS: dict = {}


def _get_training_gen_lock(agent_id: str) -> threading.Lock:
    with _TRAINING_GEN_LOCKS_GUARD:
        lock = _TRAINING_GEN_LOCKS.get(agent_id)
        if lock is None:
            lock = threading.Lock()
            _TRAINING_GEN_LOCKS[agent_id] = lock
        return lock


# ── public training share links ──────────────────────────────────────────────
# The owner mints a per-agent link so a client can train ONE agent without a
# Navreo login. Same stateless-HMAC idiom server.py uses for its own session
# cookie (_mint_session/_session_email): a base64url payload plus a
# hex-digest signature derived from SUPABASE_SERVICE_ROLE_KEY, so no new
# secret is needed and the token survives deploys. A share token only ever
# proves "this bearer may train agent <agent_id> until <exp>" - it carries no
# other permission, and route_agents_memory_delete refuses it outright.

def _share_secret() -> bytes:
    import hashlib
    srk = _KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    return hashlib.sha256((srk + ":navreo-train-share-v1").encode()).digest()


def mint_training_share(agent_id: str, days: int = 30) -> str:
    import base64
    import hashlib
    import hmac
    import time
    exp = int(time.time()) + max(1, int(days or 30)) * 86400
    payload = f"train|{agent_id}|{exp}".encode()
    sig = hmac.new(_share_secret(), payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


def verify_training_share(token: str):
    """The agent_id a share token is valid for, or None. Checks the HMAC
    signature, the "train" prefix, and expiry - never raises, so a malformed
    or tampered token is just treated as 'not valid' everywhere it is used."""
    import base64
    import hashlib
    import hmac
    import time
    try:
        token = str(token or "")
        if not token or "." not in token:
            return None
        b64, _sep, sig = token.rpartition(".")
        payload = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        expect = hmac.new(_share_secret(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        parts = payload.decode(errors="replace").split("|")
        if len(parts) != 3 or parts[0] != "train":
            return None
        _prefix, agent_id, exp = parts
        if not agent_id or not exp.isdigit() or int(exp) < time.time():
            return None
        return agent_id
    except Exception:  # noqa: BLE001 - a bad token is just "not valid"
        return None


_SHARE_EXPIRED_MSG = "This training link has expired. Ask for a fresh one."


def _resolve_share_scope(agent_id, share_token: str, public: bool = False):
    """Common share-token enforcement shared by the three training routes
    (get/generate/answer). Returns (resolved_agent_id, None) on success, or
    (None, (status, body)) when the caller should stop and return that
    response as-is.

    - share_token present + valid  -> FORCES agent_id to the token's agent
      (403 if the caller also passed a different agent_id - never silently
      swap which agent a mismatched payload trains).
    - share_token present + invalid/expired -> 401, plain-English.
    - share_token absent + public (no owner session; see server.py's
      ___public flag on unauthenticated POSTs) -> 401. A public caller must
      always carry a valid share - there is no other way in.
    - share_token absent + not public -> unchanged owner-session behaviour.
    """
    share_token = (share_token or "").strip()
    if share_token:
        share_agent = verify_training_share(share_token)
        if not share_agent:
            return None, (401, {"error": _SHARE_EXPIRED_MSG})
        if agent_id and str(agent_id) != str(share_agent):
            return None, (403, {"error": "This training link is for a different agent."})
        return share_agent, None
    if public:
        return None, (401, {"error": _SHARE_EXPIRED_MSG})
    if not agent_id:
        return None, (400, {"error": "agent_id is required"})
    return agent_id, None


def _load_training(agent_id: str) -> dict:
    default = {"cases": [], "answers": {}, "used_reply_ids": [], "readiness_history": [],
               "generating": {"status": "idle"}, "pending_merges": [],
               "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    if not _SB or not agent_id:
        return default
    try:
        rows = _SB("GET", f"{AGENTS_TABLE}?id=eq.{_training_doc_id(agent_id)}&select=doc")
        if isinstance(rows, list) and rows:
            doc = dict(rows[0].get("doc") or {})
            doc.setdefault("cases", [])
            doc.setdefault("answers", {})
            doc.setdefault("used_reply_ids", [])
            doc.setdefault("readiness_history", [])
            doc.setdefault("generating", {"status": "idle"})
            # Latency fix (2026-07-14): "remember" corrections from the
            # training-answer route no longer call merge_correction_into_
            # instructions (a gpt-5-mini call, 5-15s) inline - they queue
            # here instead, and the background retrain worker drains this
            # list first thing on every pass. See route_training_answer and
            # _training_retrain_worker.
            doc.setdefault("pending_merges", [])
            doc.setdefault("created_at", default["created_at"])
            return doc
    except Exception:  # noqa: BLE001
        pass
    return default


def _save_training(agent_id: str, doc: dict):
    if not _SB or not agent_id:
        return
    _SB("POST", f"{AGENTS_TABLE}?on_conflict=id", {"id": _training_doc_id(agent_id), "doc": doc},
       prefer="resolution=merge-duplicates,return=minimal")


def _weighted_category_targets(n: int, weights: dict | None = None,
                               negative_categories: list | None = None) -> dict:
    """Splits a batch size of `n` into per-category targets: ~80% across
    the actionable categories proportional to `weights` (largest-remainder
    rounding, so the counts always sum exactly to the actionable share),
    ~20% split evenly across `negative_categories`. Defaults to the real
    corpus weights/categories (_TRAINING_ACTIONABLE_WEIGHTS /
    _TRAINING_CLEAR_NEGATIVE_CATEGORIES) when the caller doesn't override
    them - see _synthetic_category_targets for the synthetic-scenario
    override. This only decides HOW MANY of each category to draw/invent -
    it never picks a real row or writes a scenario itself."""
    n = max(0, int(n or 0))
    weights = weights if weights is not None else _TRAINING_ACTIONABLE_WEIGHTS
    negative_categories = negative_categories if negative_categories is not None else _TRAINING_CLEAR_NEGATIVE_CATEGORIES
    n_actionable = round(n * TRAINING_ACTIONABLE_SHARE)
    n_negative = n - n_actionable
    targets = {}
    if n_actionable and weights:
        total_w = sum(weights.values()) or 1
        raw = {cat: (w / total_w) * n_actionable for cat, w in weights.items()}
        floors = {cat: int(v) for cat, v in raw.items()}
        remainder = n_actionable - sum(floors.values())
        order = sorted(raw, key=lambda c: raw[c] - floors[c], reverse=True)
        for cat in order[:remainder]:
            floors[cat] += 1
        targets.update({cat: c for cat, c in floors.items() if c})
    if n_negative and negative_categories:
        cats = negative_categories
        base, extra = divmod(n_negative, len(cats))
        for i, cat in enumerate(cats):
            c = base + (1 if i < extra else 0)
            if c:
                targets[cat] = targets.get(cat, 0) + c
    return targets


def _synthetic_category_targets(n: int) -> dict:
    """_weighted_category_targets restricted to the simple, common
    categories a SYNTHETIC scenario may represent (see the doctrine comment
    above and _SYNTHETIC_ACTIONABLE_WEIGHTS/_SYNTHETIC_NEGATIVE_CATEGORIES).
    Still 80% actionable / 20% clear-negative overall, per
    TRAINING_ACTIONABLE_SHARE."""
    return _weighted_category_targets(n, weights=_SYNTHETIC_ACTIONABLE_WEIGHTS,
                                      negative_categories=_SYNTHETIC_NEGATIVE_CATEGORIES)


def _fetch_training_candidates(category: str, exclude_ids: list, want: int,
                               allowed_campaign_ids: list | None = None) -> list:
    """Real, unused `replies` rows for one category - excludes already-used
    ids and null/short bodies. Over-fetches a small multiple of `want` so the
    caller can randomly sample real variety instead of always drawing the
    same handful of newest rows. `allowed_campaign_ids`, when given (share
    mode), restricts the pool to those campaigns only - a client training
    link must never surface a reply from a campaign outside their own agent."""
    if not _SB or want <= 0:
        return []
    if allowed_campaign_ids is not None and not allowed_campaign_ids:
        # Scoped to an agent with no campaigns: no real replies are eligible.
        return []
    try:
        pool_size = max(want * 5, 20)
        filt = (f"workspace=eq.{WORKSPACE}&category=eq.{quote(str(category), safe='')}"
                f"&order=replied_at.desc&limit={pool_size}"
                f"&select=id,smartlead_campaign_id,email,replied_at,category,reply_subject,reply_body")
        if allowed_campaign_ids is not None:
            ids_csv = ",".join(quote(str(c), safe="") for c in allowed_campaign_ids)
            filt += f"&smartlead_campaign_id=in.({ids_csv})"
        exclude_ids = list(exclude_ids or [])
        if exclude_ids:
            ids_csv = ",".join(str(i) for i in exclude_ids[-300:])
            filt += f"&id=not.in.({ids_csv})"
        rows = _SB("GET", f"{REPLIES_TABLE}?{filt}")
        if not isinstance(rows, list):
            return []
        exclude_set = {str(i) for i in exclude_ids}
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("id")) in exclude_set:
                continue
            if len(str(r.get("reply_body") or "").strip()) < 10:
                continue
            out.append(r)
        return out
    except Exception:  # noqa: BLE001
        return []


def _select_training_replies(doc: dict, batch_size: int, allowed_campaign_ids: list | None = None) -> list:
    """Weighted-real selection over the actionable + clear-negative category
    mix (see _weighted_category_targets). If a category legitimately runs
    dry (e.g. Contact Forward is a small slice of the corpus), a top-up pass
    spreads the shortfall across whichever categories still have real,
    unused rows rather than handing back a short batch. `allowed_campaign_ids`
    is forwarded to every fetch (share mode only - see _fetch_training_candidates)."""
    used = list(doc.get("used_reply_ids") or [])
    targets = _weighted_category_targets(batch_size)
    selected = []
    seen_ids = set()

    def take(cat, want):
        if want <= 0:
            return 0
        exclude = used + list(seen_ids)
        candidates = _fetch_training_candidates(cat, exclude, want, allowed_campaign_ids)
        random.shuffle(candidates)
        got = 0
        for c in candidates:
            if got >= want:
                break
            cid = str(c.get("id"))
            if cid in seen_ids:
                continue
            selected.append(c)
            seen_ids.add(cid)
            got += 1
        return got

    for cat, want in targets.items():
        take(cat, want)

    shortfall = batch_size - len(selected)
    if shortfall > 0:
        all_cats = list(_TRAINING_ACTIONABLE_WEIGHTS.keys()) + _TRAINING_CLEAR_NEGATIVE_CATEGORIES
        attempts = 0
        while shortfall > 0 and attempts < len(all_cats) * 2:
            progressed = False
            for cat in all_cats:
                if shortfall <= 0:
                    break
                got = take(cat, 1)
                if got:
                    shortfall -= got
                    progressed = True
            attempts += 1
            if not progressed:
                break

    return selected


def _fetch_original_outreach(campaign_id, email: str) -> dict:
    """The lead's original outbound (email_seq_number=1, same email+
    campaign) - the offer their reply is answering. Returns {} when none is
    recoverable (blank-canvas case, per spec - never skipped)."""
    if not _SB or not campaign_id or not email:
        return {}
    try:
        rows = _SB("GET", f"{SENT_MESSAGES_TABLE}?smartlead_campaign_id=eq.{campaign_id}&email=eq.{email}"
                          f"&email_seq_number=eq.1&select=subject,body,sent_at&limit=1")
        if isinstance(rows, list) and rows:
            r = rows[0]
            return {"subject": r.get("subject") or "", "body": r.get("body") or "", "sent_at": r.get("sent_at")}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _fetch_human_answer_history(campaign_id, email: str, replied_at: str) -> dict:
    """The earliest human-sent reply (is_manual_reply=true) sent AFTER this
    inbound's replied_at, same email+campaign - what a human actually said
    in response, for the trainer to compare our decision against. Returns
    {} when no human answer exists (blank-canvas)."""
    if not _SB or not campaign_id or not email or not replied_at:
        return {}
    try:
        rows = _SB("GET", f"{SENT_MESSAGES_TABLE}?smartlead_campaign_id=eq.{campaign_id}&email=eq.{email}"
                          f"&is_manual_reply=eq.true&sent_at=gt.{replied_at}&order=sent_at.asc&limit=1"
                          f"&select=subject,body,sent_at")
        if isinstance(rows, list) and rows:
            r = rows[0]
            return {"subject": r.get("subject") or "", "body": r.get("body") or "", "sent_at": r.get("sent_at")}
    except Exception:  # noqa: BLE001
        pass
    return {}


# ── synthetic scenario invention (shortfall top-up, see the doctrine
# comment above _TRAINING_ID_PREFIX) ────────────────────────────────────────

def _fetch_reply_tone_sample(allowed_campaign_ids: list | None = None, limit: int = 12) -> list:
    """A small sample of this agent's REAL archived replies, for TONE AND
    SHAPE reference only when inventing synthetic scenarios - deliberately
    IGNORES used_reply_ids (an already-used reply is perfectly fine to show
    the model what a real lead here actually sounds like; this is not
    selecting a case, just describing a voice). Adapts
    _fetch_training_candidates's query shape but pools across every
    category rather than one at a time. `allowed_campaign_ids`, when given
    (share mode), scopes the sample exactly like every other training
    query. Returns [] (never raises) when nothing is found - callers treat
    an empty sample as "this agent has zero replies anywhere" and fall back
    to brain/campaign context instead (see _invent_training_scenarios)."""
    if not _SB:
        return []
    if allowed_campaign_ids is not None and not allowed_campaign_ids:
        # Scoped to an agent with no campaigns: nothing is eligible.
        return []
    try:
        pool_size = max(limit * 4, 40)
        filt = (f"workspace=eq.{WORKSPACE}&order=replied_at.desc&limit={pool_size}"
                f"&select=id,smartlead_campaign_id,email,replied_at,category,reply_subject,reply_body")
        if allowed_campaign_ids is not None:
            ids_csv = ",".join(quote(str(c), safe="") for c in allowed_campaign_ids)
            filt += f"&smartlead_campaign_id=in.({ids_csv})"
        rows = _SB("GET", f"{REPLIES_TABLE}?{filt}")
        if not isinstance(rows, list):
            return []
        candidates = [r for r in rows if isinstance(r, dict)
                     and len(str(r.get("reply_body") or "").strip()) >= 10]
        random.shuffle(candidates)
        return candidates[:limit]
    except Exception:  # noqa: BLE001
        return []


def _fetch_agent_outreach_sample(campaign_ids: list, limit: int = 3) -> list:
    """A few real seq-1 outbound emails (subject+body) across this agent's
    own campaigns - the zero-replies fallback context so the model can
    invent a plausible inbound reply to what this agent's outreach actually
    says, instead of guessing blind. Never invents or returns an agent-side
    fact itself; this is just showing the model the pitch a lead would be
    reacting to."""
    campaign_ids = [str(c) for c in (campaign_ids or []) if c]
    if not _SB or not campaign_ids:
        return []
    try:
        ids_csv = ",".join(quote(c, safe="") for c in campaign_ids)
        rows = _SB("GET", f"{SENT_MESSAGES_TABLE}?smartlead_campaign_id=in.({ids_csv})"
                          f"&email_seq_number=eq.1&select=subject,body&limit={limit}")
        if isinstance(rows, list):
            return [{"subject": r.get("subject") or "", "body": r.get("body") or ""}
                   for r in rows if isinstance(r, dict) and str(r.get("body") or "").strip()]
    except Exception:  # noqa: BLE001
        pass
    return []


TRAINING_SCENARIO_ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "lead_first_name": {"type": "string"}, "lead_company": {"type": "string"},
        "subject": {"type": "string"}, "body": {"type": "string"},
    },
    "required": ["lead_first_name", "lead_company", "subject", "body"],
}

TRAINING_SCENARIO_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"scenarios": {"type": "array", "items": TRAINING_SCENARIO_ITEM_SCHEMA}},
    "required": ["scenarios"],
}

TRAINING_SCENARIO_SYSTEM = """You invent PRACTICE scenarios for training an AI appointment-setter agent. Each scenario is a made-up inbound reply from a made-up lead, used only to rehearse how the agent classifies, decides, and drafts a response - it is never sent to anyone.

LEAD-SIDE-ONLY LAW (hard rule): you may invent the lead's first name, their company, and the wording and subject of their inbound reply ONLY. You must NEVER state, as a fact, any agent-side detail - no price, no discount, no specific resource, no link, no availability window, no promised date. The lead may ASK about pricing, a resource, or availability in their own wording (that is normal lead-side content and is fine); they must never assert one, as if they already know it, in their own reply.

You are given scenario_plan, an ordered list of category labels. Produce exactly one scenario per position in that list, in the same order, so scenario i must read like a reply in category scenario_plan[i]. The categories mean:
- Interested: the lead is engaged and wants to move forward or learn more.
- Information Request: the lead is asking a question before they decide (pricing, how it works, a resource, timing).
- Meeting Request: the lead is directly asking to get on a call or find a time.
- Not Interested: the lead is politely declining, or saying now is not a good time.
- Out Of Office: an automated or lead-written away message (on leave, back on a date, or forward to a colleague instead).

reference_replies, when given, are REAL replies this exact agent has actually received before (for tone and shape reference only, never to copy) - match how real leads at this ICP actually write: length, formality, punctuation habits, how a sign-off looks. Never reuse a name, company, or sentence from reference_replies verbatim; invent new ones with a similar feel.

fallback_context, when given instead (no reference replies exist yet), is the agent's own brain plus a sample of the real outreach it sends - use it only to understand what a lead would plausibly be reacting to. Never turn any instructions/pricing/resource/voice_examples content into something the LEAD states as fact in their own reply.

avoid_duplicating lists short gists (category plus the start of the inbound text) of scenarios already waiting to be answered - do not repeat any of these angles, names, or companies.

Output STRICT JSON: {"scenarios": [{"lead_first_name": "...", "lead_company": "...", "subject": "...", "body": "..."}, ...]}, one object per scenario_plan position, in the same order. subject and body should read like a short, real inbound email reply - plain text, a couple of sentences, the way a busy person actually replies, never polished marketing copy."""


def _invent_training_scenarios(agent: dict, doc: dict, count: int, allowed_campaign_ids: list | None = None,
                               reference_sample: list | None = None) -> list:
    """ONE gpt-5-mini call inventing `count` lead-side-only synthetic
    training scenarios (see the doctrine comment above), used only to top
    up a batch the real replies table can't fill (see
    _training_generate_worker's shortfall handling). Returns a list of
    {category, lead_first_name, lead_company, subject, body} dicts, in the
    exact category mix _synthetic_category_targets computed for `count` -
    the model never chooses the mix, only writes the lead-side content for
    the category slot it is given.

    `reference_sample`, when given, is a pre-fetched _fetch_reply_tone_
    sample() result (the worker fetches it once to also decide the
    shortfall/zero_replies trigger label - see there); when None, this
    fetches its own. An empty sample means this agent has zero real
    replies anywhere reachable in this scope, so the prompt falls back to
    the agent's own brain, extra instructions, pricing notes, resources,
    voice examples, and a sample of its real campaign outreach instead.

    Returns [] on any failure (missing API key, a bad/empty count, the
    OpenAI call erroring, or unparsable JSON) - the caller degrades to
    whatever real cases it already has and never raises."""
    count = max(0, int(count or 0))
    if count <= 0:
        return []
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        return []

    targets = _synthetic_category_targets(count)
    ordered_cats = list(_SYNTHETIC_ACTIONABLE_WEIGHTS.keys()) + _SYNTHETIC_NEGATIVE_CATEGORIES
    scenario_plan = []
    for cat in ordered_cats:
        scenario_plan.extend([cat] * targets.get(cat, 0))
    # Largest-remainder rounding always sums exactly to `count`, but pad
    # defensively (falling back to the last negative category) so a future
    # weighting change can never silently short the plan below `count`.
    fallback_cat = (_SYNTHETIC_NEGATIVE_CATEGORIES or ordered_cats or ["Interested"])[-1]
    while len(scenario_plan) < count:
        scenario_plan.append(fallback_cat)
    scenario_plan = scenario_plan[:count]

    reference = reference_sample if reference_sample is not None else \
        _fetch_reply_tone_sample(allowed_campaign_ids=allowed_campaign_ids)
    payload = {"scenario_plan": scenario_plan}
    if reference:
        payload["reference_replies"] = [
            {"category": r.get("category") or "", "subject": clean_body(r.get("reply_subject") or "")[:200],
             "body": clean_body(r.get("reply_body") or "")[:600]}
            for r in reference
        ]
    else:
        campaign_ids = allowed_campaign_ids if allowed_campaign_ids is not None else (agent.get("campaign_ids") or [])
        payload["fallback_context"] = {
            "instructions": _agent_instructions(agent)[:3000],
            "extra_instructions": str((agent or {}).get("extra_instructions") or "")[:1500],
            "pricing_notes": str((agent or {}).get("pricing_notes") or "")[:1500],
            "resources": (agent or {}).get("resources") or (agent or {}).get("resource_link") or "",
            "voice_examples": list((agent or {}).get("voice_examples") or [])[:5],
            "sample_outreach": _fetch_agent_outreach_sample(campaign_ids, limit=3),
        }

    existing_cases = list((doc or {}).get("cases") or [])
    answers = dict((doc or {}).get("answers") or {})
    unanswered_gists = []
    for c in existing_cases:
        if _is_case_answered(c.get("id"), answers):
            continue
        body_text = ((c.get("inbound") or {}).get("body") or "").strip()
        unanswered_gists.append(f"{c.get('category') or ''}: {body_text[:80]}")
    if unanswered_gists:
        payload["avoid_duplicating"] = unanswered_gists[:60]

    try:
        r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                 {"Authorization": f"Bearer {key}"},
                 {"model": OPENAI_MODEL,
                  "messages": [{"role": "system", "content": TRAINING_SCENARIO_SYSTEM},
                              {"role": "user", "content": json.dumps(payload)}],
                  "response_format": {"type": "json_schema", "json_schema": {
                      "name": "setter_training_scenarios", "strict": True,
                      "schema": TRAINING_SCENARIO_SCHEMA}}})
        if not isinstance(r, dict) or r.get("error"):
            return []
        data = json.loads(r["choices"][0]["message"]["content"])
        raw_scenarios = data.get("scenarios") or []
        if not isinstance(raw_scenarios, list):
            return []
    except Exception:  # noqa: BLE001 - inventing a scenario must never crash generation
        return []

    scenarios = []
    for i, cat in enumerate(scenario_plan):
        item = raw_scenarios[i] if i < len(raw_scenarios) else {}
        if not isinstance(item, dict):
            item = {}
        body = str(item.get("body") or "").strip()
        if not body:
            continue
        scenarios.append({
            "category": cat,
            "lead_first_name": str(item.get("lead_first_name") or "").strip(),
            "lead_company": str(item.get("lead_company") or "").strip(),
            "subject": str(item.get("subject") or "").strip(),
            "body": body,
        })
    return scenarios


def _build_case_core(*, subject: str, body: str, raw_body: str, category, campaign_id, email_domain: str,
                     original_outreach: dict, human_answer_history: dict, agent: dict, eff_settings: dict,
                     avail: list, slot_status0: str, now, mem_digest: str, idx: int, reply_id,
                     synthetic: bool) -> dict:
    """Shared core of _build_training_case (real archived replies) and
    _build_synthetic_training_case (invented lead-side-only scenarios, see
    the doctrine comment above _TRAINING_ID_PREFIX): runs the exact
    classify -> decide -> draft_reply -> lint_draft pipeline pieces and
    shapes the resulting case dict. The two callers differ only in WHERE
    subject/body/category/campaign_id/original_outreach/human_answer_
    history come from - a real archived reply row vs an invented scenario -
    everything downstream of that, including the live brain and memory, is
    identical, so a real and a synthetic case are graded by the exact same
    pipeline. Costs at most 2 gpt-5-mini calls (one classify, one draft - a
    clear-negative reply skips the draft call entirely). Never raises - a
    bad input just yields no case (caller's job to catch and return None)."""
    first_outbound = original_outreach.get("body") or ""
    comp = _company_hints(email_domain) if email_domain else {}
    hints = {"phone": _extract_phone(body), "tld": ".".join(email_domain.split(".")[-2:]) if email_domain else "",
             "body": body, "country": comp.get("country"), "state": comp.get("state"), "city": comp.get("city")}

    cls = classify({"subject": subject, "body": body, "first_outbound": first_outbound,
                    "last_outbound": "", "email_domain": email_domain}, agent, owner_hints=mem_digest)

    tz, tz_confident = resolve_timezone(hints, cls)

    primary = cls.get("primary_intent")
    try:
        confidence = float(cls.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    is_clear_neg = primary in CLEAR_NEGATIVE_INTENTS and confidence >= 0.8

    slots, slot_status = [], "not_configured"
    if not is_clear_neg:
        if tz:
            slot_status = slot_status0
            if slot_status == "ok":
                eff_lead = dict(eff_settings)
                eff_lead["_lead"] = {"first_name": "", "last_name": "", "email": ""}
                slots = pick_slots(avail, tz, eff_lead, now)
                if not slots:
                    slot_status = "none_available"
        else:
            slot_status = "tz_unknown"

    # Calendly fallback (owner ruling 2026-07-14) - see decide() gate 7
    # and lint_draft().
    slots_fallback = slot_status != "ok"
    needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

    draft_html = None
    lint_ok, lint_reason = False, "No draft was produced."
    if not is_clear_neg:
        try:
            # No hydration, so no real sender name to draw on - resolves to
            # the agent's own configured identity via _sender_first_for, same
            # as every other non-live surface (owner bug report 2026-07-14:
            # this used to hardcode "Bjion" regardless of which agent it was).
            d = draft_reply({"first_name": "", "subject": subject, "body": body,
                             "first_outbound": first_outbound}, agent, cls, slots, slot_status,
                            sender_first=_sender_first_for(agent), regen_feedback=mem_digest)
            draft_html = d.get("html")
            if draft_html:
                # Second sweep (owner brief 2026-07-14) - runs BEFORE
                # lint_draft below, so lint checks the final text. Shared by
                # both real (_build_training_case) and synthetic
                # (_build_synthetic_training_case) cases.
                draft_html, _proofread_changed = proofread_draft(draft_html)
            lint_ok, lint_reason = lint_draft(draft_html, {
                "subject": d.get("subject"), "first_name": "",
                "needs_resource_link": "send_resource" in (cls.get("all_intents") or []),
                "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
                "slot_labels": [s.get("label") for s in slots],
                "instructions": _agent_instructions(agent),
                "booking_link": _booking_link(agent), "thread_text": body,
                "slots_fallback": slots_fallback, "needs_availability_ask": needs_availability_ask,
            })
        except Exception:  # noqa: BLE001
            draft_html = None
            lint_ok, lint_reason = False, "No draft was produced."

    ctx = {
        "red_flag_hits": lexicon_hits(body), "category": category,
        "first_touch": True, "slot_status": slot_status, "slots_fallback": slots_fallback,
        "timezone": tz,
        "tz_confident": tz_confident, "lint_ok": lint_ok, "lint_reason": lint_reason,
        "body_len": len(body), "hydrated": True, "answered_since_reply": False,
        "autopilot_enabled": True,
        "same_day_ask": bool(_SAME_DAY_RE.search(_strip_quoted(body))),
        "first_outbound_present": bool(str(first_outbound or "").strip()),
        "needs_availability_ask": needs_availability_ask,
    }
    decision, reason = decide(cls, agent, ctx)

    case = {
        "id": f"case-{idx:04d}", "reply_id": reply_id, "campaign_id": campaign_id,
        "category": category,
        "inbound": {"subject": subject, "body": body, "raw_body": raw_body},
        "original_outreach": original_outreach, "human_answer_history": human_answer_history,
        "classification": cls, "decision": decision, "decision_reason": reason,
        "draft_html": draft_html,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if synthetic:
        case["synthetic"] = True
    return case


def _build_training_case(reply_row: dict, agent: dict, eff_settings: dict, avail: list, slot_status0: str,
                         now, mem_digest: str, idx: int) -> dict:
    """Runs the real classify -> decide -> draft_reply pipeline pieces over
    one real archived reply - mirrors generate_grading.py's approach exactly
    (decisions computed as-if the master switch and autopilot were ON, real
    Calendly availability resolved once per batch, no live Smartlead call).
    The inbound text is the real reply verbatim; nothing here invents a
    scenario. See _build_case_core for the shared pipeline. Never raises -
    a bad reply just yields no case."""
    try:
        reply_id = reply_row.get("id")
        campaign_id = reply_row.get("smartlead_campaign_id")
        email = (reply_row.get("email") or "").strip().lower()
        category = reply_row.get("category")
        raw_body = reply_row.get("reply_body") or ""
        body = clean_body(raw_body)
        subject = reply_row.get("reply_subject") or ""
        replied_at = reply_row.get("replied_at")

        outreach = _fetch_original_outreach(campaign_id, email)
        human_answer = _fetch_human_answer_history(campaign_id, email, replied_at)
        domain = email.split("@", 1)[1] if "@" in email else ""

        return _build_case_core(subject=subject, body=body, raw_body=raw_body, category=category,
                                campaign_id=campaign_id, email_domain=domain,
                                original_outreach=outreach, human_answer_history=human_answer,
                                agent=agent, eff_settings=eff_settings, avail=avail, slot_status0=slot_status0,
                                now=now, mem_digest=mem_digest, idx=idx, reply_id=reply_id, synthetic=False)
    except Exception:  # noqa: BLE001 - a single bad reply must never abort the whole batch
        return None


def _build_synthetic_training_case(scenario: dict, agent: dict, eff_settings: dict, avail: list, slot_status0: str,
                                   now, mem_digest: str, idx: int, campaign_id=None) -> dict:
    """Turns one invented lead-side scenario (see _invent_training_scenarios)
    into a full training case through the EXACT SAME classify -> decide ->
    draft_reply -> lint_draft pipeline as a real archived reply
    (_build_case_core) - so its decision and draft are graded by the live
    brain and memory exactly like a real case. Only the inbound text is
    made up, and only on the lead's side (see the doctrine comment above).
    reply_id is always None (a synthetic case never mints a fake one);
    campaign_id is a real campaign of this agent when the caller has one to
    give, else None. Never raises - a bad scenario just yields no case,
    same discipline as _build_training_case."""
    try:
        category = scenario.get("category")
        raw_body = str(scenario.get("body") or "")
        body = clean_body(raw_body)
        subject = str(scenario.get("subject") or "")

        return _build_case_core(subject=subject, body=body, raw_body=raw_body, category=category,
                                campaign_id=campaign_id, email_domain="",
                                original_outreach={}, human_answer_history={},
                                agent=agent, eff_settings=eff_settings, avail=avail, slot_status0=slot_status0,
                                now=now, mem_digest=mem_digest, idx=idx, reply_id=None, synthetic=True)
    except Exception:  # noqa: BLE001 - a single bad scenario must never abort the whole batch
        return None


def compute_readiness(doc: dict) -> dict:
    """Pure, transparent 0-100 readiness score over the trainer's answers so
    far (doc['answers'], keyed by case_id, each {decision_ok, reply_ok, note,
    at}). Weighted toward RECENT answers (a ~15-answer exponential half
    life) so a correction actually moves the score, and scaled down by how
    few answers exist yet (coverage) so a handful of lucky answers can't
    read as 'ready'."""
    doc = doc or {}
    answers = dict(doc.get("answers") or {})
    items = sorted(answers.items(), key=lambda kv: (kv[1] or {}).get("at") or "")
    n = len(items)
    if n == 0:
        return {"score": 0, "decision_component": 0.0, "reply_component": 0.0, "coverage": 0.0,
                "n_answers": 0, "explanation": "No ratings yet. Rate a few training scenarios "
                                               "to start building a readiness score."}

    decision_num = decision_den = 0.0
    reply_num = reply_den = 0.0
    for age_rank, (_case_id, ans) in enumerate(reversed(items)):  # age_rank 0 = most recent
        w = 0.5 ** (age_rank / 15)
        decision_ok = (ans or {}).get("decision_ok")
        if decision_ok is not None:
            decision_den += w
            if decision_ok:
                decision_num += w
        reply_ok = (ans or {}).get("reply_ok")
        if reply_ok is not None:
            reply_den += w
            if reply_ok:
                reply_num += w

    decision_component = (decision_num / decision_den) if decision_den else 0.0
    reply_component = (reply_num / reply_den) if reply_den else decision_component
    raw = 100 * (0.6 * decision_component + 0.4 * reply_component)
    coverage = min(1.0, n / 20)
    score = round(raw * coverage)

    explanation = (
        f"Across your {n} rating{'s' if n != 1 else ''} (recent ones count most), you agreed with the "
        f"agent's answer-or-leave-it decision {round(decision_component * 100)}% of the time and rated "
        f"its drafts good {round(reply_component * 100)}% of the time. Coverage is {n} of 20 ratings, "
        f"so the readiness score is {score}/100 - keep rating and it climbs."
    )
    return {"score": score, "decision_component": round(decision_component, 4),
            "reply_component": round(reply_component, 4), "coverage": round(coverage, 4),
            "n_answers": n, "explanation": explanation}


def route_training_get(params):
    try:
        agent_id = _qp(params, "agent_id", "")
        share_token = _qp(params, "share", "")
        agent_id, err = _resolve_share_scope(agent_id, share_token)
        if err:
            return err
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        doc = _load_training(agent_id)
        answers = dict(doc.get("answers") or {})
        cases = list(doc.get("cases") or [])
        unanswered = [c for c in cases if not _is_case_answered(c.get("id"), answers)]
        answered = [c for c in cases if _is_case_answered(c.get("id"), answers)]
        # Minimal, name+text-only memory list (never the full agent doc) - the
        # training page's "what this agent has remembered" viewer reads it
        # from here rather than /api/setter/agents, which a share token must
        # never be able to reach.
        memory = [{"text": m.get("text") or "", "at": m.get("at") or ""}
                 for m in (agent.get("memory") or []) if isinstance(m, dict)]
        # Feature A/9: the single living manual's own audit trail - every
        # merge_correction_into_instructions call, newest last, minimal shape
        # (never the full agent doc, same discipline as `memory` above - a
        # share token must never see anything but note/how/date). Read in
        # both owner and share mode; share mode is read-only anyway (no
        # "remove" affordance is ever wired up for it in the frontend).
        instruction_edits = [
            {"note": e.get("note") or "", "how": e.get("how") or "", "at": e.get("at") or ""}
            for e in (agent.get("instruction_edits") or []) if isinstance(e, dict)
        ]

        generating = doc.get("generating") or {"status": "idle"}
        # Self-heal a stale "running" left behind by a process restart
        # mid-batch (the in-memory thread and lock die with the process) -
        # mirrors route_grading_get's relearn self-heal. A batch of up to
        # TRAINING_BATCH_MAX cases never legitimately runs past 10 minutes.
        # Healed in the RESPONSE only, same as relearn - never persisted
        # here, since the next real generate() call overwrites it anyway.
        if generating.get("status") == "running" and not _get_training_gen_lock(agent_id).locked():
            try:
                started = _parse_iso(generating.get("started_at"))
                age = (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds()
                if age > 600:
                    generating = {**generating, "status": "idle", "stale_recovered": True}
            except (TypeError, ValueError):
                generating = {**generating, "status": "idle", "stale_recovered": True}

        return 200, {
            "cases": unanswered + answered, "answers": answers,
            "readiness": compute_readiness(doc),
            "used_count": len(doc.get("used_reply_ids") or []),
            "agent_name": agent.get("name") or "",
            "agent_memory": memory,
            "instruction_edits": instruction_edits,
            "generating": generating,
            # Latency fix (2026-07-14): "remember" notes queue here instead
            # of merging inline (see route_training_answer /
            # _training_retrain_worker). Surfaced so a note waiting on a
            # dead/self-healed worker (see the stale-running heal just
            # above) is never invisible to the trainer.
            "pending_merges": len(doc.get("pending_merges") or []),
        }
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_training_generate(payload):
    """Validates synchronously (share scope, agent existence, unanswered
    cap, share-mode campaign check, batch_size clamp) so callers still get
    an instant 4xx on a bad request, then kicks the actual generation work
    off in a background daemon thread and returns immediately.

    Why: a full batch (Supabase pulls + classify() + draft_reply() per
    case, even pooled) can run past Render's edge-proxy timeout (~100s),
    which returns a 502 to the browser while the server thread keeps going
    and finishes the save anyway - the trainer sees an error though cases
    actually landed. The page polls GET /api/setter/training until the new
    batch shows up (see setter-train.html generateMore()). Mirrors the
    RELEARN background-thread precedent (_kick_off_relearn /
    _GRADING_RELEARN_LOCK), except the lock is per-agent - two different
    agents' batches never conflict."""
    try:
        payload = payload or {}
        agent_id = payload.get("agent_id")
        share_token = payload.get("share") or ""
        public = bool(payload.get("___public"))
        agent_id, err = _resolve_share_scope(agent_id, share_token, public)
        if err:
            return err
        is_share_mode = bool(share_token)
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        try:
            batch_size = int(payload.get("batch_size") or TRAINING_BATCH_DEFAULT)
        except (TypeError, ValueError):
            batch_size = TRAINING_BATCH_DEFAULT
        batch_size = max(1, min(batch_size, TRAINING_BATCH_MAX))

        # Training always draws real replies ONLY from the agent's own
        # campaigns (owner ruling 2026-07-14: an agent must never train on
        # campaigns it isn't assigned to). An unassigned agent still trains -
        # real selection comes back empty and the synthetic Practice top-up
        # fills the batch. Share links additionally require an assignment so
        # a client link is never minted for an unconfigured agent.
        allowed_campaign_ids = [str(c) for c in (agent.get("campaign_ids") or [])]
        if is_share_mode and not allowed_campaign_ids:
            return 400, {"error": "This agent has no campaigns to draw replies from yet."}

        doc = _load_training(agent_id)
        existing_cases = list(doc.get("cases") or [])
        answers = dict(doc.get("answers") or {})
        unanswered = [c for c in existing_cases if not _is_case_answered(c.get("id"), answers)]
        max_unanswered = TRAINING_MAX_UNANSWERED_SHARE if is_share_mode else TRAINING_MAX_UNANSWERED
        if len(unanswered) > max_unanswered:
            return 400, {"error": f"There are already {len(unanswered)} unanswered scenarios waiting - "
                                  "answer some before generating more."}

        lock = _get_training_gen_lock(agent_id)
        if not lock.acquire(blocking=False):
            # Already generating for this agent - idempotent no-op, the
            # page just keeps polling GET /api/setter/training.
            return 200, {"ok": True, "status": "already_running"}

        try:
            marker_doc = _load_training(agent_id)
            marker_doc["generating"] = {
                "status": "running",
                "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                "batch_size": batch_size,
            }
            _save_training(agent_id, marker_doc)
        except Exception:  # noqa: BLE001 - never leave the lock held if writing the marker itself blows up
            lock.release()
            raise

        thread = threading.Thread(
            target=_training_generate_threadmain,
            args=(agent_id, agent, allowed_campaign_ids, batch_size, lock, is_share_mode),
            daemon=True,
        )
        _TRAINING_GEN_THREADS[agent_id] = thread
        thread.start()
        return 200, {"ok": True, "status": "started"}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _training_generate_threadmain(agent_id, agent, allowed_campaign_ids, batch_size, lock, is_share_mode=False):
    try:
        _training_generate_worker(agent_id, agent, allowed_campaign_ids, batch_size, is_share_mode=is_share_mode)
        # A "remember" answer may have queued a retrain pass WHILE this
        # generate batch held the lock (see _kick_off_training_retrain) -
        # run it now, still holding the same lock, so the two kinds of work
        # never overlap and no queued correction is silently dropped.
        _maybe_run_queued_retrain(agent_id)
    finally:
        try:
            lock.release()
        except RuntimeError:  # noqa: BLE001 - lock wasn't held (shouldn't happen); never crash a bg thread
            pass


def _finish_training_generation(agent_id: str, status: str, error: str | None = None, added: int | None = None):
    """Writes only doc["generating"] - reloads the doc first so this marker
    write (a failure, or the initial-selection-empty case) never clobbers an
    answer that landed in Supabase while the batch was building. Used for
    every outcome that does NOT also need to append cases/used_reply_ids;
    the success path merges those itself (see _training_generate_worker)
    since it needs the same fresh-reload-then-append protection."""
    try:
        doc = _load_training(agent_id)
        marker = {"status": status, "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
        if error is not None:
            marker["error"] = error
        if added is not None:
            marker["added"] = added
        # A "remember" answer may have set retrain_queued on the CURRENT
        # generating marker while this batch was building (see
        # _kick_off_training_retrain) - carry it forward so
        # _maybe_run_queued_retrain (checked right after this worker returns)
        # still sees it, even when the batch itself failed or found nothing.
        if (doc.get("generating") or {}).get("retrain_queued"):
            marker["retrain_queued"] = True
        doc["generating"] = marker
        _save_training(agent_id, doc)
    except Exception:  # noqa: BLE001 - never raise out of a background thread
        pass


def _log_synthetic_usage(agent_id: str, count: int, trigger: str, is_share_mode: bool):
    """Best-effort provider_usage row for a generation run that invented one
    or more synthetic scenarios (never for a run that only used real
    replies) - mirrors server.py's _meter_verify_calls idiom exactly, over
    the same sb() REST helper this module already uses via _SB. Never
    allowed to fail generation. Table columns: id, provider, source_id,
    credits, endpoint, called_at (called_at defaults server-side).
    endpoint is "<trigger>:<owner|share>", e.g. "shortfall:owner" or
    "zero_replies:share".

    lilly-data query example:
    SELECT source_id, SUM(credits) FROM provider_usage
    WHERE provider = 'setter_synthetic' AND called_at > now() - interval '7 days'
    GROUP BY source_id;"""
    if not _SB or not count:
        return
    try:
        _SB("POST", "provider_usage",
           {"provider": "setter_synthetic", "source_id": str(agent_id or ""),
            "credits": int(count), "endpoint": f"{trigger or 'shortfall'}:{'share' if is_share_mode else 'owner'}"})
    except Exception:  # noqa: BLE001
        pass


def _training_generate_worker(agent_id, agent, allowed_campaign_ids, batch_size, is_share_mode=False):
    """The real generation work - runs off-request on a daemon thread and
    its own final save RE-LOADS the doc first (lost-update protection: an
    answer may have landed in Supabase while this batch was being built,
    and a save from a doc snapshot captured at the top of this function
    would silently discard it).

    Shortfall top-up (see the doctrine comment above _TRAINING_ID_PREFIX):
    when _select_training_replies can't fill the requested batch_size from
    real replies, the remainder is invented as synthetic, lead-side-only
    scenarios via _invent_training_scenarios and built through the exact
    same pipeline as a real case. Synthetic cases NEVER touch
    used_reply_ids and never mint a fake reply_id - only the real replies
    selected above ever do that."""
    try:
        doc = _load_training(agent_id)
        existing_cases = list(doc.get("cases") or [])
        replies = _select_training_replies(doc, batch_size, allowed_campaign_ids=allowed_campaign_ids)

        shortfall = batch_size - len(replies)
        scenarios = []
        synthetic_trigger = None
        if shortfall > 0:
            # A pre-fetched, unscoped-by-used tone sample both feeds the
            # invention prompt AND tells us whether this agent has real
            # replies anywhere reachable in this scope - "zero_replies"
            # only when that sample comes back genuinely empty, "shortfall"
            # whenever some real replies exist (this batch or the wider
            # corpus) but not enough to fill it.
            reference_sample = _fetch_reply_tone_sample(allowed_campaign_ids=allowed_campaign_ids)
            synthetic_trigger = "shortfall" if (replies or reference_sample) else "zero_replies"
            try:
                scenarios = _invent_training_scenarios(agent, doc, shortfall,
                                                       allowed_campaign_ids=allowed_campaign_ids,
                                                       reference_sample=reference_sample)
            except Exception as e:  # noqa: BLE001 - inventing scenarios must never crash the worker
                if _LOG:
                    try:
                        _LOG("/api/setter/training/generate:invent_failed",
                            {"agent_id": agent_id, "error": str(e)[:200]}, actor="system")
                    except Exception:  # noqa: BLE001
                        pass
                scenarios = []

        if not replies and not scenarios:
            _finish_training_generation(agent_id, "failed",
                error="No new real replies were available to build scenarios from.")
            return

        # Force-on, same as generate_grading.py: the training question is
        # "how would this agent have handled this", not "is autopilot on
        # right now" - the master switch and mode are simulated ON purely
        # for this generation pass. No send path exists anywhere here.
        train_agent = {**agent, "mode": "autopilot", "enabled": True}
        # Same digest/rules a live pass and a retrain pass get, so a fresh
        # batch of scenarios is graded with the owner's newest teaching too
        # (owner brief 2026-07-14): LATEST OWNER RULES leads, then this
        # training doc's own session digest (corrections AND confirmed-
        # exemplar confirmations - see _training_session_feedback_digest),
        # then the standing agent memory digest.
        session_digest = _training_session_feedback_digest(doc)
        mem_digest = "\n\n".join([x for x in (session_digest, _agent_memory_digest(train_agent)) if x])
        mem_digest = _prefix_latest_rules(_latest_owner_rules(train_agent, doc), mem_digest)

        settings = _load_settings()
        now = _dt.datetime.now(_dt.timezone.utc)
        eff = dict(settings)
        eff["_agent"] = train_agent
        slot_status0, avail, _serr = get_calendly_availability(train_agent, eff, now)

        # Cases are independent - each one is a self-contained pull (two
        # Supabase context fetches) + classify() + draft_reply() over its
        # own reply row, touching no shared mutable state (workers only read
        # module globals set once at configure() time: _SB, _HTTP, _KEYS).
        # Running them on a small thread pool turns a batch of N sequential
        # gpt-5-mini round trips into roughly one round trip's worth of wall
        # time. Selection order is preserved by writing each result into a
        # pre-sized list at its own index rather than trusting completion
        # order.
        start_idx = len(existing_cases)
        results: list = [None] * len(replies)
        if replies:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(replies))) as pool:
                future_to_idx = {
                    pool.submit(_build_training_case, r, train_agent, eff, avail, slot_status0, now,
                               mem_digest, start_idx + i): i
                    for i, r in enumerate(replies)
                }
                for fut in concurrent.futures.as_completed(future_to_idx):
                    i = future_to_idx[fut]
                    try:
                        results[i] = fut.result()
                    except Exception as e:  # noqa: BLE001 - one bad case must never sink the batch
                        if _LOG:
                            try:
                                _LOG("/api/setter/training/generate:case_failed",
                                    {"reply_id": replies[i].get("id"), "error": str(e)[:200]}, actor="system")
                            except Exception:  # noqa: BLE001
                                pass
                        results[i] = None

        new_cases = [c for c in results if c]

        # Synthetic top-up cases, built through the exact same pipeline -
        # appended AFTER the real cases so case-id numbering stays
        # contiguous with start_idx and every answer still keys correctly.
        agent_campaign_ids = agent.get("campaign_ids") or []
        synthetic_campaign_id = agent_campaign_ids[0] if agent_campaign_ids else None
        synth_start = start_idx + len(new_cases)
        synthetic_results: list = [None] * len(scenarios)
        if scenarios:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(scenarios))) as pool:
                future_to_idx = {
                    pool.submit(_build_synthetic_training_case, s, train_agent, eff, avail, slot_status0, now,
                               mem_digest, synth_start + i, campaign_id=synthetic_campaign_id): i
                    for i, s in enumerate(scenarios)
                }
                for fut in concurrent.futures.as_completed(future_to_idx):
                    i = future_to_idx[fut]
                    try:
                        synthetic_results[i] = fut.result()
                    except Exception as e:  # noqa: BLE001 - one bad scenario must never sink the batch
                        if _LOG:
                            try:
                                _LOG("/api/setter/training/generate:synthetic_case_failed",
                                    {"agent_id": agent_id, "error": str(e)[:200]}, actor="system")
                            except Exception:  # noqa: BLE001
                                pass
                        synthetic_results[i] = None

        new_synthetic_cases = [c for c in synthetic_results if c]

        if not new_cases and not new_synthetic_cases:
            _finish_training_generation(agent_id, "failed",
                error="Couldn't build any scenarios just now - try again in a minute.")
            return

        # Only real replies selected above ever touch used_reply_ids -
        # synthetic scenarios never mark a reply used (there is no real
        # reply behind them). This mirrors the old behaviour exactly:
        # every SELECTED real reply is recorded here regardless of whether
        # its own case build succeeded (see the one-worker-failure test).
        new_used_ids = [r.get("id") for r in replies]

        # Lost-update protection: reload the doc fresh right before saving.
        # classify()/draft_reply() round trips for a full batch can run past
        # a minute, and an answer may have been written to this same doc row
        # in the meantime - appending onto a stale in-memory copy would
        # silently drop it.
        fresh_doc = _load_training(agent_id)
        fresh_doc["cases"] = list(fresh_doc.get("cases") or []) + new_cases + new_synthetic_cases
        fresh_doc["used_reply_ids"] = list(fresh_doc.get("used_reply_ids") or []) + new_used_ids
        gen_marker = {
            "status": "idle",
            "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "added": len(new_cases) + len(new_synthetic_cases),
        }
        # Carry retrain_queued forward if a "remember" answer set it while
        # this batch was building - see _finish_training_generation's own
        # matching comment and _maybe_run_queued_retrain.
        if (fresh_doc.get("generating") or {}).get("retrain_queued"):
            gen_marker["retrain_queued"] = True
        fresh_doc["generating"] = gen_marker
        _save_training(agent_id, fresh_doc)

        if new_synthetic_cases:
            _log_synthetic_usage(agent_id, len(new_synthetic_cases), synthetic_trigger, is_share_mode)
    except Exception as e:  # noqa: BLE001 - never raise out of a background thread
        if _LOG:
            try:
                _LOG("/api/setter/training/generate:worker_failed",
                    {"agent_id": agent_id, "error": str(e)[:200]}, actor="system")
            except Exception:  # noqa: BLE001
                pass
        _finish_training_generation(agent_id, "failed",
            error="Something went wrong while generating scenarios - try again in a minute.")


# ── training retrain (Feature B, owner ruling 2026-07-14) ───────────────────
# ANY feedback on a training answer - a note, or an explicit wrong mark on
# either question - re-runs every remaining unanswered scenario with the
# updated brain, in the background, so the owner never repeats a correction
# case after case. Mirrors the grading page's _kick_off_relearn/
# _grading_relearn precedent exactly, except the lock is the SAME per-agent
# lock route_training_generate uses (_get_training_gen_lock) - a retrain and
# a generate() for one agent must never run concurrently, since both append/
# rewrite the same training doc's `cases` list.

def _kick_off_training_retrain(agent_id: str) -> str:
    """Latency fix (2026-07-14, part 2): the REQUEST thread does ZERO doc
    round trips here now - it only makes the lock.acquire(blocking=False)
    bookkeeping decision and starts a thread. Every Supabase write this used
    to do inline (the "running" marker on acquire, the retrain_queued flag
    on contention) now happens OFF the request thread:

      - lock acquired -> spawn the retrain worker itself. Its very FIRST
        action (see _training_retrain_worker) is persisting the running
        marker, before it drains pending_merges or touches anything else -
        so "started" really does mean "a worker is about to mark itself
        running", not "the request thread already did".
      - lock held (another generate()/retrain already running for this
        agent) -> spawn a tiny daemon "flagger" thread that does the
        load + set retrain_queued=True + save, registered under
        _TRAINING_GEN_THREADS[f"{agent_id}:flag"] (a separate key from the
        running worker's own _TRAINING_GEN_THREADS[agent_id] entry) purely
        so tests can join it deterministically - production never reads
        this map. This trades a small window (the flagger theoretically
        losing the race against the currently-running pass's own
        end-of-loop queued check) for the request thread never blocking on
        Supabase; in practice a single doc load+save is nowhere near as
        slow as the classify/draft work a real retrain pass is busy with.

    Response semantics unchanged - still returns "started" or "queued"."""
    lock = _get_training_gen_lock(agent_id)
    if lock.acquire(blocking=False):
        thread = threading.Thread(target=_training_retrain_threadmain, args=(agent_id, lock), daemon=True)
        _TRAINING_GEN_THREADS[agent_id] = thread
        thread.start()
        return "started"

    # Already generating or retraining for this agent - flag another pass is
    # wanted once the current one finishes, via a tiny daemon thread so the
    # REQUEST thread itself never touches Supabase. Never starts a second
    # worker.
    flagger = threading.Thread(target=_flag_training_retrain_queued, args=(agent_id,), daemon=True)
    _TRAINING_GEN_THREADS[f"{agent_id}:flag"] = flagger
    flagger.start()
    return "queued"


def _flag_training_retrain_queued(agent_id: str):
    """The flagger thread's entire job (see _kick_off_training_retrain's
    lock-held branch): reload the training doc fresh and persist
    generating.retrain_queued=True, so whichever pass is currently running
    for this agent loops once more at the end of its current cycle (see
    _training_retrain_worker's own queued check). Never raises out of a
    background thread."""
    try:
        doc = _load_training(agent_id)
        gen = dict(doc.get("generating") or {})
        gen["retrain_queued"] = True
        doc["generating"] = gen
        _save_training(agent_id, doc)
    except Exception:  # noqa: BLE001
        pass


def _training_retrain_threadmain(agent_id, lock):
    try:
        _training_retrain_worker(agent_id)
    finally:
        try:
            lock.release()
        except RuntimeError:  # noqa: BLE001 - lock wasn't held (shouldn't happen); never crash a bg thread
            pass


def _maybe_run_queued_retrain(agent_id):
    """Called by _training_generate_threadmain right after a generate batch
    finishes, still holding the lock: if a 'remember' answer queued a
    retrain while the batch was building, run it now instead of leaving a
    stale retrain_queued flag with no worker left to honour it."""
    try:
        doc = _load_training(agent_id)
        gen = dict(doc.get("generating") or {})
        if gen.get("retrain_queued"):
            gen["retrain_queued"] = False
            doc["generating"] = gen
            _save_training(agent_id, doc)
            _training_retrain_worker(agent_id)
    except Exception:  # noqa: BLE001 - never raise out of a background thread
        pass


def _training_session_feedback_digest(doc: dict, limit_chars: int = 2000) -> str:
    """Plain-English digest built from THIS training doc's own answers -
    every note plus every explicit wrong mark, newest first, capped to
    roughly limit_chars. Same shape and purpose as _feedback_digest (the
    grading page's version), adapted to the training doc's answers dict
    (keyed by case_id) instead of a flat feedback_log.

    Thumbs-up teaches too (owner brief 2026-07-14: "when I give a thumbs up
    it doesn't learn from it"): after the corrections above, appends a
    second block built from doc['confirmed_examples'] (see
    route_training_answer) naming the newest ~5 calls the owner explicitly
    confirmed were right, so a future pass treats a similar reply the same
    way. Corrections always take space priority - the confirmations block is
    only added if it still fits under limit_chars, and the whole return
    value is capped to limit_chars regardless."""
    doc = doc or {}
    answers = dict(doc.get("answers") or {})
    cases_by_id = {str(c.get("id")): c for c in (doc.get("cases") or [])}
    items = sorted(answers.items(), key=lambda kv: (kv[1] or {}).get("at") or "")
    lines = []
    for case_id, ans in reversed(items):
        ans = ans or {}
        note = str(ans.get("note") or "").strip()
        if note:
            lines.append(f"- {note}")
            continue
        if ans.get("decision_ok") is False or ans.get("reply_ok") is False:
            case = cases_by_id.get(str(case_id)) or {}
            inbound_snip = str((case.get("inbound") or {}).get("body") or "")[:80]
            if ans.get("decision_ok") is False:
                lines.append(f"- The owner said the '{case.get('decision') or 'call'}' call was wrong for a "
                             f"reply like: '{inbound_snip}'")
            else:
                lines.append(f"- The owner disliked the draft written for: '{inbound_snip}'")
    digest = "\n".join(lines)

    confirmed = list(doc.get("confirmed_examples") or [])
    if confirmed and len(digest) < limit_chars:
        conf_lines = []
        for entry in reversed(confirmed[-5:]):  # newest ~5, newest first
            entry = entry or {}
            gist = str(entry.get("gist") or "").strip()
            if not gist:
                continue
            verb = "answer on its own" if entry.get("decision") == "auto_send" else "leave it to a human"
            conf_lines.append(f"- '{gist}' -> {verb}")
        if conf_lines:
            conf_block = ("The owner CONFIRMED these calls were right - treat similar replies the same "
                          "way:\n" + "\n".join(conf_lines))
            digest = (digest + "\n\n" + conf_block) if digest else conf_block
    return digest[:limit_chars]


def _retrain_one_training_case(case: dict, agent_snapshot: dict, eff_settings: dict, avail: list,
                               slot_status0: str, now, digest: str):
    """Re-runs classify -> decide -> draft_reply for one UNANSWERED training
    case using the agent's freshest instructions (a 'remember' correction may
    have just rewritten them - see merge_correction_into_instructions) plus
    this session's feedback digest, mutating `case` in place. Reads from the
    case's own stored inbound/original_outreach fields (mirrors
    _build_training_case's pipeline) rather than re-fetching from Supabase -
    the case already carries everything the pipeline needs. Never raises - a
    failure here just leaves the case exactly as it was (old content
    survives), mirroring _relearn_one_case's contract."""
    try:
        inbound = case.get("inbound") or {}
        body = inbound.get("body") or ""
        subject = inbound.get("subject") or ""
        outreach = case.get("original_outreach") or {}
        first_outbound = outreach.get("body") or ""

        cls = classify({"subject": subject, "body": body, "first_outbound": first_outbound,
                        "last_outbound": "", "email_domain": ""}, agent_snapshot, owner_hints=digest)

        hints = {"phone": _extract_phone(body), "body": body}
        tz, tz_confident = resolve_timezone(hints, cls)

        primary = cls.get("primary_intent")
        try:
            confidence = float(cls.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        is_clear_neg = primary in CLEAR_NEGATIVE_INTENTS and confidence >= 0.8

        slots, slot_status = [], "not_configured"
        if not is_clear_neg:
            if tz:
                slot_status = slot_status0
                if slot_status == "ok":
                    eff_lead = dict(eff_settings)
                    eff_lead["_lead"] = {"first_name": "", "last_name": "", "email": ""}
                    slots = pick_slots(avail, tz, eff_lead, now)
                    if not slots:
                        slot_status = "none_available"
            else:
                slot_status = "tz_unknown"

        slots_fallback = slot_status != "ok"
        needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

        draft_html = None
        lint_ok, lint_reason = False, "No draft was produced."
        if not is_clear_neg:
            try:
                # No hydration in a retrain pass either - resolves to the
                # agent's own configured identity via _sender_first_for (owner
                # bug report 2026-07-14: this used to hardcode "Bjion").
                d = draft_reply({"first_name": "", "subject": subject, "body": body,
                                 "first_outbound": first_outbound}, agent_snapshot, cls, slots, slot_status,
                                sender_first=_sender_first_for(agent_snapshot), regen_feedback=digest)
                draft_html = d.get("html")
                if draft_html:
                    # Second sweep (owner brief 2026-07-14) - BEFORE lint so
                    # lint checks the final, proofread text.
                    draft_html, _proofread_changed = proofread_draft(draft_html)
                lint_ok, lint_reason = lint_draft(draft_html, {
                    "subject": d.get("subject"), "first_name": "",
                    "needs_resource_link": "send_resource" in (cls.get("all_intents") or []),
                    "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
                    "slot_labels": [s.get("label") for s in slots],
                    "instructions": _agent_instructions(agent_snapshot),
                    "booking_link": _booking_link(agent_snapshot), "thread_text": body,
                    "slots_fallback": slots_fallback, "needs_availability_ask": needs_availability_ask,
                })
            except Exception:  # noqa: BLE001
                draft_html = None
                lint_ok, lint_reason = False, "No draft was produced."

        ctx = {
            "red_flag_hits": lexicon_hits(body), "category": case.get("category"),
            "first_touch": True, "slot_status": slot_status, "slots_fallback": slots_fallback,
            "timezone": tz, "tz_confident": tz_confident, "lint_ok": lint_ok, "lint_reason": lint_reason,
            "body_len": len(body), "hydrated": True, "answered_since_reply": False, "autopilot_enabled": True,
            "same_day_ask": bool(_SAME_DAY_RE.search(_strip_quoted(body))),
            "first_outbound_present": bool(str(first_outbound or "").strip()),
            "needs_availability_ask": needs_availability_ask,
        }
        decision, reason = decide(cls, agent_snapshot, ctx)

        case["classification"] = cls
        case["decision"] = decision
        case["decision_reason"] = reason
        case["draft_html"] = draft_html
        case["updated_by_feedback"] = True
    except Exception:  # noqa: BLE001 - one bad case must never abort the whole retrain pass
        pass


# ── training review mode (owner request 2026-07-14) ──────────────────────────
# "go back through some of the old scenarios and messaging, just to check
# that it's now been trained to actually be good" - answered training cases
# are frozen historical records (old draft + the trainer's verdict). Review
# mode re-runs a batch of them through TODAY'S brain (current instructions +
# latest owner rules + proofread) and stores the result NEXT TO the original
# under case["recheck"], so the trainer sees Then vs Now - proof the training
# took, without touching history, answers, or readiness. Shares the SAME
# per-agent lock as generate/retrain (_get_training_gen_lock) so the three
# kinds of background work never interleave writes to the same doc.

def _normalize_draft_text(html) -> str:
    """Strips HTML tags and collapses whitespace, so two drafts that differ
    only in formatting (a stray <br> vs a newline, doubled spaces) are never
    flagged as "changed" by _recheck_one_training_case - only a genuine text
    difference should light up the Changed badge."""
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    return re.sub(r"\s+", " ", text).strip()


def _recheck_one_training_case(case: dict, agent_snapshot: dict, eff_settings: dict, avail: list,
                               slot_status0: str, now, digest: str):
    """Review mode's per-case pipeline - re-runs classify -> decide ->
    draft_reply -> proofread for ONE answered training case using the
    agent's freshest instructions/rules, almost exactly
    _retrain_one_training_case's own pipeline. Unlike that function, this
    NEVER mutates `case` - it returns a fresh {decision, decision_reason,
    draft_html, at, changed} dict for the caller to store under a new
    case["recheck"] key, since a recheck must never touch the case's own
    frozen decision/decision_reason/draft_html/classification (that's the
    "Back then" record the trainer is comparing against). changed is True
    when the decision differs from the case's original decision, OR the
    normalised draft text (see _normalize_draft_text) differs from the
    case's original draft_html. Returns None on any failure - a bad re-run
    just leaves that case's recheck absent, never blocks the rest of the
    batch (see _training_recheck_worker)."""
    try:
        inbound = case.get("inbound") or {}
        body = inbound.get("body") or ""
        subject = inbound.get("subject") or ""
        outreach = case.get("original_outreach") or {}
        first_outbound = outreach.get("body") or ""

        cls = classify({"subject": subject, "body": body, "first_outbound": first_outbound,
                        "last_outbound": "", "email_domain": ""}, agent_snapshot, owner_hints=digest)

        hints = {"phone": _extract_phone(body), "body": body}
        tz, tz_confident = resolve_timezone(hints, cls)

        primary = cls.get("primary_intent")
        try:
            confidence = float(cls.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        is_clear_neg = primary in CLEAR_NEGATIVE_INTENTS and confidence >= 0.8

        slots, slot_status = [], "not_configured"
        if not is_clear_neg:
            if tz:
                slot_status = slot_status0
                if slot_status == "ok":
                    eff_lead = dict(eff_settings)
                    eff_lead["_lead"] = {"first_name": "", "last_name": "", "email": ""}
                    slots = pick_slots(avail, tz, eff_lead, now)
                    if not slots:
                        slot_status = "none_available"
            else:
                slot_status = "tz_unknown"

        slots_fallback = slot_status != "ok"
        needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

        draft_html = None
        lint_ok, lint_reason = False, "No draft was produced."
        if not is_clear_neg:
            try:
                # No hydration in a recheck pass either - resolves to the
                # agent's own configured identity via _sender_first_for (owner
                # bug report 2026-07-14: this used to hardcode "Bjion").
                d = draft_reply({"first_name": "", "subject": subject, "body": body,
                                 "first_outbound": first_outbound}, agent_snapshot, cls, slots, slot_status,
                                sender_first=_sender_first_for(agent_snapshot), regen_feedback=digest)
                draft_html = d.get("html")
                if draft_html:
                    # Second sweep (owner brief 2026-07-14) - BEFORE lint so
                    # lint checks the final, proofread text.
                    draft_html, _proofread_changed = proofread_draft(draft_html)
                lint_ok, lint_reason = lint_draft(draft_html, {
                    "subject": d.get("subject"), "first_name": "",
                    "needs_resource_link": "send_resource" in (cls.get("all_intents") or []),
                    "slot_status": slot_status, "slot_links": [s.get("link") for s in slots],
                    "slot_labels": [s.get("label") for s in slots],
                    "instructions": _agent_instructions(agent_snapshot),
                    "booking_link": _booking_link(agent_snapshot), "thread_text": body,
                    "slots_fallback": slots_fallback, "needs_availability_ask": needs_availability_ask,
                })
            except Exception:  # noqa: BLE001
                draft_html = None
                lint_ok, lint_reason = False, "No draft was produced."

        ctx = {
            "red_flag_hits": lexicon_hits(body), "category": case.get("category"),
            "first_touch": True, "slot_status": slot_status, "slots_fallback": slots_fallback,
            "timezone": tz, "tz_confident": tz_confident, "lint_ok": lint_ok, "lint_reason": lint_reason,
            "body_len": len(body), "hydrated": True, "answered_since_reply": False, "autopilot_enabled": True,
            "same_day_ask": bool(_SAME_DAY_RE.search(_strip_quoted(body))),
            "first_outbound_present": bool(str(first_outbound or "").strip()),
            "needs_availability_ask": needs_availability_ask,
        }
        decision, reason = decide(cls, agent_snapshot, ctx)

        changed = (decision != case.get("decision")) or \
                 (_normalize_draft_text(draft_html) != _normalize_draft_text(case.get("draft_html")))

        return {
            "decision": decision, "decision_reason": reason, "draft_html": draft_html,
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "changed": changed,
        }
    except Exception:  # noqa: BLE001 - one bad case must never abort the whole recheck pass
        return None


def _finish_training_recheck(agent_id: str, rechecked: int = 0, error: str | None = None):
    """Writes only doc["generating"], kind="recheck" - reloads the doc first
    so this marker write never clobbers an answer that landed while the
    worker was running. Used for the recheck worker's early-exit paths (no
    answered cases somehow, agent gone, or an unexpected top-level failure);
    the normal success path (_training_recheck_worker) writes its own final
    marker alongside the `cases` merge, same discipline as
    _training_generate_worker."""
    try:
        doc = _load_training(agent_id)
        marker = {"status": "idle" if error is None else "failed", "kind": "recheck",
                  "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                  "rechecked": rechecked}
        if error is not None:
            marker["error"] = error
        doc["generating"] = marker
        _save_training(agent_id, doc)
    except Exception:  # noqa: BLE001
        pass


def _training_recheck_worker(agent_id: str, count: int):
    """Review mode's real work (see route_training_recheck) - runs off-
    request on a daemon thread, same shape as _training_generate_worker /
    _training_retrain_worker. Picks the `count` most-recently-ANSWERED cases
    (by their answer's `at`, newest first), re-runs each through TODAY'S
    pipeline concurrently (_recheck_one_training_case - classify -> decide ->
    draft_reply -> proofread, with owner_hints/regen_feedback built from the
    same LATEST OWNER RULES + session digest a live retrain pass gets), and
    writes the result into a NEW case["recheck"] key - never the case's own
    decision/decision_reason/draft_html/classification, never
    doc["answers"], doc["readiness_history"], doc["confirmed_examples"] or
    doc["used_reply_ids"]. A failed re-run just leaves that one case's
    recheck absent (see _recheck_one_training_case's own try/except) - never
    blocks the rest of the batch.

    Lost-update protection: the cases to re-run are SELECTED from a doc
    loaded at the top of this function (their inbound/original_outreach text
    is frozen history, safe to read from a snapshot), but the final save
    reloads the doc fresh and merges each result onto its copy of the
    matching case by id - so an answer that lands on any case (including one
    this pass is rechecking) while classify/draft round trips are in flight
    is never lost. Only the `recheck` key on the cases this pass targeted,
    plus `generating`, are ever written here."""
    try:
        doc = _load_training(agent_id)
        cases = list(doc.get("cases") or [])
        answers = dict(doc.get("answers") or {})
        cases_by_id = {str(c.get("id")): c for c in cases}

        answered_items = [(cid, str((answers.get(cid) or {}).get("at") or ""))
                          for cid in cases_by_id if _is_case_answered(cid, answers)]
        answered_items.sort(key=lambda kv: kv[1], reverse=True)  # newest answered first
        target_ids = [cid for cid, _at in answered_items[:count]]

        agent = _load_agent(agent_id)
        if not agent or not target_ids:
            _finish_training_recheck(agent_id, rechecked=0)
            return
        train_agent = {**agent, "mode": "autopilot", "enabled": True}

        # Same digest a live pass, a fresh generate batch, and a retrain
        # pass all get - LATEST OWNER RULES leads, then this training doc's
        # own session digest (corrections and confirmed-exemplar
        # confirmations) - so a recheck genuinely reflects TODAY's brain.
        digest = _prefix_latest_rules(_latest_owner_rules(train_agent, doc),
                                      _training_session_feedback_digest(doc))

        settings = _load_settings()
        now = _dt.datetime.now(_dt.timezone.utc)
        eff = dict(settings)
        eff["_agent"] = train_agent
        slot_status0, avail, _serr = get_calendly_availability(train_agent, eff, now)

        results: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(target_ids))) as pool:
            future_to_id = {
                pool.submit(_recheck_one_training_case, cases_by_id[cid], train_agent, eff, avail,
                           slot_status0, now, digest): cid
                for cid in target_ids if cid in cases_by_id
            }
            for fut in concurrent.futures.as_completed(future_to_id):
                cid = future_to_id[fut]
                try:
                    result = fut.result()
                except Exception as e:  # noqa: BLE001 - one bad case must never sink the batch
                    result = None
                    if _LOG:
                        try:
                            _LOG("/api/setter/training/recheck:case_failed",
                                {"agent_id": agent_id, "case_id": cid, "error": str(e)[:200]}, actor="system")
                        except Exception:  # noqa: BLE001
                            pass
                if result:
                    results[cid] = result

        # Lost-update protection (see docstring): reload fresh right before
        # saving, and only merge `recheck` onto the specific cases this pass
        # targeted.
        fresh = _load_training(agent_id)
        fresh_cases = list(fresh.get("cases") or [])
        for c in fresh_cases:
            cid = str(c.get("id"))
            if cid in results:
                c["recheck"] = results[cid]
        fresh["cases"] = fresh_cases
        fresh["generating"] = {
            "status": "idle", "kind": "recheck",
            "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "rechecked": len(results),
        }
        _save_training(agent_id, fresh)
    except Exception as e:  # noqa: BLE001 - never raise out of a background thread
        if _LOG:
            try:
                _LOG("/api/setter/training/recheck:worker_failed",
                    {"agent_id": agent_id, "error": str(e)[:200]}, actor="system")
            except Exception:  # noqa: BLE001
                pass
        _finish_training_recheck(agent_id, rechecked=0,
            error="Something went wrong while reviewing scenarios - try again in a minute.")


def _training_recheck_threadmain(agent_id, count, lock):
    try:
        _training_recheck_worker(agent_id, count)
        # A "remember" answer may have queued a retrain pass WHILE this
        # recheck held the lock (see _kick_off_training_retrain) - run it
        # now, still holding the same lock, same discipline as
        # _training_generate_threadmain.
        _maybe_run_queued_retrain(agent_id)
    finally:
        try:
            lock.release()
        except RuntimeError:  # noqa: BLE001 - lock wasn't held (shouldn't happen); never crash a bg thread
            pass


def route_training_recheck(payload):
    """POST /api/setter/training/recheck - Review mode (see the section
    doctrine above). Validates synchronously (share scope, agent existence,
    "nothing answered yet" 400) exactly like route_training_generate, then
    kicks the actual work off in a background daemon thread sharing the SAME
    per-agent lock generate/retrain use, so the three kinds of work never
    overlap. Lock already held by a generate/retrain/recheck pass for this
    agent -> idempotent no-op, same "already_running" shape
    route_training_generate returns."""
    try:
        payload = payload or {}
        agent_id = payload.get("agent_id")
        share_token = payload.get("share") or ""
        public = bool(payload.get("___public"))
        agent_id, err = _resolve_share_scope(agent_id, share_token, public)
        if err:
            return err
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}

        try:
            count = int(payload.get("count") or TRAINING_RECHECK_DEFAULT)
        except (TypeError, ValueError):
            count = TRAINING_RECHECK_DEFAULT
        count = max(1, min(count, TRAINING_RECHECK_MAX))

        doc = _load_training(agent_id)
        cases = list(doc.get("cases") or [])
        answers = dict(doc.get("answers") or {})
        if not any(_is_case_answered(c.get("id"), answers) for c in cases):
            return 400, {"error": "Nothing answered yet to review."}

        lock = _get_training_gen_lock(agent_id)
        if not lock.acquire(blocking=False):
            # Already generating/retraining/rechecking for this agent -
            # idempotent no-op, mirrors route_training_generate exactly.
            return 200, {"ok": True, "status": "already_running"}

        try:
            marker_doc = _load_training(agent_id)
            marker_doc["generating"] = {
                "status": "running", "kind": "recheck",
                "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                "count": count,
            }
            _save_training(agent_id, marker_doc)
        except Exception:  # noqa: BLE001 - never leave the lock held if writing the marker itself blows up
            lock.release()
            raise

        thread = threading.Thread(
            target=_training_recheck_threadmain,
            args=(agent_id, count, lock),
            daemon=True,
        )
        _TRAINING_GEN_THREADS[agent_id] = thread
        thread.start()
        return 200, {"ok": True, "status": "started"}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _drain_pending_merges(agent_id: str) -> list:
    """Latency fix (2026-07-14): route_training_answer no longer merges a
    "remember" note into the agent's instructions inline - it queues
    {note, source, at} onto the training doc's own `pending_merges` list
    instead (see route_training_answer). This is the other half: reloads
    the training doc fresh, pops every queued entry, and persists the empty
    list immediately (before any of the actual gpt-5-mini merge calls run)
    so a note is never double-applied and a fresh "remember" answer that
    lands mid-drain just queues its own new entry for the NEXT pass to pick
    up. Only `pending_merges` is ours to write here - reloading right before
    saving mirrors the same lost-update discipline the worker's own final
    save already uses, so an answer/cases write that lands concurrently is
    never clobbered. Returns the popped entries in submission order (empty
    list if nothing was queued)."""
    doc = _load_training(agent_id)
    pending = list(doc.get("pending_merges") or [])
    if pending:
        doc["pending_merges"] = []
        _save_training(agent_id, doc)
    return pending


def _training_retrain_worker(agent_id: str):
    """Latency fix (2026-07-14, part 2): this worker's FIRST action, on
    every pass (including the very first), is persisting the "running"
    marker itself - _kick_off_training_retrain no longer writes it from the
    request thread. Only THEN does it drain and merge any queued
    pending_merges (see _drain_pending_merges) - in submission order, each
    via merge_correction_into_instructions, which already does its own safe
    agent reload/save and always falls back to a dumb append on any
    failure, so a bad merge never blocks the retrain below. THEN reloads
    the agent fresh (picking up whatever the drain just merged), builds a
    session feedback digest from this training doc's own answers, and
    re-runs every currently UNANSWERED case in position order, concurrently
    (ThreadPoolExecutor, max 6 - same worker hygiene as
    _training_generate_worker: cases touch no shared mutable state besides
    their own dict). Persists with a fresh reload right before the final
    save so an answer that lands mid-pass is never lost (lost-update
    protection, same discipline as _training_generate_worker and
    _grading_relearn). If another trigger queued a fresh pass while this one
    ran - including a fresh "remember" note that landed mid-pass, or the
    tiny flagger thread from _kick_off_training_retrain's lock-held branch -
    loops once more, writing a fresh running marker and draining
    pending_merges again at the TOP of that follow-on pass before its own
    retrain work, mirroring _grading_relearn exactly. Never raises."""
    try:
        while True:
            started_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            marker_doc = _load_training(agent_id)
            marker_doc["generating"] = {"status": "running", "kind": "retrain", "started_at": started_at}
            _save_training(agent_id, marker_doc)

            for entry in _drain_pending_merges(agent_id):
                note = str((entry or {}).get("note") or "").strip()
                if not note:
                    continue
                merge_agent = _load_agent(agent_id)
                if not merge_agent:
                    break
                merge_correction_into_instructions(
                    merge_agent, note, source=(entry or {}).get("source") or "training")

            agent = _load_agent(agent_id)
            if not agent:
                _finish_training_generation(agent_id, "idle")
                return
            train_agent = {**agent, "mode": "autopilot", "enabled": True}

            doc = _load_training(agent_id)
            cases = list(doc.get("cases") or [])
            answers = dict(doc.get("answers") or {})
            # LATEST OWNER RULES (recency weighting) always leads, then this
            # session's own corrections/confirmations digest.
            digest = _prefix_latest_rules(_latest_owner_rules(train_agent, doc),
                                          _training_session_feedback_digest(doc))

            settings = _load_settings()
            now = _dt.datetime.now(_dt.timezone.utc)
            eff = dict(settings)
            eff["_agent"] = train_agent
            slot_status0, avail, _serr = get_calendly_availability(train_agent, eff, now)

            cases_by_id = {str(c.get("id")): c for c in cases}
            unanswered_ids = [c.get("id") for c in cases if not _is_case_answered(c.get("id"), answers)]

            updated = 0
            if unanswered_ids:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(unanswered_ids))) as pool:
                    futs = []
                    for cid in unanswered_ids:
                        case = cases_by_id.get(cid)
                        if not isinstance(case, dict):
                            continue
                        futs.append(pool.submit(_retrain_one_training_case, case, train_agent, eff, avail,
                                               slot_status0, now, digest))
                    for fut in concurrent.futures.as_completed(futs):
                        try:
                            fut.result()
                            updated += 1
                        except Exception:  # noqa: BLE001 - one bad case must never sink the pass
                            pass

            # Lost-update protection: reload the doc fresh right before the
            # final save. Only `cases` and `generating` are ours to write -
            # answers/used_reply_ids/readiness_history are left exactly as
            # the fresh reload shows, so an answer that landed on any case
            # (including one this pass just rewrote) while classify/draft
            # round trips were in flight is never lost.
            fresh = _load_training(agent_id)
            fresh["cases"] = cases
            queued = bool((fresh.get("generating") or {}).get("retrain_queued"))
            finished_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            fresh["generating"] = {"status": "idle", "kind": "retrain", "started_at": started_at,
                                   "finished_at": finished_at, "updated": updated}
            _save_training(agent_id, fresh)

            if not queued:
                break
            # else: more feedback landed while this pass ran - loop again
            # with the fresher digest, mirroring _grading_relearn.
    except Exception:  # noqa: BLE001 - a background thread must never raise
        try:
            doc = _load_training(agent_id)
            gen = dict(doc.get("generating") or {})
            gen["status"] = "idle"
            gen["finished_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            doc["generating"] = gen
            _save_training(agent_id, doc)
        except Exception:  # noqa: BLE001
            pass


def route_training_answer(payload):
    try:
        payload = payload or {}
        agent_id = payload.get("agent_id")
        share_token = payload.get("share") or ""
        public = bool(payload.get("___public"))
        agent_id, err = _resolve_share_scope(agent_id, share_token, public)
        if err:
            return err
        case_id = str(payload.get("case_id") or "")
        if not case_id:
            return 400, {"error": "case_id is required"}

        # Latency fix (2026-07-14, part 2): skip the AGENT load entirely on
        # the common path. A training doc only ever gets its cases from a
        # real agent's own generate()/retrain pass, so finding case_id among
        # them is already proof the agent existed - no separate 404 check
        # needed. Only fall back to loading the agent when the case lookup
        # misses, purely to tell "the agent itself is gone" (404 Agent not
        # found) apart from "this agent's doc just doesn't have this
        # case_id" (404 Training scenario not found). Saves one Supabase
        # round trip on every answer, note or not.
        doc = _load_training(agent_id)
        cases = list(doc.get("cases") or [])
        if not any(str(c.get("id")) == case_id for c in cases):
            if not _load_agent(agent_id):
                return 404, {"error": "Agent not found."}
            return 404, {"error": "Training scenario not found."}

        decision_ok = payload.get("decision_ok")
        reply_ok = payload.get("reply_ok")
        note = str(payload.get("note") or "").strip()
        scope = payload.get("scope") or "one_off"
        at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

        answers = dict(doc.get("answers") or {})
        answers[case_id] = {"decision_ok": decision_ok, "reply_ok": reply_ok, "note": note,
                            "scope": scope, "at": at}
        doc["answers"] = answers

        # Thumbs-up teaches too (owner brief 2026-07-14: "when I give a
        # thumbs up it doesn't learn from it"): a confirmed decision_ok=True
        # becomes a compact exemplar {gist, decision, at} the training/
        # retrain digests can point future passes at (see
        # _training_session_feedback_digest). Rolling cap 20, newest kept.
        # Same single doc write as the answer below - no extra round trip.
        if decision_ok is True:
            case = next((c for c in cases if str(c.get("id")) == case_id), None)
            gist = str(((case or {}).get("inbound") or {}).get("body") or "").strip()[:90]
            if gist:
                confirmed = list(doc.get("confirmed_examples") or [])
                confirmed.append({"gist": gist, "decision": (case or {}).get("decision"), "at": at})
                doc["confirmed_examples"] = confirmed[-20:]

        # scope="remember" (owner ruling 2026-07-14) is meant to merge the
        # note straight into the agent's own `instructions` text via
        # merge_correction_into_instructions - the single living manual, feeds
        # every future classify()/draft_reply() call and every future
        # training generation, exactly the same helper the inbox correction/
        # redraft flows still use synchronously. But that helper calls
        # gpt-5-mini (5-15s), and this route must return in well under a
        # second so "Save & continue" never blocks the trainer waiting for
        # the next card. So here the note is only QUEUED onto the training
        # doc's own `pending_merges` list (written by the SAME _save_training
        # call below that stores the answer - one write, no extra round
        # trip); the background retrain worker kicked off further down
        # drains and merges it. scope="one_off" (or an empty note) is
        # audit-only and changes nothing but feedback_log, exactly as before.
        if note and scope == "remember":
            pending_merges = list(doc.get("pending_merges") or [])
            pending_merges.append({"note": note, "source": f"training:{case_id}", "at": at})
            doc["pending_merges"] = pending_merges
        elif note:
            _append_agent_feedback_log(agent_id, note, source=f"training:{case_id}")

        readiness = compute_readiness(doc)
        history = list(doc.get("readiness_history") or [])
        history.append({"at": at, "score": readiness["score"], "n_answers": readiness["n_answers"]})
        doc["readiness_history"] = history

        _save_training(agent_id, doc)

        answered_count = sum(1 for c in cases if _is_case_answered(c.get("id"), answers))
        unanswered_count = len(cases) - answered_count

        # Feature B (owner ruling 2026-07-14): ANY feedback - a note, or an
        # explicit wrong mark on either question - re-runs every remaining
        # unanswered scenario with the updated brain, in the background, so
        # the owner never has to repeat a correction case after case. Kicked
        # off AFTER the answer (and any queued pending_merges entry) are
        # saved, so the retrain worker's own drain-then-reload sees this
        # case as answered (excluded) and picks up the just-queued note.
        triggers_retrain = bool(note) or decision_ok is False or reply_ok is False
        retrain = _kick_off_training_retrain(agent_id) if triggers_retrain else None

        return 200, {"ok": True, "readiness": readiness,
                    "answered_count": answered_count, "unanswered_count": unanswered_count,
                    "retrain": retrain}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_training_reset(payload):
    try:
        agent_id = (payload or {}).get("agent_id")
        if not agent_id:
            return 400, {"error": "agent_id is required"}
        doc = _load_training(agent_id)
        doc["answers"] = {}
        doc["readiness_history"] = []
        _save_training(agent_id, doc)
        return 200, {"ok": True}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_training_share(payload):
    """OWNER-ONLY (reached through server.py's normal login gate - never
    added to any public route list). Mints a 30-day-default share token for
    one agent and returns the page URL a client can open without logging in."""
    try:
        payload = payload or {}
        agent_id = payload.get("agent_id")
        if not agent_id:
            return 400, {"error": "agent_id is required"}
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        try:
            days = int(payload.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        token = mint_training_share(agent_id, days)
        # Decode the exp this exact token carries (rather than recomputing
        # it) so expires_at can never drift from what verify_training_share
        # will actually enforce.
        import base64
        b64 = token.rsplit(".", 1)[0]
        exp_epoch = int(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode().rsplit("|", 1)[1])
        expires_at = _dt.datetime.fromtimestamp(exp_epoch, tz=_dt.timezone.utc).isoformat(timespec="seconds")
        return 200, {"url_path": f"/app/setter-train.html?share={token}", "token": token,
                    "expires_at": expires_at}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_training_share_info(params):
    """PUBLIC (see server.py's _TRAIN_SHARE_GET). Returns only the agent name
    and id for a valid share token - never instructions, memory, campaigns,
    or anything else a client shouldn't see. 401 on an invalid/expired token."""
    try:
        share_token = _qp(params, "share", "")
        agent_id = verify_training_share(share_token)
        if not agent_id:
            return 401, {"error": _SHARE_EXPIRED_MSG}
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        return 200, {"agent_name": agent.get("name") or "", "agent_id": agent_id}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_edit_lesson_get(params):
    """Did the reviewer's edit on this row teach anything yet? The learner runs
    in the background (~40s), so the page polls this after an edited Approve
    and shows the result as a toast with Undo - a silent permanent write was
    the tester panel's core objection (2026-07-17, 5/5 startled). Returns
    {status:"learned", rule, undoable} once the lesson lands, {status:"pending"}
    before that. "pending" is also what a never-teaching edit returns - the
    page just stops polling; silence stays a valid outcome."""
    try:
        qid = _qp(params, "id", "")
        if not qid:
            return 400, {"error": "id is required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=agent_id") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row or not row.get("agent_id"):
            return 404, {"error": "Queue row not found or has no agent."}
        agent = _load_agent(row["agent_id"]) or {}
        slot = agent.get("last_edit_lesson") or {}
        if str(slot.get("source") or "") != str(qid):
            return 200, {"status": "pending"}
        undoable = _instructions_sha(_agent_instructions(agent)) == slot.get("post_sha")
        return 200, {"status": "learned", "rule": slot.get("rule"), "at": slot.get("at"),
                    "undoable": undoable}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_edit_lesson_undo(payload):
    """Takes back the most recent edit-taught lesson: restores the agent's
    instructions to the exact pre-merge text and removes the matching
    instruction_edits entry. Guarded by post_sha - if ANYTHING else has
    touched the instructions since (another lesson, a typed correction, a
    manual edit), undo refuses instead of clobbering it. One slot only: a
    newer lesson overwrites the record and this row's undo window closes."""
    try:
        payload = payload or {}
        qid = payload.get("id")
        if not qid:
            return 400, {"error": "id is required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=agent_id") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row or not row.get("agent_id"):
            return 404, {"error": "Queue row not found or has no agent."}
        agent = _load_agent(row["agent_id"]) or {}
        slot = agent.get("last_edit_lesson") or {}
        if str(slot.get("source") or "") != str(qid):
            return 409, {"error": "This lesson can no longer be undone - a newer lesson has replaced it."}
        if _instructions_sha(_agent_instructions(agent)) != slot.get("post_sha"):
            return 409, {"error": "The agent's instructions have changed since this lesson - "
                                  "edit them from the Agents drawer instead."}
        edits = [e for e in (agent.get("instruction_edits") or [])
                 if str(e.get("source") or "") != str(qid)]
        _save_agent({"id": agent.get("id"), "name": agent.get("name"),
                    "instructions": slot.get("prev_instructions") or "",
                    "instruction_edits": edits, "last_edit_lesson": None})
        return 200, {"ok": True, "undone": slot.get("rule")}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


GET_ROUTES = {
    "/api/setter/agents": route_agents_get,
    "/api/setter/campaigns": route_campaigns_get,
    "/api/setter/queue": route_queue_get,
    "/api/setter/thread": route_thread_get,
    "/api/setter/grading": route_grading_get,
    "/api/setter/training": route_training_get,
    "/api/setter/training/share-info": route_training_share_info,
    "/api/setter/edit-lesson": route_edit_lesson_get,
}

POST_ROUTES = {
    "/api/setter/agents/save": route_agents_save,
    "/api/setter/agents/delete": route_agents_delete,
    "/api/setter/agents/correction": route_agents_correction,
    "/api/setter/agents/duplicate": route_agents_duplicate,
    "/api/setter/agents/memory/delete": route_agents_memory_delete,
    "/api/setter/settings/save": route_settings_save,
    "/api/setter/queue/action": route_queue_action,
    "/api/setter/queue/redraft": route_queue_redraft,
    "/api/setter/subsequence/push": route_subsequence_push,
    "/api/setter/grading/answer": route_grading_answer,
    "/api/setter/grading/reset": route_grading_reset,
    "/api/setter/training/generate": route_training_generate,
    "/api/setter/training/answer": route_training_answer,
    "/api/setter/training/recheck": route_training_recheck,
    "/api/setter/training/reset": route_training_reset,
    "/api/setter/training/share": route_training_share,
    "/api/setter/test/inject": route_test_inject,
    "/api/setter/edit-lesson/undo": route_edit_lesson_undo,
}
