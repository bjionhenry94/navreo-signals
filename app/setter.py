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
SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
OPENAI_MODEL = "gpt-5-mini"

# ── All-workspaces federation for the Setter (MONITOR gate) ────────────────
# Historically the Setter read ONLY the `navreo` workspace, so the three sub-
# brands that live inside the shared navreo Smartlead workspace (Navreo /
# Amplifyy / Arnic) were the only clients that ever appeared. Every OTHER
# client (asteri, krg, grout, …) is its own federated workspace whose replies
# the Setter never read. This gate widens the LIST + intake to every enabled
# workspace so any client can be MANAGED here — but strictly as MONITOR-ONLY:
# a non-navreo row is surfaced for review and can NEVER send (enforced three
# ways: _is_monitor_ws, the _send_reply dry-force, and the send-action
# refusal). navreo behaviour AND navreo KPIs stay byte-for-byte unchanged
# (the pill/KPI queries remain navreo-scoped; the KPI fold re-filters to
# navreo even off the federated light scan).
#
# ONE reversal switch: SETTER_MONITOR_ALL_WS=0 restores navreo-only scoping.
# Default ON. Making a proven workspace genuinely sendable is a SEPARATE,
# explicit change (remove it from _is_monitor_ws's net) — never done here.
SETTER_MONITOR_ALL_WS = os.environ.get("SETTER_MONITOR_ALL_WS", "1") not in ("0", "false", "False", "")

# Never a real Setter reply source even if present in the table.
_WS_MONITOR_SKIP = ("heyreach", "opan-test")
_WS_IDS_CACHE = {"at": 0.0, "ids": None}


def _enabled_workspace_ids() -> list:
    """Enabled workspace ids (navreo always first). Read straight from the
    `workspaces` table — server.py owns the richer ws_all(); the Setter only
    needs the id list. 5-min cache; any failure degrades to navreo-only."""
    now = _time.time()
    c = _WS_IDS_CACHE
    if c["ids"] is not None and now - c["at"] < 300:
        return list(c["ids"])
    ids = ["navreo"]
    ok = False
    try:
        rows = _SB("GET", "workspaces?select=id,status&order=added_at") if _SB else None
        if isinstance(rows, list):
            ok = True
            for r in rows:
                wid = r.get("id") if isinstance(r, dict) else None
                if (wid and wid != "navreo" and wid not in _WS_MONITOR_SKIP
                        and (r.get("status") or "enabled") == "enabled"):
                    ids.append(wid)
    except Exception:  # noqa: BLE001 - a workspaces outage degrades below
        pass
    if ok:
        c.update(at=now, ids=ids)
        return list(ids)
    # Transient failure: serve the LAST GOOD list if one exists (panel fix
    # 2026-08-01 — caching the degraded navreo-only answer 404'd every open
    # client conversation for five minutes). A short retry floor stops a
    # persistent outage from re-paying the ~30s sb() timeout on EVERY
    # _list_ws_filter() call (up to 3 per cold queue build).
    c["at"] = now - 300 + 15   # stale again in 15s, not 300
    if c["ids"] is None:
        c["ids"] = ids         # last-resort: navreo-only until a read succeeds
    return list(c["ids"])


def _list_ws_filter() -> str:
    """PostgREST fragment scoping the Setter LIST + collapse reads. Gate OFF
    (or only navreo enabled) → navreo alone, byte-for-byte historical. Gate ON
    → every enabled workspace."""
    if not SETTER_MONITOR_ALL_WS:
        return f"workspace=eq.{WORKSPACE}"
    ids = _enabled_workspace_ids()
    if len(ids) <= 1:
        return f"workspace=eq.{WORKSPACE}"
    return "workspace=in.(" + ",".join(ids) + ")"


def _is_monitor_ws(ws) -> bool:
    """True for a workspace whose Setter rows are review-only and must NEVER
    send. Fail-closed: while the gate is on, ANYTHING that isn't navreo is
    monitor-only, whether or not it is still in the enabled list."""
    return bool(SETTER_MONITOR_ALL_WS) and (ws or "navreo") != "navreo"

# ── one OpenAI round trip, with a deadline and a retry ──────────────────────
# Every model call used to be a bare _HTTP on http_json's 60s default with
# nothing to catch a slow one. A urllib read timeout stringifies to exactly
# "The read operation timed out", which is what the reviewer saw over the
# Regenerate button (owner report 2026-07-28) - one slow call killed the whole
# regenerate. Now: a tighter per-call deadline, and ONE retry when (and only
# when) the failure was a timeout or transport blip. An HTTP error from OpenAI
# is not retried - it fails the same way twice and just doubles the wait.
#
# reasoning_effort is the single biggest wall-clock lever on gpt-5-mini.
# Measured 2026-07-28 on the real prompts: classify 15.8s -> 2.9s, draft
# 43.6s -> 4.6s, purely from dropping hidden reasoning tokens (1024 -> 0 and
# 3328 -> 0). The VISIBLE output is the same size either way (~320 tokens), so
# this buys latency, not brevity.
OPENAI_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "45"))
OPENAI_EFFORT = os.environ.get("OPENAI_EFFORT", "minimal")
# The proofread pass is the one guard-railed model call (URL/digit/length
# checks, falls back to the ORIGINAL draft on any failure), which makes it the
# one safe place for the fastest tier. Measured 2026-07-28 on the real prompt:
# same fixes out of gpt-5-nano, ~20-40% less wall clock than gpt-5-mini - and
# proofread was the single longest stage of a regenerate (7.4s of 16.6s).
PROOFREAD_MODEL = os.environ.get("SETTER_PROOFREAD_MODEL", "gpt-5-nano")
# Priority processing (measured 2026-07-28 on a draft-shaped call: 2.5s ->
# 1.4s). Costs more per token, but every setter call is a few hundred tokens
# of gpt-5-mini/nano - cents a day for a reviewer no longer watching a
# spinner. Set SETTER_OPENAI_TIER=default to revert without a deploy.
OPENAI_TIER = os.environ.get("SETTER_OPENAI_TIER", "priority")


def _is_transient(e) -> bool:
    """A timeout or connection blip - worth exactly one retry."""
    txt = (str(e) + " " + str(getattr(e, "reason", ""))).lower()
    return (isinstance(e, TimeoutError)
            or "timed out" in txt or "timeout" in txt
            or "connection reset" in txt or "connection aborted" in txt
            or "remote end closed" in txt)


def _openai(body: dict, key: str, *, timeout: float = None, retries: int = 1):
    """POST to chat/completions. Adds the effort/verbosity knobs unless the
    caller already set them. Raises on a non-transient failure."""
    body = dict(body)
    body.setdefault("reasoning_effort", OPENAI_EFFORT)
    body.setdefault("verbosity", "low")
    body.setdefault("service_tier", OPENAI_TIER)
    last = None
    for attempt in range(retries + 1):
        try:
            return _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                         {"Authorization": f"Bearer {key}"}, body,
                         OPENAI_TIMEOUT if timeout is None else timeout)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt >= retries or not _is_transient(e):
                raise
            print(f"[setter] openai {type(e).__name__} ({str(e)[:60]}), retry "
                  f"{attempt + 1}/{retries}", file=sys.stderr)
    raise last

# Only these Smartlead/Make categories may enter setter_queue (ruling
# 2026-07-14) - everything else (Contact Forward, Contact In Future, all
# negatives, uncategorised) stays out of both intake paths.
# "Call Booked" added 2026-08-09 (Bjion): booked leads still reply with real
# scheduling questions ("Is tomorrow 11am still ok?") that were invisible
# in-tool, and the client monitor path already surfaces call booked - the
# two paths now agree.
CORE_FOUR = frozenset({"Interested", "Information Request", "Meeting Request",
                       "positive-re-reply", "Call Booked"})

# PostgREST `category=in.(...)` filter built FROM CORE_FOUR (sorted for a
# deterministic query string) instead of hardcoding the label list a second
# time. Values contain spaces, so each option is double-quoted THEN percent-
# encoded (quote() turns the quote marks into %22 and the spaces into %20) -
# PostgREST needs the quotes to treat "Information Request" as one value
# instead of splitting on its internal space.
CORE_FOUR_CATEGORY_FILTER = "in.(" + ",".join(quote(f'"{c}"', safe="") for c in sorted(CORE_FOUR)) + ")"

# "positive-re-reply" is the categoriser routeB's ARCHIVE label for a fresh
# reply landing on an already-positive thread - an internal marker, never the
# lead's Smartlead category (routeB alerts + archives; it does not rewrite
# the lead's category, so Smartlead still says Interested / Meeting Request /
# ...). Stamping the label onto queue rows made the Lead-category pill read
# as if the lead's status had changed (owner ask 2026-08-17: "keep it as
# whatever the current status of it is"), so intake resolves the label to the
# lead's latest REAL category before the row is written. Both intake
# chokepoints (_process_reply_inner and _intake_agentless) call this, which
# covers every seam: webhook, poll, self-heal sweep, monitor federation and
# redrives. The label still GATES intake via CORE_FOUR - only the stamped
# value changes.
_RE_REPLY_LABEL = "positive-re-reply"


def _resolve_re_reply_category(workspace, campaign_id, email: str, before_iso):
    """The lead's latest real positive category from the replies archive -
    same campaign preferred (the pill edits the per-campaign category), then
    any-campaign fallback. None when no labelled row exists - the caller
    keeps the raw label rather than inventing a status."""
    if not _SB or not email:
        return None
    cats = ",".join(quote(f'"{c}"', safe="")
                    for c in sorted(CORE_FOUR - {_RE_REPLY_LABEL}))
    base = (f"replies?workspace=eq.{workspace}"
            f"&email=ilike.{quote(email, safe='')}"
            f"&category=in.({cats})"
            f"&select=category&order=replied_at.desc&limit=1")
    if before_iso:
        base += f"&replied_at=lt.{quote(str(before_iso), safe='')}"
    try:
        probes = ([f"&smartlead_campaign_id=eq.{campaign_id}"] if campaign_id else []) + [""]
        for probe in probes:
            rows = _SB("GET", base + probe)
            if isinstance(rows, list) and rows and (rows[0] or {}).get("category"):
                return rows[0]["category"]
    except Exception:  # noqa: BLE001 - resolution is display-truth, never load-bearing
        pass
    return None

# Uncategorised handling (ship 2026-07-20): replies the categoriser failed on
# or explicitly gave up on ("Uncategorizable by Ai" is the categoriser's own
# white-flag label) still enter setter_queue - flagged, never auto-drafted -
# so a hidden positive can be rescued from the UI instead of dying invisible.
# NULL, empty/whitespace and the legacy literal all count as "uncategorised".
UNCATEGORISED_LEGACY = "Uncategorizable by Ai"
# Fresh replies are routinely uncategorised for ~15min while the Make
# categoriser works (see handle_inbound) - only replies still uncategorised
# after this many hours are true stragglers worth queueing.
UNCAT_GRACE_HOURS = 2
# At most this many uncategorised intakes per poll tick - the positive sweep's
# own 15-cap must never be starved by a straggler backlog.
UNCAT_PER_TICK = 10


def _is_uncategorised_value(v) -> bool:
    s = str(v or "").strip()
    return (not s) or s == UNCATEGORISED_LEGACY


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


def _is_navreo_agent(agent: dict) -> bool:
    """The live Navreo-brand setter (not a client agent, not the 'Navreo copy'
    or dummy-trainer clones). Gated on the exact agent name, matching the
    house convention that Navreo-own is filtered by name, not client id."""
    return str((agent or {}).get("name") or "").strip().lower() == "navreo"


def _booking_link(agent: dict) -> str:
    """The single Calendly link used when no two-slot answer applies.
    Derived from calendly_event_url (trailing slash stripped) unless an
    explicit legacy booking_link is still set on the doc.

    The Navreo brand retired its standalone backup booking link (owner ruling
    2026-08-17): the two offered call-time slot links stay (those come from
    calendly_event_url via _slot_link, not from here), but there is no separate
    "book a call here" fallback link. Returning "" here makes every downstream
    surface (draft payload, lint ctx) see Navreo as having no backup link, and
    the drafter/lint then fall back to asking the lead to suggest times."""
    agent = agent or {}
    if _is_navreo_agent(agent):
        return ""
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

# Client MONITOR rows are review-only, so the Setter should only surface the
# ones a human must actually act on: positives (reply / booking) and replies
# still uncategorised (need triage - could be a positive the categoriser
# hasn't labelled yet). Clear non-positives - Out Of Office, Not Interested,
# Wrong Person, Do Not Contact, bounces, Uncategorizable - need no reply and
# are kept OUT of the queue entirely (Bjion 2026-08-04, once client
# federation was confirmed live; before that the monitor gate was
# deliberately open to prove intake worked at all). Exact-match, never
# substring: "Not Interested" must not be caught by "Interested".
_MONITOR_SURFACE_POSITIVE = {c.lower() for c in POSITIVE_CATEGORIES} | {
    "call booked", "positive-re-reply",
    "interested reply [manual]", "meeting request [manual]",
}


def _monitor_should_surface(category) -> bool:
    """True iff a client monitor reply is worth a human's attention: a
    positive, or still uncategorised. Everything else (clear non-positive)
    is skipped so it never clutters Needs review."""
    if _is_uncategorised_value(category):
        return True
    return str(category).strip().lower() in _MONITOR_SURFACE_POSITIVE

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
    """Best-effort IANA timezone plus whether it is CONFIDENT. A deterministic
    hit (company country/state/city, phone country code, ccTLD) is always
    confident. Otherwise the model's educated guess (inferred from the
    company/domain/signature, like a person glancing at LinkedIn) is used even
    when weak. Owner ruling 2026-08-15: this NEVER returns None any more -
    with zero signal of any kind we assume Eastern Time (America/New_York),
    because most leads are US and a concrete proposed time (labelled ET by
    _slot_label) beats a bare availability ask every time. tz_unknown is dead
    as an outcome. Returns (tz, confident)."""
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
    return "America/New_York", False


# ── slot picking + labelling ─────────────────────────────────────────────────


def slot_situation(slot_status: str, tz, slots, error: str = "") -> dict:
    """The WHY behind the call-time outcome, as two guardrails-jsonb keys
    ({slot_status, slot_reason}) persisted at every draft site. The UI used to
    reverse-engineer this from decision_reason text, which went generic (or
    silent) whenever the hold reason was about something else entirely — e.g. a
    row held for "wants custom work" with a known timezone showed a bare
    "no call times proposed" and the reviewer couldn't tell whether Calendly was
    empty, disconnected, or broken (owner report 2026-08-09)."""
    status = slot_status or "not_configured"
    n = len(slots or [])
    if status == "ok" and n:
        reason = f"{n} call time{'' if n == 1 else 's'} proposed in {tz}."
    elif status == "none_available":
        reason = (f"Timezone known ({tz}), but Calendly had no bookable slots inside the "
                  "booking window — the draft offers the booking link instead.")
    elif status == "error":
        detail = f" ({str(error)[:120]})" if error else ""
        reason = (f"Couldn't load Calendly availability{detail} — the draft falls back "
                  "to the booking link.")
    else:  # not_configured (and any future unknown status degrades to this)
        reason = ("No Calendly is connected for this agent, so no live times could be "
                  "offered — the draft uses the booking link.")
    return {"slot_status": status, "slot_reason": reason}


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


def pick_slots(avail_iso: list, tz: str, settings: dict, now_utc,
               exclude_isos=None, not_before_utc=None, horizon_days_override=None) -> list:
    """avail_iso: raw ISO8601 UTC availability from Calendly. Filters to
    workdays, [work_start, work_end) lead-local hours, within the next
    HORIZON_WORKING_DAYS working days, >= 20h out. Earliest-slot rule: the
    first slot offered is simply the earliest qualifying one; the second is
    the same day at least 2 hours later if one exists, else the next
    available day's earliest slot. Returns [{iso, label, link}]. link uses
    settings['_agent'] (calendly_event_url) and settings['_lead']
    (first_name/last_name/email).

    The three optional arguments exist for "Regenerate with feedback" (owner
    report 2026-07-25: "offer different times" / "offer next week" made no
    difference). They only ever NARROW or SHIFT the real calendar - a time
    that Calendly did not return can never be produced this way, so the
    never-invent rule is untouched:
      exclude_isos          - local ISO strings already proposed, skipped now
                              ("offer different times")
      not_before_utc        - hard floor replacing the 20h one ("next week")
      horizon_days_override - widen the search window to reach that floor
    Every existing call site passes none of them and behaves exactly as before."""
    exclude = {str(x) for x in (exclude_isos or [])}
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
    try:
        if horizon_days_override:
            horizon_days = max(horizon_days, int(horizon_days_override))
    except (TypeError, ValueError):
        pass

    now_utc = _parse_iso(now_utc) if not isinstance(now_utc, _dt.datetime) else (
        now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=_dt.timezone.utc))
    floor_utc = now_utc + _dt.timedelta(hours=20)
    if not_before_utc is not None:
        try:
            nb = _parse_iso(not_before_utc) if not isinstance(not_before_utc, _dt.datetime) else not_before_utc
            if nb.tzinfo is None:
                nb = nb.replace(tzinfo=_dt.timezone.utc)
            floor_utc = max(floor_utc, nb)
        except (ValueError, TypeError):
            pass

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
        if utc_dt < floor_utc:
            continue
        if exclude and local.isoformat() in exclude:
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


# ── how hard to push for a call on this turn (owner report 2026-07-25) ────

# Phrases in the LEAD's newest message that mean a call is already settled -
# proposing times again reads as not having listened.
# HARD markers stand on their own.
_CALL_SETTLED_RE = re.compile(
    r"\b(i(?:'ve| have)? booked|just booked|booked (?:a|the) (?:call|slot|time)|"
    r"invite (?:is )?(?:sent|accepted)|see you (?:then|on|at)|"
    r"calendar invite|call is (?:booked|set)|"
    # The call is happening RIGHT NOW (training panel 2026-08-16: 'waiting to
    # enter now' still drew a two-slot pitch 1 run in 3) - nothing could be
    # more settled than a call in progress.
    r"waiting to (?:enter|join)|joining (?:now|the call)|dial(?:ing|ling) in|"
    r"(?:trying|about) to join|on the call now|running \d+ ?min(?:ute)?s? late|"
    r"are you (?:coming|joining)|link isn'?t working|wrong (?:link|place))\b", re.IGNORECASE)
# SOFT markers only count alongside an actual day or time. "That works" and
# "does X work" are the give-away here: "does the pricing work for a smaller
# list?" is a question to answer, not a call being agreed - reading it as
# settled would suppress the call ask on exactly the replies that need one.
_CALL_SETTLED_SOFT_RE = re.compile(
    r"\b(works for me|that works|how about|confirmed|"
    r"i'?m free|does (?:\w+\s+){0,3}(?:work|suit))\b", re.IGNORECASE)
_TIME_TOKEN_RE = re.compile(
    r"\b(mon|tue|tues|wed|weds|thu|thur|thurs|fri|"
    r"monday|tuesday|wednesday|thursday|friday|"
    r"tomorrow|next week|this week|\d{1,2}\s*(?:am|pm)|\d{1,2}:\d{2}|o'?clock)\b",
    re.IGNORECASE)
# Marks in OUR side of the thread that a call has already been proposed.
_CALL_OFFERED_RE = re.compile(
    r"\b(would you be free|are you free|book a call|grab a slot|my availability|"
    r"a good time for us to talk|find a time)\b", re.IGNORECASE)

# A lead telling us the conversation stays in email, or naming a later
# window before we may come back. Judged on the unquoted reply only.
_NO_CALL_CHANNEL_RE = re.compile(
    r"\b(no calls?|don'?t do calls?|calls? (are|is) (impossible|not possible|difficult|tough)|"
    r"everything in writing|in writing,? please|email only|prefer email|over email,? please|"
    r"send (it|everything|the details) (over|via|by) email|rather not (do |have )?a call)\b",
    re.IGNORECASE)
_DEFERRAL_RE = re.compile(
    r"\b(not until|don'?t (reach|contact|call)[^.]{0,30}until|until (next|the new) year|"
    r"ping me in|circle back in|reach (back )?out in|follow up (in|after)|"
    r"pick (this|it) (back )?up (in|after|once|when)|"
    r"after (the )?(summer|holidays?|show|conference|event)|"
    r"(travell?ing|away|on leave|out of office) until|"
    r"(after|when|once) i'?m back|budget freeze|"
    r"(book|grab|find) (something|a (time|slot))[^.]{0,30}after)\b",
    re.IGNORECASE)


def call_ask_for(classification: dict, body_text: str, thread_text: str, first_touch: bool = True) -> str:
    """"required" | "only_if_relevant" | "avoid" - how hard THIS draft should
    push for a call. See the call_ask rule in DRAFT_SYSTEM.

    Owner report 2026-07-25: "when someone replies beyond the first message,
    sometimes the drafted response is a little bit out of touch ... just tries
    to continue offering a call even when it's not relevant." The call-times
    mandate was unconditional, so turn 3 of a conversation re-pitched a call
    the lead had already accepted or already declined to talk about.

    Deliberately conservative: only a clear signal moves it off "required", so
    a first-touch positive still gets the standard two-times ask."""
    classification = classification or {}
    intents = set(classification.get("all_intents") or [])
    primary = classification.get("primary_intent") or ""
    body = _strip_quoted(str(body_text or ""))
    # Channel preferences ("everything in writing") and explicit deferrals
    # ("ping me in February", "traveling until Nov 5") beat EVERYTHING -
    # including a scheduling intent (training rounds 1-4, 2026-08-16: the
    # founding "don't reach out until next year, but I'm interested in a
    # call" classifies as scheduling, so the old order forced call_ask=
    # "required" and the prompt-level constraint had to out-argue the whole
    # slot machinery on every draft - it lost roughly 1 in 3).
    if _NO_CALL_CHANNEL_RE.search(body) or _DEFERRAL_RE.search(body):
        return "avoid"
    # They have settled the call themselves (or it is happening right now) -
    # answering with two fresh times is the exact "out of touch" reply that
    # was reported. Checked BEFORE the scheduling intent: "are you coming?"
    # and "waiting to enter now" classify as scheduling, and the old order
    # handed them call_ask="required" (training panel 2026-08-16).
    if _CALL_SETTLED_RE.search(body):
        return "avoid"
    if _CALL_SETTLED_SOFT_RE.search(body) and _TIME_TOKEN_RE.search(body):
        return "avoid"
    # They are asking to book, or asking about times: always ask.
    if "scheduling" in intents or primary == "scheduling":
        return "required"
    if first_touch:
        return "required"
    # Later turn, not about scheduling, and we have already put a call on the
    # table: answer what they actually asked, offer times only if it helps.
    if _CALL_OFFERED_RE.search(str(thread_text or "")):
        return "only_if_relevant"
    return "required"


# ── "offer different times" / "offer next week" (owner report 2026-07-25) ──

_FB_DIFFERENT_RE = re.compile(
    r"\b(different|other|alternative|another|new|fresh)\s+(times?|slots?|days?|dates?)\b"
    r"|\bnot those times\b|\bchange the times?\b|\bsome other time\b", re.IGNORECASE)
_FB_NEXT_WEEK_RE = re.compile(r"\b(next|following)\s+week\b", re.IGNORECASE)
_FB_IN_WEEKS_RE = re.compile(r"\bin\s+(\d+|a|one|two|three)\s+weeks?\b", re.IGNORECASE)
_WEEK_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3}
_FB_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


def time_feedback_plan(feedback: str, tz: str, now_utc):
    """Reads reviewer feedback for a request about WHEN to offer, and returns
    {"want_change", "not_before_utc", "horizon", "said"} - or None when the
    feedback says nothing about times.

    This never invents a time: it only tells pick_slots to skip the slots
    already proposed and/or to start looking from a later date. Whatever comes
    back is still a real slot Calendly returned.

    Owner report 2026-07-25: "when you use regenerate and give it feedback
    like offer different times, or offer next week it doesn't matter"."""
    text = str(feedback or "").strip()
    if not text:
        return None
    want_diff = bool(_FB_DIFFERENT_RE.search(text))
    weeks_out = 0
    if _FB_NEXT_WEEK_RE.search(text):
        weeks_out = 1
    m = _FB_IN_WEEKS_RE.search(text)
    if m:
        word = (m.group(1) or "").strip().lower()
        weeks_out = max(weeks_out, int(word) if word.isdigit() else _WEEK_WORDS.get(word, 1))
    weekday_target = None
    low = text.lower()
    for i, day in enumerate(_FB_WEEKDAYS):
        if re.search(r"\b" + day + r"\b", low):
            weekday_target = i
            break
    if not (want_diff or weeks_out or weekday_target is not None):
        return None
    try:
        zi = ZoneInfo(tz or "Europe/London")
    except Exception:  # noqa: BLE001
        zi = ZoneInfo("Europe/London")
    now_utc = _parse_iso(now_utc) if not isinstance(now_utc, _dt.datetime) else (
        now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=_dt.timezone.utc))
    local_now = now_utc.astimezone(zi)
    not_before, horizon, said = None, None, []
    if weeks_out:
        # Start of the Nth week ahead, lead-local.
        days_to_monday = (7 - local_now.weekday()) + 7 * (weeks_out - 1)
        start = (local_now + _dt.timedelta(days=days_to_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        not_before = start.astimezone(_dt.timezone.utc)
        horizon = HORIZON_WORKING_DAYS + 5 * (weeks_out + 1)
        said.append("next week" if weeks_out == 1 else f"in {weeks_out} weeks")
    elif weekday_target is not None:
        ahead = (weekday_target - local_now.weekday()) % 7
        if ahead == 0:
            ahead = 7
        start = (local_now + _dt.timedelta(days=ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        not_before = start.astimezone(_dt.timezone.utc)
        horizon = HORIZON_WORKING_DAYS + 5
        said.append(_FB_WEEKDAYS[weekday_target].capitalize())
    if want_diff:
        said.append("different times")
    return {"want_change": True, "not_before_utc": not_before, "horizon": horizon,
            "said": " and ".join(said) or "different times"}


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
    # One ask, ever (owner rule 2026-08-17): a draft may never combine a
    # call-ask sentence with the open availability ask - destack_call_ask
    # repairs this at draft time, so tripping here means a path skipped it.
    _low_plain = _TAG_RE.sub(" ", text).lower()
    if _AVAIL_Q in _low_plain and any(p in _low_plain for p in _ASK_PHRASES):
        return False, "The draft asks for the call twice - one ask only."
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
    # A resource send that links ONLY the booking link is not a resource send
    # (owner report 2026-07-28: "Here is the resource I put together." went
    # out with the calendar as its only anchor, so the lead got no resource).
    # The booking link lives in the instructions too, so the check above is
    # satisfied by it - require a NON-booking instruction URL as well, but
    # only when the agent HAS one, so an agent whose instructions carry
    # nothing but a calendar link is unaffected.
    if ctx.get("needs_resource_link") and booking:
        resource_urls = instruction_urls - {_norm_url(booking)}
        if resource_urls and not (set(draft_urls) & resource_urls):
            return False, "The draft offers a resource but links only the booking link."
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
        #
        # But ONLY when a scheduling link actually exists to link. When there
        # is none anywhere - no booking link and no scheduling-host URL in the
        # instructions or thread (e.g. the Navreo brand, which retired its
        # backup link and carries no calendar URL) - the correct fallback is a
        # plain-text ask for the lead to suggest times, with no link, so don't
        # reject it here (owner ruling 2026-08-17).
        _sched_hosts = ("calendly.com", "savvycal.com", "cal.com")
        _has_sched = bool(booking) or any(
            any(h in u for h in _sched_hosts) for u in allowed_urls)
        if _has_sched:
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

    # 7. (retired) slots + timezone. This gate used to hold a reply when the
    # timezone was unresolved or a low-confidence guess, so a real send never
    # fired at a possibly-wrong hour. Owner ruling 2026-08-15: gone entirely -
    # if we know the timezone we ALWAYS recommend a time, and when we don't,
    # resolve_timezone() assumes Eastern (America/New_York) and the times are
    # labelled with their zone (ET etc.) by _slot_label, so the lead can see
    # exactly what was assumed. The label is the safety valve now, not a hold.

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
    r = _openai({"model": OPENAI_MODEL,
                 "messages": [{"role": "system", "content": CLASSIFY_SYSTEM},
                             {"role": "user", "content": user}],
                 "response_format": {"type": "json_schema", "json_schema": {
                     "name": "setter_classification", "strict": True, "schema": CLASSIFY_SCHEMA}}}, key)
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
<div>Hi Gustavo,</div><br><div>That's exactly what I'd walk you through on a quick call, where I could show how it applies to you.</div><br><div>If you're open to it, feel free to <a href="BOOKING_LINK">book a call here</a>.</div><br><div>Bjion</div>

CALL ASK, NO LIVE SLOTS BUT THE INSTRUCTIONS LIST CONCRETE AVAILABLE TIMES (fallback ladder step ONE-A - slot_status is anything but "ok" AND the instructions contain a concrete list of available times or time ranges, e.g. an auto-updated "Current Available Times" block):
<div>Hi Priya,</div><br><div>Would you be free for a call on Wednesday, 16th July at 1:00 PM EST or Thursday, 17th July at 10:30 AM EST, where I could share how I would implement our strategy for you?</div><br><div>If those times aren't suitable, you're welcome to <a href="INSTRUCTIONS_CALENDAR_LINK">grab a slot here</a>.</div><br><div>Bjion</div>

CALL ASK, NO LIVE SLOTS BUT THE INSTRUCTIONS GIVE ONLY A GENERAL WINDOW (fallback ladder step ONE-B - slot_status is anything but "ok" AND the instructions state only a general availability window or a scheduling/calendar link, with no concrete times listed):
<div>Hi Priya,</div><br><div>Would love to find a time that works for you.</div><br><div>I'm generally free WINDOW_FROM_INSTRUCTIONS, or you're welcome to grab a slot directly on <a href="INSTRUCTIONS_CALENDAR_LINK">my calendar</a>.</div><br><div>Bjion</div>

CALL ASK, NO TIMES AVAILABLE ANYWHERE (fallback ladder step TWO - slot_status is anything but "ok" AND the instructions say nothing at all about availability):
<div>Hi Priya,</div><br><div>Would love to find a time that works for you.</div><br><div>When would be a good time for us to talk? Here is <a href="BOOKING_LINK">my availability</a>.</div><br><div>Bjion</div>

Rules:
- WHERE A CALL TIME MAY COME FROM (read this before proposing any day or clock time). There are exactly two sources of a time: the slots you were given, and only while slot_status is "ok"; or a literal list of dates or times written out in the instructions as data (for example an auto-updated "Current Available Times" block). Nothing else is a source. In particular, a rule in the instructions that tells you HOW to write or choose a time is a FORMAT, not availability: a template ("Weekday, Dth Month at H:MM AM/PM EDT"), an example time shown to illustrate that template, a placeholder like [first specific time], a timezone rule, or an instruction to "take the slots from real availability on our calendar" all describe how to render a time you already have, and never mean that you have one. So when slot_status is anything but "ok" AND the instructions hold no literal list of times, you have NO times at all: ask for the lead's availability by the fallback ladder below, and do not name a weekday, a date, or a clock time anywhere in the draft. Never invent a time, day, or window that isn't in the slots you were given or literally stated in the instructions. This rule outranks the agent's instructions and any example in them: instructions written on the assumption that two call times exist do not authorise you to manufacture one when they don't. In particular, when the instructions mandate a fixed reply TEMPLATE that contains a time placeholder ("[first specific time]", "[second specific time]", or similar) and you have no time to put in it, you must NOT fill that placeholder with a time you worked out yourself, and you must NOT leave the placeholder in the draft. Instead keep every other block of that template exactly as the instructions demand, and swap the single line holding the placeholders for the availability ask from the fallback ladder below. Filling a template's time placeholder from a calendar you cannot see is inventing a time, no matter how firmly the template says to keep its blocks as written.
- Every draft must be built from short <div> paragraphs separated by <br>, exactly like the examples above. A single-line reply with no paragraph breaks will be rejected.
- Use the team's exact recurring phrases where they fit: the resource anchor is "Here's the breakdown I prepared." (or "Here's a case study I put together." when it's a case study); the call ask, ONLY when you have actual times to name, is "Would you be free for a call on {day, date at time TZ} or {day2, date2 at time2 TZ}, where I could share how I would implement our strategy for you?"; the fallback is "If those times aren't suitable, feel free to book a call here." with the link on "book a call here".
- ONE ASK, EVER (owner rule 2026-08-17: "You're asking for a call twice, don't do that"). A draft asks for the call at most once. The two-times call ask, a general-window proposal, and the "When would be a good time for us to talk?" availability ask are three ALTERNATIVES: exactly one may appear in a draft, never two. Each fallback-ladder step REPLACES the call ask, it never adds a second ask on top. A draft containing both "Would you be free for a call" and "When would be a good time" is invalid. Never write the call-ask sentence at all when you have no times to put in it. And never write the same sentence or phrase twice anywhere in one draft. A lead who has already said yes to a call, booked one, or shared THEIR OWN booking/scheduling link has chosen the path: confirm it (for their link: say you'll grab a time on it) and make ZERO fresh asks.
- The names in the examples above (Donald, Parag, Priya, and the sign-off) are placeholders from OTHER teams' threads. Sign ONLY {SenderFirst} - never copy "Bjion" or any example name into a draft.
- No em dashes anywhere, ever - use a comma or period instead.
- No emoji.
- Plain English, under 150 words total. The team's replies are short - do not pad.
- Only include the resource link/anchor when send_resource is one of the intents to answer.
- Resource links and when to send each one are in the instructions. When the lead should get a link, use the exact link from the instructions that matches the original_outreach and their ask. Never invent a link, never paste a link the instructions don't contain.
- Anchor text reads like the examples above - natural, first-person, never the bare resource title.
- When the intent is bespoke_request, objection_or_question, or wrong_person, the ack paragraph must acknowledge the lead's SPECIFIC ask honestly (e.g. "Happy to put a video together for you.") - never a generic "Of course." that ignores what they asked for, and never a promise of a date or deadline for the bespoke work.
- Never say you are sharing, attaching, or sending something the draft does not actually contain. If the asked-for asset is not the agent's fixed resource, acknowledge the ask ("Happy to get that over to you.") without implying it is included in this email.
- The ack paragraph must answer the SHAPE of the question. A yes/no question ("So you work on commission?") gets a direct, truthful opener grounded ONLY in the instructions ("It is a flat monthly fee rather than commission."), never "Of course."
- NEVER open with "Good question", "Great question", or any equivalent - it reads as patronising (owner rule 2026-08-17). Just answer. The same goes for reflective validation openers: never "Thanks for the detail", "That makes sense", "You're right to ask", "You're right to flag", "I hear the concern", "I appreciate the detail", or any restating of their situation back at them as an opener. Real reps answer in the first sentence.
- YOU are the person on this thread - own every answer in first person. Never say you will "escalate this to the team", "pass this to the team", or hand the question to some third party: when the exact terms aren't in the instructions, say it as yourself ("I'll confirm the exact terms and come back to you") - and that sentence is the WHOLE answer for a contract/legal/pricing question the instructions don't cover. First-person ownership NEVER licenses inventing the answer: "it is a standard engagement, not a lock-in, you can pause at the end of any month" is a fabricated contract claim unless the instructions state those exact terms (owner rule 2026-08-17: "Kevin is the person to answer this" - Kevin answers as himself, he does not make terms up).
- BEFORE writing anything, decide the greeting name: FIRST look at the end of their reply for a signed name ("Thanks, Cole" / "Kelly, Head of Partnerships" means greet "Hi Cole" / "Hi Kelly") - how the lead signed their LATEST message is ground truth and OUTRANKS lead_first_name whenever the two differ (signed "Stan Takahashi" with lead_first_name "Kathy" means greet "Hi Stan"); otherwise use lead_first_name if it is a real personal name (it is "" when we don't have one, "there" is a placeholder, and a company name or a word chopped off one - "Organic" from "Organic Beauty Transformation" - is never a personal name); otherwise LOOK AT THE GREETING LINE OF original_outreach, which opens "Hi <first name>," and names this same lead; only if no name exists in any of those three places use "Hi there". Always greet with the FIRST name alone - never a full name ("Hi Janos", never "Hi Janos Stegena") and never a quoted nickname from a signature block. NEVER greet the lead with SenderFirst - that is OUR name, used only in the sign-off. When the draft genuinely addresses two or more people (for example the lead just introduced a colleague), join the names with "and" - "Hi John and James" - never a comma list like "Hi John, James,".
- If they ask for "the video" and the agent's fixed resource is NOT a video, never present the resource link as if it were the video. Acknowledge the video ask specifically and honestly; the human reviewer will attach the right asset.
- If a question's answer is NOT in the instructions or the resource, do not improvise one - but never dodge the question either. FIRST answer it with everything you truly have: any fact the LEAD themselves stated in this thread (their team size, their CRM, their stack, their constraints) must be named and used ("For a 12-person team running your own LinkedIn outbound..."; "Since you run everything through HubSpot..."), and anything the instructions DO answer must be answered plainly. Only THEN, for the specific part you genuinely cannot answer, make that named gap the reason for the call ("exactly how it would sit alongside HubSpot is what I'd walk you through on a quick call") - unless a stated channel or timing constraint applies (see constraint_directive), which always wins over this - never a bare "That's exactly what I'd walk you through on a quick call" that ignores the lead's own stated facts; that reads as not having read their email. Engaging their facts NEVER licenses asserting a mechanism: if the instructions don't state how something works (an integration, a data mapping, a process, a guarantee), do not describe it as if it exists ("we would map our outbound data into your CRM" is an invented claim unless the instructions say so) - name their fact, put the HOW behind the call. One carve-out (owner rule 2026-08-16): a question about PROCESS - "what would the first month look like?", "what happens after we start?" - may be answered with a natural plain-English description of how an engagement typically runs, even when the instructions don't spell it out; hard facts (prices, numbers, dates, guarantees, integrations) stay instruction-only. Answer ONLY what they asked: never bolt on an unasked section, and never write "you asked for X" / "here is the X you asked for" about something their message did not ask for. Guessing at policies, capabilities, or processes is still worse than not answering.
- If SenderFirst is empty, end with no sign-off line at all.
- Whenever slots are supplied and slot_status is "ok" you MUST include the two call-time paragraph, with each day/time as an anchor whose href is that slot's own link, exactly as in the RESOURCE + CALL example, followed by the "If those times aren't suitable" booking-link paragraph. This is the DEFAULT and does not depend on the intent: a resource send, a pricing answer, or a question we can't fully answer all still get the two call times when live slots exist. Three things, and only these three, override that default. FIRST, a stated constraint: the lead's stated timing or channel constraint (see the constraint rule below) suppresses call times and booking links entirely - it always wins. SECOND, call_ask: when call_ask is "avoid" the lead is already sorted for a call (a time is agreed, they have booked, or they have just told you when they are free) or has asked something that a fresh call pitch would talk straight past - answer THAT message on its own terms and do not propose times again; when call_ask is "only_if_relevant" a call has already been offered earlier in this thread and their latest message is not about scheduling, so lead with the actual answer and only reach for times if the answer genuinely needs a call; when call_ask is "required" or absent, the default above stands. Never re-propose times a lead has already turned down or already accepted. THIRD, reviewer_feedback about WHICH times to offer ("offer different times", "offer next week"): the slots you have been given have ALREADY been re-picked from the real calendar to match that request, so propose exactly the slots in front of you and do not apologise for or refer to the times a previous draft proposed. You still never invent a time: if the feedback asks for times the calendar cannot supply, say so in feedback_note and use the fallback ladder instead of making one up. Use every slot link you were given, verbatim, and never drop a slot in favour of the booking link alone. Conversely, never propose call times from live slots when slot_status is anything but "ok". When call times are NOT available (slot_status is anything but "ok"), follow this fallback ladder, in order, and never skip a step that applies: ONE-A, if the instructions contain a CONCRETE list of available times or time ranges (for example an auto-updated "Current Available Times" block), meaning real dates or times written out as data and never a formatting template, an example time, or a rule about where times come from, pick exactly TWO different times from that list (two different days when possible) and propose them in the same phrasing as the normal two-call-times ask, as plain text (no per-slot deep links exist here). current_datetime_utc tells you when NOW is: never propose a listed time that is already in the past or later today - only listed times from tomorrow (in the lead's timezone) onwards count. When the list contains two or more future times you MUST propose exactly two, never just one; only when it holds a single future time may you propose one, and when it holds none treat the instructions as giving only the calendar link (step ONE-B). Obey any timezone rule the instructions state: when you know the lead's timezone, convert each proposed time into it and label it with that timezone - converting means changing the clock time itself, never just swapping the timezone label; when you don't, send the times exactly as listed with the timezone label the instructions use. Then hyperlink the scheduling/calendar link the instructions give in its own short follow-up paragraph ("grab a slot here"). ONE-B, if the instructions state only a general availability window or just a scheduling/calendar link, propose a meeting using exactly what the instructions say, their own words for the window, and hyperlink the calendar link the instructions give, as its own paragraph. TWO, only when the instructions say nothing at all about availability, ask exactly this, as its own paragraph: "When would be a good time for us to talk? Here is <a href="BOOKING_LINK">my availability</a>." using the real booking_link value you were given as the href. Never invent a time, day, or window that isn't in the slots you were given or literally stated in the instructions - and never copy an example's availability wording from this prompt (the windows and times in the examples above are placeholders, not facts). Never mention that a calendar, tool, or booking system failed or wasn't available - the lead should never sense anything went wrong.
- NO BACKUP BOOKING LINK. When booking_link is empty, there is NO standalone backup booking link, so you must NOT output a "book a call here" paragraph, a "my availability" booking-link paragraph, or ANY standalone booking/scheduling link anywhere in the draft. The two call-time paragraph (each time its own per-slot link) is unchanged when live slots exist. Wherever the examples show the "If those times aren't suitable, feel free to book a call here" booking-link fallback paragraph, write instead this plain-text paragraph with NO link: "If those times aren't suitable, feel free to suggest some times that work for you." And when there are no call times at all, ask for the lead's availability with that same plain-text sentence, never a booking or calendar link. This overrides the RESOURCE + CALL example's fallback line and every fallback-ladder step that would otherwise carry BOOKING_LINK.
- If pricing is one of the intents, quote the instructions content verbatim (the actual numbers/structure) rather than paraphrasing them away.
- If the intent needs a human (bespoke, objection, other, wrong_person, etc.) still write a warm, honest best-effort draft for a human to edit - never invent a fact, number, or promise not present in the resource, instructions, or thread; keep it short and let the human add specifics.
- Never invent a number, date, or fact that isn't in the instructions, the reply thread, or the call-time slots given to you. Never claim a resource covers a specific topic (a fix, a policy, a category, a mechanism) unless the instructions state that it does - "here's the breakdown, it covers exactly how we'd handle your verification issue" is an invented claim when the instructions never say so.
- Match the tone AND the exact recurring phrasing of the real examples above - the goal is a reply indistinguishable from what the team actually sends.
- original_outreach is the first email we sent this lead. Keep the reply consistent with what it actually offered - answer the thing they were pitched, so the message reads like a real continuation of that thread, not a generic template. Use the lead's facts in YOUR OWN words - never mirror their phrasing back at them ("would this work across all 40 locations?" answered with "whether this would work across all 40 locations" reads as an AI parroting; say it the way a person would: "Franchise groups are exactly where this fits - each location gets..." - owner rule 2026-08-16).
- The reason you give for a call must be the thing THIS thread actually offered: if the outreach pitched an idea, the call is to show them that idea; a video, the video; a breakdown, the breakdown. Never swap in a generic "a demo and how we'd set it up" reason the thread never mentioned (owner rule 2026-08-16: "if it's an idea, the call to action would be the idea, not a demo").
- When this draft CONFIRMS a call - a time is agreed, they booked, or the lead gave their own booking link for us to use - the confirmation always has two parts (owner rule 2026-08-16, every agent, every campaign): the booking statement and the "You will be speaking with [name]." close. The bracketed placeholders exist ONLY for a booking that has NOT happened yet (the reviewer books on the lead's link after this draft, then fills [day and time] in). When the thread already names the time - the lead booked a slot ("I grabbed the 3pm Tuesday slot"), accepted one, or proposed one that this draft accepts - you MUST write that real day and time and NEVER the [day and time] placeholder; replying "I've booked in for [day and time]" to a lead who just told you they booked Tuesday 3pm reads as not having read their email. Confirm THEIR act in natural words ("Tuesday at 3pm is confirmed") rather than claiming "I've booked" something they booked. [name] stays a placeholder unless the thread makes plain who will be on the call.
- recent_thread, when present, is a transcript of this thread, oldest first: lines starting "US" are emails WE sent, lines starting "LEAD" are the lead's replies, and the final LEAD line is the same message as reply_body - the one you are answering now. Read the WHOLE transcript before writing: a later-turn reply must read as a natural continuation of it, never repeating something already said, never re-introducing yourself, and never re-pitching what the transcript shows was already offered, answered, declined, or agreed.
- Anything the lead has stated as a condition or constraint anywhere in the thread - and above all in their latest reply - binds the draft, even when it sits beside interest. A stated timing ("not until next year", "reach out after the summer", "busy until Q3") means propose NO call time now, even when slots were supplied and even when call_ask says times are the default: acknowledge their interest, defer to their timing in one natural sentence ("I'll circle back in the new year as you suggested"), and ask for nothing more. A stated channel or contact preference ("email only", "send it over rather than a call", "speak to my colleague") is obeyed the same way - the constraint always outranks the call-times default and every template mandate. Under a stated constraint, the open availability ask ("when would be a good time to talk?") counts as proposing a call and is equally banned. And a visible phone number is not a call request: only offer to ring the lead when they ASKED to be called - a number in a signature, or a request for terms or info "via WhatsApp", means send the content they asked for, not a call offer.
- reviewer_feedback, when present, is the human reviewer's instruction for THIS regeneration ("shorter", "don't offer times", "mention the guide is free") - follow it faithfully while keeping every rule above. It never overrides the never-invent rules.
- reviewer_feedback/owner_corrections may contain a LATEST OWNER RULES block: those rules are the owner's newest teaching and take priority over everything else, including older instructions - obey them exactly.
- feedback_note is ONLY about reviewer_feedback, and only about the part you could NOT honour. When reviewer_feedback asks for something you have NO source for (a resource link when the instructions contain none, a fact or asset not present in the instructions, thread, or slots), do NOT invent it and do NOT silently ignore the ask - write one plain-English sentence in feedback_note saying what you couldn't do and why, plus what would unblock it (e.g. "No agent is assigned to this campaign, so I have no resource links to include - assign an agent or paste the link into the draft manually."). Never use feedback_note for gaps the reviewer didn't raise: a missing booking link, missing call slots, empty instructions, or any other limitation is NOT feedback_note material unless reviewer_feedback itself asked for that thing. When you honoured the feedback fully, or there is no reviewer_feedback, feedback_note must be exactly "".
- Output STRICT JSON: {"subject": "...", "html": "...", "feedback_note": "..."}. subject should read "Re: {original subject}" (or a sensible one if none given). html is the full reply body, written as the div/br block-paragraph shape shown above, using <a href="..."> for links, never markdown, never one run-on line."""


_TRANSCRIPT_MSG_CAP = 600     # per-message ceiling inside the transcript
_TRANSCRIPT_BUDGET = 2600     # whole-transcript ceiling


def _thread_transcript(thread: list) -> str:
    """The stored thread as a labelled transcript for the drafter: one block
    per message - "US (Jane, 14 Jul): ..." / "LEAD (15 Jul): ..." - oldest
    first, each body run through clean_body() so markup and quoted history
    never reach the model. The budget walks NEWEST-first, so when a thread is
    long it is the OLDEST turns that drop - the old space-join was
    head-truncated in draft_reply ([:1200]), which handed a 3rd/4th-turn
    draft a fragment of the ORIGINAL outreach and silently dropped the very
    turns (constraints, agreements, answers) a deep-thread reply must honour
    (owner report 2026-08-16)."""
    blocks = []
    used = 0
    for m in reversed(thread or []):
        if not isinstance(m, dict):
            continue
        text = re.sub(r"\s+", " ", clean_body(str(m.get("body") or ""))).strip()
        if not text:
            continue
        if len(text) > _TRANSCRIPT_MSG_CAP:
            text = text[:_TRANSCRIPT_MSG_CAP].rstrip() + " ..."
        who = "US" if str(m.get("type") or "").upper() == "SENT" else "LEAD"
        detail = []
        if who == "US" and m.get("from_name"):
            detail.append(str(m["from_name"]).split()[0])
        try:
            detail.append(_parse_iso(str(m.get("time"))).strftime("%d %b"))
        except Exception:  # noqa: BLE001 - the date label is decoration, never load-bearing
            pass
        block = (f"{who} ({', '.join(detail)}): " if detail else f"{who}: ") + text
        if blocks and used + len(block) > _TRANSCRIPT_BUDGET:
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(reversed(blocks))


def draft_reply(reply: dict, agent: dict, classification: dict, slots: list, slot_status: str, sender_first: str,
                regen_feedback: str = "") -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    reply = reply or {}
    agent = agent or {}
    classification = classification or {}
    payload = {
        # "" when unknown, never "there" (owner report 2026-07-28: the old
        # "there" fallback was handed to the model as if it WERE the lead's
        # name, so the greeting rule's first branch always fired and the
        # reply-signature / outreach-greeting fallbacks below it never ran -
        # every nameless reply got "Hi there" even when the original
        # outreach opened "Hi David,").
        "lead_first_name": reply.get("first_name") or "",
        "original_subject": reply.get("subject") or "",
        "original_outreach": (reply.get("first_outbound") or "")[:1500],
        # clean_body, not raw: the redraft path passed the stored reply_body
        # verbatim, so a full-HTML Outlook reply could spend the whole 3000
        # cap on markup and push the lead's actual words past it. clean_body
        # is a no-op on already-clean text, so the live path is unchanged.
        "reply_body": clean_body(reply.get("body") or "")[:3000],
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
    # No live slots: restate the never-invent-a-time rule IN THE USER MESSAGE,
    # right beside the instructions it has to beat. DRAFT_SYSTEM has carried
    # that rule (fallback ladder) all along, but an agent's own instructions
    # can mandate a fixed reply template with a "[first specific time]"
    # placeholder and an "add nothing else" clause - concrete, imperative, and
    # sitting in the user message. Measured on live row 1222 (Navreo agent,
    # slots: []) 2026-07-28: with the rule only in the system prompt the
    # drafter filled that placeholder with times it worked out itself 3/3 at
    # reasoning_effort=minimal, echoing the instructions' own example date
    # ("Wednesday, 29th July at 2:00 PM EDT") back at the lead. lint_draft
    # caught every one, so nothing sent, but the draft was wasted. The
    # "literal list" carve-out keeps fallback ladder step ONE-A alive: an
    # agent whose instructions DO list real times still proposes them.
    # When there is a backup booking link, the no-slots fallback ends with the
    # "Here is my availability" booking-link paragraph. When there is none
    # (booking_link empty - e.g. the Navreo brand, which retired its backup
    # link), that same fallback becomes a plain-text ask for the lead to
    # suggest times, with NO link (owner ruling 2026-08-17).
    if payload["booking_link"]:
        _step2_fallback = (
            "with exactly this, as its own paragraph: \"When would be a good time "
            "for us to talk? Here is <a href=\"BOOKING_LINK\">my availability</a>.\", putting the real "
            "booking_link value in the href."
        )
    else:
        _step2_fallback = (
            "with exactly this plain-text paragraph, containing NO link: \"When would be a good time "
            "for us to talk? Feel free to suggest some times that work for you.\" There is no backup "
            "booking link, so never output a booking or calendar link here."
        )
    if (slot_status or "not_configured") != "ok" or not slots:
        payload["no_live_slots_directive"] = (
            "You were given NO call times for this draft. Follow the fallback ladder in your rules. "
            "Nothing in `instructions` is availability unless it is a literal list of dates or times "
            "written out as data: a reply template, a placeholder such as [first specific time] or "
            "[second specific time], a formatting rule, an example time, or a rule about taking times "
            "from a calendar are NOT availability, and you must never fill one in with a time you "
            "worked out yourself. If `instructions` holds no such literal list, name no weekday, no "
            "date, and no clock time anywhere in the draft. Where a mandated template has a line that "
            "proposes times, keep every other block of that template exactly as required and rewrite "
            "that ONE line in two steps, even where the template says to keep every block as written "
            "or to add nothing else. STEP 1: drop the times from the ask while keeping the template's "
            "own reason-for-the-call wording word for word, so a line shaped like \"Would you be open "
            "to a call on [first specific time] or [second specific time], where I could WORDING?\" "
            "becomes \"Would you be open to a call, where I could WORDING?\". STEP 2: replace the "
            "template's \"if those times aren't suitable\" style fallback line (there are no times "
            "for it to refer to) " + _step2_fallback
        )
    # No standalone backup booking link (booking_link empty): the slots-ok
    # fallback line must ask the lead to suggest times in plain text instead of
    # the "book a call here" booking-link paragraph. Sits in the user message,
    # beside the instructions it has to beat (same mechanics as the directives
    # above), so it overrides the RESOURCE + CALL exemplar in DRAFT_SYSTEM.
    if not payload["booking_link"]:
        payload["no_backup_link_directive"] = (
            "There is NO backup booking link for this agent. Never output a \"book a call here\" "
            "paragraph, a \"my availability\" booking-link paragraph, or any standalone booking or "
            "calendar link anywhere in the draft. When live slots exist, keep the two call-time "
            "paragraph exactly as required, each time carrying its own per-slot link, then replace "
            "the \"If those times aren't suitable, feel free to book a call here\" booking-link "
            "paragraph with exactly this plain-text paragraph, containing NO link: \"If those times "
            "aren't suitable, feel free to suggest some times that work for you.\""
        )
    # Lead-stated constraints must beat the agent's own template mandates
    # (training round 1, 2026-08-16): with the law only in DRAFT_SYSTEM the
    # drafter ACKNOWLEDGED a deferral ("I'll grab a slot for after Oct 2
    # then") and STILL appended the mandated two-call-times paragraph with
    # this week's slots, 5/12 scenarios. Same mechanics as
    # no_live_slots_directive: the rule must sit in the user message, beside
    # the instructions it has to beat, with the literal surgery spelled out.
    payload["constraint_directive"] = (
        "FIRST, before writing, scan reply_body and recent_thread for any constraint on how we "
        "proceed - stated by the lead OR already established by either side earlier in the thread: "
        "a timing deferral ('not until next year', 'after the summer', 'mid-September', 'back Oct "
        "2', 'pick this up the week of Sept 14'), a pause ('let's hold off', 'things have blown up "
        "here'), a channel preference ('email only', 'no calls', 'just send it over'), a handoff "
        "to a colleague, a call that is ALREADY booked, agreed, rebooked, or being confirmed "
        "anywhere in the thread, or a call happening RIGHT NOW ('waiting to enter', 'joining now', "
        "'are you coming?', 'running 5 min late'). If ANY such constraint exists, it outranks the "
        "two-call-times default, the whole fallback ladder INCLUDING every step of "
        "no_live_slots_directive (do not perform its STEP 1/STEP 2 rewrite - its 'When would be a "
        "good time for us to talk?' replacement line must NOT appear), and every mandated "
        "template: you MUST NOT propose any day, date, or clock time of your own, MUST NOT use "
        "the slots you were given, and MUST NOT include any call ask in ANY phrasing ('Would you "
        "be open to a call on ...', 'Would you be open to a call, where ...', 'worth a quick "
        "chat'), the 'If those times aren't suitable' line, the 'When would be a good time for "
        "us to talk?' line, or any booking-link/availability ask - drop those paragraphs "
        "entirely, even where a template says to keep every block as written. A channel "
        "preference means the ENTIRE reply happens in that channel: deliver the substance in "
        "the email itself and ask for nothing else - this outranks every rule that says to make "
        "a gap the reason for a call. Instead: answer their actual message, acknowledge the constraint in one natural "
        "sentence and defer to it ('I'll circle back in January as you suggested'). BUT when "
        "the lead gave their OWN booking link - even inside a deferral ('book after Nov 5 via "
        "my link') - never a future-tense promise like 'I'll book something after...': the "
        "reviewer books BEFORE this email is sent, so you MUST include, verbatim and as its "
        "own paragraph: \"I've booked in for [day and time]. You will be speaking with "
        "[name].\" - write the bracketed placeholders exactly as shown; the reviewer fills "
        "them in after booking on the lead's calendar. When a call is "
        "already booked or a proposed time is being accepted, write that REAL day and time "
        "(never the [day and time] placeholder - it is only for bookings that have not "
        "happened yet), close with the same \"You will be speaking with [name].\" line, and "
        "add nothing new. When "
        "the call is happening right now, one short human line only ('No worries - see you in "
        "there.') with no links and no scheduling. Two things are NOT constraints: a lead "
        "actively trying to schedule sooner or on a different day ('how about next week?', "
        "'Friday works') - propose times as normal, honouring their preference; and "
        "reviewer_feedback that explicitly asks for times, which always wins.")
    # How hard to push for a call on THIS turn - see the call_ask rule in
    # DRAFT_SYSTEM. Owner report 2026-07-25: "when someone replies beyond the
    # first message, sometimes the drafted response ... just tries to continue
    # offering a call even when it's not relevant." The mandate used to be
    # unconditional, so a second- or third-turn reply got a fresh call pitch
    # no matter what the lead had actually said. Callers that don't compute it
    # (every pre-existing one) leave it absent and get the old default.
    call_ask = str(reply.get("call_ask") or "").strip()
    if call_ask in ("required", "only_if_relevant", "avoid"):
        payload["call_ask"] = call_ask
    # The lead's timezone, when known (owner report 2026-08-01: "even when the
    # AI knows their timezone, it still doesn't surface or suggest a time, or
    # say why it didn't"). DRAFT_SYSTEM has always said "when you know the
    # lead's timezone, convert each proposed time into it" — but the payload
    # never carried the timezone, so that branch could never fire. Live slots
    # arrive already lead-local (pick_slots converts); this makes
    # instruction-listed times and any scheduling language lead-local too,
    # and turns a silent no-time draft into an explained one.
    tz_name = str(reply.get("timezone") or classification.get("timezone_guess") or "").strip()
    if tz_name:
        # Only assert a timezone the zone database actually resolves (panel
        # fix 2026-08-01): a bad string would have told the model to convert
        # into a zone that doesn't exist while pick_slots silently fell back
        # to Europe/London — a recipe for wrong clock times.
        try:
            from zoneinfo import ZoneInfo
            local_now = _dt.datetime.now(ZoneInfo(tz_name)).strftime("%A, %d %B %Y, %H:%M")
        except Exception:  # noqa: BLE001 - an unresolvable zone gets no directive at all
            tz_name = ""
        if tz_name:
            payload["lead_timezone"] = tz_name
            payload["lead_local_now"] = local_now
            payload["timezone_directive"] = (
                "lead_timezone is this lead's IANA timezone and lead_local_now is their clock "
                "right now. The labels on any `slots` you were given are ALREADY in the lead's "
                "timezone - never re-convert a slot label. A literal availability list from the "
                "instructions, though, must be converted into the lead's timezone with a clear "
                "zone label. If scheduling is on the table but you end up proposing no concrete "
                "time, explain why in feedback_note (for example: no live availability was "
                "supplied) - never skip the time silently.")
    # Thread continuity (multi-turn autonomy): when the caller passes the
    # stored thread list, build the labelled transcript so the model knows
    # who said what and the newest turns always survive the budget. The bare
    # thread_text string stays as the fallback for older callers - tail-kept,
    # not head-kept, because the newest text is the part a later-turn draft
    # must honour.
    transcript = _thread_transcript(reply.get("thread") or [])
    if transcript:
        payload["recent_thread"] = transcript
    else:
        thread_raw = str(reply.get("thread_text") or "").strip()
        if thread_raw:
            thread_clean = re.sub(r"\s+", " ", _TAG_RE.sub(" ", thread_raw)).strip()[-_TRANSCRIPT_BUDGET:]
            if thread_clean:
                payload["recent_thread"] = thread_clean
    if (regen_feedback or "").strip():
        # 4000, not 500: the feedback carries the LATEST OWNER RULES block
        # (~1600 chars) plus the session digest (~2000). The old 500-char cap
        # silently discarded almost all teaching before the drafter saw it -
        # the root cause of "it keeps repeating the same mistakes".
        payload["reviewer_feedback"] = regen_feedback.strip()[:REVIEWER_FEEDBACK_CAP]
    user = json.dumps(payload)
    r = _openai({"model": OPENAI_MODEL,
                 "messages": [{"role": "system", "content": DRAFT_SYSTEM},
                             {"role": "user", "content": user}],
                 "response_format": {"type": "json_schema", "json_schema": {
                     "name": "setter_draft", "strict": True, "schema": DRAFT_SCHEMA}}}, key)
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
    html_body = demarkdown_links(html_body)
    html_body = enforce_signoff(html_body, sender_first)
    return {"subject": subject, "html": html_body, "feedback_note": feedback_note}


# Markdown link, tolerant of the shapes the drafter actually emits: the label
# may wrap lines, and the url may sit in the same parens as trailing text.
# The label and the "(url)" can be separated by whitespace or block markup -
# the drafter wraps long links onto their own line, sometimes with a <br> or
# a </div><div> between (seen live 2026-07-28).
_MD_LINK_RE = re.compile(
    r"\[([^\[\]]{1,200}?)\]\s*(?:<br\s*/?>|</div>\s*<div>|</p>\s*<p>|\s)*\(\s*(https?://[^\s()<>]+)\s*\)",
    re.S | re.I)
# Bare autolinks: <https://...> - a browser eats these as an unknown tag.
_MD_AUTOLINK_RE = re.compile(r"<(https?://[^\s<>\"]+)>")


def demarkdown_links(html: str) -> str:
    """Turn any markdown link the drafter emitted into a real anchor (owner
    report 2026-07-28: "[a bit about how we work](https://drive.google...)"
    reached the composer as literal text, with the raw URL on show, twice in
    the same email). DRAFT_SYSTEM forbids markdown and the model still does
    it - this is the deterministic guard that makes the rule true, the same
    way enforce_signoff does for the sign-off.

    Only ever converts a COMPLETE [label](http...) pair, so ordinary square
    brackets and ordinary parentheses are untouched. Never raises."""
    try:
        if not html or ("[" not in html and "<http" not in html):
            return html
        # Don't touch anything already inside an anchor's markup.
        def _anchor(m):
            label = re.sub(r"\s+", " ", m.group(1)).strip()
            url = m.group(2).rstrip(".,;:")
            if not label:
                label = url
            return f'<a href="{url}">{label}</a>'
        out = _MD_LINK_RE.sub(_anchor, html)
        out = _MD_AUTOLINK_RE.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', out)
        return out
    except Exception:  # noqa: BLE001 - a cosmetic guard must never fail a draft
        return html


# A closing word is not a name - never overwrite one of these with SenderFirst.
_CLOSING_WORDS = {"thanks", "thank you", "cheers", "best", "best regards", "regards",
                 "sincerely", "kind regards", "many thanks", "speak soon", "warmly",
                 "all the best", "talk soon", "yours"}
# The final block's visible text, when the draft ends in a sign-off line.
_SIGNOFF_TAIL_RE = re.compile(r"<div>([^<>]{1,40})</div>\s*$", re.I)
# What a personal-name sign-off looks like: one or two capitalised words.
_NAME_LIKE_RE = re.compile(r"^[A-Z][A-Za-z'’\-]{1,19}(?: [A-Z][A-Za-z'’\-]{1,19})?$")


def enforce_signoff(html: str, sender_first: str) -> str:
    """Deterministic guard on WHOSE name the draft signs off with (owner
    report 2026-07-28: roughly one draft in four signed "Bjorn" instead of
    "Bjion" - the drafting model normalising an unfamiliar first name -
    despite sender_first being set and an explicit owner rule forbidding it.
    _sender_first_for already made the value canonical; nothing enforced it
    on the way out).

    Rewrites the final block ONLY when every one of these holds, so it can
    never damage a draft that just doesn't end in a name:
      - sender_first is configured (empty -> DRAFT_SYSTEM's "no sign-off
        line at all" rule owns this case, leave the draft alone);
      - the html ends in a short plain-text <div> (no links, no markup);
      - that text looks like a personal name (one or two capitalised words)
        and is NOT a closing word like "Thanks" or "Best regards";
      - it does not already match sender_first.
    Anything else returns the html byte-identical. Never raises."""
    try:
        sender_first = str(sender_first or "").strip()
        if not sender_first or not html:
            return html
        m = _SIGNOFF_TAIL_RE.search(html)
        if not m:
            return html
        tail = m.group(1).strip()
        if not tail or tail.lower() in _CLOSING_WORDS or not _NAME_LIKE_RE.match(tail):
            return html
        if tail.lower() == sender_first.lower():
            return html
        return html[:m.start(1)] + sender_first + html[m.end(1):]
    except Exception:  # noqa: BLE001 - a sign-off guard must never sink a draft
        return html


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


_ASK_PHRASES = ("would you be free", "would it be worth", "are you free",
                "would you be open", "would you be available", "are you available",
                "do you have time")
_AVAIL_Q = "when would be a good time"
_DIV_BLOCK_RE = re.compile(r"<div\b[^>]*>.*?</div>", re.I | re.S)


def destack_call_ask(html: str) -> str:
    """Deterministic one-ask enforcement (owner rule 2026-08-17: "You're
    asking for a call twice, don't do that"; root-caused 2026-08-18). Despite
    DRAFT_SYSTEM's one-ask law, gpt-5-mini still occasionally emits BOTH a
    call-ask sentence AND the open "When would be a good time..." availability
    ask in one draft (~15% of fallback-path drafts). Prompt bans alone don't
    hold on a small model, so repair it in code: when both forms are present,
    drop whichever block is the weaker ask - keep the block that carries a
    concrete time or an anchor (a bookable ask), drop the other. Runs at the
    top of proofread_draft so every draft call site gets it, model or no
    model. Purely string-level, never a model call, never raises."""
    text = html or ""
    try:
        low_plain = _TAG_RE.sub(" ", text).lower()
        if _AVAIL_Q not in low_plain or not any(p in low_plain for p in _ASK_PHRASES):
            return text
        blocks = _DIV_BLOCK_RE.findall(text)
        avail_blocks = [b for b in blocks if _AVAIL_Q in _TAG_RE.sub(" ", b).lower()]
        ask_blocks = [b for b in blocks
                      if any(p in _TAG_RE.sub(" ", b).lower() for p in _ASK_PHRASES)
                      and b not in avail_blocks]
        if not avail_blocks or not ask_blocks:
            return text
        def _bookable(b: str) -> bool:
            return bool(re.search(r"\d{1,2}[:.]\d{2}\s*(?:AM|PM)", b, re.I)) or "<a " in b.lower()
        # Keep the bookable ask; drop the other form. When the call-ask block
        # has times or links it wins; otherwise the availability ask (which
        # carries the booking link) is the one real ask and the bare call-ask
        # sentence goes.
        drop = avail_blocks if any(_bookable(b) for b in ask_blocks) else ask_blocks
        for b in drop:
            text = text.replace(b + "<br>", "", 1) if (b + "<br>") in text else text.replace("<br>" + b, "", 1) if ("<br>" + b) in text else text.replace(b, "", 1)
        return text
    except Exception:  # noqa: BLE001 - a repair helper must never break drafting
        return html or ""


_TIMELESS_ASK_RE = re.compile(
    r"(?:would you be free|would it be worth|are you free)[^<]*?\bon\b\s*(<a\b[^>]*>.*?</a>)\s*\??",
    re.I | re.S)


def repair_timeless_ask(html: str) -> str:
    """Repairs the no-slots merge glitch where the drafter drops the booking
    anchor into the TIME slot of a call-ask sentence, e.g. 'Would you be free
    for a call on <a>grab a slot here</a>?' (judge finding 2026-08-18, seen
    twice). There is no time to recover, so rewrite the malformed ask into the
    clean fallback invitation, preserving the anchor. Only fires when a
    scheduling anchor sits immediately after 'on' with no time between."""
    try:
        return _TIMELESS_ASK_RE.sub(r"You're welcome to \1 whenever suits you.", html or "")
    except Exception:  # noqa: BLE001
        return html or ""


_AVAIL_FALLBACK_RE = re.compile(
    r"When would be a good time for us to talk\?\s*"
    r"(?:Here is\s*(?:<a\b([^>]*)>[^<]*</a>|my availability)\s*\.?)?"
    r"(?:\s*Feel free to suggest some times[^.<]*\.?)?",
    re.I)


def humanize_availability_fallback(html: str) -> str:
    """Rewrites the robotic no-slots fallback ask 'When would be a good time
    for us to talk? Here is my availability.' into a warm human form. This
    phrasing was the single most-flagged template tell across the Amplifyy
    human-ness eval (2026-08-18); replacing it lifts human-ness for every
    agent. When a booking anchor is present its href is kept but the anchor
    is RE-LABELLED ('grab a time that suits you here') so the sentence reads
    grammatically whatever the original label was; with no link it closes on
    the plain 'suggest some times' form."""
    def _sub(m):
        attrs = m.group(1)
        if attrs is not None:
            return f'You can <a{attrs}>grab a time that suits you here</a>.'
        return "Just let me know a couple of times that suit you and I'll set it up."
    try:
        return _AVAIL_FALLBACK_RE.sub(_sub, html or "")
    except Exception:  # noqa: BLE001
        return html or ""


def strip_deadend_ask(html: str) -> str:
    """Removes a call-ask block that carries NEITHER a concrete time NOR a
    scheduling anchor (judge finding 2026-08-18: 'Would you be free for a
    call, where I could share how I would implement our strategy for you?'
    with the slots stripped out). Such an ask is actionless - a dead end -
    so the block is dropped, leaving the resource line and sign-off. Only
    fires when the block has no digit-time and no anchor at all."""
    text = html or ""
    try:
        for b in _DIV_BLOCK_RE.findall(text):
            low = _TAG_RE.sub(" ", b).lower()
            if not any(p in low for p in _ASK_PHRASES):
                continue
            has_time = bool(re.search(r"\d{1,2}[:.]\d{2}\s*(?:am|pm)", low)) or \
                bool(re.search(r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b", low))
            has_anchor = "<a " in b.lower()
            if not has_time and not has_anchor:
                text = text.replace(b + "<br>", "", 1) if (b + "<br>") in text \
                    else text.replace("<br>" + b, "", 1) if ("<br>" + b) in text \
                    else text.replace(b, "", 1)
        return text
    except Exception:  # noqa: BLE001
        return html or ""


def destack_same_block(html: str) -> str:
    """Companion to destack_call_ask for the case where BOTH ask forms sit in
    the SAME div block (block-level dropping can't help there): removes the
    'When would be a good time...' sentence and a trailing availability
    sentence from a block that also carries a real ask phrase."""
    text = html or ""
    try:
        for b in _DIV_BLOCK_RE.findall(text):
            low = _TAG_RE.sub(" ", b).lower()
            if _AVAIL_Q in low and any(p in low for p in _ASK_PHRASES):
                nb = re.sub(r"[^.?!<>]*[Ww]hen would be a good time[^.?!]*[.?!]\s*", "", b)
                nb = re.sub(r"\s*[^.?!<>]*[Hh]ere is (?:<a[^>]*>)?my availability(?:</a>)?[^.?!]*[.?!]", "", nb)
                if _TAG_RE.sub(" ", nb).strip():
                    text = text.replace(b, nb, 1)
        return text
    except Exception:  # noqa: BLE001
        return html or ""


_GREET_RE = re.compile(
    r'^(\s*<div\b[^>]*>\s*)(Hi|Hey|Hello|Hola|Bonjour|Ciao|Ola|Hallo)([  ]+)([^,<]{2,60})(,?)', re.I)


_TITLE_TOKENS = {"dr", "mr", "mrs", "ms", "prof", "amb", "eng", "rev", "sir", "madam"}


def normalize_greeting(html: str, sender_first: str = "") -> str:
    """First-name-only greeting repair (judge findings 2026-08-18: 'Hi Janos
    Stegena' and 'Hi Dina "Desiree" Kotze,' read as mail-merge). Operates on
    the FIRST div only: strips quoted nicknames, then truncates a multi-word
    name to its first word - unless it is a team form ('... team'), a joint
    greeting (' and '), or the 'there' fallback. Deterministic, never raises."""
    text = html or ""
    try:
        m = _GREET_RE.match(text)
        if not m:
            return text
        name = re.sub(r'\s*["“][^"”]*["”]\s*', " ", m.group(4)).strip()
        low = name.lower()
        if low == "there" or low.endswith(" team") or " and " in low:
            return text if name == m.group(4).strip() else text[:m.start(4)] + name + text[m.end(4):]
        first = name.split()[0] if name.split() else name
        # Title globs from signature blocks ("Dr.Amb.Diplomat") and the
        # sender's own persona name are never the lead's name - fall back to
        # "there" (judge findings 2026-08-18).
        head = first.split(".")[0].lower().rstrip(".")
        if head in _TITLE_TOKENS or "." in first.rstrip(".") or (
                sender_first and first.lower() == sender_first.strip().lower()):
            first = "there"
        return text[:m.start(4)] + first + text[m.end(4):]
    except Exception:  # noqa: BLE001
        return html or ""


_RTF_ESC_RE = re.compile(r"\\?'([cdefCDEF][0-9a-fA-F])")


def repair_rtf_escapes(html: str) -> str:
    """Decodes RTF-style hex escapes leaked from a lead's reply encoding
    (judge finding 2026-08-18: drafts shipped "Hi D'e9bora" - 'e9 is an
    RTF-encoded e-acute the drafter copied verbatim; the leading backslash is
    stripped upstream, so match it optionally). Restricting the first hex
    nibble to c-f targets the Latin-1 accented range (0xC0-0xFF) and never
    touches decade forms like "the '90s" (0x90) or ordinary apostrophes.
    cp1252 covers the RTF default charset."""
    try:
        return _RTF_ESC_RE.sub(lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), html or "")
    except Exception:  # noqa: BLE001
        return html or ""


_HERE_IS_ANCHOR_RE = re.compile(r"\bHere is\s+(<a\b[^>]*>\s*grab a slot here\s*</a>)", re.I)


def repair_here_is_graft(html: str) -> str:
    """Fixes 'Here is <a>grab a slot here</a>' where the imperative anchor
    label got grafted after 'Here is', reading 'Here is grab a slot here'
    (judge finding 2026-08-18). Rewrites the stem to 'You can ...' so the
    anchor's own label reads naturally."""
    try:
        return _HERE_IS_ANCHOR_RE.sub(r"You can \1", html or "")
    except Exception:  # noqa: BLE001
        return html or ""


_MD_LINK_RE = re.compile(r"\[([^\]\n]{1,80})\]\((https?://[^)\s]+)\)")


def repair_markdown_links(html: str) -> str:
    """Converts leaked markdown-style links '[label](url)' into real anchors
    (judge finding 2026-08-18: a Spanish draft shipped the literal text
    '[un poco sobre como trabajamos]' - the drafter copied an instruction
    exemplar's markdown notation instead of writing HTML). Deterministic;
    the converted href still passes through lint_draft's URL allow-list."""
    try:
        return _MD_LINK_RE.sub(r'<a href="\2">\1</a>', html or "")
    except Exception:  # noqa: BLE001
        return html or ""


_ANCHOR_WITH_TEXT_RE = re.compile(r"([^<>]*?)(<a\b[^>]*>([^<]+)</a>)")


def dedupe_label_echo(html: str) -> str:
    """Drops a plain-text lead-in that echoes the anchor it introduces, e.g.
    'Here's a quick overview of how it works: <a>Here's a quick overview of
    how it works.</a>' -> '<a>Here's a quick overview of how it works.</a>'
    (judge finding 2026-08-18, three Verdant fails). Fires only when the
    text right before the anchor ends with the anchor's own label."""
    def _norm(s): return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    def _sub(m):
        lead, anchor, label = m.group(1), m.group(2), m.group(3)
        nlead, nlabel = _norm(lead), _norm(label)
        if nlabel and len(nlabel) >= 8 and nlead.endswith(nlabel):
            keep = lead[:len(lead) - len(lead.rstrip())] if False else ""
            # strip the echoed phrase + any trailing ": " / ", " separator
            cut = re.sub(re.escape(label.rstrip(". ")) + r"\s*[:,-]?\s*$", "", lead, flags=re.I)
            return cut + anchor
        return m.group(0)
    try:
        return _ANCHOR_WITH_TEXT_RE.sub(_sub, html or "")
    except Exception:  # noqa: BLE001
        return html or ""


def dedupe_adjacent_blocks(html: str) -> str:
    """Drops a div block whose visible text exactly repeats the previous
    block's (judge finding 2026-08-18: the same sentence pasted twice
    back-to-back, an assembly glitch no human sends). Exact-match only after
    whitespace/case normalisation - never touches near-duplicates."""
    text = html or ""
    try:
        blocks = _DIV_BLOCK_RE.findall(text)
        prev_norm = None
        for b in blocks:
            norm = re.sub(r"\s+", " ", _TAG_RE.sub(" ", b)).strip().lower()
            if norm and norm == prev_norm:
                text = text.replace("<br>" + b, "", 1) if ("<br>" + b) in text else text.replace(b, "", 1)
            else:
                prev_norm = norm
        return text
    except Exception:  # noqa: BLE001
        return html or ""


def _visible_digit_runs(html: str) -> set:
    """Digit runs found in the VISIBLE text only (tags/hrefs stripped first)
    - the same discipline lint_draft's own invented-number check uses, reused
    here so a proofread pass can never silently change a number, date, or
    time even though its wording changed."""
    plain = _TAG_RE.sub(" ", html or "")
    return set(re.findall(r"\d+", plain))


def proofread_draft(html: str, sender_first: str = ""):
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
    _repaired = strip_deadend_ask(destack_same_block(destack_call_ask(
        humanize_availability_fallback(repair_timeless_ask(repair_here_is_graft(
            dedupe_label_echo(repair_markdown_links(repair_rtf_escapes(html or "")))))))))
    original = dedupe_adjacent_blocks(normalize_greeting(_repaired, sender_first))
    if not original.strip():
        return original, False
    try:
        key = _KEYS.get("OPENAI_API_KEY")
        if not key:
            return original, False
        r = _openai({"model": PROOFREAD_MODEL,
                     "messages": [{"role": "system", "content": PROOFREAD_SYSTEM},
                                 {"role": "user", "content": json.dumps({"html": original})}],
                     "response_format": {"type": "json_schema", "json_schema": {
                         "name": "setter_proofread", "strict": True, "schema": PROOFREAD_SCHEMA}}}, key)
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
        # The proofreader is a second model, and it "corrects" an unfamiliar
        # first name exactly as the drafter does (owner report 2026-07-28:
        # "Bjion" came back as "Bjorn" AFTER draft_reply had already been
        # made canonical). Re-apply the guard here, so it is the LAST thing
        # that touches the html on every call site.
        result = demarkdown_links(result)
        result = enforce_signoff(result, sender_first)
        return result, result != original
    except Exception:  # noqa: BLE001 - a proofread outage must degrade to the original draft, never crash
        return original, False


# ── Smartlead helpers ────────────────────────────────────────────────────────

def _sl_key():
    return _KEYS.get("SMARTLEAD_API_KEY")


# Injected by server.py after configure() (client-workspaces-hub): maps a
# Smartlead campaign id to its OWNING workspace's API key, so setter calls
# against a done-with-you client's campaign use the client's key. None → every
# call uses the navreo env key (exactly the pre-federation behaviour).
_WS_KEY_FOR_CAMPAIGN = None


def _sl_key_for(path: str, campaign_id=None):
    cid = campaign_id
    if cid is None:
        m = re.match(r"/campaigns/(\d+)", path)
        cid = m.group(1) if m else None
    if cid is not None and _WS_KEY_FOR_CAMPAIGN:
        try:
            k = _WS_KEY_FOR_CAMPAIGN(cid)
            if k:
                return k
        except Exception:  # noqa: BLE001 - key resolution must never break a fetch
            pass
    return _sl_key()


def _sl_get(path: str, params: dict = None, campaign_id=None):
    # campaign_id lets a workspace-scoped call (e.g. /leads/?email=) resolve the
    # OWNING client's key even though the path carries no /campaigns/{id} for the
    # regex to find — without it, such calls silently fall back to the navreo key
    # and a client-workspace lead (Grout, etc.) is "not found". (Bjion 2026-07-29)
    key = _sl_key_for(path, campaign_id)
    if not key:
        return None
    qs = dict(params or {})
    qs["api_key"] = key
    # 15s, not http_json's 60s default (502 fix 2026-07-30): Smartlead READS
    # on the send/hydrate path used to inherit 60s each - a send needing
    # rehydration could pin a worker thread (and its parsed thread corpus)
    # for up to 4 minutes on the 512MB box. Reads that slow are already
    # failures; fail fast and let the row land in needs_review with a real
    # error. Mirrors _SB_TIMEOUT_S for Supabase. _sl_post (the actual reply
    # send) deliberately keeps 60s - timing out a send that might have gone
    # out risks a double-send on retry.
    return _HTTP("GET", f"{SMARTLEAD_BASE}{path}?{urlencode(qs)}", {}, timeout=15)


def _sl_post(path: str, body: dict, params: dict = None, campaign_id=None, api_key=None):
    # campaign_id mirrors _sl_get's kwarg: account-scoped POSTs (e.g.
    # /master-inbox/push-to-subsequence) carry no /campaigns/{id} in the
    # path, so without it they silently use the navreo key. api_key is an
    # explicit override for workspace-scoped calls where no campaign id
    # exists to resolve from (the client reply-sync's master-inbox pull).
    key = api_key or _sl_key_for(path, campaign_id)
    if not key:
        return None
    qs = dict(params or {})
    qs["api_key"] = key
    url = f"{SMARTLEAD_BASE}{path}?{urlencode(qs)}"
    # Retry-on-429 (owner report 2026-08-10: "Couldn't send the reply: HTTP
    # Error 429: Too Many Requests" on Approve, then it works on a manual retry
    # 15s later). A 429 is Smartlead RATE-LIMITING — it REJECTED the request, so
    # nothing was sent and a retry is double-send-SAFE (unlike a timeout, which
    # might have gone out — those still raise, unchanged). Without this a single
    # transient 429 landed the reply in needs_review with the raw error and made
    # the reviewer re-click by hand. Retry inline with backoff so the click just
    # succeeds; honour a Retry-After header when Smartlead sends one (capped so a
    # worker never pins the 512MB box). ~21s total worst case across 3 retries.
    _SL_429_BACKOFFS = (3.0, 6.0, 12.0)
    for _attempt in range(len(_SL_429_BACKOFFS) + 1):
        try:
            return _HTTP("POST", url, {}, body)
        except ValueError:
            # Smartlead sometimes answers a successful POST (e.g. reply-email-thread)
            # with a non-JSON 2xx body such as a bare "OK". http_json's json.loads then
            # raises JSONDecodeError (a ValueError) even though the HTTP call SUCCEEDED,
            # which used to land the reply as needs_review + "Expecting value: line 1
            # column 1 (char 0)" while the email had actually gone out - risking a
            # double-send on the next click. A 2xx IS success, so treat it as an
            # accepted, empty-JSON response. (4xx/5xx still raise HTTPError, unchanged.)
            return {}
        except Exception as e:  # noqa: BLE001
            # Only a 429 is retryable here; every other status/error propagates
            # to the caller exactly as before. Give up (re-raise) once retries
            # are exhausted so _send_reply lands it as needs_review as usual.
            if getattr(e, "code", None) != 429 or _attempt >= len(_SL_429_BACKOFFS):
                raise
            wait = _SL_429_BACKOFFS[_attempt]
            try:
                ra = e.headers.get("Retry-After") if getattr(e, "headers", None) else None
                if ra is not None:
                    wait = min(max(float(ra), 1.0), 15.0)  # honour Smartlead, cap 15s
            except Exception:  # noqa: BLE001 - a garbled header just uses our backoff
                pass
            _time.sleep(wait)


# from-email -> from_name for a campaign's sending accounts, cached. The
# Smartlead message history stopped carrying from_name (observed 2026-07-28:
# SENT items only have the raw `from` address), so the sending identity must
# be resolved through the campaign's email-accounts list. One fetch per
# campaign per 6h. A campaign can MIX senders (3642625 sends as both Jane
# Smithson and Kevin Dormer), so the map is per-ADDRESS, never per-campaign.
_CAMPAIGN_SENDER_CACHE = {}
_CAMPAIGN_SENDER_TTL = 6 * 3600.0


def _campaign_sender_map(campaign_id) -> dict:
    if not campaign_id:
        return {}
    key = str(campaign_id)
    hit = _CAMPAIGN_SENDER_CACHE.get(key)
    if hit and hit[0] > _time.time():
        return hit[1]
    mp = {}
    try:
        accs = _sl_get(f"/campaigns/{campaign_id}/email-accounts")
        for a in (accs if isinstance(accs, list) else []):
            em = str(a.get("from_email") or "").strip().lower()
            nm = str(a.get("from_name") or "").strip()
            if em and nm:
                mp[em] = nm
    except Exception:  # noqa: BLE001 - an unavailable list just means no name; never cache the failure
        return mp
    _CAMPAIGN_SENDER_CACHE[key] = (_time.time() + _CAMPAIGN_SENDER_TTL, mp)
    return mp


def _thread_sender_first(campaign_id, thread) -> str:
    """First name of whoever ACTUALLY sent the outbound in this thread -
    per-lead ground truth (owner report 2026-07-28: sent from Jane, the draft
    signed Kevin because the agent doc's stamped name was the only source).
    Uses the stored thread's from_name when present, else resolves the SENT
    from-address through the campaign's email-accounts. '' when unknowable -
    callers fall back to the agent's configured name via _sender_first_for."""
    last_email = ""
    for m in reversed(thread or []):
        if not isinstance(m, dict) or str(m.get("type") or "").upper() != "SENT":
            continue
        nm = str(m.get("from_name") or "").strip()
        if nm:
            return nm.split()[0]
        if not last_email:
            last_email = str(m.get("from_email") or "").strip().lower()
    if last_email:
        mp = _campaign_sender_map(campaign_id)
        nm = mp.get(last_email, "")
        if nm:
            return nm.split()[0]
        # The exact mailbox often ROTATES OUT of the campaign (spam-pulled
        # boxes get removed, verified live 2026-07-28: 7 of 10 queue rows'
        # senders were no longer in their campaign's account list), but the
        # local part still names the persona: kevindormer_k@... is Kevin
        # Dormer. Match it against the campaign's known sender personas -
        # longest compact name first so a short name can't shadow a longer
        # one. Only ever resolves to a name the campaign actually sends as.
        local = re.sub(r"[^a-z]", "", last_email.split("@", 1)[0].lower())
        if local:
            for full in sorted({v for v in mp.values() if v}, key=len, reverse=True):
                parts = full.split()
                compact = re.sub(r"[^a-z]", "", full.lower())
                first = re.sub(r"[^a-z]", "", parts[0].lower()) if parts else ""
                if compact and (local.startswith(compact) or compact in local):
                    return parts[0]
                if first and len(first) >= 4 and local.startswith(first):
                    return parts[0]
    return ""


def _sl_lead_map_id_by_email(campaign_id, lead_email: str):
    """One-call map-id resolution: GET /leads/?email=<email> returns the
    lead with `lead_campaign_data` - a list where each entry carries the
    `campaign_id` AND the `campaign_lead_map_id` for that membership (proven
    live 2026-07-17 on campaign 3506959: the paging path capped out at 2,000
    of 7,566 leads and reported the lead unfindable; this returned the map id
    3259560174 in one call and the push succeeded). Returns the id or None
    (missing email, endpoint error, no entry for this campaign) - the caller
    falls back to paging. Never raises."""
    email = (lead_email or "").strip()
    if not campaign_id or not email:
        return None
    try:
        resp = _sl_get("/leads/", {"email": email}, campaign_id=campaign_id)
        if not isinstance(resp, dict):
            return None
        memberships = resp.get("lead_campaign_data")
        if not isinstance(memberships, list):
            return None
        for m in memberships:
            if isinstance(m, dict) and str(m.get("campaign_id")) == str(campaign_id):
                return m.get("campaign_lead_map_id")
        return None
    except Exception:  # noqa: BLE001
        return None


def _sl_campaign_lead_map_id(campaign_id, lead_email: str, smartlead_lead_id=None, max_pages: int = 20):
    """Resolves the Smartlead `campaign_lead_map_id` for a lead inside a
    specific campaign - this is the id the push-to-subsequence endpoint calls
    `email_lead_map_id`.

    FIRST tries the one-call by-email lookup (_sl_lead_map_id_by_email) -
    the paging path below caps at max_pages*100 = 2,000 leads, which made
    every lead past position 2,000 of a big campaign unfindable (live bug
    2026-07-17, campaign 3506959 with 7,566 leads). Only when that yields
    nothing (no email on the row, endpoint error, no matching campaign
    entry) does it fall back to the original paging loop, unchanged:
    GET /campaigns/{campaign_id}/leads, docs at
    https://api.smartlead.ai/api-reference/leads/get-by-campaign - each row of
    the paginated `data` list carries a top-level `campaign_lead_map_id` plus
    a nested `lead` object ({id, email, ...}), matched by Smartlead lead id
    first, email second. Returns the id, or None if not found / on any
    failure. Never raises."""
    if not campaign_id:
        return None
    map_id = _sl_lead_map_id_by_email(campaign_id, lead_email)
    if map_id is not None:
        return map_id
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
        # campaign_id routes the POST to the owning workspace's key — the
        # path carries no /campaigns/{id}, so without it the map_id would be
        # resolved with the client's key and the push posted with navreo's.
        resp = _sl_post("/master-inbox/push-to-subsequence", {
            "email_lead_map_id": map_id,
            "sub_sequence_id": sub_sequence_id,
            "sub_sequence_delay_time": 0,
            "stop_lead_on_parent_campaign_reply": True,
        }, campaign_id=campaign_id)
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
        # campaign_id kwarg is load-bearing: /leads/ carries no campaign in its
        # path, so without it the key resolver falls back to the navreo key and
        # every client-workspace lead reads as "not found" (federation fix).
        lead_resp = _sl_get("/leads/", {"email": email}, campaign_id=campaign_id)
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
                # The raw sending address - since 2026-07-28 the only sender
                # identity the history carries (from_name vanished from the
                # API); _thread_sender_first resolves it to a person.
                "from_email": (m.get("from") if isinstance(m.get("from"), str) else None) or frm.get("email"),
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
        # Who actually sent: from_name when the API still carries it, else the
        # SENT from-address resolved through the campaign's email-accounts
        # (from_name vanished from the message-history API, observed
        # 2026-07-28 - without this every draft fell back to the agent's ONE
        # stamped name even on campaigns sent by someone else).
        sender_first = _thread_sender_first(campaign_id, sent)

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

# One availability lookup costs 4+ serial Calendly round trips (users/me,
# event_types, chunked available_times) before the draft model even runs -
# roughly a second of every regenerate. The slots are already minutes stale by
# the time a reviewer reads the draft, so a 60s in-process cache changes
# nothing observable; it only stops paying the same round trips again on a
# regenerate-after-regenerate. Keyed per token+event so agents never mix.
_CAL_AVAIL_CACHE = {}
_CAL_AVAIL_TTL = 60.0


def get_calendly_availability(agent: dict, settings: dict, now_utc):
    """Returns (slot_status, avail_iso_list, error). slot_status in
    {ok, not_configured, none_available, error}. Caches the resolved Calendly
    user uri onto settings['_calendly_user_uri'] for the caller to persist."""
    agent = agent or {}
    settings = settings or {}
    token = settings.get("calendly_token")
    if not token:
        return "not_configured", [], ""
    # Booking link must actually BE a Calendly link (owner report 2026-08-05:
    # every Amplifyy draft carried "Couldn't find this agent's Calendly event
    # type", and Arnic — no link — the same). The Calendly event-type lookup
    # can only resolve calendly.com slugs against THIS token's account; an
    # empty link (slug "") or a different provider (a client's SavvyCal) can
    # never match, so the lookup below returned that error and it got stamped
    # onto the row (see the `serr -> row["error"]` sites). That's not an error
    # state — it's just no Calendly availability to inline. Return
    # not_configured so the draft falls through its no-live-slots ladder and
    # still carries the raw booking link, with nothing scary on the row.
    event_url = (agent.get("calendly_event_url") or "").strip().lower()
    if not event_url or "calendly.com" not in event_url:
        return "not_configured", [], ""
    cache_key = (token[-16:], agent.get("calendly_event_url") or "")
    hit = _CAL_AVAIL_CACHE.get(cache_key)
    if hit and hit[0] > _time.time():
        if hit[2] and not settings.get("_calendly_user_uri"):
            settings["_calendly_user_uri"] = hit[2]
        status, avail, err = hit[1]
        return status, list(avail), err
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
        # Only real answers are cached - errors keep retrying at full price.
        result = ("none_available", [], "") if not avail else ("ok", avail, "")
        _CAL_AVAIL_CACHE[cache_key] = (_time.time() + _CAL_AVAIL_TTL, result,
                                       settings.get("_calendly_user_uri"))
        return result[0], list(result[1]), result[2]
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
    _bust_agents_cache()   # settings ride along in route_agents_get's payload


def _load_agents() -> list:
    if not _SB:
        return []
    try:
        # Reserved doc rows (double-underscore ids like __settings__, plus
        # training-<agent_id>) live in the same table but are never real
        # agents - filtered out client-side so they can never leak into the
        # agents list or campaign assignment lookups.
        rows = _SB("GET", f"{AGENTS_TABLE}?select=id,doc")
        if isinstance(rows, list):
            return [r.get("doc") or {} for r in rows
                   if isinstance(r, dict) and not str(r.get("id") or "").startswith("__")
                   and not str(r.get("id") or "").startswith(TRAINING_ID_PREFIX)]
    except Exception:  # noqa: BLE001
        pass
    return []


def _load_agent(agent_id):
    if not agent_id:
        return None
    # Targeted read. This used to call _load_agents(), which pulls EVERY agent
    # doc - multi-KB instruction blobs, one of them 15KB - and then picked one
    # out client-side. On the regenerate path that was 2.6s median (5.5s
    # worst) spent before a model call even started, measured live 2026-07-28.
    # Falls back to the full scan if the row id and the doc id ever disagree,
    # so an agent can't go missing on a schema quirk.
    if _SB:
        try:
            rows = _SB("GET", f"{AGENTS_TABLE}?id=eq.{quote(str(agent_id))}&select=id,doc")
            if isinstance(rows, list) and rows:
                doc = rows[0].get("doc") or {}
                if doc.get("id") == agent_id:
                    return doc
        except Exception:  # noqa: BLE001
            pass
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
        names = {}
        for r in resp:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            if r.get("parent_campaign_id"):
                out[str(r["id"])] = str(r["parent_campaign_id"])
            # id->name for the same listing, kept alongside: the campaigns
            # mirror can lag a brand-new campaign, and the picker's
            # "Campaign <id>" placeholder is what buckets its replies into
            # the client filter's "Other" (owner report 2026-08-09).
            if r.get("name"):
                names[str(r["id"])] = str(r["name"])
        _PARENT_CACHE.update({"at": _time.time(), "map": out, "names": names})
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
        claimers = [a for a in agents
                    if (not require_enabled or a.get("enabled", True))
                    and want in [str(c) for c in (a.get("campaign_ids") or [])]]
        if not claimers:
            return None
        if len(claimers) > 1:
            # Should be impossible (route_agents_save strips doubles), but if
            # bad data sneaks in, the EARLIEST claim keeps the campaign - an
            # accidental later attach must not steal a client's threads (owner
            # bug 2026-07-28: 3642625 sat in both the Amplifyy and Navreo
            # agents' lists and list order decided who drafted - a Navreo
            # demo pitch went out on an Amplifyy thread). Shouted to the log,
            # never silently roulette'd.
            def _claim_at(a):
                return str(((a.get("campaign_assigned_at") or {}).get(want)) or "9999")
            claimers.sort(key=lambda a: (_claim_at(a), str(a.get("id"))))
            print(f"[setter] WARNING campaign {want} claimed by "
                  f"{[a.get('id') for a in claimers]} - using {claimers[0].get('id')}",
                  file=sys.stderr)
        return claimers[0]

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
    # One id shape everywhere: strings, de-duplicated, order kept. The
    # int/str mix is exactly how the same campaign hid in two agents' lists
    # at once (owner bug 2026-07-28: '3642625' in one doc, 3642625 in
    # another - set intersection saw nothing).
    _seen_cids = set()
    doc["campaign_ids"] = [s for s in (str(c) for c in (doc.get("campaign_ids") or []))
                           if not (s in _seen_cids or _seen_cids.add(s))]
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
        _bust_agents_cache()   # the agents list just changed - next GET reads fresh
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
                # Adoption changed queue rows through a RAW _SB call, which -
                # unlike _apply_patch - leaves the short-TTL read caches holding
                # the pre-assign rows (agent_id null, old decision_reason). The
                # page then kept repainting the stale row after a Regenerate, so
                # the first attempt looked like it did nothing and the second,
                # once the TTL had expired, "worked" (owner report 2026-07-25).
                _bust_read_caches()
            except Exception:  # noqa: BLE001 - adoption is follow-through, not the save itself
                pass
    return doc


def _sender_first_for(agent: dict, thread_name: str = "") -> str:
    """Single canonical resolver for whose first name a draft signs off with -
    every draft_reply call site (live pipeline, queue redraft, training real-
    case building, synthetic training, retrain, recheck)
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
    roughly limit_chars). Fed into
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

MERGE_CONFLICTS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"conflicts": {"type": "array", "items": {"type": "string"}}},
    "required": ["conflicts"],
}

MERGE_CONFLICTS_SYSTEM = """You audit an AI appointment setter's instruction manual right after the owner's newest correction was added to it. Your only job is to list every passage of the manual that CONTRADICTS or undermines that correction, so those passages can be removed. A passage conflicts when following it would produce behaviour the correction forbids, or when it states an OLDER version of the same rule in different words for the same situation. Quote each conflicting passage verbatim, trimmed to the smallest span that shows the conflict, under 200 characters each. The correction itself, and passages that agree with it, are NOT conflicts. Rules about unrelated situations are NOT conflicts. When the manual is clean, return an empty list.

Output STRICT JSON: {"conflicts": ["..."]}"""

CLEANUP_INSTRUCTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"instructions": {"type": "string"}},
    "required": ["instructions"],
}

CLEANUP_INSTRUCTIONS_SYSTEM = """You maintain an AI appointment setter's instruction manual. The owner's newest correction is already in the manual, but the listed older passages contradict it. Rewrite the manual so the correction is the single truth: delete or rewrite ONLY the conflicting passages so they agree with the correction, and change nothing else. Keep every existing link, price, and unrelated rule exactly as it is. Never invent a new link, price, or rule. Plain text, short paragraphs, no em dashes anywhere, use a comma or period instead. Return the FULL updated manual, not a summary.

Output STRICT JSON: {"instructions": "..."}"""


def _find_instruction_conflicts(instructions: str, correction: str):
    """Lists manual passages that contradict the correction (verbatim quotes).
    Returns a list (possibly empty = clean) or None when the check could not
    run (no key, call failed) - callers must treat None as "unknown", never
    as "clean"."""
    try:
        key = _KEYS.get("OPENAI_API_KEY")
        if not key:
            return None
        r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                 {"Authorization": f"Bearer {key}"},
                 {"model": OPENAI_MODEL,
                  "messages": [{"role": "system", "content": MERGE_CONFLICTS_SYSTEM},
                              {"role": "user", "content": json.dumps(
                                  {"manual": instructions, "correction": correction})}],
                  "response_format": {"type": "json_schema", "json_schema": {
                      "name": "setter_merge_conflicts", "strict": True,
                      "schema": MERGE_CONFLICTS_SCHEMA}}})
        if isinstance(r, dict) and not r.get("error"):
            data = json.loads(r["choices"][0]["message"]["content"])
            out = data.get("conflicts")
            if isinstance(out, list):
                return [str(x).strip() for x in out if str(x).strip()][:8]
    except Exception:  # noqa: BLE001 - an unavailable check is "unknown", not "clean"
        pass
    return None


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

    # Verify-before-done (owner brief 2026-08-04): saving text is not the same
    # as the lesson landing. Older passages that contradict a new correction
    # make the drafter pick sides at random (16 CTA phrasings were live in the
    # queue that morning), and the append fallback is the worst offender, it
    # never removes anything. So after every merge OR append: sweep the result
    # for passages that fight the correction, rewrite exactly those away in a
    # second targeted pass (same never-drop-a-link / no-runaway-growth checks
    # as the merge itself), then record honestly what is left. A correction
    # whose conflicts_remaining is non-empty was NOT fully applied and every
    # caller can now say so instead of reporting it complete.
    conflicts = _find_instruction_conflicts(new_text, note)
    remaining = list(conflicts or [])
    if remaining:
        cleaned = None
        try:
            key = _KEYS.get("OPENAI_API_KEY")
            if key:
                payload = {"current_instructions": new_text, "correction": note,
                           "conflicting_passages": remaining}
                r = _HTTP("POST", "https://api.openai.com/v1/chat/completions",
                         {"Authorization": f"Bearer {key}"},
                         {"model": OPENAI_MODEL,
                          "messages": [{"role": "system", "content": CLEANUP_INSTRUCTIONS_SYSTEM},
                                      {"role": "user", "content": json.dumps(payload)}],
                          "response_format": {"type": "json_schema", "json_schema": {
                              "name": "setter_instructions_cleanup", "strict": True,
                              "schema": CLEANUP_INSTRUCTIONS_SCHEMA}}})
                if isinstance(r, dict) and not r.get("error"):
                    data = json.loads(r["choices"][0]["message"]["content"])
                    candidate = str(data.get("instructions") or "").strip()
                    old_urls = set(_extract_urls(new_text))
                    max_len = max(20000, int(len(new_text) * 1.5))
                    if candidate and old_urls.issubset(set(_extract_urls(candidate))) and len(candidate) <= max_len:
                        cleaned = candidate
        except Exception:  # noqa: BLE001 - a failed cleanup keeps the pre-cleanup text and reports the conflicts
            cleaned = None
        if cleaned is not None:
            new_text = cleaned
            how += "+cleaned"
            recheck = _find_instruction_conflicts(new_text, note)
            if recheck is not None:
                remaining = list(recheck)

    edits = list(agent.get("instruction_edits") or [])
    edit_entry = {"note": note, "rule": rule, "at": at, "source": source or "manual", "how": how}
    if conflicts is not None:
        edit_entry["conflicts_found"] = len(conflicts)
        edit_entry["conflicts_remaining"] = [c[:200] for c in remaining[:5]]
    edits.append(edit_entry)
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


def _preserve_followup_entries(old_thread, new_thread):
    """Follow-up markers must survive every thread overwrite (panel critical
    2026-08-01): the hydrator rebuilds `thread` from Smartlead, which knows
    the follow-up email as a plain SENT entry with no `followup` flag — so a
    wholesale overwrite erased the recency gate's only durable record within
    one conversation open. Where the new thread carries a SENT entry with the
    same body, the flag is grafted onto it; otherwise the marker is appended.
    Applied centrally in _apply_patch so every writer — hydrate, intake,
    reply-sync, future ones — preserves the record."""
    olds = [m for m in (old_thread or [])
            if isinstance(m, dict) and m.get("followup")
            and str(m.get("type") or "").upper() == "SENT"]
    if not olds:
        return new_thread
    out = list(new_thread or [])

    def _norm(b):
        return re.sub(r"\s+", " ", _TAG_RE.sub(" ", str(b or ""))).strip()[:200]

    for marker in olds:
        mb = _norm(marker.get("body"))
        grafted = False
        for m in out:
            if (isinstance(m, dict) and str(m.get("type") or "").upper() == "SENT"
                    and not m.get("followup") and _norm(m.get("body")) == mb):
                m["followup"] = True
                grafted = True
                break
        if not grafted and not any(isinstance(m, dict) and m.get("followup")
                                   and _norm(m.get("body")) == mb for m in out):
            out.append(marker)
    out.sort(key=lambda m: str((m or {}).get("time") or ""))
    return out[-50:]


def _apply_patch(row: dict, patch: dict) -> bool:
    # No-op patches skip the write AND the bust: route_thread_get re-persists
    # the thread on EVERY conversation open, and an unchanged thread must not
    # thrash caches (or pay a Supabase round trip at all).
    # Returns False only when a REAL change failed to persist — callers that
    # already wrote external systems (Smartlead, replies) surface that
    # instead of reporting a success the queue row doesn't reflect.
    if "thread" in patch:
        patch = {**patch, "thread": _preserve_followup_entries(row.get("thread"), patch["thread"])}
    changed = any(row.get(k) != v for k, v in patch.items())
    wrote = True
    if changed and _SB and row.get("id") is not None:
        try:
            # updated_at is stamped on every real change (panel fix 2026-08-01):
            # the column has only an INSERT default and no update trigger, so it
            # froze at intake time — which made every age-off-updated_at reader
            # (the sending-claim reaper, the recency gate's in-flight arm)
            # misread claim age as intake age. return=representation makes an
            # id that matched nothing (re-intake swap, deleted row) read as a
            # failed write instead of a silent success.
            got = _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{row['id']}",
                      {**patch, "updated_at": _dt.datetime.now(_dt.timezone.utc)
                       .isoformat(timespec="seconds")}, "return=representation")
            if isinstance(got, list) and not got:
                wrote = False
        except Exception:  # noqa: BLE001
            wrote = False
    if changed and wrote:
        # Keep the in-memory row in lockstep with what was persisted — a
        # caller comparing row state after a patch (e.g. the follow-up
        # restore) must see what the DB sees (panel fix 2026-08-01).
        row.update(patch)
    # A row changed under the read caches (status moves it between pills;
    # thread/draft edits change its content) - stale-mark them all and start a
    # rewarm so the reload the UI fires right after an action reads fresh
    # (perf pass 2026-07-16: queue GETs are served from short-TTL caches now).
    if changed:
        _bust_read_caches()
    return wrote


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
    if not ok and re.search(r"timeout|timed out|urlerror|connection", str(herr), re.I):
        # Transient network blip - retry once before deciding anything (panel
        # fix, F6: the 15s _sl_get timeout made one-off read blips far more
        # common, and treating them as terminal told the owner to "reply in
        # Smartlead directly" over a row that would send fine seconds later).
        ok, hyd, herr = hydrate_lead(row.get("smartlead_campaign_id"), row.get("lead_email"),
                                     row.get("message_id"))
        if not ok:
            return "", ("Smartlead was slow to answer just now, so this reply "
                        "couldn't be matched to its thread. This is usually "
                        "temporary - try Approve again in a moment."
                        + (f" ({herr})" if herr else ""))
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


# ── double-send protection (owner ruling 2026-08-01: "two emails sent in a
# space of 10 minutes shouldn't actually be allowed") ────────────────────────
# Three layers, because each one covers a hole the others can't:
#   1. _SEND_INFLIGHT — a second async send START for the same row id joins
#      the FIRST job instead of minting a new one (double-click, two tabs on
#      one row). Process-local, so…
#   2. the conditional claim in _send_reply — a one-round-trip PATCH
#      `id=eq.X&status=eq.<current>` → status 'sending'. Whoever loses the
#      race gets an empty representation back and aborts WITHOUT posting to
#      Smartlead. Durable: survives multi-tab, restarts, and the sync path.
#   3. _recent_send_block — a lead-level recency gate: any OTHER row for the
#      same lead email sent (or in flight) inside the window rejects the send
#      outright. Catches re-intake duplicates the row-level guards can't see.
_SEND_INFLIGHT_LOCK = threading.Lock()
_SEND_INFLIGHT: dict = {}    # str(queue row id) -> job_id of the running send
DOUBLE_SEND_WINDOW_MIN = float(os.environ.get("SETTER_DOUBLE_SEND_WINDOW_MIN", "10"))
# A 'sending' claim whose worker died with the process must not strand the row
# invisible forever — after this many minutes the poll reaper returns it to
# needs_review with an honest error.
SENDING_STALE_MIN = 15.0


def _recent_send_block(row: dict, followup: bool = False):
    """Human-readable reason when another outbound email went to this lead
    within DOUBLE_SEND_WINDOW_MIN, else None. Recency is computed in Python
    (not a gte. filter) so clock-skewed rows and the test fake behave the
    same as PostgREST. Never raises — a lookup failure never blocks a send.
    followup=True ALSO counts this row's OWN send evidence (sent_at + any
    follow-up entries in its thread): the old self-skip let a second
    follow-up through every layer (panel critical, 2026-08-01)."""
    email = str(row.get("lead_email") or "").strip().lower()
    if not email:
        return None
    now = _dt.datetime.now(_dt.timezone.utc)

    def _age_min(stamp):
        try:
            return (now - _parse_iso(stamp)).total_seconds() / 60.0
        except (ValueError, TypeError, AttributeError):
            return None

    def _msg(verb, age):
        return (f"Blocked: an email {verb} to {email} "
                f"{int(age)} min ago — two emails to the same person inside "
                f"{int(DOUBLE_SEND_WINDOW_MIN)} minutes aren't allowed. Nothing was sent.")

    if followup:
        own = _age_min(_own_row_last_send(row))
        if own is not None and 0 <= own < DOUBLE_SEND_WINDOW_MIN:
            return _msg("was sent", own)
    if not _SB:
        return None
    try:
        # is_test rows are excluded — a dry test send stamps sent_at without
        # any real email, and its phantom recency blocked genuine sends.
        # Ordered by updated_at (honest since 2026-08-01: bumped on claim AND
        # on send) so both a fresh send and a live claim surface first.
        got = _SB("GET", f"{QUEUE_TABLE}?lead_email=eq.{quote(email, safe='')}"
                         f"&workspace=eq.{quote(str(row.get('workspace') or WORKSPACE), safe='')}"
                         f"&status=in.(sent,auto_sent,sending)&is_test=not.is.true"
                         f"&select=id,status,sent_at,updated_at,workspace"
                         f"&order=updated_at.desc&limit=25")
        if not isinstance(got, list):
            return None
        for r in got:
            if not isinstance(r, dict) or str(r.get("id")) == str(row.get("id")):
                continue
            if (r.get("workspace") or WORKSPACE) != (row.get("workspace") or WORKSPACE):
                continue
            stamp = r.get("sent_at") if r.get("status") in ("sent", "auto_sent") else r.get("updated_at")
            age_min = _age_min(stamp)
            if age_min is None:
                continue
            if r.get("status") == "sending" and age_min > SENDING_STALE_MIN:
                continue   # a stranded claim is not a real in-flight send
            if 0 <= age_min < DOUBLE_SEND_WINDOW_MIN:
                verb = "is being sent" if r.get("status") == "sending" else "was sent"
                return _msg(verb, age_min)
    except Exception:  # noqa: BLE001 - the gate must never break a legitimate send
        return None
    return None


def _followup_thread_entry(html_body: str, now: str) -> dict:
    """The durable record of a follow-up send: appended to the row's thread
    (the ONLY schema-frozen column that can carry it without clobbering the
    first reply's sent_at/sent_body). Doubles as the follow-up recency source
    and shows the follow-up in the rendered conversation."""
    return {"type": "SENT", "time": now, "body": html_body, "followup": True}


def _own_row_last_send(row: dict):
    """Newest send evidence on THIS row: sent_at, or a later follow-up entry
    in the thread. PARSED comparison, not a string max (panel fix
    2026-08-01: mixed UTC offsets invert lexicographic order). Returns an
    ISO string or None."""
    best = best_dt = None
    for s in ([str(row.get("sent_at") or "")]
              + [str(m.get("time") or "") for m in (row.get("thread") or [])
                 if isinstance(m, dict) and str(m.get("type") or "").upper() == "SENT"
                 and m.get("followup")]):
        if not s:
            continue
        try:
            d = _parse_iso(s)
        except (ValueError, TypeError, AttributeError):
            continue
        if best_dt is None or d > best_dt:
            best, best_dt = s, d
    return best


def _send_reply(row: dict, agent: dict, subject: str, html_body: str, is_test: bool = False,
                success_status: str = "sent", is_followup: bool = False) -> dict:
    """Sends (or stub-sends) one reply. Returns {"ok": bool, "row": <patch dict>},
    plus "blocked": <reason> when the recency gate refused (route maps to 429).
    is_test rows NEVER hit Smartlead regardless of SETTER_DRY_RUN.
    is_followup is DECLARED by the caller (panel fix 2026-08-01) — inferring
    it from sent_at turned odd-state first sends into record-freezing no-ops."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    if row.get("error"):
        # Clear a PRIOR attempt's error the moment a new send starts (panel
        # fix, F5): the client's row-truth fallback reads this column while
        # the job is in flight, and a stale error made it report hard failure
        # over a send that was still going out - the false message that tempts
        # a double-send.
        _apply_patch(row, {"error": None})
    followup = bool(is_followup)

    def _success_patch():
        # A follow-up must never overwrite the FIRST reply's record — it is
        # appended to the thread instead (its own durable record + the
        # follow-up recency source). First sends stamp the full record.
        if followup:
            thread = list(row.get("thread") or [])[-49:] + [_followup_thread_entry(html_body, now)]
            return {"status": success_status, "error": None, "thread": thread}
        return {"status": success_status, "sent_at": now, "sent_body": html_body,
                "error": None, "draft_subject": subject, "draft_body": html_body}

    # Monitor-only backstop: a non-navreo (federation-monitor) row can NEVER
    # hit Smartlead, by any caller (manual, auto, async). The send-action
    # handler already refuses these up front; this is defence-in-depth so no
    # code path can ever slip a monitor-workspace send out.
    dry = bool(is_test) or _dry_run() or _is_monitor_ws(row.get("workspace"))
    if dry:
        patch = _success_patch()
        _apply_patch(row, patch)
        if _LOG:
            try:
                _LOG("/api/setter/queue/action", {"id": row.get("id"), "action": "send", "sent_via": "dry_run"},
                    action="send", entity="setter_queue", entity_id=row.get("id"))
            except Exception:  # noqa: BLE001
                pass
        patch["sent_via"] = "dry_run"
        return {"ok": True, "row": patch}
    # Durable send claim (double-send fix 2026-08-01): flip the row to
    # 'sending' with the CURRENT status as the predicate — one conditional
    # PATCH whose empty representation means another request already claimed
    # it (or the status moved under us). The loser aborts before any
    # Smartlead call.
    cur = str(row.get("status") or "")
    if _SB and row.get("id") is not None:
        # updated_at rides on the claim (panel fix 2026-08-01): the column has
        # no update trigger, so without this the claim's age reads as the
        # row's INTAKE age — the reaper ate live claims and the recency
        # gate's in-flight arm was dead for any row older than 15 minutes.
        claimed = _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{row.get('id')}"
                               f"&status=eq.{quote(cur, safe='')}",
                      {"status": "sending", "updated_at": now}, "return=representation")
        if isinstance(claimed, list) and not claimed:
            return {"ok": False, "already_in_flight": True,
                    "row": {"error": "This reply is already being sent by another request — "
                                     "nothing was sent twice."}}
        row["status"] = "sending"
    # Recency gate AFTER the claim (claim-then-verify, panel fix 2026-08-01):
    # checking before the claim was a cross-row TOCTOU — two rows for one
    # lead could both pass the read and both post. With the claim held, a
    # racing sibling either sees this claim (its verify blocks) or wins its
    # own claim first (this verify blocks). ONE check per send, all callers
    # (the routes no longer pre-check — they map "blocked" to a 429).
    blk = _recent_send_block(row, followup=followup)
    if blk:
        if followup:
            # The thread is genuinely sent — restore, never re-open review.
            _apply_patch(row, {"status": cur, "error": blk})
        else:
            _apply_patch(row, {"status": "needs_review", "error": blk})
        return {"ok": False, "blocked": blk, "row": {"status": row.get("status"), "error": blk}}
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
            # A failed FOLLOW-UP must restore the sent status itself (the
            # thread genuinely went out earlier) — needs_review would re-arm
            # Approve on an answered thread (panel fix 2026-08-01).
            patch = ({"status": cur, "error": str(resp)[:300]} if followup
                     else {"status": "needs_review", "error": str(resp)[:300]})
            _apply_patch(row, patch)
            return {"ok": False, "row": patch}
        patch = _success_patch()
        if not _apply_patch(row, patch):
            # The mail LEFT — that truth outranks the record. Retry the write
            # once; if it still fails, say so loudly in the response instead
            # of returning a clean success over a row that doesn't reflect it
            # (panel fix 2026-08-01: for a follow-up this also means the
            # recency record didn't stick).
            _time.sleep(0.5)
            if not _apply_patch(row, patch):
                patch = {**patch, "error": "The email was SENT, but recording it failed — "
                                           "do not re-send; wait 10 minutes and check Smartlead."}
        if _LOG:
            try:
                _LOG("/api/setter/queue/action", {"id": row.get("id"), "action": "send"},
                    action="send", entity="setter_queue", entity_id=row.get("id"))
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "row": patch}
    except Exception as e:  # noqa: BLE001 - a send crash must land as needs_review, never raise
        # A 429 only reaches here after _sl_post exhausted its inline retries —
        # Smartlead is sustaining a rate-limit. Nothing was sent (a 429 = request
        # rejected), so say so in plain English the reviewer can act on rather
        # than relaying "HTTP Error 429: Too Many Requests".
        msg = str(e)[:300]
        if getattr(e, "code", None) == 429 or "429" in msg:
            msg = ("Smartlead is rate-limiting sends right now, so this reply "
                   "wasn't sent. Nothing went out — wait a minute and try again.")
        patch = ({"status": cur, "error": msg} if followup
                 else {"status": "needs_review", "error": msg})
        _apply_patch(row, patch)
        return {"ok": False, "row": patch}


def _finalize_row(row: dict) -> dict:
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    row.setdefault("created_at", now_iso)
    row["updated_at"] = now_iso
    if not _SB:
        row.setdefault("id", None)
        return row
    # Enrich-on-reply (owner ask 2026-08-15): every real reply landing in the
    # queue kicks a ONE-TIME background enrichment (phone + company facts) for
    # the warm-call sideboard. The setter_lead_enrichment cache row is the
    # never-pay-twice guard, so re-intakes and redrives are free no-ops.
    if not row.get("is_test") and row.get("lead_email"):
        try:
            threading.Thread(target=_enrich_on_reply,
                             args=(row["lead_email"], row.get("company_domain") or "",
                                   row.get("workspace") or WORKSPACE),
                             daemon=True).start()
        except Exception:  # noqa: BLE001 - enrichment must never block intake
            pass
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
                    # Owner ruling 2026-08-15: a stranded row with no stored
                    # timezone assumes Eastern - times are always proposed.
                    tz = row.get("timezone") or "America/New_York"
                    slots, slot_status, serr = [], "not_configured", ""
                    eff_settings = dict(_load_settings())
                    eff_settings["_agent"] = snapshot
                    eff_settings["_lead"] = {"first_name": row.get("lead_first_name"),
                                             "last_name": row.get("lead_last_name"),
                                             "email": row.get("lead_email")}
                    slot_status, avail, serr = get_calendly_availability(snapshot, eff_settings, now)
                    if slot_status == "ok":
                        slots = pick_slots(avail, tz, eff_settings, now)
                        if not slots:
                            slot_status = "none_available"
                    thread_text = " ".join(str(m.get("body") or "") for m in (row.get("thread") or []))
                    d = draft_reply(
                        {"first_name": row.get("lead_first_name"), "subject": row.get("reply_subject"),
                         "body": row.get("reply_body"), "first_outbound": first_outbound,
                         "thread": row.get("thread"),
                         "thread_text": thread_text, "timezone": tz},
                        snapshot, classification, slots, slot_status,
                        sender_first=_sender_first_for(snapshot))
                    draft_html = d.get("html")
                    if draft_html:
                        draft_html, _changed = proofread_draft(draft_html, _sender_first_for(snapshot))
                    patch = {"agent_id": agent.get("id"), "classification": classification,
                             "draft_subject": d.get("subject"), "draft_body": draft_html,
                             "original_draft_body": draft_html, "slots": slots,
                             "guardrails": {**(row.get("guardrails") or {}),
                                            **slot_situation(slot_status, tz, slots, serr)}}
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
        redrive_id = reply.get("_redrive_id")

        # The archive label never reaches the queue row - the lead keeps its
        # real category (see _resolve_re_reply_category).
        if not is_test and str(reply.get("category") or "").strip().lower() == _RE_REPLY_LABEL:
            real_cat = _resolve_re_reply_category(workspace, campaign_id, email,
                                                  reply.get("replied_at"))
            if real_cat:
                reply["category"] = real_cat

        if not is_test and redrive_id is None:
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
        if redrive_id is not None:
            # Adopt-in-place (same mechanism as process_reply's redrive): the
            # convert path re-runs an EXISTING row through this intake, and
            # _finalize_row PATCHes an id'd row instead of inserting — no
            # delete window, no unique-key conflict (panel fix 2026-08-01).
            row["id"] = redrive_id
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


def _intake_uncategorised(reply: dict, agent: dict = None) -> dict:
    """Uncategorised intake (ship 2026-07-20): a reply the categoriser failed
    on (or explicitly gave up on) still reaches setter_queue - status
    needs_review, category left empty, NO classify/draft/decide: there is no
    verdict to act on until a human picks the real category via the
    recategorise dropdown, or the categoriser fills it in late and the poll's
    auto-resolve converts/dismisses the row. Hydrates the Smartlead thread
    best-effort exactly like the agentless path - triage needs the
    conversation context. Never raises - mirrors _intake_agentless."""
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
            "workspace": workspace, "smartlead_campaign_id": campaign_id,
            "agent_id": (agent or {}).get("id"),
            "lead_email": email, "lead_first_name": reply.get("first_name") or "",
            "lead_last_name": reply.get("last_name") or "", "company_domain": domain,
            "message_id": message_id, "source_message_id": message_id,
            "reply_subject": reply.get("subject") or "",
            "reply_body": reply.get("body") or "", "replied_at": reply.get("replied_at") or now_iso,
            "category": None, "category_source": None, "thread": [], "smartlead_lead_id": None,
            "email_stats_id": None, "classification": None, "guardrails": None,
            "timezone": None, "slots": [], "draft_subject": None, "draft_body": None,
            "decision": "review",
            "decision_reason": "This reply was never auto-categorised - the categoriser failed or "
                               "gave up on it. Pick its Smartlead category to resolve it: a positive "
                               "category runs the normal Setter pipeline, anything else removes it "
                               "from the Setter.",
            "status": "needs_review",
            "added_to_subsequence": False, "sent_at": None, "sent_body": None, "error": None,
            "is_test": is_test,
        }
        # Same best-effort context hydration as the agentless path: an
        # uncategorised row is a triage decision, and "is this a positive?"
        # can't be judged without the conversation and the original outreach.
        if not is_test:
            try:
                ok, hyd, _herr = hydrate_lead(campaign_id, email, message_id)
                if ok:
                    row["smartlead_lead_id"] = hyd.get("smartlead_lead_id")
                    row["email_stats_id"] = hyd.get("email_stats_id")
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
    except Exception as e:  # noqa: BLE001 - uncategorised intake must never crash its caller
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
    # The archive label never reaches the queue row - the lead keeps its real
    # category (see _resolve_re_reply_category). Runs before the claim insert
    # below so the claimed row is already stamped with the real category.
    if not is_test and str(reply.get("category") or "").strip().lower() == _RE_REPLY_LABEL:
        real_cat = _resolve_re_reply_category(workspace, campaign_id, email,
                                              reply.get("replied_at"))
        if real_cat:
            reply["category"] = real_cat
    # Re-drive of a stranded claim (see _redrive_stranded_claims): the queue
    # row ALREADY exists - it is the husk of a tick that died between the
    # claim and the finish - so the existing-row short-circuit below would
    # hand back the same invisible row forever. Adopt its id instead of
    # claiming a new one and let _finalize_row PATCH the result in place.
    redrive_id = reply.get("_redrive_id")

    if not is_test and redrive_id is None:
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
        # Test-inject rows may carry a caller-built thread (the downstream
        # first_outbound fallback and draft transcript have expected one all
        # along); real rows always get theirs from hydration below.
        "category": reply.get("category"),
        "thread": (reply.get("thread") or []) if bool(reply.get("is_test")) else [],
        "smartlead_lead_id": None,
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
    if redrive_id is not None:
        row["id"] = redrive_id
        reply["_claimed_id"] = redrive_id   # crash handler marks THIS row errored
    elif not is_test and _SB:
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
    # Owner training rule (2026-08-16, round 1): "No matter what they say,
    # always say something." Every HUMAN reply carries a draft even when it
    # is a clear negative (not_interested / unsubscribe / wrong_person) - the
    # reviewer wants a starting point, and decide() still routes the row
    # (no_action rows just carry their draft quietly). Only machine mail
    # (bounces, OOO autoreplies) keeps the no-draft short-circuit.
    human_reply = primary not in ("ooo", "bounce_or_system")
    wants_draft = (not is_clear_negative) or negative_but_surfaces or human_reply

    slots, slot_status, serr = [], "not_configured", ""
    if wants_draft:
        eff_settings = dict(settings)
        eff_settings["_agent"] = agent
        eff_settings["_lead"] = {"first_name": row["lead_first_name"], "last_name": row["lead_last_name"], "email": email}
        # Owner ruling 2026-08-15: resolve_timezone() always returns a zone
        # (Eastern assumed when there is zero signal), so slots are ALWAYS
        # built - a lead never gets a bare availability ask just because we
        # couldn't place them. _slot_label stamps each time with its zone
        # (ET etc.), so an assumed zone is visible, never silent.
        slot_status, avail, serr = get_calendly_availability(agent, eff_settings, now)
        if slot_status == "ok":
            slots = pick_slots(avail, tz, eff_settings, now)
            if not slots:
                slot_status = "none_available"
        if serr and not row.get("error"):
            row["error"] = serr
    row["slots"] = slots
    row["guardrails"].update(slot_situation(slot_status, tz, slots, serr))

    draft_subject, draft_body = None, None
    if wants_draft:
        try:
            # call_ask (owner report 2026-07-25): on a later turn the lead's
            # newest message decides whether a call gets pitched again - the
            # two-call-times paragraph is no longer unconditional.
            _inbound_turns = sum(1 for m in (row.get("thread") or [])
                                 if isinstance(m, dict) and str(m.get("type") or "").upper() != "SENT")
            d = draft_reply(
                {"first_name": row["lead_first_name"], "subject": row["reply_subject"], "body": body_text,
                 "first_outbound": first_outbound, "thread_text": thread_text,
                 "thread": row.get("thread"),
                 "timezone": row.get("timezone"),
                 "call_ask": call_ask_for(classification, body_text, thread_text,
                                          first_touch=_inbound_turns <= 1)},
                agent, classification, slots, slot_status, sender_first, regen_feedback=mem_digest)
            draft_subject, draft_body = d.get("subject"), d.get("html")
            if draft_body:
                # Second sweep (owner brief 2026-07-14): proofread the draft
                # BEFORE lint_draft below, so lint checks the final text.
                draft_body, _proofread_changed = proofread_draft(draft_body, sender_first)
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
        # Keep the draft (owner training rule 2026-08-16: "no matter what
        # they say, always say something") - a no_action row now carries its
        # starting point instead of a blank composer. Nothing sends here.
        row["draft_subject"], row["draft_body"] = draft_subject, draft_body
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
EMPTY_BODY_GRACE_H = 6         # empty-bodied reply older than this = mark seen, stop retrying
#   (a genuinely blank reply — e.g. an accidental empty send whose HTML strips
#   to "" — must not pin the watermark forever: it froze the whole backstop
#   from 2026-07-21 to 2026-07-24. Within the grace window we still retry,
#   which covers Smartlead's thread-indexing lag for real bodies.)
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


def _fetch_master_inbox_window(since_iso: str, until_iso: str, hard_cap: int, api_key=None):
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
        kwargs = {"api_key": api_key} if api_key else {}
        resp = _sl_post("/master-inbox/inbox-replies", {
            "limit": page_size, "offset": offset, "sortBy": "REPLY_TIME_DESC",
            "filters": {"emailStatus": "Replied",
                        "replyTimeBetween": [since_iso, until_iso]},
        }, **kwargs)
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
               "skipped_archived": 0, "skipped_empty": 0, "errors": 0, "gap": 0,
               "overflow": False, "watermark_before": None,
               "watermark_after": None, "first_run": False}
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
                    # advance past it; a later tick retries. Past the grace
                    # window the emptiness is permanent, not indexing lag:
                    # mark seen so the watermark can cross it.
                    if rt_dt and (now - rt_dt) > _dt.timedelta(hours=EMPTY_BODY_GRACE_H):
                        _mark_reply_seen(mid)
                        summary["skipped_empty"] += 1
                        handled = True
                    else:
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


# ── client-workspace backstop reply-sync (ship 2026-08-09) ───────────────────
# run_reply_sync above is navreo-only: the master-inbox path carries no
# campaign id, so _sl_key_for falls back to the navreo key and client
# workspaces were never polled. Their Make webhook chain was therefore a
# single point of failure - a dead delivery dropped replies silently for
# days (the Asteri 2026-08-04 outage: 38/41 replies invisible in-tool until
# the 2026-08-09 audit). This sweep closes the hole: per-workspace watermark,
# master-inbox pull with the WORKSPACE'S OWN key, and a direct `replies`
# insert (dedup = the same unique smartlead_message_id index the ingest edge
# function relies on). No Make, no Slack, no sends - the archived row then
# surfaces through _poll_monitor_workspaces like any other client reply
# (positives + uncategorised only, always agentless, monitor-only).
CLIENT_SYNC_CAP = 40           # per-workspace replies per run; overflow => FAILED + gap
# reply_sync_state's CHECK constraint pins ids to {1,2}, so per-workspace
# watermarks live as one "wm:<ws>" row each in reply_sync_seen with the value
# in seen_at. The prefix can never collide with a real message id (those are
# always "<digits>-<iso>").
_WS_WM_PREFIX = "wm:"


def _ws_sync_watermark(ws: str):
    """Per-workspace watermark; seeds now-minus-2h when absent.
    Returns (watermark_dt, seeded: bool)."""
    now = _dt.datetime.now(_dt.timezone.utc)
    key = f"{_WS_WM_PREFIX}{ws}"
    rows = _SB("GET", f"reply_sync_seen?message_id=eq.{quote(key, safe='')}"
                      f"&select=seen_at&limit=1") if _SB else None
    if isinstance(rows, list) and rows and rows[0].get("seen_at"):
        wm = _parse_iso(rows[0]["seen_at"])
        if wm:
            return wm, False
    seed = now - _dt.timedelta(hours=_REPLY_SYNC_FIRST_WINDOW_H)
    if _SB:
        _SB("POST", "reply_sync_seen", {"message_id": key, "seen_at": seed.isoformat()},
            prefer="resolution=merge-duplicates")
    return seed, True


def _save_ws_sync_watermark(ws: str, wm_dt) -> None:
    if _SB:
        _SB("PATCH", f"reply_sync_seen?message_id=eq.{quote(_WS_WM_PREFIX + ws, safe='')}",
            {"seen_at": wm_dt.isoformat()})


def _reply_in_archive_ws(ws: str, mid: str) -> bool:
    """Workspace-scoped twin of _reply_in_archive (which is navreo-pinned)."""
    if not _SB or not mid:
        return False
    rows = _SB("GET", f"replies?workspace=eq.{ws}"
                      f"&smartlead_message_id=eq.{quote(mid, safe='')}&select=id&limit=1")
    return isinstance(rows, list) and bool(rows)


def _ws_category_names(api_key: str) -> dict:
    """Smartlead category id -> name for one workspace account. Best-effort."""
    try:
        cats = _HTTP("GET", f"{SMARTLEAD_BASE}/leads/fetch-categories?api_key={api_key}", {})
        if isinstance(cats, list):
            return {c.get("id"): (c.get("name") or "") for c in cats if isinstance(c, dict)}
    except Exception:  # noqa: BLE001 - a failed map just means archiving uncategorised
        pass
    return {}


def _ws_reply_body(api_key: str, cid, lead_id, rtime) -> str:
    """The reply's cleaned body via per-campaign message history (the
    workspace key works on campaign paths; master-inbox rows carry no body)."""
    try:
        resp = _HTTP("GET", f"{SMARTLEAD_BASE}/campaigns/{cid}/leads/{lead_id}"
                            f"/message-history?api_key={api_key}", {})
        hist = resp.get("history") if isinstance(resp, dict) else None
        best = None
        for h in hist or []:
            if isinstance(h, dict) and h.get("type") == "REPLY":
                if (h.get("time") or "")[:19] == str(rtime)[:19]:
                    return clean_body(h.get("email_body") or "")
                best = h
        return clean_body((best or {}).get("email_body") or "")
    except Exception:  # noqa: BLE001 - body fetch failure = retry within grace
        return ""


def run_client_reply_sync() -> dict:
    """Backstop pull for every enabled NON-navreo workspace: master inbox ->
    direct `replies` insert for every unseen reply. Never raises. ok=False on
    any per-workspace cap-hit or error, with per-workspace summaries."""
    summary = {"ok": True, "workspaces": {}, "errors": 0}
    if not _SB:
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = "Supabase not configured"
        return summary
    rows = _SB("GET", "workspaces?select=id,api_key,status&order=added_at")
    targets = [(r.get("id"), r.get("api_key")) for r in (rows if isinstance(rows, list) else [])
               if isinstance(r, dict) and r.get("id") and r.get("id") != "navreo"
               and (r.get("status") or "enabled") == "enabled" and r.get("api_key")]
    for ws, api_key in targets:
        s = {"ok": True, "checked": 0, "archived": 0, "skipped_seen": 0,
             "skipped_archived": 0, "archived_bodyless": 0, "errors": 0,
             "gap": 0, "overflow": False, "first_run": False}
        summary["workspaces"][ws] = s
        try:
            wm, seeded = _ws_sync_watermark(ws)
            now = _dt.datetime.now(_dt.timezone.utc)
            s["first_run"] = seeded
            since_iso = wm.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            until_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            inbox, overflow = _fetch_master_inbox_window(since_iso, until_iso,
                                                         CLIENT_SYNC_CAP, api_key=api_key)
            s["checked"] = len(inbox)
            s["overflow"] = overflow
            to_process = inbox[:CLIENT_SYNC_CAP]
            if overflow or len(inbox) > CLIENT_SYNC_CAP:
                s["ok"] = False                 # cap-hit: FAILED, never silent
                summary["ok"] = False
                s["gap"] = max(0, len(inbox) - CLIENT_SYNC_CAP)
            catmap = None                       # fetched lazily, once per workspace
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
                mid = f"{lead_id}-{rtime}"      # == ingest/categoriser archive key
                rt_dt = _parse_iso(rtime)
                handled = False
                if _reply_sync_seen(mid):
                    s["skipped_seen"] += 1
                    handled = True
                elif _reply_in_archive_ws(ws, mid):
                    _mark_reply_seen(mid)
                    s["skipped_archived"] += 1
                    handled = True
                else:
                    text = _ws_reply_body(api_key, cid, lead_id, rtime)
                    past_grace = rt_dt and (now - rt_dt) > _dt.timedelta(hours=EMPTY_BODY_GRACE_H)
                    if text or past_grace:
                        if catmap is None:
                            catmap = _ws_category_names(api_key)
                        raw_cat = r.get("lead_category_id")
                        try:
                            raw_cat = int(raw_cat)
                        except (TypeError, ValueError):
                            raw_cat = None
                        _SB("POST", "replies",
                            {"workspace": ws, "client_id": ws,
                             "smartlead_campaign_id": cid, "email": email.lower(),
                             "replied_at": rtime,
                             "category": (catmap.get(raw_cat) or "") if raw_cat is not None else "",
                             "smartlead_message_id": mid,
                             "reply_subject": "", "reply_body": text},
                            prefer="resolution=ignore-duplicates")
                        _mark_reply_seen(mid)
                        s["archived"] += 1
                        if not text:
                            s["archived_bodyless"] += 1
                        handled = True
                    # else: no body yet and within grace - leave UNSEEN so a
                    # later tick retries (thread-indexing lag), watermark freezes.
                if handled and not frozen:
                    if rt_dt and rt_dt > advanced_to:
                        advanced_to = rt_dt
                elif not handled:
                    frozen = True
            if advanced_to > wm or seeded:
                _save_ws_sync_watermark(ws, advanced_to)
        except Exception as e:  # noqa: BLE001 - one workspace must never sink the rest
            s["ok"] = False
            s["errors"] += 1
            s["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            summary["ok"] = False
            summary["errors"] += 1
    return summary


# ── client-workspace archive reconcile (analytics-accuracy 2026-08-10) ──────
# run_client_reply_sync above only moves FORWARD from a first-run watermark
# seeded now-minus-2h, so every reply that predates a workspace's first sync
# never reaches `replies` (KRG: 6 of its 7 window positives were missing —
# the analytics page said 1), and `category` is stamped once at archive time,
# so a client team categorising in Smartlead AFTER our pull leaves the archive
# stale forever (Asteri: 52 NULL-category rows). This sweep re-walks the
# trailing RECONCILE_WINDOW_D days of each enabled client workspace's master
# inbox and (a) inserts any reply missing from the archive, (b) re-stamps
# `category` from Smartlead when it differs — on client workspaces the
# client's own Smartlead categorisation is category-truth. Existing rows are
# matched by mid AND by (email, replied_at): router-archived rows can carry a
# different message-id vocabulary and must not be duplicated. Rides the 3-min
# reply-sync tick, self-throttled via a reply_sync_seen KV row (the
# reply_sync_state table has a check constraint pinning id to existing rows,
# so the throttle rides the same store the per-ws watermarks use).
_RECONCILE_WM_KEY = "wm:reconcile"
RECONCILE_THROTTLE_H = 6
RECONCILE_WINDOW_D = 35        # covers the page's 30d range with margin
RECONCILE_PAGE_CAP = 1500      # per-ws replies per sweep; hitting it reports FAILED


def _reconcile_last_run():
    rows = _SB("GET", f"reply_sync_seen?message_id=eq.{quote(_RECONCILE_WM_KEY, safe='')}"
                      f"&select=seen_at&limit=1")
    if isinstance(rows, list) and rows and rows[0].get("seen_at"):
        return _parse_iso(rows[0]["seen_at"])
    return None


def run_client_reply_reconcile(force: bool = False, days: int = RECONCILE_WINDOW_D) -> dict:
    """Trailing-window archive reconcile for every enabled non-navreo
    workspace: backfill missing replies + late-fill categories. Never raises.
    force=True skips the cadence throttle (tests / manual runs)."""
    summary = {"ok": True, "skipped": False, "workspaces": {}, "errors": 0}
    if not _SB:
        summary.update(ok=False, errors=1, error="Supabase not configured")
        return summary
    now = _dt.datetime.now(_dt.timezone.utc)
    last = _reconcile_last_run()
    if not force and last is not None and \
            (now - last) < _dt.timedelta(hours=RECONCILE_THROTTLE_H):
        summary["skipped"] = True
        return summary
    rows = _SB("GET", "workspaces?select=id,api_key,status&order=added_at")
    targets = [(r.get("id"), r.get("api_key")) for r in (rows if isinstance(rows, list) else [])
               if isinstance(r, dict) and r.get("id") and r.get("id") != "navreo"
               and (r.get("status") or "enabled") == "enabled" and r.get("api_key")]
    since_dt = now - _dt.timedelta(days=days)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    until_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for ws, api_key in targets:
        s = {"ok": True, "checked": 0, "backfilled": 0, "recategorised": 0,
             "already_ok": 0, "errors": 0, "overflow": False}
        summary["workspaces"][ws] = s
        try:
            inbox, overflow = _fetch_master_inbox_window(since_iso, until_iso,
                                                         RECONCILE_PAGE_CAP, api_key=api_key)
            s["checked"] = len(inbox)
            s["overflow"] = overflow
            if overflow:
                s["ok"] = False       # partial coverage must be visible, never silent
                summary["ok"] = False
            # one bulk read of the ws's archived window -> match maps
            arch, off = [], 0
            while True:
                page = _SB("GET", f"replies?workspace=eq.{ws}&select=id,email,replied_at,"
                                  f"category,smartlead_message_id"
                                  f"&replied_at=gte.{since_dt.date().isoformat()}"
                                  f"&order=id&limit=1000&offset={off}") or []
                arch.extend(page)
                if len(page) < 1000:
                    break
                off += 1000
            by_mid = {str(a.get("smartlead_message_id") or ""): a for a in arch}
            by_em_t = {((a.get("email") or "").lower(), str(a.get("replied_at") or "")[:19]): a
                       for a in arch}
            catmap = _ws_category_names(api_key)
            for r in inbox[:RECONCILE_PAGE_CAP]:
                if not isinstance(r, dict):
                    continue
                lead_id = r.get("email_lead_id")
                rtime = r.get("last_reply_time")
                cid = r.get("email_campaign_id")
                email = (r.get("lead_email") or "").strip().lower()
                if not lead_id or not rtime or not cid or not email:
                    continue
                mid = f"{lead_id}-{rtime}"
                raw_cat = r.get("lead_category_id")
                try:
                    raw_cat = int(raw_cat)
                except (TypeError, ValueError):
                    raw_cat = None
                sl_cat = (catmap.get(raw_cat) or "") if raw_cat is not None else ""
                hit = by_mid.get(mid) or by_em_t.get((email, str(rtime)[:19]))
                if hit is None:
                    text = _ws_reply_body(api_key, cid, lead_id, rtime)
                    _SB("POST", "replies",
                        {"workspace": ws, "client_id": ws,
                         "smartlead_campaign_id": cid, "email": email,
                         "replied_at": rtime, "category": sl_cat,
                         "smartlead_message_id": mid,
                         "reply_subject": "", "reply_body": text},
                        prefer="resolution=ignore-duplicates")
                    _mark_reply_seen(mid)
                    s["backfilled"] += 1
                elif sl_cat and (hit.get("category") or "") != sl_cat:
                    _SB("PATCH", f"replies?id=eq.{hit['id']}", {"category": sl_cat})
                    s["recategorised"] += 1
                else:
                    s["already_ok"] += 1
        except Exception as e:  # noqa: BLE001 - one workspace must never sink the rest
            s["ok"] = False
            s["errors"] += 1
            s["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            summary["ok"] = False
            summary["errors"] += 1
    _SB("POST", "reply_sync_seen?on_conflict=message_id",
        {"message_id": _RECONCILE_WM_KEY, "seen_at": now.isoformat()},
        prefer="resolution=merge-duplicates,return=minimal")
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
                    # thread not hydrated yet — leave unseen, retry next sweep;
                    # but past the grace window the body is permanently empty
                    # (blank send), so mark seen instead of re-hydrating forever.
                    rt_dt = _parse_iso(r.get("last_reply_time"))
                    if rt_dt and (now - rt_dt) > _dt.timedelta(hours=EMPTY_BODY_GRACE_H):
                        to_mark.append(mid)
                        summary["skipped_empty"] = summary.get("skipped_empty", 0) + 1
                    else:
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


# ── ever-positive alert sweep ────────────────────────────────────────────────
# The categoriser's Slack gates all key off the CURRENT reply: routeA's
# module 33 announces fresh POSITIVE categorisations only (Not Interested and
# friends post nothing), and routeB's 🚨 fires only when THIS campaign's
# existing category is positive. A lead whose positive history lives on a
# DIFFERENT campaign id (parent vs spawned "Interested Reply"/"Meeting
# Request" subsequence) and whose new reply categorises negative passes both
# gates silently — proven live 2026-07-20: gabriel@silver.dev (Information
# Request on 3356261 Jul 17, alerted) replied on subsequence 3356263, GPT said
# Not Interested, module 7 flipped the Smartlead category, zero Slack, and the
# thread vanished mid-conversation (replies id 19418). This sweep is the
# LEAD-level guarantee: any newly archived reply from an ever-positive lead
# alerts #interested-replies exactly once, whatever the new category says.
# Positive categories are excluded here on purpose — module 33 owns fresh
# positives and routeB owns still-positive re-replies (archived as
# "positive-re-reply") — so this sweep can never double-post those classes.
# Fail-closed: the notify_alerted_at marker is stamped only after the alert
# hook ACCEPTED the post; unmarked rows retry on every 3-min tick.
EVER_POSITIVE_HOOK = "https://hook.eu2.make.com/aag8t06k43jn0wjnvktt02rpbr2xwmec"
POSITIVE_CATEGORY_NAMES = ("Interested", "Meeting Request", "Information Request",
                           "Call Booked", "positive-re-reply")
EP_WORKSPACES = ("navreo", "opan-test")  # opan-test = mock isolation; Setter reads navreo only
EP_LOOKBACK_HOURS = 72        # scan window; the marker (not the window) stops re-alerts
EP_NULL_GRACE_MIN = 45        # uncategorised rows younger than this are still in flight
EP_POST_CAP = 10              # tripwire per tick; leftovers retry next tick, loudly


def _ep_stamp(row_id, kind: str):
    """Mark a replies row handled by this sweep (notify_kind says why)."""
    _SB("PATCH", f"replies?id=eq.{row_id}",
        {"notify_alerted_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
         "notify_kind": kind}, prefer="return=minimal")


def _ep_prior_positive(workspace, email: str, before_iso: str):
    """Latest positive-category row for this lead BEFORE the given instant,
    same workspace, ANY campaign — the ever-positive predicate."""
    cats = ",".join(quote(c, safe="") for c in POSITIVE_CATEGORY_NAMES)
    rows = _SB("GET", f"replies?workspace=eq.{workspace}"
                      f"&email=ilike.{quote(email, safe='')}"
                      f"&category=in.({cats})"
                      f"&replied_at=lt.{quote(before_iso, safe='')}"
                      f"&select=category,replied_at,smartlead_campaign_id"
                      f"&order=replied_at.desc&limit=1")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _ep_campaign_names(workspace, ids) -> dict:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    rows = _SB("GET", f"campaigns?workspace=eq.{workspace}"
                      f"&smartlead_campaign_id=in.({','.join(ids)})"
                      f"&select=smartlead_campaign_id,name")
    out = {}
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict):
                out[str(r.get("smartlead_campaign_id"))] = r.get("name") or ""
    return out


def _chat_permalink(email: str, message_id: str = "") -> str:
    """Deep link straight to this lead's chat in the setter (resolved by
    /api/setter/queue/locate; message_id refines, email alone still lands).
    Used by every Slack alert composer — the tool-root link never is."""
    email = (email or "").strip().lower()
    if not email:
        return ""
    url = f"{DEFAULT_BASE_URL}/app/setter.html#/r/{quote(email, safe='')}"
    mid = str(message_id or "").strip()
    if mid:
        url += f"/{quote(mid, safe='')}"
    return url


def _ep_smartlead_link(campaign_id, email: str) -> str:
    """Best-effort master-inbox deep link for the alert. Never raises."""
    try:
        data = _sl_get("/leads/", {"email": email}) or {}
        for lc in data.get("lead_campaign_data") or []:
            if str(lc.get("campaign_id")) == str(campaign_id) and \
                    lc.get("campaign_lead_map_id"):
                return ("https://app.smartlead.ai/app/master-inbox?action=INBOX"
                        f"&leadMap={lc['campaign_lead_map_id']}")
    except Exception:  # noqa: BLE001 — the link is decoration, never load-bearing
        pass
    return ""


def _ep_compose(row: dict, prior: dict, camp_names: dict) -> str:
    cid = str(row.get("smartlead_campaign_id") or "")
    cname = camp_names.get(cid) or f"campaign {cid}"
    if cname in ("Interested Reply", "Meeting Request"):
        cname += " (subsequence)"
    pcid = str(prior.get("smartlead_campaign_id") or "")
    pname = camp_names.get(pcid) or (f"campaign {pcid}" if pcid else "earlier campaign")
    cat = row.get("category") or "uncategorised"
    snippet = clean_body(row.get("reply_body") or "")[:400]
    link = _ep_smartlead_link(row.get("smartlead_campaign_id"), row.get("email") or "")
    lines = [
        f"🔔 ONCE-POSITIVE lead replied — now: {cat}",
        "---------------------------",
        f"Lead: {row.get('email')}",
        f"Campaign: {cname}",
        (f"Originally positive: {prior.get('category')} on "
         f"{str(prior.get('replied_at') or '')[:10]} ({pname})"),
        f"Time of Reply: {str(row.get('replied_at') or '')[:16]} UTC",
    ]
    chat = _chat_permalink(row.get("email") or "", row.get("smartlead_message_id") or "")
    if chat:
        lines.append(f":dart: <{chat}|Open this chat in the Appointment Setter>")
    if link:
        lines.append(f":speech_balloon: <{link}|Open conversation in Smartlead>")
    lines += ["", "Reply:", snippet or "(no body archived)"]
    return "\n".join(lines)


def run_ever_positive_alerts() -> dict:
    """Lead-level notification guarantee over the replies archive (see the
    section comment above). Rides every 3-min reply-sync tick. Never raises."""
    summary = {"ok": True, "skipped": False, "checked": 0, "alerted": 0,
               "stamped_positive": 0, "stamped_no_history": 0,
               "deferred_null": 0, "failed_posts": 0, "capped": False,
               "errors": 0}
    if not _SB:
        summary["skipped"] = True
        return summary
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        since = (now - _dt.timedelta(hours=EP_LOOKBACK_HOURS)).isoformat()
        rows = _SB("GET", f"replies?workspace=in.({','.join(EP_WORKSPACES)})"
                          f"&notify_alerted_at=is.null"
                          f"&replied_at=gte.{quote(since, safe='')}"
                          f"&select=id,workspace,smartlead_campaign_id,email,"
                          f"replied_at,category,reply_body,smartlead_message_id"
                          f"&order=replied_at.asc&limit=200")
        if not isinstance(rows, list):
            summary["ok"] = False
            summary["errors"] += 1
            summary["error"] = "replies read returned non-list"
            return summary
        summary["checked"] = len(rows)
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            ws = row.get("workspace")
            email = (row.get("email") or "").strip()
            cat = row.get("category")
            rt = row.get("replied_at") or ""
            if not rid or not ws or not email or not rt:
                continue
            if cat in POSITIVE_CATEGORY_NAMES:
                # module 33 / routeB territory — never alert from here
                _ep_stamp(rid, "positive-covered")
                summary["stamped_positive"] += 1
                continue
            if cat is None:
                rt_dt = _parse_iso(rt)
                if not rt_dt or (now - rt_dt) < _dt.timedelta(minutes=EP_NULL_GRACE_MIN):
                    summary["deferred_null"] += 1   # still in flight — next tick
                    continue
            prior = _ep_prior_positive(ws, email, rt)
            if prior is None:
                _ep_stamp(rid, "no-positive-history")
                summary["stamped_no_history"] += 1
                continue
            if summary["alerted"] >= EP_POST_CAP:
                summary["capped"] = True
                summary["ok"] = False       # leftovers retry next tick, loudly
                continue
            names = _ep_campaign_names(
                ws, [row.get("smartlead_campaign_id"),
                     prior.get("smartlead_campaign_id")])
            text = _ep_compose(row, prior, names)
            posted = False
            try:
                _HTTP("POST", EVER_POSITIVE_HOOK, {},
                      {"event_type": "EVER_POSITIVE_ALERT", "text": text})
                posted = True
            except ValueError:
                posted = True   # Make answers a non-JSON 2xx ("Accepted") = success
            except Exception:   # noqa: BLE001 — hook down: retry next tick
                summary["failed_posts"] += 1
                summary["ok"] = False
            if posted:
                # stamp ONLY after the hook accepted — fail-closed, retryable
                _ep_stamp(rid, "ever-positive-alerted")
                summary["alerted"] += 1
        return summary
    except Exception as e:  # noqa: BLE001 — record, never crash the cron thread
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return summary


# ── Client-workspace positive alert (in-tool internal backstop) ────────────
# navreo positives are announced the moment they're categorised — the Make
# categoriser (9251436) routeA posts to #interested-replies and the
# positive-card path fires. CLIENT workspaces (grout, asteri, krg, …) have NO
# such internal ping: their Make chains at most post a card to the *client's*
# own shared Slack channel (grout has not even that), so a NEW positive on a
# client campaign archives to the setter and alerts nobody at Navreo. Proven
# 2026-08-05 by grout / sagar@eazybe.com ("how much do u charge?",
# Information Request): the reply was in `replies` with notify_* null and no
# notification had fired anywhere.
#
# This sweep is the missing backstop: every NEW positive-category reply on a
# NON-navreo workspace produces exactly one internal #interested-replies alert
# (via EVER_POSITIVE_HOOK, the same relay run_ever_positive_alerts uses) and is
# stamped with the SAME notify marker. The two sweeps read DISJOINT workspace
# sets — ever-positive: `workspace in EP_WORKSPACES`; this: `workspace not in
# EP_WORKSPACES` — so a row is only ever claimed by one of them and can never
# double-fire. Positives only, so it never touches the deliberately
# scoped-out once-positive→negative client class. Rides the reply-sync tick.
# Fail-closed and retryable (marker stamped only after the hook accepts);
# never raises.
CP_LOOKBACK_HOURS = 72        # scan window; the marker (not the window) stops re-alerts
CP_POST_CAP = 10              # tripwire per tick; leftovers retry next tick, loudly

# Per-workspace Slack channel override. A mapped workspace routes its alert to
# its OWN channel; unmapped → the hook's default (#interested-replies). The
# EVER_POSITIVE_HOOK scenario (9558449) posts to {{ifempty(1.channel; default)}},
# so a client with a dedicated channel lands there and everything else stays
# internal. Grout → #grouts-navreo (Bjion 2026-08-05). asteri/krg already get a
# card in their own channel via their Make routers, so they stay on the internal
# default here (a non-duplicate safety net), not mapped.
CLIENT_ALERT_CHANNELS = {
    "grout": "C0BEGAKS8TX",   # #grouts-navreo
}


def _cp_smartlead_link(campaign_id, email: str) -> str:
    """Master-inbox deep link resolved with the OWNING client's key
    (campaign_id → workspace key, unlike _ep_smartlead_link which uses the
    navreo key). Decoration only; never raises."""
    try:
        data = _sl_get("/leads/", {"email": email}, campaign_id=campaign_id) or {}
        for lc in data.get("lead_campaign_data") or []:
            if str(lc.get("campaign_id")) == str(campaign_id) and \
                    lc.get("campaign_lead_map_id"):
                return ("https://app.smartlead.ai/app/master-inbox?action=INBOX"
                        f"&leadMap={lc['campaign_lead_map_id']}")
    except Exception:  # noqa: BLE001 — the link is decoration, never load-bearing
        pass
    return ""


def _cp_compose(row: dict, cname: str, link: str) -> str:
    ws = row.get("workspace") or "client"
    cat = row.get("category") or "positive"
    snippet = clean_body(row.get("reply_body") or "")[:400]
    lines = [
        f"🎯 New positive reply — {ws} · {cat}",
        "---------------------------",
        f"Lead: {row.get('email')}",
        f"Campaign: {cname}",
        f"Workspace: {ws} (client)",
        f"Time of Reply: {str(row.get('replied_at') or '')[:16]} UTC",
    ]
    chat = _chat_permalink(row.get("email") or "", row.get("smartlead_message_id") or "")
    if chat:
        lines.append(f":dart: <{chat}|Open this chat in the Appointment Setter>")
    if link:
        lines.append(f":speech_balloon: <{link}|Open conversation in Smartlead>")
    lines += ["", "Reply:", snippet or "(no body archived)"]
    return "\n".join(lines)


def run_client_positive_alerts() -> dict:
    """Internal notification guarantee for a NEW positive reply on a client
    (non-navreo) workspace — the backstop navreo has and clients lacked (see
    the section comment above). Rides every reply-sync tick. Never raises."""
    summary = {"ok": True, "skipped": False, "checked": 0, "alerted": 0,
               "failed_posts": 0, "capped": False, "errors": 0}
    if not _SB:
        summary["skipped"] = True
        return summary
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        since = (now - _dt.timedelta(hours=CP_LOOKBACK_HOURS)).isoformat()
        cats = ",".join(quote(c, safe="") for c in POSITIVE_CATEGORY_NAMES)
        rows = _SB("GET", f"replies?workspace=not.in.({','.join(EP_WORKSPACES)})"
                          f"&category=in.({cats})"
                          f"&notify_alerted_at=is.null"
                          f"&replied_at=gte.{quote(since, safe='')}"
                          f"&select=id,workspace,smartlead_campaign_id,email,"
                          f"replied_at,category,reply_body,smartlead_message_id"
                          f"&order=replied_at.asc&limit=200")
        if not isinstance(rows, list):
            summary["ok"] = False
            summary["errors"] += 1
            summary["error"] = "replies read returned non-list"
            return summary
        summary["checked"] = len(rows)
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            ws = row.get("workspace")
            email = (row.get("email") or "").strip()
            cat = row.get("category")
            rt = row.get("replied_at") or ""
            # The query already filters to positives + non-navreo, but re-guard
            # here so a hand-driven call can never widen the funnel.
            if not rid or not ws or not email or not rt \
                    or cat not in POSITIVE_CATEGORY_NAMES \
                    or ws in EP_WORKSPACES:
                continue
            if summary["alerted"] >= CP_POST_CAP:
                summary["capped"] = True
                summary["ok"] = False        # leftovers retry next tick, loudly
                continue
            cid = row.get("smartlead_campaign_id")
            names = _ep_campaign_names(ws, [cid])
            cname = names.get(str(cid or "")) or (f"campaign {cid}" if cid else "unknown campaign")
            link = _cp_smartlead_link(cid, email)
            text = _cp_compose(row, cname, link)
            payload = {"event_type": "EVER_POSITIVE_ALERT", "text": text}
            chan = CLIENT_ALERT_CHANNELS.get(ws)
            if chan:
                payload["channel"] = chan   # else the hook defaults to #interested-replies
            posted = False
            try:
                _HTTP("POST", EVER_POSITIVE_HOOK, {}, payload)
                posted = True
            except ValueError:
                posted = True   # Make answers a non-JSON 2xx ("Accepted") = success
            except Exception:   # noqa: BLE001 — hook down: retry next tick
                summary["failed_posts"] += 1
                summary["ok"] = False
            if posted:
                # stamp ONLY after the hook accepted — fail-closed, retryable
                _ep_stamp(rid, "client-positive-alerted")
                summary["alerted"] += 1
        return summary
    except Exception as e:  # noqa: BLE001 — record, never crash the cron thread
        summary["ok"] = False
        summary["errors"] += 1
        summary["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return summary


def _convert_uncat_row(row: dict, category: str, source: str, settings: dict = None) -> dict:
    """An uncategorised queue row just got a real CORE_FOUR category (the
    recategorise dropdown, or the categoriser filling it in late): re-run the
    reply through the SAME intake it would have taken originally, drafting and
    all. The stale triage row is deleted first so process_reply's claim insert
    wins cleanly - the reply's identity lives in (workspace, campaign, email,
    message id), so nothing is lost with the row. Never raises."""
    try:
        cid = row.get("smartlead_campaign_id")
        email = (row.get("lead_email") or "").strip().lower()
        mid = str(row.get("source_message_id") or row.get("message_id") or "")
        reply = {
            "workspace": row.get("workspace") or WORKSPACE, "campaign_id": cid, "email": email,
            "first_name": row.get("lead_first_name"), "last_name": row.get("lead_last_name"),
            "company_domain": row.get("company_domain"),
            "subject": row.get("reply_subject") or "", "body": row.get("reply_body") or "",
            "replied_at": row.get("replied_at"), "message_id": mid,
            "category": category, "is_test": bool(row.get("is_test")),
            # ADOPT the existing row in place (panel fix 2026-08-01): the old
            # delete-before-reinsert opened a window where a failed re-intake
            # permanently lost the reply — and its unique key made
            # insert-first impossible. The redrive mechanism PATCHes the same
            # id through the full pipeline instead; on any failure the
            # original row still exists.
            "_redrive_id": row.get("id"),
        }
        # A monitor-workspace reply is never given an agent brain — its
        # campaign ids can collide with a navreo agent's list, and an agented
        # convert could dry-"send" on a client row (panel fix 2026-08-01).
        agent = None if _is_monitor_ws(row.get("workspace")) else _agent_for_campaign(cid)
        if agent:
            new_row = process_reply(reply, agent, settings or _load_settings())
        else:
            new_row = _intake_agentless(reply)
        # A finalize whose PATCH failed hands back the row with a db-error
        # marker — treating that as success returned a false 200 "converted"
        # AND (via the category_source stamp) blocked the auto-resolver from
        # ever retrying the reply (panel fix 2026-08-01).
        if str((new_row or {}).get("error") or "").startswith("db insert failed"):
            return {}
        if _SB and (new_row or {}).get("id") is not None:
            # Adopt-in-place context rescue: a convert during a Smartlead
            # outage rebuilds the row with an empty thread/ids — restore the
            # triage row's already-hydrated context instead of losing it.
            keep = {"category_source": source}
            if not (new_row.get("thread") or []) and (row.get("thread") or []):
                keep["thread"] = row["thread"]
            for k in ("smartlead_lead_id", "email_stats_id"):
                if not new_row.get(k) and row.get(k):
                    keep[k] = row[k]
            try:
                _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{new_row['id']}", keep)
                new_row.update(keep)
            except Exception:  # noqa: BLE001 - the stamp is bookkeeping, the row is the job
                pass
        _bust_read_caches()
        return new_row or {}
    except Exception as e:  # noqa: BLE001 - conversion must never crash its caller
        print(f"[setter] _convert_uncat_row failed for row {row.get('id')}: {e}", file=sys.stderr)
        return {}


def _sweep_uncategorised(agents, settings, since_iso: str, summary: dict) -> None:
    """Two passes, both bounded, both never raising:
    1) AUTO-RESOLVE: queued uncategorised rows whose `replies` row has since
       been categorised (late Make fill / reply-sync) - CORE_FOUR converts
       through the normal pipeline, anything else is dismissed with the
       category recorded. Rows a human already resolved are structurally out
       of scope: their category is set, so they are no longer uncategorised,
       and manual verdicts are authoritative (house law).
    2) INTAKE: `replies` rows still uncategorised past UNCAT_GRACE_HOURS get
       queued via _intake_uncategorised - same campaign scoping and
       assigned-at backlog gate as the positive sweep, capped at
       UNCAT_PER_TICK so stragglers never starve positives."""
    if not _SB:
        return
    now = _dt.datetime.now(_dt.timezone.utc)
    # ── pass 1: auto-resolve ──
    try:
        queued = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=eq.needs_review"
                            f"&order=created_at.desc&limit=200"
                            f"&select=id,workspace,smartlead_campaign_id,lead_email,lead_first_name,"
                            f"lead_last_name,company_domain,reply_subject,reply_body,replied_at,"
                            f"message_id,source_message_id,category,category_source,status,is_test")
        for q in (queued if isinstance(queued, list) else []):
            if not isinstance(q, dict) or q.get("is_test"):
                continue
            if not _is_uncategorised_value(q.get("category")) or q.get("category_source"):
                continue
            mid = str(q.get("source_message_id") or q.get("message_id") or "")
            cid = q.get("smartlead_campaign_id")
            if not mid or not cid:
                continue
            rows = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&smartlead_campaign_id=eq.{cid}"
                              f"&smartlead_message_id=eq.{quote(mid, safe='')}&select=category&limit=1")
            cat = (rows[0] or {}).get("category") if isinstance(rows, list) and rows else None
            if _is_uncategorised_value(cat):
                continue
            if cat in CORE_FOUR:
                _convert_uncat_row(q, cat, source="auto", settings=settings)
            else:
                _apply_patch(q, {"category": cat, "category_source": "auto", "status": "dismissed",
                                 "decision_reason": f"Auto-resolved: the categoriser later labelled "
                                                    f"this '{cat}' - removed from the Setter."})
            summary["auto_resolved"] += 1
    except Exception as e:  # noqa: BLE001 - auto-resolve must never break the poll
        summary["errors"] += 1
        print(f"[setter] uncategorised auto-resolve failed: {e}", file=sys.stderr)
    # ── pass 2: intake stragglers ──
    try:
        seen_ids, candidates = set(), []
        for filt in ("is.null", "eq.", "eq." + quote(UNCATEGORISED_LEGACY, safe="")):
            got = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&category={filt}"
                             f"&replied_at=gte.{quote(since_iso, safe='')}&order=replied_at.asc&limit=100"
                             f"&select=id,smartlead_campaign_id,email,replied_at,category,"
                             f"reply_subject,reply_body,smartlead_message_id")
            for r in (got if isinstance(got, list) else []):
                if not isinstance(r, dict):
                    continue
                # Not every caller-seeded row carries the replies PK - fall
                # back to the reply's natural identity so the three filter
                # pulls above never collapse distinct replies together.
                key = r.get("id") or (r.get("smartlead_campaign_id"),
                                      str(r.get("smartlead_message_id") or ""))
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                candidates.append(r)
        taken = 0
        for r in candidates:
            if taken >= UNCAT_PER_TICK:
                break
            cid = r.get("smartlead_campaign_id")
            email = (r.get("email") or "").strip().lower()
            mid = str(r.get("smartlead_message_id") or r.get("id") or "")
            if not cid or not email or not mid:
                continue
            if not _is_uncategorised_value(r.get("category")):
                continue  # belt-and-braces: the three filters above already scope this
            # Grace window: fresh replies are usually mid-categorisation, not
            # stragglers - leave anything younger than the grace to a later tick.
            try:
                if _parse_iso(r.get("replied_at")) > now - _dt.timedelta(hours=UNCAT_GRACE_HOURS):
                    continue
            except (ValueError, TypeError):
                pass  # unparsable timestamp: intake rather than lose the reply
            agent = _agent_for_campaign(cid, require_enabled=True, agents=agents)
            if agent:
                # Same backlog gate as the positive sweep: only replies received
                # AFTER the campaign was assigned to its agent (parent fallback
                # for subsequence campaigns, same as run_poll).
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
            reply = {
                "workspace": WORKSPACE, "campaign_id": cid, "email": email,
                "first_name": r.get("first_name"), "last_name": r.get("last_name"),
                "company_domain": r.get("company_domain"),
                "subject": r.get("reply_subject") or "", "body": r.get("reply_body") or "",
                "replied_at": r.get("replied_at"), "message_id": mid, "is_test": False,
            }
            taken += 1
            try:
                _intake_uncategorised(reply, agent)
                summary["uncategorised"] += 1
            except Exception as e:  # noqa: BLE001 - one bad reply must never stop the sweep
                summary["errors"] += 1
                print(f"[setter] uncategorised intake error for {email}/{cid}: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - the straggler sweep must never break the poll
        summary["errors"] += 1
        print(f"[setter] uncategorised sweep failed: {e}", file=sys.stderr)


# Queue rows already stamped with the archive label before the intake-side
# resolution shipped (2026-08-17) still display 'positive-re-reply' in the
# Lead-category pill. Ids that could NOT resolve (no prior real-category row
# in the archive - early rows predate the archive backfill) are memoised
# in-process so a permanently unresolvable row costs one probe per boot,
# not two GETs per tick forever.
_RE_REPLY_SWEEP_CAP = 40
_RE_REPLY_UNRESOLVED: set = set()


def _sweep_re_reply_labels(summary: dict) -> None:
    """Re-stamps legacy queue rows whose category is the internal archive
    label 'positive-re-reply' with the lead's real category - the same
    resolution intake now applies (see _resolve_re_reply_category). Runs
    every poll tick; once the backlog is converged it costs one empty GET.
    Never raises."""
    if not _SB:
        return
    try:
        rows = _SB("GET", f"{QUEUE_TABLE}?category=eq.{_RE_REPLY_LABEL}"
                          f"&order=id.desc&limit={_RE_REPLY_SWEEP_CAP}"
                          f"&select=id,workspace,smartlead_campaign_id,lead_email,replied_at,category")
        for q in (rows if isinstance(rows, list) else []):
            if not isinstance(q, dict) or q.get("id") in _RE_REPLY_UNRESOLVED:
                continue
            # Belt-and-braces: the fake test harness (and any future filter
            # loosening) may hand back rows the category filter should have
            # excluded - never re-stamp a row that no longer carries the label.
            if str(q.get("category") or "").strip().lower() != _RE_REPLY_LABEL:
                continue
            cat = _resolve_re_reply_category(q.get("workspace") or WORKSPACE,
                                             q.get("smartlead_campaign_id"),
                                             (q.get("lead_email") or "").strip().lower(),
                                             q.get("replied_at"))
            if cat:
                _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{q['id']}", {"category": cat},
                    prefer="return=minimal")
                summary["re_reply_relabelled"] = summary.get("re_reply_relabelled", 0) + 1
            else:
                _RE_REPLY_UNRESOLVED.add(q.get("id"))
    except Exception as e:  # noqa: BLE001 - a relabel sweep must never break the poll
        summary["errors"] += 1
        print(f"[setter] re-reply relabel sweep failed: {e}", file=sys.stderr)


# A claim only means "in flight" for the seconds a pipeline run takes; past
# this it means the run died. Generous enough that a live tick is never reaped
# out from under itself.
_REDRIVE_AFTER_SECS = 15 * 60
_REDRIVE_CAP = 10                  # per tick, so a backlog can't run away


def _redrive_stranded_claims(agents: list, settings: dict, summary: dict) -> None:
    """Rescues queue rows stranded in status "new".

    Owner report 2026-07-28 (jennifer@globalsponsorhub.com, queue row 1218):
    the reply was in setter_queue but appeared in NO pill in the setter. Root
    cause is the intake claim in _process_reply_inner: it inserts the row at
    status "new" BEFORE the slow work (hydrate -> classify -> draft), on
    purpose, so the webhook and the poll can't process the same reply twice.
    If the worker then dies between the claim and the finish - Render restart,
    tick killed mid-flight, OOM - nothing patches the row. The evidence for
    1218: the 14:35 poll tick logged its start and NEVER logged setter_poll_done,
    and the row's updated_at still equals its created_at.

    A row left at "new" is invisible twice over:
      * FILTER_PILLS in setter.html has needs_review / sent / auto_sent /
        dismissed / All - "new" only ever shows under All, with no draft;
      * run_poll's `if _existing_row(...): continue` sees the husk as already
        queued, so the reply is never retried - and after 48h it drops out of
        the poll window entirely. 17 rows had accumulated this way.

    So the reaper re-drives them THROUGH the real pipeline (via _redrive_id,
    which adopts the existing row instead of claiming a new one), and if that
    still doesn't move the status, force-flips it to needs_review so it can
    never be invisible again. Never raises.

    SEND-SAFETY GATE (non-negotiable, same rule as _self_heal_campaigns): this
    runs unattended on a cron tick over rows that may be days old, so every
    pipeline call uses a draft_only snapshot. A reaper must never auto-send.
    """
    if not _SB:
        return
    # Sibling reaper for stranded SEND claims (double-send fix 2026-08-01): a
    # row flipped to 'sending' whose worker died with the process would sit in
    # no pill forever. After SENDING_STALE_MIN it returns to needs_review with
    # an honest error — the reviewer must verify the thread in Smartlead
    # before retrying, because "claim written, worker dead" cannot tell us
    # whether the mail left.
    try:
        s_cut = (_dt.datetime.now(_dt.timezone.utc)
                 - _dt.timedelta(minutes=SENDING_STALE_MIN)).isoformat()
        s_now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        # First-send claims (no sent_at yet) return to needs_review…
        _SB("PATCH", f"{QUEUE_TABLE}?status=eq.sending&sent_at=is.null&is_test=not.is.true"
                     f"&updated_at=lt.{quote(s_cut, safe='')}",
            {"status": "needs_review", "updated_at": s_now,
             "error": "A send was interrupted mid-flight (server restart). Check the thread "
                      "in Smartlead before re-sending — the email may already have gone out."})
        # …but a claim taken from an already-SENT row (an interrupted
        # follow-up) must restore to sent, never needs_review — dropping it
        # there re-armed Approve on a thread whose first reply already went
        # out (panel finding 2026-08-01).
        _SB("PATCH", f"{QUEUE_TABLE}?status=eq.sending&sent_at=not.is.null&is_test=not.is.true"
                     f"&updated_at=lt.{quote(s_cut, safe='')}",
            {"status": "sent", "updated_at": s_now,
             "error": "A follow-up send was interrupted (server restart). Check the thread "
                      "in Smartlead before re-sending the follow-up."})
    except Exception as e:  # noqa: BLE001 - reaping is best-effort
        print(f"[setter] redrive: sending-claim sweep failed: {e}", file=sys.stderr)
    cutoff = (_dt.datetime.now(_dt.timezone.utc)
              - _dt.timedelta(seconds=_REDRIVE_AFTER_SECS)).isoformat()
    try:
        rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=eq.new"
                          f"&updated_at=lt.{quote(cutoff, safe='')}"
                          f"&order=created_at.desc&limit={_REDRIVE_CAP}&select=*")
    except Exception as e:  # noqa: BLE001
        summary["errors"] += 1
        print(f"[setter] redrive: stranded GET failed: {e}", file=sys.stderr)
        return
    if not isinstance(rows, list) or not rows:
        return
    for row in rows:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        qid = row["id"]
        cid = row.get("smartlead_campaign_id")
        email = (row.get("lead_email") or "").strip().lower()
        mid = str(row.get("message_id") or row.get("source_message_id") or "")
        try:
            reply = {
                "workspace": row.get("workspace") or WORKSPACE, "campaign_id": cid,
                "email": email, "first_name": row.get("lead_first_name"),
                "last_name": row.get("lead_last_name"), "company_domain": row.get("company_domain"),
                "subject": row.get("reply_subject"), "body": row.get("reply_body") or "",
                "replied_at": row.get("replied_at"), "message_id": mid,
                "category": row.get("category"), "is_test": False,
                "_redrive_id": qid,
            }
            agent = _agent_for_campaign(cid, require_enabled=True, agents=agents)
            if agent:
                out = process_reply(reply, {**agent, "mode": "draft_only"}, settings)
            else:
                # No brain for this campaign - nothing to classify or draft
                # with. _intake_agentless inserts rather than adopts, so let
                # the force-flip below make the husk visible for manual review
                # instead (same end state, minus the duplicate row).
                out = None
            status = (out or {}).get("status")
            if status in (None, "new"):
                _apply_patch(row, {
                    "status": "needs_review", "decision": "review",
                    "decision_reason": ("Held for review: this reply was picked up but its "
                                        "processing never finished, so it had no draft."),
                    "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                })
                status = "needs_review"
            summary["redriven"] = summary.get("redriven", 0) + 1
            if status == "needs_review":
                summary["needs_review"] += 1
            elif status == "no_action":
                summary["no_action"] += 1
            print(f"[setter] redrive: row {qid} ({email}/{cid}) -> {status}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - one bad husk must never stop the rest
            summary["errors"] += 1
            print(f"[setter] redrive: row {qid} failed: {e}", file=sys.stderr)


def _poll_monitor_workspaces(since: str, summary: dict) -> None:
    """MONITOR intake for every non-navreo enabled workspace (federation gate).

    Ships the OTHER half of "why only three clients show": even with the read
    federated, a client only APPEARS once its replies are in setter_queue, and
    the navreo sweep above pulls navreo only. This walks each enabled client
    workspace and intakes its recent replies as review-only rows.

    Two deliberate departures from the navreo sweep:
      • POSITIVES + UNCATEGORISED only — `_monitor_should_surface` gates
        intake so clear non-positives (Out Of Office, Not Interested, Wrong
        Person, Do Not Contact, bounces) never reach Needs review (Bjion
        2026-08-04, once federation was confirmed live). The gate was
        deliberately open before that, to prove client intake worked at all.
      • ALWAYS agentless — never look up / run an agent, so nothing is ever
        drafted, classified or auto-sent for a client. Pure surface-for-review.
    Rows land is_test=False (so they RENDER and hydrate; is_test rows are
    hidden by the UI), and CANNOT send: _is_monitor_ws forces every send path
    dry and the send action refuses them. Best-effort; never raises. Poll/cron
    path only — never a web request (512MB box)."""
    if not SETTER_MONITOR_ALL_WS or not _SB:
        return
    client_ids = [w for w in _enabled_workspace_ids() if w != "navreo"]
    if not client_ids:
        return
    processed = 0
    for ws in client_ids:
        if processed >= 15:   # shared cap with the navreo sweep's blast radius
            break
        try:
            replies = _SB("GET", f"replies?workspace=eq.{ws}"
                                 f"&replied_at=gte.{quote(since, safe='')}"
                                 f"&order=replied_at.desc&limit=50"
                                 f"&select=id,smartlead_campaign_id,email,replied_at,category,"
                                 f"reply_subject,reply_body,smartlead_message_id")
        except Exception as e:  # noqa: BLE001
            summary["errors"] += 1
            print(f"[setter] monitor poll: replies GET failed for {ws}: {e}", file=sys.stderr)
            continue
        if not isinstance(replies, list):
            summary["errors"] += 1
            continue
        for r in sorted([x for x in replies if isinstance(x, dict)],
                        key=lambda x: x.get("replied_at") or ""):
            if processed >= 15:
                break
            cid = r.get("smartlead_campaign_id")
            email = (r.get("email") or "").strip().lower()
            mid = str(r.get("smartlead_message_id") or r.get("id") or "")
            if not cid or not email or not mid:
                continue
            # Only surface positives + still-uncategorised; skip clear
            # non-positives so they never land in Needs review. Skipped rows
            # don't count against the 15-per-tick blast radius.
            if not _monitor_should_surface(r.get("category")):
                summary["skipped_nonpositive"] = summary.get("skipped_nonpositive", 0) + 1
                continue
            reply = {
                "workspace": ws, "campaign_id": cid, "email": email,
                "subject": r.get("reply_subject") or "",
                "body": r.get("reply_body") or "",
                "replied_at": r.get("replied_at"), "message_id": mid,
                "category": r.get("category"), "is_test": False,
            }
            processed += 1
            summary["checked"] += 1
            try:
                row = _intake_agentless(reply)   # dedup + hydrate + needs_review row
                summary["agentless"] += 1
                if (row or {}).get("status") == "needs_review":
                    summary["needs_review"] += 1
            except Exception as e:  # noqa: BLE001 - one bad reply never stops the sweep
                summary["errors"] += 1
                print(f"[setter] monitor poll intake error {ws} {email}/{cid}: {e}", file=sys.stderr)


_LAST_SWEEP_DONE = {"t": 0.0}  # in-process stamp of the last COMPLETED sweep
_SWEEP_FRESH_S = 120           # page-load kicks inside this window are duplicates


def run_poll() -> dict:
    """Sweeps recent core-four `replies` rows across EVERY campaign in the
    workspace (owner ruling 2026-07-14: a positive must reach the queue even
    on a campaign with no agent assigned yet), skips anything already
    queued, and runs process_reply (agented) or the agentless intake
    (unassigned) on up to 15 per tick. Never raises.

    Throttle: every setter.html open POSTs /api/setter/poll, and the pg_cron
    tick already sweeps every 5 min — a completed sweep <120s ago makes this
    call pure duplicate Smartlead load (~2 calls per processed reply). The
    stamp is in-process only (a skip must never advance any freshness stamp,
    or steady page traffic would starve real sweeps); a deploy resets it, so
    the first post-boot call always sweeps."""
    summary = {"checked": 0, "queued": 0, "auto_sent": 0, "needs_review": 0, "no_action": 0,
               "errors": 0, "agentless": 0, "uncategorised": 0, "auto_resolved": 0, "redriven": 0}
    try:
        if not _SB:
            return summary
        # RENDER-gated: local dev and the test harness drive run_poll directly
        # and must never be throttled (RENDER is the codebase's prod marker).
        age = _time.time() - _LAST_SWEEP_DONE["t"]
        if os.environ.get("RENDER") and age < _SWEEP_FRESH_S:
            summary["skipped_fresh_s"] = round(age)
            return summary
        agents = _load_agents()
        settings = _load_settings()
        # Rescue anything a previous tick claimed but never finished, BEFORE
        # the fresh sweep - a stranded claim is invisible in the setter and
        # the sweep's already-queued check will never retry it on its own.
        _redrive_stranded_claims(agents, settings, summary)
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
        # NEWEST first (owner report 2026-07-25: "when we get an email it pushes
        # it in Slack but ... it's not there" in the setter). The page is capped
        # at 200 and the already-queued check runs AFTER the fetch, so ordering
        # ascending meant a busy 48h window filled all 200 rows with replies
        # that were already in the queue and the brand-new one - the only one
        # that mattered - never made the page at all. Fetch newest-first, then
        # process oldest-first below so intake order is unchanged.
        replies = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&category={CORE_FOUR_CATEGORY_FILTER}"
                             f"&replied_at=gte.{quote(since, safe='')}&order=replied_at.desc&limit=200"
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
        # Fetched newest-first (see above) so nothing recent is starved; walk
        # them oldest-first so a thread's replies still intake in order.
        replies = sorted([r for r in replies if isinstance(r, dict)],
                         key=lambda r: r.get("replied_at") or "")
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
        # Stragglers the categoriser never labelled (ship 2026-07-20): resolve
        # queued ones whose category has since arrived, then intake new ones
        # past the grace window. Runs AFTER the positive sweep so the 15-cap
        # above is always spent on positives first.
        _sweep_uncategorised(agents, settings, since, summary)
        # Legacy 'positive-re-reply' labels: re-stamp queue rows written
        # before intake started resolving the archive label to the lead's
        # real category (owner ask 2026-08-17). Converges to one empty GET.
        _sweep_re_reply_labels(summary)
        # Federation MONITOR sweep: pull every non-navreo enabled workspace's
        # recent replies into the queue as review-only rows (see the function
        # docstring). Last, so the navreo positive sweep always spends its cap
        # first. Never sends — _is_monitor_ws forces these dry everywhere.
        _poll_monitor_workspaces(since, summary)
        _LAST_SWEEP_DONE["t"] = _time.time()  # completed sweeps only — a crash must retry next call
    except Exception as e:  # noqa: BLE001 - run_poll itself must never raise
        summary["errors"] += 1
        print(f"[setter] run_poll crashed: {e}", file=sys.stderr)
    # New rows changed the queue - drop every read cache and start a rewarm
    # so the post-poll reload (the UI's delayed loadQueue) reads fresh counts
    # and rows (perf pass 2026-07-16). A no-change sweep keeps caches warm.
    if summary.get("queued") or summary.get("needs_review") or summary.get("auto_sent") \
            or summary.get("no_action") or summary.get("uncategorised") or summary.get("auto_resolved") \
            or summary.get("redriven"):
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


# ── uncategorised: recategorise dropdown (ship 2026-07-20) ──────────────────

_CATEGORY_CACHE = {"at": 0.0, "val": None}
_CATEGORY_TTL = 3600.0  # Smartlead's category list changes ~never; 1h is plenty


def _fetch_lead_categories() -> list:
    """Live Smartlead master category list -> [{"id": int, "name": str}].
    The dropdown must always mirror Smartlead (ruling 2026-07-20: never
    hardcode the label list a second time)."""
    got = _sl_get("/leads/fetch-categories")
    if isinstance(got, dict):
        got = got.get("data") or got.get("categories") or []
    out = []
    for c in (got if isinstance(got, list) else []):
        if isinstance(c, dict) and c.get("id") is not None and c.get("name"):
            out.append({"id": c.get("id"), "name": str(c.get("name"))})
    return out


def route_categories_get(_params):
    """GET /api/setter/categories - the recategorise dropdown's options,
    served from a 1h cache; stale beats broken when Smartlead hiccups."""
    try:
        now = _time.time()
        if _CATEGORY_CACHE["val"] is not None and (now - _CATEGORY_CACHE["at"]) < _CATEGORY_TTL:
            return 200, {"categories": _CATEGORY_CACHE["val"], "cached": True}
        try:
            cats = _fetch_lead_categories()
        except Exception as e:  # noqa: BLE001 - stale beats broken
            if _CATEGORY_CACHE["val"] is not None:
                return 200, {"categories": _CATEGORY_CACHE["val"], "cached": True,
                             "detail": f"Serving cached list - Smartlead fetch failed: {str(e)[:120]}"}
            return 502, {"error": f"Couldn't fetch Smartlead categories: {str(e)[:200]}"}
        if cats:
            _CATEGORY_CACHE["val"] = cats
            _CATEGORY_CACHE["at"] = now
            return 200, {"categories": cats, "cached": False}
        if _CATEGORY_CACHE["val"] is not None:
            return 200, {"categories": _CATEGORY_CACHE["val"], "cached": True}
        return 502, {"error": "Smartlead returned no categories."}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _sl_lead_id_by_email(email: str, campaign_id=None):
    """The categoriser's own lookup (GET /leads/?email=) - returns the global
    Smartlead lead id, or None. campaign_id routes the lookup to the owning
    workspace's key (the path alone carries no campaign for the resolver)."""
    try:
        got = _sl_get("/leads/", {"email": email}, campaign_id=campaign_id)
        if isinstance(got, dict) and got.get("id") is not None:
            return got.get("id")
    except Exception:  # noqa: BLE001
        pass
    return None


def route_queue_recategorise(payload):
    """POST /api/setter/queue/recategorise {id, category_id, category_name} -
    the human verdict on a reply's category, from either the uncategorised
    triage banner OR the lead sidebar's "update lead category" control (which
    can retouch an ALREADY-categorised row, e.g. to mark someone unqualified).
    Order is load-bearing: Smartlead is written FIRST (it is the system of
    record for categories); only on success do `replies` and the queue row
    move. A CORE_FOUR choice keeps the lead in the normal flow - converting
    (re-running intake, drafting and all) when there is nothing to preserve
    (the row was uncategorised or had been filed/dismissed), or just
    relabelling an already-live row in place so a nuance change never nukes an
    existing draft. Anything else files the category and clears the row from
    the Setter. Manual verdicts are authoritative (category_source="manual") -
    nothing automated may overwrite them."""
    try:
        payload = payload or {}
        qid = payload.get("id")
        cat_id = payload.get("category_id")
        cat_name = str(payload.get("category_name") or "").strip()
        if not qid or cat_id is None or not cat_name:
            return 400, {"error": "id, category_id and category_name are required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{quote(str(qid), safe='')}"
                          f"&{_list_ws_filter()}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        # A SENT thread can now be re-labelled (owner ask 2026-07-25). It is
        # strictly a LABEL change - Smartlead + `replies` + the row's category,
        # never the status, the draft or anything on the send path. The point
        # is the follow-up reminder: marking a sent lead Not Interested has to
        # take them OUT of "Sent without follow-up", which needs the label to
        # be changeable on exactly the rows that tray is made of.
        sent_row = row.get("status") in ("sent", "auto_sent")
        # An already-categorised row is fine to change now (the sidebar's
        # "update lead category" / "mark unqualified"): was_uncat only steers
        # the disposition below, it is no longer a gate.
        was_uncat = _is_uncategorised_value(row.get("category"))
        row_ws = row.get("workspace") or WORKSPACE
        if not row.get("is_test") and not _is_monitor_ws(row_ws):
            lead_id = row.get("smartlead_lead_id") or _sl_lead_id_by_email(
                row.get("lead_email") or "", campaign_id=row.get("smartlead_campaign_id"))
            if not lead_id:
                return 502, {"error": "Couldn't resolve this lead in Smartlead, so the category "
                                      "wasn't written anywhere. Nothing was changed."}
            try:
                _sl_post(f"/campaigns/{row.get('smartlead_campaign_id')}/leads/{lead_id}/category",
                         {"category_id": int(cat_id)})
            except Exception as e:  # noqa: BLE001 - Smartlead write failed: change nothing locally
                return 502, {"error": f"Smartlead rejected the category write: {str(e)[:200]}. "
                                      f"Nothing was changed."}
        # Monitor-only workspaces skip the Smartlead write entirely (their
        # category ids belong to a different account, and monitor-only means we
        # never write to a client's Smartlead) - the label still lands in
        # `replies` + the queue row below, which is what every tool surface reads.
        if not row.get("is_test"):
            mid = str(row.get("source_message_id") or row.get("message_id") or "")
            if mid:
                try:
                    _SB("PATCH", f"replies?workspace=eq.{quote(str(row_ws), safe='')}"
                                 f"&smartlead_campaign_id=eq.{row.get('smartlead_campaign_id')}"
                                 f"&smartlead_message_id=eq.{quote(mid, safe='')}",
                        {"category": cat_name})
                except Exception:  # noqa: BLE001 - Smartlead holds the truth; sync catches replies up
                    pass
        try:
            if _LOG:
                _LOG("/api/setter/queue/recategorise",
                     {"id": qid, "category": cat_name, "category_id": cat_id},
                     action="recategorise", entity="setter_queue", entity_id=qid)
        except Exception:  # noqa: BLE001 - logging must never break the route
            pass
        # A monitor-workspace label lands only in the tool (replies + queue
        # row) — say so honestly instead of implying the client's Smartlead
        # changed (panel fix 2026-08-01). The next external categoriser run
        # for that workspace may overwrite the replies label; the queue row's
        # manual verdict stays authoritative tool-side.
        monitor_note = ("Labelled in the tool only — monitor workspaces are never "
                        "written to the client's Smartlead.") if _is_monitor_ws(row_ws) else None
        # A failed queue-row write after the Smartlead/replies writes landed
        # must NOT read as success — the reload would show the old label
        # under a success hint, which is the do-it-twice trap.
        # Wording is workspace-honest: monitor/test rows never touched
        # Smartlead, so the message must not claim they did.
        wrote_sl = not row.get("is_test") and not _is_monitor_ws(row_ws)
        _persist_fail = (502, {"error": (("The category was written to Smartlead but the queue row "
                                          "didn't update") if wrote_sl else
                                         "The category change didn't save") +
                                        " — reload and check before retrying."})
        if sent_row:
            # Label-only path. A non-positive label also resolves the follow-up
            # reminder ('dismissed'), which is the whole reason this branch
            # exists; a positive label leaves the reminder exactly as it was.
            patch = {"category": cat_name, "category_source": "manual"}
            if not _followup_category_ok(cat_name):
                patch["subsequence_decision"] = "dismissed"
            if not _apply_patch(row, patch):
                return _persist_fail
            return 200, {"ok": True, "action": "relabelled_sent", "category": cat_name,
                         "removed_from_followup": "subsequence_decision" in patch,
                         **({"detail": monitor_note} if monitor_note else {})}
        if cat_name in CORE_FOUR:
            # Convert (re-run intake so it gets a draft) only when there is
            # nothing to preserve - the row was uncategorised, or it had been
            # filed/dismissed and is being rescued. An already-live categorised
            # row just gets relabelled in place, keeping its draft and status.
            if was_uncat or row.get("status") == "dismissed":
                new_row = _convert_uncat_row(row, cat_name, source="manual")
                if not (new_row or {}).get("id"):
                    # Adopt-in-place means the ORIGINAL row still exists on
                    # any failure — nothing is lost, the retry is real.
                    return 502, {"error": "The category was written, but re-running this reply "
                                          "through the pipeline failed — the reply is still in "
                                          "the queue; try Apply again."}
                return 200, {"ok": True, "action": "converted", "category": cat_name,
                             "new_id": (new_row or {}).get("id"), "status": (new_row or {}).get("status"),
                             **({"detail": monitor_note} if monitor_note else {})}
            if not _apply_patch(row, {"category": cat_name, "category_source": "manual"}):
                return _persist_fail
            return 200, {"ok": True, "action": "relabelled", "category": cat_name,
                         **({"detail": monitor_note} if monitor_note else {})}
        if not _apply_patch(row, {"category": cat_name, "category_source": "manual", "status": "dismissed",
                                  "decision": "review",
                                  "decision_reason": f"Recategorised manually as '{cat_name}' - removed "
                                                     f"from the Setter."}):
            return _persist_fail
        return 200, {"ok": True, "action": "discarded", "category": cat_name,
                     **({"detail": monitor_note} if monitor_note else {})}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


# ── Agents+settings read cache (perf pass 2026-07-28) ─────────────────────
# route_agents_get gates the setter page's first paint, and _load_agents()
# pulls EVERY agent doc (multi-KB instruction blobs, one ~15KB) on every load —
# measured 1.6-2.2s live. Agents and settings change only on an explicit save,
# so cache the built payload with the same SWR shape as _queue_rows_cached:
#   fresh  -> serve cached;
#   stale  -> serve cached NOW, refresh once in the background (SWR);
#   absent -> compute synchronously, single-flight so concurrent GETs join it.
# Every write path (_save_agent, _save_settings, route_agents_delete) calls
# _bust_agents_cache(), so a read right after a save is never zombie-stale.
_AGENTS_TTL = 30.0
_AGENTS_CACHE = {"at": 0.0, "val": None}
_AGENTS_LOCK = threading.Lock()


def _build_agents_payload() -> dict:
    s = _load_settings()
    return {"agents": _load_agents(), "settings": {
        "calendly_connected": bool(s.get("calendly_token")),
        "work_start": s.get("work_start", 9),
        "work_end": s.get("work_end", 17),
        "autopilot_enabled": bool(s.get("autopilot_enabled")),
        "webhooks": s.get("webhooks") or {},
    }}


def _kick_agents_refresh():
    def run():
        if not _AGENTS_LOCK.acquire(blocking=False):
            return   # a compute/refresh is already in flight
        try:
            _AGENTS_CACHE["val"] = _build_agents_payload()
            _AGENTS_CACHE["at"] = _time.time()
        except Exception:  # noqa: BLE001 - background refresh must never raise
            pass
        finally:
            _AGENTS_LOCK.release()
    threading.Thread(target=run, daemon=True).start()


def _agents_payload_cached() -> dict:
    if _AGENTS_CACHE["val"] is not None:
        if (_time.time() - _AGENTS_CACHE["at"]) < _AGENTS_TTL:
            return _AGENTS_CACHE["val"]
        _kick_agents_refresh()          # stale-while-revalidate
        return _AGENTS_CACHE["val"]
    with _AGENTS_LOCK:
        if _AGENTS_CACHE["val"] is not None:   # a waiter's compute may have landed
            return _AGENTS_CACHE["val"]
        _AGENTS_CACHE["val"] = _build_agents_payload()
        _AGENTS_CACHE["at"] = _time.time()
        return _AGENTS_CACHE["val"]


def _bust_agents_cache():
    _AGENTS_CACHE["at"] = 0.0
    _AGENTS_CACHE["val"] = None


def route_agents_get(_params):
    try:
        return 200, _agents_payload_cached()
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
        # One campaign, one agent (owner bug 2026-07-28: campaign 3642625 sat
        # in BOTH the Amplifyy and Navreo agents' lists, and whichever agent
        # the loader listed first drafted its replies - a Navreo demo pitch
        # landed on an Amplifyy thread). Saving an agent TAKES ownership of
        # its campaigns: the same ids are stripped from every other agent.
        # The human just made this assignment on purpose, so the new claim
        # wins; the sweep is a repair and must never block the save.
        try:
            mine = {str(c) for c in (saved.get("campaign_ids") or [])}
            if mine:
                for other in _load_agents():
                    if str(other.get("id")) == str(saved.get("id")):
                        continue
                    theirs = [str(c) for c in (other.get("campaign_ids") or [])]
                    kept_ids = [c for c in theirs if c not in mine]
                    if len(kept_ids) != len(theirs):
                        _save_agent({"id": other["id"], "name": other.get("name"),
                                     "campaign_ids": kept_ids})
                        print(f"[setter] agent {saved.get('id')} took campaign(s) "
                              f"{sorted(mine & set(theirs))} from {other.get('id')}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
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
            _bust_agents_cache()
        return 200, {"ok": True}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_agents_correction(payload):
    """Persistent learning layer: one correction the owner (or, since Review
    mode, a share-link trainer teaching from a rechecked case) gives while
    reviewing this agent's calls, outside any per-case feedback log.
    scope="remember" (owner ruling 2026-07-14) merges the
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
            resp = {
                "ok": True, "agent_id": agent_id, "scope": scope, "how": how,
                "memory_count": len(saved.get("memory") or []),
                "feedback_log_count": len(saved.get("feedback_log") or []),
                "instruction_edits_count": len(saved.get("instruction_edits") or []),
            }
            # Verify-before-done: the merge's conflict sweep records whether
            # older passages still fight this lesson. Surface that verdict so
            # the caller (chat, the Teach modal) can tell the owner "landed
            # clean" vs "these older lines still contradict it" instead of
            # reporting every save as complete.
            last_edit = (saved.get("instruction_edits") or [{}])[-1]
            if "conflicts_found" in last_edit:
                resp["conflicts_found"] = last_edit.get("conflicts_found")
                resp["conflicts_remaining"] = last_edit.get("conflicts_remaining") or []
                resp["landed_clean"] = not resp["conflicts_remaining"]
            return 200, resp
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
    /campaigns/ - never a write.

    Returns a list of {"id","name","status"} on a SUCCESSFUL lookup (possibly
    empty when the campaign genuinely has no subsequences), or **None** when the
    Smartlead fetch itself failed - timeout, rate-limit, a non-list body, no key,
    or any exception. The None sentinel is load-bearing (root-cause fix
    2026-08-10): the old code returned [] for BOTH "no subsequences" AND
    "couldn't check", so a slow or rate-limited /campaigns/ read (navreo alone is
    ~997 campaigns / ~860KB under a 15s timeout) silently became a false "no
    subsequence" 502. Callers MUST treat None as retryable, never as "none".

    `campaign_id=parent_campaign_id` routes the listing to the OWNING workspace's
    key - without it a client-workspace campaign (ThunderBird etc.) is read with
    the navreo key and its subsequences are invisible, an always-"no subsequence"
    lie. The push path (_push_to_subsequence / _sl_campaign_lead_map_id) already
    passes campaign_id; detection was the odd one out."""
    if not parent_campaign_id:
        return []
    try:
        resp = _sl_get("/campaigns/", campaign_id=parent_campaign_id)
    except Exception:  # noqa: BLE001 - fetch failed; do NOT claim "no subsequence"
        return None
    if not isinstance(resp, list):
        return None
    out = []
    for r in resp:
        if not isinstance(r, dict):
            continue
        if r.get("parent_campaign_id") and str(r.get("parent_campaign_id")) == str(parent_campaign_id):
            out.append({"id": r.get("id"), "name": r.get("name"), "status": r.get("status")})
    return out


def _resolve_subsequence_id(campaign_id, sub_sequence_id_override):
    """Picks the subsequence to push a lead into. An explicit override always
    wins (the caller already knows which one, e.g. a picker in the UI for
    campaigns with several). Otherwise looks up campaign_id's subsequences via
    the shared workspace-aware cache: fetch failed -> retryable 503 (NEVER a
    false "none"); exactly one -> use it; none -> clear 422; more than one ->
    400 asking the caller to disambiguate (with the list attached so a picker
    can be built). Uses _subsequences_for_campaign_cached (not a raw
    _sl_find_subsequences) so a push reuses the picker's 10-min cache instead of
    re-pulling the whole ~860KB /campaigns/ listing on every click.
    Returns (sub_sequence_id, error_response) where error_response is None on
    success or a ready-to-return (status, body) tuple otherwise."""
    if sub_sequence_id_override:
        return sub_sequence_id_override, None
    subs = _subsequences_for_campaign_cached(campaign_id)
    if subs is None:
        # Fetch failed (timeout / rate-limit / non-list). NOT "no subsequence":
        # a retryable 503 so the UI says "try again" instead of the misleading
        # "this campaign has none". Never 502 - that reads as a gateway crash,
        # indistinguishable from a Render OOM, and is what made this so confusing.
        return None, (503, {"error": "Couldn't check this campaign's subsequences in Smartlead just now - please try again.", "retryable": True})
    if len(subs) == 1:
        return subs[0]["id"], None
    if len(subs) > 1:
        return None, (400, {"error": "This campaign has multiple subsequences - pick one.", "subsequences": subs})
    return None, (422, {"error": "No subsequence is configured for this campaign in Smartlead."})


# ── Send-gate: subsequence picker + follow-up decision (2026-07-17) ────────
# The queue-list caching pattern (_ROWS_CACHE et al) has short TTLs because
# queue rows churn constantly; a campaign's set of Smartlead subsequences
# almost never changes, so this gets its own longer-lived cache instead of
# riding the queue-row cache's bust cycle.
_SUBSEQ_LIST_TTL = 600
_SUBSEQ_LIST_CACHE = {}   # str(campaign_id) -> {"at": ts, "list": [{"id","name"}]}


def _subsequences_for_campaign_cached(campaign_id):
    """Cached {id,name} list of campaign_id's subsequences, or **None** when the
    Smartlead lookup failed (the sentinel from _sl_find_subsequences). A failure
    is NEVER cached - it would freeze a false "no subsequence" for 10 minutes -
    so the next call retries live. Only a genuinely successful listing (even an
    empty one) is cached."""
    key = str(campaign_id)
    ent = _SUBSEQ_LIST_CACHE.get(key)
    if ent and (_time.time() - ent["at"]) < _SUBSEQ_LIST_TTL:
        return ent["list"]
    subs = _sl_find_subsequences(campaign_id)
    if subs is None:
        return None  # fetch failed - do NOT cache, let the caller retry
    out = [{"id": s.get("id"), "name": s.get("name")} for s in subs if s.get("id") is not None]
    _SUBSEQ_LIST_CACHE[key] = {"at": _time.time(), "list": out}
    return out


def route_subsequences_get(params):
    """GET /api/setter/subsequences?campaign_id=X - the send gate's chip
    list. Wraps _sl_find_subsequences with a 10-minute in-process cache per
    campaign_id so opening reply after reply in the same campaign doesn't
    cost a live Smartlead lookup each time. A failed lookup answers 503
    (retryable) - never an empty list, which would falsely read as "no
    subsequence"."""
    try:
        campaign_id = _qp(params, "campaign_id", "")
        if not campaign_id:
            return 400, {"error": "campaign_id is required"}
        subs = _subsequences_for_campaign_cached(campaign_id)
        if subs is None:
            return 503, {"error": "Couldn't check this campaign's subsequences in Smartlead just now - please try again.", "retryable": True}
        return 200, {"subsequences": subs}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _lead_name(row: dict) -> str:
    """Server-side mirror of setter.html's leadName(): first name if it's a
    real one, otherwise the email local-part, never a hollow "Hi there"."""
    fn = str(row.get("lead_first_name") or "").strip()
    if not fn or fn.lower() == "there":
        email = str(row.get("lead_email") or "")
        local = email.split("@", 1)[0] if "@" in email else email
        return local or email or "Unknown lead"
    parts = [fn, str(row.get("lead_last_name") or "").strip()]
    name = " ".join(p for p in parts if p)
    return name or str(row.get("lead_email") or "") or "Unknown lead"


# ── Tray reconciliation against Smartlead ground truth (2026-07-17) ────────
# Owner bug report: enrolments done directly in Smartlead's own UI never
# touch our DB, so rows the human already pushed showed as "Sent without
# follow-up" - false positives. A subsequence IS a Smartlead campaign
# (parent_campaign_id points at the parent - see _sl_find_subsequences), so
# "is this lead enrolled?" = "does this lead appear in any subsequence
# campaign's own leads listing?". The listing is fetched ONCE per subsequence
# campaign per _SUBSEQ_ENROLL_TTL (batched: one read covers every candidate
# lead of that campaign), which doubles as the negative-verdict cache -
# repeated tray loads inside the window cost zero Smartlead calls. Positive
# verdicts are patched onto the row permanently, so reconciliation is
# one-time per row, never a per-request Smartlead storm. Calls stay well
# under the 200/min limit: worst case is one GET /campaigns/ per distinct
# stale parent campaign plus a few pages per subsequence, per 10 minutes.
_SUBSEQ_ENROLL_TTL = 600
_SUBSEQ_ENROLL_CACHE = {}   # str(subseq_campaign_id) -> {"at": ts, "emails": set(lowercased)}


def _subseq_enrolled_emails(sub_campaign_id, max_pages: int = 10):
    """Lowercased emails of every lead enrolled in subsequence campaign
    `sub_campaign_id`, via GET /campaigns/{id}/leads (same read
    _sl_campaign_lead_map_id pages through), cached for _SUBSEQ_ENROLL_TTL.
    Returns None on ANY fetch problem - a malformed page (Smartlead's
    rate-limit error string mid-listing reads as a non-dict page, see
    reference_smartlead_pagination_ratelimit_truncation) or an exception -
    and never caches a failure, so the caller fails OPEN (row stays in the
    tray) and the next load retries."""
    key = str(sub_campaign_id)
    ent = _SUBSEQ_ENROLL_CACHE.get(key)
    if ent and (_time.time() - ent["at"]) < _SUBSEQ_ENROLL_TTL:
        return ent["emails"]
    emails = set()
    offset = 0
    try:
        for _ in range(max_pages):
            resp = _sl_get(f"/campaigns/{sub_campaign_id}/leads", {"offset": offset, "limit": 100})
            if not isinstance(resp, dict) or not isinstance(resp.get("data"), list):
                return None  # error / rate-limited page - fail open, cache nothing
            page = resp["data"]
            if not page:
                break
            for entry in page:
                lead = (entry or {}).get("lead") or {}
                em = str(lead.get("email") or "").strip().lower()
                if em:
                    emails.add(em)
            if len(page) < 100:
                break
            offset += 100
    except Exception:  # noqa: BLE001
        return None
    _SUBSEQ_ENROLL_CACHE[key] = {"at": _time.time(), "emails": emails}
    return emails


def _reconcile_unresolved_against_smartlead(candidates):
    """`candidates` = [(raw_row, out_dict)]. Returns the out_dicts that are
    STILL unresolved after checking Smartlead ground truth. A lead found in
    any subsequence of its campaign is stamped pushed+added on the row
    (permanently leaving the unresolved set) and dropped from the response.
    Every failure path keeps the row - a false positive in the tray beats a
    silently hidden miss."""
    by_campaign = {}
    for r, o in candidates:
        by_campaign.setdefault(str(r.get("smartlead_campaign_id")), []).append((r, o))
    kept = []
    for cid, group in by_campaign.items():
        # CACHE-ONLY (perf fix 2026-07-28): warming a campaign's subsequence
        # data inline cost 10-40s on cold caches - the whole tray endpoint
        # stalled or timed out, which the owner saw as a tray that vanishes
        # and reappears. A cold campaign now keeps its rows AS-IS (their own
        # principle: a false positive in the tray beats a hidden miss) and
        # warms in a background thread, so the NEXT fetch reconciles for real.
        cached = _enrolled_emails_cached_only(cid)
        if cached is None:
            kept.extend(o for _r, o in group)
            _warm_subseq_caches_async(cid)
            continue
        for r, o in group:
            em = str(r.get("lead_email") or "").strip().lower()
            if em and em in cached:
                _apply_patch(r, {"added_to_subsequence": True, "subsequence_decision": "pushed"})
            else:
                kept.append(o)
    return kept


def _enrolled_emails_cached_only(cid):
    """The union of enrolled emails across `cid`'s subsequences, answered
    ONLY from fresh caches - None when anything would need a network fetch."""
    now = _time.time()
    ent = _SUBSEQ_LIST_CACHE.get(str(cid))
    if not ent or (now - ent["at"]) >= _SUBSEQ_LIST_TTL:
        return None
    enrolled = set()
    for s in ent["list"]:
        e = _SUBSEQ_ENROLL_CACHE.get(str(s.get("id")))
        if not e or (now - e["at"]) >= _SUBSEQ_ENROLL_TTL:
            return None
        enrolled |= e["emails"]
    return enrolled


_SUBSEQ_WARMING = set()
_SUBSEQ_WARMING_LOCK = threading.Lock()


def _warm_subseq_caches_async(cid):
    """Fill campaign `cid`'s subsequence-list + enrolled-email caches off the
    request thread. Dedup-guarded so a fetch burst warms each campaign once."""
    cid = str(cid)
    with _SUBSEQ_WARMING_LOCK:
        if cid in _SUBSEQ_WARMING:
            return
        _SUBSEQ_WARMING.add(cid)

    def _worker():
        try:
            for s in _subsequences_for_campaign_cached(cid):
                _subseq_enrolled_emails(s.get("id"))
        except Exception:  # noqa: BLE001 - warming is best-effort by definition
            pass
        finally:
            with _SUBSEQ_WARMING_LOCK:
                _SUBSEQ_WARMING.discard(cid)
    threading.Thread(target=_worker, daemon=True, name=f"subseq-warm-{cid}").start()


# Categories a SENT thread may still be chased on. Union of every positive
# label the tool recognises anywhere (the categoriser's CORE_FOUR, the
# classifier's POSITIVE_CATEGORIES, and the ever-positive sweep's
# POSITIVE_CATEGORY_NAMES) so no positive is ever dropped from the reminder by
# a naming difference between the three lists.
# Owner ask 2026-07-25: "if someone in the setter has their lead category
# updated to something which is not positive, they shouldn't then be added to
# the send follow-up reminder" - a lead who has since been marked Not
# Interested / unqualified / wrong person is not someone to chase.
FOLLOWUP_POSITIVE_CATEGORIES = (set(CORE_FOUR) | set(POSITIVE_CATEGORIES)
                                | set(POSITIVE_CATEGORY_NAMES))

# subsequence_decision values that mean "already decided, keep it out of the
# reminder tray" (setter_queue is schema-frozen - these are new VALUES in the
# existing text column, never a new column):
#   dismissed    - explicit Dismiss (owner ruling 2026-07-22)
#   pushing      - a send-gate "push" choice whose Smartlead call is in flight
# 'none' and 'none_at_send' are deliberately NOT here (owner ruling
# 2026-07-30, reaffirming 2026-07-22): a "no follow-up" choice - whether made
# from the tray ('none') or at send time in the send-gate ('none_at_send') -
# is a MARK, not a removal. The row stays visible in "Sent without follow-up"
# until an explicit Dismiss; the mark only changes which pill it renders.
# (2026-07-25's cabfc1a hid none_at_send rows entirely - that contradicted the
# owner's rule and made gate-"None" sends invisible; reverted 2026-07-30.)
RESOLVED_DECISIONS = ("dismissed", "pushing")
# A 'pushing' row whose worker never finished (process restart mid-push) must
# not vanish forever - after this it resurfaces as unresolved.
PUSHING_GRACE_MIN = 15


def _followup_category_ok(category) -> bool:
    """True when this lead's category still justifies a follow-up reminder.
    An unknown/empty/uncategorised category returns True - "not categorised
    yet" is not the same as "not positive", and a silent drop is the worse
    failure. Uses _is_uncategorised_value so the legacy literal
    "Uncategorizable by Ai" counts as uncategorised too (it was silently
    dropping every uncategorised-intake sent reply from the tray)."""
    if _is_uncategorised_value(category):
        return True
    return str(category).strip() in FOLLOWUP_POSITIVE_CATEGORIES


def _fresh_categories_for(rows: list) -> dict:
    """{message_id: category} from the `replies` table for these queue rows, in
    ONE batched GET. The queue row's own `category` is stamped at intake and
    goes stale when someone re-labels the lead in Smartlead's master inbox
    (which is where the owner's re-labels actually happen); `replies` is what
    the categoriser and reply-sync keep current. Best-effort: any failure
    returns {} and the caller falls back to the row's stored category."""
    mids = []
    for r in rows:
        mid = str((r or {}).get("source_message_id") or (r or {}).get("message_id") or "").strip()
        if mid:
            mids.append(mid)
    if not mids or not _SB:
        return {}
    try:
        # PostgREST in.() needs each value double-quoted (message ids carry
        # <>, @ and dots). Cap the batch so a huge tray can't build a URL that
        # blows the request line.
        quoted = ",".join('"' + m.replace('"', "") + '"' for m in mids[:50])
        in_list = quote(quoted, safe='",')
        got = _SB("GET", f"replies?{_list_ws_filter()}"
                         f"&smartlead_message_id=in.({in_list})"
                         f"&select=smartlead_message_id,category&limit=100")
        if isinstance(got, list):
            return {str(g.get("smartlead_message_id")): g.get("category")
                    for g in got if isinstance(g, dict) and g.get("smartlead_message_id")}
    except Exception:  # noqa: BLE001 - freshness is a bonus, never a blocker
        pass
    return {}


def route_subsequence_unresolved(_params):
    """GET /api/setter/subsequence/unresolved - the tray's feed: sent/
    auto_sent rows from the last 14 days NOT added to a subsequence and NOT
    dismissed (subsequence_decision is null / push_failed / none - a 'none'
    "no follow-up" choice stays until an explicit Dismiss, owner ruling
    2026-07-22), reconciled against Smartlead ground truth (see
    _reconcile_unresolved_against_smartlead - enrolments made in Smartlead's
    own UI are stamped onto the row and excluded). Workspace-scoped like
    every other queue read, newest first, capped at 50.

    The `status=in.(sent,auto_sent)` and `sent_at=gte.` filters are sent to
    Supabase so a live deployment never pulls more than the window needs, but
    the added_to_subsequence / subsequence_decision / date checks are ALSO
    re-applied here in Python - belt and suspenders against a PostgREST
    filter typo, and the only filtering the in-memory test fake honours."""
    try:
        if not _SB:
            return 200, {"rows": []}
        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=14)).isoformat()
        # Only the columns this endpoint actually reads. select=* dragged every
        # row's full thread JSON (megabytes for 14 days of sent rows) and sat
        # right on the Supabase timeout - measured live 2026-07-28 at 15-33s
        # with intermittent total failure, which is what made the tray vanish.
        cols = ("id,lead_email,lead_first_name,lead_last_name,company_domain,reply_body,"
                "sent_at,smartlead_campaign_id,subsequence_decision,added_to_subsequence,"
                "category,message_id,source_message_id,workspace,agent_id")
        rows = _SB("GET", f"{QUEUE_TABLE}?{_list_ws_filter()}&status=in.(sent,auto_sent)"
                          f"&sent_at=gte.{quote(since, safe='')}&order=sent_at.desc&limit=200&select={cols}")
        if not isinstance(rows, list):
            # sb() answers None on a failed fetch (it is best-effort by
            # design). Translating that into 200 {"rows": []} told the tray
            # "everything is resolved" and it vanished (owner report
            # 2026-07-28: "the send follow-up reminder just randomly vanishes
            # after you send a few emails" - the post-send fetch burst is
            # exactly when a transient Supabase timeout hits). A failure must
            # LOOK like a failure so the client keeps its last good rows.
            return 503, {"error": "Couldn't load the unresolved list right now."}
        # One row per CONVERSATION (owner ruling 2026-08-15: "there should
        # only ever be one row in the whole system"): collapse to the newest
        # sent row per (workspace, campaign, lead) BEFORE any decision gate,
        # so the representative's own state decides whether the conversation
        # appears — an older undecided reply-row can never resurrect a thread
        # whose newest send was already resolved (William marketplaceofficer
        # had 6 rows; five one-by-one dismissals each admitted the next).
        # Same thread key as the queue's read-time collapse; rows with no
        # lead_email pass through uncollapsed rather than clumping into one
        # fake thread.
        best, no_email = {}, []
        for r in rows:
            if not isinstance(r, dict):
                continue
            email = str(r.get("lead_email") or "").strip().lower()
            if not email:
                no_email.append(r)
                continue
            key = (str(r.get("workspace") or ""),
                   str(r.get("smartlead_campaign_id") or ""), email)
            cur = best.get(key)
            if (cur is None
                    or (r.get("sent_at") or "") > (cur.get("sent_at") or "")
                    or ((r.get("sent_at") or "") == (cur.get("sent_at") or "")
                        and (r.get("id") or 0) > (cur.get("id") or 0))):
                best[key] = r
        rows = no_email + list(best.values())
        candidates = []
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                if r.get("added_to_subsequence"):
                    continue
                decision = r.get("subsequence_decision")
                # Owner ruling 2026-07-22: "No follow-up needed" (decision='none')
                # is a MARK, not a removal - the thread STAYS in the reminder tray.
                # Only an explicit Dismiss (decision='dismissed') takes it out.
                # ('pushed' already left via the added_to_subsequence check above.)
                # Owner ask 2026-07-25: a decision made AT SEND (the send-gate's
                # own follow-up chips) also counts as resolved - re-listing a
                # thread whose follow-up you just chose is what made this tray
                # pop open after every single send. See RESOLVED_DECISIONS.
                if decision in RESOLVED_DECISIONS:
                    if decision != "pushing":
                        continue
                    # 'pushing' is only trusted inside its grace window, so a
                    # push whose worker died with the process resurfaces here
                    # instead of disappearing silently.
                    try:
                        age_min = (_dt.datetime.now(_dt.timezone.utc)
                                   - _parse_iso(r.get("sent_at"))).total_seconds() / 60.0
                    except (ValueError, TypeError, AttributeError):
                        age_min = 0.0
                    if age_min < PUSHING_GRACE_MIN:
                        continue
                # Owner ask 2026-07-25: a lead re-labelled to a non-positive
                # category is not someone to chase. The stored category is the
                # first gate; _fresh_categories_for re-checks the survivors
                # against `replies` (where a master-inbox re-label lands).
                if not _followup_category_ok(r.get("category")):
                    continue
                sent_at = r.get("sent_at") or ""
                if sent_at and sent_at < since:
                    continue
                candidates.append((r, {
                    "id": r.get("id"), "lead_name": _lead_name(r), "lead_email": r.get("lead_email"),
                    "company_domain": r.get("company_domain"),
                    "reply_snippet": clean_body(r.get("reply_body") or "")[:200],
                    "sent_at": r.get("sent_at"), "smartlead_campaign_id": r.get("smartlead_campaign_id"),
                    "subsequence_decision": decision,
                    # Identity the client needs so an action on a tray-opened
                    # row survives a re-intake id swap (owner bug 2026-07-28:
                    # Buthaina's follow-up "didn't send", and "Queue row not
                    # found" on dismiss - the provisional row carried no
                    # message_id, so the id-miss fallback had nothing to
                    # re-resolve on). agent_id lets the provisional sidebar
                    # stop claiming "no agent assigned".
                    "message_id": r.get("message_id"),
                    "source_message_id": r.get("source_message_id"),
                    "workspace": r.get("workspace"), "agent_id": r.get("agent_id"),
                    "lead_first_name": r.get("lead_first_name"),
                    "lead_last_name": r.get("lead_last_name"),
                }))
        candidates.sort(key=lambda c: c[1].get("sent_at") or "", reverse=True)
        candidates = candidates[:50]
        # Second category gate, one batched GET: `replies` carries the label a
        # master-inbox re-categorise wrote, which the queue row never sees.
        fresh = _fresh_categories_for([c[0] for c in candidates])
        if fresh:
            kept = []
            for row_raw, item in candidates:
                mid = str(row_raw.get("source_message_id") or row_raw.get("message_id") or "")
                if mid in fresh and not _followup_category_ok(fresh[mid]):
                    continue
                kept.append((row_raw, item))
            candidates = kept
        out = _reconcile_unresolved_against_smartlead(candidates)
        out.sort(key=lambda r: r.get("sent_at") or "", reverse=True)
        _attach_campaign_names(out)
        return 200, {"rows": out}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _subsequence_choice_worker(row: dict, sub_sequence_id_override):
    """Off the request thread - see _subsequence_choice_async. Approve must
    never wait on a Smartlead lookup+push (same bar as _learn_from_edit_async
    for the send path). Never raises: any failure lands as subsequence_decision
    'push_failed', which is exactly what the unresolved banner watches for."""
    try:
        campaign_id = row.get("smartlead_campaign_id")
        sub_id, err = _resolve_subsequence_id(campaign_id, sub_sequence_id_override)
        if err:
            _apply_patch(row, {"subsequence_decision": "push_failed"})
            return
        ok, _detail = _push_to_subsequence(campaign_id, row.get("lead_email"),
                                          row.get("smartlead_lead_id"), sub_id)
        if ok:
            _apply_patch(row, {"added_to_subsequence": True, "subsequence_decision": "pushed"})
        else:
            _apply_patch(row, {"subsequence_decision": "push_failed"})
    except Exception as e:  # noqa: BLE001
        print(f"[setter] subsequence push failed for row {row.get('id')}: {e}", file=sys.stderr)
        try:
            _apply_patch(row, {"subsequence_decision": "push_failed"})
        except Exception:  # noqa: BLE001
            pass


def _subsequence_choice_async(row: dict, sub_sequence_id_override):
    t = threading.Thread(target=_subsequence_choice_worker, args=(row, sub_sequence_id_override),
                        daemon=True, name="setter-subsequence-push")
    t.start()
    return t


def _compute_campaigns_list() -> list:
    if _SB:
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
        # Subsequence/parent + live-name lookup, fetched ONCE up front (owner
        # report 2026-08-09): the union below needs the Smartlead names for
        # mirror-lagged campaigns, and the annotation loop at the end needs the
        # parent links. One cached call serves both; an outage degrades to {}.
        try:
            pmap = _parent_map()
        except Exception:  # noqa: BLE001
            pmap = {}
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
                    name = (((lr or {}).get("name") or "").strip()
                            or (_PARENT_CACHE.get("names") or {}).get(cid)
                            or f"Campaign {cid}")
                    status = (lr or {}).get("status") if lr else None
                    out.append({"id": cid, "name": name, "status": status})
                    seen.add(cid)
        except Exception:  # noqa: BLE001 - union is additive; a failure here must not break the endpoint
            pass
        # Subsequence -> parent annotation (owner report 2026-08-09: replies
        # landing under "Interested Reply"/"Meeting Request" bucket into the
        # client filter's "Other"). A subsequence carries no client in its own
        # name; its parent does — hand the UI the link so clientForRow can
        # derive the client from the parent campaign.
        for c in out:
            pid = pmap.get(str(c.get("id")))
            if pid:
                c["parent_id"] = pid
        return out
    return []


# ── Campaign-picker read cache (perf pass 2026-07-28) ─────────────────────
# route_campaigns_get does 2-3 sequential Supabase reads on every boot (~1s
# live) to build the picker list, which changes only when the background
# campaign sync runs - never from a user action on this page. TTL-only SWR:
# serve cached, refresh in the background when stale. An empty result is never
# cached (a Supabase blip returns [] the same as "no campaigns" - freezing that
# for 60s would blank the picker), so an outage keeps retrying for real.
_CAMPAIGNS_TTL = 60.0
_CAMPAIGNS_CACHE = {"at": 0.0, "val": None}
_CAMPAIGNS_LOCK = threading.Lock()


def _kick_campaigns_refresh():
    def run():
        if not _CAMPAIGNS_LOCK.acquire(blocking=False):
            return
        try:
            val = _compute_campaigns_list()
            if val:                       # never cache an empty/degraded read
                _CAMPAIGNS_CACHE["val"] = val
                _CAMPAIGNS_CACHE["at"] = _time.time()
        except Exception:  # noqa: BLE001 - background refresh must never raise
            pass
        finally:
            _CAMPAIGNS_LOCK.release()
    threading.Thread(target=run, daemon=True).start()


def _campaigns_list_cached() -> list:
    if _CAMPAIGNS_CACHE["val"] is not None:
        if (_time.time() - _CAMPAIGNS_CACHE["at"]) < _CAMPAIGNS_TTL:
            return _CAMPAIGNS_CACHE["val"]
        _kick_campaigns_refresh()          # stale-while-revalidate
        return _CAMPAIGNS_CACHE["val"]
    with _CAMPAIGNS_LOCK:
        if _CAMPAIGNS_CACHE["val"] is not None:
            return _CAMPAIGNS_CACHE["val"]
        val = _compute_campaigns_list()
        if val:
            _CAMPAIGNS_CACHE["val"] = val
            _CAMPAIGNS_CACHE["at"] = _time.time()
        return val


def route_campaigns_get(_params):
    try:
        return 200, _campaigns_list_cached()
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
    # Lock tested in the caller (H9): don't spawn a thread just to fail an
    # acquire under a bust burst.
    if not _KPI_COMPUTE.acquire(blocking=False):
        return

    def run():
        try:
            # Generation loop (H1): a compute that a mutation raced is stamped
            # stale by _compute_kpis_sync; run again so the cache converges.
            for _ in range(3):
                gen0 = _CACHE_GEN[0]
                _compute_kpis_sync()
                if _CACHE_GEN[0] == gen0:
                    break
        finally:
            _KPI_COMPUTE.release()
    try:
        threading.Thread(target=run, daemon=True).start()
    except RuntimeError:
        _KPI_COMPUTE.release()


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
    _kpi_gen0 = _CACHE_GEN[0]   # H1: captured before any fetch; see the write
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
            # Slim select (502 fix 2026-07-30): this used to pull the FULL
            # thread blob for every needs_review row - the multi-MB corpus -
            # on every cold KPI compute, i.e. after every mutation bust. The
            # direction verdict only needs the newest message's type; the
            # thread->-1 alias serves it in a few KB (see _queue_direction).
            rows = _SB("GET", f"{QUEUE_TABLE}?workspace=eq.{WORKSPACE}&status=eq.needs_review"
                              f"&is_test=eq.false&select=id,sent_at,decision,status,"
                              "last_type:thread->-1->>type")
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
            # thread blobs - a few KB). Shared with _thread_rep_ids via
            # _light_rows_all (panel fix, #3: this exact scan used to run
            # TWICE under two uncoordinated caches); is_test filtered here
            # in Python to keep the pill-count semantics.
            rows = _light_rows_all()
            if not isinstance(rows, list):
                return None
            return [r for r in rows if isinstance(r, dict) and not r.get("is_test")]

        # Panel fix, #4: the five COUNT queries are consumed ONLY when the
        # light scan fails (the else-branch below), and one of them duplicated
        # the "needs_review" task byte-for-byte. Run the primary wave first;
        # pay the count fallback only on a light failure. 12 queries -> 5.
        tasks = {
            "light": _light,
            "reclass": _reclass,
            "auto_sent_today": lambda: _count_rows(f"is_test=eq.false&status=eq.auto_sent&created_at=gte.{today}"),
            "sent_today": lambda: _count_rows(f"is_test=eq.false&status=eq.sent&created_at=gte.{today}"),
            "no_action_today": lambda: _count_rows(f"is_test=eq.false&status=eq.no_action&created_at=gte.{today}"),
            "avg_response_mins_7d": _avg_response,
        }
        fallback_tasks = {
            "c_needs_review": lambda: _pill("status=eq.needs_review"),
            "c_sent": lambda: _pill("status=eq.sent"),
            "c_auto_sent": lambda: _pill("status=eq.auto_sent"),
            "c_dismissed": lambda: _pill("status=eq.dismissed"),
            "c_all": lambda: _pill("id=not.is.null"),
        }
        results = {}
        # 5 workers, not len(tasks): each worker opens its own TLS connection
        # to Supabase (urllib has no keep-alive) and ~11 simultaneous
        # handshakes visibly choked the small Render instance.

        def _run_wave(wave):
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(wave))) as pool:
                fut_key = {pool.submit(fn): k for k, fn in wave.items()}
                for fut in concurrent.futures.as_completed(fut_key):
                    k = fut_key[fut]
                    try:
                        results[k] = fut.result()
                    except Exception:  # noqa: BLE001 - one bad query must not sink the block
                        results[k] = None
        _run_wave(tasks)
        if results.get("light") is None:
            _run_wave(fallback_tasks)
        # the else-branch's needs_review fallback reads the same count
        results["needs_review"] = results.get("c_needs_review")
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
            # KPI badges stay navreo-only (byte-for-byte): the federated light
            # scan may carry monitor-workspace rows for the LIST/collapse, but
            # navreo's pill counts must not move — and _reclass's dir map is
            # navreo-scoped, so only navreo reps have a direction verdict here.
            reps = [r for r in reps if (r.get("workspace") or "navreo") == "navreo"]
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
        # H1: a compute that a mutation raced must not stamp itself fresh -
        # mark stale so the SWR path serves it but re-kicks a refresh.
        _KPI_CACHE["at"] = now if _CACHE_GEN[0] == _kpi_gen0 else 0.0
    return kpis


# ── Row-level campaign identity (identification fix 2026-08-11) ────────────
# The list used to rely ENTIRELY on the client joining /api/setter/campaigns
# (navreo-scoped, fetched in parallel, silently [] on a failed load) to name
# each row's campaign — any race, transient fetch failure, or federated
# (non-navreo) row rendered as "Campaign <id>" for the whole session, and the
# sidebar then read as "can't identify this campaign" so the agent couldn't
# sensibly be assigned. The name now travels WITH the row: one batched
# CROSS-WORKSPACE mirror read (cached), with the live Smartlead listing as the
# mirror-lag fallback for brand-new campaigns. Pure read — never written back.
_CAMP_NAME_TTL = 600.0
_CAMP_NAME_CACHE = {}   # str(campaign_id) -> (name, fetched_at)
_CAMP_NAME_LOCK = threading.Lock()


def _campaign_names_for(ids) -> dict:
    """{str(campaign_id): display name} for every resolvable id, across ALL
    workspaces (the queue federates). Resolution tiers: campaigns mirror →
    campaign_scorecard (every workspace's sweep) → navreo Smartlead listing →
    capped per-id Smartlead read with a federated key. Unresolvable ids map to
    None or are absent — the client keeps its "Campaign <id>" fallback for
    those. Never raises."""
    want = sorted({str(i) for i in ids if i})
    if not want:
        return {}
    now = _time.time()
    out, missing = {}, []
    with _CAMP_NAME_LOCK:
        for cid in want:
            ent = _CAMP_NAME_CACHE.get(cid)
            if ent and (now - ent[1]) < _CAMP_NAME_TTL:
                out[cid] = ent[0]
            else:
                missing.append(cid)
    if missing and _SB:
        try:
            rows = _SB("GET", "campaigns?smartlead_campaign_id=in.(" + ",".join(missing) + ")"
                              "&select=smartlead_campaign_id,name")
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict) and str(r.get("name") or "").strip():
                        out[str(r.get("smartlead_campaign_id"))] = str(r["name"]).strip()
        except Exception:  # noqa: BLE001 - a mirror blip degrades to the fallbacks below
            pass
        still = [c for c in missing if c not in out]
        if still:
            # Scorecard tier (federation fix 2026-08-12, campaign 3725976 /
            # Asteri): the register cron can MISS a client-workspace campaign
            # entirely — the mirror had no row for 3 of asteri's 8 queue
            # campaigns — but the scorecard sweep stamps every workspace's
            # campaigns (name included) on its regular pass, so it names the
            # rows the mirror never saw. Same batched-read shape as above.
            try:
                rows = _SB("GET", "campaign_scorecard?smartlead_campaign_id=in.(" + ",".join(still) + ")"
                                  "&select=smartlead_campaign_id,name")
                if isinstance(rows, list):
                    for r in rows:
                        if isinstance(r, dict) and str(r.get("name") or "").strip():
                            out[str(r.get("smartlead_campaign_id"))] = str(r["name"]).strip()
            except Exception:  # noqa: BLE001
                pass
            still = [c for c in still if c not in out]
        if still:
            # Mirror-lag fallback: the (cached) Smartlead listing knows a
            # brand-new campaign minutes before the register cron lands its
            # mirror row. _parent_map is TTL-cached, so this is usually free.
            try:
                _parent_map()
                names = _PARENT_CACHE.get("names") or {}
                for cid in still:
                    if names.get(cid):
                        out[cid] = names[cid]
            except Exception:  # noqa: BLE001
                pass
            still = [c for c in still if c not in out]
        # Last resort, capped: a direct per-id Smartlead read. _sl_get
        # federates the key via _WS_KEY_FOR_CAMPAIGN (scorecard/mirror-backed),
        # so a client-workspace id resolves with the CLIENT's key. Capped at 3
        # per call and negative-cached below, so a permanently-unresolvable id
        # can never turn every queue rebuild into a Smartlead storm.
        for cid in still[:3]:
            try:
                r = _sl_get(f"/campaigns/{cid}", campaign_id=cid)
                if isinstance(r, dict) and str(r.get("name") or "").strip():
                    out[cid] = str(r["name"]).strip()
            except Exception:  # noqa: BLE001
                pass
        with _CAMP_NAME_LOCK:
            for cid in missing:
                # Misses cache as None (negative cache): "known unresolvable,
                # don't re-hammer the fallbacks until the TTL turns over".
                # The attach helper's `if n:` guard skips None stamps.
                _CAMP_NAME_CACHE[cid] = (out.get(cid), now)
    return out


def _attach_campaign_names(rows) -> None:
    """Stamp `campaign_name` onto queue/tray row dicts IN PLACE (read-time
    annotation, same never-written-back class as _annotate_queue_row's).
    Best-effort: a resolution failure leaves rows untouched, never raises."""
    try:
        names = _campaign_names_for({(r or {}).get("smartlead_campaign_id")
                                     for r in rows if isinstance(r, dict)})
        for r in rows:
            if isinstance(r, dict):
                n = names.get(str(r.get("smartlead_campaign_id") or ""))
                if n:
                    r["campaign_name"] = n
    except Exception:  # noqa: BLE001 - identity annotation must never break the queue
        pass


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
    g = row.get("guardrails") or {}
    if not slots and row.get("draft_body") and g.get("slot_status") not in (None, "ok") and g.get("slot_reason"):
        # Structured truth, stamped at draft time by slot_situation() — no
        # guessing. The text heuristic below only serves rows drafted before
        # the stamp existed (2026-08-09).
        no_slots = str(g["slot_reason"])
    elif not slots and row.get("draft_body"):
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
        # Slim row (memory ruling 2026-07-30): the list fetch aliases the
        # newest thread message's type off thread->-1 instead of carrying the
        # whole blob. hydrate_lead always persists threads time-sorted
        # ascending, so the last element is the newest - same verdict the
        # max() below reaches on a full thread.
        lt = row.get("last_type")
        if lt:
            if str(lt).upper() == "REPLY":
                return True, None
            is_agent = bool(row.get("sent_at")) and row.get("decision") == "auto_send"
            return False, ("auto_sent" if is_agent else "sent")
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


def _light_rows_all():
    """ONE 2000-row light scan shared by the thread-collapse and the KPI
    compute (panel fix, #3: the same scan ran twice under two uncoordinated
    caches - which could even disagree about a thread's representative).
    is_test is UNfiltered here; callers filter in Python. order= is load-
    bearing: without it PostgREST truncation past 2000 rows is arbitrary and
    the collapse silently drops representatives (panel nitpick, correctness
    cliff). Returns None on fetch failure. Rides _REP_IDS_CACHE's 10s clock."""
    now = _time.time()
    if _REP_IDS_CACHE.get("rows") is not None and (now - _REP_IDS_CACHE.get("rows_at", 0.0)) < _REP_IDS_TTL:
        return _REP_IDS_CACHE["rows"]
    if now < _REP_IDS_CACHE.get("truncated_until", 0.0):
        return None   # a recent cap-out: don't re-pay the full scan per request
    if not _SB:
        return None
    # PAGED (panel fix 2026-08-01): a single limit=2000 request is silently
    # clipped to Supabase's 1000-row max-rows, so the old cap check could
    # never fire and the collapse quietly dropped the OLDEST rows — the
    # un-actioned needs_review replies the inbox must never lose. Three
    # 1000-row pages cover 3x today's corpus; a genuine 3000+ overflow
    # refuses the scan loudly (callers degrade to the uncollapsed view).
    # Single-flight (panel fix 2026-08-01): three boot warm-ups reach this on
    # an empty cache together, and each scan is now up to 3 sequential reads.
    if not _LIGHT_SCAN_LOCK.acquire(blocking=False):
        # A peer is scanning. Serve the LAST-GOOD (stale) scan instead of
        # None (ghost fix 2026-08-09): returning None made every loser of
        # this race skip the thread collapse entirely and serve — and CACHE —
        # the uncollapsed view, resurrecting dismissed conversations' older
        # needs_review siblings right after any action busted the caches.
        # A few-seconds-stale collapse is strictly better than none; brand-new
        # rows unknown to the stale scan pass through via the `known` set.
        return _REP_IDS_CACHE.get("rows")
    try:
        ent2 = _REP_IDS_CACHE.get("rows")   # the peer may have landed it
        if ent2 is not None and (_time.time() - _REP_IDS_CACHE.get("rows_at", 0.0)) < _REP_IDS_TTL:
            return ent2
        light = []
        for page in range(3):
            got = _SB("GET", f"{QUEUE_TABLE}?{_list_ws_filter()}&limit=1000&offset={page * 1000}"
                             "&order=created_at.desc,id.desc"
                             "&select=id,status,smartlead_campaign_id,lead_email,"
                             "replied_at,created_at,is_test,workspace")
            if not isinstance(got, list):
                # Failed fetch: last-good stale scan beats no collapse at all
                # (ghost fix 2026-08-09, same rationale as the lock branch).
                return _REP_IDS_CACHE.get("rows")
            light.extend(got)
            if len(got) < 1000:
                break
        else:
            print("[setter] light scan overflowed 3000 rows — skipping thread collapse "
                  "rather than dropping old rows; page this scan wider.", file=sys.stderr)
            # Floor stamped AFTER the scan (a slow scan must still leave one).
            _REP_IDS_CACHE["truncated_until"] = _time.time() + _REP_IDS_TTL
            return None
        _REP_IDS_CACHE["rows"] = light
        _REP_IDS_CACHE["rows_at"] = _time.time()
        return light
    finally:
        _LIGHT_SCAN_LOCK.release()


def _thread_rep_ids():
    """Set of setter_queue ids that are their thread's representative row,
    or None when the light fetch fails (callers then skip the collapse and
    degrade to the uncollapsed view rather than blanking the inbox)."""
    now = _time.time()
    if _REP_IDS_CACHE["val"] is not None and (now - _REP_IDS_CACHE["at"]) < _REP_IDS_TTL:
        return _REP_IDS_CACHE["val"]
    try:
        light = _light_rows_all()
        if not isinstance(light, list):
            # Degrade to the LAST-GOOD rep set (ghost fix 2026-08-09) — None
            # (skip-the-collapse) resurrected dismissed conversations' older
            # siblings; a stale collapse never does, and rows the stale scan
            # has never seen pass the filter via the `known` set.
            return _REP_IDS_CACHE["val"]
        val = {r.get("id") for r in _collapse_threads(light) if isinstance(r, dict)}
        if not val:
            # An empty representative-set while the queue has rows (the KPIs show
            # a backlog) means the light fetch came back empty/short — a cold-boot
            # or transient blip, never a real "zero threads". Serve the last-good
            # rep set (None only on a true cold boot) so callers never flip to
            # the uncollapsed view. Don't cache the empty (10s TTL) — retry on
            # the next read.
            return _REP_IDS_CACHE["val"]
    except Exception:  # noqa: BLE001 - collapse is best-effort, never sink the queue
        return _REP_IDS_CACHE["val"]
    _REP_IDS_CACHE["val"] = val
    # Every id the scan saw: the pill filter keeps ids OUTSIDE this set (a
    # brand-new intake a stale rep set can't know about must never be hidden).
    _REP_IDS_CACHE["known"] = {r.get("id") for r in light if isinstance(r, dict)}
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
    if _POLL_TS_CACHE["val"] is not None:
        if (now - _POLL_TS_CACHE["at"]) < _POLL_TS_TTL:
            return _POLL_TS_CACHE["val"]
        # Stale-serve + background refresh (panel fix, F3): after a bust the
        # next queue GET used to pay this Supabase round trip synchronously -
        # inside the 'instant' response path. The display is minutes-granular;
        # a 10s-stale value is indistinguishable to the user.
        if _POLL_TS_REFRESHING.acquire(blocking=False):
            def _rf():
                try:
                    rows = _SB("GET", "app_activity_log?action=eq.setter_poll_done"
                                      "&order=ts.desc&limit=1&select=ts") if _SB else None
                    v = rows[0].get("ts") if isinstance(rows, list) and rows else None
                    if v is not None:
                        _POLL_TS_CACHE["val"] = v
                        _POLL_TS_CACHE["at"] = _time.time()
                except Exception:  # noqa: BLE001 - best-effort display value
                    pass
                finally:
                    _POLL_TS_REFRESHING.release()
            try:
                threading.Thread(target=_rf, daemon=True).start()
            except RuntimeError:
                _POLL_TS_REFRESHING.release()
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


_POLL_TS_REFRESHING = threading.Lock()


# Every setter_queue column EXCEPT the fat `thread` jsonb, plus two scalar
# aliases off its newest element for who-spoke-last (memory ruling 2026-07-30;
# see _fetch_queue_rows). setter_queue is schema-frozen (see the schema-freeze
# gotcha) so this list drifts only if that ruling is ever revisited - if a
# column IS added, add it here or the queue list silently won't carry it.
QUEUE_LIST_COLUMNS = (
    # original_draft_body deliberately absent (panel fix, #2): it is a byte
    # copy of draft_body (~25% of the list payload) consumed by exactly one
    # client line, which now reads it off the send response's full row.
    # last_time deliberately absent: selected-but-never-read dead payload.
    "added_to_subsequence,agent_id,category,category_source,classification,"
    "company_domain,created_at,decision,decision_reason,draft_body,"
    "draft_subject,email_stats_id,error,first_outbound,guardrails,id,is_test,"
    "lead_email,lead_first_name,lead_last_name,message_id,"
    "replied_at,reply_body,reply_subject,sent_at,sent_body,slots,"
    "smartlead_campaign_id,smartlead_lead_id,source_message_id,status,"
    "subsequence_decision,timezone,updated_at,workspace,"
    "last_type:thread->-1->>type")

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
# Full-trim (owner ask 2026-07-29): only Needs review is kept warm in the row
# cache. The other pills (sent / auto_sent / dismissed / all-statuses "") fetch
# fresh on their rare click and are never cached, so they don't sit in the
# 512MB web instance's memory. The follow-up tray is its own endpoint.
_ROWS_REWARM_STATUSES = ("needs_review",)

# Memoized serialize+gzip of the queue GET body (see queue_response below).
# _queue_rows_cached single-flights the Supabase FETCH, but every GET still
# re-ran json.dumps(~6MB full-hydrate corpus)+gzip through server.py's _json.
# N tabs booting -> N concurrent multi-MB serializations, GIL-pinned on the
# 0.5-CPU starter box: /healthz starves and Render restarts it (observed
# crash-looping ~every 2-4 min on a fixed commit). Build the bytes ONCE behind
# a single global lock and hand the same buffer to every concurrent caller.
_QUEUE_RESP_MEMO = {}          # (status, limit, fields) -> (etag, raw_len, gz, at)
_QUEUE_RESP_LOCK = threading.Lock()
_QUEUE_RESP_TTL = _ROWS_TTL    # align with the rows SWR window
# Hard wall-clock bound on serving a stale buffer (panel fix, F1/H3): if the
# background rebuild keeps failing, one inline build restores truth rather
# than serving a frozen snapshot forever.
_QUEUE_RESP_MAX_STALE_S = 120.0
# Single-flight for the rare non-needs_review pill builds (H7).
_PILL_BUILD_LOCK = threading.Lock()


def _rows_lock(key):
    with _ROWS_META:
        lk = _ROWS_LOCKS.get(key)
        if lk is None:
            lk = _ROWS_LOCKS[key] = threading.Lock()
        return lk


def _fetch_queue_rows(status: str, limit: int, before: str = None,
                      return_raw_count: bool = False):
    """The uncached read: fetch, direction-reclassify, annotate. Pure read.

    `before` (an ISO created_at) fetches the window STRICTLY OLDER than that
    cursor - the keyset page behind the inbox's infinite scroll (owner ask
    2026-08-17). It lets the tray reach past the newest-`limit` window without
    ever holding the whole backlog resident: each older page is fetched,
    served, and dropped (the cursor path is never cached). `return_raw_count`
    makes the return a (rows, raw_len) tuple - raw_len is the count BEFORE
    collapse/reclass, so the caller can tell "the scan filled the window"
    (raw_len == limit, maybe more older rows) from "the window wasn't full"
    (the genuine end of the backlog).

    Returns None (NOT []) when the underlying Supabase fetch FAILED. A false-
    empty here would blank an inbox whose pill COUNT still reports a backlog -
    so callers keep the last-good value on None; a genuinely empty pill still
    returns [].

    Memory ruling 2026-07-30 (502 fix): this used to select=* including the
    full `thread` blobs - 6.9MB of JSON for 177 rows, held resident in
    _ROWS_CACHE as tens of MB of Python dicts on a 512MB box, refetched on
    every SWR refresh - when the ONLY thing the list path needs from the
    thread is "who spoke last" (_queue_direction). thread->-1 gives exactly
    that: hydrate_lead always persists the thread time-sorted ascending, so
    the last element IS the newest message. Full threads are served per-row
    by /api/setter/thread (cache-first) - never by the list."""
    rows = []
    fetch_failed = False
    raw_len = 0
    if _SB:
        # Keyset cursor: `created_at=lt.<before>` is the window strictly older
        # than the client's oldest loaded row (infinite scroll). No `before`
        # is the normal newest-`limit` head fetch, byte-identical to before.
        cursor = f"&created_at=lt.{quote(before, safe='')}" if before else ""
        base = (f"{_list_ws_filter()}&order=created_at.desc&limit={limit}{cursor}"
                f"&select={QUEUE_LIST_COLUMNS}")
        # For the direction-aware pills (needs_review / sent / auto_sent) the
        # membership depends on who spoke last, computed at read time from
        # `thread` (see _queue_direction). The sent/auto_sent pills must also
        # consider needs_review rows we've already answered, so pull both.
        def _one_fetch(filt):
            """One PostgREST read with a LOUD degraded fallback (panel fix,
            F2): http_json returns a 4xx error BODY as a dict (it does not
            raise), so a select-syntax rejection - e.g. a PostgREST version
            that refuses the thread->-1 alias - used to be indistinguishable
            from 'no rows' and blanked the inbox silently, forever. A dict
            answer is logged and retried once with the alias-free select."""
            got = _SB("GET", f"{QUEUE_TABLE}?{filt}")
            if isinstance(got, dict):
                print(f"[setter] queue select rejected ({str(got)[:200]}) - "
                      f"retrying without JSON-path aliases", file=sys.stderr)
                plain = QUEUE_LIST_COLUMNS.split(",last_type:")[0]
                got = _SB("GET", f"{QUEUE_TABLE}?{filt.replace(QUEUE_LIST_COLUMNS, plain)}")
            return got

        # sent/auto_sent pills must also consider needs_review rows we've
        # already answered - one in.() query, not two serial round trips
        # (panel fix, #5: two calls also made the effective cap 2x limit).
        if status in ("sent", "auto_sent"):
            fetched = _one_fetch(f"{base}&status=in.({status},needs_review)")
        elif status:
            fetched = _one_fetch(f"{base}&status=eq.{status}")
        else:  # All
            fetched = _one_fetch(base)
        if isinstance(fetched, list):
            rows = fetched
            raw_len = len(fetched)   # BEFORE collapse/reclass — the has_more signal
        else:  # None = timeout/error from _SB, never "no rows"
            fetch_failed = True
        # Every fetch failed and we have nothing: signal failure so the caller
        # keeps its last-good rows instead of caching/serving a false-empty.
        if fetch_failed and not rows:
            return (None, 0) if return_raw_count else None
        # Thread collapse FIRST (one representative row per conversation),
        # THEN the who-spoke-last reclass on the survivor - the order is
        # load-bearing: a stale needs_review sibling must vanish because a
        # newer dismissed/sent sibling won the thread, and only the winner's
        # own state decides its pill.
        rep_ids = _thread_rep_ids()
        if rep_ids is not None:
            # A row the (possibly stale) scan never saw passes through: hiding
            # a brand-new reply for a scan cycle is worse than briefly showing
            # a sibling pair (ghost fix 2026-08-09).
            known = _REP_IDS_CACHE.get("known") or set()
            rows = [r for r in rows if isinstance(r, dict)
                    and (r.get("id") in rep_ids or r.get("id") not in known)]
        if status in ("needs_review", "sent", "auto_sent"):
            rows = _reclassify_queue(rows, status)
        rows.sort(key=lambda r: (r or {}).get("created_at") or "", reverse=True)
    out = [_annotate_queue_row(r) for r in rows if isinstance(r, dict)]
    _attach_campaign_names(out)
    return (out, raw_len) if return_raw_count else out


# Mutation generation counter (panel fix 2026-07-30, H1). Stale-marking means
# an in-flight refresh that started BEFORE a mutation could land AFTER it and
# stamp pre-mutation rows with a fresh timestamp - serving deleted rows for a
# full TTL. Every writer captures the generation before its fetch; a store
# whose generation moved underneath it is stamped already-stale (at=0.0), so
# the SWR path still serves it but immediately re-kicks a refresh.
_CACHE_GEN = [0]


def _store_rows(key, rows, gen=None):
    if rows is None:   # a failed fetch (timeout) — never cache a false-empty
        return
    fresh = gen is None or gen == _CACHE_GEN[0]
    _ROWS_CACHE[key] = {"at": _time.time() if fresh else 0.0, "rows": rows}


def _queue_rows_cached(status: str, limit: int) -> list:
    # Full-trim (owner ask 2026-07-29): only Needs review is cached. Every other
    # pill fetches fresh on its (rare) click so nothing but the inbox sits warm
    # in the 512MB instance's memory. A failed fetch degrades to [] like before.
    # Only the UI's own limit (200) is cache-keyed (panel fix 2026-08-01): the
    # limit comes off the query string, so caching per-limit let any authed
    # client mint up to 500 permanent full-row-list entries — an OOM walk on
    # the 512MB box. Odd limits just fetch through.
    if status != "needs_review" or limit != 200:
        rows = _fetch_queue_rows(status, limit)
        return [] if rows is None else rows
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
        if rows is None:              # fetch failed: keep last-good, don't cache
            ent = _ROWS_CACHE.get(key)
            return ent["rows"] if ent else []
        _store_rows(key, rows)
        return rows


def _kick_rows_refresh(key):
    # Lock is tested in the CALLER (panel fix 2026-07-30, H9): under a bust
    # burst most refresh threads used to exist only to fail an acquire and
    # exit - spawn only when this kick actually owns the refresh.
    lk = _rows_lock(key)
    if not lk.acquire(blocking=False):
        return   # someone is already refreshing this key

    def run():
        try:
            # Generation loop (H1): if a mutation lands mid-fetch the store is
            # stamped stale - refetch so the cache converges on post-mutation
            # data without waiting for the next GET. Bounded, never spins.
            for _ in range(3):
                gen0 = _CACHE_GEN[0]
                _store_rows(key, _fetch_queue_rows(*key), gen=gen0)
                if _CACHE_GEN[0] == gen0:
                    break
        except Exception:  # noqa: BLE001 - background refresh must never raise
            pass
        finally:
            lk.release()
    try:
        threading.Thread(target=run, daemon=True).start()
    except RuntimeError:   # can't start new thread - release, next GET re-kicks
        lk.release()


def _kick_queue_resp_rebuild(memo_key):
    """Rebuild one memoized queue response OFF the request path (SWR leg of
    queue_response, 502 fix 2026-07-30). Non-blocking single-flight: if the
    global lock is busy someone is already building - skip, the next GET
    re-kicks if still stale. Never raises; an empty-rows body is never stored
    (same guard as the inline build - a cold thread-collapse can briefly
    filter to [] and caching that blanks the inbox for a whole TTL)."""
    # Lock tested in the caller (H9): no thread spawned just to fail an acquire.
    if not _QUEUE_RESP_LOCK.acquire(blocking=False):
        return

    def run():
        import gzip
        try:
            status_q, limit = memo_key
            etag = _queue_resp_etag(status_q, limit)
            ent = _QUEUE_RESP_MEMO.get(memo_key)
            if ent and ent[0] == etag and (_time.time() - ent[3]) <= _QUEUE_RESP_TTL:
                return   # a peer rebuilt it while we queued
            # Freshen the ROWS first (panel fix, H2): building off
            # _queue_rows_cached's stale-serving would memoize pre-mutation
            # rows and make convergence take a third GET. This worker is
            # already off the request path - pay the real fetch here.
            rows_ent = _ROWS_CACHE.get((status_q, limit))
            if not rows_ent or (_time.time() - rows_ent["at"]) >= _ROWS_TTL:
                for _ in range(3):   # generation loop, same as _kick_rows_refresh
                    gen0 = _CACHE_GEN[0]
                    _store_rows((status_q, limit),
                                _fetch_queue_rows(status_q, limit), gen=gen0)
                    if _CACHE_GEN[0] == gen0:
                        break
            # Generation guard (panel fix 2026-08-01, same H1 rule the rows/
            # KPI caches already had): a mutation that landed mid-build means
            # these bytes are pre-mutation — stamping the post-mutation etag
            # on them would declare stale bytes FRESH and kick no rebuild.
            # Retry up to 3 builds toward a still generation (same shape as
            # _store_rows) so a mutation burst converges HERE instead of
            # leaving a raced etag that makes every GET re-kick a 6MB build.
            st = body = raw = gz = None
            etag_new = None
            for attempt in range(3):
                gen0 = _CACHE_GEN[0]
                if attempt:
                    # A raced attempt means a mutation landed mid-build: the
                    # rows cache is stale-marked, so re-serializing it buys
                    # nothing — fetch fresh rows first so the retry actually
                    # converges (panel fix 2026-08-01).
                    _store_rows((status_q, limit),
                                _fetch_queue_rows(status_q, limit), gen=gen0)
                st, body = route_queue_get({"status": [status_q],
                                            "limit": [str(limit)]})
                if st != 200 or not _queue_body_cacheable(body):
                    return
                raw = json.dumps(body).encode()
                gz = gzip.compress(raw, 1 if len(raw) > 262144 else 6)
                if _CACHE_GEN[0] == gen0:
                    etag_new = _queue_resp_etag(status_q, limit)
                    break
                etag_new = f"raced|{_CACHE_GEN[0]}"
            ent_new = (etag_new, len(raw), gz, _time.time())
            _QUEUE_RESP_MEMO[memo_key] = ent_new
            # Raced bytes are never written to durable storage — the next
            # boot would restore them as the first paint (panel fix).
            if (memo_key == ("needs_review", 200) and body.get("rows")
                    and not str(etag_new).startswith("raced")):
                _persist_queue_resp(ent_new)
        except Exception as e:  # noqa: BLE001 - must never raise, but NEVER silently:
            # a permanently-failing rebuild is indistinguishable from a healthy
            # one, and the max-stale ceiling is the only other safety net (F1).
            print(f"[setter] queue memo rebuild failed: {e}", file=sys.stderr)
        finally:
            _QUEUE_RESP_LOCK.release()
    try:
        threading.Thread(target=run, daemon=True, name="setter-queue-rebuild").start()
    except RuntimeError:
        _QUEUE_RESP_LOCK.release()


def _bust_read_caches(rewarm: bool = True):
    """A mutation changed queue rows: mark every read cache STALE (never
    empty) so the next GET serves the last-good value instantly while a
    background refresh replaces it.

    502 fix 2026-07-30: this used to CLEAR the caches outright, so the first
    GET after ANY action paid a cold 12-query KPI compute + a multi-MB rows
    fetch + serialize + gzip synchronously - under the process-global response
    lock, on a 512MB / 0.5-CPU box. Every send fires 2-4 busts, so a burst of
    actions GIL-starved /healthz, Render restarted the instance (boot ledger:
    20+ restarts/day), and every in-flight request got the proxy's 502 - the
    "Couldn't send the reply" / "Couldn't refresh the queue" reports. Stale-
    marking keeps the same freshness contract (every cache here is already
    SWR; the UI tolerates seconds of lag) with none of the cold cliffs."""
    _CACHE_GEN[0] += 1   # H1: any in-flight refresh must not stamp itself fresh
    with _KPI_LOCK:
        if _KPI_CACHE.get("val") is not None:
            _KPI_CACHE["at"] = 0.0   # stale -> _compute_kpis serves cached + bg refresh
        # val stays None only on a true cold boot: that one compute is sync.
    _POLL_TS_CACHE["at"] = 0.0
    _REP_IDS_CACHE["at"] = 0.0
    _REP_IDS_CACHE["rows_at"] = 0.0
    for ent in list(_ROWS_CACHE.values()):   # list(): concurrent insert-safe (M12)
        ent["at"] = 0.0              # stale, never cleared: SWR keeps serving
    # _QUEUE_RESP_MEMO entries deliberately survive: their etag (rows_at +
    # kpis) stops matching the moment refreshed rows land, and queue_response
    # then serves the stale buffer while rebuilding in the background.
    if rewarm:
        _kick_kpi_refresh()
        stale_keys = [k for k in list(_ROWS_CACHE.keys())
                      if k[0] in _ROWS_REWARM_STATUSES and k[1] == 200]
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
        before = _qp(params, "before", "") or None
        if before:
            # Infinite-scroll keyset page: rows OLDER than the client's cursor,
            # fetched fresh and never cached (the 512MB box must not hold the
            # whole backlog resident). has_more = the raw scan filled the
            # window, so a still-older ?before request may find more. The KPI
            # block is deliberately omitted - the head fetch owns the counts;
            # an older page only extends the list.
            page_rows, raw_len = (_fetch_queue_rows(status, limit, before=before,
                                                    return_raw_count=True)
                                  if _SB else ([], 0))
            if page_rows is None:
                return 503, {"error": "Couldn't load older replies - retry in a moment."}
            return 200, {"rows": page_rows, "has_more": raw_len >= limit}
        rows = _queue_rows_cached(status, limit) if _SB else []
        # fields=list is accepted for client compatibility but is now a no-op:
        # the slim QUEUE_LIST_COLUMNS select never fetches `thread`, so list
        # and default responses are identical (threads come from
        # /api/setter/thread, cache-first).
        return 200, {"rows": rows, "kpis": _compute_kpis(), "last_checked": _last_poll_done_at()}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


# ── queue buffer persistence (queue-502 fix 2026-08-01) ─────────────────────
# The memo above is process memory, and the box restarts 5-20x/day (deploys +
# OOM), so the very first /api/setter/queue after every boot paid the full
# cold build inline — the residual "Couldn't refresh the queue: 502". Persist
# the ONE buffer the UI's first request always asks for (needs_review/200)
# into the same generic KV table the deliverability page already uses for
# exactly this reason, and restore it before the first cold build. The
# restored buffer serves instantly (its etag can't match, so the SWR leg
# rebuilds truth in the background).
_QUEUE_RESP_STORE_ID = "setter_queue_resp_v1"
_QUEUE_RESP_PERSIST_MIN_S = 60.0     # throttle: at most one ~300KB write/min
_QUEUE_RESP_PERSIST_LAST = [0.0]
# 24h, not minutes (panel fix 2026-08-01): Render idle spin-downs exceed any
# minutes-scale bound by definition, so a tight bound nullified persistence on
# exactly the boots it was built for. The restored buffer serves ONE first
# paint and is SWR-replaced on the same request; the 120s ceiling and the
# client's 60s refresh bound how long stale content can survive after that.
_QUEUE_RESP_RESTORE_MAX_AGE_S = 24 * 3600.0
_QUEUE_RESP_RESTORE_LOCK = threading.Lock()   # single-flight: one ~300KB read, not N
# done: a definitive answer was read (present or genuinely absent).
# next_try: retry floor after a TRANSIENT failure — one cold-connection blip
# must not burn the process's only restore attempt (panel fix 2026-08-01).
_QUEUE_RESP_RESTORE = {"done": False, "next_try": 0.0}


def _persist_queue_resp(ent) -> None:
    """Best-effort write of the needs_review/200 buffer to Supabase. Never
    raises; throttled so mutation bursts don't turn into write storms."""
    now = _time.time()
    if not _SB or (now - _QUEUE_RESP_PERSIST_LAST[0]) < _QUEUE_RESP_PERSIST_MIN_S:
        return
    _QUEUE_RESP_PERSIST_LAST[0] = now
    try:
        import base64
        _SB("POST", "deliverability_audit_cache?on_conflict=id",
            {"id": _QUEUE_RESP_STORE_ID,
             "blob": {"etag": ent[0], "raw_len": ent[1],
                      "gz_b64": base64.b64encode(ent[2]).decode(), "saved_at": now},
             "ts": _dt.datetime.now(_dt.timezone.utc).isoformat()},
            prefer="resolution=merge-duplicates,return=minimal")
    except Exception as e:  # noqa: BLE001 - persistence is a bonus, never a blocker
        print(f"[setter] queue memo persist failed: {e}", file=sys.stderr)


def restore_queue_memo_from_store() -> bool:
    """One-shot per process: pull the last persisted queue buffer into the
    memo so a fresh boot serves bytes instantly instead of paying the cold
    build on the request path. Called from server.py's _boot_warmup AND
    lazily by queue_response if a request beats the warmup. Never raises."""
    if _QUEUE_RESP_RESTORE["done"] or not _SB:
        return False
    if _time.time() < _QUEUE_RESP_RESTORE["next_try"]:
        return False
    # Single-flight (panel fix 2026-08-01): N concurrent cold requests each
    # paid the ~300KB blob read; the losers now skip straight to the build
    # path, where the bounded lock makes them wait on the one builder.
    if not _QUEUE_RESP_RESTORE_LOCK.acquire(blocking=False):
        return False
    try:
        import base64
        rows = _SB("GET", f"deliverability_audit_cache?id=eq.{_QUEUE_RESP_STORE_ID}&select=blob")
        if not isinstance(rows, list):
            # sb() answers None on a transient failure — leave the attempt
            # open (with a floor) instead of burning it on a cold connection.
            _QUEUE_RESP_RESTORE["next_try"] = _time.time() + 30.0
            return False
        _QUEUE_RESP_RESTORE["done"] = True   # definitive answer: present or absent
        blob = rows[0].get("blob") if rows and isinstance(rows[0], dict) else None
        if isinstance(blob, str):
            blob = json.loads(blob)
        if not isinstance(blob, dict) or not blob.get("gz_b64"):
            return False
        # Age bound (panel fix 2026-08-01): after a weekend spin-down the
        # snapshot may be days old — "stale then rebuilt" is the design, but
        # unbounded staleness is not. Older than the bound → cold build.
        if _time.time() - float(blob.get("saved_at") or 0) > _QUEUE_RESP_RESTORE_MAX_AGE_S:
            return False
        gz = base64.b64decode(blob["gz_b64"])
        key = ("needs_review", 200)
        if key not in _QUEUE_RESP_MEMO:
            # at=now keeps it inside the max-stale ceiling; the saved etag
            # can't match the live one, so the SWR leg rebuilds immediately.
            _QUEUE_RESP_MEMO[key] = (str(blob.get("etag") or "restored"),
                                     int(blob.get("raw_len") or len(gz)), gz, _time.time())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[setter] queue memo restore failed: {e}", file=sys.stderr)
        _QUEUE_RESP_RESTORE["next_try"] = _time.time() + 30.0
        return False
    finally:
        _QUEUE_RESP_RESTORE_LOCK.release()


def _queue_resp_etag(status: str, limit: int) -> str:
    """PURE in-memory fingerprint for the queue body - no serialization, no
    I/O (panel fix 2026-07-30, F3: the old version called _compute_kpis() and
    _last_poll_done_at() on every GET, which post-bust meant a synchronous
    Supabase round trip - or on a cold boot the full 12-query fan-out -
    INSIDE the fingerprint, before the 'instant' stale bytes went out).
    rows_at moves whenever the rows refetch; _CACHE_GEN moves on every
    mutation - together they change iff the body's rows could have. The
    kpis/last_checked blocks riding in the body may lag one rows-refresh
    behind; both are advisory displays the UI already treats as eventually
    consistent."""
    ent = _ROWS_CACHE.get((status, limit))
    rows_at = ent["at"] if ent else 0.0
    return f"{status}|{limit}|{rows_at}|{_CACHE_GEN[0]}"


def queue_response(params, accept_gzip: bool):
    """Memoized, single-flighted serialize/gzip for GET /api/setter/queue.

    The JSON is byte-identical to route_queue_get() - this only stops the
    multi-MB serialize+gzip from being re-run per concurrent caller, which is
    the boot burst that crash-looped the Render instance. At most ONE big
    serialization runs process-wide (the global lock), and identical fetches
    within the SWR window share the built buffer. route_queue_get() stays the
    source of truth (the unit tests call it directly).

    Returns (status, content_encoding_or_None, body_bytes).
    """
    import gzip
    status_q = _qp(params, "status", "")
    before_q = _qp(params, "before", "")
    try:
        limit = max(1, min(int(_qp(params, "limit", "200") or 200), 500))
    except (ValueError, TypeError):
        limit = 200
    # Full-trim (owner ask 2026-07-29): only the UI's own shape
    # (needs_review, limit 200) is memoized — odd limits joined the pill path
    # 2026-08-01 so a query-string fan-out can't mint memo entries or pay the
    # discarded pre-lock warm. Pills build fresh on their rare click, but
    # single-flighted (panel fix 2026-07-30, H7) and BOUNDED (2026-08-01):
    # one slow "All" build must not serially pin every pill click forever.
    # An infinite-scroll cursor (?before=…) ALWAYS takes this fresh path too
    # (2026-08-17): older pages are one-shot reads, never memoized/cached.
    if before_q or status_q != "needs_review" or limit != 200:
        if not _PILL_BUILD_LOCK.acquire(timeout=10.0):
            return 503, None, json.dumps({"error": "That view is busy building - retry in a moment."}).encode()
        try:
            st, body = route_queue_get(params)
            raw = json.dumps(body).encode()
            if st != 200:
                return st, None, raw
            gz = gzip.compress(raw, 1 if len(raw) > 262144 else 6)
        finally:
            _PILL_BUILD_LOCK.release()
        if accept_gzip and len(raw) >= 512:
            return 200, "gzip", gz
        return 200, None, raw
    # Warm the rows cache OUTSIDE the global lock so the (rare) cold Supabase
    # fetch never blocks other queue responses; the lock then guards CPU only.
    if _SB:
        try:
            _queue_rows_cached(status_q, limit)
        except Exception:  # noqa: BLE001 - route_queue_get repeats the read + handles errors
            pass
    # fields is deliberately NOT in the memo key (panel fix, #9): the slim
    # select made fields=list and the default byte-identical, and two keys
    # doubled the buffer memory for nothing.
    memo_key = (status_q, limit)
    etag = _queue_resp_etag(status_q, limit)
    ent = _QUEUE_RESP_MEMO.get(memo_key)
    fresh = ent and ent[0] == etag and (_time.time() - ent[3]) <= _QUEUE_RESP_TTL
    over_ceiling = ent and (_time.time() - ent[3]) > _QUEUE_RESP_MAX_STALE_S
    if ent and not fresh and not over_ceiling:
        # SWR (502 fix 2026-07-30): a stale buffer exists - serve it NOW and
        # rebuild in the background. The old behaviour rebuilt synchronously
        # under the global lock (multi-MB fetch + dumps + gzip on 0.5 CPU),
        # which is exactly the request that outlived the proxy timeout or
        # starved /healthz right after a mutation bust.
        _kick_queue_resp_rebuild(memo_key)
    if not ent and restore_queue_memo_from_store():
        # A request beat _boot_warmup to a fresh process: the persisted
        # buffer from before the restart serves NOW, and the SWR kick below
        # rebuilds truth off the request path — no cold inline build.
        ent = _QUEUE_RESP_MEMO.get(memo_key)
        if ent:
            _kick_queue_resp_rebuild(memo_key)
    if not ent or over_ceiling:
        # Cold boot (no buffer), or the buffer aged past the hard ceiling
        # (panel fix, F1/H3: background rebuilds can fail silently - lock
        # busy, fetch error - and without a wall-clock bound the inbox could
        # serve one snapshot forever). One inline build restores truth.
        # Bounded acquire (panel fix 2026-08-01): a blocking wait here held
        # every request behind one slow Supabase build — once the ceiling
        # forced this path, that was a thread pile-up and a 502 storm.
        # Timing out serves the stale buffer (truth is already rebuilding
        # under the holder). On a TRUE cold boot (no buffer at all) there is
        # nothing stale to serve, so waiting on the one builder beats an
        # instant 503 the client would only retry once — hence the longer
        # bound when ent is None (20s: a real build lands well inside it,
        # and it stays under the client's own 25s abort so the honest 503
        # reaches the retry path instead of dying as a network error).
        got_lock = _QUEUE_RESP_LOCK.acquire(timeout=2.0 if ent else 20.0)
        if not got_lock:
            if ent:
                raw_len, gz = ent[1], ent[2]
                if accept_gzip and raw_len >= 512:
                    return 200, "gzip", gz
                return 200, None, gzip.decompress(gz)
            return 503, None, json.dumps({"error": "The queue is warming up - retry in a moment."}).encode()
        try:
            # Recompute INSIDE the lock (panel fix 2026-08-01): comparing a
            # peer's post-build etag against our pre-lock snapshot made every
            # queued waiter rebuild whenever anything moved mid-build.
            etag = _queue_resp_etag(status_q, limit)
            ent = _QUEUE_RESP_MEMO.get(memo_key)   # a peer may have built it while we waited
            if not (ent and ent[0] == etag and (_time.time() - ent[3]) <= _QUEUE_RESP_TTL):
                gen0 = _CACHE_GEN[0]
                st, body = route_queue_get(params)
                if st != 200:
                    # A failed build with a stale buffer on hand: serve the
                    # buffer and re-arm the ceiling, so every next request
                    # doesn't burn the acquire timeout on the same failure
                    # (panel fix 2026-08-01). True cold boot: honest error.
                    if ent:
                        print(f"[setter] queue build failed ({st}) - serving stale buffer", file=sys.stderr)
                        _QUEUE_RESP_MEMO[memo_key] = (ent[0], ent[1], ent[2], _time.time())
                        raw_len, gz = ent[1], ent[2]
                        if accept_gzip and raw_len >= 512:
                            return 200, "gzip", gz
                        return 200, None, gzip.decompress(gz)
                    return st, None, json.dumps(body).encode()
                raw = json.dumps(body).encode()
                # Level policy mirrors _json: past ~256KB, level 1 compresses
                # JSON nearly as well at a fraction of the CPU.
                gz = gzip.compress(raw, 1 if len(raw) > 262144 else 6)
                if not _queue_body_cacheable(body):
                    # Incoherent cold blip only (rows empty while KPIs still
                    # show a backlog) - never memoize it. A GENUINELY empty
                    # inbox (KPIs agree) memoizes normally (panel fix, F1).
                    # With a last-good buffer on hand, serve THAT instead of
                    # blanking this one user's inbox with the incoherent body,
                    # and re-arm the ceiling — loudly, so a persistent
                    # incoherence is visible instead of a silent freeze
                    # (panel fix 2026-08-01).
                    if ent:
                        print("[setter] queue build incoherent (rows [] vs KPI backlog) - "
                              "serving stale buffer", file=sys.stderr)
                        _QUEUE_RESP_MEMO[memo_key] = (ent[0], ent[1], ent[2], _time.time())
                        raw_len, gz2 = ent[1], ent[2]
                        if accept_gzip and raw_len >= 512:
                            return 200, "gzip", gz2
                        return 200, None, gzip.decompress(gz2)
                    # True cold boot with an incoherent build: nothing stale
                    # to serve — say so on stderr (its two siblings do).
                    print("[setter] cold-boot queue build incoherent (rows [] vs KPI backlog) "
                          "- serving unmemoized", file=sys.stderr)
                    if accept_gzip and len(raw) >= 512:
                        return 200, "gzip", gz
                    return 200, None, raw
                # Bound the memo: legit shapes number ~10 (pills x limits);
                # drop expired entries if an odd `limit` fan-out grows it.
                if len(_QUEUE_RESP_MEMO) > 32:
                    cutoff = _time.time() - _QUEUE_RESP_TTL
                    for k in [k for k, v in list(_QUEUE_RESP_MEMO.items())
                              if v[3] < cutoff]:
                        _QUEUE_RESP_MEMO.pop(k, None)
                # Etag stamped AFTER the build, with the same generation
                # guard as the background rebuild: raced bytes get a
                # deliberately-mismatching etag so SWR replaces them.
                etag_new = (_queue_resp_etag(status_q, limit)
                            if _CACHE_GEN[0] == gen0 else f"raced|{_CACHE_GEN[0]}")
                ent = (etag_new, len(raw), gz, _time.time())
                _QUEUE_RESP_MEMO[memo_key] = ent
                if (memo_key == ("needs_review", 200) and body.get("rows")
                        and not str(etag_new).startswith("raced")):
                    _persist_queue_resp(ent)
        finally:
            if got_lock:
                _QUEUE_RESP_LOCK.release()
    raw_len, gz = ent[1], ent[2]
    if accept_gzip and raw_len >= 512:
        return 200, "gzip", gz
    # Non-gzip clients (rare - browsers all send Accept-Encoding: gzip) get the
    # raw body back; storing only the compressed copy keeps the memo lean.
    return 200, None, gzip.decompress(gz)


def _queue_body_cacheable(body) -> bool:
    """False only for the incoherent cold blip: rows empty while the KPI block
    still reports a needs_review backlog (the _thread_rep_ids race). A body
    whose rows and KPIs AGREE - including a genuinely empty inbox - caches."""
    if not isinstance(body, dict):
        return False
    if body.get("rows"):
        return True
    kpis = body.get("kpis") or {}
    return not (kpis.get("needs_review") or 0)


def route_poll_status(_params):
    """GET /api/setter/poll/status - when the last reply-check FINISHED and
    what it found.

    Owner report 2026-07-25: "even when you click 'Check for new replies' it
    still doesn't show." The sweep is fire-and-forget on a background thread
    and a full tick (up to 15 replies, each a classify + draft round trip) runs
    far longer than the fixed 2.5s the button used to wait before reloading -
    so the reload landed BEFORE the new reply had been intaken, every time.
    The button now waits on this instead of a timer, and reports a real count.

    Deliberately uncached (unlike _last_poll_done_at, which rides on every
    queue GET): this is polled a handful of times per click and its whole job
    is to notice a change the moment it happens."""
    try:
        if not _SB:
            return 200, {"ok": True, "last_done": None, "summary": {}}
        rows = _SB("GET", "app_activity_log?action=in.(setter_poll_done,setter_poll_failed)"
                          "&order=ts.desc&limit=1&select=ts,action,payload")
        r = rows[0] if isinstance(rows, list) and rows else None
        if not isinstance(r, dict):
            return 200, {"ok": True, "last_done": None, "summary": {}}
        return 200, {"ok": True, "last_done": r.get("ts"), "action": r.get("action"),
                     "summary": r.get("payload") if isinstance(r.get("payload"), dict) else {}}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_queue_row_get(params):
    """GET /api/setter/queue/row?id=X - one full queue row by id, annotated
    exactly like the list rows (same _annotate_queue_row pass). Added for the
    unresolved-followup banner (owner ruling 2026-07-17: clicking an
    unresolved row must show the CONVERSATION): the banner can surface rows
    from any status tab, so the one clicked may not be in the client's
    currently loaded list. Workspace-scoped like every other queue read."""
    try:
        qid = _qp(params, "id", "")
        if not qid:
            return 400, {"error": "id is required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{quote(str(qid), safe='')}"
                          f"&{_list_ws_filter()}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        return 200, {"row": _annotate_queue_row(row)}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_queue_locate_get(params):
    """GET /api/setter/queue/locate?email=X&message_id=Y - resolve a chat
    permalink to its queue row. Keyed on lead_email + message_id because row
    ids don't survive re-intake. message_id is a REFINEMENT, not a gate: its
    time half is format-fluid across intake paths, so a miss falls back to
    the lead's most recent row rather than a dead link. One indexed select
    per attempt; workspace-scoped like every other queue read."""
    try:
        email = _qp(params, "email", "").strip().lower()
        mid = _qp(params, "message_id", "").strip()
        if not email:
            return 400, {"error": "email is required"}
        if not _SB:
            return 404, {"error": "Conversation not found."}
        row = None
        if mid:
            rows = _SB("GET", f"{QUEUE_TABLE}?lead_email=ilike.{quote(email, safe='')}"
                              f"&message_id=eq.{quote(mid, safe='')}"
                              f"&{_list_ws_filter()}&select=*&limit=1")
            row = rows[0] if isinstance(rows, list) and rows else None
        matched = "message_id" if row else "email"
        if not row:
            rows = _SB("GET", f"{QUEUE_TABLE}?lead_email=ilike.{quote(email, safe='')}"
                              f"&{_list_ws_filter()}&select=*"
                              f"&order=replied_at.desc.nullslast&limit=1")
            row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Conversation not found."}
        out = _annotate_queue_row(row)
        _attach_campaign_names([out])
        return 200, {"row": out, "matched": matched}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


# ── Smartlead-wide search (global-search ship 2026-08-15) ───────────────────
# The queue tables only hold conversations the setter INGESTED — a prospect
# who replied before the setter existed (or whose row was pruned) is
# unfindable from the search bar. These routes ask Smartlead ITSELF: one
# master-inbox page per enabled workspace (filters.search is Smartlead's own
# server-side match), each hit cross-referenced against setter_queue so the
# client can badge in-setter hits vs never-ingested ones. Read paths only.
_SL_SEARCH_CACHE = {}            # q(lower) -> (fetched_at, payload)
_SL_SEARCH_TTL = 120.0
_SL_SEARCH_CACHE_MAX = 50        # bound the map; queries are tiny but unbounded
_SL_SEARCH_WS_CACHE = {"at": 0.0, "keys": None}


def _sl_search_keys():
    """[(workspace_id, api_key)] for every enabled workspace, navreo first.
    Mirrors _enabled_workspace_ids but carries the KEY (that helper strips
    it); same 5-min cache + degrade-to-navreo-only failure shape."""
    now = _time.time()
    c = _SL_SEARCH_WS_CACHE
    if c["keys"] is not None and now - c["at"] < 300:
        return list(c["keys"])
    keys = []
    nav = _sl_key()
    if nav:
        keys.append(("navreo", nav))
    if SETTER_MONITOR_ALL_WS and _SB:
        try:
            rows = _SB("GET", "workspaces?select=id,api_key,status&order=added_at")
            for r in rows if isinstance(rows, list) else []:
                if not isinstance(r, dict):
                    continue
                wid = r.get("id")
                k = (r.get("api_key") or "").strip()
                if (wid and wid != "navreo" and wid not in _WS_MONITOR_SKIP and k
                        and (r.get("status") or "enabled") == "enabled"):
                    keys.append((wid, k))
        except Exception:  # noqa: BLE001 - a workspaces outage degrades to navreo-only search
            pass
    c.update(at=now, keys=keys)
    return list(keys)


def route_search_smartlead_get(params):
    """GET /api/setter/search-smartlead?q=… — search ALL of Smartlead for
    conversations matching q (name / email / company, matched by Smartlead's
    own master-inbox `search` filter), across every enabled workspace.
    Returns hits newest-reply-first, each carrying queue_id/queue_status when
    the conversation ALSO lives in the setter (any pill), so the client can
    route those opens through the normal full-control path and badge the rest
    "Not in setter". 120s cache per query; one 20-row page per workspace per
    miss — never an unbounded sweep (512MB box)."""
    try:
        q = _qp(params, "q", "").strip()
        if len(q) < 2:
            return 400, {"error": "q must be at least 2 characters"}
        ck = q.lower()
        now = _time.time()
        hit = _SL_SEARCH_CACHE.get(ck)
        if hit and now - hit[0] < _SL_SEARCH_TTL:
            return 200, dict(hit[1], cached=True)
        results, errors, seen = [], 0, set()
        # One short-lived thread per workspace (live measure 2026-08-15: the
        # serial loop cost 19.5s cold across the enabled workspaces — each
        # master-inbox search is ~5s on Smartlead's side). Bounded at the
        # workspace count (single digits), joined with a hard deadline so a
        # hung workspace can't pin the request thread on the 512MB box.
        ws_keys = _sl_search_keys()
        pages = {}
        def _one(ws, key):
            try:
                pages[ws] = _sl_post("/master-inbox/inbox-replies", {
                    "limit": 20, "offset": 0, "sortBy": "REPLY_TIME_DESC",
                    "filters": {"emailStatus": "Replied", "search": q},
                }, api_key=key)
            except Exception:  # noqa: BLE001 - one workspace failing must not kill the search
                pages[ws] = None
        threads = [threading.Thread(target=_one, args=(ws, key), daemon=True,
                                    name=f"sl-search-{ws}") for ws, key in ws_keys]
        for t in threads:
            t.start()
        deadline = _time.time() + 25
        for t in threads:
            t.join(timeout=max(0.1, deadline - _time.time()))
        for ws, _key in ws_keys:
            try:
                resp = pages.get(ws)
                if resp is None:
                    errors += 1
                    continue
                data = resp.get("data") if isinstance(resp, dict) else None
                for r in data if isinstance(data, list) else []:
                    if not isinstance(r, dict):
                        continue
                    email = (r.get("lead_email") or "").strip().lower()
                    cid = r.get("email_campaign_id")
                    if not email or not cid:
                        continue
                    k2 = (ws, str(cid), email)
                    if k2 in seen:
                        continue
                    seen.add(k2)
                    results.append({
                        "workspace": ws,
                        "lead_email": email,
                        "lead_first_name": r.get("lead_first_name") or r.get("first_name") or "",
                        "lead_last_name": r.get("lead_last_name") or r.get("last_name") or "",
                        "lead_name": r.get("lead_name") or "",
                        "smartlead_campaign_id": cid,
                        "campaign_name": r.get("campaign_name") or r.get("email_campaign_name") or "",
                        "smartlead_lead_id": r.get("email_lead_id"),
                        "last_reply_time": r.get("last_reply_time"),
                        "subject": r.get("email_subject") or r.get("subject") or "",
                        "queue_id": None, "queue_status": None,
                    })
            except Exception:  # noqa: BLE001 - one workspace failing must not kill the search
                errors += 1
        results.sort(key=lambda r: str(r.get("last_reply_time") or ""), reverse=True)
        results = results[:40]
        # Cross-ref the setter queue in ONE indexed select: newest row per
        # (campaign, email) wins, bare-email fallback mirrors /queue/locate.
        if results and _SB:
            try:
                emails = sorted({r["lead_email"] for r in results})
                inlist = ",".join(quote(e, safe="") for e in emails)
                qrows = _SB("GET", f"{QUEUE_TABLE}?lead_email=in.({inlist})"
                                   f"&{_list_ws_filter()}"
                                   f"&select=id,lead_email,status,smartlead_campaign_id,replied_at"
                                   f"&order=replied_at.desc.nullslast&limit=200")
                by_convo, by_email = {}, {}
                for qr in qrows if isinstance(qrows, list) else []:
                    if not isinstance(qr, dict):
                        continue
                    em = (qr.get("lead_email") or "").strip().lower()
                    by_convo.setdefault(f"{qr.get('smartlead_campaign_id')}|{em}", qr)
                    by_email.setdefault(em, qr)
                for r in results:
                    qr = (by_convo.get(f"{r['smartlead_campaign_id']}|{r['lead_email']}")
                          or by_email.get(r["lead_email"]))
                    if qr:
                        r["queue_id"] = qr.get("id")
                        r["queue_status"] = qr.get("status")
            except Exception:  # noqa: BLE001 - cross-ref is best-effort; hits still render un-badged
                pass
        payload = {"q": q, "results": results, "errors": errors}
        if len(_SL_SEARCH_CACHE) >= _SL_SEARCH_CACHE_MAX:
            _SL_SEARCH_CACHE.clear()
        # A partial answer (a workspace call failed/timed out) must never be
        # cached — live find 2026-08-15: a transient one-workspace failure got
        # served as "0 results" for the full TTL, which reads as "this person
        # was never contacted". Serve it once, let the next keystroke retry.
        if not errors:
            _SL_SEARCH_CACHE[ck] = (now, payload)
        return 200, payload
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_smartlead_thread_get(params):
    """GET /api/setter/smartlead-thread?campaign_id=X&email=Y — full Smartlead
    conversation for a search hit with NO queue row. Read-only by design: the
    client renders these with zero send/approve controls (never-send rail),
    and nothing here writes anywhere. hydrate_lead resolves the OWNING
    workspace's key via campaign_id, same as every queue-row hydrate."""
    try:
        cid = _qp(params, "campaign_id", "").strip()
        email = _qp(params, "email", "").strip()
        if not cid or not email:
            return 400, {"error": "campaign_id and email are required"}
        ok, hyd, herr = hydrate_lead(cid, email, "")
        if not ok:
            return 502, {"error": herr or "Couldn't load the Smartlead conversation."}
        return 200, {"thread": hyd.get("thread") or []}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _kick_thread_rehydrate(row: dict):
    """Live-refresh one row's thread OFF the request path (cache-first open,
    2026-07-30). Per-row single-flight; the refreshed thread persists via the
    normal _apply_patch (whose no-change guard means an already-current
    thread costs zero cache busts). The next open serves the refreshed copy."""
    rid = row.get("id")
    with _THREAD_REFRESH_LOCK:
        if rid in _THREAD_REFRESH_INFLIGHT:
            return
        # Per-row hydrate throttle: the client now calls /thread on EVERY open
        # (the read is one indexed select - cheap), so the 2-Smartlead-call
        # refresh behind it must self-limit or rapid row-browsing spawns a
        # hydrate burst - the exact class of load that used to OOM the box.
        last = _THREAD_REFRESH_LAST.get(rid, 0.0)
        if _time.time() - last < _THREAD_REFRESH_MIN_S:
            return
        _THREAD_REFRESH_LAST[rid] = _time.time()
        if len(_THREAD_REFRESH_LAST) > 2000:   # bound the map across re-intakes
            cutoff = _time.time() - 3600
            for k in [k for k, v in list(_THREAD_REFRESH_LAST.items()) if v < cutoff]:
                _THREAD_REFRESH_LAST.pop(k, None)
        _THREAD_REFRESH_INFLIGHT.add(rid)

    def run():
        try:
            mid = row.get("message_id") or row.get("source_message_id") or ""
            ok, hyd, _err = hydrate_lead(row.get("smartlead_campaign_id"),
                                         row.get("lead_email"), mid)
            if ok:
                thread = hyd.get("thread") or []
                if thread:
                    _apply_patch(row, {"thread": thread})
        except Exception:  # noqa: BLE001 - background refresh must never raise
            pass
        finally:
            with _THREAD_REFRESH_LOCK:
                _THREAD_REFRESH_INFLIGHT.discard(rid)
    threading.Thread(target=run, daemon=True, name="setter-thread-refresh").start()


_LIGHT_SCAN_LOCK = threading.Lock()
_THREAD_REFRESH_LOCK = threading.Lock()
_THREAD_REFRESH_INFLIGHT: set = set()
_THREAD_REFRESH_LAST: dict = {}    # row id -> last background-hydrate kick
_THREAD_REFRESH_MIN_S = 90.0


def route_thread_get(params):
    """Thread for one queue row - CACHE-FIRST (perf ruling 2026-07-30).

    Every intake path (process_reply / agentless / uncategorised, plus the
    3-minute reply-sync) already persists the full normalized thread into
    setter_queue.thread the moment a reply lands. Opening a conversation used
    to ignore that and pay 2 serial Smartlead round trips (60s timeouts) per
    open - the 'history takes way too long' report. Now: serve the stored
    snapshot immediately and kick the live Smartlead re-hydrate onto a
    background thread; the open after a refresh (or the client's follow-up
    poll) picks up anything new. The owner ruling 2026-07-15 ('an opened
    thread must show the latest emails') is honoured by the background
    refresh + the client's stale re-poll, not by blocking the paint.

    ?live=1 forces the old synchronous hydrate (explicit refresh / tests).
    Test rows return their stored thread untouched, as before."""
    try:
        from urllib.parse import quote as _q
        qid = _qp(params, "id", "")
        if not qid:
            return 400, {"error": "id is required"}
        # Federated scope + quoted id: the LIST shows every enabled workspace,
        # so the per-row read must too — a navreo-only pin here 404'd every
        # client-workspace conversation open (the 'history doesn't work on
        # client conversations' report).
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{_q(str(qid), safe='')}"
                          f"&{_list_ws_filter()}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        if row.get("is_test"):
            return 200, {"thread": row.get("thread") or [], "refreshed": False, "cached": True}
        stored = row.get("thread") or []
        want_live = _qp(params, "live", "") == "1"
        if stored and not want_live:
            _kick_thread_rehydrate(row)
            return 200, {"thread": stored, "refreshed": False, "cached": True, "stale": True}
        # No stored snapshot (legacy row) or an explicit live ask: hydrate inline.
        mid = row.get("message_id") or row.get("source_message_id") or ""
        ok, hyd, herr = hydrate_lead(row.get("smartlead_campaign_id"), row.get("lead_email"), mid)
        if not ok:
            # Stale beats broken: hand back the stored snapshot with the why.
            return 200, {"thread": stored, "refreshed": False, "cached": True, "detail": herr}
        thread = hyd.get("thread") or []
        try:
            _apply_patch(row, {"thread": thread})
        except Exception:  # noqa: BLE001 - persisting is best-effort; the response is what matters
            pass
        return 200, {"thread": thread, "refreshed": True}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


# ---- Warm-call sideboard enrichment (owner ask 2026-08-15) -----------------
# A fresh reply is enriched ONCE (phone + company facts), cached forever in
# setter_lead_enrichment so a lead is never paid for twice. Provider order:
# GetLeads when a server key exists (none today - GetLeads is OAuth-MCP only,
# the adapter is dormant until GETLEADS_API_URL/KEY land in the env), then
# Prospeo /enrich-person - the exact call the Make positive-reply scenario
# already pays for on this same event, so server-side is cost-neutral.
_ENRICH_INFLIGHT: set = set()     # emails currently enriching (thread guard)


def _enrichment_row(email: str):
    """The lead's cached enrichment row, or None. A row EXISTing (even with
    an empty phone) means we already tried - never re-spend on that lead."""
    try:
        rows = _SB("GET", "setter_lead_enrichment"
                          f"?lead_email=eq.{quote((email or '').lower(), safe='')}&limit=1") if _SB else None
        return rows[0] if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001
        return None


def _company_row(domain: str) -> dict:
    try:
        if not domain:
            return {}
        rows = _SB("GET", f"companies?domain=eq.{quote(domain.lower(), safe='')}"
                          "&select=domain,name,description,employee_count,employee_range,"
                          "city,state,country,industry,linkedin_url&limit=1") if _SB else None
        return rows[0] if isinstance(rows, list) and rows else {}
    except Exception:  # noqa: BLE001
        return {}


_CLIENT_CTX_CACHE: dict = {}      # client slug -> (fetched_at, row)
_CLIENT_CTX_TTL = 300.0
_CLIENT_SLUG_CACHE: dict = {}     # campaign_id -> (fetched_at, slug)


def _client_slug_for(campaign_id, workspace) -> str:
    """ Which CLIENT a row belongs to (owner fix 2026-08-17: the fold said
    'About Navreo' on every navreo-workspace row, but Amplifyy/Arnic/etc
    campaigns live INSIDE that workspace). A federated client workspace IS
    the client; navreo rows resolve through campaign_scorecard.client - the
    one label authority - mirroring the UI's clientForRow()."""
    ws = (workspace or WORKSPACE or "navreo").lower()
    if ws != "navreo":
        return ws
    if not (campaign_id and _SB):
        return "navreo"
    key = str(campaign_id)
    now = _time.time()
    hit = _CLIENT_SLUG_CACHE.get(key)
    if hit and (now - hit[0]) < 600:
        return hit[1]
    slug = "navreo"
    try:
        rows = _SB("GET", f"campaign_scorecard?smartlead_campaign_id=eq.{quote(key, safe='')}"
                          "&select=client&limit=1")
        c = str((rows[0].get("client") or "")).strip() if isinstance(rows, list) and rows else ""
        if c and c != "__unassigned":
            slug = c.lower()
    except Exception:  # noqa: BLE001 - unknown campaign just reads as Navreo
        pass
    _CLIENT_SLUG_CACHE[key] = (now, slug)
    return slug


def _client_context(slug: str) -> dict:
    ws = (slug or "navreo").lower()
    now = _time.time()
    hit = _CLIENT_CTX_CACHE.get(ws)
    if hit and (now - hit[0]) < _CLIENT_CTX_TTL:
        return hit[1]
    row = {}
    try:
        rows = _SB("GET", f"setter_client_context?workspace=eq.{quote(ws, safe='')}&limit=1") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else {}
    except Exception:  # noqa: BLE001
        row = {}
    _CLIENT_CTX_CACHE[ws] = (now, row)
    return row


def _headcount_number(comp: dict):
    """Best headcount as an int: employee_count, else the employee_range
    midpoint ('11-50' -> 30). None when the company holds neither."""
    try:
        if comp.get("employee_count"):
            return int(comp["employee_count"])
        rng = str(comp.get("employee_range") or "")
        nums = [int(n) for n in re.findall(r"\d+", rng.replace(",", ""))]
        if len(nums) >= 2:
            return (nums[0] + nums[1]) // 2
        if nums:
            return nums[0]
    except Exception:  # noqa: BLE001
        pass
    return None


def _qualify(comp: dict, icp: dict, title: str = ""):
    """(verdict, reason) for the sidebar chip: likely / unlikely / unknown.
    Considers the WHOLE profile - the replier's role plus company size, geo
    and industry (owner redesign 2026-08-17). Plain-English reason, always."""
    if not isinstance(icp, dict) or not icp:
        return "unknown", "No qualification rules saved for this client yet."
    hc = _headcount_number(comp or {})
    country = str((comp or {}).get("country") or "").strip()
    industry = str((comp or {}).get("industry") or "").strip()
    title = str(title or "").strip()
    knew_anything = False
    roles = [str(r).lower() for r in (icp.get("roles") or []) if str(r).strip()]
    if roles and title:
        knew_anything = True
        if not any(r in title.lower() for r in roles):
            return "unlikely", f"A {title} replied - not the buyer this client usually sells to."
    countries = [str(c).lower() for c in (icp.get("countries") or [])]
    if countries and country:
        knew_anything = True
        if country.lower() not in countries:
            return "unlikely", f"Based in {country} - not a target market for this client."
    # Per-market headcount floor (owner ICP 2026-08-17: Navreo takes 10+
    # staff anywhere, but 2+ from the US/UK/Netherlands/Germany) - matched
    # by substring so "United States of America" still hits "united states".
    lo, hi = icp.get("headcount_min"), icp.get("headcount_max")
    floors = icp.get("headcount_min_by_country")
    if country and isinstance(floors, dict):
        cl = country.lower()
        for k, v in floors.items():
            if str(k).lower() in cl:
                lo = v
                break
    if hc is not None and (lo or hi):
        knew_anything = True
        if lo and hc < int(lo):
            return "unlikely", f"~{hc} staff - under this client's {lo}-person floor for {country or 'their market'}."
        if hi and hc > int(hi):
            return "unlikely", f"~{hc} staff - bigger than this client usually sells to (cap {hi})."
    industries = [str(i).lower() for i in (icp.get("industries") or [])]
    if industries and industry:
        knew_anything = True
        if not any(t in industry.lower() for t in industries):
            return "unlikely", f"{industry} - not a target industry for this client."
    if not knew_anything:
        return "unknown", "Not enough company data yet to judge fit."
    bits = []
    if roles and title:
        bits.append(f"a {title} replied")
    if hc is not None:
        bits.append(f"~{hc} staff fits the {lo or 1}-{hi or 'any'} range" if hi
                    else f"~{hc} staff clears the {lo or 1}+ floor")
    if country:
        bits.append(f"based in {country}")
    line = ", ".join(bits)
    return "likely", ((line[0].upper() + line[1:]) if line else "Matches this client's saved rules") + "."


def _prospeo_enrich(email: str, linkedin: str = "") -> dict:
    """One Prospeo /enrich-person call (mobile on) -> normalised
    {phone, phone_source, company{...}, payload}. Empty dict on any miss -
    the caller banks even a miss so the lead is never re-paid. Auth header is
    X-KEY (verified live 2026-08-15 - the docs' KEY name 400s INVALID_API_KEY).
    A linkedin_url matches far more reliably than a bare email, so pass the
    people table's slug whenever we hold one - mirrors the Make scenario."""
    key = _KEYS.get("PROSPEO_API_KEY") or ""
    if not (key and (email or linkedin) and _HTTP):
        return {}
    data = {"linkedin_url": linkedin} if linkedin else {"email": email}
    try:
        j = _HTTP("POST", "https://api.prospeo.io/enrich-person", {"X-KEY": key},
                  {"enrich_mobile": True, "data": data}, timeout=45)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(j, dict):
        return {}
    body = j.get("response") if isinstance(j.get("response"), dict) else j
    person = body.get("person") if isinstance(body.get("person"), dict) else {}
    comp = body.get("company") if isinstance(body.get("company"), dict) else {}
    mob = person.get("mobile")
    phone = ""
    if isinstance(mob, dict):
        phone = str(mob.get("mobile") or mob.get("number") or "").strip()
    elif mob:
        phone = str(mob).strip()
    # Live shape (verified 2026-08-15): company.location is an OBJECT, the
    # richest description is description > description_ai > description_seo,
    # and the person carries their own location - used as the fallback so the
    # Location line still answers "where would I be calling?".
    loc = comp.get("location") if isinstance(comp.get("location"), dict) else {}
    ploc = person.get("location") if isinstance(person.get("location"), dict) else {}
    if isinstance(comp.get("location"), str) and comp["location"].strip():
        loc = {"city": comp["location"].strip()}
    if isinstance(person.get("location"), str) and person["location"].strip():
        ploc = {"city": person["location"].strip()}
    company = {
        "name": comp.get("name") or "",
        "description": comp.get("description") or comp.get("description_ai")
                       or comp.get("description_seo") or "",
        "employee_count": comp.get("employee_count") or comp.get("employee_count_on_prospeo") or None,
        "employee_range": comp.get("employee_range") or "",
        "city": loc.get("city") or loc.get("locality") or ploc.get("city") or "",
        "state": loc.get("state") or loc.get("region") or ploc.get("state") or ploc.get("region") or "",
        "country": loc.get("country") or ploc.get("country") or "",
        "industry": comp.get("industry") or "",
        "linkedin_url": comp.get("linkedin_url") or comp.get("linkedin") or "",
    }
    return {"phone": phone, "phone_source": "prospeo" if phone else "",
            "company": company, "payload": body}


def _getleads_enrich(email: str) -> dict:
    """GetLeads adapter - DORMANT: GetLeads has no public HTTP API today
    (OAuth MCP only). The moment GETLEADS_API_URL + GETLEADS_API_KEY appear
    in the env this slot goes first in the waterfall; shape mirrors
    _prospeo_enrich's return."""
    base = (_KEYS.get("GETLEADS_API_URL") or "").rstrip("/")
    key = _KEYS.get("GETLEADS_API_KEY") or ""
    if not (base and key and email and _HTTP):
        return {}
    try:
        j = _HTTP("POST", f"{base}/enrich-person", {"Authorization": f"Bearer {key}"},
                  {"email": email, "include_phone": True}, timeout=45)
        if not isinstance(j, dict):
            return {}
        person = j.get("person") if isinstance(j.get("person"), dict) else j
        comp = j.get("company") if isinstance(j.get("company"), dict) else {}
        phone = str(person.get("phone") or person.get("mobile") or "").strip()
        return {"phone": phone, "phone_source": "getleads" if phone else "",
                "company": {k: comp.get(k) for k in ("name", "description", "employee_count",
                                                     "employee_range", "city", "state",
                                                     "country", "industry", "linkedin_url")},
                "payload": j}
    except Exception:  # noqa: BLE001
        return {}


def _enrich_on_reply(email: str, domain: str, workspace: str) -> None:
    """Daemon-thread body: enrich ONE fresh replier, once ever. Writes the
    setter_lead_enrichment cache row (even on a miss - tried = never re-pay),
    fills the companies row's empty facts, and pops the lead-contact cache so
    the sidebar's next open sees the new data. Never raises."""
    try:
        email = (email or "").strip().lower()
        if not (email and _SB) or email in _ENRICH_INFLIGHT:
            return
        _ENRICH_INFLIGHT.add(email)
        try:
            if _enrichment_row(email):
                return
            # A LinkedIn profile matches far more reliably than a bare email
            # (a bare contact@ NO_MATCHes) - use the people table's slug when
            # we hold one, exactly like the Make scenario does.
            linkedin = ""
            try:
                ppl = _SB("GET", f"people?email=eq.{quote(email, safe='')}"
                                 "&select=linkedin_slug&limit=1")
                slug = (ppl[0].get("linkedin_slug") or "").strip().strip("/") \
                    if isinstance(ppl, list) and ppl else ""
                if slug:
                    linkedin = slug if slug.startswith("http") \
                        else f"https://www.linkedin.com/in/{slug}"
            except Exception:  # noqa: BLE001
                pass
            res = _getleads_enrich(email) or _prospeo_enrich(email, linkedin)
            comp = res.get("company") or {}
            # Bank real attempts only: a NO_MATCH is a real miss (never re-pay),
            # but an auth/credit/network failure must NOT poison the cache -
            # the next open retries once the infrastructure is fixed.
            payload = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            err = str(payload.get("error_code") or "") if payload.get("error") else ""
            if not res or (err and err != "NO_MATCH"):
                return
            _SB("POST", "setter_lead_enrichment?on_conflict=lead_email", {
                "lead_email": email, "phone": res.get("phone") or "",
                "phone_source": res.get("phone_source") or "",
                "company_domain": (domain or "").lower(),
                "payload": res.get("payload"),
            }, prefer="resolution=merge-duplicates,return=minimal")
            if domain and any(v for v in comp.values()):
                _SB("POST", "companies?on_conflict=domain", {
                    "domain": domain.lower(),
                    **{k: v for k, v in comp.items() if v},
                }, prefer="resolution=merge-duplicates,return=minimal")
            for k in [k for k in _LEAD_CONTACT_CACHE if k[0] == email]:
                _LEAD_CONTACT_CACHE.pop(k, None)
        finally:
            _ENRICH_INFLIGHT.discard(email)
    except Exception:  # noqa: BLE001 - enrichment is a nice-to-have, never a crash
        pass


_LEAD_CONTACT_CACHE = {}          # email(lower) -> (fetched_at, {linkedin, website, ...})
_LEAD_CONTACT_TTL = 3600.0        # a lead's profile/website changes ~never; 1h cache


def route_lead_contact_get(params):
    """GET /api/setter/lead-contact?id=<queue_id> - the lead's personal
    LinkedIn, real company website, and Smartlead conversation id for the
    sidebar's quick links (owner ask 2026-07-28: Website linked the freemail
    domain, LinkedIn fell back to a name search, Smartlead opened a generic
    search view).

    Two sources, merged: Supabase `people` (linkedin_slug + the REAL
    company_domain - even a gmail lead knows its bohoplume.pl there) and
    Smartlead `/leads/` (stored linkedin_profile/website, plus
    `lead_campaign_data[].campaign_lead_map_id` for THIS campaign - the id
    the master inbox's ?leadMap= deep link opens directly, verified against
    the master-inbox bundle 2026-07-28). Cached per email+campaign for an
    hour; test rows and unknown leads answer empty. Never raises."""
    try:
        qid = _qp(params, "id", "")
        if not qid:
            return 400, {"error": "id is required"}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{quote(str(qid), safe='')}"
                          f"&{_list_ws_filter()}"
                          "&select=lead_email,is_test,smartlead_campaign_id,company_domain,workspace") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        email = (row.get("lead_email") or "").strip()
        campaign_id = row.get("smartlead_campaign_id")
        domain = (row.get("company_domain") or "").strip().lower()
        workspace = (row.get("workspace") or WORKSPACE or "navreo").lower()
        empty = {"linkedin": "", "website": "", "company_name": "", "phone": "", "lead_map": "",
                 "phone_kind": "", "person": {}, "company": {}, "qualified": {}, "client": {}}
        if not email or row.get("is_test"):
            return 200, empty
        now = _time.time()
        cache_key = (email.lower(), str(campaign_id or ""))
        cached = _LEAD_CONTACT_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _LEAD_CONTACT_TTL:
            return 200, cached[1]
        out = dict(empty)
        # Supabase first (free, no rate limit): the people table's slug is the
        # personal profile, and its company_domain is the enriched REAL domain.
        try:
            ppl = _SB("GET", f"people?email=eq.{quote(email.lower())}"
                             "&select=linkedin_slug,company_domain,title&limit=1") if _SB else None
            if isinstance(ppl, list) and ppl:
                title = (ppl[0].get("title") or "").strip()
                if title:
                    out["person"] = {"title": title}
                slug = (ppl[0].get("linkedin_slug") or "").strip().strip("/")
                if slug:
                    out["linkedin"] = slug if slug.startswith("http") \
                        else f"https://www.linkedin.com/in/{slug}"
                dom = (ppl[0].get("company_domain") or "").strip()
                if dom:
                    out["website"] = dom
        except Exception:  # noqa: BLE001 - Supabase miss just falls through to Smartlead
            pass
        try:
            resp = _sl_get("/leads/", {"email": email}, campaign_id=campaign_id)
            if isinstance(resp, dict):
                out["linkedin"] = out["linkedin"] or (resp.get("linkedin_profile") or "").strip()
                out["website"] = out["website"] or (resp.get("website") or "").strip()
                out["company_name"] = (resp.get("company_name") or "").strip()
                out["phone"] = str(resp.get("phone_number") or "").strip()
                # The conversation id: this lead's campaign_lead_map_id inside
                # THIS campaign (same one-call resolution _sl_lead_map_id_by_email
                # proved live 2026-07-17).
                for m in (resp.get("lead_campaign_data") or []):
                    if isinstance(m, dict) and str(m.get("campaign_id")) == str(campaign_id or ""):
                        out["lead_map"] = str(m.get("campaign_lead_map_id") or "")
                        break
        except Exception:  # noqa: BLE001 - a missing lookup just means no quick link
            pass
        # Warm-call facts (owner ask 2026-08-15): phone + company breakdown +
        # a Likely-qualified verdict + the client's own context, all from the
        # Supabase side. The enrichment cache outranks Smartlead's phone (the
        # Make pipeline's phones historically died in Folk, so Smartlead is
        # almost always blank); a lead with NO cache row yet gets a one-time
        # background enrichment kicked off right here, so rows that landed
        # before this shipped still fill in on first open.
        try:
            enr = _enrichment_row(email)
            if enr and (enr.get("phone") or "").strip():
                out["phone"] = str(enr["phone"]).strip()
                # Number type for the dial decision (SDR panel 2026-08-15):
                # prospeo/getleads numbers are provider-verified MOBILES; the
                # backfill sources are numbers on file, type unknown.
                out["phone_kind"] = "mobile" if (enr.get("phone_source") or "") in ("prospeo", "getleads") else "listed"
                # Freshness + provenance for the tooltip, and the rep-filed
                # disposition (connected / voicemail / bad) so a number one
                # rep learned is dead stops being vouched for (SDR panel
                # round 2, 2026-08-15).
                out["phone_meta"] = {
                    "source": enr.get("phone_source") or "",
                    "captured": str(enr.get("enriched_at") or "")[:10],
                    "status": enr.get("phone_status") or "",
                    "status_at": str(enr.get("phone_status_at") or "")[:10],
                }
            elif out.get("phone"):
                out["phone_kind"] = "listed"
            # The replier's role: the people table first, else whatever the
            # enrichment payload knows (Prospeo current_job_title/headline).
            if not (out.get("person") or {}).get("title") and isinstance((enr or {}).get("payload"), dict):
                pp = enr["payload"].get("person") if isinstance(enr["payload"].get("person"), dict) else {}
                ptitle = str(pp.get("current_job_title") or pp.get("headline") or "").strip()
                if ptitle:
                    out["person"] = {"title": ptitle[:120]}
            if enr is None:
                threading.Thread(target=_enrich_on_reply,
                                 args=(email, domain or (out.get("website") or ""), workspace),
                                 daemon=True).start()
            comp = _company_row(domain or (out.get("website") or ""))
            if comp:
                out["company"] = {
                    "name": comp.get("name") or out.get("company_name") or "",
                    "description": comp.get("description") or "",
                    "employee_count": comp.get("employee_count"),
                    "employee_range": comp.get("employee_range") or "",
                    "city": comp.get("city") or "", "state": comp.get("state") or "",
                    "country": comp.get("country") or "",
                    "industry": comp.get("industry") or "",
                    "linkedin_url": comp.get("linkedin_url") or "",
                }
            client_slug = _client_slug_for(campaign_id, workspace)
            # No fallback to the workspace row: an Amplifyy lead borrowing
            # Navreo's about/offer is exactly the wrong-client bug (owner,
            # 2026-08-17) - an honest empty fold beats the wrong pitch.
            ctx = _client_context(client_slug)
            icp = ctx.get("icp") if isinstance(ctx.get("icp"), dict) else {}
            verdict, reason = _qualify(comp or {}, icp, (out.get("person") or {}).get("title") or "")
            out["qualified"] = {"verdict": verdict, "reason": reason}
            out["client"] = {"label": ctx.get("client_label") or client_slug.title(),
                             "slug": client_slug,
                             "about": ctx.get("about") or "",
                             "offer": ctx.get("offer") or "",
                             "crm_url": ctx.get("crm_url") or ""}
        except Exception:  # noqa: BLE001 - warm-call extras never break quick links
            pass
        _LEAD_CONTACT_CACHE[cache_key] = (now, out)
        return 200, out
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_phone_status_post(payload):
    """POST /api/setter/phone-status {email, status} - the rep's one-tap call
    disposition (SDR panel 2026-08-15): connected | voicemail | bad | "" to
    clear. Written on the setter_lead_enrichment row (OUR table - never
    Smartlead), so a number a rep learned is dead stops being vouched for
    everywhere the sideboard renders it."""
    try:
        email = str((payload or {}).get("email") or "").strip().lower()
        status = str((payload or {}).get("status") or "").strip().lower()
        if not email:
            return 400, {"error": "email is required"}
        if status not in ("connected", "voicemail", "bad", ""):
            return 400, {"error": "status must be connected, voicemail, bad, or empty to clear"}
        if not _SB:
            return 503, {"error": "storage unavailable"}
        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        _SB("PATCH", f"setter_lead_enrichment?lead_email=eq.{quote(email, safe='')}",
            {"phone_status": status or None, "phone_status_at": now_iso if status else None})
        for k in [k for k in _LEAD_CONTACT_CACHE if k[0] == email]:
            _LEAD_CONTACT_CACHE.pop(k, None)
        return 200, {"ok": True, "status": status}
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


def _dismiss_conversation_siblings(row: dict):
    """Dismiss is a CONVERSATION verb, not a row verb (owner report
    2026-08-09: "dismissed conversations come back after a send/reload").
    Intake stores one row per inbound reply, so a thread accumulates sibling
    rows and only the read-time collapse hides the older ones — dismissing
    just the representative left its needs_review siblings alive in the
    table, and any collapse degrade (cold boot, scan contention right after
    a mutation busts the caches) resurrected the whole conversation. Sweep
    every still-open sibling of the same (workspace, campaign, lead, is_test)
    thread to dismissed. Best-effort: the representative's own patch already
    succeeded, so a failure here just leaves the old (collapse-shielded)
    behaviour."""
    try:
        em = str(row.get("lead_email") or "").strip()
        cid = row.get("smartlead_campaign_id")
        if not em or cid is None or not _SB:
            return
        _SB("PATCH",
            f"{QUEUE_TABLE}?workspace=eq.{row.get('workspace') or WORKSPACE}"
            f"&smartlead_campaign_id=eq.{cid}"
            f"&lead_email=eq.{quote(em, safe='')}"
            f"&is_test=eq.{'true' if row.get('is_test') else 'false'}"
            f"&status=in.(needs_review,new,error)",
            {"status": "dismissed"})
    except Exception as e:  # noqa: BLE001 - sweep is belt-and-braces, never fail the dismiss
        print(f"[setter] dismiss sibling-sweep failed for row {row.get('id')}: {e}",
              file=sys.stderr)


def route_queue_action(payload):
    try:
        payload = payload or {}
        # Coerce + quote once (panel fix, F7): qid comes straight from the
        # JSON body and was interpolated raw into PostgREST filters; every
        # row read/write below is also workspace-scoped now (the /thread
        # hardening covered only the read-only route).
        qid = quote(str(payload.get("id") or ""), safe="")
        action = payload.get("action")
        if not qid or not action:
            return 400, {"error": "id and action are required"}
        if action in ("send", "send_followup") and payload.get("async"):
            # Send-as-a-job (owner report 2026-07-28: "Couldn't send the reply:
            # Request failed (502)"). Same disease the redraft had: a send that
            # must re-hydrate a missing email_stats_id pages Smartlead inline
            # and the one open request can outlive the gateway, which answers
            # 502 while the mail often still goes out - the worst possible
            # ambiguity for a reviewer. The wrapper returns 202 + job_id
            # immediately and runs the EXACT same branch below in a worker;
            # clients poll the shared job-status route. Jobs share the redraft
            # store on purpose - one GC, one lock, one status route, and a job
            # lost to a restart resolves the same way (re-read the row, whose
            # status was patched before the job finished). Without "async" the
            # behaviour is byte-for-byte unchanged.
            inner = {k: v for k, v in payload.items() if k != "async"}
            job_id = uuid.uuid4().hex[:16]
            # Double-click / two-tab dedupe (2026-08-01): a second send START
            # for a row whose send job is still running JOINS that job — same
            # job_id back, one Smartlead post. The durable claim in
            # _send_reply covers what this process-local map can't (restarts,
            # a second instance); this map covers the START-burst window the
            # claim can't (both requests 202 before either worker runs).
            # Atomic check-and-claim (panel fix 2026-08-01): the old
            # check-then-set released the lock between the read and the
            # write, so two simultaneous STARTs could both see no entry and
            # both spawn workers. Any existing inflight entry is JOINED
            # unconditionally — the worker's finally-pop guarantees the
            # entry never outlives its job. The job entry is registered
            # BEFORE the inflight claim so a joiner can never poll an id the
            # status route doesn't know yet; the loser retracts its
            # provisional entry.
            with _REDRAFT_JOBS_LOCK:
                _redraft_jobs_gc()
                _REDRAFT_JOBS[job_id] = {"state": "running", "at": _time.time()}
            with _SEND_INFLIGHT_LOCK:
                existing = _SEND_INFLIGHT.get(qid)
                if existing is None:
                    _SEND_INFLIGHT[qid] = job_id
            if existing is not None:
                with _REDRAFT_JOBS_LOCK:
                    _REDRAFT_JOBS.pop(job_id, None)
                return 202, {"job_id": existing, "state": "running", "deduped": True}

            def _send_job_worker():
                try:
                    try:
                        status, body = route_queue_action(inner)
                    except Exception as e:  # noqa: BLE001 - a worker must never die silently
                        status, body = 500, {"error": str(e)[:300]}
                    # Result FIRST, then release the inflight slot — a joiner
                    # arriving between the two must find the finished job,
                    # never a gap that mints a second real send.
                    with _REDRAFT_JOBS_LOCK:
                        _REDRAFT_JOBS[job_id] = {"state": "done" if status == 200 else "error",
                                                 "status": status, "body": body, "at": _time.time()}
                finally:
                    with _SEND_INFLIGHT_LOCK:
                        if _SEND_INFLIGHT.get(qid) == job_id:
                            _SEND_INFLIGHT.pop(qid, None)
            threading.Thread(target=_send_job_worker, daemon=True,
                             name="setter-send").start()
            return 202, {"job_id": job_id, "state": "running"}
        if action == "dismiss":
            # One round-trip (perf ruling 2026-07-16): the old GET-then-PATCH
            # cost two sequential Supabase calls over keep-alive-less urllib.
            # return=representation makes the PATCH itself the existence check.
            updated = _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{qid}",
                          {"status": "dismissed"}, "return=representation") if _SB else None
            if isinstance(updated, list) and updated:
                _dismiss_conversation_siblings(updated[0])
                _bust_read_caches()
                return 200, {"ok": True, "status": "dismissed"}
            # The id missed - re-intake may have swapped it (owner bug
            # 2026-07-28: "Couldn't dismiss: Queue row not found" on a
            # tray-opened row). Re-resolve on the reply's identity, exactly
            # like every other action below, before giving up.
            ident = payload.get("identity")
            if isinstance(ident, dict):
                row = _existing_row(ident.get("workspace") or WORKSPACE,
                                    ident.get("smartlead_campaign_id"),
                                    str(ident.get("lead_email") or "").strip().lower(),
                                    str(ident.get("message_id") or ""))
                if row and row.get("id") is not None:
                    re_up = _SB("PATCH", f"{QUEUE_TABLE}?id=eq.{row['id']}",
                                {"status": "dismissed"}, "return=representation") if _SB else None
                    if isinstance(re_up, list) and re_up:
                        _dismiss_conversation_siblings(re_up[0])
                        _bust_read_caches()
                        return 200, {"ok": True, "status": "dismissed"}
            return 404, {"error": "Queue row not found."}
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            # A stale id is not a missing reply (owner bug 2026-07-28: "Couldn't
            # send the reply: Queue row not found"). Re-intake DELETES a queue
            # row and re-inserts it under a NEW id (see the re-categorise path),
            # so any tab open across that swap holds a dead id and every action
            # 404s even though the reply is sitting right there. The client
            # sends the reply's own identity alongside the id, so re-resolve on
            # it and act on the row that now carries this reply.
            ident = payload.get("identity")
            if isinstance(ident, dict):
                row = _existing_row(ident.get("workspace") or WORKSPACE,
                                    ident.get("smartlead_campaign_id"),
                                    str(ident.get("lead_email") or "").strip().lower(),
                                    str(ident.get("message_id") or ""))
        if not row:
            return 404, {"error": "Queue row not found."}
        def _sweep_followup_siblings(patch: dict, skip_decisions=("dismissed",)):
            """One conversation = ONE row everywhere (owner ruling 2026-08-15):
            a follow-up decision made on any reply-row applies to the whole
            thread — same workspace + campaign + lead email, status
            sent/auto_sent — so a resolved conversation can never resurface
            through an older sibling reply-row. Values in existing columns
            only (setter_queue is schema-frozen). Best-effort: a failed sweep
            never fails the action the reviewer actually took — the tray's
            read-time collapse hides siblings regardless, this just keeps the
            stored backlog honest. Siblings already enrolled
            (added_to_subsequence) or carrying a decision in skip_decisions
            keep their stronger/equal state."""
            try:
                email = str(row.get("lead_email") or "").strip()
                cid = row.get("smartlead_campaign_id")
                if not email or cid in (None, "") or not _SB or row.get("id") is None:
                    return
                wsq = (f"workspace=eq.{quote(str(row.get('workspace')), safe='')}"
                       if row.get("workspace") else _list_ws_filter())
                sibs = _SB("GET", f"{QUEUE_TABLE}?{wsq}"
                                  f"&smartlead_campaign_id=eq.{quote(str(cid), safe='')}"
                                  f"&lead_email=ilike.{quote(email, safe='')}"
                                  f"&status=in.(sent,auto_sent)"
                                  f"&id=neq.{quote(str(row['id']), safe='')}"
                                  f"&select=id,subsequence_decision,added_to_subsequence")
                for s in (sibs if isinstance(sibs, list) else []):
                    if not isinstance(s, dict) or s.get("id") is None:
                        continue
                    if s.get("added_to_subsequence") and not patch.get("added_to_subsequence"):
                        continue
                    if str(s.get("subsequence_decision") or "") in skip_decisions:
                        continue
                    _apply_patch(s, patch)
            except Exception:  # noqa: BLE001 - sweep is belt-and-braces, never the action
                pass

        if action == "subsequence":
            if _is_monitor_ws(row.get("workspace")):
                return 403, {"error": "This workspace is monitor-only — subsequence pushes write "
                                      "to the client's Smartlead and are disabled here."}
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
            _apply_patch(row, {"added_to_subsequence": True, "subsequence_decision": "pushed"})
            # The lead is enrolled per-campaign in Smartlead, so the mark is
            # factually true for every reply-row of this conversation.
            _sweep_followup_siblings({"added_to_subsequence": True, "subsequence_decision": "pushed"},
                                     skip_decisions=("dismissed", "pushed"))
            return 200, {"ok": True, "added_to_subsequence": True, "subsequence_id": sub_id, "detail": detail}
        if action == "subsequence_none":
            # Tray's "No follow-up needed" - a MARK, not a removal (owner ruling
            # 2026-07-22): the reviewer decided this sent row needs no follow-up
            # track, but it STAYS in the tray until explicitly dismissed. A row
            # already pushed stays pushed (this is a decision about whether to
            # push, not a way to undo one that already happened).
            if row.get("added_to_subsequence"):
                return 409, {"error": "This lead was already added to a subsequence."}
            _apply_patch(row, {"subsequence_decision": "none"})
            _sweep_followup_siblings({"subsequence_decision": "none"},
                                     skip_decisions=("dismissed", "pushed", "pushing", "none"))
            return 200, {"ok": True, "subsequence_decision": "none"}
        if action == "subsequence_dismiss":
            # The ONLY thing that removes a thread from the follow-up reminder
            # tray (owner ruling 2026-07-22). Leaves status/sent untouched - it
            # is a real sent reply; this only resolves the follow-up reminder.
            # IDEMPOTENT (owner report 2026-07-25: "when I dismiss some of the
            # conversations listed as sent without follow-up, it comes up with
            # this error and then it kind of restarts"). Dismissing a row that
            # is already dismissed - a double-click, a stale tray still showing
            # a row another tab resolved, a retry after a slow response - is
            # SUCCESS, not a 404/409. The tray reload that follows an error was
            # the "restart"; the honest answer is that the row is where the
            # reviewer wanted it.
            if row.get("subsequence_decision") == "dismissed":
                # Still sweep: the representative may have been dismissed in a
                # past life while older reply-rows kept resurfacing the thread
                # (the exact William case) — an idempotent re-dismiss is the
                # reviewer saying "this CONVERSATION is done".
                _sweep_followup_siblings({"subsequence_decision": "dismissed"})
                return 200, {"ok": True, "subsequence_decision": "dismissed", "already": True}
            _apply_patch(row, {"subsequence_decision": "dismissed"})
            _sweep_followup_siblings({"subsequence_decision": "dismissed"})
            return 200, {"ok": True, "subsequence_decision": "dismissed"}
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
            if row.get("status") == "sending":
                # An autosave landing mid-send would race the success patch on
                # draft_body AND refresh the claim's age, postponing the
                # reaper (panel fix 2026-08-01). The edit is not lost — the
                # client retries its debounced save after the send resolves.
                return 409, {"error": "This reply is being sent - the draft can't change right now."}
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
            if row.get("status") == "sending":
                return 409, {"error": "This reply is already being sent — wait for it to finish."}
            if _is_monitor_ws(row.get("workspace")):
                return 403, {"error": "This workspace is monitor-only (federation test) — "
                                      "sending is disabled here. Reply in Smartlead directly."}
            # No recency pre-check here: _send_reply verifies AFTER taking the
            # claim (atomic, one GET per send) and returns "blocked".
            agent = _load_agent(row.get("agent_id")) or {}
            subject = payload.get("subject_override") or row.get("draft_subject") or f"Re: {row.get('reply_subject') or ''}"
            body_html = payload.get("body_override") or row.get("draft_body") or ""
            original = row.get("original_draft_body") or ""
            result = _send_reply(row, agent, subject, body_html, is_test=bool(row.get("is_test")), success_status="sent")
            if result.get("blocked"):
                return 429, {"error": result["blocked"]}
            if result.get("ok"):
                # Owner ask 2026-07-17: rewriting the draft IS feedback. Only
                # a SUCCESSFUL send teaches - a reply that never left must not
                # change the brain. Fires after the send, in the background:
                # Approve returns the moment the mail is away, never waiting on
                # the learner's gpt-5-mini call (perf bar, 2026-07-16).
                _learn_from_edit_async(row, agent, original, body_html,
                                      training_on=bool(payload.get("training")))
                # Send-gate follow-up decision (owner spec 2026-07-17): only a
                # SUCCESSFUL send records one - a reply that never left must
                # not claim a follow-up decision was made. No "subsequence"
                # key at all (old clients, autopilot) leaves the decision NULL
                # exactly as before - the unresolved banner is what catches
                # those, not a forced choice at send time.
                # Owner ask 2026-07-25: "every time that I send a message in the
                # setter, it automatically gets opened in the Send Follow-Up
                # section, even if I've already selected a follow-up." A gate
                # choice IS the follow-up decision, so it must resolve the
                # reminder rather than land the row back in it:
                #   none -> 'none_at_send' (distinct from the tray's own 'none'
                #           MARK, which still stays put per 2026-07-22)
                #   push -> 'pushing' stamped SYNCHRONOUSLY, before the worker
                #           starts, so the tray reload that follows the send
                #           never catches the row mid-flight. The worker then
                #           moves it to 'pushed' or 'push_failed' as before.
                sub_choice = payload.get("subsequence")
                if isinstance(sub_choice, dict):
                    choice = sub_choice.get("choice")
                    if choice == "none":
                        _apply_patch(row, {"subsequence_decision": "none_at_send"})
                    elif choice == "push":
                        _apply_patch(row, {"subsequence_decision": "pushing"})
                        _subsequence_choice_async(row, sub_choice.get("sub_sequence_id"))
            out = {"ok": result.get("ok"), "row": {**row, **(result.get("row") or {})}}
            err = (result.get("row") or {}).get("error")
            if not result.get("ok") and err:
                out["error"] = err
            return 200, out
        if action == "send_followup":
            # A sent thread is not a closed thread (owner ask 2026-07-28):
            # another email can go into the same Smartlead thread, from the
            # same mailbox, any time after the reply went out. Guarded to
            # already-sent rows so Approve stays the one door for the FIRST
            # reply and its already-sent 409 protection stays intact.
            if row.get("status") not in ("sent", "auto_sent"):
                return 409, {"error": "This thread's reply hasn't been sent yet - use Approve for the first send."}
            if _is_monitor_ws(row.get("workspace")):
                return 403, {"error": "This workspace is monitor-only (federation test) — "
                                      "sending is disabled here. Reply in Smartlead directly."}
            body_html = payload.get("body") or ""
            if not _TAG_RE.sub(" ", body_html).strip():
                return 400, {"error": "body is required"}
            agent = _load_agent(row.get("agent_id")) or {}
            prev_status = row.get("status")
            subject = row.get("draft_subject") or f"Re: {row.get('reply_subject') or ''}"
            # is_followup declared (panel fix 2026-08-01): the follow-up's own
            # failure/blocked paths restore the sent status inside _send_reply,
            # its success is recorded as a thread entry (never clobbering the
            # first reply's record), and its recency gate counts THIS row's
            # own sends — a second follow-up inside the window answers 429.
            result = _send_reply(row, agent, subject, body_html,
                                 is_test=bool(row.get("is_test")), success_status=prev_status,
                                 is_followup=True)
            if result.get("blocked"):
                return 429, {"error": result["blocked"]}
            out = {"ok": result.get("ok"), "row": {**row, **(result.get("row") or {})}}
            err = (result.get("row") or {}).get("error")
            if not result.get("ok") and err:
                out["error"] = err
            return 200, out
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
        # Monitor guard (panel fix 2026-08-01, made fail-CLOSED same day): the
        # key-comparison version was fail-open — _sl_key_for swallows resolver
        # errors and answers the navreo key, so an unknown campaign or a
        # Supabase blip made both sides equal and the push proceeded. The
        # campaigns table is the workspace authority; no row, a non-navreo
        # row, or an unreadable table all refuse.
        if SETTER_MONITOR_ALL_WS:
            try:
                got = _SB("GET", f"campaigns?smartlead_campaign_id=eq.{quote(str(campaign_id), safe='')}"
                                 "&select=workspace&limit=1") if _SB else None
                ws = (got[0].get("workspace") if isinstance(got, list) and got
                      and isinstance(got[0], dict) else None)
            except Exception:  # noqa: BLE001 - unknown workspace means NO
                ws = None
            if (ws or "") != "navreo":
                return 403, {"error": "That campaign isn't confirmed as a Navreo-workspace campaign — "
                                      "subsequence pushes write to the owner's Smartlead and are "
                                      "refused without that confirmation."}
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


# ── redraft as a background job (owner report 2026-07-25: "whenever I try to
# regenerate a response from a blank, I get [502]") ────────────────────────
# A redraft on a row with no stored classification runs classify -> draft ->
# proofread back to back, three model round trips. Measured live on an 8KB
# reply: 25-42s, which sits right on the gateway's limit - a slow model call
# tips it over and the proxy answers 502 while the work is still running (and
# usually SUCCEEDS a moment later, so the reviewer sees an error over a draft
# that did get written). Long work does not belong in a request: the POST now
# starts a job and answers immediately, and the UI polls this for the result.
_REDRAFT_JOBS = {}
_REDRAFT_JOBS_LOCK = threading.Lock()
_REDRAFT_JOB_TTL = 900          # keep a finished job readable for 15 minutes


def _redraft_jobs_gc():
    """Drop finished jobs older than the TTL. In-memory by design - a job lost
    to a restart is recoverable, because _redraft_sync persists the draft to
    the row before it returns (the client re-reads the row in that case)."""
    now = _time.time()
    # RUNNING jobs survive the normal TTL (panel fix 2026-08-01): aging one
    # out while its worker still ran dropped the send-dedupe join target, so
    # a joiner minted a second job for a send that was still going out. A
    # hard ceiling (3x TTL, far above any real send) still reaps a job whose
    # worker died without writing a result, so the map can't leak forever.
    for jid in [k for k, v in _REDRAFT_JOBS.items()
                if now - (v.get("at") or 0) > _REDRAFT_JOB_TTL
                and (v.get("state") != "running"
                     or now - (v.get("at") or 0) > 3 * _REDRAFT_JOB_TTL)]:
        _REDRAFT_JOBS.pop(jid, None)


def _redraft_job_worker(job_id: str, payload: dict):
    # Result write in a finally (panel fix 2026-08-01): a BaseException
    # between the work and the write pinned the job at 'running' forever.
    status, body, state = 500, {"error": "the job died before writing a result"}, "error"
    try:
        status, body = _redraft_sync(payload)
        state = "done" if status == 200 else "error"
    except Exception as e:  # noqa: BLE001 - a worker must never take the thread down silently
        status, body, state = 500, {"error": str(e)[:300]}, "error"
        print(f"[setter] redraft job {job_id} crashed: {e}", file=sys.stderr)
    finally:
        with _REDRAFT_JOBS_LOCK:
            _REDRAFT_JOBS[job_id] = {"state": state, "status": status, "body": body,
                                     "at": _time.time()}


def route_redraft_status(params):
    """GET /api/setter/queue/redraft/status?job=<id> - state of a background
    redraft. An unknown id answers state="unknown" (not an error): the server
    may have restarted, and the caller's correct move is to re-read the row,
    whose draft was persisted before the job finished."""
    try:
        job_id = _qp(params, "job", "")
        if not job_id:
            return 400, {"error": "job is required"}
        with _REDRAFT_JOBS_LOCK:
            _redraft_jobs_gc()
            job = _REDRAFT_JOBS.get(job_id)
        if not job:
            return 200, {"state": "unknown"}
        if job.get("state") == "running":
            return 200, {"state": "running"}
        out = {"state": job.get("state"), "status": job.get("status")}
        out.update(job.get("body") or {})
        return 200, out
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def route_queue_redraft(payload):
    """POST /api/setter/queue/redraft. With {"async": true} this starts a job
    and returns 202 {"job_id": ...} immediately - see the note above. Without
    it, behaviour is byte-for-byte what it always was, so older clients and
    every existing test are unaffected."""
    payload = payload or {}
    if not payload.get("async"):
        return _redraft_sync(payload)
    if not payload.get("id"):
        return 400, {"error": "id is required"}
    job_id = uuid.uuid4().hex[:16]
    with _REDRAFT_JOBS_LOCK:
        _redraft_jobs_gc()
        _REDRAFT_JOBS[job_id] = {"state": "running", "at": _time.time()}
    threading.Thread(target=_redraft_job_worker, args=(job_id, payload),
                    daemon=True, name="setter-redraft").start()
    return 202, {"job_id": job_id, "state": "running"}


def _redraft_sync(payload):
    # Per-stage wall clock, surfaced in the job body so a slow regenerate can
    # be attributed without guessing (which call is it THIS time?). Cheap:
    # a handful of _time.time() reads on a path that costs seconds.
    stages, _t_start = {}, _time.time()

    def _stage(name, since):
        stages[name] = int((_time.time() - since) * 1000)
    try:
        payload = payload or {}
        qid = payload.get("id")
        if not qid:
            return 400, {"error": "id is required"}
        # Settings are independent of the row - fetch them in parallel with
        # the row+agent loads instead of paying a third serial Supabase round
        # trip (~300-600ms of a path with a hard 10s bar).
        _settings_box = {}

        def _settings_worker():
            try:
                _settings_box["v"] = _load_settings()
            except Exception:  # noqa: BLE001 - same degrade-to-empty the serial path had
                _settings_box["v"] = {}
        _settings_th = threading.Thread(target=_settings_worker, daemon=True,
                                        name="setter-settings")
        _settings_th.start()
        # The client already knows the row's agent (it rendered the row), so it
        # sends agent_hint and the agent doc loads in parallel with the row
        # instead of after it. The hint is only TRUSTED when the loaded row
        # confirms it - a stale/wrong hint falls back to the serial load.
        agent_hint = str(payload.get("agent_hint") or "") or None
        _agent_box = {}
        _agent_th = None
        if agent_hint:
            def _agent_worker():
                try:
                    _agent_box["v"] = _load_agent(agent_hint)
                except Exception:  # noqa: BLE001
                    _agent_box["v"] = None
            _agent_th = threading.Thread(target=_agent_worker, daemon=True,
                                         name="setter-agent-hint")
            _agent_th.start()
        _t = _time.time()
        rows = _SB("GET", f"{QUEUE_TABLE}?id=eq.{qid}&select=*") if _SB else None
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            return 404, {"error": "Queue row not found."}
        _stage("load_row", _t)
        _t = _time.time()
        if _agent_th and str(row.get("agent_id") or "") == agent_hint:
            _agent_th.join(timeout=10)
            agent = _agent_box.get("v") or {}
        else:
            agent = _load_agent(row.get("agent_id")) or {}
        _stage("load_agent", _t)
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
        _settings_th.join(timeout=10)
        settings = _settings_box.get("v") or {}
        classification = row.get("classification") or {}
        tz = row.get("timezone")
        # A stored timezone was already vetted at intake; only a fresh
        # resolve below can downgrade confidence.
        tz_confident = bool(tz)
        if not tz and classification:
            # Some intakes stored a classification but never stamped the row's
            # timezone, and this route only re-resolved when the classification
            # was missing too - so every Regenerate re-read the empty field,
            # skipped the Calendly lookup, and fell back to the availability
            # ask while real slots existed (owner report 2026-08-04, row 1435:
            # classification carried America/New_York at 0.9 the whole time).
            # Resolve exactly like intake - deterministic hints first, then the
            # stored guess - and persist below so one Regenerate heals the row.
            body_text = clean_body(row.get("reply_body") or "")
            domain = (row.get("company_domain") or "").lower()
            comp_hints = _company_hints(domain)
            hints = {"country": comp_hints.get("country"), "state": comp_hints.get("state"),
                     "city": comp_hints.get("city"), "phone": _extract_phone(body_text),
                     "tld": ".".join(domain.split(".")[-2:]) if domain else "", "body": body_text}
            tz, tz_confident = resolve_timezone(hints, classification)
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
            _t = _time.time()
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
            _stage("classify", _t)
        now = _dt.datetime.now(_dt.timezone.utc)
        eff_settings = dict(settings)
        eff_settings["_agent"] = agent
        eff_settings["_lead"] = {"first_name": row.get("lead_first_name"), "last_name": row.get("lead_last_name"),
                                 "email": row.get("lead_email")}
        # "offer different times" / "offer next week" (owner report 2026-07-25):
        # read the typed feedback for a WHEN request and re-pick the slots from
        # the real calendar to match it. Nothing is invented - the plan only
        # skips slots this row already proposed and/or moves the floor forward.
        # Owner ruling 2026-08-15: an old stored row may still carry no
        # timezone (and a classify outage skips the re-resolve above) -
        # assume Eastern rather than skip the slot build. tz_unknown is dead.
        tz = tz or "America/New_York"
        time_plan = time_feedback_plan(feedback_text, tz, now)
        slots, slot_status, serr = [], "not_configured", ""
        slot_note = ""
        slot_status, avail, serr = get_calendly_availability(agent, eff_settings, now)
        if slot_status == "ok":
            if time_plan:
                prior = [str(s.get("iso")) for s in (row.get("slots") or []) if isinstance(s, dict)]
                slots = pick_slots(avail, tz, eff_settings, now,
                                   exclude_isos=prior,
                                   not_before_utc=time_plan.get("not_before_utc"),
                                   horizon_days_override=time_plan.get("horizon"))
                if not slots:
                    # The calendar genuinely has nothing matching. Fall back
                    # to the normal pick and SAY SO rather than silently
                    # re-offering the same times as if nothing was asked.
                    slots = pick_slots(avail, tz, eff_settings, now)
                    slot_note = (f"You asked for {time_plan['said']}, but the calendar has no "
                                 f"free slot that matches inside the booking window.")
            else:
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
        # When the WHEN request was actioned, say so plainly at the very front
        # of the feedback: without it the drafter can read "offer next week"
        # beside a next-week slot list and still hedge about the old times.
        if time_plan:
            marker = (f"TIMES ALREADY RE-PICKED: the slots below are the {time_plan['said']} you "
                      f"asked for. Propose exactly these and do not mention the previous times."
                      if not slot_note else f"COULD NOT RE-PICK TIMES: {slot_note}")
            combined_feedback = marker + "\n" + combined_feedback
        combined_feedback = _prefix_latest_rules(rules_block, combined_feedback)
        # Who signs this draft: the row's STORED thread keeps from_name on
        # every SENT message (hydration has stored it since the thread was
        # normalised), so the actual sending identity for THIS lead is right
        # here - no live re-read needed. The agent's stamped sender_first is
        # ONE name, but an agent can serve campaigns sent by different people
        # (owner report 2026-07-28: sent from Jane, regenerate signed Kevin
        # because the agent doc - its "memory" - was stamped Kevin). Same
        # precedence as the live pipeline: thread ground truth wins, the
        # agent's configured name is only the fallback.
        sender_first = _sender_first_for(
            agent, _thread_sender_first(row.get("smartlead_campaign_id"), row.get("thread")))
        # call_ask: a redraft on a later turn must not re-pitch a call the lead
        # already settled or never asked about (owner report 2026-07-25).
        # Explicit time feedback always forces "required" - the reviewer is
        # asking for times, so times are the point of this draft.
        redraft_body_text = clean_body(row.get("reply_body") or "")
        # "Later turn" = the lead has replied more than once in this thread.
        inbound_turns = sum(1 for m in (row.get("thread") or [])
                            if isinstance(m, dict) and str(m.get("type") or "").upper() != "SENT")
        call_ask = "required" if time_plan else call_ask_for(
            classification, redraft_body_text, thread_text, first_touch=inbound_turns <= 1)
        _t = _time.time()
        d = draft_reply(
            {"first_name": row.get("lead_first_name"), "subject": row.get("reply_subject"), "body": row.get("reply_body"),
             "first_outbound": row.get("first_outbound") or "",
             "thread": row.get("thread"),
             "thread_text": thread_text, "call_ask": call_ask},
            agent, classification, slots, slot_status, sender_first=sender_first,
            regen_feedback=combined_feedback)
        _stage("draft", _t)
        draft_html = d.get("html")
        if draft_html:
            # Second sweep (owner brief 2026-07-14): proofread before this
            # regenerated draft is saved.
            _t = _time.time()
            draft_html, _proofread_changed = proofread_draft(draft_html, sender_first)
            _stage("proofread", _t)
        # Re-stamped, not preserved: the baseline for an Approve-time diff is
        # the LATEST thing the agent wrote, not its first attempt. Edits the
        # reviewer makes after this regenerate are measured against this draft.
        patch = {"draft_subject": d.get("subject"), "draft_body": draft_html,
                 "original_draft_body": draft_html, "slots": slots,
                 "guardrails": {**(row.get("guardrails") or {}),
                                **slot_situation(slot_status, tz, slots, serr)}}
        if fresh_classification is not None:
            # Persist what the redraft-classify learned so the UI's Intent
            # line updates and the next Regenerate doesn't re-classify.
            patch["classification"] = fresh_classification
            patch["first_outbound"] = row.get("first_outbound") or ""
        if tz and not row.get("timezone"):
            # Also covers the heal above (stored classification, empty
            # timezone) - without this stamp the next Regenerate re-resolves
            # from scratch every time.
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
        _t = _time.time()
        _apply_patch(row, patch)
        _stage("save", _t)
        _stage("total", _t_start)
        # Transient, response-only (setter_queue schema-freeze: never a new
        # column): the drafter's can't-comply explanation for the TYPED
        # feedback, surfaced only when the reviewer actually typed some.
        # slot_note is OUR finding, not the model's: when the calendar could not
        # honour "next week"/"different times" the reviewer must be told, even
        # if the drafter said nothing about it.
        note = (d.get("feedback_note") or "") if feedback_text else ""
        if slot_note:
            note = (slot_note + " " + note).strip()
        return 200, {"row": {**row, **patch}, "feedback_note": note, "stages": stages}
    except Exception as e:  # noqa: BLE001
        _stage("total", _t_start)
        return 500, {"error": str(e)[:300], "stages": stages}


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
        # Optional caller-built thread for deep-conversation test scenarios
        # (training loop 2026-08-16). Lead-side realism law applies to the
        # caller; the pipeline treats it exactly like a hydrated thread.
        if isinstance(payload.get("thread"), list):
            reply["thread"] = payload["thread"]
        if payload.get("sender_first"):
            reply["sender_first"] = payload["sender_first"]
        row = process_reply(reply, agent, settings)
        return 200, {"row": row}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


# Shared answered-check for training case docs (used by the training
# engine's generate/retrain/recheck passes).
def _is_case_answered(case_id, answers: dict) -> bool:
    a = (answers or {}).get(case_id)
    return isinstance(a, dict) and a.get("decision_ok") is not None


# ── training engine (per-agent, permanent) ──────────────────────────────────
# Turns real archived replies into scenarios one agent can be trained on, in
# the open-ended batches. Every REAL scenario's inbound text is a real reply
# verbatim - the eval realism law applies here: no invented pricing,
# resources, or facts.
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
# __settings__ (see _load_agents's exclusion filter above).
# Uses the exact same classify/decide/draft_reply/lint_draft pipeline
# pieces as the live queue, run as-if the master switch and this
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


# Per-agent generation locks - keyed by agent since two different agents'
# batches never conflict with each other (see route_training_generate).
# Guarded by their
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


# Per-agent lock over the training doc's request-path read-modify-write
# (answer / chat / material). Without it, rapid concurrent answer POSTs -
# exactly what the portal's one-click "Correct" produces - each load the
# doc, add their own answer, and save, silently dropping each other's
# (observed 2026-08-16: 6 of 10 robot-speed answers lost). Held only around
# the load→save window, never across an OpenAI call.
_TRAINING_DOC_LOCKS: dict = {}
_TRAINING_DOC_LOCKS_GUARD = threading.Lock()


def _get_training_doc_lock(agent_id: str) -> threading.Lock:
    with _TRAINING_DOC_LOCKS_GUARD:
        lock = _TRAINING_DOC_LOCKS.get(agent_id)
        if lock is None:
            lock = threading.Lock()
            _TRAINING_DOC_LOCKS[agent_id] = lock
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


# ── portal thread view (owner founding case 2026-08-17) ─────────────────────
# Every training card must read as a REALISTIC email thread: at most
# THREAD_RENDER_MAX emails, chronological, what-we-sent / what-they-sent,
# and the LEAD is always the last to respond. These are structural
# invariants, so they live here in deterministic code with tests — never in
# a prompt (prompt rules lose ~1-in-3 against strong mandates; proven in the
# setter-context training loop).

THREAD_RENDER_MAX = 4


def _assemble_case_thread(raw_thread: list, cutoff_at: str = None):
    """Turns a queue-style thread ([{type: SENT|REPLY, time, subject, body,
    from_name}]) into the portal card's thread: cleaned bodies, strictly
    chronological (input order is untrusted), cut at `cutoff_at` when given
    (so a case never shows messages newer than the reply it is about),
    trailing us-side messages dropped (the lead is ALWAYS last — the card
    is about answering them), and only the most recent THREAD_RENDER_MAX
    emails kept. Returns (entries, earlier_count): entries as
    [{who: us|lead, subject, body, at, from_name}], earlier_count = how
    many older messages were cut (the card shows a note, never the raw
    backlog). ([], 0) when nothing usable — callers fall back."""
    def _ts(v):
        try:
            return _parse_iso(v).timestamp()
        except (TypeError, ValueError):
            return None
    entries = []
    for m in (raw_thread or []):
        if not isinstance(m, dict):
            continue
        t = str(m.get("type") or m.get("who") or "").upper()
        who = "us" if t in ("SENT", "US") else "lead"
        body_c = clean_body(m.get("body") or "")
        if not body_c.strip():
            continue
        at = str(m.get("time") or m.get("at") or "")
        entries.append({"who": who, "subject": str(m.get("subject") or ""),
                        "body": body_c, "at": at,
                        "from_name": str(m.get("from_name") or ""), "_ts": _ts(at)})
    entries.sort(key=lambda e: (e["_ts"] is None, e["_ts"] or 0.0))
    cut_ts = _ts(cutoff_at) if cutoff_at else None
    if cut_ts is not None:
        # +2s tolerance: the same instant can differ by ms between the
        # queue hydration and the replies table.
        entries = [e for e in entries if e["_ts"] is None or e["_ts"] <= cut_ts + 2]
    while entries and entries[-1]["who"] != "lead":
        entries.pop()
    if not entries:
        return [], 0
    earlier = max(0, len(entries) - THREAD_RENDER_MAX)
    kept = entries[-THREAD_RENDER_MAX:]
    for e in kept:
        e.pop("_ts", None)
    return kept, earlier


def _fetch_queue_thread(campaign_id, email: str) -> dict:
    """The richest real context we hold for (campaign, email): the setter
    queue's hydrated thread AND the lead's first name, when a non-test row
    exists. Returns {} (never raises) when there is none — the case falls
    back to outreach + inbound and a nameless greeting is avoided via
    thread from_name where possible."""
    if not _SB or not campaign_id or not email:
        return {}
    try:
        rows = _SB("GET", f"{QUEUE_TABLE}?smartlead_campaign_id=eq.{campaign_id}"
                          f"&lead_email=eq.{quote(str(email), safe='')}&is_test=not.is.true"
                          f"&select=thread,lead_first_name&order=id.desc&limit=1")
        if isinstance(rows, list) and rows:
            return rows[0] if isinstance(rows[0], dict) else {}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _case_lead_first_name(case: dict) -> str:
    """The lead's first name for a training case (owner verdict, round 1
    2026-08-17: drafts must greet the lead by name — the live setter never
    says 'Hi there'). Prefers the stored name, falls back to the newest
    lead-side from_name in the case's thread."""
    name = str((case or {}).get("lead_first_name") or "").strip()
    if name:
        return name.split()[0]
    for e in reversed((case or {}).get("thread") or []):
        if e.get("who") == "lead" and (e.get("from_name") or "").strip():
            return str(e["from_name"]).strip().split()[0]
    return ""


_SPINTAX_ALT_RE = re.compile(r"\{([^{}|]*)\|[^{}]*\}")
_MERGE_TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z_ ]+?)\s*\}\}")
_CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _display_clean(text: str, first_name: str = "", company: str = "") -> str:
    """Display hygiene for portal threads (training round 1, 2026-08-17):
    raw spintax braces, unfilled merge tokens, and control characters must
    never reach a client's eyes. Deterministic: spintax resolves to its
    FIRST option (memory: copy-nonspintax-first), known merge tokens fill
    from the lead we're rendering, unknown ones drop, control chars strip.
    Runs on every thread body and subject at the case's single choke point
    in _build_case_core."""
    t = str(text or "")
    for _ in range(3):  # nested/multiple spintax groups
        t2 = _SPINTAX_ALT_RE.sub(lambda m: m.group(1), t)
        if t2 == t:
            break
        t = t2

    def _fill(m):
        key = m.group(1).strip().lower().replace("_", "").replace(" ", "")
        if key in ("firstname", "first"):
            return first_name or ""
        if key in ("company", "companyname"):
            return company or ""
        return ""
    t = _MERGE_TOKEN_RE.sub(_fill, t)
    t = _CTRL_CHAR_RE.sub("", t)
    # collapse doubled spaces a dropped token can leave behind
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


_GREETING_NAME_RE = re.compile(r"^(\s*(?:hi|hey|hello|dear)\s+)([A-Z][\w'-]*)", re.IGNORECASE)


def _swap_greeting_name(body: str, first_name: str) -> str:
    """Deterministic greeting swap for synthetic threads: a REAL outreach
    body reused as a fictitious lead's email 1 gets its greeting renamed to
    the invented lead — nothing else in the body changes."""
    if not first_name:
        return body
    return _GREETING_NAME_RE.sub(lambda m: m.group(1) + first_name, body, count=1)


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
        # Portal thread view (2026-08-17): optional earlier lead turn - when
        # non-empty the case builder constructs a 4-email thread (outreach ->
        # this -> OUR real drafted reply -> body). Empty string = 2-email case.
        "prior_lead_reply": {"type": "string"},
        # Only used when the agent has zero real outreach to reuse (see
        # fallback_context): a plausible outreach email 1 written FROM the
        # agent's own instructions - never invented facts.
        "outreach_subject": {"type": "string"}, "outreach_body": {"type": "string"},
    },
    "required": ["lead_first_name", "lead_company", "subject", "body",
                 "prior_lead_reply", "outreach_subject", "outreach_body"],
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

THREAD DEPTH: for roughly one scenario in three (spread across categories), also fill prior_lead_reply - an EARLIER, shorter message from the same lead that came before the final reply in `body` (e.g. a first "sounds interesting, how does it work?" before the final "OK and what about pricing?"). The two lead messages must read as the same person continuing one conversation. For all other scenarios prior_lead_reply is an empty string. prior_lead_reply obeys the same lead-side-only law as body.

outreach_subject / outreach_body: the payload's outreach_needed flag decides. When outreach_needed is false, leave both empty (a real sent email will be reused). When outreach_needed is true, ALWAYS write them - the outreach email the lead is replying to, a faithful short rendition of what this agent sends, drawn ONLY from the agent context you were given (reference_replies tone, fallback_context instructions); never invent a price, link, or claim that isn't in that context, and never leave them empty when outreach_needed is true.

REALISM (how a real lead writes, learned from real replies): short sentences, sometimes fragments; typos and lowercase happen; specific practical questions ("does this work with outlook?", "what's the cost?"); mobile sign-offs ("Sent from my iPhone"); busy-person brevity ("Send it over.", "Not now - Q3 maybe."). Never bullet-pointed brochure prose, never perfectly parallel sentence structure.

Output STRICT JSON: {"scenarios": [{"lead_first_name": "...", "lead_company": "...", "subject": "...", "body": "...", "prior_lead_reply": "...", "outreach_subject": "...", "outreach_body": "..."}, ...]}, one object per scenario_plan position, in the same order. subject and body should read like a short, real inbound email reply - plain text, a couple of sentences, the way a busy person actually replies, never polished marketing copy."""


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
    # Outreach availability is about SENDS, not replies (training round 1,
    # 2026-08-17): an agent can have plenty of real replies in scope yet
    # zero reusable outreach - the invention must then write email 1 itself
    # or the synthetic thread has no us-side at all.
    _camp_ids_for_outreach = allowed_campaign_ids if allowed_campaign_ids is not None \
        else (agent.get("campaign_ids") or [])
    outreach_needed = not _fetch_agent_outreach_sample(_camp_ids_for_outreach, limit=1)
    payload = {"scenario_plan": scenario_plan, "outreach_needed": outreach_needed}
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
            "prior_lead_reply": str(item.get("prior_lead_reply") or "").strip(),
            "outreach_subject": str(item.get("outreach_subject") or "").strip(),
            "outreach_body": str(item.get("outreach_body") or "").strip(),
        })
    # Outreach reuse (thread round 1, 2026-08-17): when outreach was needed
    # the model sometimes fills it for only part of the batch (the classic
    # ~1-in-3 prompt-rule miss). A scenario without one would be DROPPED by
    # the case builder's no-us-side guard, silently shrinking the batch -
    # the owner hit a "round" of one card. Deterministic repair: borrow a
    # sibling's outreach from the SAME call (same agent, same context; the
    # greeting is renamed per-lead downstream), so batches stay full.
    if outreach_needed:
        donor = next((s for s in scenarios if s["outreach_body"]), None)
        if donor:
            for s in scenarios:
                if not s["outreach_body"]:
                    s["outreach_body"] = donor["outreach_body"]
                    s["outreach_subject"] = s["outreach_subject"] or donor["outreach_subject"]
    return scenarios


def _build_case_core(*, subject: str, body: str, raw_body: str, category, campaign_id, email_domain: str,
                     original_outreach: dict, human_answer_history: dict, agent: dict, eff_settings: dict,
                     avail: list, slot_status0: str, now, mem_digest: str, idx: int, reply_id,
                     synthetic: bool, thread_raw: list = None, cutoff_at: str = None,
                     inbound_at: str = None, synthetic_thread: list = None,
                     lead_first_name: str = "") -> dict:
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
    # Lead-name fallback (owner verdict, round 1 2026-08-17): when the
    # caller has no stored name, the newest lead-side from_name in the raw
    # thread supplies it — drafting happens below, before thread assembly.
    if not (lead_first_name or "").strip():
        for m in reversed(thread_raw or []):
            t = str((m or {}).get("type") or (m or {}).get("who") or "").upper()
            if t not in ("SENT", "US") and str((m or {}).get("from_name") or "").strip():
                lead_first_name = str(m["from_name"]).strip().split()[0]
                break
    lead_first_name = (lead_first_name or "").strip()

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
    # Owner training rule (2026-08-16, round 1), mirrored from the live
    # pipeline's wants_draft gate: "No matter what they say, always say
    # something" - every HUMAN reply gets a draft, even a clear negative.
    # Only machine mail (OOO autoreplies, bounces) keeps the no-draft
    # short-circuit. The training path had kept the old is_clear_neg skip
    # (owner question, thread round 1 2026-08-17: "why is there no draft
    # for Carl?" - Carl was machine mail, but the question exposed that
    # human negatives were also draft-less here, diverging from live).
    human_reply = primary not in ("ooo", "bounce_or_system")
    wants_draft = (not is_clear_neg) or human_reply or (category in POSITIVE_CATEGORIES)

    slots, slot_status = [], "not_configured"
    if wants_draft:
        # resolve_timezone() always returns a zone (owner ruling 2026-08-15:
        # Eastern assumed on zero signal), so slots are always built here.
        slot_status = slot_status0
        if slot_status == "ok":
            eff_lead = dict(eff_settings)
            eff_lead["_lead"] = {"first_name": "", "last_name": "", "email": ""}
            slots = pick_slots(avail, tz, eff_lead, now)
            if not slots:
                slot_status = "none_available"

    # Calendly fallback (owner ruling 2026-07-14) - see decide() gate 7
    # and lint_draft().
    slots_fallback = slot_status != "ok"
    needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

    draft_html = None
    lint_ok, lint_reason = False, "No draft was produced."
    if wants_draft:
        try:
            # Sender identity resolves via _sender_first_for (owner bug
            # report 2026-07-14). The LEAD's first name rides in the payload
            # (owner verdict, round 1 2026-08-17): a draft must greet the
            # lead by name — the live setter never says "Hi there".
            d = draft_reply({"first_name": lead_first_name, "subject": subject, "body": body,
                             "first_outbound": first_outbound}, agent, cls, slots, slot_status,
                            sender_first=_sender_first_for(agent), regen_feedback=mem_digest)
            draft_html = d.get("html")
            if draft_html:
                # Second sweep (owner brief 2026-07-14) - runs BEFORE
                # lint_draft below, so lint checks the final text. Shared by
                # both real (_build_training_case) and synthetic
                # (_build_synthetic_training_case) cases.
                draft_html, _proofread_changed = proofread_draft(draft_html, _sender_first_for(agent))
            lint_ok, lint_reason = lint_draft(draft_html, {
                "subject": d.get("subject"), "first_name": lead_first_name,
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

    # Portal thread view (owner founding case 2026-08-17): every case
    # carries a render-ready thread — chronological, <= THREAD_RENDER_MAX
    # emails, lead always last. Priority: real queue thread -> caller-built
    # synthetic thread -> outreach+inbound fallback. The case's own inbound
    # is guaranteed to be the final entry.
    thread, thread_earlier = (_assemble_case_thread(thread_raw, cutoff_at=cutoff_at)
                              if thread_raw else ([], 0))
    if not thread and synthetic_thread:
        thread = [dict(e) for e in synthetic_thread if isinstance(e, dict) and (e.get("body") or "").strip()]
        thread_earlier = max(0, len(thread) - THREAD_RENDER_MAX)
        thread = thread[-THREAD_RENDER_MAX:]
    if not thread:
        thread = []
        if str(first_outbound or "").strip():
            thread.append({"who": "us", "subject": original_outreach.get("subject") or "",
                           "body": clean_body(first_outbound),
                           "at": str(original_outreach.get("sent_at") or ""), "from_name": ""})
        thread.append({"who": "lead", "subject": subject, "body": body,
                       "at": str(inbound_at or ""), "from_name": ""})
        thread_earlier = 0
    else:
        last = thread[-1]
        same_inbound = last.get("who") == "lead" and \
            (last.get("body") or "").strip()[:80] == (body or "").strip()[:80]
        if not same_inbound:
            thread.append({"who": "lead", "subject": subject, "body": body,
                           "at": str(inbound_at or ""), "from_name": ""})
            if len(thread) > THREAD_RENDER_MAX:
                thread_earlier += len(thread) - THREAD_RENDER_MAX
                thread = thread[-THREAD_RENDER_MAX:]

    # Display hygiene choke point (training round 1, 2026-08-17): every
    # thread body/subject - real, synthetic, or fallback - gets spintax
    # resolved, merge tokens filled from the lead, control chars stripped.
    lead_name = next((e.get("from_name") for e in thread
                      if e.get("who") == "lead" and (e.get("from_name") or "").strip()), "")
    for e in thread:
        e["body"] = _display_clean(e.get("body"), first_name=lead_name)
        e["subject"] = _display_clean(e.get("subject"), first_name=lead_name)

    case = {
        # Globally unique id (thread round 1, 2026-08-17): the old
        # position-derived case-{idx:04d} collided as soon as cases were
        # ever pruned from a doc - a duplicate id makes one answer mark its
        # twin answered, ending a round after one card, and lets a recheck
        # paint the wrong draft onto the wrong card. Same law as the queue:
        # ids are never positional. idx stays as a readable suffix only.
        "id": f"case-{uuid.uuid4().hex[:10]}-{idx:02d}", "reply_id": reply_id, "campaign_id": campaign_id,
        "category": category,
        "inbound": {"subject": subject, "body": body, "raw_body": raw_body},
        "original_outreach": original_outreach, "human_answer_history": human_answer_history,
        "classification": cls, "decision": decision, "decision_reason": reason,
        "draft_html": draft_html,
        "thread": thread, "thread_earlier": thread_earlier,
        "lead_first_name": lead_first_name,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if synthetic:
        case["synthetic"] = True
    return case


def _build_training_case(reply_row: dict, agent: dict, eff_settings: dict, avail: list, slot_status0: str,
                         now, mem_digest: str, idx: int) -> dict:
    """Runs the real classify -> decide -> draft_reply pipeline pieces over
    one real archived reply (decisions computed as-if the master switch and
    autopilot were ON, real Calendly availability resolved once per batch,
    no live Smartlead call).
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
        qrow = _fetch_queue_thread(campaign_id, email)

        return _build_case_core(subject=subject, body=body, raw_body=raw_body, category=category,
                                campaign_id=campaign_id, email_domain=domain,
                                original_outreach=outreach, human_answer_history=human_answer,
                                agent=agent, eff_settings=eff_settings, avail=avail, slot_status0=slot_status0,
                                now=now, mem_digest=mem_digest, idx=idx, reply_id=reply_id, synthetic=False,
                                thread_raw=qrow.get("thread") or [],
                                cutoff_at=replied_at, inbound_at=replied_at,
                                lead_first_name=str(qrow.get("lead_first_name") or ""))
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

        # Portal thread view (2026-08-17): a synthetic case still shows a
        # real-looking thread. Email 1 is REAL outreach (a genuine sent
        # seq-1 body, greeting renamed to the invented lead) or, for an
        # agent with zero sends, the outreach the invention wrote from the
        # agent's own instructions. When the scenario carries a
        # prior_lead_reply, the thread deepens to 4 emails and OUR mid-
        # thread reply is the REAL drafter's output over that prior turn —
        # every us-side email is pipeline output, never hand-written.
        first_name = str(scenario.get("lead_first_name") or "").strip()
        camp_ids = [campaign_id] if campaign_id else (agent.get("campaign_ids") or [])
        sample = _fetch_agent_outreach_sample(camp_ids, limit=1)
        if sample:
            o_subject = str(sample[0].get("subject") or "")
            o_body = _swap_greeting_name(clean_body(sample[0].get("body") or ""), first_name)
        else:
            o_subject = str(scenario.get("outreach_subject") or "")
            o_body = clean_body(str(scenario.get("outreach_body") or ""))
        prior = clean_body(str(scenario.get("prior_lead_reply") or ""))
        if not o_body.strip():
            # No us-side email is buildable (no real send to reuse AND the
            # invention wrote no outreach): a practice thread where nobody
            # wrote to the lead first isn't a thread - drop the scenario
            # (same bad-scenario discipline as every other None return;
            # training round 1, 2026-08-17).
            return None

        def _at(days_ago: float) -> str:
            return (now - _dt.timedelta(days=days_ago)).isoformat(timespec="seconds")

        synthetic_thread = []
        original_outreach = {}
        if o_body.strip():
            original_outreach = {"subject": o_subject, "body": o_body, "sent_at": _at(6)}
            synthetic_thread.append({"who": "us", "subject": o_subject, "body": o_body,
                                     "at": _at(6), "from_name": ""})
        if prior and o_body.strip():
            synthetic_thread.append({"who": "lead", "subject": subject, "body": prior,
                                     "at": _at(4), "from_name": first_name})
            try:
                prior_cls = classify({"subject": subject, "body": prior, "first_outbound": o_body,
                                      "last_outbound": "", "email_domain": ""}, agent, owner_hints=mem_digest)
                mid = draft_reply({"first_name": first_name, "subject": subject, "body": prior,
                                   "first_outbound": o_body}, agent, prior_cls, [], "not_configured",
                                  sender_first=_sender_first_for(agent), regen_feedback=mem_digest)
                mid_text = clean_body(mid.get("html") or "")
                if mid_text.strip():
                    synthetic_thread.append({"who": "us", "subject": subject, "body": mid_text,
                                             "at": _at(3.8), "from_name": ""})
            except Exception:  # noqa: BLE001 - a failed mid-turn just yields a shorter thread
                pass
        synthetic_thread.append({"who": "lead", "subject": subject, "body": body,
                                 "at": _at(1), "from_name": first_name})

        return _build_case_core(subject=subject, body=body, raw_body=raw_body, category=category,
                                campaign_id=campaign_id, email_domain="",
                                original_outreach=original_outreach, human_answer_history={},
                                agent=agent, eff_settings=eff_settings, avail=avail, slot_status0=slot_status0,
                                now=now, mem_digest=mem_digest, idx=idx, reply_id=None, synthetic=True,
                                synthetic_thread=synthetic_thread, inbound_at=_at(1),
                                lead_first_name=first_name)
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
        # mid-batch (the in-memory thread and lock die with the process).
        # A batch of up to TRAINING_BATCH_MAX cases never legitimately runs
        # past 10 minutes. Healed in the RESPONSE only - never persisted
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
            # Client training portal (2026-08-16): the companion chat's own
            # history (so a refresh doesn't wipe the conversation) and the
            # documents the client has fed the agent - summaries only, the
            # raw text never round-trips back out.
            "chat_log": list(doc.get("chat_log") or []),
            "materials": [{"filename": m.get("filename") or "", "kind": m.get("kind") or "",
                           "summary": m.get("summary") or "", "facts_count": m.get("facts_count") or 0,
                           "at": m.get("at") or ""}
                          for m in (doc.get("materials") or []) if isinstance(m, dict)],
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
    batch shows up (see setter-train.html generateMore()). The lock is
    per-agent - two different agents' batches never conflict."""
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
        # fills the batch. A share link used to require a campaign so a client
        # link was never minted for an unconfigured agent - but an agent WITH
        # instructions and no campaign yet (a from-scratch AI-SDR trained
        # before its campaign launches, owner ruling 2026-08-18) is configured
        # enough to practise: the synthetic top-up builds the whole batch from
        # the instructions alone. Only refuse a truly empty agent.
        allowed_campaign_ids = [str(c) for c in (agent.get("campaign_ids") or [])]
        if is_share_mode and not allowed_campaign_ids and not (agent.get("instructions") or "").strip():
            return 400, {"error": "Add some instructions to this agent before training it."}

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

        # Force-on: the training question is
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
# case after case. The lock is the SAME per-agent
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
    roughly limit_chars. Built from the training doc's answers dict
    (keyed by case_id) rather than a flat feedback_log.

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
    survives)."""
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
        # Mirror the live wants_draft gate (owner rule 2026-08-16: every
        # HUMAN reply gets a draft; only machine mail short-circuits) -
        # same fix as _build_case_core, thread round 1 2026-08-17.
        human_reply = primary not in ("ooo", "bounce_or_system")
        wants_draft = (not is_clear_neg) or human_reply or (case.get("category") in POSITIVE_CATEGORIES)

        slots, slot_status = [], "not_configured"
        if wants_draft:
            # resolve_timezone() always returns a zone (owner ruling
            # 2026-08-15: Eastern assumed on zero signal) - always build.
            slot_status = slot_status0
            if slot_status == "ok":
                eff_lead = dict(eff_settings)
                eff_lead["_lead"] = {"first_name": "", "last_name": "", "email": ""}
                slots = pick_slots(avail, tz, eff_lead, now)
                if not slots:
                    slot_status = "none_available"

        slots_fallback = slot_status != "ok"
        needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

        draft_html = None
        lint_ok, lint_reason = False, "No draft was produced."
        if wants_draft:
            try:
                # Sender identity via _sender_first_for (owner bug report
                # 2026-07-14). Lead name from the case (owner verdict, round
                # 1 2026-08-17: never "Hi there").
                lead_first = _case_lead_first_name(case)
                d = draft_reply({"first_name": lead_first, "subject": subject, "body": body,
                                 "first_outbound": first_outbound}, agent_snapshot, cls, slots, slot_status,
                                sender_first=_sender_first_for(agent_snapshot), regen_feedback=digest)
                draft_html = d.get("html")
                if draft_html:
                    # Second sweep (owner brief 2026-07-14) - BEFORE lint so
                    # lint checks the final, proofread text.
                    draft_html, _proofread_changed = proofread_draft(draft_html, _sender_first_for(agent_snapshot))
                lint_ok, lint_reason = lint_draft(draft_html, {
                    "subject": d.get("subject"), "first_name": lead_first,
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
        # Mirror the live wants_draft gate (owner rule 2026-08-16: every
        # HUMAN reply gets a draft; only machine mail short-circuits) -
        # same fix as _build_case_core, thread round 1 2026-08-17.
        human_reply = primary not in ("ooo", "bounce_or_system")
        wants_draft = (not is_clear_neg) or human_reply or (case.get("category") in POSITIVE_CATEGORIES)

        slots, slot_status = [], "not_configured"
        if wants_draft:
            # resolve_timezone() always returns a zone (owner ruling
            # 2026-08-15: Eastern assumed on zero signal) - always build.
            slot_status = slot_status0
            if slot_status == "ok":
                eff_lead = dict(eff_settings)
                eff_lead["_lead"] = {"first_name": "", "last_name": "", "email": ""}
                slots = pick_slots(avail, tz, eff_lead, now)
                if not slots:
                    slot_status = "none_available"

        slots_fallback = slot_status != "ok"
        needs_availability_ask = "scheduling" in (cls.get("all_intents") or [])

        draft_html = None
        lint_ok, lint_reason = False, "No draft was produced."
        if wants_draft:
            try:
                # No hydration in a recheck pass either - resolves to the
                # agent's own configured identity via _sender_first_for (owner
                # bug report 2026-07-14: this used to hardcode "Bjion").
                # Lead name from the case (owner verdict, round 1
                # 2026-08-17: never "Hi there").
                lead_first = _case_lead_first_name(case)
                d = draft_reply({"first_name": lead_first, "subject": subject, "body": body,
                                 "first_outbound": first_outbound}, agent_snapshot, cls, slots, slot_status,
                                sender_first=_sender_first_for(agent_snapshot), regen_feedback=digest)
                draft_html = d.get("html")
                if draft_html:
                    # Second sweep (owner brief 2026-07-14) - BEFORE lint so
                    # lint checks the final, proofread text.
                    draft_html, _proofread_changed = proofread_draft(draft_html, _sender_first_for(agent_snapshot))
                lint_ok, lint_reason = lint_draft(draft_html, {
                    "subject": d.get("subject"), "first_name": lead_first,
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
    protection, same discipline as _training_generate_worker). If another
    trigger queued a fresh pass while this one ran - including a fresh
    "remember" note that landed mid-pass, or the tiny flagger thread from
    _kick_off_training_retrain's lock-held branch - loops once more, writing
    a fresh running marker and draining pending_merges again at the TOP of
    that follow-on pass before its own retrain work. Never raises."""
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
            # with the fresher digest.
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
        # Doc lock: the portal's one-click "Correct" makes rapid concurrent
        # answers routine; the whole load→save below must be atomic per
        # agent or concurrent answers silently drop each other.
        with _get_training_doc_lock(agent_id):
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


# ── client training portal: chat companion + material intake ─────────────────
# Both routes are PUBLIC behind a share token (server.py _AUTH_PUBLIC_POST)
# and scoped by the same _resolve_share_scope helper as every other training
# route: one token, one agent, nothing else reachable. Neither can send mail -
# they only ever write to the agent's own training doc / instructions.

TRAINING_CHAT_CAP = 60          # rolling chat_log entries kept in the doc
TRAINING_MATERIALS_CAP = 20     # rolling materials entries kept in the doc
TRAINING_MATERIAL_TEXT_CAP = 200_000    # pasted/extracted chars fed to distill
TRAINING_MATERIAL_PDF_CAP = 7 * 1024 * 1024  # decoded PDF bytes

TRAINING_CHAT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"reply": {"type": "string"},
                   "action": {"type": "string",
                              "enum": ["none", "remember_feedback", "show_tutorial"]},
                   "feedback_text": {"type": "string"}},
    "required": ["reply", "action", "feedback_text"],
}

TRAINING_CHAT_SYSTEM = """You are the friendly guide on a training page where a business owner teaches their AI email assistant (their "AI") how to reply to leads in their voice. You are NOT the AI being trained - you are the helper standing next to them.

The page: scenario cards on the right show a simulated conversation and the AI's draft reply. The owner marks each card "Correct" or "Needs work" (Needs work requires saying what they'd do instead - that reason teaches the AI). Every verdict teaches the AI. A readiness score climbs as they rate; at 90 the AI is considered trained. They train in rounds of about 10 cards. They can also drop in documents (pricing, FAQs, case studies) or just tell YOU standing rules in this chat.

Your job, in order of priority:
1. If their message is standing guidance about how their AI should behave, write, or answer ("we never discount", "our demo link is X", "always sound informal", pricing details, resource rules) - set action to "remember_feedback" and put a clean, self-contained version of the rule in feedback_text. In reply, confirm in one short sentence that their AI will remember it. Copy exact facts (prices, links, names) verbatim - never invent or embellish them.
2. If they ask how the page works, seem lost, or ask to see the tutorial/walkthrough again - set action to "show_tutorial" and tell them you'll bring it up.
3. Otherwise action is "none" and feedback_text is empty: answer their question or give brief, encouraging commentary on where they are (use the context numbers you're given - never invent progress).

Voice rules: plain, warm, simple English a 16-year-old would understand. 1-3 short sentences. No jargon, no internal system talk (never say "agent doc", "instructions merge", "readiness_history" or similar). Never promise anything about emailing real people - this page never emails anyone. Never give business, legal, or pricing advice of your own - their answers train their AI; you only guide the process."""

TRAINING_DISTILL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"summary": {"type": "string"},
                   "facts": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "facts"],
}

TRAINING_DISTILL_SYSTEM = """A business owner uploaded a document (or pasted text) to teach their AI email assistant about their business. Distill it into standing facts the assistant can use when replying to leads.

Extract ONLY what would change how a reply is written: pricing and what it includes, offers and guarantees, resources/links and when to share each, answers to common questions, named case studies or proof points, and voice/tone rules. Copy exact numbers, names, and URLs verbatim - never round, never invent. Skip filler, marketing fluff, and anything generic.

Return: summary = one plain sentence saying what this document is. facts = up to 12 self-contained bullet statements, each usable on its own (e.g. "Pricing: the Growth plan is $1,500/month and includes up to 3 campaigns."). If the text contains nothing usable, return an empty facts list."""


def _training_chat_llm(agent: dict, message: str, context: dict, chat_log: list) -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    payload = {
        "owner_message": str(message)[:2000],
        "agent_name": agent.get("name") or "your AI",
        "page_context": {k: context.get(k) for k in
                         ("readiness_score", "answered_count", "cases_total",
                          "round_num", "round_right", "round_total", "view")
                         if context.get(k) is not None},
        # last few turns so follow-ups make sense; text only, capped
        "recent_chat": [{"who": e.get("who"), "text": str(e.get("text") or "")[:400]}
                        for e in (chat_log or [])[-8:]],
    }
    r = _openai({"model": OPENAI_MODEL,
                 "messages": [{"role": "system", "content": TRAINING_CHAT_SYSTEM},
                             {"role": "user", "content": json.dumps(payload)}],
                 "response_format": {"type": "json_schema", "json_schema": {
                     "name": "training_chat", "strict": True, "schema": TRAINING_CHAT_SCHEMA}}}, key)
    if not isinstance(r, dict):
        raise RuntimeError("OpenAI: empty response")
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {str(r['error'].get('message', r['error']))[:200]}")
    return json.loads(r["choices"][0]["message"]["content"])


def route_training_chat(payload):
    """The portal's companion chat. Commentary + walkthrough by default; a
    standing rule typed here queues onto pending_merges (the SAME low-latency
    path a "Remember going forward" note takes in route_training_answer - the
    background retrain worker drains and merges it), so the chat response
    never waits on a 5-15s instructions merge."""
    try:
        payload = payload or {}
        agent_id, err = _resolve_share_scope(payload.get("agent_id"),
                                             payload.get("share") or "",
                                             bool(payload.get("___public")))
        if err:
            return err
        message = str(payload.get("message") or "").strip()
        if not message:
            return 400, {"error": "message is required"}
        if len(message) > 4000:
            return 400, {"error": "That message is too long for the chat - use the paste box for big text."}
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}
        doc = _load_training(agent_id)
        chat_log = list(doc.get("chat_log") or [])
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

        out = _training_chat_llm(agent, message, context, chat_log)
        reply = str(out.get("reply") or "").strip() or "I'm here - what would you like to know?"
        action = out.get("action") if out.get("action") in ("none", "remember_feedback", "show_tutorial") else "none"
        feedback_text = str(out.get("feedback_text") or "").strip()

        at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        saved = False
        retrain = None
        # Reload under the doc lock: the LLM call above took seconds, and an
        # answer POST may have written the doc in the meantime - never save
        # over it from the stale pre-LLM copy.
        with _get_training_doc_lock(agent_id):
            doc = _load_training(agent_id)
            if action == "remember_feedback" and feedback_text:
                pending = list(doc.get("pending_merges") or [])
                pending.append({"note": feedback_text[:2500], "source": "chat-feedback", "at": at})
                doc["pending_merges"] = pending
                saved = True
            fresh_log = list(doc.get("chat_log") or [])
            fresh_log.append({"who": "client", "text": message[:2000], "at": at})
            fresh_log.append({"who": "guide", "text": reply[:2000], "at": at, "action": action})
            doc["chat_log"] = fresh_log[-TRAINING_CHAT_CAP:]
            _save_training(agent_id, doc)
        if saved:
            retrain = _kick_off_training_retrain(agent_id)

        return 200, {"reply": reply, "action": action, "saved": saved, "retrain": retrain}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)[:300]}


def _extract_pdf_text(data: bytes) -> str:
    from io import BytesIO
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF reading isn't available right now - copy and paste the text instead.")
    reader = PdfReader(BytesIO(data))
    parts = []
    for page in reader.pages[:80]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one unreadable page never kills the doc
            continue
    return "\n".join(parts).strip()


def _training_distill_llm(text: str, filename: str) -> dict:
    key = _KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from keys")
    r = _openai({"model": OPENAI_MODEL,
                 "messages": [{"role": "system", "content": TRAINING_DISTILL_SYSTEM},
                             {"role": "user", "content": json.dumps(
                                 {"filename": filename, "text": text[:TRAINING_MATERIAL_TEXT_CAP]})}],
                 "response_format": {"type": "json_schema", "json_schema": {
                     "name": "training_distill", "strict": True, "schema": TRAINING_DISTILL_SCHEMA}}},
                key, timeout=90)
    if not isinstance(r, dict):
        raise RuntimeError("OpenAI: empty response")
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {str(r['error'].get('message', r['error']))[:200]}")
    return json.loads(r["choices"][0]["message"]["content"])


def route_training_material(payload):
    """PDF drop / large-text paste from the portal. Extracts, distills to
    instruction-ready facts (one gpt-5-mini call, inline - a single call
    stays well under the edge-proxy timeout), then queues ONE combined
    correction onto pending_merges so the background retrain worker merges
    it into the agent's instructions - the client's page never blocks on the
    merge itself. The raw document text is never stored, only the distilled
    facts and a one-line summary."""
    try:
        payload = payload or {}
        agent_id, err = _resolve_share_scope(payload.get("agent_id"),
                                             payload.get("share") or "",
                                             bool(payload.get("___public")))
        if err:
            return err
        agent = _load_agent(agent_id)
        if not agent:
            return 404, {"error": "Agent not found."}

        filename = str(payload.get("filename") or "").strip()[:120]
        text = str(payload.get("text") or "").strip()
        pdf_b64 = payload.get("pdf_base64") or ""
        kind = "text"
        if pdf_b64:
            import base64
            try:
                data = base64.b64decode(pdf_b64, validate=False)
            except Exception:  # noqa: BLE001
                return 400, {"error": "That file didn't upload cleanly - try again."}
            if len(data) > TRAINING_MATERIAL_PDF_CAP:
                return 400, {"error": "That PDF is too big (7MB max). Try a smaller file, or paste the key text instead."}
            text = _extract_pdf_text(data)
            kind = "pdf"
            filename = filename or "document.pdf"
        if len(text) < 50:
            return 400, {"error": "I couldn't read enough text from that. If it's a scanned PDF, "
                                  "copy and paste the text instead."}
        filename = filename or "pasted text"

        out = _training_distill_llm(text, filename)
        facts = [str(f).strip() for f in (out.get("facts") or []) if str(f).strip()][:12]
        summary = str(out.get("summary") or "").strip()[:300]
        if not facts:
            return 200, {"ok": True, "facts": [], "summary": summary,
                        "message": "I read it, but couldn't find anything that would change how your AI replies. "
                                   "Try a document with pricing, offers, links, or answers to common questions."}

        at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        note = f"Reference material from \"{filename}\": " + " ".join(f"- {f}" for f in facts)
        # Same doc-lock discipline as answer/chat: the distill call above
        # took seconds, so load fresh inside the lock before writing.
        with _get_training_doc_lock(agent_id):
            doc = _load_training(agent_id)
            pending = list(doc.get("pending_merges") or [])
            pending.append({"note": note[:2500], "source": f"material:{filename}", "at": at})
            doc["pending_merges"] = pending
            materials = list(doc.get("materials") or [])
            materials.append({"filename": filename, "kind": kind, "chars": len(text),
                             "summary": summary, "facts_count": len(facts), "at": at})
            doc["materials"] = materials[-TRAINING_MATERIALS_CAP:]
            _save_training(agent_id, doc)
        retrain = _kick_off_training_retrain(agent_id)

        return 200, {"ok": True, "facts": facts, "summary": summary, "filename": filename,
                    "retrain": retrain}
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
    "/api/setter/queue/row": route_queue_row_get,
    "/api/setter/queue/locate": route_queue_locate_get,
    "/api/setter/search-smartlead": route_search_smartlead_get,
    "/api/setter/smartlead-thread": route_smartlead_thread_get,
    "/api/setter/categories": route_categories_get,
    "/api/setter/thread": route_thread_get,
    "/api/setter/lead-contact": route_lead_contact_get,
    "/api/setter/training": route_training_get,
    "/api/setter/training/share-info": route_training_share_info,
    "/api/setter/edit-lesson": route_edit_lesson_get,
    "/api/setter/subsequences": route_subsequences_get,
    "/api/setter/subsequence/unresolved": route_subsequence_unresolved,
    "/api/setter/poll/status": route_poll_status,
    "/api/setter/queue/redraft/status": route_redraft_status,
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
    "/api/setter/queue/recategorise": route_queue_recategorise,
    "/api/setter/subsequence/push": route_subsequence_push,
    "/api/setter/training/generate": route_training_generate,
    "/api/setter/training/answer": route_training_answer,
    "/api/setter/training/recheck": route_training_recheck,
    "/api/setter/training/reset": route_training_reset,
    "/api/setter/training/share": route_training_share,
    "/api/setter/training/chat": route_training_chat,
    "/api/setter/training/material": route_training_material,
    "/api/setter/test/inject": route_test_inject,
    "/api/setter/edit-lesson/undo": route_edit_lesson_undo,
    "/api/setter/phone-status": route_phone_status_post,
}
