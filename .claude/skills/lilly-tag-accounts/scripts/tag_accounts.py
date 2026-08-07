#!/usr/bin/env python3
"""
Bulk tag / untag / read Smartlead email-account tags.

DEFAULT IS DRY-RUN: it pulls accounts, applies your selection filters, and
prints the matched set + a breakdown. Nothing is written until you add --apply.
This is deliberate — bulk tagging runs on a multi-client production account, so
you confirm the scope before firing.

Auth: SMARTLEAD_API_KEY is read from ~/.navreo-keys.env (or pass --api-key).
HTTP goes through curl (Smartlead's Cloudflare blocks bare python-urllib UAs).
Rate limit is 200 req/min, SHARED with live sending — calls retry on 429.

SELECTION (combine freely; all are AND-ed):
  --type OUTLOOK,SMTP        account .type (OUTLOOK = Hypertide, SMTP = Maildoso)
  --domain-contains amplifyy substring match on the from_email domain (repeat w/ commas)
  --domain-in a.info,b.info  exact domain allow-list
  --exclude-domain x.info    exact domain block-list
  --smtp-host smtp.maildoso.com   exact smtp_host match
  --from-name-contains "Kevin"    substring on from_name
  --ids 101,102              explicit account ids
  --ids-from-csv path.csv    csv with an 'id' column

ACTION:
  --tag "Name"      create this tag (or reuse if already present on the set) then assign
  --tag-id 405504   use an existing tag id (no create; avoids duplicate definitions)
  --color "#16a34a" color for a newly created tag (default teal)
  --action assign|remove   (default assign)
  --read            just print current tags for the matched set (or for --emails)
  --emails a@x,b@y  read tags for these emails only (skips the full pull; read mode)
  --apply           actually perform writes (omit for a dry run)

EXAMPLES:
  # dry run — how many Outlook accounts on amplifyy domains?
  tag_accounts.py --type OUTLOOK --domain-contains amplifyy
  # create + assign
  tag_accounts.py --type OUTLOOK --domain-contains amplifyy --tag "Amplifyy - Hypertide" --color "#2563eb" --apply
  # assign an existing tag by id (no duplicate)
  tag_accounts.py --type SMTP --domain-contains amplifyy --tag-id 405504 --apply
  # remove a tag from a selection
  tag_accounts.py --domain-in amplifyseller.info --tag-id 405504 --action remove --apply
  # read tags for specific mailboxes
  tag_accounts.py --read --emails kevindormer@amplifyysales.info
"""
import argparse, csv as csvmod, json, os, re, subprocess, sys, time
from collections import Counter

BASE = "https://server.smartlead.ai/api/v1"


def load_key(cli):
    if cli:
        return cli
    path = os.path.expanduser("~/.navreo-keys.env")
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r"\s*(?:export\s+)?SMARTLEAD_API_KEY\s*=\s*(.+)", line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    sys.exit("SMARTLEAD_API_KEY not found — pass --api-key or add it to ~/.navreo-keys.env")


def call(key, method, path, body=None, tries=8):
    sep = "&" if "?" in path else "?"
    url = f"{BASE}/{path}{sep}api_key={key}"
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method, url,
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    for _ in range(tries):
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        nl = out.rfind("\n")
        code, payload = out[nl + 1:].strip(), out[:nl]
        if code == "429":
            time.sleep(12)
            continue
        try:
            return code, (json.loads(payload) if payload.strip() else {})
        except Exception:
            return code, {"raw": payload[:200]}
    return "429", {"err": "rate-limited after retries"}


def pull_all(key):
    out, off = [], 0
    while True:
        c, js = call(key, "GET", f"email-accounts/?offset={off}&limit=100")
        batch = js if isinstance(js, list) else js.get("data", [])
        if not batch:
            break
        out += batch
        if len(batch) < 100:
            break
        off += 100
    return out


def domain_of(a):
    e = (a.get("from_email") or "").lower()
    return e.split("@")[1] if "@" in e else ""


def select(accts, args):
    splitc = lambda s: [x.strip().lower() for x in s.split(",") if x.strip()] if s else []
    types = [t.upper() for t in splitc(args.type)]
    contains = splitc(args.domain_contains)
    dom_in = set(splitc(args.domain_in))
    excl = set(splitc(args.exclude_domain))
    name_sub = (args.from_name_contains or "").lower()
    ids = set(int(x) for x in splitc(args.ids)) if args.ids else set()
    if args.ids_from_csv:
        with open(args.ids_from_csv) as f:
            ids |= {int(r["id"]) for r in csvmod.DictReader(f)}
    out = []
    for a in accts:
        d = domain_of(a)
        if types and (a.get("type") or "").upper() not in types:
            continue
        if contains and not any(s in d for s in contains):
            continue
        if dom_in and d not in dom_in:
            continue
        if excl and d in excl:
            continue
        if name_sub and name_sub not in (a.get("from_name") or "").lower():
            continue
        if ids and a.get("id") not in ids:
            continue
        if args.smtp_host and (a.get("smtp_host") or "") != args.smtp_host:
            continue
        out.append(a)
    return out


def summarize(sel):
    by_type = Counter((a.get("type") or "?") for a in sel)
    print(f"matched {len(sel)} accounts")
    print("  by type: " + ", ".join(f"{k}={v}" for k, v in by_type.most_common()))
    print(f"  distinct domains: {len(set(domain_of(a) for a in sel))}")
    for a in sel[:10]:
        print(f"    {a.get('id')}  {(a.get('type') or '?'):8}  {a.get('from_email')}")
    if len(sel) > 10:
        print(f"    ... +{len(sel) - 10} more")


def resolve_tag_id(key, args, sample_emails):
    """Return an existing tag id (--tag-id), reuse a same-named tag already on the
    set, or create a new one. There is no list-all-tags endpoint, so reuse only
    works if the name is already assigned to one of the sampled accounts."""
    if args.tag_id:
        return int(args.tag_id)
    if sample_emails:
        c, js = call(key, "POST", "email-accounts/tag-list", {"email_ids": sample_emails[:25]})
        for row in (js.get("data") or []):
            for t in (row.get("tags") or []):
                if t.get("tag_name") == args.tag:
                    print(f"reusing existing tag '{args.tag}' id={t.get('tag_id')}")
                    return t.get("tag_id")
    c, js = call(key, "POST", "tags", {"name": args.tag, "color": args.color})
    tid = (js.get("data") or {}).get("id")
    if not tid:
        sys.exit(f"tag create failed: HTTP {c} {js}")
    print(f"created tag '{args.tag}' id={tid} (color {args.color})")
    return tid


def map_batches(key, ids, tag_id, remove):
    method = "DELETE" if remove else "POST"
    totals = Counter()
    n = (len(ids) + 24) // 25
    for i in range(0, len(ids), 25):
        c, js = call(key, method, "email-accounts/tag-mapping",
                     {"email_account_ids": ids[i:i + 25], "tag_ids": [tag_id]})
        summ = (js.get("data") or {}).get("summary") or {}
        for k, v in summ.items():
            totals[k] += v
        if c != "200":
            print(f"  batch {i // 25 + 1}/{n}: HTTP {c} {str(js)[:140]}")
    return totals


def read_tags(key, emails):
    for i in range(0, len(emails), 25):
        c, js = call(key, "POST", "email-accounts/tag-list", {"email_ids": emails[i:i + 25]})
        for row in (js.get("data") or []):
            tags = ", ".join(t.get("tag_name", "") for t in (row.get("tags") or []))
            print(f"  {row.get('email_id')}: [{tags}]")


def main():
    p = argparse.ArgumentParser(description="Bulk tag/untag/read Smartlead email accounts")
    p.add_argument("--api-key")
    for f in ["type", "domain-contains", "domain-in", "exclude-domain",
              "smtp-host", "from-name-contains", "ids", "ids-from-csv", "emails"]:
        p.add_argument("--" + f, dest=f.replace("-", "_"))
    p.add_argument("--tag")
    p.add_argument("--tag-id")
    p.add_argument("--color", default="#0d9488")
    p.add_argument("--action", choices=["assign", "remove"], default="assign")
    p.add_argument("--read", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    key = load_key(args.api_key)

    # read mode for explicit emails: no full pull needed
    if args.read and args.emails:
        read_tags(key, [e.strip() for e in args.emails.split(",") if e.strip()])
        return

    print("pulling all email accounts ...")
    accts = pull_all(key)
    print(f"workspace total: {len(accts)}")
    sel = select(accts, args)
    summarize(sel)
    if not sel:
        sys.exit("no accounts matched — refine the selection")

    emails = [a.get("from_email") for a in sel]
    if args.read:
        print("\ncurrent tags:")
        read_tags(key, emails)
        return

    if not (args.tag or args.tag_id):
        print("\n(dry run — selection only. Add --tag NAME or --tag-id ID, then --apply, to write.)")
        return
    if not args.apply:
        verb = "remove from" if args.action == "remove" else "assign to"
        print(f"\n(dry run — would {verb} {len(sel)} accounts. Add --apply to execute.)")
        return

    tag_id = resolve_tag_id(key, args, emails)
    ids = [a.get("id") for a in sel]
    print(f"\n{args.action}ing tag {tag_id} on {len(ids)} accounts (batches of 25)...")
    totals = map_batches(key, ids, tag_id, remove=(args.action == "remove"))
    print("result: " + ", ".join(f"{k}={v}" for k, v in totals.items()))

    print("\nverify sample:")
    read_tags(key, emails[:3])


if __name__ == "__main__":
    main()
