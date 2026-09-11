"""The three positive-alert card composers - setter._ep_positive_shared_text
(client-shared), _ep_compose (internal once-positive) and _cp_compose
(client-safe positive) - all render the ONE card shape from
docs/positive-alert-card-design-2026-09-11.md (Bjion approved 2026-09-11).

What the card must NEVER carry, and what these tests police on every composer:
no "Workspace" / "(client)" internal labelling, no "---" divider, no
"Not on file" / "Role n/a" placeholders (a missing fact is OMITTED), no raw
https:// outside Slack's <url|label> syntax, no smartlead.ai link, and exactly
ONE link - the trailing "Open conversation" to app.navreo.ai.

NO network: _alert_lead_facts is stubbed, Supabase is None.
Run: python3 test_positive_card_composers.py   (exit 1 on any failure)
"""
import sys

import setter

RESULTS = []
_REAL_FACTS = setter._alert_lead_facts


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS: " if cond else "FAIL: ") + name +
          (f"\n      {extra}" if (extra and not cond) else ""))


# --- the five §1 cases, as _alert_lead_facts would return them --------------
FACTS = {
    "jl@skalestrategy.com": {
        "name": "Jason Needham", "title": "Cofounder, CEO, now Chair",
        "company": "Skale Strategy",
        "linkedin": "https://www.linkedin.com/in/jlneedham1/",
        "website": "skalestrategy.com"},
    "info@kamsah.com": {                      # company, no name  (case c)
        "name": "", "title": "", "company": "Kamsah",
        "linkedin": "", "website": "kamsah.com"},
    "kabir@infeedo.com": {                    # name, no title    (case d)
        "name": "Kabir", "title": "", "company": "inFeedo",
        "linkedin": "", "website": "infeedo.com"},
    "jane.doe@gmail.com": {},                 # free-mail, nothing (case e)
}


def wire():
    """Stub the one Smartlead read out; kill Supabase so nothing can dial."""
    setter._SB = None
    setter._FACTS_CACHE.clear()
    setter._alert_lead_facts = lambda cid, email: dict(
        FACTS.get((email or "").strip().lower(), {}))


def row(email, **kw):
    r = {"email": email, "smartlead_message_id": "m-7",
         "smartlead_campaign_id": 3879940, "category": "Interested",
         "replied_at": "2026-09-10T22:18:00+00:00", "workspace": "navreo"}
    r.update(kw)
    return r


PRIOR = {"category": "Interested", "replied_at": "2026-09-01T10:00:00+00:00",
         "smartlead_campaign_id": 3700002}
NAMES = {"3879940": "Navreo | Amazon Agencies - recontact [Sep 2026]",
         "3700002": "Navreo | Amazon C2"}


# --- the shared hygiene contract -------------------------------------------
BANNED = ("Workspace", "(client)", "---", "Not on file", "Role n/a",
          "smartlead.ai", "n/a")


def raw_urls(text):
    """Every https:// that is NOT immediately opening a Slack <url|label>."""
    out, i = [], text.find("https://")
    while i != -1:
        if i == 0 or text[i - 1] != "<":
            out.append(text[max(0, i - 12):i + 40])
        i = text.find("https://", i + 1)
    return out


def hygiene(label, text):
    for bad in BANNED:
        check(f"{label}: no {bad!r}", bad not in text, text)
    check(f"{label}: no raw https:// outside <url|label>",
          not raw_urls(text), str(raw_urls(text)))
    check(f"{label}: exactly one 'Open conversation' link",
          text.count("|Open conversation>") == 1, text)
    check(f"{label}: the one link is app.navreo.ai",
          text.count("<https://app.navreo.ai/") == 1
          and text.rstrip().endswith("|Open conversation>"), text)
    check(f"{label}: no empty <https://|> link", "<https://|" not in text, text)
    check(f"{label}: no blank line", "\n\n" not in text and not text.endswith("\n"), repr(text))
    for ln in text.split("\n"):
        check(f"{label}: no orphan separator on {ln[:28]!r}",
              not ln.strip().startswith("·") and not ln.rstrip().endswith("·")
              and "·  ·" not in ln, ln)


# --- 1. internal once-positive (_ep_compose) -------------------------------
def test_ep_compose():
    wire()
    t = setter._ep_compose(row("jl@skalestrategy.com", category="Not Interested"),
                           PRIOR, NAMES)
    want = (
        "*\U0001F501 Interested lead replied again · Skale Strategy*\n"
        "Jason Needham · Cofounder, CEO, now Chair\n"
        "✉️ jl@skalestrategy.com  ·  "
        "\U0001F310 <https://skalestrategy.com|skalestrategy.com>  ·  "
        "\U0001F517 <https://www.linkedin.com/in/jlneedham1/|LinkedIn>\n"
        "*Now* · Not interested\n"
        "*Interested since* · 1 Sep\n"
        "*Campaign* · Navreo | Amazon Agencies - recontact [Sep 2026]\n"
        "*Replied* · 10 Sep, 22:18 UTC\n"
        "\U0001F3AF <https://app.navreo.ai/app/setter.html"
        "#/r/jl%40skalestrategy.com/m-7|Open conversation>")
    check("1a internal re-reply card renders the approved shape exactly",
          t == want, repr(t))
    check("1b internal card KEEPS the Campaign line, once, and never the prior one",
          t.count("*Campaign* · ") == 1 and "Navreo | Amazon C2" not in t, t)
    check("1c a non-positive new category is named, humanised, under *Now*",
          "*Now* · Not interested" in t and "Not Interested" not in t, t)
    hygiene("1", t)
    tp = setter._ep_compose(row("jl@skalestrategy.com", category="positive-re-reply"),
                            PRIOR, NAMES)
    check("1d a positive re-reply carries NO *Now* line (nothing flipped)",
          "*Now*" not in tp and "positive-re-reply" not in tp
          and tp.startswith("*\U0001F501 Interested lead replied again"), tp)
    check("1e ...and still carries *Interested since* + Campaign",
          "*Interested since* · 1 Sep" in tp and "*Campaign* · Navreo |" in tp, tp)
    hygiene("1d", tp)
    t2 = setter._ep_compose(row("jl@skalestrategy.com", category=None),
                            {"category": "Meeting Request"}, {})
    check("1f prior with no date: the *Interested since* line is omitted",
          "*Interested since*" not in t2, t2)
    check("1g missing category falls back, never blank, never a slug",
          "*Now* · Uncategorised" in t2, t2)
    hygiene("1f", t2)


# --- 2. client-shared (_ep_positive_shared_text) ---------------------------
def test_ep_positive_shared_text():
    wire()
    t = setter._ep_positive_shared_text(row("info@kamsah.com"), "Navreo | Amazon", "x")
    want = ("*\U0001F389 New positive reply · Kamsah*\n"
            "✉️ info@kamsah.com  ·  \U0001F310 <https://kamsah.com|kamsah.com>\n"
            "*Replied* · 10 Sep, 22:18 UTC\n"
            "\U0001F3AF <https://app.navreo.ai/app/setter.html"
            "#/r/info%40kamsah.com/m-7|Open conversation>")
    check("2a company-only shared card renders the design shape exactly",
          t == want, repr(t))
    check("2b the name line is GONE, not blank", t.count("\n") == 3, repr(t))
    check("2c client card drops the Campaign line (cname passed, never rendered)",
          "Campaign" not in t and "Amazon" not in t, t)
    check("2d client card drops the category word", "Interested" not in t, t)
    hygiene("2", t)
    t2 = setter._ep_positive_shared_text(
        row("kabir@infeedo.com"), "Grout - SaaS", "",
        header="\U0001F501 Reply in ongoing conversation")
    want2 = ("*\U0001F501 Reply in ongoing conversation · inFeedo*\n"
             "Kabir\n"
             "✉️ kabir@infeedo.com  ·  \U0001F310 <https://infeedo.com|infeedo.com>\n"
             "*Replied* · 10 Sep, 22:18 UTC\n"
             "\U0001F3AF <https://app.navreo.ai/app/setter.html"
             "#/r/kabir%40infeedo.com/m-7|Open conversation>")
    check("2e re-reply header + name-without-title renders exactly", t2 == want2, repr(t2))
    check("2f re-reply wording is the conversation frame, never 'again'",
          "Reply in ongoing conversation" in t2 and "again" not in t2, t2)
    hygiene("2e", t2)


# --- 3. client positive (_cp_compose) --------------------------------------
def test_cp_compose():
    wire()
    t = setter._cp_compose(row("jl@skalestrategy.com", workspace="grout"),
                           "Grout - SaaS CEOs", "x")
    want = ("*\U0001F389 New positive reply · Skale Strategy*\n"
            "Jason Needham · Cofounder, CEO, now Chair\n"
            "✉️ jl@skalestrategy.com  ·  "
            "\U0001F310 <https://skalestrategy.com|skalestrategy.com>  ·  "
            "\U0001F517 <https://www.linkedin.com/in/jlneedham1/|LinkedIn>\n"
            "*Replied* · 10 Sep, 22:18 UTC\n"
            "\U0001F3AF <https://app.navreo.ai/app/setter.html"
            "#/r/jl%40skalestrategy.com/m-7|Open conversation>")
    check("3a client positive renders the design shape exactly", t == want, repr(t))
    check("3b the workspace word 'grout' appears nowhere", "grout" not in t.lower(), t)
    check("3c header is fixed, never the workspace/category",
          t.startswith("*\U0001F389 New positive reply ·"), t)
    hygiene("3", t)


# --- 4. worst case: nothing held on the lead -------------------------------
def test_empty_facts_worst_case():
    wire()
    for label, fn in (("shared", lambda r: setter._ep_positive_shared_text(r, "C", "")),
                      ("client", lambda r: setter._cp_compose(r, "C", ""))):
        t = fn(row("jane.doe@gmail.com", replied_at="2026-09-11T14:03:00+00:00"))
        want = ("*\U0001F389 New positive reply*\n"
                "✉️ jane.doe@gmail.com\n"
                "*Replied* · 11 Sep, 14:03 UTC\n"
                "\U0001F3AF <https://app.navreo.ai/app/setter.html"
                "#/r/jane.doe%40gmail.com/m-7|Open conversation>")
        check(f"4a[{label}] empty facts -> the 4-line worst case, exactly",
              t == want, repr(t))
        check(f"4b[{label}] four lines, none blank",
              len(t.split("\n")) == 4 and all(x.strip() for x in t.split("\n")), repr(t))
        check(f"4c[{label}] header carries no dangling separator",
              t.split("\n")[0] == "*\U0001F389 New positive reply*", t)
        hygiene(f"4[{label}]", t)


# --- 5. the shape helpers ---------------------------------------------------
def test_helpers():
    check("5a _fmt_when is '10 Sep, 22:18 UTC'",
          setter._fmt_when("2026-09-10T22:18:00+00:00") == "10 Sep, 22:18 UTC",
          setter._fmt_when("2026-09-10T22:18:00+00:00"))
    check("5b _fmt_when normalises an offset to UTC",
          setter._fmt_when("2026-09-11T00:18:00+02:00") == "10 Sep, 22:18 UTC",
          setter._fmt_when("2026-09-11T00:18:00+02:00"))
    check("5c _fmt_when never raises on junk",
          setter._fmt_when("") == "" and setter._fmt_when(None) == ""
          and setter._fmt_when("not a date") == "")
    check("5d _fmt_day is the date alone",
          setter._fmt_day("2026-09-01T10:00:00Z") == "1 Sep",
          setter._fmt_day("2026-09-01T10:00:00Z"))
    bare = setter._card_text("H", "", "", "", "a@b.com", "", "", campaign=None,
                             replied_at=None, chat_url="")
    check("5e _card_text with one fact renders two lines, no placeholders",
          bare == "*H*\n✉️ a@b.com", repr(bare))
    notitle = setter._card_text("H", "Co", "Ann", "", "a@b.com", "b.com", "",
                                replied_at="2026-09-10T22:18:00+00:00",
                                chat_url="https://app.navreo.ai/x")
    check("5f a name without a title carries no trailing separator",
          "Ann\n" in notitle and "Ann ·" not in notitle, notitle)
    check("5g extra lines land above Campaign/Replied",
          setter._card_text("H", "", "", "", "a@b.com", "", "", campaign="C",
                            extra=["*Now* · X", ""])
          == "*H*\n✉️ a@b.com\n*Now* · X\n*Campaign* · C",
          setter._card_text("H", "", "", "", "a@b.com", "", "", campaign="C",
                            extra=["*Now* · X", ""]))
    h = setter._humanise_category
    check("5h _humanise_category maps every taxonomy word we ship",
          [h(x) for x in ("positive-re-reply", "Information Request",
                          "Not Interested", "Meeting Request", "Out Of Office",
                          "Wrong Person", "Do Not Contact", "Interested")]
          == ["Positive", "Information request", "Not interested",
              "Meeting request", "Out of office", "Wrong person",
              "Do not contact", "Interested"],
          str([h(x) for x in ("positive-re-reply", "Information Request",
                              "Not Interested", "Meeting Request",
                              "Out Of Office", "Wrong Person",
                              "Do Not Contact", "Interested")]))
    check("5i an unknown category sentence-cases, never leaves a slug",
          h("some-new_category") == "Some new category"
          and h("BOUNCED") == "Bounced", f"{h('some-new_category')} / {h('BOUNCED')}")
    check("5j empty in, empty out (the caller drops the line)",
          h("") == "" and h(None) == "" and h("   ") == "")


# --- 6. _alert_lead_facts: one cached call, never raises --------------------
def test_alert_lead_facts():
    setter._alert_lead_facts = _REAL_FACTS      # wire() stubs it for the composers
    setter._SB = None
    setter._FACTS_CACHE.clear()
    calls = []
    real_get = setter._sl_get
    setter._sl_get = lambda path, params=None, campaign_id=None: (
        calls.append((path, params)) or
        {"first_name": "Jason", "last_name": "Needham",
         "company_name": "Skale Strategy", "website": "https://www.skalestrategy.com/",
         "linkedin_profile": "https://linkedin.com/in/x",
         "custom_fields": {"title": "Cofounder"}})
    try:
        f = setter._alert_lead_facts(111, "JL@Skalestrategy.com")
        check("6a name is joined from the Smartlead lead", f["name"] == "Jason Needham", str(f))
        check("6b title comes off custom_fields.title (never .role)",
              f["title"] == "Cofounder", str(f))
        check("6c website is normalised to a bare domain",
              f["website"] == "skalestrategy.com", str(f))
        setter._alert_lead_facts(111, "jl@skalestrategy.com")
        check("6d second call is cached, case-insensitively - one Smartlead read",
              len(calls) == 1, str(calls))
        setter._FACTS_CACHE.clear()
        setter._sl_get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        g = setter._alert_lead_facts(111, "someone@acme.io")
        check("6e a Smartlead failure never raises and still resolves the website",
              g["website"] == "acme.io" and g["name"] == "" and g["company"] == "", str(g))
        setter._FACTS_CACHE.clear()
        setter._sl_get = lambda *a, **k: None
        h = setter._alert_lead_facts(111, "jane.doe@gmail.com")
        check("6f free-mail with no lead record -> every field empty, no placeholder",
              h == {"name": "", "title": "", "company": "", "linkedin": "",
                    "website": ""}, str(h))
    finally:
        setter._sl_get = real_get
        setter._FACTS_CACHE.clear()


# --- 7. the re-reply header the callers pass -------------------------------
def test_caller_header_strings():
    src = open(setter.__file__, encoding="utf-8").read()
    check("7a run_ever_positive_alerts passes the conversation-frame header twice",
          src.count("Reply in ongoing conversation") == 2, "")
    check("7b the re-reply card states the fact, and the old flip wording is gone",
          src.count("Interested lead replied again") == 1
          and "Once-positive lead replied" not in src
          and "*Was positive*" not in src, "")
    check("7c no composer still calls the Smartlead master-inbox helpers",
          src.count("_ep_smartlead_link(") == 1 and src.count("_cp_smartlead_link(") == 1)


if __name__ == "__main__":
    test_ep_compose()
    test_ep_positive_shared_text()
    test_cp_compose()
    test_empty_facts_worst_case()
    test_helpers()
    test_alert_lead_facts()
    test_caller_header_strings()
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} pass")
    sys.exit(1 if bad else 0)
