#!/usr/bin/env python3
"""
build_external_scenario.py  ::  lilly-positive-reply-setup (external / client-workspace mode)

Builds a SELF-CONTAINED Make blueprint for a client who runs their OWN Smartlead workspace:
  reply webhook -> lead lookup -> message history -> AI categorise -> set category back in
  THEIR Smartlead -> on a positive: post a card + log a row + thread the phone
  (BetterContact -> Prospeo waterfall) to the client's Slack channel + Notion leads page.

It starts from the verified categoriser blueprint (external_scenario_template.json, which keeps
the AI prompt byte-for-byte) and:
  - swaps the Smartlead API key everywhere to the client's key,
  - points the trigger at the client's Make hook,
  - rewrites the Positive Reply route to: card -> Notion row -> Prospeo -> BetterContact -> phone,
    all pointed at the client's Slack channel + Notion DB, every step guarded.

Single-tenant: every positive in this workspace goes to the one client's channel + DB (no
campaign-name routing needed).

USAGE
  python3 build_external_scenario.py --client "Acme" --api-key "<SMARTLEAD_KEY>" \
      --slack C0XXXXXXX --notion-db <notion_db_id> --hook <make_hook_id> [--out blueprint.json]
  Keys read from env if not passed: PROSPEO_API_KEY, BETTERCONTACT_API_KEY
  (set -a; source ~/.navreo-keys.env; set +a)

Then: validate_blueprint_schema -> scenarios_create (teamId 536258) -> scenarios_activate.
"""
import json, argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "external_scenario_template.json")
NAVREO_SL_KEY = "a8f9359c-b334-4120-9dc5-e36880040492_jfmj1yb"   # placeholder key in the template
TEMPLATE_PROSPEO = "pk_f18e63bac88d94ef3d28bb5d736a19b221cad0558b5b47e9f20cf96a0c48850d"
ICON = "https://cdn.theorg.com/5516b70b-cd51-45d5-8b66-4bae4e8892b8_medium.jpg"
SLACK_CONN = 9254394
NOTION_CONN = 11521245
OPS_CHANNEL = "C07TTLZKU56"      # Navreo-internal alerts channel for write failures
HTTP = {"useMtls": False, "bodyType": "raw", "contentType": "application/json", "serializeUrl": False,
        "shareCookies": False, "parseResponse": True, "followRedirect": True, "useQuerystring": False,
        "followAllRedirects": False, "rejectUnauthorized": True}
CAMP = '{{get(map(29.data.lead_campaign_data; "campaign_name"; "campaign_id"; 1.campaign_id); 1)}}'
FIRST_SENT = "{{stripHTML(2.data.history[1].email_body)}}"

def urlf(ref):
    # Plain field reference. Make OMITS a Notion URL field when the mapped value is an empty
    # *reference*; a formula that returns "" is instead SENT, and Notion rejects "" (URL must be
    # a non-empty string or null) -> the whole row write fails for any lead missing a website /
    # LinkedIn. Notion accepts bare domains as-is, so no https:// prefixing is needed.
    return "{{%s}}" % ref

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--api-key", required=True, help="the client's OWN Smartlead API key")
    ap.add_argument("--slack", required=True, help="client Slack channel ID (Cxxxx)")
    ap.add_argument("--notion-db", required=True, help="client responses-DB id")
    ap.add_argument("--hook", required=True, type=int, help="Make hook id to trigger this scenario")
    ap.add_argument("--prospeo-key", default=os.environ.get("PROSPEO_API_KEY", ""))
    ap.add_argument("--bc-key", default=os.environ.get("BETTERCONTACT_API_KEY", ""))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.bc_key:
        sys.exit("! BETTERCONTACT_API_KEY missing (env or --bc-key)")

    db = a.notion_db.replace("-", "")
    # 1) load template, swap the Smartlead key everywhere (lead lookup, message history, all set-category calls)
    blob = open(TEMPLATE).read().replace(NAVREO_SL_KEY, a.api_key)
    if a.prospeo_key:
        blob = blob.replace(TEMPLATE_PROSPEO, a.prospeo_key)
    bp = json.loads(blob)
    bp["name"] = "smartlead reply-router — %s (client workspace)" % a.client
    bp.pop("scheduling", None); bp.pop("interface", None)

    # 2) point trigger at the client's hook
    next(m for m in bp["flow"] if m["id"] == 1)["parameters"]["hook"] = a.hook

    router = next(m for m in bp["flow"] if m["id"] == 6)
    posroute = router["routes"][-1]
    prospeo = next(m for m in posroute["flow"] if m["id"] == 34)   # reuse template's Prospeo module

    card = {"id": 33,
        "filter": {"name": "Positive Reply", "conditions": [
            [{"a": "{{5.result.category}}", "b": "Interested", "o": "text:equal"}],
            [{"a": "{{5.result.category}}", "b": "Meeting Request", "o": "text:equal"}],
            [{"a": "{{5.result.category}}", "b": "Information Request", "o": "text:equal"}],
            [{"a": "{{5.result.category}}", "b": "Call Booked", "o": "text:equal"}]]},
        "mapper": {"text":
            "\U0001f389 *New Positive Response*\n\n*Client:* %s\n*Campaign:* %s\n"
            "*Lead:* {{29.data.first_name}} {{29.data.last_name}} @ {{29.data.company_name}}\n"
            "*Email:* {{1.sl_lead_email}}\n*LinkedIn:* {{ifempty(29.data.linkedin_profile; \"Not on file\")}}\n"
            "*Time of reply:* {{formatDate(1.reply_message.time; \"DD-MM-YYYY hh:mm A\")}}\n\n"
            "*Their reply:*\n{{1.reply_message.text}}\n\n*Original email we sent:*\n%s\n\n"
            "\U0001f4ca *<https://www.notion.so/%s|View all your leads →>*" % (a.client, CAMP, FIRST_SENT, db),
            "parse": False, "mrkdwn": True, "channel": a.slack, "icon_url": ICON,
            "username": "NAVREO BOT", "channelWType": "manualy"},
        "module": "slack:CreateMessage", "version": 4,
        "onerror": [{"id": 51, "mapper": {}, "module": "builtin:Resume", "version": 1,
                     "metadata": {"designer": {"x": 1789, "y": 1700}}}],
        "metadata": {"designer": {"x": 1789, "y": 1500, "name": "Positive card"}},
        "parameters": {"__IMTCONN__": SLACK_CONN}}

    notion = {"id": 40,
        "mapper": {"fields": [
            {"key": "Lead-Name", "type": "title", "value": "{{29.data.first_name}} {{29.data.last_name}}"},
            {"key": "Full-Reply", "type": "rich_text", "value": "{{stripHTML(1.reply_message.text)}}"},
            {"key": "Company Name", "type": "rich_text", "value": "{{29.data.company_name}}"},
            {"key": "Website", "type": "url", "value": urlf("29.data.website")},
            {"key": "Email", "type": "email", "value": "{{1.sl_lead_email}}"},
            {"key": "LinkedIn URL", "type": "url", "value": urlf("29.data.linkedin_profile")},
            {"key": "Campaign Name", "type": "rich_text", "value": CAMP},
            {"key": "Time of Reply", "date": {"start": "{{1.reply_message.time}}", "includeTime": True}, "type": "date"},
            {"key": "First Email Sent", "type": "rich_text", "value": FIRST_SENT},
            {"key": "Select", "type": "select", "value": "Interested"},
            {"key": "Status", "type": "select", "value": "1. Not responded"},
        ], "select": "map", "database": db},
        "module": "notion:createAPage", "version": 1,
        "onerror": [
            {"id": 47, "mapper": {"text": "⚠️ *%s portal-DB write failed* — {{29.data.first_name}} {{29.data.last_name}} <{{1.sl_lead_email}}>. Add manually to the %s responses DB." % (a.client, a.client),
                                  "channel": OPS_CHANNEL, "channelWType": "manualy"},
             "module": "slack:CreateMessage", "version": 4,
             "metadata": {"designer": {"x": 2089, "y": 1700}}, "parameters": {"__IMTCONN__": SLACK_CONN}},
            {"id": 48, "mapper": {}, "module": "builtin:Resume", "version": 1,
             "metadata": {"designer": {"x": 2289, "y": 1700}}},
        ],
        "metadata": {"designer": {"x": 2089, "y": 1500, "name": "Positive → portal DB"}},
        "parameters": {"__IMTCONN__": NOTION_CONN}}

    bc_body = ('{"data":[{"first_name":"{{29.data.first_name}}","last_name":"{{29.data.last_name}}",'
               '"company":"{{29.data.company_name}}","linkedin_url":"{{29.data.linkedin_profile}}",'
               '"custom_fields":{"uuid":"{{1.sl_email_lead_id}}"}}],'
               '"enrich_email_address":false,"enrich_phone_number":true}')
    bc_submit = {"id": 41,
        "mapper": dict({"qs": [], "url": "https://app.bettercontact.rocks/api/v2/async", "data": bc_body,
                        "gzip": True, "method": "post", "headers": [{"name": "X-API-Key", "value": a.bc_key}]}, **HTTP),
        "module": "http:ActionSendData", "version": 3,
        "onerror": [{"id": 44, "mapper": {"data": {}, "statusCode": 0}, "module": "builtin:Resume", "version": 1,
                     "metadata": {"designer": {"x": 2389, "y": 1700}}}],
        "metadata": {"designer": {"x": 2389, "y": 1500, "name": "BetterContact submit"}},
        "parameters": {"handleErrors": False, "useNewZLibDeCompress": True}}
    sleep = {"id": 42, "mapper": {"duration": 240}, "module": "util:FunctionSleep", "version": 1,
             "metadata": {"designer": {"x": 2539, "y": 1500, "name": "wait for BetterContact"}}}
    bc_get = {"id": 43,
        "mapper": dict({"qs": [], "url": "https://app.bettercontact.rocks/api/v2/async/{{41.data.id}}",
                        "data": "", "gzip": True, "method": "get", "headers": [{"name": "X-API-Key", "value": a.bc_key}]}, **HTTP),
        "module": "http:ActionSendData", "version": 3,
        "onerror": [{"id": 45, "mapper": {"data": {}, "statusCode": 0}, "module": "builtin:Resume", "version": 1,
                     "metadata": {"designer": {"x": 2689, "y": 1700}}}],
        "metadata": {"designer": {"x": 2689, "y": 1500, "name": "BetterContact result"}},
        "parameters": {"handleErrors": False, "useNewZLibDeCompress": True}}
    phone = {"id": 35,
        "mapper": {"text": "\U0001f4de *Phone (for calling):* "
                   "{{if(43.data.data[1].contact_phone_number; 43.data.data[1].contact_phone_number; "
                   "if(34.data.person.mobile.status = \"VERIFIED\"; 34.data.person.mobile.mobile; "
                   "\"❌ no verified mobile found\"))}}",
                   "parse": False, "mrkdwn": True, "channel": a.slack, "thread_ts": "{{33.ts}}",
                   "icon_url": ICON, "username": "NAVREO BOT", "channelWType": "manualy"},
        "module": "slack:CreateMessage", "version": 4,
        "onerror": [{"id": 46, "mapper": {}, "module": "builtin:Resume", "version": 1,
                     "metadata": {"designer": {"x": 2839, "y": 1700}}}],
        "metadata": {"designer": {"x": 2839, "y": 1500, "name": "Phone → thread"}},
        "parameters": {"__IMTCONN__": SLACK_CONN}}

    posroute["flow"] = [card, notion, prospeo, bc_submit, sleep, bc_get, phone]

    out_json = json.dumps(bp, ensure_ascii=False)
    if a.out:
        open(a.out, "w").write(out_json)
        sys.stderr.write("wrote %s (%d bytes)\n" % (a.out, len(out_json)))
    else:
        print(out_json)

if __name__ == "__main__":
    main()
