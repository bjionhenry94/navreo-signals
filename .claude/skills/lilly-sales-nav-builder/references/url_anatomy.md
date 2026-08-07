# Sales Nav URL Anatomy

Detailed reference for the LinkedIn Sales Navigator query-string format. Use this when you need to debug a malformed URL, add a new filter type to the script, or understand what the script is generating.

## Top-level structure

```
https://www.linkedin.com/sales/search/people#query=(<query_value>)
```

Sales Nav uses a **hash fragment** (`#query=`), NOT a query string (`?query=`). The query-string form silently drops filters on page load — it must be `#query=`.

The `<query_value>` is a comma-separated list of key:value pairs, wrapped in parentheses. The keys appear in a fixed-ish order. The most common keys:

| Key | Used for |
|---|---|
| `keywords` | Free-text full-profile search |
| `filters` | The filter list (`List(...)` of filter tuples) |
| `recentSearchParam` | Session-specific cruft from a saved search — ignore when building from scratch |
| `spellCorrectionEnabled` | Boolean toggle (default true) |

The script only emits `keywords` and `filters` — that's all you need for a fresh URL.

## Filter list structure

```
filters%3AList(<filter1>%2C<filter2>%2C...)
```

Each `<filterN>` is a tuple:

```
(type%3A<TYPE>%2Cvalues%3AList(<item1>%2C<item2>%2C...))
```

Each `<itemN>` is one of two formats depending on the filter type:

**Text-only:**
```
(text%3A<value>%2CselectionType%3AINCLUDED)
```

**ID + text:**
```
(id%3A<id_value>%2Ctext%3A<display_text>%2CselectionType%3AINCLUDED)
```

The `selectionType` can be `INCLUDED` (must match) or `EXCLUDED` (must not match). The script defaults to INCLUDED.

## Which filters use which item format

| Filter type | Item format | Notes |
|---|---|---|
| `CURRENT_TITLE` / `PAST_TITLE` | text-only | Free-text title strings |
| `CURRENT_COMPANY` / `PAST_COMPANY` | text-only (or id+text for precision) | Numeric company ID auto-resolves perfectly |
| `INDUSTRY` | text-only | Free-text industry name (LinkedIn taxonomy) |
| `GEOGRAPHY` | text-only | URN ID as the text value (renders chips, doesn't filter) |
| `REGION` | **id+text** | Numeric URN as id, country name as text — the actual location filter |
| `SENIORITY_LEVEL` | **id+text** | Numeric seniority ID as id, name as text |
| `COMPANY_HEADCOUNT` | **id+text** | Letter code as id (B/C/D/...), range as text ("1-10"/...) |
| `FUNCTION` | text-only | Function name from LinkedIn taxonomy |

**Critical:** filters that require id+text format silently drop if you provide text-only items. The script's `translate_*` helpers handle the format mapping.

## REGION vs GEOGRAPHY (the location-filter trap)

Sales Nav has TWO location-related filter types and you must populate BOTH for filtering to work:

- **`GEOGRAPHY`** — text-only items with URN IDs as the text value. Used to render the location chips visually in the UI. Does NOT actually narrow the result set.
- **`REGION`** — id+text items where `id` is the URN ID and `text` is the country name. This is the operational filter that narrows results.

If you populate only `GEOGRAPHY`, the chips appear but results are not filtered to those countries. If you populate only `REGION`, filtering works but the UI may not show the chip clearly. Always emit both — the script does this automatically when you supply `geographies` in the config.

## Tree view of a complete URL

A 5-filter URL (CURRENT_TITLE + GEOGRAPHY + REGION + SENIORITY_LEVEL + COMPANY_HEADCOUNT) decomposes like:

```
#query=(
  filters:List(
    (type:CURRENT_TITLE,values:List(
      (text:Head of Amazon,selectionType:INCLUDED),
      (text:VP Marketing,selectionType:INCLUDED),
      ...
    )),
    (type:GEOGRAPHY,values:List(
      (text:103644278,selectionType:INCLUDED),
      (text:101165590,selectionType:INCLUDED)
    )),
    (type:REGION,values:List(
      (id:103644278,text:United States,selectionType:INCLUDED),
      (id:101165590,text:United Kingdom,selectionType:INCLUDED)
    )),
    (type:SENIORITY_LEVEL,values:List(
      (id:300,text:Vice President,selectionType:INCLUDED),
      (id:220,text:Director,selectionType:INCLUDED)
    )),
    (type:COMPANY_HEADCOUNT,values:List(
      (id:D,text:51-200,selectionType:INCLUDED),
      (id:E,text:201-500,selectionType:INCLUDED)
    ))
  )
)
```

After encoding, that becomes the long single-line URL the browser reads.

## Encoding rules (the gotcha)

Sales Nav uses **double encoding** for text values. There are two passes:

**Pass 1 — Inner encoding.** Each text value gets standard URL encoding:
- ` ` → `%20`
- Other special chars → `%xx`

**Pass 2 — Outer encoding.** The whole `query=` parameter value gets encoded again:
- The `%` from pass 1 becomes `%25`, so `%20` becomes `%2520`
- `:` becomes `%3A`
- `,` becomes `%2C`
- `(` and `)` are NOT encoded — they're treated as syntax, not data

So the value `Inventus Group` ends up as `Inventus%2520Group` in the final URL.

The script handles this in `encode_text_value()`:

```python
def encode_text_value(value: str) -> str:
    inner = urllib.parse.quote(value, safe="-")    # pass 1
    return inner.replace("%", "%25")               # pass 2
```

## Paren counting

This is the #1 source of broken URLs. Every `(` must have a matching `)`. The script's `validate_paren_balance()` does a global open/close count. If they're unequal, the URL is malformed — Sales Nav will either return a blank page or silently drop a filter.

## Filter type names

See `filter_types.md` for the full list of names that Sales Nav recognises and the value formats each accepts.

## ID-based vs text-based company filters

For `CURRENT_COMPANY` / `PAST_COMPANY`, the script outputs **text-based** items: `(text:Stefanini,selectionType:INCLUDED)`. Sales Nav tries to auto-resolve the text to an actual company, but it doesn't always succeed.

The **ID-based** form is more precise:

```
(id:1337,text:Stefanini,selectionType:INCLUDED)
```

…where `1337` is LinkedIn's numeric company ID. To get IDs, look them up via Sales Nav's UI (search the company, copy the URL, parse the ID) or via the LinkedIn API.

## Reference URL — fully populated 6-filter

```
https://www.linkedin.com/sales/search/people#query=(filters%3AList((type%3ACURRENT_TITLE%2Cvalues%3AList((text%3AHead%2520of%2520Amazon%2CselectionType%3AINCLUDED)%2C(text%3AVP%2520Marketing%2CselectionType%3AINCLUDED)))%2C(type%3AGEOGRAPHY%2Cvalues%3AList((text%3A103644278%2CselectionType%3AINCLUDED)%2C(text%3A101165590%2CselectionType%3AINCLUDED)))%2C(type%3AREGION%2Cvalues%3AList((id%3A103644278%2Ctext%3AUnited%2520States%2CselectionType%3AINCLUDED)%2C(id%3A101165590%2Ctext%3AUnited%2520Kingdom%2CselectionType%3AINCLUDED)))%2C(type%3AINDUSTRY%2Cvalues%3AList((text%3AApparel%2520%2526%2520Fashion%2CselectionType%3AINCLUDED)))%2C(type%3ASENIORITY_LEVEL%2Cvalues%3AList((id%3A300%2Ctext%3AVice%2520President%2CselectionType%3AINCLUDED)%2C(id%3A220%2Ctext%3ADirector%2CselectionType%3AINCLUDED)))%2C(type%3ACOMPANY_HEADCOUNT%2Cvalues%3AList((id%3AD%2Ctext%3A51-200%2CselectionType%3AINCLUDED)%2C(id%3AE%2Ctext%3A201-500%2CselectionType%3AINCLUDED)))))
```

## Length limits

Browsers and servers have practical URL length caps:
- Chrome / Edge / Firefox: ~32 kB officially, ~8 kB in practice
- LinkedIn server: appears to truncate ~10 kB based on observation
- Sales Nav title filter: silently caps at ~70-80 values per filter (Sales Nav's own limit, not URL length)

The script's diagnostic warns at 8 kB URL length and at 70 titles. If you exceed either, split into two saved searches.
