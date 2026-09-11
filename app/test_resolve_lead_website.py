"""setter.resolve_lead_website - the website waterfall behind the positive-reply
alert cards (design doc docs/positive-alert-card-design-2026-09-11.md §2).

Order, stopping at the first hit: the Smartlead lead's own `website` -> its
custom fields -> Supabase setter_lead_enrichment.company_domain -> a Supabase
`companies` row keyed by the email domain (the DOMAIN KEY only, never the
polluted `name`) -> the email domain itself unless it is free-mail -> "".

The two leads that motivated this (jl@skalestrategy.com, info@kamsah.com) both
had a blank Smartlead website and a correct setter_lead_enrichment row, which
is why step 3 exists.
"""
import unittest

import server
import setter


class FakeSB:
    """Stands in for the module's _SB helper. `rows` maps a table name to the
    rows a GET returns; every query string is recorded so a test can prove
    which columns were asked for (and that `companies.name` never was)."""

    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []

    def __call__(self, method, path, *a, **kw):
        self.calls.append(path)
        table = path.split("?")[0]
        return self.rows.get(table, [])


class WaterfallTests(unittest.TestCase):
    def setUp(self):
        self._sb = setter._SB
        setter._WEBSITE_CACHE.clear()

    def tearDown(self):
        setter._SB = self._sb
        setter._WEBSITE_CACHE.clear()

    # 1 ── Smartlead's own field wins, and never costs a Supabase read
    def test_smartlead_website_wins(self):
        sb = FakeSB({"setter_lead_enrichment": [{"company_domain": "wrong.com"}]})
        setter._SB = sb
        d, src = setter.resolve_lead_website_traced(
            {"website": "https://www.Kamsah.com/shop/", "custom_fields": {"website": "other.com"}},
            "info@kamsah.com")
        self.assertEqual(d, "kamsah.com")
        self.assertEqual(src, "lead_website")
        self.assertEqual(sb.calls, [])

    # 2 ── custom fields, any casing/spacing, when the website field is empty
    def test_custom_field_when_website_empty(self):
        setter._SB = FakeSB()
        self.assertEqual(setter.resolve_lead_website(
            {"website": "", "custom_fields": {"Website": "acme.io"}}, "a@gmail.com"), "acme.io")
        setter._WEBSITE_CACHE.clear()
        self.assertEqual(setter.resolve_lead_website(
            {"custom_fields": {"Company Website": "http://beta.co.uk/x"}}, "b@gmail.com"), "beta.co.uk")
        setter._WEBSITE_CACHE.clear()
        self.assertEqual(setter.resolve_lead_website(
            {"custom_fields": {"company_url": "gamma.dev"}}, "c@gmail.com"), "gamma.dev")
        setter._WEBSITE_CACHE.clear()
        self.assertEqual(setter.resolve_lead_website(
            {"custom_fields": {"domain": "delta.ai"}}, "d@gmail.com"), "delta.ai")

    def test_junk_custom_field_falls_through(self):
        setter._SB = FakeSB()
        # "Not on file" is not a domain: fall through to the email domain.
        self.assertEqual(setter.resolve_lead_website(
            {"custom_fields": {"website": "Not on file"}}, "x@realco.com"), "realco.com")

    # 3 ── our own enrichment table: the step that fixes the two live leads
    def test_enrichment_table_domain(self):
        sb = FakeSB({"setter_lead_enrichment": [{"company_domain": "skalestrategy.com"}]})
        setter._SB = sb
        d, src = setter.resolve_lead_website_traced({}, "jl@SkaleStrategy.com")
        self.assertEqual(d, "skalestrategy.com")
        self.assertEqual(src, "enrichment")
        self.assertTrue(any("setter_lead_enrichment?lead_email=eq.jl%40skalestrategy.com" in c
                            for c in sb.calls), sb.calls)

    def test_enrichment_beats_email_domain(self):
        # A free-mail replier whose real company we enriched still gets a website.
        setter._SB = FakeSB({"setter_lead_enrichment": [{"company_domain": "bohoplume.pl"}]})
        self.assertEqual(setter.resolve_lead_website({}, "someone@gmail.com"), "bohoplume.pl")

    # 4 ── companies: the DOMAIN key, never the name
    def test_companies_domain_key_never_name(self):
        sb = FakeSB({"setter_lead_enrichment": [],
                     "companies": [{"domain": "skalestrategy.com", "name": "Consensus"}]})
        setter._SB = sb
        d, src = setter.resolve_lead_website_traced({}, "jl@skalestrategy.com")
        self.assertEqual(d, "skalestrategy.com")
        self.assertEqual(src, "companies")
        self.assertNotIn("consensus", d.lower())
        comp = [c for c in sb.calls if c.startswith("companies?")]
        self.assertEqual(len(comp), 1, sb.calls)
        self.assertIn("select=domain&", comp[0])
        self.assertNotIn("name", comp[0])

    # 5 ── the email domain itself
    def test_email_domain_fallback(self):
        setter._SB = FakeSB()
        d, src = setter.resolve_lead_website_traced({}, "Info@Kamsah.com")
        self.assertEqual(d, "kamsah.com")
        self.assertEqual(src, "email_domain")

    def test_no_supabase_still_answers(self):
        setter._SB = None
        self.assertEqual(setter.resolve_lead_website({}, "a@realco.com"), "realco.com")

    # 6 ── free-mail is never a company website
    def test_freemail_returns_empty(self):
        setter._SB = FakeSB()
        for e in ("jane.doe@gmail.com", "x@yahoo.co.uk", "y@gmx.de", "z@yandex.ru",
                  "p@proton.me", "q@icloud.com", "r@mail.com", "s@outlook.com"):
            setter._WEBSITE_CACHE.clear()
            self.assertEqual(setter.resolve_lead_website({}, e), "", e)

    def test_freemail_stems_do_not_eat_real_companies(self):
        setter._SB = FakeSB()
        for e, want in (("a@live-nation.com", "live-nation.com"),
                        ("b@mail.acme.com", "mail.acme.com"),
                        ("c@zohocorp.com", "zohocorp.com")):
            setter._WEBSITE_CACHE.clear()
            self.assertEqual(setter.resolve_lead_website({}, e), want, e)

    def test_empty_email_and_garbage_never_raise(self):
        setter._SB = FakeSB()
        self.assertEqual(setter.resolve_lead_website({}, ""), "")
        self.assertEqual(setter.resolve_lead_website(None, None), "")
        self.assertEqual(setter.resolve_lead_website({}, "not-an-email"), "")

    # 7 ── _norm_domain
    def test_norm_domain_strips_and_rejects(self):
        cases = {
            "https://www.Kamsah.com/": "kamsah.com",
            "HTTP://SKALESTRATEGY.COM/a/b?x=1#f": "skalestrategy.com",
            "www.acme.co.uk": "acme.co.uk",
            "  Acme.io  ": "acme.io",
            "acme.io:8080/path": "acme.io",
            "jl@skalestrategy.com": "skalestrategy.com",
            "acme.io.": "acme.io",
            "n/a": "",
            "Not on file": "",
            "TBC": "",
            "localhost": "",
            "": "",
            None: "",
            "-": "",
        }
        for raw, want in cases.items():
            self.assertEqual(setter._norm_domain(raw), want, repr(raw))

    # 8 ── cache
    def test_cache_hit_skips_supabase(self):
        sb = FakeSB({"setter_lead_enrichment": [{"company_domain": "kamsah.com"}]})
        setter._SB = sb
        self.assertEqual(setter.resolve_lead_website({}, "info@kamsah.com"), "kamsah.com")
        n = len(sb.calls)
        self.assertTrue(n >= 1)
        d, src = setter.resolve_lead_website_traced({}, "info@kamsah.com")
        self.assertEqual(d, "kamsah.com")
        self.assertEqual(src, "cache:enrichment")
        self.assertEqual(len(sb.calls), n, "a cache hit must not re-read Supabase")

    def test_cache_is_capped(self):
        setter._SB = FakeSB()
        for i in range(setter._WEBSITE_CACHE_CAP + 50):
            setter._website_cache_put(f"u{i}@x.com", "x.com", "email_domain")
        self.assertLessEqual(len(setter._WEBSITE_CACHE), setter._WEBSITE_CACHE_CAP)

    def test_miss_expires_sooner_than_a_hit(self):
        self.assertLess(setter._WEBSITE_TTL_MISS, setter._WEBSITE_TTL_HIT)
        setter._WEBSITE_CACHE["a@b.com"] = (0.0, "", "none")           # stale miss
        self.assertIsNone(setter._website_cache_get("a@b.com"))


class CardPayloadWiringTests(unittest.TestCase):
    """The client card (Make 8946472) reads lead_data.website - it must come
    from the waterfall, not the raw Smartlead field."""

    def setUp(self):
        self._sb = setter._SB
        setter._SB = None            # no Supabase in the test -> email-domain step
        setter._WEBSITE_CACHE.clear()

    def tearDown(self):
        setter._SB = self._sb
        setter._WEBSITE_CACHE.clear()

    def _payload(self, lead):
        return server.compose_positive_card_payload(
            lead, [{"type": "REPLY", "time": "2026-09-11T09:42:00.000Z",
                    "email_body": "<p>yes</p>", "stats_id": "s", "message_id": "<m>"}],
            3507001, "Interested")

    def test_blank_smartlead_website_still_lands_on_the_card(self):
        p = self._payload({"id": 1, "email": "info@kamsah.com", "website": "",
                           "custom_fields": {}})
        self.assertEqual(p["lead_data"]["website"], "kamsah.com")

    def test_custom_field_website_lands_on_the_card(self):
        p = self._payload({"id": 1, "email": "someone@gmail.com", "website": "",
                           "custom_fields": {"Company Website": "https://www.acme.io/"}})
        self.assertEqual(p["lead_data"]["website"], "acme.io")

    def test_freemail_with_nothing_held_renders_no_website(self):
        p = self._payload({"id": 1, "email": "jane.doe@gmail.com", "website": "",
                           "custom_fields": {}})
        self.assertEqual(p["lead_data"]["website"], "")


if __name__ == "__main__":
    unittest.main()
