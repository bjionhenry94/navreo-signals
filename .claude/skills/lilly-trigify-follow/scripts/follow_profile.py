#!/usr/bin/env python3
"""
follow_profile.py — Trigify: "follow this LinkedIn profile's posts and push engagers to Clay."

What it does, end to end:
  1. Creates (or reuses) a DAILY LinkedIn profile monitor for the given profile.
  2. Creates a workflow BOUND to that monitor — binding (social_saved_search_id) can ONLY
     be set at workflow-creation time, so this is the only reliable way to make a New-Post
     workflow actually fire (see the gotcha in SKILL.md).
  3. The workflow, on each new post, scrapes commenters, enriches each person, and POSTs
     them to a Clay webhook.
  4. Verifies the new workflow is bound + enabled + pushing to Clay.

Auth: reads TRIGIFY_API_KEY from the environment (~/.navreo-keys.env auto-loads it).
A browser User-Agent is required or Cloudflare returns 403 error 1010.

Usage:
  python3 follow_profile.py --url https://www.linkedin.com/in/penn-frank
  python3 follow_profile.py --url <url> --name "Penn Frank" --clay-url <webhook>
  python3 follow_profile.py --url <url> --dry-run     # print the workflow def, change nothing
"""
import argparse, json, os, re, ssl, sys, urllib.request, urllib.error

API_BASE = "https://api.trigify.io"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# Default Clay destination (the workspace's "pull in data from a webhook" source).
DEFAULT_CLAY = ("https://api.clay.com/v3/sources/webhook/"
                "pull-in-data-from-a-webhook-f53ac2a4-0ada-4d79-bc14-49f022927bb3")


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl._create_unverified_context()


def api(path, key, method="GET", body=None):
    req = urllib.request.Request(API_BASE + path, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    req.add_header("x-api-key", key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=40, context=_ctx()) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": "non-json"}


def load_key():
    """TRIGIFY_API_KEY from the env, falling back to parsing ~/.navreo-keys.env
    (non-interactive shells don't auto-source it)."""
    key = os.environ.get("TRIGIFY_API_KEY")
    if key:
        return key
    path = os.path.expanduser("~/.navreo-keys.env")
    try:
        for line in open(path):
            m = re.match(r'^\s*export\s+TRIGIFY_API_KEY=("?)(.*?)\1\s*$', line)
            if m:
                return m.group(2)
    except FileNotFoundError:
        pass
    return None


def derive_name(url):
    """Best-effort display name from a LinkedIn /in/ or /company/ slug."""
    m = re.search(r"/(?:in|company)/([^/?#]+)", url)
    if not m:
        return url.strip()
    parts = m.group(1).split("-")
    # drop a trailing LinkedIn id hash (mix of letters+digits, length >= 6)
    while len(parts) > 1 and re.search(r"\d", parts[-1]) and len(parts[-1]) >= 6:
        parts.pop()
    return " ".join(w.capitalize() for w in parts) or url.strip()


def build_workflow_def(post_author_name, post_author_url, clay_url, max_comments):
    """Canonical 'comments engagers -> Clay' New-Post workflow definition.

    Mirrors the 45 proven '<Person> Engagers' workflows: New Post trigger ->
    get post comments -> loop -> enrich each commenter -> POST to Clay -> exit.
    The push body is a JSON *string* (that's how Trigify stores http_request bodies).
    """
    body = {
        "postAuthorName": post_author_name,
        "postUrl": "{{ !ref($.trigger.outputs.postUrl) }}",
        "postAuthorUrl": post_author_url,
        "postDatePosted": "{{ !ref($.trigger.outputs.datePosted) }}",
        "postText": "{{ !ref($.trigger.outputs.text) }}",
        "postLikes": "{{ !ref($.trigger.outputs.likes) }}",
        "postComments": "{{ !ref($.trigger.outputs.comments) }}",
        "engagementType": "comment",
        "engagedAt": "{{ !ref($.steps.loop.item.createdAtString) }}",
        "commentText": "{{ !ref($.steps.loop.item.text) }}",
        "commentPermalink": "{{ !ref($.steps.loop.item.permalink) }}",
        "commentLikes": "{{ !ref($.steps.loop.item.totalSocialActivityCounts.likeCount) }}",
        "engagerFirstName": "{{ !ref($.steps.enrich.result.firstName) }}",
        "engagerLastName": "{{ !ref($.steps.enrich.result.lastName) }}",
        "engagerFullName": "{{ !ref($.steps.enrich.result.fullName) }}",
        "engagerLinkedinUrl": "{{ !ref($.steps.enrich.result.linkedinUrl) }}",
        "engagerUsername": "{{ !ref($.steps.loop.item.author.username) }}",
        "engagerUrn": "{{ !ref($.steps.loop.item.author.urn) }}",
        "engagerHeadline": "{{ !ref($.steps.loop.item.author.title) }}",
        "engagerProfilePicture": "{{ !ref($.steps.loop.item.author.profilePicture[0].url) }}",
        "engagerOpenToWork": "{{ !ref($.steps.enrich.result.openToWork) }}",
        "engagerJobTitle": "{{ !ref($.steps.enrich.result.jobTitle) }}",
        "engagerCompanyName": "{{ !ref($.steps.enrich.result.companyName) }}",
        "engagerCompanyDomain": "{{ !ref($.steps.enrich.result.companyDomain) }}",
        "engagerCompanyIndustry": "{{ !ref($.steps.enrich.result.companyIndustry) }}",
        "engagerCompanyHeadCount": "{{ !ref($.steps.enrich.result.companyHeadCount) }}",
        "engagerCompanyDescription": "{{ !ref($.steps.enrich.result.companyDescription) }}",
        "engagerCountry": "{{ !ref($.steps.enrich.result.country) }}",
        "engagerLocation": "{{ !ref($.steps.enrich.result.location) }}",
    }
    return {
        "trigger": {"kind": "workflows/new-post"},
        "actions": [
            {"id": "getComments", "kind": "linkedin_get_post_comments",
             "inputs": {"postUrl": "{{ !ref($.trigger.outputs.postUrl) }}",
                        "maxComments": max_comments}},
            {"id": "loop", "kind": "builtin:loop",
             "inputs": {"collection": "{{ !ref($.steps.getComments.result.data.items) }}"}},
            {"id": "enrich", "kind": "person_enrichment",
             "inputs": {"profile": "{{ !ref($.steps.loop.item.author.linkedinUrl) }}"}},
            {"id": "push", "kind": "http_request",
             "inputs": {"url": clay_url, "body": json.dumps(body), "method": "POST",
                        "headers": {"Content-Type": "application/json"}}},
            {"id": "_exit_done", "kind": "builtin:exit", "inputs": {}},
        ],
        "edges": [
            {"to": "getComments", "from": "$source"},
            {"to": "loop", "from": "getComments"},
            {"to": "enrich", "from": "loop", "name": "For Each Comment",
             "conditional": {"ref": "!ref($.steps.loop.isCompleted)", "type": "loop"}},
            {"to": "push", "from": "enrich"},
            {"to": "_exit_done", "from": "loop", "name": "Completed",
             "conditional": {"ref": "!ref($.steps.loop.isCompleted)", "type": "completed"}},
        ],
    }


def main():
    ap = argparse.ArgumentParser(description="Follow a LinkedIn profile's posts -> push engagers to Clay")
    ap.add_argument("--url", required=True, help="LinkedIn profile or company URL")
    ap.add_argument("--name", help="Display name (default: derived from the URL slug)")
    ap.add_argument("--clay-url", default=DEFAULT_CLAY, help="Clay webhook URL (default: workspace Clay source)")
    ap.add_argument("--max-comments", type=int, default=25)
    ap.add_argument("--max-results", type=int, default=50, help="Monitor max results per run")
    ap.add_argument("--frequency", default="DAILY",
                    choices=["EVERY_12H", "DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"])
    ap.add_argument("--force", action="store_true", help="Create even if a workflow for this person exists")
    ap.add_argument("--dry-run", action="store_true", help="Print the workflow definition and exit")
    args = ap.parse_args()

    name = args.name or derive_name(args.url)
    search_name = f"Profile Monitor — {name}"      # em dash, matches existing monitors
    wf_name = f"{name} Engagers → Clay"            # arrow, matches existing workflows
    print(f"Profile : {args.url}\nName    : {name}\nMonitor : {search_name}\nWorkflow: {wf_name}\nClay    : {args.clay_url}\n")

    wf = build_workflow_def(name, args.url, args.clay_url, args.max_comments)
    if args.dry_run:
        print(json.dumps(wf, indent=2))
        return

    key = load_key()
    if not key:
        sys.exit("ERROR: TRIGIFY_API_KEY not set (it lives in ~/.navreo-keys.env).")

    # Guard: don't silently duplicate an existing pipeline for this person.
    s, wl = api("/v1/workflows?limit=100", key)
    if s == 200:
        dupes = [w["name"] for w in wl["data"]["items"]
                 if w["name"].lower().startswith(name.lower() + " engagers")]
        if dupes and not args.force:
            sys.exit(f"ABORT: a workflow already exists for this person: {dupes}. "
                     f"Re-run with --force to create another, or edit by recreate+delete.")

    # 1) Reuse an existing monitor with the same name, else create one.
    s, sl = api("/v1/searches", key)
    search_id = None
    if s == 200:
        for x in sl["data"]:
            if x["name"] == search_name:
                search_id = x["id"]
                print(f"Reusing existing monitor: {search_id}")
                break
    if not search_id:
        s, r = api("/v1/searches/linkedin/profile", key, "POST",
                   {"name": search_name, "profile_url": args.url,
                    "frequency": args.frequency, "max_results": args.max_results})
        if s not in (200, 201):
            sys.exit(f"ERROR creating monitor: HTTP {s} {r}")
        search_id = (r.get("data") or r).get("id")
        print(f"Created monitor: {search_id}")

    # 2) Create the workflow BOUND to the monitor (search_id binds it at creation).
    s, r = api("/v1/workflows", key, "POST",
               {"name": wf_name,
                "description": f"On each new post by {name}: scrape commenters -> enrich -> push engagers to Clay.",
                "workflow": wf, "search_id": search_id,
                "status": "PUBLISHED", "enabled": True})
    if s not in (200, 201):
        sys.exit(f"ERROR creating workflow: HTTP {s} {r}")
    nid = r["data"]["id"]

    # 3) Verify binding + destination + state.
    s, g = api(f"/v1/workflows/{nid}", key)
    d = g["data"]
    push = [a["inputs"].get("url") for a in d["workflow"]["actions"] if a.get("id") == "push"]
    ok = (d.get("social_saved_search_id") == search_id
          and push == [args.clay_url] and d["status"] == "PUBLISHED" and d["enabled"])
    print(f"\nWorkflow created: {nid}")
    print(f"  bound to monitor : {d.get('social_saved_search_id') == search_id}")
    print(f"  pushes to Clay   : {push == [args.clay_url]}")
    print(f"  published+enabled: {d['status']=='PUBLISHED' and d['enabled']}")
    print("\nDONE ✅" if ok else "\nVERIFICATION FAILED ❌ — inspect the workflow before relying on it.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
