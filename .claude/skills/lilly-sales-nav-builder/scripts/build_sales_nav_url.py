#!/usr/bin/env python3
"""Build a LinkedIn Sales Navigator search URL from a JSON config or CLI args.

Sales Nav uses a custom hash-fragment format with strict requirements that this
script handles automatically:

  * URL prefix is `#query=` (hash fragment), NOT `?query=` (query string).
    The query-string form silently drops filters on page load.
  * Spaces inside text values are double-encoded (%2520, not %20)
  * `:` and `,` are encoded as %3A and %2C
  * `(` and `)` are syntax delimiters and stay LITERAL
  * Every `(` must have a matching `)` — a single missed paren breaks the page
  * Some filters require `(text:X,...)` items (CURRENT_TITLE, INDUSTRY,
    GEOGRAPHY)
  * Some filters require `(id:X,text:Y,...)` items (REGION, COMPANY_HEADCOUNT,
    SENIORITY_LEVEL) — text-only items are silently dropped
  * Location filtering requires BOTH `GEOGRAPHY` (text-only URN IDs, for chip
    rendering) AND `REGION` (id+text pairs, for actual filtering). The script
    auto-emits both when you supply `geographies`.

USAGE
    # From a JSON config file:
    python3 build_sales_nav_url.py --config config.json

    # From CLI args (handy for quick one-offs):
    python3 build_sales_nav_url.py \\
        --companies "Inventus Group,Stefanini,KORE Wireless,Clinexion" \\
        --titles "Clinical Trial Manager,Director of Clinical Operations" \\
        --title-type CURRENT_TITLE

CONFIG SCHEMA
    {
      "companies": ["Inventus Group", "Stefanini", ...],
      "company_filter": "CURRENT_COMPANY",   // or "PAST_COMPANY"
      "titles": ["Clinical Trial Manager", "Director of Clinical Operations", ...],
      "title_filter": "CURRENT_TITLE",       // or "PAST_TITLE"
      "geographies": ["United States", "United Kingdom"],
              // Country names from COUNTRY_TO_URN, OR raw URN ID strings.
              // Auto-emits BOTH GEOGRAPHY (text URN IDs) AND REGION (id+text).
      "industries": ["Pharmaceuticals", "Biotechnology Research"],
      "seniorities": ["Director", "VP", "CXO"],
              // Names from SENIORITY_TO_ID, auto-translated to id+text format
              // and emitted as SENIORITY_LEVEL filter.
      "company_headcount": ["51-200", "201-500"],
              // Range strings from HEADCOUNT_TO_CODE, auto-translated to id+text.
      "keywords": "free text search string",
      "options": {
        "keep_parens_in_titles": false,
        "keep_emdash_in_titles": false,
        "warn_above_titles": 70
      }
    }

All fields are optional except at least one of: companies, titles, keywords.
"""

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union


# Sales Nav filter type names. The script knows how to render each as a
# (type:X,values:List(...)) tuple. To add a new filter type, just include its
# canonical name here and pass values via the config.
KNOWN_FILTER_TYPES = {
    "CURRENT_COMPANY",
    "PAST_COMPANY",
    "CURRENT_TITLE",
    "PAST_TITLE",
    "GEOGRAPHY",
    "REGION",
    "INDUSTRY",
    "SENIORITY_LEVEL",
    "COMPANY_HEADCOUNT",
    "FUNCTION",
    "YEARS_AT_CURRENT_COMPANY",
    "YEARS_IN_CURRENT_POSITION",
    "FOLLOWING_YOUR_COMPANY",
    "VIEWED_YOUR_PROFILE_RECENTLY",
}


# ---------------------------------------------------------------------------
# Lookup tables — country/headcount/seniority codes
# ---------------------------------------------------------------------------

# Country name → LinkedIn geo-URN ID. The REGION filter uses id+text format
# with these IDs; GEOGRAPHY uses the same IDs but text-only. Extend as needed
# for new markets — find the URN by inspecting a Sales Nav URL after picking
# the country in the UI.
COUNTRY_TO_URN: Dict[str, str] = {
    # Navreo high-GDP/high-salary set
    "United States": "103644278",
    "Canada": "101174742",
    "United Kingdom": "101165590",
    "Australia": "101452733",
    "Ireland": "104738515",
    "New Zealand": "105490917",
    "Germany": "101282230",
    "Netherlands": "102890719",
    "Switzerland": "106693272",
    "Sweden": "105117694",
    "Norway": "103819153",
    "Denmark": "104514075",
    "Finland": "100456013",
    "Singapore": "102454443",
    # Common additional markets
    "France": "105015875",
    "Italy": "103350119",
    "Spain": "105646813",
    "Belgium": "100565514",
    "Austria": "103883259",
    "Poland": "105072130",
    "Brazil": "106057199",
    "Mexico": "103323778",
    "Japan": "101355337",
    "India": "102713980",
    "China": "102890883",
    "United Arab Emirates": "104305776",
    "South Africa": "104035573",
    "Israel": "101620260",
    "Hong Kong": "103291313",
    "Portugal": "100364837",
    "Czech Republic": "104508036",
    "Greece": "104677530",
    "Romania": "106670623",
    "Hungary": "100288700",
}

# Company headcount range → Sales Nav letter code
HEADCOUNT_TO_CODE: Dict[str, str] = {
    "Self-employed": "A",
    "1-10": "B",
    "11-50": "C",
    "51-200": "D",
    "201-500": "E",
    "501-1000": "F",
    "1001-5000": "G",
    "5001-10000": "H",
    "10001+": "I",
}

# Seniority name → Sales Nav numeric ID. Aliases supported.
SENIORITY_TO_ID: Dict[str, Tuple[str, str]] = {
    # Display name lookup → (id, canonical_text)
    "Entry Level": ("110", "Entry Level"),
    "Entry": ("110", "Entry Level"),
    "Senior": ("130", "Senior"),
    "Senior IC": ("130", "Senior"),
    "Manager": ("200", "Manager"),
    "Senior Manager": ("210", "Senior Manager"),
    "Director": ("220", "Director"),
    "Senior Director": ("230", "Senior Director"),
    "Vice President": ("300", "Vice President"),
    "VP": ("300", "Vice President"),
    "CXO": ("310", "CXO"),
    "C-Suite": ("310", "CXO"),
    "C Suite": ("310", "CXO"),
    "Owner / Partner": ("320", "Owner / Partner"),
    "Owner": ("320", "Owner / Partner"),
    "Partner": ("320", "Owner / Partner"),
    "Founder": ("320", "Owner / Partner"),
}


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------

_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*")
_EMDASH_RE = re.compile(r"\s*[–—]\s*")
_SMART_QUOTE_RE = re.compile(r"[\u2018\u2019\u201C\u201D]")
_BAD_URL_CHAR_RE = re.compile(r"[&?#+]")
_WS_RE = re.compile(r"\s+")


def sanitise_title(title: str, *, keep_parens: bool = False, keep_emdash: bool = False) -> str:
    """Clean a title string for safe inclusion in a Sales Nav text filter.

    Strips parentheticals (e.g. "VP Supply Chain (Clinical)" -> "VP Supply Chain"),
    em-dashes / en-dashes (e.g. "Vendor Manager – Clinical" -> "Vendor Manager Clinical"),
    smart quotes, URL-unsafe chars, and collapses whitespace.

    Sales Nav's title text matcher does not reliably handle parens or em-dashes.
    """
    s = title.strip()
    if not keep_parens:
        s = _PARENTHETICAL_RE.sub(" ", s)
    if not keep_emdash:
        s = _EMDASH_RE.sub(" ", s)
    s = _SMART_QUOTE_RE.sub("", s)
    s = _BAD_URL_CHAR_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def sanitise_company(name: str) -> str:
    """Light cleanup for company names — Sales Nav is more tolerant here."""
    s = name.strip()
    s = _SMART_QUOTE_RE.sub("", s)
    s = _BAD_URL_CHAR_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def dedupe_preserving_order(items: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for item in items:
        # For tuples (id, text), key on the tuple itself; for strings, lowercase
        if isinstance(item, tuple):
            key = tuple(p.lower() if isinstance(p, str) else p for p in item)
        else:
            key = item.lower() if isinstance(item, str) else item
        if key in seen or not item:
            continue
        seen.add(key)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode_text_value(value: str) -> str:
    """Double-encode a text value the way Sales Nav expects.

    Inner level: spaces -> %20 (standard URL encoding).
    Outer level: the whole query string is URL-encoded again, so %20 -> %2520.

    We do both passes here so the caller doesn't have to think about it.
    """
    inner = urllib.parse.quote(value, safe="-")
    return inner.replace("%", "%25")


# Items can be either:
#   - a plain string                         → renders as (text:X,selectionType:INCLUDED)
#   - a tuple (id, text)                     → renders as (id:X,text:Y,selectionType:INCLUDED)
Item = Union[str, Tuple[str, str]]


def render_item(item: Item) -> str:
    """Render one filter item — either text-only or id+text format."""
    if isinstance(item, tuple):
        item_id, text = item
        return (
            f"(id%3A{encode_text_value(item_id)}"
            f"%2Ctext%3A{encode_text_value(text)}"
            f"%2CselectionType%3AINCLUDED)"
        )
    return f"(text%3A{encode_text_value(item)}%2CselectionType%3AINCLUDED)"


def render_filter(filter_type: str, values: List[Item]) -> str:
    """Render one filter tuple `(type%3AX%2Cvalues%3AList(...))`."""
    if filter_type not in KNOWN_FILTER_TYPES:
        print(
            f"WARN: filter type {filter_type!r} is not in the known list — "
            f"Sales Nav may ignore it. Known: {sorted(KNOWN_FILTER_TYPES)}",
            file=sys.stderr,
        )
    items_str = "%2C".join(render_item(v) for v in values)
    return f"(type%3A{filter_type}%2Cvalues%3AList({items_str}))"


def build_url(filters: List[Tuple[str, List[Item]]], *, keywords: Optional[str] = None) -> str:
    """Assemble the final Sales Nav people-search URL using #query= hash fragment."""
    pieces: List[str] = []

    if keywords:
        encoded_kw = encode_text_value(keywords)
        pieces.append(f"keywords%3A{encoded_kw}")

    if filters:
        rendered = "%2C".join(render_filter(t, v) for t, v in filters)
        pieces.append(f"filters%3AList({rendered})")

    if not pieces:
        raise ValueError("Need at least one of: filters, keywords")

    query_value = "(" + "%2C".join(pieces) + ")"
    # Sales Nav uses a HASH FRAGMENT (#query=), not a query string (?query=).
    # The query-string form silently drops filters on page load.
    return f"https://www.linkedin.com/sales/search/people#query={query_value}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_paren_balance(url: str) -> Tuple[int, int, bool]:
    """Count `(` and `)` in the URL. Returns (opens, closes, balanced)."""
    opens = url.count("(")
    closes = url.count(")")
    return opens, closes, opens == closes


def diagnose(url: str, filters: List[Tuple[str, List[Item]]], options: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable diagnostic lines."""
    out = []
    opens, closes, balanced = validate_paren_balance(url)
    out.append(f"Paren balance: {opens} opens, {closes} closes — {'OK' if balanced else 'MISMATCH'}")
    out.append(f"URL length: {len(url):,} chars")
    if len(url) > 8000:
        out.append("  WARN: URL exceeds 8 kB — some browsers/servers may truncate. Consider splitting into 2 saved searches.")
    elif len(url) > 4000:
        out.append("  Note: URL is large but should still load in modern browsers.")

    out.append(f"Filters: {len(filters)}")
    for ftype, vals in filters:
        out.append(f"  {ftype}: {len(vals)} values")
        warn = options.get("warn_above_titles", 70)
        if ftype in ("CURRENT_TITLE", "PAST_TITLE") and len(vals) > warn:
            out.append(f"    WARN: {len(vals)} titles exceeds soft limit ({warn}). Sales Nav may silently drop some.")

    return out


# ---------------------------------------------------------------------------
# Translation helpers — geography, headcount, seniority
# ---------------------------------------------------------------------------

def translate_geographies(geographies: List[str]) -> Tuple[List[Item], List[Item]]:
    """Build the GEOGRAPHY (text-only URN IDs) and REGION (id+text pairs) item
    lists from a list of country names or raw URN IDs.

    Sales Nav requires BOTH filters to be populated:
      - GEOGRAPHY renders the location chips visually
      - REGION is the actual operational filter that narrows results

    Returns (geography_items, region_items). Either may be empty if input was
    incomplete.
    """
    geo_items: List[Item] = []
    region_items: List[Item] = []
    for raw in geographies:
        country = raw.strip()
        if not country:
            continue
        # Numeric URN ID passed directly — emit GEOGRAPHY only (no name for REGION)
        if country.isdigit():
            geo_items.append(country)
            print(
                f"WARN: geography {country!r} is a numeric URN ID with no name lookup — "
                f"GEOGRAPHY chip will render but REGION filter (which actually narrows "
                f"results) needs a country name. Add it to COUNTRY_TO_URN.",
                file=sys.stderr,
            )
            continue
        urn = COUNTRY_TO_URN.get(country)
        if not urn:
            print(
                f"WARN: country {country!r} not found in COUNTRY_TO_URN — skipping. "
                f"Add it to the lookup or pass the URN ID directly.",
                file=sys.stderr,
            )
            continue
        geo_items.append(urn)
        region_items.append((urn, country))
    return geo_items, region_items


def translate_headcount(ranges: List[str]) -> List[Item]:
    """Translate range strings ("1-10", "11-50", ...) to id+text items.

    Accepts either the human range or the raw letter code (B/C/D/...).
    Returns a list of (code, range) tuples ready for the COMPANY_HEADCOUNT filter.
    """
    items: List[Item] = []
    code_to_range = {v: k for k, v in HEADCOUNT_TO_CODE.items()}
    for raw in ranges:
        v = raw.strip()
        if not v:
            continue
        if v in HEADCOUNT_TO_CODE:
            items.append((HEADCOUNT_TO_CODE[v], v))
        elif v in code_to_range:
            items.append((v, code_to_range[v]))
        else:
            print(
                f"WARN: headcount value {v!r} not in HEADCOUNT_TO_CODE — skipping. "
                f"Valid: {sorted(HEADCOUNT_TO_CODE.keys())}",
                file=sys.stderr,
            )
    return items


def translate_seniorities(seniorities: List[str]) -> List[Item]:
    """Translate seniority names ("VP", "Director", ...) to id+text items.

    Returns a list of (id, canonical_text) tuples ready for the SENIORITY_LEVEL filter.
    """
    items: List[Item] = []
    for raw in seniorities:
        v = raw.strip()
        if not v:
            continue
        entry = SENIORITY_TO_ID.get(v)
        if not entry:
            print(
                f"WARN: seniority {v!r} not in SENIORITY_TO_ID — skipping. "
                f"Valid: {sorted(SENIORITY_TO_ID.keys())}",
                file=sys.stderr,
            )
            continue
        items.append(entry)
    return items


# ---------------------------------------------------------------------------
# Config -> filter list
# ---------------------------------------------------------------------------

def config_to_filters(config: Dict[str, Any]) -> Tuple[List[Tuple[str, List[Item]]], Optional[str]]:
    """Translate a config dict into an ordered list of (filter_type, values) tuples."""
    options = config.get("options", {})
    keep_parens = options.get("keep_parens_in_titles", False)
    keep_emdash = options.get("keep_emdash_in_titles", False)

    filters: List[Tuple[str, List[Item]]] = []

    if config.get("companies"):
        ftype = config.get("company_filter", "CURRENT_COMPANY")
        vals = dedupe_preserving_order(sanitise_company(c) for c in config["companies"])
        if vals:
            filters.append((ftype, vals))

    if config.get("titles"):
        ftype = config.get("title_filter", "CURRENT_TITLE")
        vals = dedupe_preserving_order(
            sanitise_title(t, keep_parens=keep_parens, keep_emdash=keep_emdash)
            for t in config["titles"]
        )
        if vals:
            filters.append((ftype, vals))

    if config.get("geographies"):
        geo_items, region_items = translate_geographies(config["geographies"])
        if geo_items:
            filters.append(("GEOGRAPHY", dedupe_preserving_order(geo_items)))
        if region_items:
            filters.append(("REGION", dedupe_preserving_order(region_items)))

    if config.get("industries"):
        vals = dedupe_preserving_order(i.strip() for i in config["industries"])
        if vals:
            filters.append(("INDUSTRY", vals))

    if config.get("seniorities"):
        seniority_items = translate_seniorities(config["seniorities"])
        if seniority_items:
            filters.append(("SENIORITY_LEVEL", dedupe_preserving_order(seniority_items)))

    if config.get("company_headcount"):
        headcount_items = translate_headcount(config["company_headcount"])
        if headcount_items:
            filters.append(("COMPANY_HEADCOUNT", dedupe_preserving_order(headcount_items)))

    for ftype, vals in (config.get("extra_filters") or {}).items():
        cleaned = dedupe_preserving_order(v.strip() if isinstance(v, str) else v for v in vals)
        if cleaned:
            filters.append((ftype, cleaned))

    keywords = config.get("keywords")
    return filters, keywords


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def split_csv_arg(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="Path to JSON config file")
    parser.add_argument("--companies", help="Comma-separated company names (alt to --config)")
    parser.add_argument("--titles", help="Comma-separated titles (alt to --config)")
    parser.add_argument("--title-type", default="CURRENT_TITLE", choices=["CURRENT_TITLE", "PAST_TITLE"])
    parser.add_argument("--company-type", default="CURRENT_COMPANY", choices=["CURRENT_COMPANY", "PAST_COMPANY"])
    parser.add_argument("--geographies", help="Comma-separated country names (auto-translated to GEOGRAPHY+REGION)")
    parser.add_argument("--industries", help="Comma-separated industry filter values")
    parser.add_argument("--seniorities", help="Comma-separated seniority names (auto-translated to SENIORITY_LEVEL)")
    parser.add_argument("--company-headcount", dest="company_headcount", help="Comma-separated headcount ranges (e.g. '1-10,11-50,51-200')")
    parser.add_argument("--keywords", help="Free-text keywords filter")
    parser.add_argument("--keep-parens", action="store_true", help="Keep parentheticals in titles (default: strip)")
    parser.add_argument("--keep-emdash", action="store_true", help="Keep em/en dashes in titles (default: strip)")
    parser.add_argument("--quiet", action="store_true", help="Print only the URL, no diagnostics")
    args = parser.parse_args(argv)

    if args.config:
        config = json.loads(args.config.read_text())
    else:
        config = {
            "companies": split_csv_arg(args.companies),
            "titles": split_csv_arg(args.titles),
            "company_filter": args.company_type,
            "title_filter": args.title_type,
            "geographies": split_csv_arg(args.geographies),
            "industries": split_csv_arg(args.industries),
            "seniorities": split_csv_arg(args.seniorities),
            "company_headcount": split_csv_arg(args.company_headcount),
            "keywords": args.keywords,
            "options": {
                "keep_parens_in_titles": args.keep_parens,
                "keep_emdash_in_titles": args.keep_emdash,
            },
        }

    filters, keywords = config_to_filters(config)

    if not filters and not keywords:
        print("ERROR: no filters and no keywords — nothing to build.", file=sys.stderr)
        return 2

    url = build_url(filters, keywords=keywords)

    if not args.quiet:
        print("=" * 60, file=sys.stderr)
        for line in diagnose(url, filters, config.get("options", {})):
            print(line, file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
