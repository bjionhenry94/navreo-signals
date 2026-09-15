"""compose_positive_card_payload — the pure half of the categoriser→card-hook
bypass. The payload must carry every field Make scenario 8946472 references
(audited from the live blueprint 2026-07-16): lead_data.{email,first_name,
last_name,company_name,website,linkedin_profile,location,custom_fields.role},
campaign_name, client_id, history (type+email_body), last_reply, app_url,
lead_id, from_email, lead_category.new_name — plus navreo_source, the marker
8946472 requires on LEAD_CATEGORY_UPDATED events so Smartlead's hours-late
native deliveries can never double-post."""
import unittest
from urllib.parse import unquote

import server
import setter


LEAD = {
    "id": 4012418253,
    "email": "hola@dulceafro.com",
    "first_name": "Dulce",
    "last_name": "afro team",
    "company_name": "Dulce afro",
    "website": "dulceafro.com",
    "linkedin_profile": "",
    "location": "",
    "phone_number": "",
    "custom_fields": {"role": "Owner"},
    "lead_campaign_data": [
        {"campaign_id": 3507001, "campaign_name": "Amplifyy - Not on Amazon (Soft) - StoreLead - NEW",
         "campaign_status": "ACTIVE", "client_id": 429350, "campaign_lead_map_id": 3259617259,
         "lead_category_id": 5},
        {"campaign_id": 3477409, "campaign_name": "Navreo | Latka | Saas",
         "campaign_status": "ACTIVE", "client_id": None, "campaign_lead_map_id": 111,
         "lead_category_id": None},
    ],
}

HISTORY = [
    {"type": "SENT", "time": "2026-07-15T07:45:00.000Z", "subject": "hi",
     "email_body": "<p>first outreach</p>", "stats_id": "s1", "message_id": "<m1>"},
    {"type": "REPLY", "time": "2026-07-15T17:41:28.000Z", "subject": "re: hi",
     "email_body": "<p>we are interested</p>", "stats_id": "s2", "message_id": "<m2>"},
]


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.p = server.compose_positive_card_payload(LEAD, HISTORY, 3507001, "Information Request")

    def test_marker_and_event_type(self):
        self.assertEqual(self.p["navreo_source"], "categoriser")
        self.assertEqual(self.p["event_type"], "LEAD_CATEGORY_UPDATED")

    def test_campaign_scoped_fields(self):
        # Fields must come from the reply's OWN campaign row, not a sibling's
        # (the cross-campaign gate bug class).
        self.assertEqual(self.p["campaign_name"], "Amplifyy - Not on Amazon (Soft) - StoreLead - NEW")
        self.assertEqual(self.p["client_id"], 429350)
        self.assertIn("leadMap=3259617259", self.p["app_url"])

    def test_every_8946472_reference_present(self):
        ld = self.p["lead_data"]
        for k in ("email", "first_name", "last_name", "company_name", "website",
                  "linkedin_profile", "location", "custom_fields"):
            self.assertIn(k, ld)
        self.assertEqual(ld["custom_fields"]["role"], "Owner")
        for k in ("app_url", "campaign_name", "from_email", "lead_id", "history",
                  "last_reply", "lead_category"):
            self.assertIn(k, self.p)
        self.assertEqual(self.p["lead_category"]["new_name"], "Information Request")

    def test_history_shape_drives_header_math(self):
        # 8946472's header does: length(history) - count(type==SENT) > 1 → 🔁.
        # One SENT + one REPLY here → 1 lead-reply → "New Positive Response".
        h = self.p["history"]
        self.assertEqual([m["type"] for m in h], ["SENT", "REPLY"])
        self.assertTrue(all("email_body" in m for m in h))
        lead_replies = len(h) - len([m for m in h if m["type"] == "SENT"])
        self.assertEqual(lead_replies, 1)

    def test_last_reply_is_newest_reply(self):
        self.assertEqual(self.p["last_reply"]["time"], "2026-07-15T17:41:28.000Z")
        self.assertIn("interested", self.p["last_reply"]["email_body"])
        self.assertEqual(self.p["reply_message"]["text"].strip(), "we are interested")

    def test_missing_campaign_row_degrades_not_crashes(self):
        p = server.compose_positive_card_payload(LEAD, HISTORY, 999, "Interested")
        self.assertEqual(p["campaign_name"], "")
        self.assertIsNone(p["client_id"])
        self.assertEqual(p["app_url"], "")

    def test_empty_history_degrades_not_crashes(self):
        p = server.compose_positive_card_payload(LEAD, [], 3507001, "Interested")
        self.assertEqual(p["history"], [])
        self.assertEqual(p["last_reply"]["email_body"], "")


class FakeSB:
    """In-memory campaign_drafts / campaigns registry for the client share map
    (same shape as test_client_share_links.FakeSB). No network."""
    def __init__(self, drafts, registry):
        self.drafts, self.registry = drafts, registry

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        if table == "campaign_drafts":
            return [dict(d) for d in self.drafts]
        if table == "campaigns":
            return [dict(r) for r in self.registry]
        return []


class ClientLinkTests(unittest.TestCase):
    """`setter_url` is the CLIENT share link (2026-09-15). 8946472 renders it
    on its per-client cards only, and Altius Reach (Kirsty) hit the login page
    off the owner permalink it used to carry - "anyone with the link can visit
    it and access it" is the goal."""

    def setUp(self):
        self._saved = (setter._SB, setter._KEYS)
        setter._SB = FakeSB(
            [{"id": "camp-sl-3507001", "client_id": "amplifyy", "name": "Amplifyy - Not on Amazon (Soft)"}],
            [{"workspace": "navreo", "smartlead_campaign_id": 3812255, "client_id": "navreo",
              "name": "Altius Reach - Camp 1 - Fund Deal Teams"}])
        setter._KEYS = {"SUPABASE_SERVICE_ROLE_KEY": "test-secret"}
        setter._CLIENT_CAMPAIGNS_CACHE.update({"at": 0.0, "map": None})
        setter._PARENT_CACHE.update({"at": 0.0, "map": None})

    def tearDown(self):
        setter._SB, setter._KEYS = self._saved
        setter._CLIENT_CAMPAIGNS_CACHE.update({"at": 0.0, "map": None})

    @staticmethod
    def _token(url):
        return unquote(url.split("?share=", 1)[1].split("#", 1)[0])

    def test_setter_url_is_the_client_share_link(self):
        p = server.compose_positive_card_payload(LEAD, HISTORY, 3507001, "Interested")
        url = p["setter_url"]
        self.assertIn("/app/setter.html?share=", url)
        self.assertLess(url.index("?share="), url.index("#/r/"))   # before the hash, or the page never sees it
        self.assertTrue(url.endswith("#/r/hola%40dulceafro.com/%3Cm2%3E"), url)
        self.assertEqual(setter.verify_client_share(self._token(url)), ("amplifyy", False))
        self.assertEqual(p["owner_setter_url"], setter._chat_permalink("hola@dulceafro.com", "<m2>"))
        self.assertNotIn("share=", p["owner_setter_url"])

    def test_navreo_hosted_client_resolves_by_campaign_name(self):
        # Altius Reach lives in the navreo workspace with client_id 'navreo':
        # only the campaign NAME says whose it is (CLIENT_NAME_CLIENT_IDS).
        p = server.compose_positive_card_payload(LEAD, HISTORY, 3812255, "Interested")
        self.assertEqual(setter.verify_client_share(self._token(p["setter_url"])), ("altius reach", False))

    def test_unknown_campaign_keeps_the_owner_permalink(self):
        p = server.compose_positive_card_payload(LEAD, HISTORY, 999, "Interested")
        self.assertEqual(p["setter_url"], p["owner_setter_url"])
        self.assertNotIn("share=", p["setter_url"])
        self.assertIn("/app/setter.html#/r/hola%40dulceafro.com", p["setter_url"])


if __name__ == "__main__":
    unittest.main()
