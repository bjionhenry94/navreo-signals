# AI Ark Reference (for qwintiq-list-building)

Everything you need to run AI Ark searches for this skill. AI Ark indexes about 70M companies
and about 500M people. There are TWO ways to call it: a connected tool (clean, recommended) and
the raw web API (works anywhere, a few quirks). Both hit the same data.

## Contents
1. Which path am I on? (tool vs raw API)
2. Connecting: Option A (tool / MCP) and Option B (raw API)
3. Resolving filter labels (industry, location)
4. Company search: params + count pattern
5. People search: params + count pattern + role-to-filter mapping
6. Billing (why the export gate exists)
7. Quirks that will bite you (READ THIS)
8. Troubleshooting

---

## 1. Which path am I on?

- **Connected tool ("MCP") path:** there are tools in this session whose names end in
  `company_search` and `people_search`. The server prefix is a long random id, e.g.
  `mcp__9e11f93d-...__company_search`. It is NOT called `ai-ark`. Search for the tool by its
  **bare name** (`company_search` / `people_search`), not by "ai-ark", or you will think it is
  missing. This path takes **flat parameters** and returns clean data. Prefer it.
- **Raw API path:** no such tool is loaded. You call AI Ark's web API directly with the user's
  key using a normal web request (curl). Works immediately, but read the Quirks section.

---

## 2. Connecting

### Option A: connect the tool (MCP), recommended for ongoing use

One-time. Add an `ai-ark` entry to the user's Claude config (`~/.claude.json`) under
`mcpServers`, using the `mcp-remote` bridge, with their key in the URL:

```json
"ai-ark": {
  "command": "npx",
  "args": ["-y", "mcp-remote@latest",
           "https://api.ai-ark.com/v1/mcp?token=THEIR_AI_ARK_KEY"]
}
```

Then the user must **fully quit and reopen the app** (not just a new chat) for the tool to load.
Needs Node/npm on their machine. After restart, the `company_search` / `people_search` tools
appear (under a random-id prefix). If they cannot restart now, use Option B for this session.

### Option B: raw API (no restart, paste-key)

Call the web API directly with the key in a header:

- Company search: `POST https://api.ai-ark.com/api/developer-portal/v1/companies`
- People search:  `POST https://api.ai-ark.com/api/developer-portal/v1/people`
- Header: `X-TOKEN: THEIR_AI_ARK_KEY`, `Content-Type: application/json`
- Rate limit: 5 requests/second. Put a 2-second pause between calls or rapid calls fail.

Request bodies use **nested** filters (a different shape from the flat tool params), see sections 4 and 5.

---

## 3. Resolving filter labels (do this before searching)

AI Ark's industry and location values are a **strict catalog**. A wrong label silently returns
0 or the wrong set. Resolve them first:

- **Industry** is an exact, usually **lowercase** label (e.g. `staffing and recruiting`,
  `dental`, `hospital & health care`, `marketing and advertising`). Capitalised or `&`-vs-`and`
  variants can return zero.
  - On the tool path: there are `industry_search` / `location_search` helper tools. Query them
    with the user's plain word ("recruitment", "dental") to get the exact catalog value(s). One
    intent can map to several labels, take them all.
  - On either path, a reliable trick: look up a **known firm in that vertical by its website**
    (company search by domain) and read the `industry` value AI Ark assigns it. That is the exact
    label to filter on. (Example: looking up a big staffing firm returns `staffing and recruiting`.)
- **Location** is a leaf name from the catalog: country (`United Kingdom`, `United States`,
  `Germany`), state/region, or continent. Continent for the Americas is `Northern America`
  (not "North America"). Pass leaf names only, never a combined "Country::State" path.

---

## 4. Company search

### Tool path (flat params): `company_search`
Key params:
- `industry`: exact catalog label, CSV for multiple (`"staffing and recruiting"`).
- `location`: leaf name(s), CSV for multiple (`"United Kingdom"`).
- `minEmployees` / `maxEmployees`: integers; these **do** filter on the tool path.
- `keyword` + `keywordMode` (SMART / WORD / STRICT): for tightening (e.g. keyword `"practice,clinic"`).
- `excludeIndustry`, `excludeType`, `excludeLocation`: for dropping leakage.
- `size`: rows per page (use **1** for a count). `page`: 0-based.
- Read **`totalElements`** from the response = total companies matching. That is the market-size number.

### Raw API path (nested): `/v1/companies`
```json
{
  "page": 0, "size": 1,
  "account": {
    "industry":     {"any": {"include": ["staffing and recruiting"]}},
    "location":     {"any": {"include": ["United Kingdom"]}},
    "employeeSize": {"type": "RANGE", "range": [{"start": 11, "end": 50}]},
    "keywords":     {"any": {"include": ["practice","clinic"]}}
  }
}
```
Read `totalElements`. **Note the size filter uses `employeeSize` RANGE here, NOT a `headcount`
bucket** (see Quirks). Company fields you will export: `summary.name`, `link.domain_ltd`
(canonical bare domain), `location.headquarter.country`, `summary.staff.total`, `summary.industry`,
`link.linkedin`.

### Count pattern (both paths)
Always count with `size: 1` and read `totalElements`. Never paginate the whole list to count;
that is an export and costs per row.

---

## 5. People search

### Tool path (flat params): `people_search`
Company-side filters are prefixed `company...`; person-side are bare:
- `companyIndustry`, `companyLocation`, `minEmployees`, `maxEmployees`: narrow by the person's company.
- `seniority`: CSV from `c_suite, vp, director, manager, senior, mid-level, entry, intern, owner,
  founder, head, partner`.
- `department`: CSV from `sales, business_development, operations, finance, marketing,
  human_resources, ...` (see the tool schema for the full list). **Not always "sales", match the brief.**
- `title`: a job-title string (e.g. "practice manager"). `excludeTitle`: titles to drop.
  `excludeSeniority`, `excludeDepartment`: exclusions.
- `size` (use **1** for a count), `page`. Read **`totalElements`**.

### Raw API path (nested): `/v1/people`
```json
{
  "page": 0, "size": 1,
  "account": {
    "industry":     {"any": {"include": ["staffing and recruiting"]}},
    "location":     {"any": {"include": ["United Kingdom"]}},
    "employeeSize": {"type": "RANGE", "range": [{"start": 11, "end": 50}]}
  },
  "contact": {
    "seniority": {"any": {"include": ["founder","owner","c_suite","partner","director","head","vp"]}}
  }
}
```
Read `totalElements`. Person fields you will export: `profile.full_name`, `profile.title`,
`link.linkedin`, plus the nested `company` object for the company name/domain.

### Role-to-filter mapping (the multi-count pattern)
Seniority, department, and title are ANDed within one search, so a brief naming more than one
kind of role usually needs **several counts that you sum** (keep them non-overlapping). Pick the
dial that isolates each role. The department is **not always "sales"**, match it to the brief.

- **Sales-led brief ("founders + sales leaders"):**
  - A: `seniority = founder,owner,c_suite,partner,director,head,vp` (no department).
  - B: `department = sales,business_development` AND `seniority = manager`, `excludeTitle = Account Manager`.
  - Total = A + B.
- **No-sales-function brief ("practice owners + practice managers", e.g. dental/clinics):**
  - A: `seniority = owner,founder,c_suite,partner,director`.
  - B: `title = "practice manager"` (title search; there is no sales department here).
  - Total = A + B.
- **Single-role brief ("heads of marketing"):** one count, `department = marketing` AND
  `seniority = head,director`. No summing.

After a fallback or broad pull, re-apply a title sanity check to drop off-brief hits.

---

## 6. Billing: why the export gate exists

AI Ark **charges per record returned.** A `size: 1` count costs about 1 credit and gives you the
full `totalElements` for free, which is why mapping is cheap. But pulling a full list of N rows
costs about N credits. So an "export everything" on a 50,000-match market is a 50,000-credit
event. That is exactly what the confirmation phrase in SKILL.md protects against. Treat any call
that returns more than one row as a spend that needs the gate.

---

## 7. Quirks that will bite you (READ THIS)

All confirmed live against the API:

1. **Industry label is lowercase-exact.** `"staffing and recruiting"` works; `"Staffing & Recruiting"`
   returns 0. Resolve the label first (section 3).
2. **Raw-API size filter:** the `headcount` bucket filter is **silently ignored** on the raw
   `/v1/companies` and `/v1/people` endpoints. The count comes back unchanged and giant companies
   still appear. **Use `employeeSize` with `type:"RANGE"`** instead (shown in sections 4 and 5).
   On the tool path, `minEmployees`/`maxEmployees` work correctly, no issue there.
3. **Raw-API responses contain literal newlines inside company/person descriptions**, which breaks
   strict JSON parsers (`jq` will choke). Parse with Python `json.loads(text, strict=False)`. The
   tool path returns clean data, no issue.
4. **`summary.staff.range` is unreliable** (often shows `start: 10001` even for tiny firms). Trust
   `summary.staff.total` for the real employee count. The size *filter* still works correctly
   despite the bad range echo.
5. **`totalElements` does not cap at 10,000.** It returns the true total (seen well into six figures).
6. **Rapid raw-API calls fail** (rate limit, 5/sec). Pause about 2 seconds between calls.

---

## 8. Troubleshooting

- **Count is 0 but you expected matches:** almost always the industry label (case, or `and` vs `&`).
  Re-resolve via section 3 (known-firm-domain lookup is the surest).
- **Size band seems ignored** (giant companies in results, count unchanged with vs without size):
  on the raw API you used `headcount` buckets; switch to `employeeSize` RANGE (quirk 2).
- **JSON will not parse / `jq` errors:** raw-API newline issue; parse with `strict=False` (quirk 3).
- **Tool says it is not available:** the MCP server is not loaded this session. Either set it up
  (Option A) and restart, or fall back to the raw API (Option B) with the user's key.
- **List looks padded with the wrong company types** (associations, suppliers, labs): broad
  industry-label leakage. Tighten with a `keyword` for the real target ("practice", "clinic",
  "agency") and/or `excludeIndustry` / `excludeType`, then re-count. Do this before the export gate.
- **Everything returns the full index regardless of filters:** the key may be a read-only / no-filter
  tier. Verify filters actually change the count (run a tight filter and check the total drops). If
  it never drops, ask the user for their filter-enabled AI Ark key.
