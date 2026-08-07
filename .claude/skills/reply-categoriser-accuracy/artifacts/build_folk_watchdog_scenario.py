"""Build + install the Folk fail-safe watchdog Make scenario (webhook-triggered; a Supabase pg_cron job POSTs to hook 4251558 every 3h).

Flow: Supabase view folk_failsafe_queue (positives last 30h minus leads alerted <24h ago) -> iterate ->
folk:findPerson by email (existing connection 9252689) -> if NOT found:
  Slack alert to #interested-replies (fires FIRST, guaranteed) ->
  Smartlead lead + campaign lookups -> re-POST rebuilt EMAIL_REPLY to hook 4001002
  (pipeline 8946472 is create->find->update = idempotent).
A lead that stays missing re-alerts every 3h until fixed - nothing silent.

Usage: MAKE_TOKEN=... python3 build_folk_watchdog_scenario.py [--update SCENARIO_ID]
"""
import json, os, sys
import requests
sys.path.insert(0, "/Users/bjionhenry/.claude/skills/_shared")
from navreo_db import _env

TOKEN = os.environ["MAKE_TOKEN"]
H = {"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"}
BASE = "https://eu2.make.com/api/v2"
TEAM = 536258
FOLK_CONN = 9252689
SLACK_CONN = 9254394
SLACK_CHANNEL = "C096Q9LHQGZ"  # #interested-replies
HOOK_URL = "https://hook.eu2.make.com/qt3b07kefg9ogusrgd044qh1uae7hu27"
SUPABASE_URL = _env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _env("SUPABASE_SERVICE_ROLE_KEY")
SL_KEY = _env("SMARTLEAD_API_KEY")

HTTP_PARAMS = {"handleErrors": False, "useNewZLibDeCompress": True}
HTTP_DEFAULTS = {"qs": [], "gzip": True, "useMtls": False, "bodyType": "raw",
                 "serializeUrl": False, "shareCookies": False, "parseResponse": True,
                 "followRedirect": True, "useQuerystring": False,
                 "followAllRedirects": False, "rejectUnauthorized": True}
META_ERR = {"restore": {}, "advanced": True, "scenario": {"dlq": True}}

payload_body = json.dumps({
    "event_type": "EMAIL_REPLY",
    "lead_category": {"new_name": "Interested"},
    "campaign_name": "{{5.data.name}}",
    "campaign_id": "{{2.smartlead_campaign_id}}",
    "from_email": "{{2.email}}",
    "app_url": "https://app.smartlead.ai/app/master-inbox",
    "last_reply": {"time": "{{2.replied_at}}",
                   "email_body": "(re-pushed automatically by folk-failsafe watchdog - open the Smartlead conversation link for the reply text)"},
    "history": [{"type": "SENT", "email_body": ""}],
    "lead_id": "{{4.data.id}}",
    "sl_email_lead_id": "{{4.data.id}}",
    "lead_data": {"first_name": "{{4.data.first_name}}", "last_name": "{{4.data.last_name}}",
                  "company_name": "{{4.data.company_name}}", "email": "{{4.data.email}}",
                  "website": "{{4.data.website}}", "linkedin_profile": "{{4.data.linkedin_profile}}",
                  "location": "{{4.data.location}}", "custom_fields": {"role": ""}},
})

blueprint = {
    "name": "folk-failsafe-watchdog",
    "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 10, "autoCommit": True,
                 "autoCommitTriggerLast": True, "sequential": False, "confidential": False,
                 "dataloss": False, "dlq": True, "freshVariables": False}},
    "flow": [
        {"id": 8, "module": "gateway:CustomWebHook", "version": 1,
         "parameters": {"hook": 4251558, "maxResults": 1},
         "metadata": {"designer": {"x": -300, "y": 0}, "restore": {}},
         "mapper": {}},
        {"id": 1, "module": "http:ActionSendData", "version": 3,
         "parameters": HTTP_PARAMS,
         "metadata": {"designer": {"x": 0, "y": 0}, **META_ERR},
         "mapper": {**HTTP_DEFAULTS, "method": "get", "data": "", "contentType": "",
                    "url": SUPABASE_URL + "/rest/v1/folk_failsafe_queue?select=*",
                    "headers": [{"name": "apikey", "value": SUPABASE_KEY},
                                {"name": "Authorization", "value": f"Bearer {SUPABASE_KEY}"}]}},
        {"id": 2, "module": "builtin:BasicFeeder", "version": 1,
         "parameters": {},
         "metadata": {"designer": {"x": 300, "y": 0}, "restore": {}},
         "mapper": {"array": "{{1.data}}"}},
        {"id": 3, "module": "folk:findPerson", "version": 1,
         "parameters": {"__IMTCONN__": FOLK_CONN},
         "onerror": [
            {"id": 9, "module": "builtin:Resume", "version": 1,
             "parameters": {},
             "metadata": {"designer": {"x": 600, "y": 300}},
             "mapper": {"id": "NOTFOUND", "fullName": ""}}],
         "metadata": {"designer": {"x": 600, "y": 0}, **META_ERR},
         "mapper": {"email": "{{2.email}}", "fullName": ""}},
        {"id": 10, "module": "builtin:BasicRouter", "version": 1,
         "metadata": {"designer": {"x": 900, "y": 0}},
         "mapper": None,
         "routes": [{"flow": [
            {"id": 11, "module": "http:ActionSendData", "version": 3,
             "parameters": HTTP_PARAMS,
             "filter": {"name": "Not found in Folk",
                        "conditions": [[{"a": "{{3.id}}", "b": "NOTFOUND", "o": "text:equal"}]]},
             "metadata": {"designer": {"x": 1350, "y": 0}, **META_ERR},
             "mapper": {**HTTP_DEFAULTS, "method": "post",
                        "url": SUPABASE_URL + "/rest/v1/optimiser_notifications",
                        "contentType": "application/json",
                        "data": json.dumps({"campaign_id": "{{2.smartlead_campaign_id}}",
                                            "finding_type": "folk_failsafe",
                                            "title": "Folk missing {{2.email}}",
                                            "detail": "Positive lead not found in Folk; automatic re-push attempted. Suppresses re-alerts for 24h.",
                                            "status": "new"}),
                        "headers": [{"name": "apikey", "value": SUPABASE_KEY},
                                    {"name": "Authorization", "value": "Bearer " + SUPABASE_KEY},
                                    {"name": "Prefer", "value": "return=minimal"}]}},
            {"id": 6, "module": "slack:CreateMessage", "version": 4,
             "parameters": {"__IMTCONN__": SLACK_CONN},
             "metadata": {"designer": {"x": 1200, "y": 0}, **META_ERR},
             "mapper": {"channel": SLACK_CHANNEL, "channelWType": "manualy",
                        "username": "NAVREO BOT",
                        "text": ("⚠️ *Folk fail-safe*: positive lead *{{2.email}}* "
                                 "(campaign {{2.smartlead_campaign_id}}, tagged {{2.category}}) "
                                 "is NOT in Folk. Attempting automatic re-push through the pipeline now — "
                                 "if this alert repeats next run, add manually."),
                        "parse": False, "mrkdwn": True}},
            {"id": 4, "module": "http:ActionSendData", "version": 3,
             "parameters": HTTP_PARAMS,
             "metadata": {"designer": {"x": 1500, "y": 0}, **META_ERR},
             "mapper": {**HTTP_DEFAULTS, "method": "get", "data": "", "contentType": "",
                        "url": f"https://server.smartlead.ai/api/v1/leads/?api_key={SL_KEY}" + "&email={{2.email}}",
                        "headers": []}},
            {"id": 5, "module": "http:ActionSendData", "version": 3,
             "parameters": HTTP_PARAMS,
             "filter": {"name": "Lead found in Smartlead",
                        "conditions": [[{"a": "{{4.statusCode}}", "b": "200", "o": "number:equal"},
                                        {"a": "{{4.data.id}}", "o": "exist"}]]},
             "metadata": {"designer": {"x": 1800, "y": 0}, **META_ERR},
             "mapper": {**HTTP_DEFAULTS, "method": "get", "data": "", "contentType": "",
                        "url": "https://server.smartlead.ai/api/v1/campaigns/{{2.smartlead_campaign_id}}" + f"?api_key={SL_KEY}",
                        "headers": []}},
            {"id": 7, "module": "http:ActionSendData", "version": 3,
             "parameters": HTTP_PARAMS,
             "filter": {"name": "Campaign resolved",
                        "conditions": [[{"a": "{{5.statusCode}}", "b": "200", "o": "number:equal"}]]},
             "metadata": {"designer": {"x": 2100, "y": 0}, **META_ERR},
             "mapper": {**HTTP_DEFAULTS, "method": "post", "url": HOOK_URL,
                        "data": payload_body, "contentType": "application/json", "headers": []}},
         ]}]},
    ],
}

update_id = None
if "--update" in sys.argv:
    update_id = sys.argv[sys.argv.index("--update") + 1]

body = {"blueprint": json.dumps(blueprint),
        "scheduling": json.dumps({"type": "immediately"}),
        "teamId": TEAM, "confirmed": True}
if update_id:
    r = requests.patch(f"{BASE}/scenarios/{update_id}", headers=H,
                       json={"blueprint": body["blueprint"], "scheduling": body["scheduling"]}, timeout=60)
else:
    r = requests.post(f"{BASE}/scenarios", headers=H, json=body, timeout=60)
print(r.status_code, r.text[:800])
