---
name: lilly-slay
description: "One-prompt web research via the Slaygent API — send a question, get back an evidence-backed answer with cited sources. Use whenever the user wants a fresh, cited answer researched from the live web from a single prompt: 'research whether X', 'find out online if…', 'check whether [company] is hiring [role]', 'what does [company/site] say about…', 'look this up on the web and cite it', 'slaygent this', '/lilly-slay …'. Also fires when the user pastes a URL and asks what it says / to extract something from it. NOT for the full Loom company deep-dive pack (overview + ICP + clients + events + competitors + org chart) — that is loom-research. NOT for internal outreach history (that is lilly-data) or TAM sizing (lilly-tam). This is a thin wrapper around one external research call; it never enriches leads, never writes to Smartlead/Supabase, and spends Slaygent credits only when it actually runs a query."
---

# lilly-slay — One-Prompt Web Research (Slaygent)

## Purpose

Thin wrapper around the **Slaygent** research API. You give it a plain-English question (optionally a URL) and it plans searches, scrapes authoritative sources, and returns a synthesised, **cited** answer. Use it for quick evidence-backed lookups — not the full `loom-research` company pack.

- **API base:** `https://api.slaygent.co`
- **Auth:** header `X-API-Key: $SLAYGENT_API_KEY` — always `source ~/.navreo-keys.env` first (key is NOT in this repo).
- **Credits:** prompt-only (open-web) research = **2 credits**; a prompt that contains an explicit URL (or you pass `"url"`) = **1 credit**. Confirm with the user before firing a batch of many queries.

## When to use vs not

| Use `lilly-slay` | Use something else |
|---|---|
| "Research whether Acme is hiring web devs, cite it" | Full Loom prospecting pack → **loom-research** |
| "What does this page say about pricing?" (+URL) | "Have we emailed anyone at acme.com?" → **lilly-data** |
| "Find an evidence-backed answer to <question>" | "How big is the TAM for…" → **lilly-tam** |
| One-off cited fact-check / open-web lookup | Company deep-dive with ICP + org chart → **loom-research** |

## Quickstart (sync — default)

Most questions complete in one call. `source` the keys, POST the prompt, read `.result` + `.sources`.

```bash
source ~/.navreo-keys.env
curl -s -m 90 -X POST "https://api.slaygent.co/v1/research" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SLAYGENT_API_KEY" \
  -d '{
    "prompt": "Check whether Microsoft is currently hiring web developers. Prioritize official listings and cite the evidence.",
    "response_format": "text"
  }'
```

Read from the response:
- `.result` — the prose answer (the thing to show the user)
- `.sources[]` — `{url, title, from_cache}`; **always surface these as the citations**
- `.status` — `"completed"` when done
- `.pages_analyzed`, `.web_search_used` — provenance to mention if useful
- `.could_not_answer: true` — say so plainly; don't fabricate an answer
- `.resolved_target` — which entity Slaygent decided you meant (check `.confidence`)

### Request body (POST /v1/research)

| field | type | default | notes |
|---|---|---|---|
| `prompt` | string | — | **required**, max 5000 chars. Be specific; ask it to cite. |
| `url` | string | — | optional target URL for site-specific research |
| `allow_web_search` | bool | `false` | let a URL-scoped request fall back to open-web search |
| `response_format` | string | `"text"` | `"text"` for prose, `"json"` for structured extraction |
| `async_mode` | bool | `false` | return `202` + `task_id` immediately, then poll |
| `no_cache` | bool | `false` | skip the page cache and scrape fresh (use for time-sensitive facts) |

Prompt-writing tips: name the entity precisely (add the domain if the name is common), state the freshness you need, and explicitly ask it to "cite the evidence" so `.sources` is well-populated.

## Async / long research (poll)

Use `async_mode: true` for heavy questions, or fall back to polling if a **sync call returns HTTP 202** (server-side timeout). Poll `GET /v1/research/{task_id}` every 1–2s until `status` is `completed` or `failed`.

```bash
source ~/.navreo-keys.env
# 1) kick off
task_id=$(curl -s -X POST "https://api.slaygent.co/v1/research" \
  -H "Content-Type: application/json" -H "X-API-Key: $SLAYGENT_API_KEY" \
  -d '{"prompt":"<your question>","async_mode":true}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["task_id"])')

# 2) poll until done (cap the loop; 1–2s between polls)
for i in $(seq 1 60); do
  resp=$(curl -s "https://api.slaygent.co/v1/research/$task_id" \
    -H "X-API-Key: $SLAYGENT_API_KEY")
  status=$(printf '%s' "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status"))')
  [ "$status" = "completed" ] && { printf '%s' "$resp"; break; }
  [ "$status" = "failed" ]    && { echo "FAILED: $resp"; break; }
  sleep 2
done
```

## Handling failures (report honestly, don't retry blind)

- **`ambiguous_target`** (task fails safely) → response carries `resolution_candidates[]`. Show the candidates and ask the user which one, or re-run with the domain pinned in the prompt. Don't pick silently.
- **`could_not_answer: true`** → tell the user Slaygent couldn't find an answer; offer to broaden the prompt or add `no_cache:true`. Never invent a result.
- **HTTP 401** `{"detail":"Invalid or missing API key."}` → the env var didn't load. Re-run `source ~/.navreo-keys.env` in the SAME shell as the curl.
- **HTTP 402** `Insufficient credits` → out of Slaygent credits; tell the user, don't loop.
- **HTTP 429** `Rate limit exceeded. Try again in N seconds.` → back off for the stated seconds, then one retry.
- **HTTP 503** `Could not reach target site` → the target is down/blocking; for a URL request try `allow_web_search:true`, else report it.
- **HTTP 000 / no body** → DNS or network; confirm host is `api.slaygent.co` and connectivity.

## Guardrails

- Read-only research tool. It never sends outreach, never writes to Smartlead/Supabase, never enriches or uploads leads.
- Always pass the key via `$SLAYGENT_API_KEY` from `~/.navreo-keys.env`; never paste the raw `slay_…` key into a file, a committed script, or chat.
- Every answer you relay MUST carry its `.sources`. If `sources` is empty and `web_search_used` is false, flag the answer as low-confidence.
- Credits cost money — for more than a handful of queries, tell the user the count × 2 credits and confirm before running the batch.
