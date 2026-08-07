# lilly-strategy engine — run.json contract

The engine (`engine.py`) is the deterministic back end of /lilly-strategy. The session
writes the CREATIVE fields; the engine owns every NUMBER and every splice into the wizard.
Division of labour, per idea:

| Who | Fields |
|---|---|
| **Session (LLM)** | id, name, who, offer, caption, tag/shortTag, firstName/company (illustrative example person), pain, moment, videoAngle, why, repliesLine, freeNote, copyProvenance, peerProofLine, people[] example prospects, colleagues, footer |
| **Engine** | probe (gross via `probe`), netting (via `net`), validate, hydrate, handoff |

Numbers are NEVER hand-written: `net`/`gross`/`freeFromRecords`/`newPeople` must come from
`probe` + `net` outputs (probe date + provider recorded on the idea). `validate` enforces this.

## run.json shape

```json
{
  "client": "navreo",
  "date": "2026-07-19",
  "run_id": "navreo-20260719-k3f9",
  "footer": "Ideas for Navreo · updated 19 July 2026 · every number probe-confirmed and suppression-netted · example people are illustrative · nothing here sends email without you.",
  "colleagues": { "apollo": "Sam", "exporters": "Owen" },
  "carry": [ { "idea": "cleaning", "state": { "phase": 7, "launched": true, "uploadState": "uploaded", "stagesDone": 5 } } ],
  "validation_card": { "id": "validate-x", "eyebrow": "Client question", "title": "…", "verdictShort": "…", "verdictLine": "…", "microline": "…", "found": 416, "afterCooldown": 390, "freeFromRecords": 280, "askPrompt": "…" },
  "ideas": [
    {
      "id": "exporters", "campaignNo": "TBC", "name": "Exporters scale-up",
      "vector": "targeted_list",
      "net": 1920, "gross": 2749, "emails": 690,
      "netUnit": "people we can reach",
      "freeFromRecords": 190, "newPeople": 1730,
      "who": "…", "offer": "…", "caption": "3-4 words · at rest",
      "tag": "Recommended", "shortTag": "Recommended",
      "firstName": "Priya", "company": "Meridian Export Co",
      "pain": "…", "moment": "…", "videoAngle": "…",
      "why": "Why: …", "repliesLine": "…",
      "freeNote": "…", "copyProvenance": "…",
      "subject": "the stack vs the hours",
      "email": "Hi {first},\n\n{icebreaker}\n\n… only pay when a meeting lands.\n\n%signature%",
      "sequence": [
        { "name": "First email", "versions": [
          { "subject": "the stack vs the hours", "email": "Hi {first},\n\n{icebreaker}\n\n…\n\n%signature%" },
          { "subject": "you bought the tools, who's driving?", "email": "Hi {first},\n\n{icebreaker}\n\n…\n\n%signature%" }
        ] },
        { "name": "Follow-up", "versions": [
          { "subject": "", "email": "Hi {first},\n\nFloating this back up …\n\n%signature%" }
        ] }
      ],
      "icebreaker": {
        "kind": "dynamic",
        "angles": [
          { "name": "They're hiring a producer", "recommended": true,
            "note": "They're hiring commercial sales, so they want to grow the book.",
            "triggerLabel": "Fires on hiring",
            "triggers": ["Commercial Lines Producer", "Insurance Producer", "Sales Producer"],
            "example": "I noticed {company} is hiring a commercial lines producer, and thought I'd reach out." },
          { "name": "They recently joined",
            "note": "Prospect joined in the last 60 days, fresh in seat.",
            "example": "Saw you recently joined {company}, and thought you may be the best person to speak to about this." }
        ],
        "fallback": "Apologies if this isn't relevant, wasn't sure who the best person at {company} was."
      },
      "checks": { "schema": true, "grammar": true },
      "probe": { "provider": "prospeo_person", "date": "2026-07-19", "credits": 1, "gross": 2749 },
      "netting": { "ratio": 0.7, "method": "engine net, 10-domain sample", "date": "2026-07-19" },
      "pull_spec": {
        "provider": "prospeo_person",
        "filters": {
          "company_keywords": { "include": ["exporter", "export"], "include_company_description": true },
          "company_headcount_range": ["11-20", "21-50", "51-100", "101-200"],
          "company_location_search": { "include": ["United States", "United Kingdom", "Canada", "Australia"] },
          "person_job_title": { "include": ["…"], "include_partial_match": true },
          "person_seniority": { "include": ["Founder/Owner", "C-Suite", "Vice President", "Head", "Director"] }
        },
        "notes": "exclude legal/IT/freight bleed at build"
      }
    }
  ],
  "people": {
    "exporters": [
      { "first": "Priya", "title": "Founder", "company": "Meridian Export Co",
        "detail": true, "colleague": true,
        "lines": { "detail": "…", "colleague": "…", "safe": "…" } }
    ]
  }
}
```

- `run_id` (session-scoped boards, 2026-08-02): minted ONCE per chat session
  (`<client>-<YYYYMMDD>-<4 rand>`, `^[a-z0-9][a-z0-9-]{2,58}[a-z0-9]$`) and carried on every
  POST — the server stores each session's run under its own key so boards never clobber each
  other. Board URL: `strategy.html#/r/<run_id>`. Client permalink: `POST /api/strategy/share
  {run_id}` → logged-out copy-edit-only view (fields: pain/moment/videoAngle/offer/email/caption
  via `POST /api/strategy/copy-edit`). A publish WITHOUT run_id hits the legacy shared board and
  returns a warning — treat as a bug.
- `vector` ∈ targeted_list · hiring_signal · engagement_signal · events · followers ·
  lookalike · news_intent · prospeo_signal · recontact. **Mixture rule:** a board of ≥5
  ideas must span ≥3 vectors (validate fails otherwise) — the menu is never one campaign type.
- `pull_spec.provider` ∈ prospeo_person · prospeo_company · theirstack · aiark_people ·
  aiark_company · manual · trigify · porkbun_export. The SAME spec drives the probe and,
  post-approval, the /lilly-tam build (`handoff` renders it) — probe-confirmed shape = build shape.
- `targeting` (per idea, page-visible — NOT stripped) drives the "Campaign at a glance"
  showcase for EVERY use-case, data-first:
  - `groups`: `[{label, chips[], muted?}]` — the malleable "what we target" clusters. Each
    group supplies its OWN label (a niche list "Companies we target", a signal "What we watch
    for", a followers idea "Pages whose followers we email", a lookalike "Companies like these"
    + "Case studies we pull"). A group that omits `label` falls back to the per-kind default.
    A chip carrying a " — " tail renders the tail as a muted sub-label.
  - `kind`: optional vector string — ONLY a key into the default-label map + the plain-English
    campaign-TYPE eyebrow ("Buying signal", "Niche list", …). Absent/unknown kind = no eyebrow.
  - `roles` (decision-makers we email, the editable chips), `meta` (scope — array of `[k,v]`
    pairs OR a single pre-joined string), `label`, `excluded`, `note` as before.
  - Back-compat: legacy runs with `idea.anchors`/`idea.cases` (no `groups`) are shimmed into
    groups automatically; NEVER hard-code a section label to one idea's framing.
  - `signal`: for signal kinds, the SPECIFIC signal name shown on the sidebar LIVE pill
    (e.g. "Runs a sales stack"), falling back to the generic type name.
- **Copy IS in run.json now** (the live board reads it directly; the old `variantsFor` in-page
  derivation is retired). Per idea:
  - `subject` + `email` = the PRIMARY email (mirrors `sequence[0].versions[0]`; Preview resolves
    these). `subject` falls back to `caption` if absent (so a real subject never clobbers the
    sidebar sub-title).
  - `sequence`: `[{name, versions:[{subject, email}]}]` — the email steps (First email, Follow-up,
    …), each with its A/B/C copy variations shown as tabs on the Copy page. Both GTME and the
    share-client see every variation. Client edits go through `seq:<step>:<ver>` copy-edit fields.
  - Emails follow the Navreo voice (lilly-copywriter canonical), use merge tokens
    `{first}`/`{company}`/`{icebreaker}`/`{colleague}` and `%signature%`, and carry no em-dashes.
- `icebreaker` (per idea, drives the Icebreaker page — see SKILL Phase 2b): `{kind:"fixed"|
  "dynamic", angles:[{name, note, example, recommended?, triggers?[], triggerLabel?}], fallback}`.
  Hiring/tool angles MUST list `triggers` (exact roles/tools). The Preview `{icebreaker}` resolves
  to the recommended/first angle. GTME reorders angles on the board (arrows) or via chat.
- `checks` (per idea, stamped at BUILD by the upload gate, not at ideation): evidence flags the
  Launch checklist reads — `{schema, normalisation, variable_fill, spintax, recontact,
  email_verification, list_audit, grammar}`. Signature + grammar show auto-done regardless.
- `signature` (RUN level): `{name, role, company, domain}` — resolves `%signature%` to the house
  4-line format (name / role / company / "Visit our website at <domain>"), with `domain` stored in
  the DEFUSED form (`navreo(.)ai`, dot in brackets — never a clickable link). If unknown, ASK.
  Navreo default: Bjion / Founder / Navreo / navreo(.)ai.
- `people[id]` = the sign-off test-drive cast: 4-5 illustrative prospects, `lines.safe`
  mandatory, `detail`/`colleague` only where those opener types apply; may carry `website`/
  `linkedin` (their real links show in the Preview card).
- Engine-only fields (`vector`, `probe`, `netting`, `pull_spec`) are stripped by the SERVER before
  the page sees them; everything else (targeting, sequence, icebreaker, checks, signature, people)
  reaches the board.
- **LIVE board = `~/navreo-signals/app/strategy.html`, edited DIRECTLY** (it has DIVERGED from
  `wizard-template.html`; NEVER `build_live`/`hydrate` it from the template — that reverts live
  UI). `engine.py hydrate` renders the OLD template design and is drifting; it's only for an
  in-chat snapshot, not the source of truth. See memory `strategy-html-diverged-from-template`.

## Command crib

```bash
E=~/.claude/skills/lilly-strategy/engine/engine.py
python3 $E retro --client navreo --out-json retro.json     # free
python3 $E probe --run run.json --idea exporters           # 1 cr (prospeo) / free (theirstack)
python3 $E net --client navreo --domains a.com,b.com       # free — 30-day cooldown router
python3 $E validate --run run.json                         # free — schema + house rules
python3 $E hydrate --run run.json --out wizard-navreo.html # → publish to standing artifact
python3 $E handoff --run run.json --idea exporters         # → /lilly-tam brief
```

Costs: retro/net/validate/hydrate/handoff free · prospeo probe 1 cr/idea (hard ceiling at
strategy time) · theirstack preview free · aiark count ~1 cr. Probes cache their sample
rows into Supabase (navreo_db) and write the provider-usage ledger automatically.
