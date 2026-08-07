# Sales Nav Filter Types

Reference list of filter `type:` values that Sales Nav accepts in the `filters:List(...)` structure. Each filter takes a `values:List(...)` of items.

There are two item formats:
- **text-only:** `(text:X,selectionType:INCLUDED)`
- **id+text:**  `(id:X,text:Y,selectionType:INCLUDED)`

Critical: filters that require id+text format silently drop if you give them text-only items.

## Company filters

| Type | Item format | Notes |
|---|---|---|
| `CURRENT_COMPANY` | text-only (or id+text) | Person currently works there. Text auto-resolves; numeric ID is precise. |
| `PAST_COMPANY` | text-only (or id+text) | Person previously worked there. Useful for alumni outreach. |
| `COMPANY_HEADCOUNT` | **id+text** | Letter code as id, range as text. See table below. |
| `COMPANY_TYPE` | text-only | `Public Company`, `Privately Held`, `Non Profit`, `Educational Institution`, `Self Employed`, `Government Agency`, `Sole Proprietorship`, `Partnership` |
| `INDUSTRY` | text-only | Free text matching LinkedIn's industry taxonomy (e.g. `Apparel & Fashion`, `Cosmetics`, `Information Technology and Services`) |

### COMPANY_HEADCOUNT codes (id, text)

| id | text |
|---|---|
| `A` | `Self-employed` |
| `B` | `1-10` |
| `C` | `11-50` |
| `D` | `51-200` |
| `E` | `201-500` |
| `F` | `501-1000` |
| `G` | `1001-5000` |
| `H` | `5001-10000` |
| `I` | `10001+` |

## Person filters

| Type | Item format | Notes |
|---|---|---|
| `CURRENT_TITLE` | text-only | Person's current job title (substring/keyword match). |
| `PAST_TITLE` | text-only | Person's past job titles. |
| `SENIORITY_LEVEL` | **id+text** | Numeric seniority ID + display name. See table below. |
| `FUNCTION` | text-only | `Accounting`, `Administrative`, `Arts and Design`, `Business Development`, `Community and Social Services`, `Consulting`, `Education`, `Engineering`, `Entrepreneurship`, `Finance`, `Healthcare Services`, `Human Resources`, `Information Technology`, `Legal`, `Marketing`, `Media and Communication`, `Military and Protective Services`, `Operations`, `Product Management`, `Program and Project Management`, `Purchasing`, `Quality Assurance`, `Real Estate`, `Research`, `Sales`, `Support` |
| `YEARS_AT_CURRENT_COMPANY` | text-only | `Less than 1 year`, `1 to 2 years`, `3 to 5 years`, `6 to 10 years`, `More than 10 years` |
| `YEARS_IN_CURRENT_POSITION` | text-only | Same buckets as above |
| `YEARS_OF_EXPERIENCE` | text-only | Same buckets as above |
| `SCHOOL` | text-only (or id+text) | School the person attended. |

### SENIORITY_LEVEL IDs (id, text)

| id | text |
|---|---|
| `110` | `Entry Level` |
| `130` | `Senior` |
| `200` | `Manager` |
| `210` | `Senior Manager` |
| `220` | `Director` |
| `230` | `Senior Director` |
| `300` | `Vice President` |
| `310` | `CXO` |
| `320` | `Owner / Partner` |

## Geography filters — REGION + GEOGRAPHY (use both)

Sales Nav has two location-related filters and you must populate **both** for filtering to work.

| Type | Item format | Role |
|---|---|---|
| `GEOGRAPHY` | text-only (URN ID as the text value) | Renders the location chips visually. **Does NOT actually filter results.** |
| `REGION` | **id+text** (URN ID as id, country name as text) | The operational filter that narrows results to those locations. |

The script auto-emits BOTH when you supply `geographies` in the config. Don't try to populate just one.

### Common geo-URN IDs (id, text)

Navreo's high-GDP/high-salary set:

| URN ID | Country |
|---|---|
| `103644278` | United States |
| `101174742` | Canada |
| `101165590` | United Kingdom |
| `101452733` | Australia |
| `104738515` | Ireland |
| `105490917` | New Zealand |
| `101282230` | Germany |
| `102890719` | Netherlands |
| `106693272` | Switzerland |
| `105117694` | Sweden |
| `103819153` | Norway |
| `104514075` | Denmark |
| `100456013` | Finland |
| `102454443` | Singapore |

Additional common markets supported by the script:

| URN ID | Country |
|---|---|
| `105015875` | France |
| `103350119` | Italy |
| `105646813` | Spain |
| `100565514` | Belgium |
| `103883259` | Austria |
| `105072130` | Poland |
| `106057199` | Brazil |
| `103323778` | Mexico |
| `101355337` | Japan |
| `102713980` | India |
| `102890883` | China |
| `104305776` | United Arab Emirates |
| `104035573` | South Africa |
| `101620260` | Israel |
| `103291313` | Hong Kong |
| `100364837` | Portugal |
| `104508036` | Czech Republic |
| `104677530` | Greece |
| `106670623` | Romania |
| `100288700` | Hungary |

To find a URN for a country not in the list, click the country in Sales Nav's UI region picker and copy the URN from the resulting URL (the long numeric string under `REGION`'s `id:`). Add it to `COUNTRY_TO_URN` in `build_sales_nav_url.py`.

| Type | Item format | Notes |
|---|---|---|
| `POSTAL_CODE` | structured | ZIP/postcode + radius — different value format with `geo:`, `radius:` keys. |

## Engagement / signal filters

| Type | Notes |
|---|---|
| `FOLLOWING_YOUR_COMPANY` | Boolean — different filter mechanic, not a values-list. |
| `VIEWED_YOUR_PROFILE_RECENTLY` | Boolean — same. |
| `RECENTLY_CHANGED_JOBS` | Boolean — job-changers in the past 90 days. |
| `MENTIONED_IN_NEWS` | Boolean — person was mentioned in news in the past 30 days. |
| `POSTED_ON_LINKEDIN` | Boolean — posted on LinkedIn in the past 30 days. |

## Connection filters

| Type | Item format | Notes |
|---|---|---|
| `RELATIONSHIP` | text-only | `F` (1st-degree), `S` (2nd-degree), `O` (3rd-degree+), `IN` (Group members), `TM` (Teamlink) |
| `TEAMLINK_INTRO` | Boolean | Person can be intro'd via your team. |
| `GROUP` | id-only | Numeric LinkedIn group ID. |

## Notes for the script

- The script's `KNOWN_FILTER_TYPES` set includes the most common ones. If the user requests a filter type not in that set, the script warns but still emits it — Sales Nav will ignore unknown types silently.
- Boolean filters (e.g. `FOLLOWING_YOUR_COMPANY`) need a different rendering than the standard items — not currently supported by the script.
- The `EXCLUDED` selection type is supported by the URL format but not currently exposed via CLI/config. To add: introduce an `excluded` list per filter in the config schema, render those items with `selectionType%3AEXCLUDED`.
