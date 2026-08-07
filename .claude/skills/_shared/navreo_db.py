"""Shared Supabase helper for Navreo skills and scripts.

Design rules:
- stdlib + requests only, no ORM.
- Reads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY from ~/.navreo-keys.env directly
  (does not require the shell to have sourced it).
- FAILS SOFT: every read returns None (or []) on any network/auth error so callers
  fall through to the local ~/.navreo-cache mirror or a fresh provider call.
  A Supabase outage must never break a campaign build.
- put_enrichment() dual-writes the local ~/.navreo-cache mirror file.
"""

import json
import os
import re
import datetime
from pathlib import Path

import requests

KEYS_FILE = Path.home() / ".navreo-keys.env"
LOCAL_CACHE = Path.home() / ".navreo-cache"
TIMEOUT = 20

_env_cache = None


def _env(name, default=None):
    """Read a key from ~/.navreo-keys.env (export K=V or K=V lines), else os.environ."""
    global _env_cache
    if _env_cache is None:
        _env_cache = {}
        try:
            for line in KEYS_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                line = line.removeprefix("export ").strip()
                if "=" in line:
                    k, _, v = line.partition("=")
                    _env_cache[k.strip()] = v.strip().strip('"').strip("'")
        except OSError:
            pass
    return _env_cache.get(name) or os.environ.get(name, default)


def _base():
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None, None
    return url.rstrip("/"), key


def _headers(key, prefer=None):
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _request(method, path, prefer=None, params=None, payload=None):
    """Single REST call. Returns parsed JSON (or True for empty 2xx), None on failure."""
    url, key = _base()
    if not url:
        return None
    try:
        r = requests.request(
            method, f"{url}{path}",
            headers=_headers(key, prefer),
            params=params,
            data=json.dumps(payload) if payload is not None else None,
            timeout=TIMEOUT,
        )
        if r.status_code >= 300:
            return None
        return r.json() if r.text else True
    except (requests.RequestException, ValueError):
        return None


def canonical_domain(raw):
    """Mirror of the SQL canonical_domain() — keep in sync with db/schema.sql."""
    if not raw:
        return None
    d = raw.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = re.sub(r"/.*$", "", d)
    return d or None


# ---------------------------------------------------------------------------
# Enrichment cache
# ---------------------------------------------------------------------------

def get_enrichment(entity_type, key, provider=None, max_age_days=30):
    """Freshest cached payload for an entity, or None (miss / stale / Supabase down)."""
    if entity_type == "company":
        key = canonical_domain(key)
    if not key:
        return None
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=max_age_days)).isoformat()
    params = {
        "entity_type": f"eq.{entity_type}",
        "entity_key": f"eq.{key}",
        "fetched_at": f"gte.{cutoff}",
        "order": "fetched_at.desc",
        "limit": "1",
        "select": "payload,provider,endpoint,fetched_at,source_skill",
    }
    if provider:
        params["provider"] = f"eq.{provider}"
    rows = _request("GET", "/rest/v1/enrichments", params=params)
    return rows[0] if rows else None


def put_enrichment(entity_type, key, provider, payload,
                   endpoint=None, source_skill=None, fetched_at=None):
    """Store a raw provider payload; also dual-write the local ~/.navreo-cache mirror.

    Returns True if the Supabase write succeeded (local mirror is best-effort either way).
    """
    if entity_type == "company":
        key = canonical_domain(key)
    if not key:
        return False
    fetched_at = fetched_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Local mirror (same envelope the skills already read)
    sub = "companies" if entity_type == "company" else "people"
    try:
        mirror = LOCAL_CACHE / provider / sub
        mirror.mkdir(parents=True, exist_ok=True)
        (mirror / f"{key}.json").write_text(json.dumps({
            "fetched_at": fetched_at,
            "endpoint": endpoint,
            "source_skill": source_skill,
            "data": payload,
        }, indent=2))
    except OSError:
        pass

    ok = _request("POST", "/rest/v1/enrichments",
                  prefer="resolution=ignore-duplicates",
                  params={"on_conflict": "entity_type,entity_key,provider,endpoint,fetched_at"},
                  payload={
                      "entity_type": entity_type,
                      "entity_key": key,
                      "provider": provider,
                      "endpoint": endpoint or "",
                      "source_skill": source_skill,
                      "fetched_at": fetched_at,
                      "payload": payload,
                  })
    return ok is not None


# ---------------------------------------------------------------------------
# Entity upserts
# ---------------------------------------------------------------------------

def upsert_company(domain, **fields):
    domain = canonical_domain(domain)
    if not domain:
        return False
    row = {"domain": domain,
           "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    row.update({k: v for k, v in fields.items() if v is not None})
    ok = _request("POST", "/rest/v1/companies",
                  prefer="resolution=merge-duplicates",
                  params={"on_conflict": "domain"}, payload=row)
    return ok is not None


# Providers whose emails arrive already deliverability-verified, so writing one
# IS a verification event. AI-Ark verifies every email through BounceBan at
# source (real-time), so an AI-Ark-sourced email is deliverable the moment it
# lands — no MillionVerifier/ListMint re-check, and the signals verify pipeline
# (which reads people.email_verification, 60-day TTL) skips it for free.
_PREVERIFIED_PROVIDERS = {"ai_ark", "aiark", "ai-ark", "bounceban"}


def upsert_person(email=None, linkedin_slug=None, provider=None, **fields):
    if not email and not linkedin_slug:
        return False
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = {"updated_at": now}
    if email:
        row["email"] = email.strip().lower()
    if linkedin_slug:
        row["linkedin_slug"] = linkedin_slug.strip().lower()
    if fields.get("company_domain"):
        fields["company_domain"] = canonical_domain(fields["company_domain"])
        # FK safety: make sure the company row exists before referencing it
        upsert_company(fields["company_domain"])
    # AI-Ark (BounceBan) emails are pre-verified at source — stamp the verify
    # date as the pull date so we never re-spend a credit checking them. An
    # explicit email_verification in `fields` (e.g. a real MV/ListMint verdict)
    # always wins over this auto-stamp.
    if (email and provider and str(provider).lower() in _PREVERIFIED_PROVIDERS
            and not fields.get("email_verification")):
        fields.setdefault("email_verification", "good")
        fields.setdefault("email_verified_at", now)
    row.update({k: v for k, v in fields.items() if v is not None})
    conflict = "email" if email else "linkedin_slug"
    ok = _request("POST", "/rest/v1/people",
                  prefer="resolution=merge-duplicates",
                  params={"on_conflict": conflict}, payload=row)
    return ok is not None


# ---------------------------------------------------------------------------
# Exclusions & logging
# ---------------------------------------------------------------------------

def check_exclusions(client_id, emails=None, domains=None):
    """Returns list of {matched_email, matched_domain, reason}.

    Returns None when Supabase is unreachable — callers must treat None as
    'exclusion check unavailable', NOT as 'no exclusions'.
    """
    emails = [e.strip().lower() for e in (emails or []) if e]
    domains = [canonical_domain(d) for d in (domains or [])]
    domains = [d for d in domains if d]
    return _request("POST", "/rest/v1/rpc/check_exclusions", payload={
        "p_client": client_id,
        "p_emails": emails,
        "p_domains": domains,
    })


def log_contact(client_id, email, company_domain=None, workspace=None,
                smartlead_campaign_id=None, smartlead_lead_id=None,
                status=None, lead_category=None, icebreaker=None,
                icebreaker_angle=None, custom_fields=None,
                first_contacted_at=None, source="skill"):
    row = {
        "client_id": client_id,
        "email": email.strip().lower(),
        "company_domain": canonical_domain(company_domain) if company_domain else None,
        "workspace": workspace,
        "smartlead_campaign_id": smartlead_campaign_id,
        "smartlead_lead_id": smartlead_lead_id,
        "status": status,
        "lead_category": lead_category,
        "icebreaker": icebreaker,
        "icebreaker_angle": icebreaker_angle,
        "custom_fields": custom_fields,
        "first_contacted_at": first_contacted_at,
        "last_event_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": source,
    }
    row = {k: v for k, v in row.items() if v is not None}
    ok = _request("POST", "/rest/v1/contact_history",
                  prefer="resolution=merge-duplicates",
                  params={"on_conflict": "client_id,workspace,smartlead_campaign_id,email"},
                  payload=row)
    return ok is not None


def log_signal(signal_type, source, detected_at, company_domain=None,
               person_id=None, detail=None):
    row = {
        "signal_type": signal_type,
        "source": source,
        "detected_at": detected_at,
        "company_domain": canonical_domain(company_domain) if company_domain else None,
        "person_id": person_id,
        "detail": detail,
    }
    row = {k: v for k, v in row.items() if v is not None}
    ok = _request("POST", "/rest/v1/signals",
                  prefer="resolution=ignore-duplicates", payload=row)
    return ok is not None


def log_provider_usage(provider, credits, endpoint=None, source_id=None):
    """Ledger one paid provider call in provider_usage. Call after EVERY spend.

    provider: 'prospeo' | 'ai_ark' | 'ocean' | 'theirstack' | 'millionverifier' |
    'listmint' | 'leadmagic'. credits: what the call cost (int; round up fractions).
    source_id: run/skill identifier so spend is attributable, e.g. 'lilly-decision-maker-finder-v2'.
    """
    row = {
        "provider": provider,
        "credits": int(credits),
        "endpoint": endpoint,
        "source_id": source_id,
        "called_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    row = {k: v for k, v in row.items() if v is not None}
    ok = _request("POST", "/rest/v1/provider_usage", payload=row)
    return ok is not None


# ---------------------------------------------------------------------------
# Generic REST access for scripts (backfill, sync)
# ---------------------------------------------------------------------------

def rest(method, path, prefer=None, params=None, payload=None):
    """Raw PostgREST call for scripts that need tables not wrapped above."""
    return _request(method, path, prefer=prefer, params=params, payload=payload)


if __name__ == "__main__":
    url, _ = _base()
    if not url:
        print("NOT CONFIGURED: add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to ~/.navreo-keys.env")
    else:
        ping = _request("GET", "/rest/v1/clients", params={"select": "id", "limit": "1"})
        print(f"Supabase URL: {url}")
        print(f"Connectivity: {'OK' if ping is not None else 'FAILED (check key / schema applied?)'}")
