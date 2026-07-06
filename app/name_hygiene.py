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
    if s.isupper() and len(s) > 4:  # ALL-CAPS shouting -> Title Case (keep short acronyms)
        s = " ".join(w.capitalize() for w in s.split())
    if len(s) < 2:
        return company if fallback else None
    return s
