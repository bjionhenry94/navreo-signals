"""Business-name normalisation — ported from the lilly-qa lead-field-hygiene rules.

`clean_company_name` mirrors ~/.claude/skills/lilly-qa/scripts/check_lead_field_hygiene.py
(and its references/lead-field-hygiene.md). Keep the two in sync: this is the same cleaner
that QA runs on Smartlead leads, applied here at ingest so every business name stored in
signal_leads / engagement_events is already clean before it can reach an email.

Rules (summary): strip legal suffixes (Inc, Ltd, GmbH, S.A. …), profession tails
(Advogados, Attorneys …), trailing non-Latin transliterations, wrapping parentheticals
(but promote an acronym parenthetical to the brand), website TLDs (navreo.ai → Navreo),
title-case ALL-CAPS shouting >4 chars; preserve short acronyms, lowercase-start brands
(iCrossing, eBay), ampersands, apostrophes, hyphens. Junk / URLs are left untouched.
"""
import re
import unicodedata
from typing import Optional

JUNK_COMPANIES = {
    "unknown", "-", "n/a", "na", "none", "tbd", "self",
    "self-employed", "freelance", "",
}

LEGAL_SUFFIXES = [  # longest first to avoid partial matches
    r"gmbh\s*&\s*co\.?\s*kg", r"s\.?a\.?\s+de\s+c\.?v\.?", r"sp\.?\s*z\s*o\.?o\.?",
    r"pvt\.?\s*ltd\.?", r"private\s+limited", r"co\.?\s*ltd\.?",
    r"l\.?l\.?c\.?", r"l\.?l\.?p\.?", r"p\.?l\.?c\.?", r"b\.?v\.?", r"n\.?v\.?",
    r"s\.?r\.?l\.?", r"s\.?l\.?", r"s\.?a\.?", r"s\.?a\.?s\.?u?", r"s\.?p\.?a\.?",
    r"gmbh", r"mbh", r"ag", r"ug", r"kg", r"ohg", r"e\.?g\.?",
    r"ltd\.?", r"limited", r"inc\.?", r"incorporated", r"corp\.?", r"corporation",
    r"pty", r"co\.?", r"company", r"holdings?", r"group",
    r"ltda\.?", r"limitada", r"me", r"eireli",
    r"apS", r"a/s", r"as", r"ab", r"oy", r"oyj",
    r"k\.?k\.?", r"s\.?r\.?o\.?", r"kft\.?", r"ooo",
    r"sarl", r"sas(u)?", r"eurl", r"v\.?o\.?f\.?",
]
LEGAL_RE = re.compile(r"[,\s]*\b(" + "|".join(LEGAL_SUFFIXES) + r")\s*\.?\s*$", re.IGNORECASE)

PROFESSION_TAILS = [
    r"advogados?", r"avvocati", r"avocats?", r"abogados?", r"rechtsanw[aä]lte",
    r"advocates", r"attorneys", r"law\s+(office|firm)", r"kancelaria",
    r"studio\s+legale", r"commercialisti", r"chartered\s+accountants",
]
PROF_RE = re.compile(r"\s+(" + "|".join(PROFESSION_TAILS) + r")\s*$", re.IGNORECASE)

NON_LATIN_TAIL = re.compile(r"\s+[^\x00-\x7FÀ-ɏḀ-ỿ]+\s*$")
PARENTHETICAL = re.compile(r"\s*\([^)]+\)\s*$")
PARENTHETICAL_ACRONYM = re.compile(r"\(([A-Z]{2,6})\)\s*$")
URL_RE = re.compile(r"^https?://|/", re.IGNORECASE)

EMAIL_AUTOLINK_TLDS = (
    "com", "org", "net", "io", "ai", "co", "app", "dev", "tech", "digital",
    "ly", "tv", "fm", "me", "biz", "info", "online", "shop", "store", "cloud",
    "studio", "agency", "club", "live", "life", "world", "global", "group",
    "tools", "space", "site", "page", "xyz", "pro", "plus", "gg", "health",
    "law", "media", "works", "finance", "capital", "consulting", "partners",
    "new", "ninja", "rocks", "wtf", "fyi", "click", "link", "one",
    "us", "eu", "uk", "de", "fr", "it", "es", "nl", "ca", "au", "nz", "jp",
    "br", "mx", "in", "ie", "pl", "be", "ch", "at", "se", "no", "dk", "fi",
    "is", "cz", "ru", "ws", "cc",
)
TLD_RE = re.compile(r"\.(" + "|".join(EMAIL_AUTOLINK_TLDS) + r")\b\s*$", re.IGNORECASE)


def clean_company_name(company: Optional[str], fallback: bool = True) -> Optional[str]:
    """Return a cleaned company name. With fallback=True (default), returns the
    original value untouched when cleaning can't safely improve it (junk, URL,
    or would collapse to <2 chars) so we never store something worse."""
    s = (company or "").strip()
    if not s or s.lower() in JUNK_COMPANIES:
        return company if fallback else None
    if URL_RE.search(s):  # full URL — flag, don't auto-clean
        return company if fallback else None
    m = PARENTHETICAL_ACRONYM.search(s)  # "UK Power Engineers (UKPE)" -> "UKPE"
    if m:
        return m.group(1)
    s = NON_LATIN_TAIL.sub("", s).strip()
    s = PARENTHETICAL.sub("", s).strip()
    for _ in range(3):
        new = LEGAL_RE.sub("", s).strip(" .,")
        if new == s:
            break
        s = new
    s = PROF_RE.sub("", s).strip()
    new = TLD_RE.sub("", s).strip()  # navreo.ai -> navreo
    if len(new) >= 2:
        s = new
    if s.isupper() and len(s) > 4:  # ALL-CAPS shouting -> Title Case, but keep acronyms/codes
        s = " ".join(_recase_caps_token(w) for w in s.split())
    s = _fix_acronyms(s)  # "Buldrr Ai" -> "Buldrr AI"
    s = email_safe(s)  # strip trademark/pipe/emoji so a merged {{company}} is email-ready
    if len(s) < 2:
        return company if fallback else None
    return s


# ── Acronym casing ──────────────────────────────────────────────────────────
# Conservative canonical-casing map for tokens that read wrong when title-cased
# (e.g. an enrichment source gives "Buldrr Ai"). Keyed by UPPERCASE token; only
# words that case-insensitively match a key are rewritten, so ordinary words are
# never touched. Deliberately excludes ambiguous English words (It, Us, Me, As …).
_ACRONYMS = {
    "AI": "AI", "API": "API", "IOT": "IoT", "AR": "AR", "VR": "VR", "ML": "ML",
    "SAAS": "SaaS", "PAAS": "PaaS", "IAAS": "IaaS", "B2B": "B2B", "B2C": "B2C",
    "D2C": "D2C", "B2B2C": "B2B2C", "CRM": "CRM", "ERP": "ERP", "SEO": "SEO",
    "SEM": "SEM", "PPC": "PPC", "ROI": "ROI", "BI": "BI", "3PL": "3PL",
    "SMB": "SMB", "DTC": "DTC", "NFT": "NFT", "IIOT": "IIoT",
}


def _fix_acronyms(s: str) -> str:
    if not s:
        return s
    return " ".join(_ACRONYMS.get(w.upper(), w) for w in s.split())


def _recase_caps_token(w: str) -> str:
    """Title-case one word of an ALL-CAPS company name WITHOUT mangling acronyms
    or codes: keep short tokens (<=3 chars: UK, USA, CPB, GIS) and any token with
    a digit/dot/slash (3-GIS, A.C.T., B2B) as-is; only real words get title-cased
    ('CALIMA' -> 'Calima', 'ICONIC' -> 'Iconic')."""
    core = w.strip(".,")
    if len(core) <= 3:
        return w
    if any(c.isdigit() for c in w) or "." in w or "/" in w:
        return w
    return w.capitalize()


# ── Email-safe sanitising + person-name cleaning ─────────────────────────────
# "Special character" = any codepoint outside {letters (incl. accented Latin),
# digits, whitespace, ordinary punctuation, and the '+' math sign}. In practice
# that removes emoji / pictographs / dingbats / symbols (categories So, Sk, Sc),
# private-use + control + format codepoints (Co, Cc, Cf — incl. zero-width
# joiner), unassigned (Cn), and math symbols other than '+' (Sm). Braces { } are
# punctuation (Ps/Pe) so {{merge_tags}} pass through untouched.
# Mn/Me = combining + enclosing marks: after NFC composition, any that remain are
# orphaned emoji cruft (variation selectors, keycap/skin-tone joiners), never a
# base letter's accent (those compose into a single Latin codepoint under NFC).
_REMOVE_CATS = {"So", "Sk", "Sc", "Cc", "Cf", "Co", "Cn", "Mn", "Me"}
_ALLOWED_SM = {"+"}


def _is_special(ch: str) -> bool:
    if ch.isspace():
        return False
    cat = unicodedata.category(ch)
    if cat in _REMOVE_CATS:
        return True
    if cat == "Sm" and ch not in _ALLOWED_SM:
        return True
    return False


def is_email_safe(text: Optional[str]) -> bool:
    """True iff `text` contains no special character (the verifier's predicate)."""
    return not any(_is_special(c) for c in unicodedata.normalize("NFC", text or ""))


def _strip_special(text: str) -> str:
    text = unicodedata.normalize("NFC", text)  # compose accents so é stays a letter
    return "".join("" if _is_special(c) else c for c in text)


def email_safe(text: Optional[str]) -> Optional[str]:
    """Belt-and-suspenders sanitiser for a rendered string: drop every special
    character, collapse the whitespace it leaves behind, and heal spaces stranded
    before attaching punctuation (so 'Ana 🍩's' -> "Ana's")."""
    if not text:
        return text
    s = _strip_special(text)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([',.!?:;)’])", r"\1", s)  # no space before attaching punct
    s = re.sub(r"([(])\s+", r"\1", s)               # no space after opening paren
    return s.strip()


# Role / title tails a person sometimes appends to their own name on LinkedIn
# ("Mike Weiss ceo", "Jane Doe | Head of Growth"). Stripped from the tail only.
_ROLE_TAIL = re.compile(
    r"[\s,/|·–—-]+("
    r"ceo|cto|cfo|coo|cmo|cro|cpo|cio|ciso|"
    r"co[\-\s]?founders?|founders?|co[\-\s]?owners?|owners?|"
    r"presidents?|vice\s+presidents?|vps?|svps?|evps?|avps?|"
    r"managing\s+directors?|mds?|directors?|"
    r"partners?|principals?|consultants?|advisors?|"
    r"heads?\s+of\s+[\w&/\s]+|"
    r"chiefs?(\s+[\w]+)*\s+officers?"
    r")\s*$",
    re.IGNORECASE,
)


def clean_person_name(name: Optional[str], fallback: bool = True) -> Optional[str]:
    """Return an email-ready person name: strip emoji / special chars, drop any
    trailing role tail, collapse whitespace, and fix ALL-CAPS / all-lowercase
    casing while preserving genuine intra-word caps (McCarthy, O'Brien).
    Returns the original when cleaning would empty it (fallback=True)."""
    s = _strip_special(name or "")
    s = re.sub(r"\s+", " ", s).strip(" ,/|-·–—")
    for _ in range(3):  # peel repeated tails: "Jane Doe Founder CEO"
        new = _ROLE_TAIL.sub("", s).strip(" ,/|-·–—")
        if new == s or not new:
            break
        s = new
    if s and (s.isupper() or s.islower()):  # SHOUTING or lowercase -> Title Case
        s = " ".join(w.capitalize() for w in s.split())
    if s and s[0].islower():  # leading lowercase (often an emoji was glued on) -> capitalise
        s = s[0].upper() + s[1:]
    if not s.strip():
        return name if fallback else None
    return s.strip()


# Small words kept lowercase when title-casing an ALL-CAPS / all-lowercase title.
_TITLE_MINOR = {"of", "and", "the", "for", "to", "in", "at", "a", "an", "or",
                "on", "with", "de", "du", "van", "per", "as", "by"}
_TITLE_PAREN = re.compile(r"\s*\([^)]*\)")            # "(Annual Contract)", "(Remote)", "(m/f/d)"
_TITLE_TAIL = re.compile(r"\s*[,;|].*$|\s+[–—-]\s+.*$")  # drop qualifier tail after , ; | or spaced dash


def clean_job_title(title: Optional[str], fallback: bool = True) -> Optional[str]:
    """Return an email-ready job title (the role a company is hiring for, merged
    into an icebreaker). Beyond email-safety this trims recruiter-board cruft so
    the role reads naturally in a sentence: drops parentheticals ('Retail Sales
    Consultant (Annual Contract)' -> 'Retail Sales Consultant') and any qualifier
    tail after a comma/semicolon/pipe/spaced-dash ('Skills Consultant, Direct
    Sales' -> 'Skills Consultant'); strips emoji/special chars; title-cases a
    SHOUTING or all-lowercase title while keeping small connectors lowercase
    ('Head of Sales'); preserves mixed-case titles and acronyms. Returns the
    original when cleaning would empty it."""
    raw = title or ""
    s = _TITLE_PAREN.sub("", raw)   # cut before email_safe so a "|" tail is still detectable
    s = _TITLE_TAIL.sub("", s)
    s = email_safe(s) or ""
    s = s.strip(" ,/|-·–—")
    if not s.strip():
        return title if fallback else None
    out = []
    for i, w in enumerate(s.split()):
        lw = w.lower()
        if i and lw in _TITLE_MINOR:       # small connector word -> lowercase
            out.append(lw)
        elif w.islower() or (w.isupper() and len(w) > 3):  # lower / SHOUTING -> Title
            out.append(_fix_acronyms(w.capitalize()))
        else:                              # mixed-case, or short acronym (AE, VP) -> keep
            out.append(_fix_acronyms(w))
    s = " ".join(out)
    return s.strip() or (title if fallback else None)
