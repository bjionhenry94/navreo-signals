# Country Tiers Preset — Hard-Block + Tiered Min-Employees

Reusable country lists for **Recipe 1** in `SKILL.md`. Use these when the user wants tiered `min_employees` rules by country economic tier (e.g. "block India/Pakistan-type, min 100 in low-GDP, min 10 in high-GDP").

The lists below were calibrated for the Navreo Boomerang re-qualification run (Apr 2026, 369k rows). They lean on the GDP-per-capita / median-salary divide rather than strict OECD membership — the goal is to match the *quality of buyer* in each market, not the political grouping.

---

## Tier 0 — HARD BLOCK (drop entirely)

Reason: outsourcing-dominant labour markets where outbound to "Director / VP" titles maps to lower buying power and higher spam-trap density than the title implies.

| Country | ISO-2 |
|---|---|
| India | IN |
| Pakistan | PK |
| Bangladesh | BD |
| Sri Lanka | LK |
| Nepal | NP |

**Adjust per run.** If the user's pitch is specifically aimed at outsourcing buyers (e.g. selling to dev shops in India), drop this tier from the block list.

---

## Tier 1 — LOW-GDP / LOW-SALARY (`min_employees: 100`)

Reason: senior titles are real, but at smaller company sizes the buyer rarely has the budget for a Western outbound-services / SaaS pitch. Lifting the size floor to 100 selects for established mid-market buyers.

### LATAM
| Country | ISO-2 |
|---|---|
| Mexico | MX |
| Brazil | BR |
| Argentina | AR |
| Colombia | CO |
| Chile | CL |
| Peru | PE |
| Venezuela | VE |
| Ecuador | EC |
| Bolivia | BO |
| Uruguay | UY |
| Paraguay | PY |
| Costa Rica | CR |
| Panama | PA |
| Dominican Republic | DO |
| Guatemala | GT |
| Honduras | HN |
| El Salvador | SV |
| Nicaragua | NI |
| Cuba | CU |
| Puerto Rico | PR |

### Africa
| Country | ISO-2 |
|---|---|
| Nigeria | NG |
| Kenya | KE |
| Ghana | GH |
| Egypt | EG |
| South Africa | ZA |
| Morocco | MA |
| Tunisia | TN |
| Algeria | DZ |
| Ethiopia | ET |
| Tanzania | TZ |
| Uganda | UG |
| Zimbabwe | ZW |
| Zambia | ZM |
| Senegal | SN |
| Cameroon | CM |
| Côte d'Ivoire / Ivory Coast | CI |
| Angola | AO |
| Mozambique | MZ |
| Rwanda | RW |
| Botswana | BW |
| Namibia | NA |
| Mali | ML |
| Sudan | SD |
| Libya | LY |

### SE Asia (non-blocked)
| Country | ISO-2 |
|---|---|
| Vietnam | VN |
| Indonesia | ID |
| Thailand | TH |
| Philippines | PH |
| Cambodia | KH |
| Laos | LA |
| Myanmar | MM |
| Mongolia | MN |

### Eastern Europe / CIS
| Country | ISO-2 |
|---|---|
| Romania | RO |
| Bulgaria | BG |
| Ukraine | UA |
| Serbia | RS |
| Russia | RU |
| Belarus | BY |
| Moldova | MD |
| North Macedonia / Macedonia | MK |
| Albania | AL |
| Bosnia and Herzegovina / Bosnia | BA |
| Montenegro | ME |
| Kosovo | XK |
| Georgia | GE |
| Armenia | AM |
| Azerbaijan | AZ |
| Kazakhstan | KZ |
| Uzbekistan | UZ |
| Kyrgyzstan | KG |
| Tajikistan | TJ |
| Turkmenistan | TM |
| Turkey | TR |

### Middle East (lower-tier)
| Country | ISO-2 |
|---|---|
| Iran | IR |
| Iraq | IQ |
| Lebanon | LB |
| Jordan | JO |
| Syria | SY |
| Yemen | YE |
| Palestine | PS |

---

## Tier 2 — HIGH-GDP / HIGH-SALARY (`min_employees: 10`)

| Country | ISO-2 |
|---|---|
| United States / USA / US | US |
| Canada | CA |
| United Kingdom / UK | GB |
| Ireland | IE |
| Germany | DE |
| France | FR |
| Netherlands | NL |
| Belgium | BE |
| Switzerland | CH |
| Austria | AT |
| Luxembourg | LU |
| Italy | IT |
| Spain | ES |
| Portugal | PT |
| Sweden | SE |
| Norway | NO |
| Denmark | DK |
| Finland | FI |
| Iceland | IS |
| Australia | AU |
| New Zealand | NZ |
| Japan | JP |
| South Korea / Republic of Korea / Korea | KR |
| Singapore | SG |
| Hong Kong | HK |
| Taiwan | TW |
| Israel | IL |
| United Arab Emirates / UAE | AE |
| Saudi Arabia | SA |
| Qatar | QA |

---

## Default for Unknown / Missing Locations

**Treat as Tier 2 (high-GDP, min 10).** The role + avoid filters still gate the row, so being permissive at the location step recovers leads rather than losing them. The user can review the qualified `Size Tier: high_gdp` rows where they look out-of-place.

---

## Boomerang Location Format Quirks

The `Linkedin Company Location` column from Boomerang exports has **two patterns** worth knowing:

1. **Trailing ISO-2 code, no full country name**: e.g. `San Francisco, California, US` — final segment is `US`, not `United States`.
2. **"Primary" tag prefix**: some rows include a literal `Primary` segment as the last token: `San Francisco, California, US, Primary` → strip "Primary" before parsing.

When parsing the country, take the **last non-"Primary" non-empty comma-separated segment**, lowercase it, and match against **both** the full-name set **and** the ISO-2 code set. The first preprocess in the Boomerang re-qual leaked 12,897 India rows into high-GDP because it only matched on full names.

```python
def parse_country(loc: str) -> str:
    if not loc:
        return ""
    parts = [p.strip() for p in loc.split(",") if p.strip() and p.strip().lower() != "primary"]
    return parts[-1] if parts else ""

def country_tier(country: str, hard_block: set, low_gdp: set, high_gdp: set) -> str:
    c = country.strip().lower()
    if not c:
        return "high_gdp"  # permissive default
    if c in hard_block:
        return "blocked"
    if c in low_gdp:
        return "low_gdp"
    if c in high_gdp:
        return "high_gdp"
    return "high_gdp"  # unknown → permissive
```

Build `hard_block`, `low_gdp`, `high_gdp` as lowercase sets containing **both** full names **and** ISO-2 codes from the tables above. Sanity-check counts: if hard-block hits look low after running the preprocess, the ISO-2 codes likely aren't in the set yet.

---

## When to Deviate

- **Pitch aimed at low-cost buyers** (outsourcing partnerships, white-label tools sold to dev shops): drop the hard-block tier or move the LATAM/SEA tiers down to high-GDP rules.
- **Geo-specific campaign** (e.g. all-Australia, all-DACH): switch to a single bucket with `location_criteria.mode: "allowlist"` and skip the tiered preprocess entirely.
- **Premium-only pitch** (six-figure ACV): raise the high-GDP `min_employees` to 50+ and drop the low-GDP tier entirely.
