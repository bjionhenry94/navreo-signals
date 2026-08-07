---
name: lilly-trigify-follow
description: Follow a single LinkedIn profile's (or company page's) posts in Trigify and push every post-engager straight into Clay. Given just a LinkedIn URL, it provisions the whole pipeline end to end — creates a DAILY profile monitor (saved search), then creates a New-Post workflow BOUND to that monitor (binding is creation-only in Trigify) that, on each new post, scrapes the commenters, enriches each person, and POSTs them to a Clay webhook — then verifies the workflow is bound, enabled, and pushing to Clay. Use whenever the user wants to start tracking/following a person's or company's LinkedIn posts and capture who engages, e.g. 'here's a LinkedIn URL, follow their posts', 'follow this person on LinkedIn and push to Clay', 'track [name]'s posts', 'add [profile] to the engagement pipeline', 'set up a Trigify monitor for this profile', 'watch this profile's posts and send engagers to Clay'. This is the lightweight single-profile sibling of lilly-trigify-setup (the full brief wizard) — use THIS when the ask is simply 'follow this one profile -> Clay'. Knows the critical Trigify gotcha: the search-to-workflow binding can only be set at workflow creation; updating a bound workflow (e.g. changing its webhook) silently strips the binding and stops it firing, so edits must be done by recreate-then-delete.
---

# Lilly Trigify Follow

## Purpose

Turn "here's a LinkedIn URL, follow their posts" into a live Trigify pipeline that pushes post-engagers to Clay — in one step. One profile = one run.

For each new post the tracked profile publishes, the workflow scrapes the commenters, enriches each (name, title, company, domain, industry, location, etc.), and POSTs every engager to a Clay webhook as a row.

This is the single-profile utility. For a full multi-account brief (ICP, competitor lists, Make + Sheet + Smartlead provisioning) use `lilly-trigify-setup` instead.

## Quick start

```bash
python3 ~/.claude/skills/lilly-trigify-follow/scripts/follow_profile.py \
  --url https://www.linkedin.com/in/penn-frank
```

That's the whole job. The script creates the monitor, creates the bound workflow, and prints a pass/fail verification. Add `--name "Penn Frank"` if the URL slug doesn't produce a clean display name, or `--dry-run` to preview the workflow definition without changing anything.

## Inputs & defaults

| Thing | Default | Notes |
|---|---|---|
| `--url` (required) | — | LinkedIn profile (`/in/...`) or company (`/company/...`) URL |
| `--name` | derived from URL slug | display name for the monitor + workflow |
| `--clay-url` | the workspace Clay "pull in data from a webhook" source | override to send elsewhere |
| `--max-comments` | 25 | commenters scraped per post |
| `--frequency` | `DAILY` | how often the monitor checks for new posts |
| `--max-results` | 50 | monitor results per run |

Naming it uses (matches every existing pipeline): monitor = `Profile Monitor — {Name}` (em dash), workflow = `{Name} Engagers → Clay` (arrow). The workflow is created `PUBLISHED` + `enabled`.

Auth: the script reads `TRIGIFY_API_KEY` from the environment (lives in `~/.navreo-keys.env`, auto-loaded by the shell). A browser User-Agent is sent automatically — without it Trigify's Cloudflare returns `403 error 1010`.

## How it works (3 steps the script performs)

1. **Create / reuse the monitor** — `POST /v1/searches/linkedin/profile` (monitoring type `linkedin-profile`), daily. If a monitor named `Profile Monitor — {Name}` already exists it is reused (no wasted credit / duplicate).
2. **Create the workflow, bound to the monitor** — `POST /v1/workflows` with `search_id` set to the monitor's id. The definition is the canonical `New Post → get comments → loop → enrich → push to Clay → exit` graph (same as the 45 proven `… Engagers` workflows). The push body carries the full engager field set.
3. **Verify** — re-fetch the workflow and confirm `social_saved_search_id` == the monitor, the push action's URL == Clay, and `status=PUBLISHED, enabled=true`.

It first guards against duplicates: if a workflow whose name starts with `{Name} Engagers` already exists it aborts (use `--force` to override).

## ⚠️ The one critical gotcha — binding is creation-only

The thing that makes a New-Post workflow actually fire is the workflow-level field **`social_saved_search_id`** (the linked monitor). In Trigify:

- This binding can be set **only when the workflow is created** (`search_id` on create).
- **`update_workflow` (MCP) and `PATCH /v1/workflows/{id}` (REST) do NOT carry it** — calling either to change *anything* (even just the webhook URL) **silently resets the binding to null**, and the workflow stops firing. (This is exactly how 17 working workflows got silently unbound during a bulk webhook-URL change.)
- The Trigify **web UI** can bind in place; the API cannot.

**Therefore: never edit a bound workflow via the API.** To change a bound workflow (new webhook, tweaked copy, etc.): create a replacement with `search_id` set, verify it, then `DELETE` the old one. The old being unbound first means no double-fire. (Recreating changes the workflow ID — harmless, nothing external references it.)

## Editing / re-pointing an existing followed profile

Don't PATCH it. Recreate it:
1. `GET /v1/workflows/{id}` — grab its current definition + its `social_saved_search_id`.
2. Make your change to the definition.
3. `POST /v1/workflows` with the edited definition + the same `search_id`, `status:PUBLISHED, enabled:true`.
4. Verify the new one is bound, then `DELETE /v1/workflows/{oldId}`.

## Stop / pause following a profile

- Pause: `update_workflow`/`PATCH` with `enabled:false` (safe — you're not relying on the binding).
- Stop the monitor too: `PATCH /v1/searches/{id}` with `status:paused`.
- Remove entirely: `DELETE /v1/workflows/{id}` (and optionally the monitor).

## Alternative: do it via the Trigify MCP (no key needed)

The same flow works through the Trigify MCP tools:
1. `create_linkedin_profile_search` → `{ name: "Profile Monitor — {Name}", profile_url, frequency: "DAILY", max_results: 50 }` → note the returned search id.
2. `create_workflow` → `{ name: "{Name} Engagers → Clay", workflow: <canonical def>, search_id: <id>, status: "PUBLISHED", enabled: true }`.
3. Re-fetch and confirm `social_saved_search_id` is set.

Use the script when you want a verified one-shot; use the MCP when you're already mid-conversation and want no shell. Either way, **verify the binding after** — an empty `social_saved_search_id` means it will never fire.

## Trigify REST API reference

- Base: `https://api.trigify.io/v1` · auth header: `x-api-key: <TRIGIFY_API_KEY>` (in `~/.navreo-keys.env`).
- Send a normal browser `User-Agent` or Cloudflare blocks with `403 error 1010`.
- OpenAPI spec: `https://api.trigify.io/docs`. `curl` is absent on this machine — use `python3` urllib (the script does).
- Workflow list is paginated 20/page — use `?limit=100&offset=`.
- Key endpoints: `POST /v1/searches/linkedin/profile`, `GET /v1/searches`, `POST /v1/workflows`, `GET|PATCH|DELETE /v1/workflows/{id}`.

## Communication style

Report results in plain English: "I'm now following [name]'s posts — every new post, the people who comment get enriched and dropped into Clay." Avoid jargon (binding, social_saved_search_id, webhook, trigger) when talking to the user; keep that detail for the logs.

See also: `lilly-trigify-setup` (full brief wizard), `lilly-trigify-data-processing` (downstream enrichment + Smartlead push). The binding gotcha is also recorded in memory under `reference_trigify_api_workflow_search_binding`.
