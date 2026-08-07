#!/usr/bin/env python3
"""
lilly-client-reporting :: route_responses.py

Given a config of active clients, find NEW positive replies in Smartlead
(not already in each client's portal DB), enrich them (lead details +
message-history reply/original-email + a verified mobile via the phone
waterfall: BetterContact first, Prospeo fallback), and emit ready-to-post
items: Notion row properties + Slack card text + phone.

The script does ALL Smartlead/BetterContact/Prospeo work + assembly. It does NOT touch
Notion or Slack (no creds) — the calling agent dispatches the output to the
Notion create-pages and Slack send MCP tools.

USAGE
  python3 route_responses.py <config.json> [out_dir]

CONFIG (config.json)
{
  "clients": [
    {
      "name": "Arnic",                       # also used as campaign-name match
      "smartlead_client_id": 366437,          # int or null
      "responses_db_id": "2ec3...2561",
      "slack_channel_id": "C0BBH29BXTQ",
      "leads_db_url": "https://app.notion.com/p/2ec3...2561",
      "existing_emails": ["a@x.com", ...]      # dedup exclude (current rows in their DB)
    }, ...
  ]
}

OUTPUT  ->  <out_dir>/<client>.json
{
  "client": "Arnic", "slack_channel_id": "...", "responses_db_id": "...",
  "new_count": 3,
  "items": [
    {"notion": {<page properties>}, "card": "<slack markdown>", "phone": "+.. or null", "email": ".."}
  ]
}

Env: SMARTLEAD_API_KEY, BETTERCONTACT_API_KEY, PROSPEO_API_KEY  (loaded from ~/.navreo-keys.env by the caller).
"""
import json, sys, os, re, html, subprocess, urllib.parse, time
from collections import OrderedDict

SL = os.environ["SMARTLEAD_API_KEY"]
PROSPEO = os.environ.get("PROSPEO_API_KEY", "")
BETTERCONTACT = os.environ.get("BETTERCONTACT_API_KEY", "")
BASE = "https://server.smartlead.ai/api/v1"

# BetterContact = Stage 1 of the phone waterfall (tried BEFORE Prospeo). Async API:
# POST /async to submit, then poll GET /async/{id} until status == "terminated".
BC_BASE = "https://app.bettercontact.rocks/api/v2"
BC_POLL_TRIES = 24          # max polls before giving up (waterfall falls through to Prospeo)
BC_POLL_WAIT = 5            # seconds between polls (~2 min cap; most resolve in seconds)

POSITIVE = {"interested", "meeting request", "information request", "re: interested",
            "call booked", "referral request", "[manual] interested", "[manual] send resource"}

def curl(url, method="GET", headers=None, data=None):
    cmd = ["curl", "-s", "-X", method, url]
    for h in (headers or []):
        cmd += ["-H", h]
    if data is not None:
        cmd += ["-d", data]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout

def jget(url):
    try:
        return json.loads(curl(url))
    except Exception:
        return None

def clean(s, limit=700):
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\r", "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()[:limit]

def strip_quote(reply):
    """Trim a reply down to the prospect's actual message (drop quoted thread)."""
    cuts = []
    for pat in [r"\nOn .{0,70}wrote:", r" On \w{3}, \w{3,9} \d", r"\nFrom: ", r"\n>",
                r"On \d{1,2} \w{3,9} 20\d\d", r"On \w{3,9} \d{1,2}, 20\d\d",
                r"On 20\d\d-", r"\nLe \w", r"-----Original Message-----", r"Sent from my "]:
        m = re.search(pat, reply)
        if m:
            cuts.append(m.start())
    if cuts:
        reply = reply[:min(cuts)]
    return re.sub(r"\s+", " ", reply).strip()[:600]

def website_url(w):
    w = (w or "").strip()
    if not w:
        return ""
    return w if w.startswith("http") else "https://" + w

def campaigns_for(client, all_campaigns):
    """Campaigns belonging to a client: by Smartlead client_id, else by name match
    (campaign name contains the client name and NOT 'Navreo')."""
    cid = client.get("smartlead_client_id")
    name = client["name"].lower()
    out = []
    for c in all_campaigns:
        cn = (c.get("name") or "")
        cl = cn.lower()
        if cid and c.get("client_id") == cid:
            out.append((c["id"], cn))
        elif name in cl and "navreo" not in cl:
            out.append((c["id"], cn))
    return out

def find_positive_emails(campaigns):
    """Return {email: (campaign_id, campaign_name, category)} for positive-category leads."""
    import csv, io
    found = OrderedDict()
    SUBSEQ = {"interested reply", "meeting request"}
    for cid, cname in campaigns:
        txt = curl(f"{BASE}/campaigns/{cid}/leads-export?api_key={SL}")
        if not txt or not txt.startswith('"'):
            continue
        for row in csv.DictReader(io.StringIO(txt)):
            cat = (row.get("category") or "").strip()
            if cat.lower() not in POSITIVE:
                continue
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            new_main = cname.strip().lower() not in SUBSEQ
            ex = found.get(email)
            if ex and not (new_main and ex[1].strip().lower() in SUBSEQ):
                continue
            found[email] = (cid, cname, cat)
    return found

def domain_of(website):
    """Bare registrable domain from a website value, for BetterContact company_domain."""
    w = (website or "").strip()
    if not w:
        return ""
    w = re.sub(r"^https?://", "", w, flags=re.I).split("/")[0]
    if w.lower().startswith("www."):
        w = w[4:]
    return w.strip()

def bettercontact_phone(first, last, company, domain, linkedin):
    """Stage 1 of the phone waterfall. Submit one contact to BetterContact's async
    enrichment, poll until terminated, and return a formatted mobile string (or "").
    BetterContact requires first + last name and a company (name or domain); if those
    are missing we bail so the caller falls through to Prospeo."""
    if not BETTERCONTACT or not first or not last or not (company or domain):
        return ""
    lead = {"first_name": first, "last_name": last}
    if company:
        lead["company"] = company
    if domain:
        lead["company_domain"] = domain
    if linkedin:
        lead["linkedin_url"] = linkedin
    body = json.dumps({"data": [lead], "enrich_email_address": False, "enrich_phone_number": True})
    try:
        resp = json.loads(curl(f"{BC_BASE}/async", "POST",
                               ["Content-Type: application/json", f"X-API-Key: {BETTERCONTACT}"], body))
    except Exception:
        return ""
    rid = (resp or {}).get("id")
    if not (resp or {}).get("success") or not rid:
        return ""
    for _ in range(BC_POLL_TRIES):
        time.sleep(BC_POLL_WAIT)
        try:
            r = json.loads(curl(f"{BC_BASE}/async/{rid}", "GET", [f"X-API-Key: {BETTERCONTACT}"]))
        except Exception:
            continue
        if (r or {}).get("status") != "terminated":
            continue
        rows = (r or {}).get("data") or []
        if rows:
            ph = (rows[0].get("contact_phone_number") or "").strip()
            cc = (rows[0].get("contact_phone_number_cc") or "").strip()
            if ph:
                return ph + (f"  ·  {cc}" if cc and cc not in ph else "")
        return ""    # terminated with no phone -> fall through to Prospeo
    return ""        # never terminated within budget -> fall through to Prospeo

def prospeo_phone(email, linkedin):
    """Stage 2 (fallback) of the phone waterfall. Returns a formatted mobile string (or "")."""
    if not PROSPEO:
        return ""
    key = "linkedin_url" if linkedin else "email"
    val = linkedin if linkedin else email
    body = json.dumps({"enrich_mobile": True, "data": {key: val}})
    try:
        pr = json.loads(curl("https://api.prospeo.io/enrich-person", "POST",
                             ["Content-Type: application/json", f"X-KEY: {PROSPEO}"], body))
    except Exception:
        pr = None
    mob = (((pr or {}).get("person") or {}).get("mobile") or {})
    if mob.get("status") == "VERIFIED" and mob.get("mobile"):
        return mob["mobile"] + (f"  ·  {mob.get('mobile_country')}" if mob.get("mobile_country") else "")
    return ""

def enrich(email, slack_camp):
    lead = jget(f"{BASE}/leads/?api_key={SL}&email={urllib.parse.quote(email)}")
    if not lead or not lead.get("id"):
        return None
    lcd = lead.get("lead_campaign_data") or []
    def score(c):
        n = (c.get("campaign_name") or "")
        return 0 if n.strip() == (slack_camp or "").strip() else (1 if (slack_camp or "")[:8] in n else 2)
    reply = first_sent = reply_time = ""
    used_camp = slack_camp or ""
    for c in sorted(lcd, key=score):
        cid = c.get("campaign_id")
        if not cid:
            continue
        mh = jget(f"{BASE}/campaigns/{cid}/leads/{lead['id']}/message-history?api_key={SL}")
        hist = (mh or {}).get("history") or []
        reps = sorted([h for h in hist if h.get("type") == "REPLY" and h.get("email_body")], key=lambda h: h.get("time", ""))
        sents = sorted([h for h in hist if h.get("type") == "SENT" and h.get("email_body")], key=lambda h: h.get("time", ""))
        if reps:
            reply = reps[0]["email_body"]
            reply_time = reps[0].get("time", "")
            if sents:
                first_sent = clean(sents[0]["email_body"], 600)
            if c.get("campaign_name"):
                used_camp = c["campaign_name"]
            break
    fn = (lead.get("first_name") or "").strip()
    ln = (lead.get("last_name") or "").strip()
    name = (fn + " " + ln).strip()
    if name.lower() in ("there", "") or "@" in name:
        name = lead.get("company_name") or email
    # --- Phone waterfall: BetterContact first, Prospeo as fallback ---
    li = (lead.get("linkedin_profile") or "").strip()
    company = (lead.get("company_name") or "").strip()
    domain = domain_of(lead.get("website", ""))
    phone, phone_source = "", ""
    phone = bettercontact_phone(fn, ln, company, domain, li)
    if phone:
        phone_source = "BetterContact"
    else:
        phone = prospeo_phone(email, li)
        if phone:
            phone_source = "Prospeo"
    return {
        "name": name, "email": lead.get("email", email),
        "company": lead.get("company_name", ""), "website": website_url(lead.get("website", "")),
        "linkedin": (lead.get("linkedin_profile") or "").strip(),
        "title": (lead.get("custom_fields") or {}).get("title", ""),
        "campaign": used_camp, "reply": reply, "first_sent": first_sent,
        "reply_time": reply_time, "phone": phone, "phone_source": phone_source,
    }

def build_item(e, client):
    notion = {
        "Lead-Name": e["name"], "Email": e["email"], "Company Name": e["company"],
        "Campaign Name": e["campaign"], "Full-Reply": strip_quote(clean(e["reply"], 1500)),
        "First Email Sent": e["first_sent"], "Select": "Interested", "Status": "1. Not responded",
    }
    if e["website"]:
        notion["Website"] = e["website"]
    if e["linkedin"]:
        notion["LinkedIn URL"] = e["linkedin"]
    if e["reply_time"]:
        notion["date:Time of Reply:start"] = e["reply_time"]
        notion["date:Time of Reply:is_datetime"] = 1
    title_line = e["name"]
    if e.get("title") or e["company"]:
        title_line += " — " + " @ ".join([x for x in [e.get("title", ""), e["company"]] if x])
    card = (
        "🎉 **New Positive Response**\n"
        "———————————————\n"
        f"**Client:** {client['name']}\n"
        f"**Campaign:** {e['campaign']}\n"
        f"**Lead:** {title_line}\n"
        f"**Email:** {e['email']}\n"
        f"**LinkedIn:** {e['linkedin'] or 'Not on file'}\n"
        + (f"**Time of reply:** {e['reply_time'][:16].replace('T',' ')}\n" if e["reply_time"] else "")
        + "\n**Their reply:**\n> " + strip_quote(clean(e["reply"], 800)).replace("\n", " ") + "\n"
        + (("\n**Original email we sent:**\n> " + e["first_sent"].replace("\n", " ") + "\n") if e["first_sent"] else "")
        + f"\n📊 **[View all your leads →]({client.get('leads_db_url', '')})**"
    )
    phone = (f"📞 **Mobile ({e.get('phone_source') or 'verified'}):** " + e["phone"]) if e["phone"] else None
    return {"notion": notion, "card": card, "phone": phone, "email": e["email"]}

def main():
    cfg = json.load(open(sys.argv[1]))
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/lcr_out"
    os.makedirs(out_dir, exist_ok=True)
    all_campaigns = jget(f"{BASE}/campaigns?api_key={SL}") or []
    summary = []
    for client in cfg["clients"]:
        existing = set(x.strip().lower() for x in client.get("existing_emails", []))
        camps = campaigns_for(client, all_campaigns)
        positives = find_positive_emails(camps)
        items = []
        for email, (cid, cname, cat) in positives.items():
            if email in existing:
                continue
            e = enrich(email, cname)
            if not e:
                continue
            items.append(build_item(e, client))
        out = {"client": client["name"], "slack_channel_id": client["slack_channel_id"],
               "responses_db_id": client["responses_db_id"], "new_count": len(items), "items": items}
        path = os.path.join(out_dir, re.sub(r"[^a-z0-9]+", "_", client["name"].lower()) + ".json")
        json.dump(out, open(path, "w"), indent=1)
        summary.append(f"{client['name']}: {len(items)} new (scanned {len(camps)} campaigns, {len(positives)} positives, {len(existing)} already in DB) -> {path}")
    print("\n".join(summary))

if __name__ == "__main__":
    main()
