#!/usr/bin/env python3
"""
lilly-phone-finder :: find_phones.py

Enrich a CSV / list of people with a VERIFIED MOBILE NUMBER using a waterfall:

    Stage 1  BetterContact  (batched, up to 100 contacts per call)   -- tried FIRST
    Stage 2  Prospeo        (per-row, enrich-person)                 -- fallback only

For each person the script tries BetterContact first; only the rows BetterContact
could not find a number for fall through to Prospeo. The output keeps every input
row + column and appends the mobile, which provider found it, and the status.

USAGE
    python3 find_phones.py <input.csv> [output.csv] [--no-prospeo]

  output.csv defaults to "<input>_phones.csv".
  --no-prospeo runs BetterContact only (skip the fallback stage).

INPUT COLUMNS  (case-insensitive; common aliases auto-detected)
    first name : first_name | firstname | first | given_name
    last name  : last_name  | lastname  | last  | surname | family_name
    full name  : name | full_name | contact_name        (split if first/last absent)
    company    : company | company_name | organization | organisation
    domain     : company_domain | domain | website | url | company_website
    linkedin   : linkedin | linkedin_url | linkedin_profile | linkedin_profile_url
    email      : email | email_address | work_email

  BetterContact needs first + last + (company OR domain). Prospeo fallback needs
  a linkedin url OR an email. Rows missing what a stage needs simply skip that
  stage (and may end up with no number).

OUTPUT  (original columns preserved, these appended)
    mobile         : the verified number, or "" if none found
    mobile_source  : BetterContact | Prospeo | ""        (which stage found it)
    mobile_status  : provider status (BetterContact contact_phone_number_status, or Prospeo "VERIFIED")

COST / CREDITS
  Each provider charges per enrichment. The script prints BetterContact
  credits_consumed / credits_left after the run. For a large list, run a small
  sample first (e.g. head -n 20) to sanity-check hit rate before the full spend.

Env: BETTERCONTACT_API_KEY, PROSPEO_API_KEY
     (load with:  set -a; source ~/.navreo-keys.env; set +a)
"""
import json, sys, os, re, csv, io, time, subprocess

BETTERCONTACT = os.environ.get("BETTERCONTACT_API_KEY", "")
PROSPEO = os.environ.get("PROSPEO_API_KEY", "")

BC_BASE = "https://app.bettercontact.rocks/api/v2"
BC_BATCH = 100          # BetterContact accepts up to 100 contacts per /async call
BC_POLL_TRIES = 60      # max polls per chunk (~5 min) before giving up on that chunk
BC_POLL_WAIT = 5        # seconds between polls

# ---- column alias resolution -------------------------------------------------
ALIASES = {
    "first":   ["first_name", "firstname", "first", "given_name", "givenname"],
    "last":    ["last_name", "lastname", "last", "surname", "family_name", "familyname"],
    "full":    ["full_name", "fullname", "name", "contact_name", "contactname", "lead_name", "lead-name"],
    "company": ["company", "company_name", "companyname", "organization", "organisation", "account", "account_name"],
    "domain":  ["company_domain", "companydomain", "domain", "website", "url", "company_website", "websiteurl", "web"],
    "linkedin":["linkedin_url", "linkedin", "linkedin_profile", "linkedin_profile_url", "linkedinurl", "li_url", "li"],
    "email":   ["email", "email_address", "emailaddress", "work_email", "workemail", "e-mail"],
}

def norm(h):
    return re.sub(r"[^a-z0-9]+", "", (h or "").lower())

def build_colmap(fieldnames):
    """Map our logical keys -> the actual header in the CSV (first alias that matches)."""
    present = {norm(h): h for h in fieldnames}
    colmap = {}
    for key, al in ALIASES.items():
        for a in al:
            if norm(a) in present:
                colmap[key] = present[norm(a)]
                break
    return colmap

def domain_of(value):
    """Bare registrable domain from a website/url/domain cell."""
    w = (value or "").strip()
    if not w:
        return ""
    w = re.sub(r"^https?://", "", w, flags=re.I).split("/")[0]
    if w.lower().startswith("www."):
        w = w[4:]
    return w.strip()

def split_name(full):
    parts = (full or "").strip().split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if len(parts) == 1:
        return parts[0], ""
    return "", ""

def fields_for(row, colmap):
    """Pull the logical inputs we need out of one CSV row."""
    g = lambda k: (row.get(colmap[k], "") if k in colmap else "").strip()
    first, last = g("first"), g("last")
    if not (first and last) and "full" in colmap:
        f2, l2 = split_name(g("full"))
        first = first or f2
        last = last or l2
    return {
        "first": first, "last": last,
        "company": g("company"),
        "domain": domain_of(g("domain")),
        "linkedin": g("linkedin"),
        "email": g("email"),
    }

# ---- http --------------------------------------------------------------------
def curl(url, method="GET", headers=None, data=None, timeout=120):
    cmd = ["curl", "-s", "-X", method, url]
    for h in (headers or []):
        cmd += ["-H", h]
    if data is not None:
        cmd += ["-d", data]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout

def jload(s):
    try:
        return json.loads(s)
    except Exception:
        return None

# ---- Stage 1: BetterContact (batched) ----------------------------------------
def bettercontact_batch(rows):
    """rows: list of (idx, fields). Returns {idx: {'mobile','status'}} for hits,
    plus (credits_consumed, credits_left) totals. Order-preserving; maps results
    back by the uuid custom field (falls back to positional order)."""
    found, consumed, left = {}, 0, None
    if not BETTERCONTACT:
        return found, consumed, left
    # only rows BetterContact can act on
    submit = [(i, f) for (i, f) in rows if f["first"] and f["last"] and (f["company"] or f["domain"])]
    for start in range(0, len(submit), BC_BATCH):
        chunk = submit[start:start + BC_BATCH]
        data = []
        for i, f in chunk:
            lead = {"first_name": f["first"], "last_name": f["last"],
                    "custom_fields": {"uuid": str(i)}}
            if f["company"]:
                lead["company"] = f["company"]
            if f["domain"]:
                lead["company_domain"] = f["domain"]
            if f["linkedin"]:
                lead["linkedin_url"] = f["linkedin"]
            data.append(lead)
        body = json.dumps({"data": data, "enrich_email_address": False, "enrich_phone_number": True})
        resp = jload(curl(f"{BC_BASE}/async", "POST",
                          ["Content-Type: application/json", f"X-API-Key: {BETTERCONTACT}"], body))
        rid = (resp or {}).get("id")
        if not (resp or {}).get("success") or not rid:
            sys.stderr.write(f"  ! BetterContact submit failed for chunk @{start}: {str(resp)[:160]}\n")
            continue
        result = None
        for _ in range(BC_POLL_TRIES):
            time.sleep(BC_POLL_WAIT)
            r = jload(curl(f"{BC_BASE}/async/{rid}", "GET", [f"X-API-Key: {BETTERCONTACT}"]))
            if r and r.get("status") == "terminated":
                result = r
                break
        if not result:
            sys.stderr.write(f"  ! BetterContact chunk @{start} never terminated (request_id {rid})\n")
            continue
        consumed += result.get("credits_consumed") or 0
        if result.get("credits_left") is not None:
            left = result["credits_left"]
        out_rows = result.get("data") or []
        for pos, rr in enumerate(out_rows):
            uuid = None
            for cf in (rr.get("custom_fields") or []):
                if cf.get("name") == "uuid":
                    uuid = cf.get("value")
            idx = int(uuid) if (uuid and uuid.isdigit()) else (chunk[pos][0] if pos < len(chunk) else None)
            if idx is None:
                continue
            ph = (rr.get("contact_phone_number") or "").strip()
            if ph:
                found[idx] = {"mobile": ph,
                              "status": (rr.get("contact_phone_number_status") or "valid")}
    return found, consumed, left

# ---- Stage 2: Prospeo (per-row fallback) -------------------------------------
def prospeo_phone(f):
    """Returns {'mobile','status'} or None. Needs a linkedin url or an email."""
    if not PROSPEO:
        return None
    li, email = f["linkedin"], f["email"]
    if not (li or email):
        return None
    key = "linkedin_url" if li else "email"
    val = li if li else email
    body = json.dumps({"enrich_mobile": True, "data": {key: val}})
    pr = jload(curl("https://api.prospeo.io/enrich-person", "POST",
                    ["Content-Type: application/json", f"X-KEY: {PROSPEO}"], body))
    mob = (((pr or {}).get("person") or {}).get("mobile") or {})
    if mob.get("status") == "VERIFIED" and mob.get("mobile"):
        num = mob["mobile"]
        if mob.get("mobile_country"):
            num += f"  ·  {mob['mobile_country']}"
        return {"mobile": num, "status": "VERIFIED"}
    return None

# ---- main --------------------------------------------------------------------
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    if not args:
        sys.exit("usage: find_phones.py <input.csv> [output.csv] [--no-prospeo]")
    in_path = args[0]
    out_path = args[1] if len(args) > 1 else re.sub(r"\.csv$", "", in_path, flags=re.I) + "_phones.csv"
    use_prospeo = "--no-prospeo" not in flags

    with open(in_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        in_fields = reader.fieldnames or []
        rows = list(reader)
    colmap = build_colmap(in_fields)
    missing = [k for k in ("first", "last", "company", "domain", "linkedin", "email") if k not in colmap]
    if "first" not in colmap and "full" not in colmap:
        sys.exit(f"! No name column found. Headers seen: {in_fields}")
    parsed = [(i, fields_for(r, colmap)) for i, r in enumerate(rows)]

    sys.stderr.write(f"Loaded {len(rows)} rows. Columns mapped: "
                     f"{ {k: colmap.get(k, '-') for k in ALIASES} }\n")
    if missing:
        sys.stderr.write(f"  (no column for: {', '.join(missing)} — those inputs unavailable)\n")

    # Stage 1
    sys.stderr.write("Stage 1: BetterContact (batched)...\n")
    bc, consumed, left = bettercontact_batch(parsed)
    sys.stderr.write(f"  BetterContact found {len(bc)} / {len(rows)}  "
                     f"(credits_consumed={consumed}, credits_left={left})\n")

    # Stage 2 (only rows BetterContact missed)
    pr_found = 0
    results = {}
    for i, f in parsed:
        if i in bc:
            results[i] = {**bc[i], "source": "BetterContact"}
        elif use_prospeo:
            p = prospeo_phone(f)
            if p:
                results[i] = {**p, "source": "Prospeo"}
                pr_found += 1
    if use_prospeo:
        sys.stderr.write(f"Stage 2: Prospeo fallback found {pr_found} more.\n")

    # write
    extra = ["mobile", "mobile_source", "mobile_status"]
    out_fields = in_fields + [c for c in extra if c not in in_fields]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields)
        w.writeheader()
        for i, r in enumerate(rows):
            res = results.get(i)
            r = dict(r)
            r["mobile"] = res["mobile"] if res else ""
            r["mobile_source"] = res["source"] if res else ""
            r["mobile_status"] = res["status"] if res else ""
            w.writerow(r)

    total = len(results)
    print(f"Done. {total}/{len(rows)} numbers found "
          f"({len(bc)} BetterContact + {pr_found} Prospeo). -> {out_path}")
    if left is not None:
        print(f"BetterContact credits: {consumed} consumed this run, {left} left.")

if __name__ == "__main__":
    main()
