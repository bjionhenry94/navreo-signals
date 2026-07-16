"""compose_positive_card_payload — the pure half of the categoriser→card-hook
bypass. The payload must carry every field Make scenario 8946472 references
(audited from the live blueprint 2026-07-16): lead_data.{email,first_name,
last_name,company_name,website,linkedin_profile,location,custom_fields.role},
campaign_name, client_id, history (type+email_body), last_reply, app_url,
lead_id, from_email, lead_category.new_name — plus navreo_source, the marker
8946472 requires on LEAD_CATEGORY_UPDATED events so Smartlead's hours-late
native deliveries can never double-post."""
import unittest

import server


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


if __name__ == "__main__":
    unittest.main()
