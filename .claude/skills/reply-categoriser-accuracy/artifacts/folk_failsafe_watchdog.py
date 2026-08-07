"""Folk fail-safe watchdog: no positive lead falls through the cracks.

Every run (suggest daily via cron/launchd or a scheduled Claude run):
  1. Pull positive replies from the last LOOKBACK_H hours from Supabase `replies`.
  2. For each, verify the person exists in Folk (search by email via Folk API).
  3. Missing -> rebuild a Smartlead-shaped EMAIL_REPLY payload from the Smartlead API
     (lead lookup + message history; replies.raw does NOT store the original webhook)
     and re-POST it to Make hook 4001002 (scenario 8946472; Folk step is
     create->find->update, so re-sends are idempotent) AND write an alert row to
     Supabase optimiser_notifications (kind 'folk_failsafe') so it surfaces in the
     notifications digest even if the re-push also fails.

Required env / ~/.navreo-keys.env:
  FOLK_API_KEY   - Folk REST API key (https://developer.folk.app) -- NOT yet stored
  MAKE_TOKEN     - Make API token, used once per run to resolve hook 4001002's URL
                   (or set HOOK_URL directly to skip the Make call)
  SMARTLEAD_API_KEY - already stored; used to rebuild replay payloads
State: ~/.navreo-cache/folk_failsafe_state.json (leads already verified/re-pushed).
"""
import json, sys, time, datetime
from pathlib import Path
import requests

sys.path.insert(0, "/Users/bjionhenry/.claude/skills/_shared")
from navreo_db import _base, _headers, _env

LOOKBACK_H = 48
POSITIVE = ("Interested", "Meeting Request", "Information Request", "Call Booked",
            "Re: Interested")
STATE = Path.home() / ".navreo-cache" / "folk_failsafe_state.json"
FOLK_KEY = _env("FOLK_API_KEY")
MAKE_TOKEN = _env("MAKE_TOKEN")
HOOK_URL = _env("HOOK_URL")

assert FOLK_KEY, "FOLK_API_KEY missing - cannot verify Folk membership"

url, key = _base()
h = _headers(key)
state = json.loads(STATE.read_text()) if STATE.exists() else {"verified": {}}

since = (datetime.datetime.now(datetime.timezone.utc)
         - datetime.timedelta(hours=LOOKBACK_H)).isoformat()
cat_list = ",".join('"' + c + '"' for c in POSITIVE)
r = requests.get(f"{url}/rest/v1/replies", headers=h, params={
    "select": "id,email,smartlead_campaign_id,replied_at,category,reply_body",
    "replied_at": f"gte.{since}",
    "category": f"in.({cat_list})",
    "order": "replied_at.asc", "limit": 500}, timeout=30)
r.raise_for_status()
positives = r.json()

def in_folk(email):
    fr = requests.get("https://api.folk.app/v1/people",
                      headers={"Authorization": f"Bearer {FOLK_KEY}"},
                      params={"filter[emails]": email, "limit": 1}, timeout=30)
    fr.raise_for_status()
    return bool(fr.json().get("data"))

def hook_url():
    global HOOK_URL
    if HOOK_URL:
        return HOOK_URL
    hr = requests.get("https://eu2.make.com/api/v2/hooks/4001002",
                      headers={"Authorization": f"Token {MAKE_TOKEN}"}, timeout=30)
    hr.raise_for_status()
    HOOK_URL = hr.json()["hook"]["url"]
    return HOOK_URL

def alert(email, cid, note):
    requests.post(f"{url}/rest/v1/optimiser_notifications", headers={**h, "Prefer": "return=minimal"},
                  json={"kind": "folk_failsafe", "title": f"Positive lead missing from Folk: {email}",
                        "body": note, "campaign_id": str(cid),
                        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                  timeout=30)

SL_KEY = _env("SMARTLEAD_API_KEY")
SL = "https://server.smartlead.ai/api/v1"

def build_payload(p):
    """Rebuild the EMAIL_REPLY webhook shape from Smartlead (fields per the
    manual-replay recipe: lead_category.new_name, campaign_name, lead_data, history)."""
    g = requests.get(f"{SL}/leads/", params={"api_key": SL_KEY, "email": p["email"]}, timeout=30)
    if g.status_code != 200 or not g.json().get("id"):
        return None
    lead = g.json()
    cid = p["smartlead_campaign_id"]
    camp = requests.get(f"{SL}/campaigns/{cid}", params={"api_key": SL_KEY}, timeout=30).json()
    hist = requests.get(f"{SL}/campaigns/{cid}/leads/{lead['id']}/message-history",
                        params={"api_key": SL_KEY}, timeout=30).json().get("history", [])
    sent = next((m for m in hist if m.get("type") == "SENT"), {})
    reply = next((m for m in reversed(hist) if m.get("type") == "REPLY"), {})
    return {
        "event_type": "EMAIL_REPLY",
        "lead_category": {"new_name": "Interested"},
        "campaign_name": camp.get("name", ""),
        "campaign_id": cid,
        "from_email": p["email"],
        "app_url": f"https://app.smartlead.ai/app/master-inbox?lead={lead['id']}",
        "last_reply": {"time": reply.get("time") or p["replied_at"],
                       "email_body": reply.get("email_body") or p.get("reply_body") or ""},
        "history": [{"type": "SENT", "email_body": sent.get("email_body", "")}],
        "lead_id": lead["id"],
        "sl_email_lead_id": lead["id"],
        "lead_data": {k: lead.get(k) for k in ("first_name", "last_name", "company_name",
                                               "email", "website", "linkedin_profile", "location")}
                     | {"custom_fields": {"role": (lead.get("custom_fields") or {}).get("role", "")}},
    }

missing, repushed = [], []
for p in positives:
    em = p["email"]
    if state["verified"].get(em):
        continue
    try:
        if in_folk(em):
            state["verified"][em] = p["replied_at"]
            continue
        missing.append(em)
        payload = build_payload(p)
        if payload and (MAKE_TOKEN or HOOK_URL):
            pr = requests.post(hook_url(), json=payload, timeout=30)
            if pr.status_code == 200:
                repushed.append(em)
                alert(em, p["smartlead_campaign_id"],
                      "Was missing from Folk; re-pushed through pipeline 8946472. Verify on next run.")
            else:
                alert(em, p["smartlead_campaign_id"], f"Missing from Folk; re-push failed HTTP {pr.status_code}. ADD MANUALLY.")
        else:
            alert(em, p["smartlead_campaign_id"], "Missing from Folk; could not rebuild payload or no hook access. ADD MANUALLY.")
        time.sleep(1)
    except Exception as e:
        alert(em, p.get("smartlead_campaign_id"), f"Folk verify errored: {str(e)[:150]} - check manually.")

STATE.parent.mkdir(exist_ok=True)
STATE.write_text(json.dumps(state, indent=1))
print(json.dumps({"positives_checked": len(positives), "missing_from_folk": missing,
                  "repushed": repushed}, indent=1))
