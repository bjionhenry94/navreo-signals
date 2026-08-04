"""role_filter — is a prospect's job title an OUTBOUND/GTM decision-maker?

Runs server-side at pull/upload time so tech-stack (and any "are you doing outreach?"
angle) lists never email a Head of Legal / HR / Engineering. Autonomous: no local
state, pure function of the title string. Bjion 2026-08-04 (stack campaign 3760383 was
emailing "assumed you might be doing outreach" to 60%+ non-sales roles).

Three buckets:
  "owner"     — clear sales/marketing/growth/revenue/BD/GTM/commercial OR a general
                leader (CEO/Founder/Owner/President) with no non-sales scope. KEEP.
  "non_owner" — a clear non-sales FUNCTION scopes the title (legal, HR, engineering,
                product, finance, operations, IT, delivery, design, research, audit,
                support, procurement). PAUSE / never upload for outreach angles.
  "ambiguous" — bare leadership (Director / VP / Managing Director / Exec Director /
                GM / Chief of Staff / Advisor) with no function either way. KEEP by
                default (at a small firm this is often the buyer); a stricter caller
                may choose to drop these.

classify(title) -> "owner" | "non_owner" | "ambiguous"
is_outreach_owner(title, *, keep_ambiguous=True) -> bool
"""
import re

_OWNER_FN = [
    "sales", "marketing", "growth", "revenue", "business development", "biz dev",
    "bdr", "sdr", "demand gen", "demand generation", "gtm", "go-to-market",
    "go to market", "commercial", "brand", "customer acquisition", "lead gen",
    "lead generation", "outbound", "account executive", "account exec",
    "partnerships", "partnership", "cmo", "cro", "chief revenue", "chief marketing",
    "chief growth", "chief commercial", "chief sales",
]
# a clear non-sales FUNCTION — pause these even if a leadership word is present
_NON_OWNER_FN = [
    "legal", "counsel", "compliance", "human resource", "people officer", "head of people",
    "talent", "recruit", "recruiting", "information technology", "it services",
    "it consulting", "it director", "it manager", "engineer", "engineering",
    "developer", "software", "product manager", "product management", "head of product",
    "vp product", "chief product", "operations", "operational", "chief operating",
    "coo", "finance", "financial", "accounting", "controller", "treasur", "cfo",
    "chief financial", "procurement", "purchasing", "supply chain", "logistics",
    "delivery", "service delivery", "chief delivery", "research", "scientist",
    "customer success", "customer service", "customer support", "support",
    "office manager", "administrative", "quality", "hse", "health and safety",
    "facilities", "creative", "designer", "design ", "head of design", "clinical",
    "medical", "nursing", "data science", "data engineer", "analytics", "audit",
    "reinsurance", "claims", "actuar", "landscape", "architecture", "cto", "cio",
    "chro", "clo", "chief technology", "chief information", "chief people",
    "chief human", "project management", "program manager", "chief of staff",
]
_GENERAL_LEADER = [
    "ceo", "chief executive", "founder", "co-founder", "cofounder", "owner",
    "managing director", "managing partner", "managing member", "geschäftsführer",
    "geschaftsfuhrer", "president", "proprietor",
]
# bare titles that carry no function signal either way
_AMBIGUOUS_ONLY = [
    "director", "vice president", "vp", "executive director", "general manager",
    "gm", "advisor", "adviser", "strategic advisor", "board member", "principal",
    "associate director", "head",
]


def _norm(title: str) -> str:
    return " " + re.sub(r"[^a-z0-9&\- ]+", " ", (title or "").lower()).strip() + " "


def _has(t: str, kw: str) -> bool:
    # word-boundary match so short acronyms (cto/coo/cfo/cro/cmo/gm/hr/it) don't
    # false-hit inside longer words — "cto" must NOT match "director".
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t) is not None


def classify(title: str) -> str:
    t = _norm(title)
    has_owner = any(_has(t, k) for k in _OWNER_FN)
    has_nonsales = any(_has(t, k) for k in _NON_OWNER_FN)
    # an explicit sales/GTM function always wins (e.g. "VP Sales & Operations")
    if has_owner and not has_nonsales:
        return "owner"
    if has_nonsales and not has_owner:
        return "non_owner"
    if has_owner and has_nonsales:
        # mixed (e.g. "Head of Sales & Delivery") — sales intent present, keep
        return "owner"
    # no function words: general leader = owner, otherwise ambiguous
    if any(_has(t, k) for k in _GENERAL_LEADER):
        return "owner"
    return "ambiguous"


def is_outreach_owner(title: str, *, keep_ambiguous: bool = True) -> bool:
    c = classify(title)
    if c == "owner":
        return True
    if c == "ambiguous":
        return keep_ambiguous
    return False
