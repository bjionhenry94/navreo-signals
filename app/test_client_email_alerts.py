"""Client positive-reply EMAIL lane + Slack opt-out (Settings → Clients)."""
import datetime as dt
import os
import sys
import setter

FAILS = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {info}"))
    if not cond:
        FAILS.append(name)

now = dt.datetime.now(dt.timezone.utc)
iso = lambda m: (now - dt.timedelta(minutes=m)).isoformat()
STORE = {"blob": None}
LOG = []
REPLIES = [
    {"id": 1, "workspace": "grout", "smartlead_campaign_id": 11, "email": "a@x.com",
     "replied_at": iso(5), "category": "Interested", "reply_body": "Yes keen\nOn Mon Bob wrote:\n> hi",
     "smartlead_message_id": "m1"},
    {"id": 2, "workspace": "krg", "smartlead_campaign_id": 12, "email": "b@y.com",
     "replied_at": iso(5), "category": "Interested", "reply_body": "sure", "smartlead_message_id": "m2"},
    {"id": 3, "workspace": "grout", "smartlead_campaign_id": 11, "email": "old@x.com",
     "replied_at": iso(60 * 24 * 10), "category": "Interested", "reply_body": "old", "smartlead_message_id": "m3"},
]

def sb(method, path, body=None, prefer=None):
    if path.startswith("deliverability_audit_cache"):
        if method == "GET":
            return [{"blob": STORE["blob"]}] if STORE["blob"] else []
        STORE["blob"] = body["blob"]; return None
    if path.startswith("app_activity_log"):
        return [{"entity_id": e["id"]} for e in LOG]
    if path.startswith("replies?") and "replied_at=lt." in path:
        return []                       # no prior positives
    if path.startswith("replies?"):
        return [r for r in REPLIES if (now - dt.datetime.fromisoformat(r["replied_at"])).days < 3]
    return []

setter._SB = sb
setter._LOG = lambda ep, payload, actor=None, action=None, entity=None, entity_id=None: \
    LOG.append({"id": entity_id, "action": action, "payload": payload})
setter._alert_lead_facts = lambda cid, email: {"name": "Ann Lee", "company": "Acme", "title": "CEO"}
setter._client_chat_link = lambda e, c, m="": "https://app.navreo.ai/app/setter.html?x"
setter._client_dashboard_link = lambda c: ""
SENT = []
setter._send_client_email = lambda to, subj, text, html: SENT.append((to, subj, text))
os.environ["NOTIFY_SMTP_PASSWORD"] = "x"

check("default mode is slack", setter.client_notify_mode("grout") == "slack")
check("email mode needs an address", not setter.client_notify_set("grout", "email", "")["ok"])
check("bad address rejected", not setter.client_notify_set("grout", "email", "nope")["ok"])
check("navreo is not a client", not setter.client_notify_set("navreo", "slack", [])["ok"])
r = setter.client_notify_set("grout", "email", "bjion@navreo.ai, BJION@navreo.ai")
check("save ok + dedup/lowercase", r["ok"] and r["pref"]["emails"] == ["bjion@navreo.ai"], r)
check("email-only turns Slack off", not setter.client_slack_enabled("grout"))
check("krg untouched keeps Slack", setter.client_slack_enabled("krg"))

# enabled_at is 'now' → the 5-min-old reply predates it; backdate to test sending
STORE["blob"]["clients"]["grout"]["email_enabled_at"] = iso(30)
setter._CN_CACHE.update({"at": 0.0, "prefs": None})
res = setter.run_client_positive_emails()
check("one email sent (grout only, krg not opted in)", res["emailed"] == 1 and len(SENT) == 1, res)
check("subject names the lead", SENT and SENT[0][1] == "New positive reply: Ann Lee at Acme", SENT)
check("quoted thread stripped", SENT and "Yes keen" in SENT[0][2] and "Bob wrote" not in SENT[0][2])
check("marked in activity log", LOG and LOG[0]["action"] == "client_positive_email_sent")
res2 = setter.run_client_positive_emails()
check("second tick never re-sends", res2["emailed"] == 0 and len(SENT) == 1, res2)

# a lead already positive replies again -> emailed as "replied again"
REPLIES.append({"id": 4, "workspace": "grout", "smartlead_campaign_id": 11, "email": "a@x.com",
                "replied_at": iso(2), "category": "positive-re-reply", "reply_body": "Tuesday works",
                "smartlead_message_id": "m4"})
_orig_sb = setter._SB
setter._SB = lambda m, p, b=None, prefer=None: (
    [{"category": "Interested", "replied_at": iso(5)}]
    if p.startswith("replies?") and "replied_at=lt." in p and "a%40x.com" in p
    else _orig_sb(m, p, b, prefer))
res3 = setter.run_client_positive_emails()
check("re-reply is emailed", res3["emailed"] == 1 and len(SENT) == 2, res3)
check("re-reply subject says replied again", SENT[-1][1] == "Ann Lee at Acme replied again", SENT[-1][1])
check("re-reply body says ongoing conversation", "ongoing conversation" in SENT[-1][2])
setter._SB = _orig_sb

setter.client_notify_set("grout", "both", ["bjion@navreo.ai"])
check("both keeps Slack on", setter.client_slack_enabled("grout"))
setter.client_notify_set("grout", "none", [])
check("none turns Slack off", not setter.client_slack_enabled("grout"))
del os.environ["NOTIFY_SMTP_PASSWORD"]
setter.client_notify_set("krg", "email", ["bjion@navreo.ai"])
check("no SMTP password → skipped loudly", setter.run_client_positive_emails().get("error"))
print("\n%d failure(s)" % len(FAILS)); sys.exit(1 if FAILS else 0)
