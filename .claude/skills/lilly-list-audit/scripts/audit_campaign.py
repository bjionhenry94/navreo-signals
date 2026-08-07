#!/usr/bin/env python3
"""
lilly-list-audit : read-only function/ICP composition audit of a Smartlead campaign's leads.

Pulls the leads enrolled in a campaign, classifies each lead's job title into a single
function bucket, and reports how much of the list is ON-ICP vs OFF-ICP. Writes two CSVs.
NOTHING is mutated: this script only issues GET requests.

Usage:
  python3 audit_campaign.py --campaign-id 3285048
  python3 audit_campaign.py --campaign-id 3285048 --sample 100          # quick spot-test
  python3 audit_campaign.py --campaign-id 3285048 --on-icp "MARKETING/PR"  # retarget ICP
  python3 audit_campaign.py --campaign-id 3285048 --out-dir ~/Downloads

Env: SMARTLEAD_API_KEY  (loaded from ~/.navreo-keys.env in the Navreo setup)

The classifier is tuned for a COMMERCIAL / sales-leader ICP by default. To audit a campaign
that targets a different function (e.g. a Heads-of-Marketing campaign), pass --on-icp with the
function label(s) that should count as on-target. See references/classification-rules.md.
"""
import os, sys, re, csv, json, ssl, time, math, random, argparse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

BASE = "https://server.smartlead.ai/api/v1"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
H = {"Accept": "application/json", "User-Agent": UA}
try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl._create_unverified_context()

# ---------------------------------------------------------------- HTTP (GET only, with retry)
def get(path, tries=6):
    key = os.environ["SMARTLEAD_API_KEY"]
    url = f"{BASE}{path}{'&' if '?' in path else '?'}api_key={key}"
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=90, context=CTX) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):      # shared 200/min limit -> back off
                time.sleep(1.5 * (i + 1) + random.random()); continue
            return None
        except Exception:
            time.sleep(1.0 * (i + 1) + random.random())
    return None

# ---------------------------------------------------------------- title extraction
# Smartlead stores the title inside custom_fields, not as a first-class column.
TITLE_KEYS = ["Title", "title", "Job Title", "job_title", "JobTitle"]
def title_of(lead, cf):
    for k in TITLE_KEYS:
        v = cf.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    v = lead.get("title") or lead.get("job_title")
    return v.strip() if isinstance(v, str) else ""

# ---------------------------------------------------------------- the classifier
# WHY this is fiddly: job titles are free text and abbreviations collide with common words.
# The single most important rule: match abbreviations on WORD BOUNDARIES, never as substrings.
# "cto" is a substring of "Dire(cto)r"; "cro"/"cso"/"cio" hide inside other words too. A bare
# `'cto' in title` check silently mislabels every Director as a CTO. Always use \b...\b.
def wb(tl, *abbrs):
    return any(re.search(r"\b" + a + r"\b", tl) for a in abbrs)

def is_vp(tl):
    # "Vice President" contains "president"; if we let the owner check see it, every VP becomes
    # an exec. VPs are FUNCTION leaders (a VP Sales is sales; a VP Marketing is marketing), so we
    # detect VP-ness here and keep it OUT of the owner bucket.
    return "vice president" in tl or wb(tl, "vp", "svp", "evp")

# "Partner" noise: these are NOT equity owners, they are partnerships / HR "business partner" roles.
PARTNER_NOISE = [
    "partner marketing", "partner network", "partner program", "partner solution",
    "partner management", "partner relations", "partner success", "channel partner",
    "business partner", "people partner", "people business", "people operations partner",
    "talent partner", "talent operations", "recruitment partner", "partnering with",
    "head of partner", "vp partner", "partnership",
]
def is_owner_partner(tl):
    # Lesson from production: at agencies/consultancies a "Partner" or "Founding Partner" is an
    # OWNER even when the title also names a function ("Founding Partner, Creative Director").
    # Scoring such a person on the functional half deletes a business owner. So treat partner-as-
    # ownership FIRST, excluding the partnerships / business-partner noise above.
    if "partner" not in tl:
        return False
    if any(x in tl for x in PARTNER_NOISE):
        return False
    if "founding partner" in tl or tl.strip() == "partner":
        return True
    return True  # remaining standalone "Partner ..." -> owner-level

def classify(title):
    """Return one function label for a title. Order matters: ownership is checked before
    functional roles so owner-operators are not lost to their functional half."""
    tl = title.lower().strip()
    if not tl:
        return "UNTITLED"
    # 1) OWNER / EXEC (top of house)
    if any(k in tl for k in ["founder", "co-found", "cofound"]):                  return "OWNER/EXEC"
    if wb(tl, "ceo") or "chief executive" in tl:                                  return "OWNER/EXEC"
    if "owner" in tl or "proprietor" in tl:                                       return "OWNER/EXEC"
    if "managing director" in tl or "managing partner" in tl:                     return "OWNER/EXEC"
    if "chairman" in tl or "chairwoman" in tl or "chairperson" in tl or wb(tl, "chair"): return "OWNER/EXEC"
    if "principal" in tl:                                                         return "OWNER/EXEC"
    if "president" in tl and not is_vp(tl):                                       return "OWNER/EXEC"
    if is_owner_partner(tl):                                                      return "OWNER/EXEC"
    # 2) SALES-SUPPORT (carve out before generic "sales")
    if any(k in tl for k in ["sales operation", "sales enablement", "sales ops",
                              "revenue operation", "revops", "pre-sales", "presales"]): return "SALES-SUPPORT"
    # 3) SALES-LEADER (incl. sales-relevant chiefs, spelled out to avoid abbrev collisions)
    if wb(tl, "cro") or any(k in tl for k in ["chief revenue", "chief sales", "chief commercial", "chief growth"]):
        return "SALES-LEADER"
    if any(k in tl for k in ["sales", "revenue", "commercial", "business development",
                              "new business", "go-to-market", "head of growth", "vp growth"]):
        return "SALES-LEADER"
    # 4) NON-SALES functions
    if any(k in tl for k in ["creative", "art director", "art ", "design", "editorial",
                              "content", "copywrit", "video", "studio", "photograph"]):   return "CREATIVE/CONTENT"
    if "account" in tl or "client " in tl or "customer success" in tl:                    return "ACCOUNT/CLIENT"
    if wb(tl, "cmo") or any(k in tl for k in ["market", "demand gen", "seo", "ppc",
                              "social media", "communication", "public relations", "comms", "brand"]): return "MARKETING/PR"
    if wb(tl, "coo") or any(k in tl for k in ["operation", "chief operating", "delivery",
                              "project manager", "program manager", "producer", "pmo"]):  return "OPERATIONS/DELIVERY"
    if wb(tl, "cto", "cio") or any(k in tl for k in ["technical", "technology", "engineer",
                              "developer", "software", "data scien", "data analyst",
                              "product manager", "head of product"]):                      return "TECH/PRODUCT"
    if wb(tl, "cfo") or any(k in tl for k in ["finance", "financial", "accounting", "controller", "treasur"]): return "FINANCE"
    if any(k in tl for k in ["people", "talent", "recruit", "human resources",
                              " hr ", "l&d", "learning & development", "learning and development"]): return "HR/TALENT"
    if any(k in tl for k in ["legal", "counsel", "compliance", "attorney"]):              return "LEGAL"
    # 5) Generic leadership (function not stated in title) vs everything else
    if tl.endswith(("director", "manager", "officer", "head", "lead")) or tl in ("director", "manager", "head", "lead", "consultant"):
        return "OTHER-LEADERSHIP"
    return "OTHER"

DEFAULT_ON_ICP = {"OWNER/EXEC", "SALES-LEADER", "SALES-SUPPORT"}

# ---------------------------------------------------------------- pull leads (all or sample)
def fetch_page(cid, off):
    d = get(f"/campaigns/{cid}/leads?offset={off}&limit=100")
    return [r.get("lead", r) for r in (d.get("data", []) if d else [])]

def pull(cid, sample=None):
    head = get(f"/campaigns/{cid}/leads?offset=0&limit=1")
    total = int((head or {}).get("total_leads", 0) or 0)
    all_offsets = list(range(0, max(total, 1), 100))
    if sample and sample < total:
        offsets = random.sample(all_offsets, min(len(all_offsets), math.ceil(sample / 100)))
    else:
        offsets = all_offsets
    leads = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for fut in as_completed([ex.submit(fetch_page, cid, o) for o in offsets]):
            leads.extend(fut.result())
    # dedupe by lead id (guards against pagination overlap)
    seen, uniq = set(), []
    for L in leads:
        i = L.get("id")
        if i in seen:
            continue
        seen.add(i); uniq.append(L)
    if sample and len(uniq) > sample:
        uniq = random.sample(uniq, sample)
    return total, uniq

def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip())[:60].strip("-")

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--sample", type=int, default=None, help="audit a random N-lead sample (spot-test)")
    ap.add_argument("--on-icp", default=None, help="comma-sep function labels that count as on-ICP (default: OWNER/EXEC,SALES-LEADER,SALES-SUPPORT)")
    ap.add_argument("--out-dir", default="~/Downloads")
    a = ap.parse_args()
    if "SMARTLEAD_API_KEY" not in os.environ:
        sys.exit("SMARTLEAD_API_KEY not set (source ~/.navreo-keys.env)")
    cid = a.campaign_id
    on_icp = set(x.strip().upper() for x in a.on_icp.split(",")) if a.on_icp else DEFAULT_ON_ICP
    out_dir = os.path.expanduser(a.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    meta = get(f"/campaigns/{cid}")
    name = (meta or {}).get("name", f"campaign-{cid}")
    total, leads = pull(cid, a.sample)
    if not leads:
        sys.exit(f"No leads pulled for campaign {cid} (total={total}). Check the id / API key.")

    rows = []
    for L in leads:
        cf = L.get("custom_fields") or {}
        t = title_of(L, cf)
        fn = classify(t)
        rows.append({
            "email": L.get("email", ""), "first_name": L.get("first_name", ""),
            "last_name": L.get("last_name", ""), "title": t, "function": fn,
            "on_icp": "Y" if fn in on_icp else ("" if fn != "UNTITLED" else "?"),
            "company": L.get("company_name", ""), "location": L.get("location", ""),
            "linkedin": L.get("linkedin_profile", ""),
        })

    titled = [r for r in rows if r["function"] != "UNTITLED"]
    n_titled = len(titled) or 1
    mix = Counter(r["function"] for r in titled)
    on_n = sum(v for k, v in mix.items() if k in on_icp)
    off = [r for r in titled if r["function"] not in on_icp]
    off_mix = Counter(r["function"] for r in off)

    # ---- CSV exports
    base = f"{cid}_{safe(name)}"
    all_csv = os.path.join(out_dir, f"AUDIT_{base}_all.csv")
    off_csv = os.path.join(out_dir, f"AUDIT_{base}_off-icp.csv")
    fields = ["email", "first_name", "last_name", "title", "function", "on_icp", "company", "location", "linkedin"]
    with open(all_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in sorted(rows, key=lambda x: (x["on_icp"], x["function"], x["title"])): w.writerow(r)
    with open(off_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in sorted(off, key=lambda x: (x["function"], x["title"])): w.writerow(r)

    # ---- report
    mode = f"SAMPLE of {len(leads)}" if a.sample else f"FULL ({len(leads)} leads)"
    print(f"\n{'='*78}\nlilly-list-audit  |  {name}  [{cid}]\n  mode: {mode}  |  campaign total leads: {total}\n{'='*78}")
    untitled = len(rows) - len(titled)
    if untitled:
        print(f"  {untitled} leads have no title (excluded from %).")
    print(f"\n  ON-ICP  : {on_n}/{len(titled)}  ({on_n/n_titled*100:.0f}%)   [on-ICP = {', '.join(sorted(on_icp))}]")
    print(f"  OFF-ICP : {len(off)}/{len(titled)}  ({len(off)/n_titled*100:.0f}%)")
    if a.sample and total > len(leads):
        print(f"  -> extrapolated to full campaign (~{total}): roughly {round(len(off)/n_titled*total):,} off-ICP leads")
    print("\n  Function mix:")
    for k, v in mix.most_common():
        tag = "ON " if k in on_icp else "off"
        print(f"     [{tag}] {k:<22}{v:>6} ({v/n_titled*100:>2.0f}%)")
    if off:
        print("\n  OFF-ICP examples (first distinct titles per bucket):")
        for fn, _ in off_mix.most_common():
            ex = []
            for r in off:
                if r["function"] == fn and r["title"] not in ex:
                    ex.append(r["title"])
                if len(ex) >= 4:
                    break
            print(f"     {fn:<22} e.g. " + " | ".join(e[:32] for e in ex))
    print(f"\n  CSVs:\n    all    -> {all_csv}\n    off-ICP-> {off_csv}")
    print("\n  Reminder: this is a heuristic title audit. The OTHER-LEADERSHIP bucket (bare")
    print("  Director/Manager/Partner with no function word) is genuinely ambiguous: eyeball it")
    print("  before acting. See references/classification-rules.md.\n")

if __name__ == "__main__":
    main()
