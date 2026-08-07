# Playbook Profiles

The QA runs against a playbook. Pick one of: Generic, Navreo, or Custom.

## Generic profile (default)

Universal best practices. Use when no client-specific rules apply.

```json
{
  "name": "Generic",
  "min_step_delay_days": 3,
  "step1_first_touch_delay_days": 0,
  "require_plain_text": false,
  "min_variants_step1": 1,
  "ps_format": "P.S.",
  "apostrophe_style": "straight",
  "subject_diversity_required": false,
  "internal_domains": []
}
```

## Navreo profile

Tuned for Navreo's outbound playbook. Adds:

```json
{
  "name": "Navreo",
  "min_step_delay_days": 3,
  "step1_first_touch_delay_days": 0,
  "require_plain_text": true,
  "min_variants_step1": 2,
  "ps_format": "P.S.",
  "apostrophe_style": "straight",
  "subject_diversity_required": true,
  "subject_lowercase_warn": true,
  "force_plain_text_required": true,
  "spintax_distribution_mode": "Randomized",
  "sending_pattern": "50/50",
  "tracking_open": false,
  "tracking_click": false,
  "internal_domains": ["navreo.com", "asteri.com"]
}
```

Navreo-specific extra checks:
- Flag P.S. format anything other than `P.S.` (no dash, no semicolon)
- Flag any subject not using personalisation
- Flag delay configuration that doesn't follow 3+ day rule
- Recommend straight apostrophes for plain-text rendering safety

## Custom profile

User pastes their own playbook config. The skill should accept any subset of the fields above. If a field isn't specified, fall back to Generic defaults.

## How to use

When the QA report cites a rule (e.g. "Step 1 first-touch delay = 1 day, convention is 0"), the value of "convention" comes from the active playbook. Always cite which playbook the QA was run against in the report header.
