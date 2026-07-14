"""Pure-python test suite for app/setter.py. NO network - Supabase and OpenAI/
Smartlead/Calendly HTTP are replaced with in-memory fakes via setter.configure()
(and, for a couple of pipeline tests, direct monkeypatch of setter's own module
globals). Run: python3 test_setter.py. Prints PASS/FAIL per case, exits 1 on
any failure (or any XFAIL case that unexpectedly passes).

Covers (per the build spec's Tests section):
  - decision matrix (decide()) - every listed veto plus the happy path,
    including the autopilot master switch, the category-disagreement guard,
    and the answered_since_reply veto
  - a fixtures-driven pass over setter_fixtures.json's decision-relevant cases
  - slot picker (pick_slots): hours/weekday filtering, day-spread, deep links
  - timezone mapper (guess_timezone): US city/state, GB, .com.br TLD, unknown,
    and the phone -> country-code path via the real _extract_phone() wiring
  - draft lint (lint_draft): em dash, {{ placeholder, missing resource link,
    invented number, missing subject, wrong first name
  - lexicon veto (lexicon_hits) including quoted-history stripping and the
    pattern vetoes (removal request, do-not-contact, delete-me)
  - idempotent intake (dupe message_id is skipped, not reprocessed) and the
    claim-race path (another claimant winning the insert never triggers a
    second classify())
  - test-inject never calls Smartlead's real send endpoint
  - poll batching cap (run_poll processes at most 15 replies per tick) and the
    campaign_assigned_at filter (backlog before assignment is never swept up)
  - unknown timezone still builds tentative slots; decide() still vetoes
    auto-send purely on timezone=None
  - handle_inbound(): Smartlead EMAIL_REPLY webhook -> pipeline field mapping,
    and every ignore case (non-reply event, missing message id, missing
    campaign/email, unassigned campaign)
  - ensure_webhooks(): additive registration, existing webhooks left intact,
    dry-run skip, and the second-call no-op
  - route_queue_action's double-send guard (409 on an already-sent row)

Bugs suspected in setter.py are marked XFAIL with a comment explaining what
happens vs. what the spec requires, and are also listed in the lane's
`concerns` output - do not fix setter.py from this file (lane C does not own
setter.py). None are currently open; the phone-wiring and lexicon-pattern
bugs this suite used to XFAIL are both fixed in setter.py and are now plain
passing checks.
"""

import copy
import datetime as dt
import json
import os
import re
import sys
import threading
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402
import setter_backfill  # noqa: E402 - one-time backfill script; see its own module docstring


FIXTURES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setter_fixtures.json")

RESULTS = []  # (name, passed: bool, detail: str, xfail: bool)


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail, False))


def check_xfail(name, condition, detail=""):
    """Use for assertions that currently FAIL because of a suspected setter.py
    bug. `condition` is the assertion that SHOULD hold per the spec. If it
    ever starts passing (bug fixed), this test will flag it so the XFAIL can
    be removed."""
    RESULTS.append((name, bool(condition), detail, True))


def run_report():
    failed = 0
    unexpected_pass = 0
    for name, passed, detail, xfail in RESULTS:
        if xfail:
            if passed:
                print(f"XPASS (bug seems fixed, remove xfail): {name}  {detail}")
                unexpected_pass += 1
            else:
                print(f"XFAIL (known setter.py bug):           {name}  {detail}")
        else:
            status = "PASS" if passed else "FAIL"
            print(f"{status}: {name}" + (f"  {detail}" if (detail and not passed) else ""))
            if not passed:
                failed += 1
    total = len(RESULTS)
    xfail_n = sum(1 for *_r, x in RESULTS if x)
    print(f"\n{total - xfail_n - failed}/{total - xfail_n} pass (+{xfail_n} known-bug xfail, "
          f"{unexpected_pass} unexpectedly now passing)")
    return failed  # unexpected_pass is informational only, not a hard failure


# ── fakes ─────────────────────────────────────────────────────────────────

class FakeSB:
    """Very small in-memory stand-in for the sb(method, path, body, prefer)
    PostgREST helper, covering only the query shapes setter.py issues."""

    def __init__(self):
        self.agents = {}       # id -> {"id":..., "doc": {...}}
        self.queue = []        # list of row dicts
        self.companies = {}    # domain -> {city, state, country}
        self.replies = []      # list of raw reply rows for run_poll() / training generation
        self.sent_messages = []  # list of raw sent_messages rows for training's outreach/human-answer join
        self.provider_usage = []  # list of posted provider_usage rows (setter_synthetic ledger)
        # When set, a POST to provider_usage raises instead of recording -
        # simulates a Supabase write failure so tests can prove a failed
        # usage log never fails generation itself.
        self.provider_usage_post_error = None
        self._next_id = 1
        self.calls = []

    # -- helpers --
    @staticmethod
    def _split(path):
        if "?" in path:
            table, qs = path.split("?", 1)
        else:
            table, qs = path, ""
        params = {}
        for part in qs.split("&"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
            else:
                k, v = part, ""
            params[k] = unquote(v)
        return table, params

    @staticmethod
    def _match_eq(value, op_value):
        if op_value.startswith("eq."):
            return str(value) == op_value[3:]
        if op_value.startswith("neq."):
            return str(value) != op_value[4:]
        if op_value.startswith("not.in."):
            inner = op_value[7:].strip("()")
            opts = [o for o in inner.split(",") if o != ""]
            return str(value) not in opts
        if op_value.startswith("in."):
            inner = op_value[3:].strip("()")
            opts = [o for o in inner.split(",") if o != ""]
            return str(value) in opts
        if op_value.startswith("gt."):
            return str(value) > op_value[3:]
        if op_value.startswith("gte."):
            return True  # date comparisons not modelled; tests use recent timestamps
        return True

    def __call__(self, method, path, body=None, prefer=""):
        self.calls.append((method, path, body, prefer))
        table, params = self._split(path)

        if table == setter.AGENTS_TABLE:
            return self._agents_table(method, params, body)
        if table == setter.QUEUE_TABLE:
            return self._queue_table(method, params, body, prefer)
        if table == "companies":
            return self._companies_table(params)
        if table == "replies":
            return self._replies_table(params)
        if table == "sent_messages":
            return self._sent_messages_table(params)
        if table == "provider_usage":
            return self._provider_usage_table(method, body)
        return []

    def _provider_usage_table(self, method, body):
        if method == "POST":
            if self.provider_usage_post_error is not None:
                raise self.provider_usage_post_error
            self.provider_usage.append(dict(body or {}))
            return []
        return list(self.provider_usage)

    def _agents_table(self, method, params, body):
        if method == "GET":
            rows = list(self.agents.values())
            if "id" in params:
                rows = [r for r in rows if self._match_eq(r["id"], params["id"])]
            return [{"id": r["id"], "doc": r["doc"]} for r in rows]
        if method == "POST":
            self.agents[body["id"]] = {"id": body["id"], "doc": body["doc"]}
            return []
        if method == "DELETE":
            val = params.get("id", "")
            if val.startswith("eq."):
                self.agents.pop(val[3:], None)
            return []
        return []

    def _queue_row_matches(self, row, params):
        for key in ("id", "workspace", "smartlead_campaign_id", "lead_email", "message_id", "status", "is_test"):
            if key in params and not self._match_eq(row.get(key), params[key]):
                return False
        return True

    def _queue_table(self, method, params, body, prefer):
        if method == "GET":
            rows = [r for r in self.queue if self._queue_row_matches(r, params)]
            limit = params.get("limit")
            if limit:
                try:
                    rows = rows[: int(limit)]
                except ValueError:
                    pass
            return copy.deepcopy(rows)
        if method == "POST":
            key = (body.get("workspace"), str(body.get("smartlead_campaign_id")),
                   body.get("lead_email"), body.get("message_id"))
            for r in self.queue:
                rkey = (r.get("workspace"), str(r.get("smartlead_campaign_id")),
                        r.get("lead_email"), r.get("message_id"))
                if rkey == key:
                    if "ignore-duplicates" in (prefer or ""):
                        return []
                    r.update(body)
                    return [copy.deepcopy(r)]
            row = dict(body)
            row["id"] = self._next_id
            self._next_id += 1
            self.queue.append(row)
            return [copy.deepcopy(row)]
        if method == "PATCH":
            val = params.get("id", "")
            target_id = None
            if val.startswith("eq."):
                try:
                    target_id = int(val[3:])
                except ValueError:
                    target_id = val[3:]
            for r in self.queue:
                if str(r.get("id")) == str(target_id):
                    r.update(body or {})
            return []
        return []

    def _companies_table(self, params):
        domain_op = params.get("domain", "")
        domain = domain_op[3:] if domain_op.startswith("eq.") else ""
        row = self.companies.get(domain)
        return [row] if row else []

    def _replies_table(self, params):
        rows = self.replies
        cid_op = params.get("smartlead_campaign_id", "")
        if cid_op.startswith("in."):
            allowed = set(cid_op[3:].strip("()").split(","))
            rows = [r for r in rows if str(r.get("smartlead_campaign_id")) in allowed]
        elif cid_op:
            rows = [r for r in rows if self._match_eq(r.get("smartlead_campaign_id"), cid_op)]
        if "workspace" in params:
            rows = [r for r in rows if self._match_eq(r.get("workspace"), params["workspace"])]
        if "category" in params:
            rows = [r for r in rows if self._match_eq(r.get("category"), params["category"])]
        if "id" in params:
            rows = [r for r in rows if self._match_eq(r.get("id"), params["id"])]
        order = params.get("order", "")
        if order.startswith("replied_at"):
            rows = sorted(rows, key=lambda r: r.get("replied_at") or "", reverse=order.endswith("desc"))
        limit = params.get("limit")
        if limit:
            try:
                rows = rows[: int(limit)]
            except ValueError:
                pass
        return copy.deepcopy(rows)

    def _sent_messages_table(self, params):
        rows = self.sent_messages
        for key in ("smartlead_campaign_id", "email", "email_seq_number"):
            if key in params:
                rows = [r for r in rows if self._match_eq(r.get(key), params[key])]
        if "is_manual_reply" in params:
            op = params["is_manual_reply"]
            want_bool = op[3:] == "true" if op.startswith("eq.") else True
            rows = [r for r in rows if bool(r.get("is_manual_reply")) == want_bool]
        if "sent_at" in params:
            rows = [r for r in rows if self._match_eq(r.get("sent_at"), params["sent_at"])]
        order = params.get("order", "")
        if order.startswith("sent_at"):
            rows = sorted(rows, key=lambda r: r.get("sent_at") or "", reverse=order.endswith("desc"))
        limit = params.get("limit")
        if limit:
            try:
                rows = rows[: int(limit)]
            except ValueError:
                pass
        return copy.deepcopy(rows)


class FakeHTTP:
    """Stand-in for http_json(method, url, headers, body). Routes by
    substring on the URL. classify_fn/draft_fn are callables(request_body)
    returning the dict payload the real OpenAI call would have parsed out."""

    def __init__(self):
        self.classify_fn = None
        self.draft_fn = None
        # merge_fn(body) -> {"instructions": "..."} for the
        # merge_correction_into_instructions() OpenAI call (schema
        # "setter_instructions_merge"). None -> the default empty-string
        # response, which always trips merge_correction_into_instructions's
        # own fallback-to-append path - tests that want a real merge set this.
        self.merge_fn = None
        # proofread_fn(body) -> {"html": "..."} for proofread_draft()'s
        # OpenAI call (schema "setter_proofread"). None -> defaults to
        # echoing back the SAME html the call was given (parsed straight out
        # of the request payload) so every pre-existing test's draft-content
        # assertions stay byte-identical without having to know this feature
        # exists.
        self.proofread_fn = None
        # invent_fn(body) -> {"scenarios": [...]} for
        # _invent_training_scenarios()'s OpenAI call (schema
        # "setter_training_scenarios"). None -> a default that returns one
        # generic scenario per entry in the requested scenario_plan, so
        # tests that don't care about content still get a full batch.
        self.invent_fn = None
        self.calendly_avail = []
        self.smartlead_calls = []
        self.calls = []
        # Message-history rows hydrate_lead() should see for any non-test reply
        # (a list of the same raw shape setter.py normalises: type/time/subject/
        # email_body/message_id/stats_id/from_name). Empty by default so tests
        # that don't care about hydration succeeding just get a clean "not found".
        self.message_history = []
        # Smartlead's per-campaign webhook list, keyed by str(campaign_id), for
        # ensure_webhooks() tests. GET returns the bare list; POST appends and
        # returns the created object with an id, mirroring Smartlead's API shape.
        self.webhooks_by_campaign = {}
        self._next_webhook_id = 1
        # Subsequence enrolment fixtures (real-Smartlead-write tests):
        # campaign_leads_by_campaign: str(campaign_id) -> list of
        #   {"campaign_lead_map_id": int, "status": str, "lead": {"id":, "email":}}
        #   mirroring GET /campaigns/{id}/leads's `data` shape.
        self.campaign_leads_by_campaign = {}
        # all_campaigns: list of {"id","name","status","parent_campaign_id"}
        # mirroring GET /campaigns/ (used to discover a parent's subsequences).
        self.all_campaigns = []
        # subsequence_push_result: None -> default success reply; a dict -> use
        # verbatim; a callable(body) -> dict -> computed per-call (e.g. to
        # simulate a Smartlead 500/failure).
        self.subsequence_push_result = None
        self.subsequence_push_calls = []

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url))
        if "api.openai.com" in url:
            schema = (((body or {}).get("response_format") or {}).get("json_schema") or {}).get("name")
            if schema == "setter_classification":
                data = self.classify_fn(body) if self.classify_fn else {}
                return {"choices": [{"message": {"content": json.dumps(data)}}]}
            if schema == "setter_draft":
                data = self.draft_fn(body) if self.draft_fn else {"subject": "Re: hi", "html": "<p>hi</p>"}
                return {"choices": [{"message": {"content": json.dumps(data)}}]}
            if schema == "setter_instructions_merge":
                data = self.merge_fn(body) if self.merge_fn else {"instructions": ""}
                return {"choices": [{"message": {"content": json.dumps(data)}}]}
            if schema == "setter_proofread":
                if self.proofread_fn:
                    data = self.proofread_fn(body)
                else:
                    original = json.loads(body["messages"][1]["content"]).get("html") or ""
                    data = {"html": original}
                return {"choices": [{"message": {"content": json.dumps(data)}}]}
            if schema == "setter_training_scenarios":
                if self.invent_fn:
                    data = self.invent_fn(body)
                else:
                    payload = json.loads(body["messages"][1]["content"])
                    plan = payload.get("scenario_plan") or []
                    data = {"scenarios": [
                        {"lead_first_name": "Pat", "lead_company": "Acme Co",
                         "subject": "Re: our email", "body": f"Synthetic {cat} reply body #{i}. Thanks."}
                        for i, cat in enumerate(plan)
                    ]}
                return {"choices": [{"message": {"content": json.dumps(data)}}]}
            return {"choices": [{"message": {"content": "{}"}}]}
        if "calendly.com" in url:
            if "users/me" in url:
                return {"resource": {"uri": "https://api.calendly.com/users/FAKE"}}
            # Checked BEFORE the plain "event_types" branch below: the
            # available-times call's own query string embeds the event_type
            # URI as a value (".../event_types/FAKE"), so it also contains the
            # substring "event_types" and would otherwise be shadowed.
            if "event_type_available_times" in url:
                return {"collection": [{"start_time": iso} for iso in self.calendly_avail]}
            if "event_types" in url:
                return {"collection": [{"uri": "https://api.calendly.com/event_types/FAKE",
                                        "slug": "book-a-call-with-us-clone-2"}]}
            return {}
        if "smartlead.ai" in url:
            self.smartlead_calls.append((method, url, body))
            if "reply-email-thread" in url:
                return {"ok": True}
            if "master-inbox/push-to-subsequence" in url:
                self.subsequence_push_calls.append(body)
                if callable(self.subsequence_push_result):
                    return self.subsequence_push_result(body)
                if self.subsequence_push_result is not None:
                    return self.subsequence_push_result
                return {"success": True, "message": "Lead pushed to subsequence",
                        "data": {"email_lead_map_id": (body or {}).get("email_lead_map_id"),
                                 "parent_campaign_id": None,
                                 "sub_sequence_id": (body or {}).get("sub_sequence_id"),
                                 "will_start_at": "2026-07-14T00:00:00Z",
                                 "stop_on_parent_reply": (body or {}).get("stop_lead_on_parent_campaign_reply")}}
            # message-history's own URL (".../leads/{id}/message-history") also
            # contains "/leads/", so it must be checked BEFORE the generic
            # leads-lookup branch or it always shadows it. Campaign-leads
            # listing (".../campaigns/{id}/leads?...") must also be checked
            # first - it has no trailing slash before "?" so it wouldn't
            # actually collide with the "/leads/" substring below, but keeping
            # it here documents the ordering dependency explicitly.
            if "message-history" in url:
                return {"history": self.message_history}
            m = re.search(r"/campaigns/([^/?]+)/leads(?:\?|$)", url)
            if m:
                cid = m.group(1)
                entries = self.campaign_leads_by_campaign.get(cid, [])
                qs = url.split("?", 1)[1] if "?" in url else ""
                q = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                offset = int(q.get("offset", "0") or 0)
                limit = int(q.get("limit", "100") or 100)
                page = entries[offset: offset + limit]
                return {"total_leads": str(len(entries)), "offset": offset, "limit": limit, "data": page}
            if re.search(r"/campaigns/\?", url):
                return list(self.all_campaigns)
            if "/leads/" in url:
                return {"id": 999, "first_name": "Test", "last_name": "Lead"}
            m = re.search(r"/campaigns/([^/]+)/webhooks", url)
            if m:
                cid = m.group(1)
                hooks = self.webhooks_by_campaign.setdefault(cid, [])
                if method == "GET":
                    return list(hooks)
                if method == "POST":
                    hook = dict(body or {})
                    hook["id"] = self._next_webhook_id
                    self._next_webhook_id += 1
                    hooks.append(hook)
                    return hook
            return {}
        return {}


class ClaimRaceSB:
    """Wraps a FakeSB to simulate two intake paths (the Smartlead webhook and
    the cron poll) racing on the same reply: process_reply's own dedupe check
    finds nothing (nobody has claimed the reply yet), but by the time its
    claim insert runs, another claimant has already won - exactly what the
    unique-key insert-with-ignore-duplicates is there to catch. The first
    matching claim POST loses on purpose (returns [] like Postgres would for a
    conflicting ignore-duplicates insert) and plants the "winner" row directly,
    so the caller's own _existing_row fallback finds it."""

    def __init__(self, inner):
        self.inner = inner
        self.winner_row = None
        self._claim_seen = False

    def __call__(self, method, path, body=None, prefer=""):
        table, _params = FakeSB._split(path)
        if (table == setter.QUEUE_TABLE and method == "POST" and not self._claim_seen
                and "ignore-duplicates" in (prefer or "")):
            self._claim_seen = True
            winner = dict(body or {})
            winner["id"] = self.inner._next_id
            self.inner._next_id += 1
            self.inner.queue.append(winner)
            self.winner_row = winner
            return []
        return self.inner(method, path, body, prefer)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def fresh_setter(fake_sb=None, fake_http=None):
    sb = fake_sb or FakeSB()
    http = fake_http or FakeHTTP()
    setter.configure(sb=sb, http_json=http, keys={"OPENAI_API_KEY": "x", "SMARTLEAD_API_KEY": "y"},
                     log_activity=lambda *a, **k: None)
    return sb, http


# ── 1. lexicon veto ─────────────────────────────────────────────────────────

def test_lexicon():
    check("lexicon: cease", "cease" in setter.lexicon_hits("Kindly cease"))
    check("lexicon: unsubscribe", "unsubscribe" in setter.lexicon_hits("Unsubscribe Sent from Outlook for Mac"))
    check("lexicon: spam as accusation",
         "spam" in setter.lexicon_hits("erguz.com.mx uses the spamrl.com spam block list and it suspected your message is spam."))
    check("lexicon: lawyer (substring of lawyers)",
         "lawyer" in setter.lexicon_hits("I will report this to our lawyers and the ICO."))
    check("lexicon: no false positive on clean reply", setter.lexicon_hits("Sure, send it over, thanks!") == [])
    check("lexicon: quoted history stripped",
         setter.lexicon_hits("Sure, send it over.\nOn Tue, Jan 1 wrote:\n> please unsubscribe me") == [])
    check("lexicon: case-insensitive", "cease" in setter.lexicon_hits("KINDLY CEASE"))

    # Pattern vetoes (fixed): a bare "Remove <Name>" at the start of a reply now
    # hints at an opt-out even though it never says "remove me", plus the
    # do-not-contact and delete-me patterns lexicon_hits() also checks.
    check("lexicon: 'Remove <Name>' pattern hints removal request (real remove_me fixture body)",
         "removal request" in setter.lexicon_hits("Remove Phil Lowe Sales Director Schiedel Chimney Systems Ltd."))
    check("lexicon: 'Please remove' (with a lead-in word) still matches the removal pattern",
         "removal request" in setter.lexicon_hits("Please remove John Smith from your list."))
    check("lexicon: 'remove' mid-sentence does NOT trip the removal pattern (only near the start)",
         "removal request" not in setter.lexicon_hits(
             "Thanks for reaching out. One thing that would help is if you could remove the friction in onboarding."))
    check("lexicon: 'do not contact' pattern", "do-not-contact request" in setter.lexicon_hits("Please do not contact me again."))
    check("lexicon: 'delete me' pattern", "delete request" in setter.lexicon_hits("Please delete me from your list."))
    check("lexicon: 'delete my email' pattern", "delete request" in setter.lexicon_hits("Could you delete my email from the system?"))


# ── 2. timezone mapper ──────────────────────────────────────────────────────

def test_guess_timezone():
    tz, conf = setter.guess_timezone({"country": "GB"})
    check("tz: GB country code", tz == "Europe/London", f"got {tz}")

    tz, conf = setter.guess_timezone({"country": "US", "state": "CA"})
    check("tz: US + CA state", tz == "America/Los_Angeles", f"got {tz}")

    tz, conf = setter.guess_timezone({"country": "US", "city": "chicago"})
    check("tz: US + city fallback", tz == "America/Chicago", f"got {tz}")

    tz, conf = setter.guess_timezone({"tld": "com.br", "body": ""})
    check("tz: .com.br TLD", tz == "America/Sao_Paulo", f"got {tz}")

    tz, conf = setter.guess_timezone({"tld": "co.uk", "body": ""})
    check("tz: .co.uk TLD (compound beats bare uk)", tz == "Europe/London", f"got {tz}")

    tz, conf = setter.guess_timezone({"body": "Sure, send it through. Jane Doe, VP Sales, San Francisco"})
    check("tz: US city named in body (Pacific)", tz == "America/Los_Angeles", f"got {tz}")

    tz, conf = setter.guess_timezone({"body": "nothing identifiable here"})
    check("tz: unknown -> None", tz is None and conf == 0.0, f"got {(tz, conf)}")

    # Fixed: setter.py's own wiring now runs the reply body through
    # _extract_phone() first (never passes the whole body as the "phone" hint),
    # so a phone number embedded mid-signature (the normal case) resolves via
    # the deterministic phone -> country-code path, exactly like the real
    # feel_free_send_details fixture.
    body = "Yeah feel free to send the details Kelly Head of Partnerships || +44 7732 728478 forgoodcode.com"
    extracted_phone = setter._extract_phone(body)
    check("phone: _extract_phone pulls just the number substring, not the whole body",
         extracted_phone == "+44 7732 728478", extracted_phone)

    tz_if_extracted, _ = setter.guess_timezone({"country": None, "state": None, "city": None,
                                                "phone": "+44 7732 728478", "tld": "forgoodcode.com", "body": body})
    check("tz: phone-based guess works when phone is pre-extracted", tz_if_extracted == "Europe/London",
         f"got {tz_if_extracted}")

    tz_real_wiring, _ = setter.guess_timezone({"country": None, "state": None, "city": None,
                                               "phone": extracted_phone, "tld": "forgoodcode.com", "body": body})
    check("tz: real pipeline wiring (_extract_phone -> guess_timezone) resolves the "
         "feel_free_send_details fixture's +44 signature to Europe/London",
         tz_real_wiring == "Europe/London", f"got {tz_real_wiring}")


# ── 3. slot picker ───────────────────────────────────────────────────────────

def test_pick_slots():
    from zoneinfo import ZoneInfo
    now_utc = dt.datetime(2026, 7, 11, 8, 0, tzinfo=dt.timezone.utc)  # a Saturday
    zi = ZoneInfo("Europe/London")

    def local_slot(d, hour, minute=0):
        local_dt = dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=zi)
        return local_dt.astimezone(dt.timezone.utc).isoformat()

    monday = dt.date(2026, 7, 13)
    wednesday = dt.date(2026, 7, 15)
    saturday = dt.date(2026, 7, 11)

    settings = {"work_start": 9, "work_end": 17,
                "_agent": {"calendly_event_url": "https://calendly.com/navreo/book-a-call"},
                "_lead": {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"}}

    # ── earliest-slot rule, case 1: a same-day slot >=2h after the first
    # qualifying slot exists -> that's the second slot, not a later day's.
    # Includes an 08:00 (before work_start) and a 17:00 (== work_end, excluded)
    # to prove the work-hours filter still runs before the earliest-slot pick.
    avail = [local_slot(monday, 8), local_slot(monday, 9), local_slot(monday, 10),
            local_slot(monday, 13), local_slot(monday, 17), local_slot(wednesday, 9)]
    slots = setter.pick_slots(avail, "Europe/London", settings, now_utc)
    check("slots: returns exactly 2 when a qualifying pair exists", len(slots) == 2, slots)
    if len(slots) == 2:
        check("slots: first slot is the earliest qualifying slot (09:00 Monday, not 08:00)",
             slots[0]["iso"][:16] == "2026-07-13T09:00", slots)
        check("slots: second slot is the same-day slot >=2h later (13:00), not Wednesday",
             slots[1]["iso"][:16] == "2026-07-13T13:00", slots)
        for s in slots:
            check(f"slots: label format for {s['iso']}",
                 all(tok in s["label"] for tok in (" at ", ",")) and any(c.isalpha() for c in s["label"][-4:]),
                 s["label"])
            check(f"slots: deep link format for {s['iso']}",
                 s["link"].startswith("https://calendly.com/navreo/book-a-call/") and
                 "name=Jane%20Doe" in s["link"] and "email=jane%40example.com" in s["link"],
                 s["link"])

    # ── case 2: no same-day slot >=2h after the first -> second slot is the
    # next available day's earliest slot instead.
    avail2 = [local_slot(monday, 9), local_slot(monday, 9, 45), local_slot(wednesday, 9)]
    slots2 = setter.pick_slots(avail2, "Europe/London", settings, now_utc)
    check("slots: case 2 returns exactly 2", len(slots2) == 2, slots2)
    if len(slots2) == 2:
        check("slots: case 2 first slot is still the earliest (Monday 09:00)",
             slots2[0]["iso"][:16] == "2026-07-13T09:00", slots2)
        check("slots: case 2 second slot skips the too-close 09:45 and falls to the next day's earliest",
             slots2[1]["iso"][:16] == "2026-07-15T09:00", slots2)

    # ── case 3: only one qualifying slot total -> a single slot is returned,
    # never padded out with something outside the rule.
    slots3 = setter.pick_slots([local_slot(monday, 9)], "Europe/London", settings, now_utc)
    check("slots: only one qualifying slot -> exactly one slot returned", len(slots3) == 1, slots3)

    # weekday-only + 20h-out filters, isolated
    only_weekend_and_soon = [local_slot(saturday, 10), (now_utc + dt.timedelta(hours=2)).isoformat()]
    slots_empty = setter.pick_slots(only_weekend_and_soon, "Europe/London", settings, now_utc)
    check("slots: weekend + too-soon slots both filtered out", slots_empty == [], slots_empty)

    check("slots: empty availability -> empty list", setter.pick_slots([], "Europe/London", settings, now_utc) == [])
    check("slots: bad tz name falls back instead of raising",
         isinstance(setter.pick_slots(avail, "Not/AZone", settings, now_utc), list))


# ── 4. draft lint ────────────────────────────────────────────────────────────

def test_lint_draft():
    ctx = {"subject": "Re: hello", "first_name": "Jane", "needs_resource_link": True,
           "instructions": "Resource: The breakdown - https://navreo.notion.site/abc - "
                           "send when they want more info.",
           "slot_status": "ok",
           "slot_links": ["https://calendly.com/x/1"], "slot_labels": ["Monday, 13th July at 10:00 AM BST"],
           "thread_text": ""}
    # email-shaped (v2): short <div> paragraphs separated by <br>, matching
    # the real house shape the drafter is now asked to produce.
    html_ok = ('<div>Hi Jane,</div><br><div>Of course.</div><br>'
              '<div><a href="https://navreo.notion.site/abc">Here is the breakdown</a></div><br>'
              '<div>Would you be free on <a href="https://calendly.com/x/1">Monday, 13th July at 10:00 AM BST</a>?</div><br>'
              '<div>Best,<br>Sam</div>')

    ok, reason = setter.lint_draft(html_ok, ctx)
    check("lint: clean email-shaped draft passes", ok, reason)

    # the OLD (pre-v2) single-line shape must now fail specifically on the
    # new email-shape check, even though every other check would pass it.
    single_line = ('Hi Jane, Of course. <a href="https://navreo.notion.site/abc">Here is the breakdown</a> '
                  'Would you be free on <a href="https://calendly.com/x/1">Monday, 13th July at 10:00 AM BST</a>? '
                  'Best, Sam')
    ok, reason = setter.lint_draft(single_line, ctx)
    check("lint: single-line (no div/br) draft fails the email-shape check",
         not ok and "formatted like an email" in reason, reason)

    # multiple <div> blocks with no <br> at all should also satisfy the shape
    # check (3+ blocks = at least 2 gaps between them), per the spec's "or
    # multiple div/p blocks" clause.
    div_only = ('<div>Hi Jane,</div><div>Of course.</div>'
               '<div><a href="https://navreo.notion.site/abc">Here is the breakdown</a></div>'
               '<div>Would you be free on <a href="https://calendly.com/x/1">Monday, 13th July at 10:00 AM BST</a>?</div>'
               '<div>Best, Sam</div>')
    ok, reason = setter.lint_draft(div_only, ctx)
    check("lint: multiple div blocks with no <br> still passes the email-shape check", ok, reason)

    ok, reason = setter.lint_draft(html_ok + "<br><div>We spoke on the phone — let's talk</div>", ctx)
    check("lint: em dash fails", not ok and "em dash" in reason, reason)

    ok, reason = setter.lint_draft(html_ok + "<br><div>{{first_name}}</div>", ctx)
    check("lint: unfilled placeholder fails", not ok and "placeholder" in reason, reason)

    ok, reason = setter.lint_draft(html_ok.replace('href="https://navreo.notion.site/abc"', 'href="https://x.example"'), ctx)
    check("lint: a link the instructions don't contain fails",
         not ok and reason == "The draft contains a link that isn't in the instructions.", reason)

    ok, reason = setter.lint_draft(html_ok + "<br><div>call us on 55512 now</div>", ctx)
    check("lint: invented number fails", not ok and "invents a number" in reason, reason)

    ok, reason = setter.lint_draft(html_ok.replace("Jane", "Bob"), ctx)
    check("lint: wrong first name fails", not ok and "first name" in reason, reason)

    ok, reason = setter.lint_draft(html_ok, {**ctx, "subject": ""})
    check("lint: empty subject fails", not ok and "subject" in reason, reason)

    ok, reason = setter.lint_draft("", ctx)
    check("lint: empty draft fails", not ok, reason)

    ok, reason = setter.lint_draft(html_ok.replace('<div><a href="https://navreo.notion.site/abc">Here is the breakdown</a></div><br>', ''),
                                   ctx)
    check("lint: resource link entirely absent fails",
         not ok and reason == "The draft is missing the resource link from the instructions.", reason)


def test_lint_draft_url_discipline():
    """New instructions-only URL allow-list (v3): every link the draft uses
    must come from the instructions, the offered call-time slot links
    (Calendly deep links count as slot links), the booking link, or a URL
    already present in the thread - anything else is an invented/wrong link."""
    base_ctx = {
        "subject": "Re: hi", "first_name": "Jane", "needs_resource_link": False,
        "instructions": "Resource: The guide - https://navreo.notion.site/guide - send on request. "
                        "Pricing: flat $500/mo.",
        "slot_status": "not_configured", "slot_links": [], "slot_labels": [], "thread_text": "",
    }

    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Here you go: '
        '<a href="https://navreo.notion.site/guide">the guide</a>.</div><br><div>Sam</div>', base_ctx)
    check("url discipline: a link straight from the instructions passes", ok, reason)

    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Here you go: '
        '<a href="https://evil.example/phish">a link</a>.</div><br><div>Sam</div>', base_ctx)
    check("url discipline: a link the instructions never mention fails",
         not ok and reason == "The draft contains a link that isn't in the instructions.", reason)

    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Here you go: '
        'https://evil.example/bare-in-text (no anchor tag at all).</div><br><div>Sam</div>', base_ctx)
    check("url discipline: a BARE (non-anchor) foreign URL in the text also fails",
         not ok and reason == "The draft contains a link that isn't in the instructions.", reason)

    # a trailing slash or trailing prose punctuation must not defeat the match
    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Here you go: '
        '<a href="https://navreo.notion.site/guide/">the guide</a>.</div><br><div>Sam</div>', base_ctx)
    check("url discipline: trailing slash on an otherwise-known link still passes", ok, reason)

    # send_resource in play: at least one instructions link must appear
    needs_link_ctx = {**base_ctx, "needs_resource_link": True}
    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Happy to help.</div><br><div>Sam</div>', needs_link_ctx)
    check("url discipline: send_resource draft with no instructions link fails",
         not ok and reason == "The draft is missing the resource link from the instructions.", reason)
    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Here you go: '
        '<a href="https://navreo.notion.site/guide">the guide</a>.</div><br><div>Sam</div>', needs_link_ctx)
    check("url discipline: send_resource draft WITH an instructions link passes", ok, reason)

    # a slot link and a booking link are both allowed even though neither is
    # mentioned in the instructions text
    slot_ctx = {**base_ctx, "slot_status": "ok", "slot_links": ["https://calendly.com/navreo/call/2026-07-15T09:00"],
               "slot_labels": ["Wed 9am"]}
    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Free on '
        '<a href="https://calendly.com/navreo/call/2026-07-15T09:00">Wed 9am</a>?</div><br><div>Sam</div>',
        slot_ctx)
    check("url discipline: a Calendly slot deep link is always allowed", ok, reason)

    booking_ctx = {**base_ctx, "booking_link": "https://calendly.com/navreo/book-a-call"}
    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Feel free to '
        '<a href="https://calendly.com/navreo/book-a-call">book a call here</a>.</div><br><div>Sam</div>',
        booking_ctx)
    check("url discipline: the booking link is always allowed", ok, reason)

    # a URL already present in the thread (e.g. the lead's own prior message)
    # is allowed even though it's not in the instructions
    thread_ctx = {**base_ctx, "thread_text": "as discussed at https://partner.example/deck"}
    ok, reason = setter.lint_draft(
        '<div>Hi Jane,</div><br><div>Here is '
        '<a href="https://partner.example/deck">the deck</a> again.</div><br><div>Sam</div>', thread_ctx)
    check("url discipline: a URL already present in the thread is allowed", ok, reason)


# ── 4b. Calendly fallback lint (owner ruling 2026-07-14) ────────────────────

FALLBACK_LINT_CTX = {
    "subject": "Re: hi", "first_name": "Jane", "needs_resource_link": False,
    "instructions": "Resource: The guide - https://navreo.notion.site/guide - send on request.",
    "slot_status": "not_configured", "slot_links": [], "slot_labels": [], "thread_text": "",
    "booking_link": "https://calendly.com/navreo/book-a-call",
    "slots_fallback": True, "needs_availability_ask": True,
}


def test_lint_draft_calendly_fallback_booking_link():
    """When Calendly can't offer real times (slots_fallback) and the ask is
    scheduling-relevant (needs_availability_ask), the draft must link the
    booking page as a REAL <a href> hyperlink - never bare text - and never
    invent a specific slot-time deep link (already caught by the existing
    URL allow-list, since slot_links is empty in fallback mode)."""
    ok_html = ('<div>Hi Jane,</div><br><div>When would be a good time for us to talk? '
              'Here is <a href="https://calendly.com/navreo/book-a-call">my availability</a>.</div><br>'
              '<div>Sam</div>')
    ok, reason = setter.lint_draft(ok_html, FALLBACK_LINT_CTX)
    check("lint: fallback draft with a proper hyperlinked booking link passes", ok, reason)

    bare_html = ('<div>Hi Jane,</div><br><div>When would be a good time for us to talk? '
                'Here is my availability: https://calendly.com/navreo/book-a-call</div><br><div>Sam</div>')
    ok, reason = setter.lint_draft(bare_html, FALLBACK_LINT_CTX)
    check("lint: fallback draft with a bare (non-hyperlinked) booking URL fails",
         not ok and reason == "The draft doesn't link a calendar for the lead to pick a time.", reason)

    no_link_html = '<div>Hi Jane,</div><br><div>When would be a good time for us to talk?</div><br><div>Sam</div>'
    ok, reason = setter.lint_draft(no_link_html, FALLBACK_LINT_CTX)
    check("lint: fallback draft missing the booking link entirely fails",
         not ok and reason == "The draft doesn't link a calendar for the lead to pick a time.", reason)

    slot_time_html = ('<div>Hi Jane,</div><br><div>Would you be free on '
                      '<a href="https://calendly.com/navreo/book-a-call/2026-07-15T09:00">Wednesday at 9am</a>?'
                      '</div><br><div>Sam</div>')
    ok, reason = setter.lint_draft(slot_time_html, FALLBACK_LINT_CTX)
    check("lint: fallback draft with an invented slot-time deep link fails via the URL allow-list",
         not ok and reason == "The draft contains a link that isn't in the instructions.", reason)

    # non-scheduling ask (needs_availability_ask False): the new requirement
    # doesn't apply even though slots_fallback is still true
    non_sched_ctx = {**FALLBACK_LINT_CTX, "needs_availability_ask": False, "needs_resource_link": True}
    resource_only_html = ('<div>Hi Jane,</div><br><div>Here you go: '
                          '<a href="https://navreo.notion.site/guide">the guide</a>.</div><br><div>Sam</div>')
    ok, reason = setter.lint_draft(resource_only_html, non_sched_ctx)
    check("lint: fallback ctx but non-scheduling ask doesn't require the booking hyperlink", ok, reason)


def test_lint_draft_calendly_fallback_instructions_link():
    """Feature C / owner ruling 2026-07-14: the fallback ladder's step ONE
    lets a draft propose a meeting using a scheduling/calendar link the
    INSTRUCTIONS themselves state, with no booking_link set at all - the
    loosened lint check (any anchor into the allow-list, not specifically
    booking_link) must accept that."""
    ctx_no_booking_link = {
        "subject": "Re: hi", "first_name": "Jane", "needs_resource_link": False,
        "instructions": "I'm generally free weekday afternoons UK time. You can also grab a slot "
                        "directly on my calendar: https://calendly.com/navreo/discovery-call",
        "slot_status": "not_configured", "slot_links": [], "slot_labels": [], "thread_text": "",
        "slots_fallback": True, "needs_availability_ask": True,
        # no booking_link key at all - the old check would have hard-failed here
    }
    html = ('<div>Hi Jane,</div><br><div>Would love to find a time that works for you.</div><br>'
           '<div>I\'m generally free weekday afternoons UK time, or grab a slot on '
           '<a href="https://calendly.com/navreo/discovery-call">my calendar</a>.</div><br><div>Sam</div>')
    ok, reason = setter.lint_draft(html, ctx_no_booking_link)
    check("lint: fallback draft anchored to an INSTRUCTIONS calendar link (no booking_link set) passes",
         ok, reason)

    no_anchor_html = ('<div>Hi Jane,</div><br><div>Would love to find a time that works for you.</div><br>'
                      '<div>I\'m generally free weekday afternoons UK time.</div><br><div>Sam</div>')
    ok, reason = setter.lint_draft(no_anchor_html, ctx_no_booking_link)
    check("lint: fallback draft with no anchor at all still fails, even mentioning a window in prose",
         not ok and reason == "The draft doesn't link a calendar for the lead to pick a time.", reason)


def test_lint_draft_slot_status_ok_unchanged_by_fallback_rules():
    """slots_fallback/needs_availability_ask are irrelevant when slot_status
    is "ok" - the pre-existing two-slots + booking-link behaviour is exactly
    as before (regression guard for the gate-7/lint rework)."""
    ok_ctx = {
        "subject": "Re: hello", "first_name": "Jane", "needs_resource_link": False,
        "instructions": "", "slot_status": "ok",
        "slot_links": ["https://calendly.com/x/1"], "slot_labels": ["Monday, 13th July at 10:00 AM BST"],
        "thread_text": "", "booking_link": "https://calendly.com/navreo/book-a-call",
        # even if these were mistakenly left set, slot_status == "ok" must
        # take priority and the fallback hyperlink rule must not fire
        "slots_fallback": True, "needs_availability_ask": True,
    }
    html = ('<div>Hi Jane,</div><br><div>Would you be free on '
           '<a href="https://calendly.com/x/1">Monday, 13th July at 10:00 AM BST</a>?</div><br><div>Sam</div>')
    ok, reason = setter.lint_draft(html, ok_ctx)
    check("lint: slot_status ok always wins over stray slots_fallback/needs_availability_ask flags", ok, reason)


# ── 5. decision matrix ───────────────────────────────────────────────────────

def _cls(primary, all_intents=None, simple_ask=True, confidence=0.95, red_flags=None):
    return {"primary_intent": primary, "all_intents": all_intents or [primary],
            "simple_ask": simple_ask, "confidence": confidence, "red_flags": red_flags or []}


AGENT_AUTO = {"mode": "autopilot", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"],
             "pricing_notes": "Flat $500/mo, 3 seats included.", "confidence_threshold": 0.9}
CTX_ALL_GOOD = {"red_flag_hits": [], "category": None, "first_touch": True, "slot_status": "ok",
                "timezone": "Europe/London", "lint_ok": True, "lint_reason": "", "body_len": 20, "hydrated": True,
                # The global autopilot master switch (settings.autopilot_enabled) ships OFF and
                # gates every other decide() rule - "all good" here means the operator has also
                # turned the switch on, same as every other CTX_ALL_GOOD field being satisfied.
                "autopilot_enabled": True}


def test_decide_matrix():
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: autopilot + simple + conf .95 -> auto_send", d == "auto_send", r)

    d, r = setter.decide(_cls("send_resource", confidence=0.85), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: conf .85 below .9 threshold -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), {**AGENT_AUTO, "mode": "draft_only"}, CTX_ALL_GOOD)
    check("decide: draft_only mode -> review", d == "review", r)

    d, r = setter.decide(_cls("bespoke_request", simple_ask=False, confidence=0.4), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: bespoke_request not in allowed_intents -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "red_flag_hits": ["cease"]})
    check("decide: lexicon veto -> review even though intent/confidence look fine", d == "review", r)

    d, r = setter.decide(_cls("send_resource", red_flags=["hostile tone"]), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: LLM red_flags veto -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "category": "Not Interested"})
    check("decide: Smartlead categoriser veto -> review", d == "review", r)

    # multi-turn autonomy, user ruling 2026-07-13: a later-turn reply that is
    # STILL a simple, fully-allowed ask now continues past the first-touch
    # gate instead of always holding (this replaces the old "second reply
    # always goes to review" assertion - see the matching multi-turn tests
    # further down for the off-intent / not-simple-ask review cases).
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "first_touch": False})
    check("decide: second reply, simple + allowed ask -> auto_send (multi-turn autonomy)", d == "auto_send", r)

    # Calendly fallback, owner ruling 2026-07-14: no free slots / Calendly not
    # connected no longer holds the reply - the drafter proposes no times at
    # all (the fallback availability-ask instead), so timezone/slot risk is
    # zero and these now auto-send exactly like any other clean gate-7 pass.
    # (Previously these asserted "review"; see test_decide_gate7_calendly_
    # fallback_skips_holds below for the full gate-7 rework coverage.)
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "slot_status": "none_available"})
    check("decide: no Calendly slots available -> calendly fallback -> auto_send", d == "auto_send", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "slot_status": "not_configured"})
    check("decide: Calendly not connected -> calendly fallback -> auto_send", d == "auto_send", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "timezone": None})
    check("decide: unresolved timezone -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "body_len": 1600})
    check("decide: body over 1500 chars -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "lint_ok": False, "lint_reason": "x"})
    check("decide: lint failure -> review", d == "review", r)

    d, r = setter.decide(_cls("not_interested", confidence=0.95), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: clear negative -> no_action (not review, not auto_send)", d == "no_action", r)

    d, r = setter.decide(_cls("unsubscribe_dnc", confidence=0.95), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: clear negative (unsubscribe) -> no_action", d == "no_action", r)

    d, r = setter.decide(_cls("pricing"), {**AGENT_AUTO, "pricing_notes": ""}, CTX_ALL_GOOD)
    check("decide: pricing intent but empty pricing_notes -> review", d == "review", r)

    d, r = setter.decide(_cls("pricing"), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: pricing intent with non-empty pricing_notes -> auto_send", d == "auto_send", r)

    d, r = setter.decide(_cls("scheduling"), {**AGENT_AUTO, "allowed_intents": ["send_resource"]}, CTX_ALL_GOOD)
    check("decide: scheduling always allowed even if not in agent.allowed_intents", d == "auto_send", r)

    d, r = setter.decide(_cls("scheduling", simple_ask=False), AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: scheduling but not a simple ask (e.g. specific date) -> review", d == "review", r)

    d, r = setter.decide({"primary_intent": None, "all_intents": [], "simple_ask": False, "confidence": 0.0,
                         "red_flags": []}, AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: classify failure (no primary_intent) -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource", all_intents=["send_resource", "objection_or_question"]),
                         AGENT_AUTO, CTX_ALL_GOOD)
    check("decide: any off-allowlist intent in all_intents vetoes, not just primary", d == "review", r)

    # ── autopilot master switch (settings.autopilot_enabled, ships OFF) ─────
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "autopilot_enabled": False})
    check("decide: master switch off vetoes an otherwise-perfect auto_send", d == "review", r)
    check("decide: master switch off - exact plain-English reason", r ==
         "Held for review: every check passed, but the autopilot master switch is off.", r)

    ctx_no_switch_key = {k: v for k, v in CTX_ALL_GOOD.items() if k != "autopilot_enabled"}
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, ctx_no_switch_key)
    check("decide: master switch defaults to off when the key is absent entirely", d == "review", r)

    # ── category-disagreement guard (clear negative vs Smartlead's own categoriser) ──
    d, r = setter.decide(_cls("not_interested", confidence=0.9), AGENT_AUTO, {**CTX_ALL_GOOD, "category": "Interested"})
    check("decide: classifier says not_interested but Smartlead categorised it Interested -> review (disagreement)",
         d == "review", r)
    check("decide: disagreement reason names both readings", r ==
         "Held for review: the AI read this as a not interested but Smartlead categorised it as "
         "Interested, so a person should decide.", r)

    d, r = setter.decide(_cls("not_interested", confidence=0.9), AGENT_AUTO, {**CTX_ALL_GOOD, "category": "Not Interested"})
    check("decide: classifier and Smartlead categoriser agree (Not Interested) -> no_action", d == "no_action", r)

    # ── answered_since_reply veto (a person already replied in Smartlead) ───
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "answered_since_reply": True})
    check("decide: answered_since_reply -> no_action", d == "no_action", r)
    check("decide: answered_since_reply - exact reason", r == "Someone already replied to this lead in Smartlead.", r)

    # ── lexicon pattern veto overrides even a naive classification ──────────
    remove_name_body = "Remove Phil Lowe Sales Director Schiedel Chimney Systems Ltd."
    hits = setter.lexicon_hits(remove_name_body)
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "red_flag_hits": hits})
    check("decide: 'Remove <Name>' lexicon pattern vetoes even a naive send_resource classification",
         d == "review", r)


# ── 5b. gate 7 rework: Calendly fallback (owner ruling 2026-07-14) ─────────
#
# When real call times can't be offered for ANY reason (Calendly not
# connected, an API error, no free slots, or the lead's timezone couldn't be
# worked out), the agent no longer holds the reply for review - it drafts
# the fallback ask ("When would be a good time for us to talk? Here is my
# availability", hyperlinked to the booking link) instead, and that draft
# may auto-send if every other gate passes. slots_fallback = (slot_status !=
# "ok") is set at every ctx build site; decide() also derives it from
# slot_status alone when the key is absent, so direct decide() callers that
# never set it (like most of this file) keep working unchanged.

def test_decide_gate7_calendly_fallback_skips_holds():
    """Every reason real times aren't available (not_configured, error,
    none_available, tz_unknown) now skips the timezone-None hold, the
    tz_confident hold, and the old per-status hold entirely - a simple
    scheduling ask with everything else green auto_sends."""
    for bad_status in ("error", "not_configured", "none_available", "tz_unknown"):
        ctx = {**CTX_ALL_GOOD, "slot_status": bad_status, "timezone": None,
              "tz_confident": False, "slots_fallback": True}
        d, r = setter.decide(_cls("scheduling"), AGENT_AUTO, ctx)
        check(f"decide: calendly fallback ({bad_status}) + unresolved timezone -> auto_send, not held",
             d == "auto_send", (d, r))


def test_decide_gate7_calendly_fallback_ignores_tz_confidence():
    """A known-but-unconfident timezone guess is also irrelevant under
    fallback mode - the draft proposes no times at all, so tz_confident=False
    can't veto it any more."""
    d, r = setter.decide(_cls("scheduling"), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "slot_status": "not_configured", "timezone": "America/New_York",
                          "tz_confident": False, "slots_fallback": True})
    check("decide: calendly fallback ignores tz_confident=False -> auto_send", d == "auto_send", r)


def test_decide_gate7_slot_status_ok_keeps_holds_unchanged():
    """When slot_status IS "ok" (slots_fallback False), gate 7 behaves
    exactly as before the rework - an unresolved timezone or a low-confidence
    guess still holds, real times are actually being proposed."""
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "slot_status": "ok", "timezone": None, "slots_fallback": False})
    check("decide: slot_status ok + unresolved timezone still holds, unchanged",
         d == "review" and r == "Held for review: couldn't work out the lead's timezone.", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "slot_status": "ok", "timezone": "Europe/London",
                          "tz_confident": False, "slots_fallback": False})
    check("decide: slot_status ok + low-confidence timezone still holds, unchanged",
         d == "review" and "not sure enough of the lead's timezone" in r, r)


def test_decide_gate_3b_same_day_ask_still_holds_under_fallback():
    """The same-day-scheduling gate (3b) runs BEFORE gate 7 and is untouched
    by the calendly-fallback rework - an urgent same-day ask still needs a
    human, even when Calendly is down (fallback mode would otherwise
    auto-send)."""
    d, r = setter.decide(_cls("scheduling"), AGENT_AUTO, {**CTX_ALL_GOOD, "same_day_ask": True})
    check("decide: same-day scheduling ask still holds for a person", d == "review", r)
    check("decide: same-day hold reason unchanged",
         r == "Held for review: the lead wants to talk today, which needs a person right now.", r)

    d2, r2 = setter.decide(_cls("scheduling"), AGENT_AUTO,
                           {**CTX_ALL_GOOD, "same_day_ask": True, "slot_status": "error",
                            "timezone": None, "slots_fallback": True})
    check("decide: same-day gate still wins even when calendly fallback would otherwise auto-send",
         d2 == "review", r2)


def test_decide_gate7_master_switch_still_last_under_fallback():
    """Mode + the global master switch are still checked LAST, even for a
    calendly-fallback draft that would otherwise auto-send."""
    d, r = setter.decide(_cls("scheduling"), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "slot_status": "not_configured", "timezone": None,
                          "slots_fallback": True, "autopilot_enabled": False})
    check("decide: master switch off still overrides a calendly-fallback auto_send", d == "review", r)
    check("decide: master switch off reason unchanged even under fallback", r ==
         "Held for review: every check passed, but the autopilot master switch is off.", r)

    d2, r2 = setter.decide(_cls("scheduling"), {**AGENT_AUTO, "mode": "draft_only"},
                           {**CTX_ALL_GOOD, "slot_status": "not_configured", "timezone": None,
                            "slots_fallback": True})
    check("decide: draft_only mode still overrides a calendly-fallback auto_send", d2 == "review", r2)


# ── 6. fixtures-driven decision pass ────────────────────────────────────────

def _load_fixtures():
    with open(FIXTURES_PATH) as f:
        return json.load(f)["cases"]


def test_fixtures():
    cases = {c["name"]: c for c in _load_fixtures()}

    def run(name, primary, all_intents=None, simple_ask=True, confidence=0.95, agent=None, ctx_overrides=None):
        c = cases[name]
        body = c["body"]
        ctx = dict(CTX_ALL_GOOD)
        ctx["red_flag_hits"] = setter.lexicon_hits(body)
        ctx["body_len"] = len(body)
        ctx.update(ctx_overrides or {})
        d, r = setter.decide(_cls(primary, all_intents, simple_ask, confidence), agent or AGENT_AUTO, ctx)
        exp = c["expected"]
        want_auto = exp.get("auto_ok")
        got_auto = d == "auto_send"
        check(f"fixture[{name}]: auto_ok == {want_auto}", got_auto == want_auto,
             f"decide()->({d}, {r!r}); intent={primary}")

    run("bare_sure", "send_resource")
    run("send_it_signature", "send_resource")
    run("know_more", "send_resource")
    run("feel_free_send_details", "send_resource")
    run("meeting_pick_my_calendly", "scheduling")
    run("specific_date_request", "scheduling", simple_ask=False, confidence=0.6)
    run("zero_upfront_conditional", "objection_or_question", all_intents=["objection_or_question"],
       simple_ask=False, confidence=0.5)
    run("commission_question", "objection_or_question", all_intents=["objection_or_question"],
       simple_ask=False, confidence=0.5)
    run("interested_where_based", "objection_or_question", all_intents=["objection_or_question", "send_resource"],
       simple_ask=False, confidence=0.5)
    run("not_agency_open_to_call", "objection_or_question", all_intents=["objection_or_question", "scheduling"],
       simple_ask=False, confidence=0.5)
    run("loom_for_us", "bespoke_request", simple_ask=False, confidence=0.9)
    run("custom_breakdown", "bespoke_request", simple_ask=False, confidence=0.9)
    run("kindly_cease", "send_resource", confidence=0.95)  # lexicon veto should override a wrong/naive classification
    run("remove_me", "unsubscribe_dnc", confidence=0.95)
    run("no_thanks", "not_interested", confidence=0.95)
    run("unsubscribe_outlook", "unsubscribe_dnc", confidence=0.95)
    run("ooo_travelling", "ooo", confidence=0.95)
    run("inactive_mailbox", "bounce_or_system", confidence=0.9)
    run("spam_block_notice", "bounce_or_system", confidence=0.95)
    run("angry_legal", "unsubscribe_dnc", confidence=0.95)
    run("broken_link", "send_resource", all_intents=["send_resource", "objection_or_question"],
       simple_ask=False, confidence=0.5)
    run("forward_colleague", "wrong_person", confidence=0.85)
    run("tz_brazil", "send_resource")
    run("tz_us_pacific", "send_resource")

    # pricing: auto only when pricing_notes non-empty (fixture's own expected.auto_ok
    # assumes a pricing_notes-bearing agent; the empty-notes case is checked separately)
    check("fixture[whats_the_price]: review when this agent's pricing_notes is empty",
         setter.decide(_cls("pricing"), {**AGENT_AUTO, "pricing_notes": ""}, CTX_ALL_GOOD)[0] == "review")
    run("whats_the_price", "pricing", agent=AGENT_AUTO)
    run("price_with_niche", "pricing", agent={**AGENT_AUTO, "pricing_notes": "Exporters: $400/mo flat."})

    # intent_depends fixtures: resource IS the video vs. isn't (no single "auto_ok" in
    # the fixture for these - both branches are asserted directly against the notes)
    video_agent = {**AGENT_AUTO, "resource_name": "Demo video", "resource_description": "A short walkthrough video"}
    c = cases["resend_video_fixed"]
    ctx = dict(CTX_ALL_GOOD)
    ctx["red_flag_hits"] = setter.lexicon_hits(c["body"])
    ctx["body_len"] = len(c["body"])
    d, r = setter.decide(_cls("send_resource"), video_agent, ctx)
    check("fixture[resend_video_fixed]: auto_send when the agent's fixed resource IS the video", d == "auto_send", r)

    c = cases["share_video_bespoke"]
    ctx = dict(CTX_ALL_GOOD)
    ctx["red_flag_hits"] = setter.lexicon_hits(c["body"])
    ctx["body_len"] = len(c["body"])
    d, r = setter.decide(_cls("bespoke_request", simple_ask=False, confidence=0.6), AGENT_AUTO, ctx)
    check("fixture[share_video_bespoke]: review (default_auto_ok false) when resource isn't the video", d == "review", r)

    # second-touch: multi-turn autonomy, user ruling 2026-07-13 - a simple,
    # fully-allowed later-turn ask ("sure, send it over" is exactly that) now
    # continues past the first-touch gate instead of always dropping to
    # review. (This fixture's own "auto_ok": false / note describe the
    # pre-2026-07-13 behaviour and are left as historical data in
    # setter_fixtures.json; this test asserts the new spec directly.)
    c = cases["sure_but_second_reply"]
    ctx = dict(CTX_ALL_GOOD)
    ctx["red_flag_hits"] = setter.lexicon_hits(c["body"])
    ctx["body_len"] = len(c["body"])
    ctx["first_touch"] = False
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, ctx)
    check("fixture[sure_but_second_reply]: simple later-turn ask now auto_sends (multi-turn autonomy)",
         d == "auto_send", r)

    # long_detailed_email: the fixture's own body is only ~1000 chars (short of the
    # 1500 the fixture's note describes) - pad it in the test itself so the length
    # veto is actually exercised as intended, rather than silently not-testing it.
    c = cases["long_detailed_email"]
    padded_body = c["body"] + ("X" * 1000)
    check("fixture[long_detailed_email]: source body itself is not actually >1500 chars (fixture data note)",
         len(c["body"]) <= 1500, f"len={len(c['body'])}")
    ctx = dict(CTX_ALL_GOOD)
    ctx["body_len"] = len(padded_body)
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, ctx)
    check("fixture[long_detailed_email]: >1500 chars vetoes auto_send", d != "auto_send", r)


# ── 7. idempotent intake ────────────────────────────────────────────────────

def test_idempotent_intake():
    sb, http = fresh_setter()

    def classify_should_not_be_called(_body):
        raise AssertionError("classify() must not be called for an already-queued reply")

    existing_row = {
        "id": 1, "workspace": "navreo", "smartlead_campaign_id": 111, "agent_id": "agent-aaaa1111",
        "lead_email": "dupe@example.com", "message_id": "msg-1", "status": "needs_review",
        "decision": "review", "decision_reason": "Held for review: not confident enough this is a simple ask.",
        "reply_body": "hi", "created_at": "2026-07-01T00:00:00+00:00",
    }
    sb.queue.append(existing_row)

    agent = {"id": "agent-aaaa1111", "mode": "autopilot", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "pricing_notes": "x",
             "confidence_threshold": 0.9}
    http.classify_fn = classify_should_not_be_called

    reply = {"workspace": "navreo", "campaign_id": 111, "email": "dupe@example.com", "message_id": "msg-1",
             "body": "hi", "subject": "Re: hi", "replied_at": "2026-07-10T00:00:00+00:00", "is_test": False}
    row = setter.process_reply(reply, agent, {})
    check("idempotent intake: dupe message_id returns the existing row unchanged",
         row.get("id") == 1 and row.get("status") == "needs_review", row)
    check("idempotent intake: no new row was inserted", len(sb.queue) == 1, len(sb.queue))


# ── 8. test-inject never sends for real ─────────────────────────────────────

def test_inject_never_sends():
    sb, http = fresh_setter()
    setter.route_settings_save({"autopilot_enabled": True})
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.98, "red_flags": [], "timezone_guess": "Europe/London", "tz_confidence": 0.9,
        "wants": "wants the resource", "rationale": "unqualified yes",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": 'Hi Test, <a href="https://x.example/r">Here it is</a>. Best, Sam'}
    http.calendly_avail = []  # slot_status stays not_configured/none regardless - irrelevant to this test

    agent = {
        "id": "agent-bbbb2222", "mode": "autopilot", "enabled": True, "campaign_ids": [222],
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "pricing_notes": "x",
        "confidence_threshold": 0.9, "resource_link": "https://x.example/r",
        "calendly_event_url": "https://calendly.com/navreo/book-a-call",
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    payload = {"campaign_id": 222, "email": "test@example.com", "body": "sure, send it over!"}
    status, resp = setter.route_test_inject(payload)
    row = resp.get("row") or {}

    check("test-inject: returns 200", status == 200, (status, resp))
    check("test-inject: row is flagged is_test", row.get("is_test") is True, row)
    smartlead_send_calls = [c for c in http.smartlead_calls if "reply-email-thread" in c[1]]
    check("test-inject: never calls the real Smartlead send endpoint", smartlead_send_calls == [], smartlead_send_calls)
    check("test-inject: never calls Smartlead hydration either (is_test skips it)", http.smartlead_calls == [],
         http.smartlead_calls)
    check("test-inject: dry-sent rows are still marked as sent/auto_sent, not silently dropped",
         row.get("status") in ("auto_sent", "sent", "needs_review"), row.get("status"))


def test_env_dry_run_send_never_hits_network():
    sb, http = fresh_setter()
    os.environ["SETTER_DRY_RUN"] = "1"
    try:
        row = {"id": 42, "smartlead_campaign_id": 333, "lead_email": "a@b.com", "message_id": "m1",
              "reply_body": "hi", "replied_at": "2026-07-01T00:00:00+00:00"}
        result = setter._send_reply(row, {}, "Re: hi", "<p>hi</p>", is_test=False, success_status="auto_sent")
        check("SETTER_DRY_RUN=1: send succeeds without hitting the network",
             result.get("ok") is True and http.calls == [], (result, http.calls))
    finally:
        os.environ.pop("SETTER_DRY_RUN", None)


# ── 9. poll batching cap ─────────────────────────────────────────────────────

def test_poll_batching_cap():
    sb, http = fresh_setter()
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.5,  # deliberately below any default threshold so nothing auto-sends mid-test
        "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0, "wants": "wants info", "rationale": "",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Sam"}

    agent = {"id": "agent-cccc3333", "mode": "draft_only", "enabled": True, "campaign_ids": [444],
             "allowed_intents": ["send_resource"], "pricing_notes": "", "confidence_threshold": 0.9}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    for i in range(20):
        sb.replies.append({
            "workspace": "navreo", "smartlead_campaign_id": 444, "email": f"lead{i}@example.com",
            "first_name": "Lead", "last_name": str(i), "company_domain": "example.com",
            "subject": "Re: hi", "reply_body": "sure, send it", "replied_at": "2026-07-10T00:00:00+00:00",
            "message_id": f"m-{i}", "category": "Interested",  # core-four, or the intake gate would skip all 20
        })

    summary = setter.run_poll()
    check("poll: never processes more than 15 replies in one tick", summary.get("checked", 0) <= 15,
         summary)
    check("poll: did process some replies", summary.get("checked", 0) > 0, summary)
    check("poll: queued rows count matches checked count", len(sb.queue) == summary.get("checked", 0),
         (len(sb.queue), summary))

    # a second poll tick should pick up the remaining backlog (nothing already
    # queued gets reprocessed - the still-pending replies are what's left)
    summary2 = setter.run_poll()
    check("poll: second tick makes further progress on the backlog", summary2.get("checked", 0) > 0, summary2)
    check("poll: never re-queues an already-queued reply",
         len(sb.queue) == summary.get("checked", 0) + summary2.get("checked", 0), (len(sb.queue), summary, summary2))


def test_poll_never_raises_on_bad_agent_config():
    sb, http = fresh_setter()
    # no agents at all -> run_poll must return a summary, not raise
    summary = setter.run_poll()
    check("poll: no agents configured -> returns empty summary without raising",
         summary == {"checked": 0, "queued": 0, "auto_sent": 0, "needs_review": 0, "no_action": 0, "errors": 0},
         summary)


def test_run_poll_assigned_at_filter():
    sb, http = fresh_setter()
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.5, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants info", "rationale": "",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Sam"}

    agent = {"id": "agent-assigned01", "mode": "draft_only", "enabled": True, "campaign_ids": [700],
             "allowed_intents": ["send_resource"], "pricing_notes": "",
             "campaign_assigned_at": {"700": "2026-07-05T00:00:00+00:00"}}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 700, "email": "old@example.com",
        "subject": "Re: hi", "reply_body": "sure, send it", "replied_at": "2026-07-01T00:00:00+00:00",
        "smartlead_message_id": "old-1", "category": "Interested",  # core-four so assigned_at is the only gate at play
    })
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 700, "email": "new@example.com",
        "subject": "Re: hi", "reply_body": "sure, send it", "replied_at": "2026-07-10T00:00:00+00:00",
        "smartlead_message_id": "new-1", "category": "Interested",
    })

    summary = setter.run_poll()
    check("run_poll: a reply older than campaign_assigned_at is skipped, only the newer one is checked",
         summary.get("checked") == 1, summary)
    emails_processed = {r.get("lead_email") for r in sb.queue}
    check("run_poll: the newer reply is the one that actually got queued",
         emails_processed == {"new@example.com"}, emails_processed)


def test_route_queue_action_send_409_when_already_sent():
    sb, http = fresh_setter()
    sb.queue.append({"id": 501, "workspace": "navreo", "smartlead_campaign_id": 111, "lead_email": "x@y.com",
                     "message_id": "m1", "status": "auto_sent", "draft_body": "hi", "draft_subject": "Re: hi",
                     "reply_subject": "hi"})
    sb.queue.append({"id": 502, "workspace": "navreo", "smartlead_campaign_id": 111, "lead_email": "z@y.com",
                     "message_id": "m2", "status": "sent", "draft_body": "hi", "draft_subject": "Re: hi",
                     "reply_subject": "hi"})

    status, resp = setter.route_queue_action({"id": 501, "action": "send"})
    check("route_queue_action: send on an already auto_sent row returns 409", status == 409, (status, resp))
    check("route_queue_action: 409 body is the exact double-send message",
         resp == {"error": "This reply was already sent."}, resp)

    status2, resp2 = setter.route_queue_action({"id": 502, "action": "send"})
    check("route_queue_action: send on an already sent row also returns 409", status2 == 409, (status2, resp2))


# ── real Smartlead sub-sequence enrolment ───────────────────────────────────

def _subsequence_fixture(sb, http, campaign_id=3591996, sub_id=3633403, lead_id=42,
                          email="lead@x.com", map_id=777888):
    """Wires up the Smartlead fixtures a subsequence push needs: one campaign
    (`sub_id`) whose parent_campaign_id is `campaign_id` (so
    _sl_find_subsequences() resolves it automatically), and one lead in
    `campaign_id`'s leads listing carrying `map_id` as its campaign_lead_map_id
    (so _sl_campaign_lead_map_id() resolves it)."""
    http.all_campaigns = [{"id": sub_id, "name": "Meeting Request", "status": "ACTIVE",
                           "parent_campaign_id": campaign_id}]
    http.campaign_leads_by_campaign[str(campaign_id)] = [
        {"campaign_lead_map_id": map_id, "status": "INPROGRESS", "created_at": "2026-07-01T00:00:00Z",
         "lead": {"id": lead_id, "email": email, "first_name": "Lead"}},
    ]


def test_subsequence_success_pushes_live_and_patches_flag():
    sb, http = fresh_setter()
    _subsequence_fixture(sb, http)
    sb.queue.append({"id": 601, "workspace": "navreo", "smartlead_campaign_id": 3591996,
                     "lead_email": "lead@x.com", "smartlead_lead_id": 42, "message_id": "m1",
                     "status": "needs_review", "added_to_subsequence": False})

    status, resp = setter.route_queue_action({"id": 601, "action": "subsequence", "checked": True})

    check("subsequence success: 200 status", status == 200, (status, resp))
    check("subsequence success: response says added_to_subsequence=true", resp.get("ok") is True
         and resp.get("added_to_subsequence") is True, resp)
    check("subsequence success: resolved subsequence id in response", resp.get("subsequence_id") == 3633403, resp)
    check("subsequence success: exactly one live push POST fired", len(http.subsequence_push_calls) == 1,
         http.subsequence_push_calls)
    pushed_body = http.subsequence_push_calls[0] if http.subsequence_push_calls else {}
    check("subsequence success: push body carries the resolved email_lead_map_id",
         pushed_body.get("email_lead_map_id") == 777888, pushed_body)
    check("subsequence success: push body targets the resolved subsequence",
         pushed_body.get("sub_sequence_id") == 3633403, pushed_body)
    check("subsequence success: push body stops the lead on a parent-campaign reply",
         pushed_body.get("stop_lead_on_parent_campaign_reply") is True, pushed_body)
    check("subsequence success: flag IS patched in the queue row",
         sb.queue[0].get("added_to_subsequence") is True, sb.queue[0])


def test_subsequence_failure_http200_okfalse_returns_502():
    """Live-proven 2026-07-13: Smartlead answers HTTP 200 with
    {"ok": false, "message": "Invalid subsequence or not related to the
    parent campaign"} for a bad sub_sequence_id - no "success" key at all.
    Success must be an explicit positive, or the route must report failure."""
    sb, http = fresh_setter()
    _subsequence_fixture(sb, http)
    http.subsequence_push_result = {"ok": False,
                                    "message": "Invalid subsequence or not related to the parent campaign"}
    sb.queue.append({"id": 603, "workspace": "navreo", "smartlead_campaign_id": 3591996,
                     "lead_email": "lead@x.com", "smartlead_lead_id": 42, "message_id": "m3",
                     "status": "needs_review", "added_to_subsequence": False})

    status, resp = setter.route_queue_action({"id": 603, "action": "subsequence", "checked": True})

    check("subsequence http200 ok:false -> 502", status == 502, (status, resp))
    check("subsequence http200 ok:false -> Smartlead's message surfaced",
         "Invalid subsequence" in str(resp.get("error")), resp)
    check("subsequence http200 ok:false -> flag NOT patched",
         sb.queue[0].get("added_to_subsequence") is False, sb.queue[0])


def test_subsequence_failure_smartlead_error_returns_502_flag_untouched():
    sb, http = fresh_setter()
    _subsequence_fixture(sb, http)
    http.subsequence_push_result = {"success": False, "message": "Internal Server Error"}
    sb.queue.append({"id": 602, "workspace": "navreo", "smartlead_campaign_id": 3591996,
                     "lead_email": "lead@x.com", "smartlead_lead_id": 42, "message_id": "m2",
                     "status": "needs_review", "added_to_subsequence": False})

    status, resp = setter.route_queue_action({"id": 602, "action": "subsequence", "checked": True})

    check("subsequence failure: Smartlead error -> 502", status == 502, (status, resp))
    check("subsequence failure: checkbox-facing error string is Smartlead's own message",
         resp.get("error") == "Internal Server Error", resp)
    check("subsequence failure: added_to_subsequence is false in the response",
         resp.get("added_to_subsequence") is False, resp)
    check("subsequence failure: flag NOT patched in the queue row",
         sb.queue[0].get("added_to_subsequence") is False, sb.queue[0])


def test_subsequence_failure_lead_not_found_never_pushes():
    sb, http = fresh_setter()
    # A subsequence exists, but the lead isn't in the campaign's leads listing.
    http.all_campaigns = [{"id": 3633403, "name": "Meeting Request", "status": "ACTIVE",
                           "parent_campaign_id": 3591996}]
    http.campaign_leads_by_campaign["3591996"] = []
    sb.queue.append({"id": 603, "workspace": "navreo", "smartlead_campaign_id": 3591996,
                     "lead_email": "ghost@x.com", "smartlead_lead_id": 999, "message_id": "m3",
                     "status": "needs_review", "added_to_subsequence": False})

    status, resp = setter.route_queue_action({"id": 603, "action": "subsequence", "checked": True})

    check("subsequence failure (lead not found): 502", status == 502, (status, resp))
    check("subsequence failure (lead not found): honest error, not a stack trace",
         "couldn't find" in (resp.get("error") or "").lower(), resp)
    check("subsequence failure (lead not found): the push endpoint was never called",
         http.subsequence_push_calls == [], http.subsequence_push_calls)
    check("subsequence failure (lead not found): flag NOT patched",
         sb.queue[0].get("added_to_subsequence") is False, sb.queue[0])


def test_subsequence_no_queue_row_route_resolves_by_email_and_pushes():
    sb, http = fresh_setter()
    # This route never has a smartlead_lead_id to work with (no queue row) -
    # resolution must fall back to matching by email alone.
    _subsequence_fixture(sb, http, email="standalone@x.com", lead_id=None, map_id=555111)

    status, resp = setter.route_subsequence_push({"campaign_id": 3591996, "email": "standalone@x.com"})

    check("no-queue-row push: 200 status", status == 200, (status, resp))
    check("no-queue-row push: added_to_subsequence=true in response", resp.get("added_to_subsequence") is True, resp)
    check("no-queue-row push: resolved subsequence id", resp.get("subsequence_id") == 3633403, resp)
    check("no-queue-row push: exactly one live push POST fired", len(http.subsequence_push_calls) == 1,
         http.subsequence_push_calls)
    check("no-queue-row push: resolved by email lands the right map id",
         http.subsequence_push_calls[0].get("email_lead_map_id") == 555111, http.subsequence_push_calls[0])
    check("no-queue-row push: missing campaign_id/email -> 400, not a crash",
         setter.route_subsequence_push({"email": "x@y.com"})[0] == 400)


def test_subsequence_uncheck_makes_no_smartlead_call():
    sb, http = fresh_setter()
    _subsequence_fixture(sb, http)
    sb.queue.append({"id": 604, "workspace": "navreo", "smartlead_campaign_id": 3591996,
                     "lead_email": "lead@x.com", "smartlead_lead_id": 42, "message_id": "m4",
                     "status": "needs_review", "added_to_subsequence": True})

    status, resp = setter.route_queue_action({"id": 604, "action": "subsequence", "checked": False})

    check("subsequence uncheck: 200 status", status == 200, (status, resp))
    check("subsequence uncheck: added_to_subsequence cleared in response",
         resp.get("added_to_subsequence") is False, resp)
    check("subsequence uncheck: zero Smartlead HTTP calls of any kind",
         http.smartlead_calls == [], http.smartlead_calls)
    check("subsequence uncheck: flag cleared in the queue row",
         sb.queue[0].get("added_to_subsequence") is False, sb.queue[0])


def test_subsequence_ambiguous_multiple_subsequences_needs_override():
    sb, http = fresh_setter()
    http.all_campaigns = [
        {"id": 1001, "name": "Meeting Request", "status": "ACTIVE", "parent_campaign_id": 3591996},
        {"id": 1002, "name": "Interested Reply", "status": "ACTIVE", "parent_campaign_id": 3591996},
    ]
    http.campaign_leads_by_campaign["3591996"] = [
        {"campaign_lead_map_id": 42424242, "status": "INPROGRESS",
         "lead": {"id": 42, "email": "lead@x.com"}},
    ]
    sb.queue.append({"id": 605, "workspace": "navreo", "smartlead_campaign_id": 3591996,
                     "lead_email": "lead@x.com", "smartlead_lead_id": 42, "message_id": "m5",
                     "status": "needs_review", "added_to_subsequence": False})

    status, resp = setter.route_queue_action({"id": 605, "action": "subsequence", "checked": True})
    check("subsequence ambiguous: two subsequences with no override -> 400",
         status == 400, (status, resp))
    check("subsequence ambiguous: both candidates surfaced for a picker",
         {s["id"] for s in resp.get("subsequences", [])} == {1001, 1002}, resp)
    check("subsequence ambiguous: nothing pushed to Smartlead", http.subsequence_push_calls == [])

    # An explicit override skips resolution entirely and pushes straight through.
    status2, resp2 = setter.route_queue_action({"id": 605, "action": "subsequence", "checked": True,
                                                 "sub_sequence_id": 1002})
    check("subsequence override: explicit sub_sequence_id succeeds", status2 == 200, (status2, resp2))
    check("subsequence override: pushes to the requested subsequence, not the other one",
         resp2.get("subsequence_id") == 1002, resp2)


def test_claim_race_returns_existing_row_without_classifying():
    """Two intake paths (the webhook and the poll) can race on the same reply.
    process_reply's own dedupe check can find nothing (nobody has claimed the
    reply yet) and still lose the race a moment later at the claim insert, if
    the other claimant gets there first. ClaimRaceSB plants the "winner" row
    exactly when the claim insert fires, forcing that insert to report a lost
    claim (an empty list, like Postgres would for a conflicting
    ignore-duplicates insert)."""
    inner_sb = FakeSB()
    racing_sb = ClaimRaceSB(inner_sb)
    http = FakeHTTP()
    classify_calls = []
    http.classify_fn = lambda body: classify_calls.append(body) or {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.99, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "", "rationale": "",
    }
    setter.configure(sb=racing_sb, http_json=http, keys={"OPENAI_API_KEY": "x", "SMARTLEAD_API_KEY": "y"},
                     log_activity=lambda *a, **k: None)

    agent = {"id": "agent-race0001", "mode": "autopilot", "enabled": True,
             "allowed_intents": ["send_resource"], "pricing_notes": "x", "confidence_threshold": 0.9}
    reply = {"workspace": "navreo", "campaign_id": 555, "email": "race@example.com", "message_id": "m-race",
             "body": "sure, send it", "subject": "Re: hi", "replied_at": "2026-07-10T00:00:00+00:00", "is_test": False}

    row = setter.process_reply(reply, agent, {})

    check("claim race: classify() is never invoked when another claimant wins the race",
         classify_calls == [], classify_calls)
    check("claim race: process_reply returns the other claimant's row, not a fresh one",
         racing_sb.winner_row is not None and row.get("id") == racing_sb.winner_row.get("id"), row)
    check("claim race: exactly one row ends up in the queue", len(inner_sb.queue) == 1, len(inner_sb.queue))


# ── intake dedupe: source_message_id + percent-encoding ─────────────────────

def test_existing_row_percent_encodes_plus_in_keys():
    sb, http = fresh_setter()
    sb.queue.append({"id": 9101, "workspace": "navreo", "smartlead_campaign_id": 700,
                     "lead_email": "plus@example.com", "message_id": "123-2026-07-08T13:16:23+00:00",
                     "status": "needs_review"})
    row = setter._existing_row("navreo", 700, "plus@example.com", "123-2026-07-08T13:16:23+00:00")
    check("_existing_row: a message id containing '+' still matches (value percent-encoded)",
         bool(row) and row.get("id") == 9101, row)
    gets = [p for m, p, *_ in sb.calls if m == "GET" and p.startswith(setter.QUEUE_TABLE)]
    check("_existing_row: no raw '+' ever reaches the query string (PostgREST reads it as a space)",
         bool(gets) and all("+" not in g for g in gets), gets)


def test_existing_row_falls_back_to_source_message_id():
    sb, http = fresh_setter()
    sb.queue.append({"id": 9102, "workspace": "navreo", "smartlead_campaign_id": 700,
                     "lead_email": "swap@example.com", "message_id": "<real-rfc-id@mail.example>",
                     "source_message_id": "999-2026-07-08T13:16:23+00:00", "status": "no_action"})
    row = setter._existing_row("navreo", 700, "swap@example.com", "999-2026-07-08T13:16:23+00:00")
    check("_existing_row: a row whose message_id was hydration-swapped is still found via source_message_id",
         bool(row) and row.get("id") == 9102, row)


def test_run_poll_skips_reply_already_queued_under_swapped_mid():
    sb, http = fresh_setter()
    agent = {"id": "agent-dedupe01", "mode": "draft_only", "enabled": True, "campaign_ids": [700],
             "allowed_intents": ["send_resource"], "pricing_notes": ""}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 700, "email": "swap@example.com",
        "subject": "Re: hi", "reply_body": "sure, send it", "replied_at": "2026-07-10T00:00:00+00:00",
        "smartlead_message_id": "999-2026-07-10T00:00:00+00:00", "category": "Interested",
    })
    sb.queue.append({"id": 9103, "workspace": "navreo", "smartlead_campaign_id": 700,
                     "lead_email": "swap@example.com", "message_id": "<real@mail.example>",
                     "source_message_id": "999-2026-07-10T00:00:00+00:00", "status": "needs_review"})
    summary = setter.run_poll()
    check("run_poll: a reply whose queue row carries the hydration-swapped mid is NOT re-intaken",
         summary.get("checked") == 0 and len(sb.queue) == 1, (summary, len(sb.queue)))


def test_claim_rows_carry_source_message_id():
    sb, http = fresh_setter()
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.5, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants info", "rationale": "",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Sam"}
    agent = {"id": "agent-dedupe02", "mode": "draft_only", "enabled": True, "campaign_ids": [700],
             "allowed_intents": ["send_resource"], "pricing_notes": ""}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 700, "email": "fresh@example.com",
        "subject": "Re: hi", "reply_body": "sure, send it", "replied_at": "2026-07-10T00:00:00+00:00",
        "smartlead_message_id": "777-2026-07-10T00:00:00+00:00", "category": "Interested",
    })
    setter.run_poll()
    srcs = [r.get("source_message_id") for r in sb.queue]
    check("intake: the claimed row preserves the intake key in source_message_id",
         srcs == ["777-2026-07-10T00:00:00+00:00"], srcs)


# ── hydrate_lead: answered_since_reply ───────────────────────────────────────

def test_hydrate_lead_answered_since_reply():
    sb, http = fresh_setter()
    http.message_history = [
        {"type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi", "email_body": "sure",
         "message_id": "m-ans-1", "stats_id": "st-ans-1"},
        {"type": "SENT", "time": "2026-07-10T10:00:00+00:00", "subject": "Re: hi", "email_body": "a person replied",
         "from_name": "Bjion Henry"},
    ]
    ok, hyd, err = setter.hydrate_lead(111, "person@example.com", "m-ans-1")
    check("hydrate_lead: finds the target reply", ok, err)
    check("hydrate_lead: answered_since_reply true when a SENT message follows the reply's time",
         hyd.get("answered_since_reply") is True, hyd)

    http.message_history = [
        {"type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi", "email_body": "sure",
         "message_id": "m-ans-2", "stats_id": "st-ans-2"},
    ]
    ok2, hyd2, err2 = setter.hydrate_lead(111, "person2@example.com", "m-ans-2")
    check("hydrate_lead: finds the target reply (no later SENT)", ok2, err2)
    check("hydrate_lead: answered_since_reply false when nothing followed",
         hyd2.get("answered_since_reply") is False, hyd2)


# ── unknown timezone still builds tentative slots, decide() still vetoes ────

def _future_weekday_avail(count=6):
    """ISO8601 UTC slot times on the next `count` weekdays, at UTC hours (11,
    14) so they land inside Europe/London's 9am-5pm window regardless of BST -
    drives get_calendly_availability()'s fake HTTP for pipeline tests that
    need slot_status to actually resolve to "ok"."""
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    d = now.date()
    added = 0
    while added < count:
        d = d + dt.timedelta(days=1)
        if d.weekday() < 5:
            for hour in (11, 14):
                out.append(dt.datetime(d.year, d.month, d.day, hour, 0, tzinfo=dt.timezone.utc).isoformat())
            added += 1
    return out


def test_tz_none_calendly_fallback_no_slots_but_auto_sends():
    """Owner ruling 2026-07-14: an unresolved timezone alone no longer holds
    the reply for review. slot_status still resolves to "tz_unknown" and NO
    real call times are ever fabricated for an unknown timezone (that part
    is unchanged - see the assertions below) - but decide()'s gate 7 now
    treats "no real times available for any reason" as calendly-fallback
    mode, where timezone risk is zero because no time is being proposed at
    all. A simple send_resource ask with everything else green now
    auto-sends instead of holding (previously: test_tz_none_still_builds_
    tentative_slots_but_vetoes_auto asserted review here)."""
    sb, http = fresh_setter()
    http.calendly_avail = _future_weekday_avail()
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "Sure, send it over, thanks", "message_id": "m-tzNone", "stats_id": "st-tzNone",
    }]
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.99, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants the resource", "rationale": "unqualified yes",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                               "html": '<div>Hi Test,</div><br><div><a href="https://x.example/r">'
                                       'Here it is</a>.</div><br><div>Sam</div>'}

    agent = {
        "id": "agent-tzNone01", "mode": "autopilot", "enabled": True, "campaign_ids": [909],
        "allowed_intents": ["send_resource", "pricing", "scheduling"],
        "instructions": "Resource: The guide - https://x.example/r - send when they want more info.",
        "confidence_threshold": 0.9, "resource_link": "https://x.example/r",
        "calendly_event_url": "https://calendly.com/navreo/book-a-call-with-us-clone-2",
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    settings = {"autopilot_enabled": True, "calendly_token": "tok123"}
    reply = {
        "workspace": "navreo", "campaign_id": 909, "email": "there@example.org",
        "first_name": "There", "message_id": "m-tzNone",
        "body": "Sure, send it over, thanks", "subject": "Re: hi",
        "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False,
    }
    row = setter.process_reply(reply, agent, settings)

    check("tz-none: timezone stays unresolved", row.get("timezone") is None, row.get("timezone"))
    check("tz-none: NO slots are fabricated when the timezone is unknown (never a London default)",
         len(row.get("slots") or []) == 0, row.get("slots"))
    check("tz-none: no draft slot uses a Europe/London zone abbreviation",
         not any((s.get("label") or "")[-3:] in ("GMT", "BST") for s in (row.get("slots") or [])), row.get("slots"))
    check("tz-none: calendly fallback (owner ruling 2026-07-14) - unresolved timezone no longer holds",
         row.get("decision") == "auto_send", row)


def test_tz_guessed_low_confidence_shows_local_times_but_holds():
    # A weak educated guess (e.g. US company, no hard signal): the draft should
    # show plausible LOCAL times, but the decision must still HOLD - never
    # auto-send at a possibly-wrong hour.
    sb, http = fresh_setter()
    http.calendly_avail = _future_weekday_avail()
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "Sure, send it over", "message_id": "m-tzLo", "stats_id": "st-tzLo",
    }]
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.99, "red_flags": [], "timezone_guess": "America/New_York", "tz_confidence": 0.4,
        "wants": "wants the resource", "rationale": "US company guess",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                               "html": 'Hi There, <a href="https://x.example/r">Here it is</a>. Best, Sam'}
    agent = {
        "id": "agent-tzLo01", "mode": "autopilot", "enabled": True, "campaign_ids": [909],
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "pricing_notes": "x",
        "confidence_threshold": 0.9, "resource_link": "https://x.example/r",
        "calendly_event_url": "https://calendly.com/navreo/book-a-call-with-us-clone-2",
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    settings = {"autopilot_enabled": True, "calendly_token": "tok123"}
    reply = {"workspace": "navreo", "campaign_id": 909, "email": "there@nofraud.com",
             "first_name": "There", "message_id": "m-tzLo", "body": "Sure, send it over", "subject": "Re: hi",
             "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False}
    row = setter.process_reply(reply, agent, settings)
    check("tz-guess-low: timezone is the guessed zone", row.get("timezone") == "America/New_York", row.get("timezone"))
    check("tz-guess-low: local slots ARE built for the reviewer to see", len(row.get("slots") or []) > 0, row.get("slots"))
    check("tz-guess-low: held, not auto-sent", row.get("decision") == "review", row.get("decision"))
    check("tz-guess-low: reason is the confidence gate",
         "not sure enough of the lead's timezone" in (row.get("decision_reason") or ""), row.get("decision_reason"))


def test_tz_confidence_gate_in_decide():
    # A guessed timezone that isn't confident holds; a confident one is eligible.
    d_lo, r_lo = setter.decide(_cls("send_resource"),
                              AGENT_AUTO, {**CTX_ALL_GOOD, "timezone": "America/New_York", "tz_confident": False})
    check("tz-decide: low-confidence timezone holds", d_lo == "review", (d_lo, r_lo))
    check("tz-decide: hold reason is the confidence gate",
         "not sure enough of the lead's timezone" in r_lo, r_lo)
    d_hi, r_hi = setter.decide(_cls("send_resource"),
                              AGENT_AUTO, {**CTX_ALL_GOOD, "timezone": "America/New_York", "tz_confident": True})
    check("tz-decide: confident guess is eligible to auto-send", d_hi == "auto_send", (d_hi, r_hi))


def test_process_reply_calendly_not_connected_scheduling_ask_auto_sends():
    """End-to-end (owner ruling 2026-07-14): a flexible scheduling ask, with
    a confidently-resolved timezone but NO Calendly token configured
    (slot_status resolves to "not_configured"), no longer holds for review -
    the fallback draft ("When would be a good time for us to talk? Here is
    my availability", hyperlinked to the booking link) auto-sends because
    every other gate passes."""
    sb, http = fresh_setter()
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "Happy to chat, whenever suits you next week", "message_id": "m-fb1", "stats_id": "st-fb1",
    }]
    http.classify_fn = lambda _b: {
        "primary_intent": "scheduling", "all_intents": ["scheduling"], "simple_ask": True,
        "confidence": 0.97, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants to book a call", "rationale": "flexible on timing",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                               "html": ('<div>Hi Test,</div><br><div>When would be a good time for us to talk? '
                                        'Here is <a href="https://calendly.com/navreo/book-a-call">my availability'
                                        '</a>.</div><br><div>Bjion</div>')}
    agent = {
        "id": "agent-fallback01", "mode": "autopilot", "enabled": True, "campaign_ids": [909],
        "allowed_intents": ["send_resource", "pricing", "scheduling"],
        "confidence_threshold": 0.9, "calendly_event_url": "https://calendly.com/navreo/book-a-call",
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    settings = {"autopilot_enabled": True}  # no calendly_token -> get_calendly_availability returns not_configured
    reply = {
        "workspace": "navreo", "campaign_id": 909, "email": "there@example.co.uk",
        "first_name": "There", "message_id": "m-fb1", "body": "Happy to chat, whenever suits you next week",
        "subject": "Re: hi", "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False,
    }
    row = setter.process_reply(reply, agent, settings)

    check("calendly fallback: timezone resolved confidently from the .co.uk domain",
         row.get("timezone") == "Europe/London", row.get("timezone"))
    check("calendly fallback: slot_status resolves to not_configured (no token), not held on it",
         row.get("slots") == [], row.get("slots"))
    check("calendly fallback: decision is auto_send, not held for a Calendly-down reason",
         row.get("decision") == "auto_send", (row.get("decision"), row.get("decision_reason")))


# ── handle_inbound: Smartlead EMAIL_REPLY webhook -> pipeline ───────────────

def test_handle_inbound_field_mapping():
    sb, http = fresh_setter()
    agent = {"id": "agent-wh0001", "mode": "draft_only", "enabled": True, "campaign_ids": [777]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    # handle_inbound now looks the reply up in `replies` for the verified
    # Make category rather than trusting the webhook's own lead_category -
    # this row is what makes the gate pass so field mapping can be checked.
    sb.replies.append({"workspace": "navreo", "smartlead_campaign_id": 777,
                       "smartlead_message_id": "wh-msg-1", "category": "Interested"})

    captured = {}
    real_process_reply = setter.process_reply

    def spy_process_reply(reply, agent_, settings_):
        captured["reply"] = reply
        return {"status": "needs_review", "id": 1}

    setter.process_reply = spy_process_reply
    try:
        payload = {
            "event_type": "EMAIL_REPLY", "campaign_id": 777,
            "sl_lead_email": "Inbound@Example.com",
            "lead_data": {"first_name": "Jamie", "last_name": "Doe", "email": "inbound@example.com"},
            "subject": "Re: our outreach",
            "reply_message": {"text": "Sure, send it over!", "message_id": "wh-msg-1",
                              "time": "2026-07-10T12:00:00+00:00"},
        }
        resp = setter.handle_inbound(payload)
    finally:
        setter.process_reply = real_process_reply

    check("handle_inbound: well-formed payload is marked processed", resp.get("processed") is True, resp)
    check("handle_inbound: status/id pass through from process_reply's row",
         resp.get("status") == "needs_review" and resp.get("id") == 1, resp)

    r = captured.get("reply") or {}
    check("handle_inbound: body mapped from reply_message.text", r.get("body") == "Sure, send it over!", r.get("body"))
    check("handle_inbound: keys the reply on the webhook's message id", r.get("message_id") == "wh-msg-1", r.get("message_id"))
    check("handle_inbound: lead email lower-cased", r.get("email") == "inbound@example.com", r.get("email"))
    check("handle_inbound: campaign id mapped through", r.get("campaign_id") == 777, r.get("campaign_id"))
    check("handle_inbound: first/last name mapped from lead_data",
         (r.get("first_name"), r.get("last_name")) == ("Jamie", "Doe"), r)


def test_handle_inbound_non_reply_event_ignored():
    sb, http = fresh_setter()
    resp = setter.handle_inbound({"event_type": "EMAIL_SENT", "campaign_id": 1, "sl_lead_email": "a@b.com",
                                  "reply_message": {"text": "hi", "message_id": "m1"}})
    check("handle_inbound: non-reply event type is ignored", "ignored" in resp, resp)


def test_handle_inbound_missing_message_id_ignored():
    sb, http = fresh_setter()
    agent = {"id": "agent-wh0002", "mode": "draft_only", "enabled": True, "campaign_ids": [888]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    payload = {"event_type": "EMAIL_REPLY", "campaign_id": 888, "sl_lead_email": "a@b.com",
              "reply_message": {"text": "hi"}}  # no message id anywhere in the payload
    resp = setter.handle_inbound(payload)
    check("handle_inbound: missing message id is ignored (left for the poll sweep)", "ignored" in resp, resp)


def test_handle_inbound_unassigned_campaign_ignored():
    sb, http = fresh_setter()  # no agents registered at all
    payload = {"event_type": "EMAIL_REPLY", "campaign_id": 999, "sl_lead_email": "a@b.com",
              "reply_message": {"text": "hi", "message_id": "m1"}}
    resp = setter.handle_inbound(payload)
    check("handle_inbound: campaign with no agent assigned is ignored", "ignored" in resp, resp)


def test_handle_inbound_missing_campaign_or_email_ignored():
    sb, http = fresh_setter()
    resp1 = setter.handle_inbound({"event_type": "EMAIL_REPLY", "sl_lead_email": "a@b.com",
                                   "reply_message": {"text": "hi", "message_id": "m1"}})  # no campaign_id
    check("handle_inbound: missing campaign id is ignored", "ignored" in resp1, resp1)
    resp2 = setter.handle_inbound({"event_type": "EMAIL_REPLY", "campaign_id": 1,
                                   "reply_message": {"text": "hi", "message_id": "m1"}})  # no email anywhere
    check("handle_inbound: missing lead email is ignored", "ignored" in resp2, resp2)


# ── ensure_webhooks: additive Smartlead EMAIL_REPLY webhook registration ────

def test_ensure_webhooks_adds_one_and_preserves_existing():
    sb, http = fresh_setter()
    cid = 321
    # a pre-existing, unrelated webhook already registered directly in Smartlead
    existing_hook = {"id": "existing-1", "webhook_url": "https://other.example/hook", "event_types": ["EMAIL_OPEN"]}
    http.webhooks_by_campaign[str(cid)] = [dict(existing_hook)]
    agent = {"id": "agent-hook0001", "campaign_ids": [cid]}

    results = setter.ensure_webhooks(agent)

    check("ensure_webhooks: reports ok for the campaign", len(results) == 1 and results[0].get("ok") is True, results)
    check("ensure_webhooks: existing_intact reported true", results[0].get("existing_intact") is True, results)

    hooks_after = http.webhooks_by_campaign[str(cid)]
    check("ensure_webhooks: adds exactly one new webhook (pre-existing + new = 2)", len(hooks_after) == 2, hooks_after)
    check("ensure_webhooks: the pre-existing webhook is byte-for-byte untouched",
         hooks_after[0] == existing_hook, hooks_after[0])
    check("ensure_webhooks: the new webhook points at /api/setter/inbound",
         "/api/setter/inbound" in (hooks_after[1].get("webhook_url") or ""), hooks_after[1])

    settings = setter._load_settings()
    check("ensure_webhooks: records the new webhook into settings.webhooks",
         str(cid) in (settings.get("webhooks") or {}), settings.get("webhooks"))


def test_ensure_webhooks_dry_run_skips():
    sb, http = fresh_setter()
    cid = 654
    agent = {"id": "agent-hook0002", "campaign_ids": [cid]}
    os.environ["SETTER_DRY_RUN"] = "1"
    try:
        results = setter.ensure_webhooks(agent)
    finally:
        os.environ.pop("SETTER_DRY_RUN", None)
    check("ensure_webhooks: dry run returns skipped without touching Smartlead",
         results == [{"campaign_id": cid, "ok": True, "skipped": "dry run"}] and http.smartlead_calls == [],
         (results, http.smartlead_calls))


def test_ensure_webhooks_second_call_is_noop():
    sb, http = fresh_setter()
    cid = 987
    agent = {"id": "agent-hook0003", "campaign_ids": [cid]}

    first = setter.ensure_webhooks(agent)
    calls_after_first = len(http.smartlead_calls)
    check("ensure_webhooks: first call registers the webhook", first == [{
        "campaign_id": cid, "ok": True, "existing_intact": True, "webhook_id": 1, "error": None,
    }], first)

    second = setter.ensure_webhooks(agent)
    check("ensure_webhooks: second call for the same campaign is a no-op 'already'",
         second == [{"campaign_id": cid, "ok": True, "already": True}], second)
    check("ensure_webhooks: second call makes no further Smartlead calls",
         len(http.smartlead_calls) == calls_after_first, (calls_after_first, len(http.smartlead_calls)))


# ── v2: instructions field (with pricing_notes fallback) ───────────────────

def test_agent_instructions_fallback():
    # a brand-new v2 doc using the `instructions` key directly
    check("_agent_instructions: reads the new `instructions` key",
         setter._agent_instructions({"instructions": "Flat $500/mo."}) == "Flat $500/mo.")

    # a legacy doc that only ever had `pricing_notes` still works unchanged
    check("_agent_instructions: falls back to legacy pricing_notes when instructions is unset",
         setter._agent_instructions({"pricing_notes": "Flat $400/mo, 2 seats."}) == "Flat $400/mo, 2 seats.")

    # instructions present but blank still falls back to pricing_notes (an
    # old doc re-saved by the v2 UI with a blank instructions box shouldn't
    # silently lose its legacy pricing answer)
    check("_agent_instructions: blank instructions still falls back to pricing_notes",
         setter._agent_instructions({"instructions": "  ", "pricing_notes": "Flat $400/mo."}) == "Flat $400/mo.")

    # instructions takes priority when both are set (a v2 re-save of an old doc)
    check("_agent_instructions: non-blank instructions wins over pricing_notes",
         setter._agent_instructions({"instructions": "New answer.", "pricing_notes": "Old answer."}) == "New answer.")

    check("_agent_instructions: neither key set -> empty string",
         setter._agent_instructions({}) == "")

    # decide()'s pricing gate: a legacy doc with only pricing_notes (no
    # `instructions` key at all) still auto-sends a pricing question
    legacy_agent = {k: v for k, v in AGENT_AUTO.items() if k != "instructions"}
    legacy_agent["pricing_notes"] = "Flat $500/mo."
    d, r = setter.decide(_cls("pricing"), legacy_agent, CTX_ALL_GOOD)
    check("decide: legacy pricing_notes-only agent still auto-sends a pricing question", d == "auto_send", r)

    # decide()'s pricing gate: the new `instructions` field alone (no
    # pricing_notes at all) also auto-sends
    v2_agent = {k: v for k, v in AGENT_AUTO.items() if k != "pricing_notes"}
    v2_agent["instructions"] = "Flat $500/mo, 3 seats included."
    d, r = setter.decide(_cls("pricing"), v2_agent, CTX_ALL_GOOD)
    check("decide: v2 instructions-only agent auto-sends a pricing question", d == "auto_send", r)

    # decide()'s pricing gate: both empty -> review, with the v2 reason text
    empty_agent = {**AGENT_AUTO, "pricing_notes": "", "instructions": ""}
    d, r = setter.decide(_cls("pricing"), empty_agent, CTX_ALL_GOOD)
    check("decide: pricing intent with no instructions and no legacy pricing_notes -> review", d == "review", r)
    check("decide: exact v2 reason text for the empty-instructions pricing gate",
         r == "Held for review: no instructions cover pricing, so a person should answer.", r)


# ── v2: booking_link derived from calendly_event_url ────────────────────────

def test_booking_link_derivation():
    check("_booking_link: derives from calendly_event_url, trailing slash stripped",
         setter._booking_link({"calendly_event_url": "https://calendly.com/navreo/book-a-call/"}) ==
         "https://calendly.com/navreo/book-a-call")

    check("_booking_link: no trailing slash to strip -> unchanged",
         setter._booking_link({"calendly_event_url": "https://calendly.com/navreo/book-a-call"}) ==
         "https://calendly.com/navreo/book-a-call")

    check("_booking_link: an explicit legacy booking_link still wins over the derived one",
         setter._booking_link({"calendly_event_url": "https://calendly.com/navreo/book-a-call",
                               "booking_link": "https://navreo.ai/book-a-call"}) == "https://navreo.ai/book-a-call")

    check("_booking_link: neither field set -> empty string", setter._booking_link({}) == "")


# ── multi-turn autonomy / persistent memory / brain duplication (2026-07-13) ─

def test_decide_multi_turn_autonomy():
    # simple, fully-allowed later-turn ask -> continues past the (weakened)
    # first-touch gate instead of always holding
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "first_touch": False})
    check("multi-turn: simple + allowed later-turn ask -> auto_send", d == "auto_send", r)

    # off-intent later-turn ask is still held - by gate 2 ("intent(s) within
    # what this agent is allowed to answer alone"), which runs UNCONDITIONALLY
    # before the first-touch gate and is never weakened
    d, r = setter.decide(_cls("bespoke_request", simple_ask=False, confidence=0.4), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "first_touch": False})
    check("multi-turn: off-intent later-turn ask -> review", d == "review", r)
    check("multi-turn: off-intent later-turn ask uses the SAME intent-not-allowed reason first-touch gets "
         "(gate 2 applies unchanged to later-turn replies)",
         r == setter._INTENT_REASON["bespoke_request"], r)

    # not-a-simple-ask later-turn is still held - by gate 3 ("simple ask +
    # confidence"), same unchanged-gate guarantee
    d, r = setter.decide(_cls("scheduling", simple_ask=False), AGENT_AUTO, {**CTX_ALL_GOOD, "first_touch": False})
    check("multi-turn: not-simple later-turn ask -> review", d == "review", r)
    check("multi-turn: not-simple later-turn ask uses the SAME confidence-gate reason first-touch gets "
         "(gate 3 applies unchanged to later-turn replies)",
         r == "Held for review: not confident enough this is a simple ask.", r)

    # answered_since_reply still blocks regardless of first_touch (checked
    # even earlier than the intent/simple-ask gates, so this was already true)
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "first_touch": False, "answered_since_reply": True})
    check("multi-turn: answered_since_reply still blocks regardless of first_touch (no_action)", d == "no_action", r)

    # a not-hydrated later-turn reply still holds too (also checked earlier)
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO,
                         {**CTX_ALL_GOOD, "first_touch": False, "hydrated": False})
    check("multi-turn: not-hydrated later-turn reply -> review", d == "review", r)

    # first_touch=True behaviour is unchanged (spot-check; test_decide_matrix
    # and test_fixtures already exercise the full first-touch matrix)
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, CTX_ALL_GOOD)
    check("multi-turn: first_touch=True + simple/allowed still auto_sends, unchanged", d == "auto_send", r)
    d, r = setter.decide(_cls("bespoke_request", simple_ask=False, confidence=0.4), AGENT_AUTO, CTX_ALL_GOOD)
    check("multi-turn: first_touch=True + off-intent still reviews, unchanged", d == "review", r)


def test_draft_reply_thread_continuity():
    """draft_reply() must pass recent thread text through to the model
    (stripped of HTML tags) when the caller supplies it, and must add NO new
    key at all when it doesn't - so a first-touch draft (which has nothing to
    pass here in the older call sites) stays byte-identical."""
    sb, http = fresh_setter()
    draft_calls = []
    http.draft_fn = lambda body: draft_calls.append(body) or {"subject": "Re: hi", "html": "Hi There, thanks. Best, Sam"}
    agent = {"id": "agent-thread01", "resource_link": "https://x.example/r"}
    classification = {"primary_intent": "send_resource", "all_intents": ["send_resource"], "wants": "wants info"}

    setter.draft_reply(
        {"first_name": "There", "subject": "Re: hi", "body": "sure",
         "thread_text": "Hi, following up on this <br> Sure, sounds good"},
        agent, classification, [], "not_configured", "Sam")
    payload = json.loads(draft_calls[-1]["messages"][1]["content"])
    check("draft_reply: thread text reaches the model as recent_thread",
         "following up" in payload.get("recent_thread", ""), payload.get("recent_thread"))
    check("draft_reply: recent_thread has HTML tags stripped",
         "<br>" not in payload.get("recent_thread", ""), payload.get("recent_thread"))

    setter.draft_reply(
        {"first_name": "There", "subject": "Re: hi", "body": "sure"},
        agent, classification, [], "not_configured", "Sam")
    payload2 = json.loads(draft_calls[-1]["messages"][1]["content"])
    check("draft_reply: no thread_text given -> no recent_thread key at all (byte-identical to before this feature)",
         "recent_thread" not in payload2, payload2)


def test_memory_digest_reaches_classify_and_draft():
    """Feature 1: agent['memory'] must be fed into EVERY live pipeline pass -
    classify()'s owner_hints and draft_reply()'s regen_feedback - with no
    extra work by the caller (process_reply builds the digest itself)."""
    sb, http = fresh_setter()
    captured = {}
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "sure, send it over", "message_id": "m-mem1", "stats_id": "st-mem1",
    }]

    def classify_fn(body):
        captured["classify_body"] = body
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.98, "red_flags": [], "timezone_guess": "Europe/London", "tz_confidence": 0.9,
            "wants": "wants the resource", "rationale": "unqualified yes",
        }

    def draft_fn(body):
        captured["draft_body"] = body
        return {"subject": "Re: hi", "html": 'Hi There, <a href="https://x.example/r">Here it is</a>. Best, Sam'}

    http.classify_fn = classify_fn
    http.draft_fn = draft_fn

    agent = {
        "id": "agent-mem0001", "mode": "draft_only", "enabled": True, "campaign_ids": [501],
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "pricing_notes": "x",
        "confidence_threshold": 0.9, "resource_link": "https://x.example/r",
        "memory": [
            {"text": "Always mention the free trial.", "source": "manual", "scope": "remember",
             "at": "2026-07-01T00:00:00+00:00"},
            {"text": "Never promise a specific onboarding date.", "source": "q-1", "scope": "remember",
             "at": "2026-07-05T00:00:00+00:00"},
        ],
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    reply = {"workspace": "navreo", "campaign_id": 501, "email": "mem@example.com",
             "first_name": "There", "message_id": "m-mem1", "body": "sure, send it over",
             "subject": "Re: hi", "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False}
    row = setter.process_reply(reply, agent, {})

    classify_payload = json.loads(captured["classify_body"]["messages"][1]["content"])
    draft_payload = json.loads(captured["draft_body"]["messages"][1]["content"])
    check("memory digest: reaches classify() as owner_corrections",
         "Never promise a specific onboarding date." in classify_payload.get("owner_corrections", ""),
         classify_payload.get("owner_corrections"))
    check("memory digest: reaches draft_reply() as reviewer_feedback",
         "Never promise a specific onboarding date." in draft_payload.get("reviewer_feedback", ""),
         draft_payload.get("reviewer_feedback"))
    check("memory digest: newest-first ordering",
         classify_payload["owner_corrections"].index("Never promise") <
         classify_payload["owner_corrections"].index("Always mention"),
         classify_payload["owner_corrections"])
    check("memory digest: process_reply still returns a normal row",
         row.get("status") in ("needs_review", "auto_sent", "sent", "no_action"), row)


def test_memory_digest_empty_is_byte_identical():
    """An agent with no memory must send NO owner_corrections/reviewer_feedback
    key at all - not an empty-string key - matching pre-feature behaviour."""
    sb, http = fresh_setter()
    captured = {}
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "sure, send it over", "message_id": "m-mem2", "stats_id": "st-mem2",
    }]

    def classify_fn(body):
        captured["classify_body"] = body
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.98, "red_flags": [], "timezone_guess": "Europe/London", "tz_confidence": 0.9,
            "wants": "wants the resource", "rationale": "unqualified yes",
        }

    def draft_fn(body):
        captured["draft_body"] = body
        return {"subject": "Re: hi", "html": 'Hi There, <a href="https://x.example/r">Here it is</a>. Best, Sam'}

    http.classify_fn = classify_fn
    http.draft_fn = draft_fn

    agent = {
        "id": "agent-mem0002", "mode": "draft_only", "enabled": True, "campaign_ids": [502],
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "pricing_notes": "x",
        "confidence_threshold": 0.9, "resource_link": "https://x.example/r", "memory": [],
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    reply = {"workspace": "navreo", "campaign_id": 502, "email": "nomem@example.com",
             "first_name": "There", "message_id": "m-mem2", "body": "sure, send it over",
             "subject": "Re: hi", "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False}
    setter.process_reply(reply, agent, {})

    classify_payload = json.loads(captured["classify_body"]["messages"][1]["content"])
    draft_payload = json.loads(captured["draft_body"]["messages"][1]["content"])
    check("memory digest empty: no owner_corrections key sent to classify()",
         "owner_corrections" not in classify_payload, classify_payload)
    check("memory digest empty: no reviewer_feedback key sent to draft_reply()",
         "reviewer_feedback" not in draft_payload, draft_payload)


# ── instructions merge (Feature A, owner ruling 2026-07-14) ─────────────────
# A "remember" correction is no longer appended to a separate memory list -
# it is merged straight into the agent's own instructions text, the single
# living manual every classify()/draft_reply() call already reads in full.

def test_merge_correction_into_instructions_success_and_fallbacks():
    sb, http = fresh_setter()
    agent = {"id": "agent-merge0001", "name": "Ada",
             "instructions": "Resource: The guide - https://x.example/guide - send on request. "
                             "Pricing: flat $500/mo."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    # Success path: the model rewrites the manual, keeping every existing URL.
    http.merge_fn = lambda body: {
        "instructions": "Resource: The guide - https://x.example/guide - send on request. "
                        "Pricing: flat $500/mo, no setup fee for referrals. "
                        "Never offer a discount over email."
    }
    ok, new_instructions, detail = setter.merge_correction_into_instructions(
        agent, "Never offer a discount over email.", source="manual")
    check("merge success: ok is True", ok, (ok, new_instructions, detail))
    check("merge success: detail is merged", detail == "merged", detail)
    check("merge success: instructions actually rewritten",
         "Never offer a discount over email." in new_instructions, new_instructions)
    check("merge success: the original resource URL survives",
         "https://x.example/guide" in new_instructions, new_instructions)

    saved = setter._load_agent(agent["id"])
    check("merge success: saved doc's instructions match what was returned",
         saved.get("instructions") == new_instructions, saved.get("instructions"))
    check("merge success: instruction_edits logged how=merged",
         len(saved.get("instruction_edits") or []) == 1 and saved["instruction_edits"][0]["how"] == "merged",
         saved.get("instruction_edits"))
    check("merge success: instruction_edits carries the note verbatim",
         saved["instruction_edits"][0]["note"] == "Never offer a discount over email.",
         saved.get("instruction_edits"))
    check("merge success: agent memory is untouched (nothing writes memory any more)",
         (saved.get("memory") or []) == [], saved.get("memory"))

    # URL-drop: the model's rewrite silently loses the existing resource link
    # -> falls back to a dumb, always-safe append instead of trusting it.
    agent2 = {"id": "agent-merge0002", "name": "Ada",
             "instructions": "Resource: The guide - https://x.example/guide - send on request."}
    sb.agents[agent2["id"]] = {"id": agent2["id"], "doc": agent2}
    http.merge_fn = lambda body: {"instructions": "Resource: the guide is available on request. "
                                                  "Never offer a discount over email."}
    ok2, new_instructions2, detail2 = setter.merge_correction_into_instructions(
        agent2, "Never offer a discount over email.")
    check("merge URL-drop: falls back to append", detail2 == "appended", detail2)
    check("merge URL-drop: old text is preserved verbatim at the start",
         new_instructions2.startswith(agent2["instructions"]), new_instructions2)
    check("merge URL-drop: the note is appended as a dated Training note line",
         "Training note (" in new_instructions2 and "Never offer a discount over email." in new_instructions2,
         new_instructions2)
    saved2 = setter._load_agent(agent2["id"])
    check("merge URL-drop: instruction_edits logged how=appended",
         saved2["instruction_edits"][0]["how"] == "appended", saved2.get("instruction_edits"))

    # Empty LLM response (schema returned {}  ->  instructions "") -> the
    # same append fallback, never an empty/blank instructions text.
    agent3 = {"id": "agent-merge0003", "name": "Ada", "instructions": "Flat $200/mo."}
    sb.agents[agent3["id"]] = {"id": agent3["id"], "doc": agent3}
    http.merge_fn = None  # default FakeHTTP response is {"instructions": ""}
    ok3, new_instructions3, detail3 = setter.merge_correction_into_instructions(agent3, "Always mention the trial.")
    check("merge empty response: falls back to append", ok3 and detail3 == "appended", (ok3, detail3))
    check("merge empty response: old text preserved, note appended",
         new_instructions3.startswith("Flat $200/mo.") and "Always mention the trial." in new_instructions3,
         new_instructions3)

    # No agent id at all -> never crashes, reports failure honestly.
    ok4, new_instructions4, detail4 = setter.merge_correction_into_instructions({}, "some note")
    check("merge no agent id: ok is False", ok4 is False, (ok4, new_instructions4, detail4))

    # Blank note -> no-op, instructions returned unchanged.
    ok5, new_instructions5, detail5 = setter.merge_correction_into_instructions(agent3, "   ")
    check("merge blank note: no-op, original instructions returned unchanged",
         ok5 and new_instructions5 == "Flat $200/mo.", (ok5, new_instructions5, detail5))


def test_correction_one_off_does_not_touch_memory():
    sb, http = fresh_setter()
    agent = {"id": "agent-corr0001", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"],
             "memory": [{"text": "existing memory", "source": "manual", "scope": "remember",
                        "at": "2026-07-01T00:00:00+00:00"}]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    before_digest = setter._agent_memory_digest(setter._load_agent(agent["id"]))
    status, resp = setter.route_agents_correction(
        {"agent_id": agent["id"], "text": "typo in the resource link", "scope": "one_off"})
    check("correction one_off: returns 200", status == 200, (status, resp))
    check("correction one_off: response reports feedback_log_count 1", resp.get("feedback_log_count") == 1, resp)
    check("correction one_off: response reports memory_count 1 (unchanged)", resp.get("memory_count") == 1, resp)

    saved = setter._load_agent(agent["id"])
    check("correction one_off: feedback_log grew by one", len(saved.get("feedback_log") or []) == 1,
         saved.get("feedback_log"))
    check("correction one_off: memory is unchanged", saved.get("memory") == agent["memory"], saved.get("memory"))
    after_digest = setter._agent_memory_digest(saved)
    check("correction one_off: memory digest is unchanged", after_digest == before_digest,
         (before_digest, after_digest))
    check("correction one_off: feedback_log text stored verbatim",
         saved["feedback_log"][0]["text"] == "typo in the resource link", saved["feedback_log"])


def test_correction_remember_route_merges_instructions():
    """Owner ruling 2026-07-14: scope="remember" now merges into the agent's
    instructions text (the single living manual) instead of growing
    agent['memory']."""
    sb, http = fresh_setter()
    agent = {"id": "agent-corr0002", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"],
             "instructions": "Flat $500/mo."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    http.merge_fn = None  # default fallback (append) - no LLM shape needed for this test

    status, resp = setter.route_agents_correction(
        {"agent_id": agent["id"], "text": "Always offer the case study.", "scope": "remember", "source": "manual"})
    check("correction remember: returns 200", status == 200, (status, resp))
    check("correction remember: response reports how", resp.get("how") in ("merged", "appended"), resp)
    check("correction remember: response reports instruction_edits_count 1", resp.get("instruction_edits_count") == 1,
         resp)

    saved = setter._load_agent(agent["id"])
    check("correction remember: memory is NOT touched (nothing writes memory any more)",
         (saved.get("memory") or []) == [], saved.get("memory"))
    check("correction remember: feedback_log untouched (empty)", (saved.get("feedback_log") or []) == [],
         saved.get("feedback_log"))
    check("correction remember: instructions actually changed and contain the correction",
         "Always offer the case study." in saved.get("instructions", ""), saved.get("instructions"))
    check("correction remember: original instructions text is preserved",
         "Flat $500/mo." in saved.get("instructions", ""), saved.get("instructions"))
    check("correction remember: instruction_edits grew by one, how=appended (default FakeHTTP merge_fn)",
         len(saved.get("instruction_edits") or []) == 1 and saved["instruction_edits"][0]["how"] == "appended",
         saved.get("instruction_edits"))

    status2, resp2 = setter.route_agents_correction(
        {"agent_id": "agent-doesnotexist", "text": "x", "scope": "remember"})
    check("correction: unknown agent -> 404", status2 == 404, (status2, resp2))

    status3, resp3 = setter.route_agents_correction({"agent_id": agent["id"], "text": "  ", "scope": "remember"})
    check("correction: blank text -> 400", status3 == 400, (status3, resp3))

    status4, resp4 = setter.route_agents_correction({"agent_id": agent["id"], "scope": "remember"})
    check("correction: missing agent_id on an otherwise-valid call still requires text -> 400",
         status4 == 400, (status4, resp4))


def test_agents_memory_delete():
    """The training page's memory viewer: a remembered lesson can always be
    taken back, matched by timestamp (+ text defensively), without touching
    the rest of the doc."""
    sb, http = fresh_setter()
    agent = {"id": "agent-memdel01", "mode": "draft_only", "enabled": True,
             "instructions": "keep me",
             "memory": [{"text": "Lead with the $300 line.", "at": "2026-07-13T20:00:00+00:00", "source": "s1"},
                         {"text": "Never promise a discount.", "at": "2026-07-13T21:00:00+00:00", "source": "s2"}]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = setter.route_agents_memory_delete(
        {"agent_id": agent["id"], "at": "2026-07-13T20:00:00+00:00", "text": "Lead with the $300 line."})
    check("memory delete: 200", status == 200, (status, resp))
    check("memory delete: count drops to 1", resp.get("memory_count") == 1, resp)
    saved = setter._load_agent(agent["id"])
    check("memory delete: the right entry survives",
         (saved.get("memory") or [{}])[0].get("text") == "Never promise a discount.", saved.get("memory"))
    check("memory delete: rest of the doc untouched", saved.get("instructions") == "keep me", saved)

    status2, resp2 = setter.route_agents_memory_delete(
        {"agent_id": agent["id"], "at": "2026-07-13T20:00:00+00:00"})
    check("memory delete: already-removed entry -> 404", status2 == 404, (status2, resp2))
    status3, resp3 = setter.route_agents_memory_delete({"agent_id": agent["id"]})
    check("memory delete: missing at -> 400", status3 == 400, (status3, resp3))
    status4, resp4 = setter.route_agents_memory_delete({"agent_id": "agent-nope", "at": "x"})
    check("memory delete: unknown agent -> 404", status4 == 404, (status4, resp4))


def test_redraft_scope_remember_merges_instructions():
    """Owner ruling 2026-07-14: a redraft's scope="remember" feedback now
    merges into the agent's instructions instead of growing agent['memory'],
    and the redraft itself runs with the freshly merged instructions."""
    sb, http = fresh_setter()
    agent = {"id": "agent-redraft01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Resource: https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.queue.append({
        "id": 601, "workspace": "navreo", "smartlead_campaign_id": 111, "agent_id": agent["id"],
        "lead_email": "r@example.com", "lead_first_name": "There", "message_id": "m-r1",
        "reply_subject": "Re: hi", "reply_body": "sure, send it",
        "classification": {"primary_intent": "send_resource", "all_intents": ["send_resource"]},
        "timezone": None, "thread": [],
    })
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi There, thanks. Best, Sam"}
    http.merge_fn = None  # default append fallback

    status, resp = setter.route_queue_redraft({"id": 601, "feedback": "shorter please", "scope": "remember"})
    check("redraft remember: returns 200", status == 200, (status, resp))

    saved = setter._load_agent(agent["id"])
    check("redraft remember: memory is NOT touched (nothing writes memory any more)",
         (saved.get("memory") or []) == [], saved.get("memory"))
    check("redraft remember: instructions changed and contain the feedback text",
         "shorter please" in saved.get("instructions", ""), saved.get("instructions"))
    check("redraft remember: original instructions text is preserved",
         "https://x.example/r" in saved.get("instructions", ""), saved.get("instructions"))
    check("redraft remember: instruction_edits grew by one, source is the queue row id",
         len(saved.get("instruction_edits") or []) == 1 and saved["instruction_edits"][0]["source"] == "601",
         saved.get("instruction_edits"))


def test_redraft_without_scope_does_not_persist():
    sb, http = fresh_setter()
    agent = {"id": "agent-redraft02", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "resource_link": "https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.queue.append({
        "id": 602, "workspace": "navreo", "smartlead_campaign_id": 111, "agent_id": agent["id"],
        "lead_email": "r2@example.com", "lead_first_name": "There", "message_id": "m-r2",
        "reply_subject": "Re: hi", "reply_body": "sure, send it",
        "classification": {"primary_intent": "send_resource", "all_intents": ["send_resource"]},
        "timezone": None, "thread": [],
    })
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi There, thanks. Best, Sam"}

    status, resp = setter.route_queue_redraft({"id": 602, "feedback": "shorter please"})
    check("redraft default scope (absent): returns 200", status == 200, (status, resp))
    saved = setter._load_agent(agent["id"])
    check("redraft default scope (absent): memory is NOT touched", (saved.get("memory") or []) == [],
         saved.get("memory"))

    status2, resp2 = setter.route_queue_redraft({"id": 602, "feedback": "shorter still", "scope": "one_off"})
    check("redraft explicit scope=one_off: returns 200", status2 == 200, (status2, resp2))
    saved2 = setter._load_agent(agent["id"])
    check("redraft explicit scope=one_off: memory is still NOT touched", (saved2.get("memory") or []) == [],
         saved2.get("memory"))


def test_agent_duplicate():
    sb, http = fresh_setter()
    original = {
        "id": "agent-dup0001", "name": "Sales Agent", "mode": "autopilot", "enabled": True,
        "campaign_ids": [111, 222],
        "campaign_assigned_at": {"111": "2026-07-01T00:00:00+00:00", "222": "2026-07-01T00:00:00+00:00"},
        "allowed_intents": ["send_resource"], "instructions": "Flat $500/mo.",
        "memory": [{"text": "remember this", "source": "manual", "scope": "remember",
                   "at": "2026-07-01T00:00:00+00:00"}],
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }
    sb.agents[original["id"]] = {"id": original["id"], "doc": copy.deepcopy(original)}

    status, resp = setter.route_agents_duplicate({"agent_id": original["id"]})
    check("duplicate: returns 200", status == 200, (status, resp))
    clone = resp.get("doc") or {}
    check("duplicate: clone has a new id", clone.get("id") not in (None, original["id"]), clone.get("id"))
    check("duplicate: clone id follows the agent-<8 hex> shape",
         bool(re.match(r"^agent-[0-9a-f]{8}$", str(clone.get("id") or ""))), clone.get("id"))
    check("duplicate: clone name has the ' copy' suffix", clone.get("name") == "Sales Agent copy", clone.get("name"))
    check("duplicate: clone mode is draft_only", clone.get("mode") == "draft_only", clone.get("mode"))
    check("duplicate: clone has no campaigns", clone.get("campaign_ids") == [], clone.get("campaign_ids"))
    check("duplicate: clone campaign_assigned_at is empty", clone.get("campaign_assigned_at") == {},
         clone.get("campaign_assigned_at"))
    check("duplicate: clone is enabled", clone.get("enabled") is True, clone.get("enabled"))
    check("duplicate: clone carries over memory", clone.get("memory") == original["memory"], clone.get("memory"))
    check("duplicate: clone carries over instructions", clone.get("instructions") == "Flat $500/mo.",
         clone.get("instructions"))

    original_after = setter._load_agent(original["id"])
    check("duplicate: original doc is byte-unchanged", original_after == original, (original, original_after))
    check("duplicate: original is now a separate row - two agents stored", len(sb.agents) == 2,
         list(sb.agents.keys()))

    # editing the clone must never touch the original
    setter._save_agent({"id": clone["id"], "name": "Edited clone name"})
    original_after_edit = setter._load_agent(original["id"])
    check("duplicate: editing the clone leaves the original untouched", original_after_edit == original,
         (original, original_after_edit))
    clone_after_edit = setter._load_agent(clone["id"])
    check("duplicate: the clone itself did pick up the edit", clone_after_edit.get("name") == "Edited clone name",
         clone_after_edit)

    status2, resp2 = setter.route_agents_duplicate({"agent_id": "agent-doesnotexist"})
    check("duplicate: unknown agent -> 404", status2 == 404, (status2, resp2))

    status3, resp3 = setter.route_agents_duplicate({})
    check("duplicate: missing agent_id -> 400", status3 == 400, (status3, resp3))


# ── v2: grading page endpoints ──────────────────────────────────────────────

def _wait_for_relearn_idle(timeout=2.0):
    """Relearn runs on a background thread; against the fakes it's near
    instant (no real network), but polling for idle rather than assuming a
    fixed sleep keeps this test honest and non-flaky either way."""
    import time as _time
    deadline = _time.time() + timeout
    resp = {}
    while _time.time() < deadline:
        _, resp = setter.route_grading_get(None)
        if (resp.get("relearn") or {}).get("status") == "idle":
            return resp
        _time.sleep(0.01)
    return resp


def test_grading_endpoints():
    sb, http = fresh_setter()

    status, resp = setter.route_grading_get(None)
    check("grading: GET with nothing stored returns empty cases/answers/relearn/feedback_log",
         status == 200 and resp == {"cases": [], "answers": {}, "relearn": {"status": "idle"}, "feedback_log": []},
         resp)

    status, resp = setter.route_grading_answer({"id": "case-1", "decision_ok": True, "reply_ok": False,
                                                "note": "close but no cigar"})
    check("grading: answer upsert returns 200 ok", status == 200 and resp.get("ok") is True, resp)
    check("grading: the answer is stored under its case id",
         resp.get("answers", {}).get("case-1", {}).get("decision_ok") is True, resp)
    check("grading: reply_ok and note both persisted",
         resp.get("answers", {}).get("case-1", {}).get("reply_ok") is False and
         resp.get("answers", {}).get("case-1", {}).get("note") == "close but no cigar", resp)
    # a note (or a False on either question) is feedback worth learning from -
    # the answer response reports that a relearn pass has been kicked off
    check("grading: an answer carrying a note kicks off a relearn pass immediately",
         resp.get("relearn", {}).get("status") == "running", resp)
    _wait_for_relearn_idle()

    _, resp2 = setter.route_grading_get(None)
    check("grading: GET reflects the stored answer", resp2.get("answers", {}).get("case-1", {}).get("decision_ok") is True, resp2)
    check("grading: the feedback note landed in feedback_log",
         any(e.get("note") == "close but no cigar" for e in resp2.get("feedback_log") or []), resp2.get("feedback_log"))

    # a second, different case is additive - both persist. decision_ok=False
    # with no note is still a wrong-call signal, so it also triggers relearn.
    status_b, resp_b = setter.route_grading_answer({"id": "case-2", "decision_ok": False, "reply_ok": None, "note": ""})
    check("grading: a noteless wrong-decision answer also kicks off relearn",
         resp_b.get("relearn", {}).get("status") == "running", resp_b)
    _wait_for_relearn_idle()
    _, resp3 = setter.route_grading_get(None)
    check("grading: two different cases both persist",
         set(resp3.get("answers", {}).keys()) == {"case-1", "case-2"}, resp3)
    check("grading: feedback_log has one entry per triggering answer (2 so far)",
         len(resp3.get("feedback_log") or []) == 2, resp3.get("feedback_log"))

    # re-answering the same case upserts in place rather than duplicating
    setter.route_grading_answer({"id": "case-1", "decision_ok": False, "reply_ok": True, "note": "actually no"})
    _wait_for_relearn_idle()
    _, resp4 = setter.route_grading_get(None)
    check("grading: re-answering the same case id upserts in place, not a duplicate",
         resp4.get("answers", {}).get("case-1", {}).get("decision_ok") is False and
         len(resp4.get("answers", {})) == 2, resp4)

    # answer with no id is rejected
    status5, resp5 = setter.route_grading_answer({"decision_ok": True})
    check("grading: answer without an id returns 400", status5 == 400, (status5, resp5))

    # reset clears answers only, never the cases list
    doc = setter._load_grading()
    doc["cases"] = [{"id": "case-1", "inbound": "hi"}]
    setter._save_grading(doc)
    status6, resp6 = setter.route_grading_reset({})
    check("grading: reset returns 200 ok", status6 == 200 and resp6.get("ok") is True, resp6)
    _, resp7 = setter.route_grading_get(None)
    check("grading: reset clears every answer", resp7.get("answers") == {}, resp7)
    check("grading: reset leaves the stored cases list untouched",
         resp7.get("cases") == [{"id": "case-1", "inbound": "hi"}], resp7)

    # the reserved __grading__ doc row must never leak into _load_agents()
    check("grading: the __grading__ doc row never appears in _load_agents()",
         all(a.get("id") != setter.GRADING_ID for a in setter._load_agents()), setter._load_agents())


def test_grading_relearn_updates_unanswered_cases():
    """The owner's own scenario: leave feedback on one case, and every other
    still-unanswered case should get re-classified/re-decided/re-drafted with
    that feedback folded in - without the owner repeating themselves, and
    without ever touching an already-answered case."""
    sb, http = fresh_setter()
    agent_snapshot = {
        "id": "agent-grading-test", "mode": "autopilot", "enabled": True,
        "allowed_intents": ["send_resource", "pricing", "scheduling"],
        "instructions": "Flat $500/mo. Resource: The breakdown - https://x.example/r - "
                        "send when they want more info.",
        "confidence_threshold": 0.9,
    }
    case_answered = {
        "id": "case-00", "bucket": "b", "inbound": "Sure, send it over.",
        "lead_first_name": "Jane", "company_domain": "example.com", "hydrated": True,
        "thread": [], "category": None, "intent": "send_resource", "confidence": 0.5,
        "decision": "review", "reason": "old reason", "draft_html": "<div>old</div>", "would_auto": False,
        "_ctx": {"category": None, "timezone": "Europe/London", "slot_status": "not_configured",
                 "body_len": 20, "same_day_ask": False, "subject": "Re: hi", "last_outbound": ""},
    }
    case_unanswered = {
        "id": "case-01", "bucket": "b", "inbound": "Yeah go for it, cheers",
        "lead_first_name": "Sam", "company_domain": "example.org", "hydrated": True,
        "thread": [], "category": None, "intent": None, "confidence": 0.4,
        "decision": "review", "reason": "old reason", "draft_html": None, "would_auto": False,
        "_ctx": {"category": None, "timezone": "Europe/London", "slot_status": "ok",
                 "body_len": 22, "same_day_ask": False, "subject": "Re: hi", "last_outbound": ""},
    }
    doc = {"cases": [case_answered, case_unanswered],
          "answers": {"case-00": {"decision_ok": True, "reply_ok": True, "note": ""}},
          "agent_snapshot": agent_snapshot, "feedback_log": [], "relearn": {"status": "idle"}}
    setter._save_grading(doc)

    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.97, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants the resource", "rationale": "unqualified yes",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                               "html": '<div>Hi Sam,</div><br><div>Of course.</div><br>'
                                       '<div><a href="https://x.example/r">Here it is</a></div><br>'
                                       '<div>Best,<br>Bjion</div>'}

    status, resp = setter.route_grading_answer({"id": "case-00", "decision_ok": False, "reply_ok": True,
                                                "note": "This should have been held for review"})
    check("grading relearn: answering with a note kicks off a running relearn pass immediately",
         status == 200 and resp.get("relearn", {}).get("status") == "running", resp)

    final = _wait_for_relearn_idle()
    check("grading relearn: relearn settles back to idle", final.get("relearn", {}).get("status") == "idle", final)
    check("grading relearn: notes_applied reflects the one feedback entry",
         final.get("relearn", {}).get("notes_applied") == 1, final.get("relearn"))
    check("grading relearn: cases_updated counts the one unanswered case",
         final.get("relearn", {}).get("cases_updated") == 1, final.get("relearn"))
    check("grading relearn: feedback_log recorded the note verbatim",
         len(final.get("feedback_log") or []) == 1 and
         final["feedback_log"][0]["note"] == "This should have been held for review", final.get("feedback_log"))

    updated_cases = {c["id"]: c for c in final.get("cases") or []}
    check("grading relearn: the ANSWERED case (case-00) is left completely untouched",
         updated_cases["case-00"]["draft_html"] == "<div>old</div>" and
         not updated_cases["case-00"].get("updated_by_feedback"), updated_cases.get("case-00"))
    check("grading relearn: the UNANSWERED case (case-01) got re-classified and re-drafted",
         updated_cases["case-01"].get("updated_by_feedback") is True and
         updated_cases["case-01"]["intent"] == "send_resource" and
         updated_cases["case-01"]["decision"] == "auto_send" and
         updated_cases["case-01"]["would_auto"] is True and
         "Hi Sam" in (updated_cases["case-01"]["draft_html"] or ""), updated_cases.get("case-01"))


def test_grading_relearn_extracts_real_calendly_slots_from_existing_draft():
    """When a case's own _ctx.slot_status was 'ok', a relearn re-draft must
    keep offering the SAME two real call times already baked into the case's
    existing draft (extracted from its calendly.com anchors), never invent
    fresh ones and never call Calendly again."""
    html = ('<div>Hi Sam,</div><br><div>Of course.</div><br>'
           '<div>Would you be free on <a href="https://calendly.com/navreo/book-a-call/2026-07-15T09:00">'
           'Wednesday, 15th July at 9:00 AM BST</a> or '
           '<a href="https://calendly.com/navreo/book-a-call/2026-07-15T13:00">1:00 PM BST</a>?</div><br>'
           '<div>Best,<br>Bjion</div>')
    slots = setter._extract_calendly_slots(html)
    check("grading relearn: extracts exactly two calendly slots from an existing draft's anchors",
         len(slots) == 2, slots)
    if len(slots) == 2:
        check("grading relearn: first slot's link is the real calendly deep link",
             slots[0]["link"] == "https://calendly.com/navreo/book-a-call/2026-07-15T09:00", slots)
        check("grading relearn: first slot's label is the anchor's own text",
             slots[0]["label"] == "Wednesday, 15th July at 9:00 AM BST", slots)
        check("grading relearn: second slot's link is the real calendly deep link",
             slots[1]["link"] == "https://calendly.com/navreo/book-a-call/2026-07-15T13:00", slots)
    check("grading relearn: no calendly anchors in the draft -> empty slots, never raises",
         setter._extract_calendly_slots("<div>no links here</div>") == [])
    check("grading relearn: empty/None draft_html -> empty slots, never raises",
         setter._extract_calendly_slots(None) == [] and setter._extract_calendly_slots("") == [])


# ── training engine ──────────────────────────────────────────────────────────

_TRAINING_CATEGORIES = ["Interested", "Information Request", "Meeting Request", "Contact Forward",
                        "positive-re-reply", "Not Interested", "Do Not Contact", "Wrong Person", "Out Of Office"]


def _seed_training_corpus(sb, per_category=6, campaign_id=8001, start_id=1):
    """Real-shaped `replies` rows spread evenly across every training
    category (5 actionable + 4 clear-negative), each with a real-looking,
    >=10-char body - what _fetch_training_candidates requires."""
    rid = start_id
    for cat in _TRAINING_CATEGORIES:
        for i in range(per_category):
            sb.replies.append({
                "id": rid, "workspace": "navreo", "smartlead_campaign_id": campaign_id,
                "email": f"lead-{cat.lower().replace(' ', '-')}-{i}@example.com",
                "replied_at": f"2026-06-{10 + i:02d}T09:00:00+00:00",
                "category": cat, "reply_subject": "Re: our email",
                "reply_body": f"Real archived reply body #{rid} for category {cat}. Thanks for the note.",
            })
            rid += 1


def _training_classify_fn(body):
    payload = json.loads(body["messages"][1]["content"])
    return {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.5,  # below any default threshold, so nothing would ever auto-send even if it tried
        "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0, "wants": "wants info", "rationale": "",
    }


def _generate_and_wait(payload, agent_id=None, timeout=10):
    """route_training_generate is now async (see setter.py): a successful
    call returns {status:"started"|"already_running"} almost instantly and
    the real work happens on a background daemon thread. This joins that
    agent's thread (setter._TRAINING_GEN_THREADS - production never reads
    this map, it exists purely so tests can be deterministic) before
    returning, so callers can inspect the saved doc right after."""
    status, resp = setter.route_training_generate(payload)
    aid = agent_id or payload.get("agent_id")
    if status == 200 and resp.get("status") in ("started", "already_running") and aid:
        thread = setter._TRAINING_GEN_THREADS.get(aid)
        if thread is not None:
            thread.join(timeout=timeout)
    return status, resp


def _answer_and_wait(payload, agent_id=None, timeout=10):
    """route_training_answer (Feature B) may kick off a background RETRAIN
    pass sharing the exact same per-agent lock/thread map generation uses
    (setter._get_training_gen_lock / setter._TRAINING_GEN_THREADS). This
    joins that agent's thread before returning - whether the response was
    "started" (a fresh pass) or "queued" (an already-running pass that will
    pick up the fresher digest) - so callers can inspect the saved doc
    deterministically right after, exactly like _generate_and_wait does.

    Latency fix (2026-07-14, part 2): a "queued" response no longer means
    the request thread already persisted retrain_queued=True itself - a
    tiny daemon "flagger" thread does that off-thread now (see
    setter._kick_off_training_retrain), registered under
    _TRAINING_GEN_THREADS[f"{aid}:flag"]. Join that FIRST so the flag is
    guaranteed persisted before joining the (still-running) main worker
    thread that's supposed to consume it."""
    status, resp = setter.route_training_answer(payload)
    aid = agent_id or payload.get("agent_id")
    if status == 200 and resp.get("retrain") in ("started", "queued") and aid:
        if resp.get("retrain") == "queued":
            flagger = setter._TRAINING_GEN_THREADS.get(f"{aid}:flag")
            if flagger is not None:
                flagger.join(timeout=timeout)
        thread = setter._TRAINING_GEN_THREADS.get(aid)
        if thread is not None:
            thread.join(timeout=timeout)
    return status, resp


def test_training_generate_weighted_excludes_used_and_batch_cap():
    sb, http = fresh_setter()
    _seed_training_corpus(sb, per_category=6)
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-train0001", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 8})
    check("training generate: returns 200 and starts immediately",
         status == 200 and resp.get("status") == "started", (status, resp))

    doc = setter._load_training(agent["id"])
    gen = doc.get("generating") or {}
    check("training generate: background worker marks generating idle once the batch lands",
         gen.get("status") == "idle", gen)
    check("training generate: default-sized batch generates 8 real cases and generating.added says so",
         len(doc.get("cases") or []) == 8 and gen.get("added") == 8, (doc.get("cases"), gen))
    check("training generate: used_count grew by 8", len(doc.get("used_reply_ids") or []) == 8,
         doc.get("used_reply_ids"))

    first_cases = list(doc.get("cases") or [])
    first_reply_ids = {c["reply_id"] for c in first_cases}
    check("training generate: no duplicate reply_id within one batch",
         len(first_reply_ids) == len(first_cases), first_cases)

    status2, resp2 = _generate_and_wait({"agent_id": agent["id"], "batch_size": 999})
    check("training generate: batch_size above the max is clamped to 10, not rejected (still starts)",
         status2 == 200 and resp2.get("status") == "started", resp2)

    doc2 = setter._load_training(agent["id"])
    new_cases = list(doc2.get("cases") or [])[len(first_cases):]
    check("training generate: batch_size above the max is clamped to 10, not rejected",
         len(new_cases) <= 10, new_cases)

    second_reply_ids = {c["reply_id"] for c in new_cases}
    check("training generate: a later batch never repeats a reply_id already used",
         first_reply_ids.isdisjoint(second_reply_ids), (first_reply_ids, second_reply_ids))

    check("training generate: used_reply_ids accumulates across calls",
         len(doc2.get("used_reply_ids") or []) == len(first_reply_ids) + len(second_reply_ids),
         doc2.get("used_reply_ids"))
    check("training: the training-<agent_id> doc row never appears in _load_agents()",
         all(not str(a.get("id") or "").startswith(setter.TRAINING_ID_PREFIX) for a in setter._load_agents()),
         setter._load_agents())


def test_training_generate_stores_real_bodies_verbatim():
    sb, http = fresh_setter()
    _seed_training_corpus(sb, per_category=6, campaign_id=8010)
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-train0002", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    _generate_and_wait({"agent_id": agent["id"], "batch_size": 6})
    doc = setter._load_training(agent["id"])
    by_reply_id = {r["id"]: r for r in sb.replies}
    ok = True
    for case in doc.get("cases") or []:
        original = by_reply_id[case["reply_id"]]
        if case["inbound"]["raw_body"] != original["reply_body"]:
            ok = False
        if case["inbound"]["subject"] != original["reply_subject"]:
            ok = False
        if case["category"] != original["category"]:
            ok = False
    check("training generate: every case's inbound is the real reply verbatim (raw body, subject, category)",
         ok and bool(doc.get("cases")), doc.get("cases"))


def test_training_case_includes_original_outreach_and_human_answer_when_present():
    sb, http = fresh_setter()
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    campaign_id = 9001
    email = "history@example.com"
    sb.sent_messages.append({
        "smartlead_campaign_id": campaign_id, "email": email, "email_seq_number": 1,
        "is_manual_reply": False, "subject": "Our first email", "body": "Hi, wanted to share our breakdown.",
        "sent_at": "2026-06-01T09:00:00+00:00",
    })
    sb.sent_messages.append({
        "smartlead_campaign_id": campaign_id, "email": email, "email_seq_number": 2,
        "is_manual_reply": True, "subject": "Re: our email", "body": "Sure, here is the call link.",
        "sent_at": "2026-06-11T09:00:00+00:00",
    })
    reply_row = {"id": 9101, "smartlead_campaign_id": campaign_id, "email": email,
                "replied_at": "2026-06-10T09:00:00+00:00", "category": "Interested",
                "reply_subject": "Re: our email", "reply_body": "Sounds great, send more info please."}

    agent = {"id": "agent-train0003", "resource_link": "https://x.example/r"}
    now = dt.datetime.now(dt.timezone.utc)
    case = setter._build_training_case(reply_row, agent, {}, [], "not_configured", now, "", idx=0)

    check("training case: carries original_outreach when sent_messages has seq 1",
         case["original_outreach"].get("body") == "Hi, wanted to share our breakdown.", case["original_outreach"])
    check("training case: carries human_answer_history (earliest manual reply after replied_at)",
         case["human_answer_history"].get("body") == "Sure, here is the call link.", case["human_answer_history"])
    check("training case: inbound raw_body is the real reply verbatim",
         case["inbound"]["raw_body"] == reply_row["reply_body"], case["inbound"])

    reply_row2 = {"id": 9102, "smartlead_campaign_id": 9002, "email": "nohistory@example.com",
                 "replied_at": "2026-06-10T09:00:00+00:00", "category": "Interested",
                 "reply_subject": "Re: our email", "reply_body": "Sounds great, send more info please."}
    case2 = setter._build_training_case(reply_row2, agent, {}, [], "not_configured", now, "", idx=1)
    check("training case: blank-canvas when no original outreach exists",
         case2["original_outreach"] == {}, case2["original_outreach"])
    check("training case: blank-canvas when no human answer exists",
         case2["human_answer_history"] == {}, case2["human_answer_history"])


def test_training_generate_memory_digest_reaches_classify():
    sb, http = fresh_setter()
    _seed_training_corpus(sb, per_category=6, campaign_id=8100)
    captured = []

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        captured.append(payload.get("owner_corrections"))
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.5, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
            "wants": "wants info", "rationale": "",
        }

    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {
        "id": "agent-train0004", "mode": "draft_only", "enabled": True,
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r",
        "memory": [{"text": "Never promise a specific onboarding date.", "source": "manual",
                   "scope": "remember", "at": "2026-07-01T00:00:00+00:00"}],
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 4})
    check("training generate: 200 and starts", status == 200 and resp.get("status") == "started", (status, resp))
    check("training generate: classify was actually called", len(captured) > 0, captured)
    check("training generate: agent memory digest reaches classify as owner_corrections",
         len(captured) > 0 and all("Never promise a specific onboarding date." in (c or "") for c in captured),
         captured)


def _fixed_case(reply_row, idx):
    """Minimal, cheap stand-in for what _build_training_case would have
    returned - used to isolate route_training_generate's own concurrency/
    ordering/error-handling logic from the real classify/draft pipeline."""
    return {
        "id": f"case-{idx:04d}", "reply_id": reply_row.get("id"), "campaign_id": reply_row.get("smartlead_campaign_id"),
        "category": reply_row.get("category"),
        "inbound": {"subject": reply_row.get("reply_subject") or "", "body": reply_row.get("reply_body") or "",
                   "raw_body": reply_row.get("reply_body") or ""},
        "original_outreach": {}, "human_answer_history": {}, "classification": {},
        "decision": "left_alone", "decision_reason": "test", "draft_html": None,
        "generated_at": "2026-07-14T00:00:00+00:00",
    }


def _fixed_training_replies(n, prefix="r"):
    return [{"id": f"{prefix}{i}", "smartlead_campaign_id": 1, "email": f"lead{i}@example.com",
            "replied_at": "2026-06-10T09:00:00+00:00", "category": "Interested",
            "reply_subject": "Re: our email", "reply_body": f"Real archived reply body {i}. Thanks."}
           for i in range(n)]


def test_training_generate_concurrent_preserves_selection_order():
    """Workers race (deliberately slowest-first by submission order below),
    but the STORED case order must still match the order _select_training_
    replies returned - never completion order."""
    import time as _time

    sb, http = fresh_setter()
    agent = {"id": "agent-train-conc1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    fixed_replies = _fixed_training_replies(6, prefix="ord")
    real_select = setter._select_training_replies
    real_build = setter._build_training_case

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        return fixed_replies

    def fake_build(reply_row, agent_, eff, avail, slot_status0, now, mem_digest, idx):
        # Later-submitted replies (higher idx) finish FIRST. If the route
        # trusted completion order instead of the index each worker was
        # given, the stored order would come out reversed.
        _time.sleep(0.03 * (len(fixed_replies) - idx))
        return _fixed_case(reply_row, idx)

    setter._select_training_replies = fake_select
    setter._build_training_case = fake_build
    try:
        status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 6})
    finally:
        setter._select_training_replies = real_select
        setter._build_training_case = real_build

    check("training generate concurrent: 200 and starts", status == 200 and resp.get("status") == "started",
         (status, resp))
    doc = setter._load_training(agent["id"])
    cases = doc.get("cases") or []
    check("training generate concurrent: all 6 cases built", len(cases) == 6, cases)
    got_order = [c["reply_id"] for c in cases]
    want_order = [r["id"] for r in fixed_replies]
    check("training generate concurrent: stored case order matches selection order, not completion order",
         got_order == want_order, (got_order, want_order))


def test_training_generate_one_worker_failure_drops_only_that_case():
    sb, http = fresh_setter()
    agent = {"id": "agent-train-conc2", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    fixed_replies = _fixed_training_replies(4, prefix="bad")
    bad_id = fixed_replies[2]["id"]
    real_select = setter._select_training_replies
    real_build = setter._build_training_case

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        return fixed_replies

    def fake_build(reply_row, agent_, eff, avail, slot_status0, now, mem_digest, idx):
        if reply_row.get("id") == bad_id:
            raise RuntimeError("simulated classify/draft failure")
        return _fixed_case(reply_row, idx)

    setter._select_training_replies = fake_select
    setter._build_training_case = fake_build
    try:
        status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 4})
    finally:
        setter._select_training_replies = real_select
        setter._build_training_case = real_build

    check("training generate one-failure: still 200 and starts", status == 200 and resp.get("status") == "started",
         (status, resp))
    doc = setter._load_training(agent["id"])
    cases = doc.get("cases") or []
    check("training generate one-failure: exactly 3 of 4 cases survive", len(cases) == 3, cases)
    got_ids = [c["reply_id"] for c in cases]
    check("training generate one-failure: the failing reply's case is absent, the other 3 present in order",
         got_ids == [r["id"] for r in fixed_replies if r["id"] != bad_id], got_ids)

    used = list(doc.get("used_reply_ids") or [])
    check("training generate one-failure: used_reply_ids still records all 4 selected replies exactly once "
         "(including the one that failed to build a case), with no duplicates from concurrent workers",
         sorted(used) == sorted(r["id"] for r in fixed_replies) and len(used) == len(set(used)), used)


def test_training_generate_all_workers_fail_marks_generating_failed_plain_english():
    """The old synchronous route returned a 502 with the plain-English error
    body directly. Now the route itself always starts (200/started) - a
    total build failure surfaces as doc.generating = {status:"failed",
    error:...} instead, which the training page shows via showError() once
    a poll picks it up (see setter-train.html pollGeneratingOnce())."""
    sb, http = fresh_setter()
    agent = {"id": "agent-train-conc3", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    fixed_replies = _fixed_training_replies(3, prefix="allbad")
    real_select = setter._select_training_replies
    real_build = setter._build_training_case

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        return fixed_replies

    def fake_build(reply_row, agent_, eff, avail, slot_status0, now, mem_digest, idx):
        raise RuntimeError("simulated total outage")

    setter._select_training_replies = fake_select
    setter._build_training_case = fake_build
    try:
        status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 3})
    finally:
        setter._select_training_replies = real_select
        setter._build_training_case = real_build

    check("training generate all-fail: still starts synchronously (200, async)",
         status == 200 and resp.get("status") == "started", (status, resp))

    doc = setter._load_training(agent["id"])
    gen = doc.get("generating") or {}
    check("training generate all-fail: generating.status is failed with a plain-English error, no em dash",
         gen.get("status") == "failed"
         and gen.get("error") == "Couldn't build any scenarios just now - try again in a minute."
         and "—" not in (gen.get("error") or ""), gen)
    check("training generate all-fail: nothing partially saved - used_reply_ids stays empty",
         (doc.get("used_reply_ids") or []) == [], doc.get("used_reply_ids"))
    check("training generate all-fail: nothing partially saved - cases list stays empty",
         (doc.get("cases") or []) == [], doc.get("cases"))


def test_training_generate_concurrent_batch_matches_sequential_case_count():
    """Sanity check over the REAL (non-monkeypatched) pipeline: a normal
    weighted batch built concurrently still yields the same case count and
    reply-id set shape as the pre-concurrency sequential version did - see
    test_training_generate_weighted_excludes_used_and_batch_cap for the
    original assertions this mirrors."""
    sb, http = fresh_setter()
    _seed_training_corpus(sb, per_category=6, campaign_id=8200)
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-train-conc4", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 8})
    check("training generate concurrent real pipeline: 200 and starts", status == 200 and resp.get("status") == "started",
         (status, resp))
    doc = setter._load_training(agent["id"])
    check("training generate concurrent real pipeline: a full 8-case batch landed",
         len(doc.get("cases") or []) == 8, doc.get("cases"))
    check("training generate concurrent real pipeline: used_reply_ids grew by exactly 8, no duplicates",
         len(doc.get("used_reply_ids") or []) == 8 and len(set(doc.get("used_reply_ids") or [])) == 8,
         doc.get("used_reply_ids"))


def test_training_generate_refuses_over_40_unanswered():
    sb, http = fresh_setter()
    agent = {"id": "agent-train0005", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": f"case-{i:04d}"} for i in range(41)], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 4})
    check("training generate: refuses (400) with more than 40 unanswered cases already pending",
         status == 400, (status, resp))


def test_training_generate_second_call_while_running_is_already_running():
    """The route acquires a per-agent lock before starting the background
    thread (see setter._get_training_gen_lock). A second call for the SAME
    agent while that thread is still working must never start a second
    thread - it's an idempotent no-op the page can treat exactly like
    "started" (just keep polling)."""
    sb, http = fresh_setter()
    agent = {"id": "agent-train-async1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    fixed_replies = _fixed_training_replies(2, prefix="block")
    started_event = threading.Event()
    release_event = threading.Event()
    real_select = setter._select_training_replies
    real_build = setter._build_training_case

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        started_event.set()
        release_event.wait(timeout=10)
        return fixed_replies

    def fake_build(reply_row, agent_, eff, avail, slot_status0, now, mem_digest, idx):
        return _fixed_case(reply_row, idx)

    setter._select_training_replies = fake_select
    setter._build_training_case = fake_build
    try:
        status1, resp1 = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 2})
        check("training generate async: the first call starts immediately (200/started)",
             status1 == 200 and resp1.get("status") == "started", (status1, resp1))
        check("training generate async: started_event fires - the worker actually reached the selection step",
             started_event.wait(timeout=5), None)

        doc_mid = setter._load_training(agent["id"])
        check("training generate async: the doc shows generating.running right after the POST returns",
             doc_mid.get("generating", {}).get("status") == "running", doc_mid.get("generating"))

        status2, resp2 = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 2})
        check("training generate async: a second call while the first is still running -> already_running, "
             "not a second background batch", status2 == 200 and resp2.get("status") == "already_running",
             (status2, resp2))

        release_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)

        doc_final = setter._load_training(agent["id"])
        check("training generate async: generating flips to idle once the background batch actually finishes",
             doc_final.get("generating", {}).get("status") == "idle", doc_final.get("generating"))
        check("training generate async: exactly one batch's worth of cases was saved (no duplicate run)",
             len(doc_final.get("cases") or []) == 2, doc_final.get("cases"))
    finally:
        setter._select_training_replies = real_select
        setter._build_training_case = real_build
        release_event.set()


def test_training_generate_lost_update_protection_answer_survives():
    """An owner (or client, on a share link) can answer an EXISTING scenario
    while a new batch is still generating in the background. The worker's
    final save must reload the doc first, so that in-flight answer is never
    silently overwritten by the generation thread's own stale in-memory
    copy (see setter._training_generate_worker's fresh_doc reload)."""
    sb, http = fresh_setter()
    agent = {"id": "agent-train-async2", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    existing_doc = {"cases": [{"id": "case-pre-0000"}], "answers": {}, "used_reply_ids": [],
                    "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], existing_doc)

    fixed_replies = _fixed_training_replies(2, prefix="mid")
    started_event = threading.Event()
    release_event = threading.Event()
    real_select = setter._select_training_replies
    real_build = setter._build_training_case

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        started_event.set()
        release_event.wait(timeout=10)
        return fixed_replies

    def fake_build(reply_row, agent_, eff, avail, slot_status0, now, mem_digest, idx):
        return _fixed_case(reply_row, idx)

    setter._select_training_replies = fake_select
    setter._build_training_case = fake_build
    try:
        status, resp = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 2})
        check("lost-update: generation starts", status == 200 and resp.get("status") == "started", (status, resp))
        check("lost-update: worker reached the (blocked) selection step",
             started_event.wait(timeout=5), None)

        # An answer lands on the ORIGINAL pre-existing case while the batch
        # above is still stuck mid-generation (blocked on release_event).
        astatus, aresp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-pre-0000", "decision_ok": True, "reply_ok": True,
            "note": "", "scope": "one_off",
        })
        check("lost-update: the mid-generation answer itself saves fine", astatus == 200, (astatus, aresp))

        release_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)

        final_doc = setter._load_training(agent["id"])
        check("lost-update: the answer that landed mid-generation survives the worker's final save",
             final_doc.get("answers", {}).get("case-pre-0000", {}).get("decision_ok") is True,
             final_doc.get("answers"))
        check("lost-update: the new batch's cases were appended on top, not lost",
             len(final_doc.get("cases") or []) == 3, final_doc.get("cases"))
        gen = final_doc.get("generating") or {}
        check("lost-update: generating flips to idle with added=2",
             gen.get("status") == "idle" and gen.get("added") == 2, gen)
    finally:
        setter._select_training_replies = real_select
        setter._build_training_case = real_build
        release_event.set()


# ── synthetic training scenarios (shortfall top-up) ─────────────────────────
# See the doctrine comment above setter._TRAINING_ID_PREFIX: when the real
# replies table can't fill a requested batch, the remainder is invented as
# lead-side-only synthetic scenarios and built through the exact same live
# classify/decide/draft_reply/lint_draft pipeline as a real case.

def test_training_generate_shortfall_top_up_real_plus_synthetic():
    """3 selectable real replies, batch 8 -> 8 cases: 3 real (synthetic
    falsy, reply_id set) + 5 synthetic (synthetic:true, reply_id null), and
    exactly the 3 real replies land in used_reply_ids."""
    sb, http = fresh_setter()
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-synth0001", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "campaign_ids": ["9500"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    real_replies = _fixed_training_replies(3, prefix="realshort")
    for r in real_replies:
        sb.replies.append(dict(r, workspace="navreo"))

    real_select = setter._select_training_replies

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        return list(real_replies)

    setter._select_training_replies = fake_select
    try:
        status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 8})
    finally:
        setter._select_training_replies = real_select

    check("shortfall: 200 and starts", status == 200 and resp.get("status") == "started", (status, resp))
    doc = setter._load_training(agent["id"])
    cases = doc.get("cases") or []
    check("shortfall: exactly 8 cases total", len(cases) == 8, cases)

    real_cases = [c for c in cases if not c.get("synthetic")]
    synth_cases = [c for c in cases if c.get("synthetic") is True]
    check("shortfall: exactly 3 real cases, no synthetic flag, reply_id set",
         len(real_cases) == 3 and all(c.get("reply_id") is not None for c in real_cases), real_cases)
    check("shortfall: exactly 5 synthetic cases, reply_id null",
         len(synth_cases) == 5 and all(c.get("reply_id") is None for c in synth_cases), synth_cases)

    used = list(doc.get("used_reply_ids") or [])
    check("shortfall: exactly 3 new used_reply_ids, matching the 3 real replies only",
         sorted(str(u) for u in used) == sorted(str(r["id"]) for r in real_replies), used)


def test_training_generate_pure_synthetic_zero_replies():
    """An agent with zero replies anywhere: batch 8 -> 8 synthetic cases,
    used_reply_ids untouched, and the invention prompt falls back to the
    agent's own brain/campaign/offer context."""
    sb, http = fresh_setter()
    captured = []

    def invent_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        captured.append(payload)
        plan = payload.get("scenario_plan") or []
        return {"scenarios": [
            {"lead_first_name": "Jamie", "lead_company": "Roke Ltd",
             "subject": "Re: our note", "body": f"Synthetic {cat} body #{i}."}
            for i, cat in enumerate(plan)
        ]}

    http.invent_fn = invent_fn
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    campaign_id = "9600"
    sb.sent_messages.append({
        "smartlead_campaign_id": campaign_id, "email": "seed@example.com", "email_seq_number": 1,
        "is_manual_reply": False, "subject": "Our outreach", "body": "Hi, wanted to share our breakdown.",
        "sent_at": "2026-06-01T09:00:00+00:00",
    })
    agent = {
        "id": "agent-synth0002", "mode": "draft_only", "enabled": True,
        "allowed_intents": ["send_resource"], "campaign_ids": [campaign_id],
        "instructions": "Our pricing is $500/mo flat. Resource: https://x.example/breakdown",
        "extra_instructions": "Always mention the free audit.",
        "pricing_notes": "Legacy pricing note.",
        "resources": "https://x.example/breakdown",
        "voice_examples": ["Hi there, thanks for reaching out!"],
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    doc_before = setter._load_training(agent["id"])
    used_before = list(doc_before.get("used_reply_ids") or [])

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 8})
    check("zero-replies: 200 and starts", status == 200 and resp.get("status") == "started", (status, resp))

    doc = setter._load_training(agent["id"])
    cases = doc.get("cases") or []
    check("zero-replies: 8 cases, all synthetic",
         len(cases) == 8 and all(c.get("synthetic") is True for c in cases), cases)
    check("zero-replies: no reply_id anywhere", all(c.get("reply_id") is None for c in cases), cases)

    used_after = list(doc.get("used_reply_ids") or [])
    check("zero-replies: used_reply_ids byte-identical before/after",
         used_after == used_before, (used_before, used_after))

    check("zero-replies: invent prompt was actually called", len(captured) == 1, captured)
    payload = captured[0] if captured else {}
    fb = payload.get("fallback_context") or {}
    check("zero-replies: prompt fallback_context carries the agent's brain/campaign/offer context",
         "500" in fb.get("instructions", "") and fb.get("extra_instructions") == "Always mention the free audit."
         and fb.get("pricing_notes") == "Legacy pricing note." and fb.get("resources")
         and fb.get("voice_examples") and fb.get("sample_outreach"), fb)


def test_training_generate_synthetic_only_preserves_existing_used_reply_ids():
    """Provenance + purity: after a synthetic-only generation, every new
    case carries synthetic:true and used_reply_ids is exactly what it was
    before (not merely empty-to-empty - a non-empty pre-existing list must
    also survive byte-identical)."""
    sb, http = fresh_setter()
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-synth0003", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    existing_doc = {"cases": [{"id": "case-0000", "reply_id": 101, "category": "Interested",
                               "inbound": {"subject": "", "body": "old real case", "raw_body": "old real case"}}],
                    "answers": {}, "used_reply_ids": [101, 102],
                    "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], existing_doc)

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 4})
    check("purity: 200 and starts", status == 200 and resp.get("status") == "started", (status, resp))

    doc = setter._load_training(agent["id"])
    all_cases = doc.get("cases") or []
    new_cases = [c for c in all_cases if c.get("id") != "case-0000"]
    check("purity: exactly 4 new cases, every one synthetic",
         len(new_cases) == 4 and all(c.get("synthetic") is True for c in new_cases), new_cases)
    check("purity: used_reply_ids is exactly what it was before (no reply ever marked used)",
         list(doc.get("used_reply_ids") or []) == [101, 102], doc.get("used_reply_ids"))


def test_training_synthetic_category_mix_80_20():
    """A batch of 10 synthetic scenarios honours 80/20 within rounding: 8
    actionable spread across Interested/Information Request/Meeting
    Request, 2 negatives from Not Interested/Out Of Office - and the exact
    counts the code computes are what get sent to the model as
    scenario_plan."""
    from collections import Counter

    targets = setter._synthetic_category_targets(10)
    actionable = {"Interested", "Information Request", "Meeting Request"}
    negative = {"Not Interested", "Out Of Office"}
    total_actionable = sum(v for k, v in targets.items() if k in actionable)
    total_negative = sum(v for k, v in targets.items() if k in negative)
    check("category mix: 8 actionable across the 3 simple categories", total_actionable == 8, targets)
    check("category mix: 2 negatives across Not Interested/Out Of Office", total_negative == 2, targets)
    check("category mix: no category outside the simple/common synthetic set",
         set(targets.keys()) <= (actionable | negative), targets)
    check("category mix: total sums to 10", sum(targets.values()) == 10, targets)

    sb, http = fresh_setter()
    captured = []

    def invent_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        captured.append(payload.get("scenario_plan"))
        plan = payload.get("scenario_plan") or []
        return {"scenarios": [{"lead_first_name": "A", "lead_company": "B", "subject": "s", "body": f"body {i}"}
                              for i, _ in enumerate(plan)]}

    http.invent_fn = invent_fn
    agent = {"id": "agent-mix0001"}
    scenarios = setter._invent_training_scenarios(agent, {"cases": [], "answers": {}}, 10)

    check("category mix prompt: invent was actually called", len(captured) == 1, captured)
    plan = captured[0] if captured else []
    check("category mix prompt: scenario_plan sent to the model matches the computed per-category counts",
         dict(Counter(plan)) == targets, (dict(Counter(plan)), targets))
    check("category mix: returned scenarios carry the same category the code assigned, in plan order",
         [s["category"] for s in scenarios] == plan, (scenarios, plan))


def test_training_invent_prompt_includes_reference_sample_gists_and_law():
    """With real replies present, the captured prompt contains the
    reply-sample text and the unanswered-case gists, and the system message
    states the lead-side-only law."""
    sb, http = fresh_setter()
    sb.replies.append({"id": "ref1", "workspace": "navreo", "smartlead_campaign_id": 9700,
                       "email": "lead@example.com", "replied_at": "2026-06-10T09:00:00+00:00",
                       "category": "Interested", "reply_subject": "Re: our email",
                       "reply_body": "Sounds great, tell me more about pricing please."})
    captured = []

    def invent_fn(body):
        captured.append(body)
        payload = json.loads(body["messages"][1]["content"])
        plan = payload.get("scenario_plan") or []
        return {"scenarios": [{"lead_first_name": "A", "lead_company": "B", "subject": "s", "body": f"body {i}"}
                              for i, _ in enumerate(plan)]}

    http.invent_fn = invent_fn
    agent = {"id": "agent-prompt0001"}
    doc = {"cases": [{"id": "case-0000", "category": "Information Request",
                      "inbound": {"body": "Can you send the pricing sheet over please, thanks a lot."}}],
          "answers": {}}
    setter._invent_training_scenarios(agent, doc, 5)

    check("prompt inputs: invent call happened", len(captured) == 1, captured)
    body = captured[0] if captured else {}
    system_msg = (body.get("messages") or [{}])[0].get("content", "")
    user_payload = json.loads(body["messages"][1]["content"]) if captured else {}
    check("prompt inputs: system prompt states the lead-side-only law",
         "LEAD-SIDE-ONLY LAW" in system_msg and "NEVER state, as a fact, any agent-side detail" in system_msg,
         system_msg[:200])
    check("prompt inputs: user payload carries the real reply-sample text",
         any("pricing" in (r.get("body") or "") for r in user_payload.get("reference_replies") or []),
         user_payload.get("reference_replies"))
    check("prompt inputs: user payload carries the unanswered-case gist",
         any("Can you send the pricing sheet" in g for g in user_payload.get("avoid_duplicating") or []),
         user_payload.get("avoid_duplicating"))


def test_training_generate_synthetic_never_bypasses_unanswered_cap():
    """An agent already over its unanswered cap (owner 40, share 20)
    refuses the whole generate call before any synthetic top-up ever
    runs - the 40/20 caps stay the only throttle, real or synthetic."""
    sb, http = fresh_setter()
    agent = {"id": "agent-synth-cap1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": f"case-{i:04d}"} for i in range(41)], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 8})
    check("cap: owner over the 40 cap refuses with 400 before any synthetic top-up runs",
         status == 400, (status, resp))
    doc_after = setter._load_training(agent["id"])
    check("cap: no cases were added (no real, no synthetic)",
         len(doc_after.get("cases") or []) == 41, doc_after.get("cases"))
    check("cap: no provider_usage row was posted", sb.provider_usage == [], sb.provider_usage)

    agent2 = {"id": "agent-synth-cap2", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"],
             "campaign_ids": [7200]}
    sb.agents[agent2["id"]] = {"id": agent2["id"], "doc": agent2}
    doc2 = {"cases": [{"id": f"case-{i:04d}"} for i in range(21)], "answers": {}, "used_reply_ids": [],
           "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent2["id"], doc2)
    token = setter.mint_training_share(agent2["id"])

    status2, resp2 = setter.route_training_generate({"share": token, "batch_size": 8})
    check("cap: share link over the 20 cap refuses with 400 before any synthetic top-up runs",
         status2 == 400, (status2, resp2))
    doc2_after = setter._load_training(agent2["id"])
    check("cap: share agent's cases untouched", len(doc2_after.get("cases") or []) == 21, doc2_after.get("cases"))


def test_training_generate_synthetic_lost_update_protection_answer_survives():
    """Same lost-update guarantee as
    test_training_generate_lost_update_protection_answer_survives, but with
    a synthetic top-up in play (the whole batch is synthetic, since the
    mocked selection returns zero real replies) - the worker's
    fresh-reload-before-save must still protect an answer that lands
    mid-batch."""
    sb, http = fresh_setter()
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-synth-lu1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    existing_doc = {"cases": [{"id": "case-pre-0000"}], "answers": {}, "used_reply_ids": [],
                    "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], existing_doc)

    started_event = threading.Event()
    release_event = threading.Event()
    real_select = setter._select_training_replies

    def fake_select(doc, batch_size, allowed_campaign_ids=None):
        started_event.set()
        release_event.wait(timeout=10)
        return []  # forces the entire batch to be synthetic

    setter._select_training_replies = fake_select
    try:
        status, resp = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 3})
        check("synthetic lost-update: generation starts", status == 200 and resp.get("status") == "started",
             (status, resp))
        check("synthetic lost-update: worker reached the (blocked) selection step",
             started_event.wait(timeout=5), None)

        astatus, aresp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-pre-0000", "decision_ok": True, "reply_ok": True,
            "note": "", "scope": "one_off",
        })
        check("synthetic lost-update: the mid-generation answer itself saves fine", astatus == 200, (astatus, aresp))

        release_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)

        final_doc = setter._load_training(agent["id"])
        check("synthetic lost-update: the answer that landed mid-generation survives the worker's final save",
             final_doc.get("answers", {}).get("case-pre-0000", {}).get("decision_ok") is True,
             final_doc.get("answers"))
        cases = final_doc.get("cases") or []
        new_cases = [c for c in cases if c.get("id") != "case-pre-0000"]
        check("synthetic lost-update: the new synthetic batch was appended on top, not lost",
             len(new_cases) == 3 and all(c.get("synthetic") is True for c in new_cases), cases)
    finally:
        setter._select_training_replies = real_select
        release_event.set()


def test_training_answer_readiness_moves_identically_for_synthetic_case():
    """Rating a synthetic case via the same answer path as a real one moves
    the readiness inputs (n_answers / score) exactly as it would for a real
    case - no weighting, no exclusion; compute_readiness only ever reads
    doc['answers'], never the case's own synthetic flag."""
    sb, http = fresh_setter()
    real_agent_id = "agent-real-ready1"
    synth_agent_id = "agent-synth-ready1"
    sb.agents[real_agent_id] = {"id": real_agent_id, "doc": {"id": real_agent_id}}
    sb.agents[synth_agent_id] = {"id": synth_agent_id, "doc": {"id": synth_agent_id}}

    real_doc = {"cases": [{"id": "case-real-0000", "reply_id": 55}], "answers": {}, "used_reply_ids": [55],
               "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    synth_doc = {"cases": [{"id": "case-synth-0000", "synthetic": True, "reply_id": None}], "answers": {},
                "used_reply_ids": [], "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(real_agent_id, real_doc)
    setter._save_training(synth_agent_id, synth_doc)

    status_r, resp_r = setter.route_training_answer({
        "agent_id": real_agent_id, "case_id": "case-real-0000", "decision_ok": True, "reply_ok": True,
        "note": "", "scope": "one_off",
    })
    status_s, resp_s = setter.route_training_answer({
        "agent_id": synth_agent_id, "case_id": "case-synth-0000", "decision_ok": True, "reply_ok": True,
        "note": "", "scope": "one_off",
    })
    check("readiness: both answer calls succeed", status_r == 200 and status_s == 200, (status_r, status_s))
    check("readiness: n_answers identical for one rating on a real vs a synthetic case",
         resp_r["readiness"]["n_answers"] == resp_s["readiness"]["n_answers"] == 1,
         (resp_r["readiness"], resp_s["readiness"]))
    check("readiness: score identical for the same rating, real vs synthetic (no special-casing)",
         resp_r["readiness"]["score"] == resp_s["readiness"]["score"],
         (resp_r["readiness"]["score"], resp_s["readiness"]["score"]))


def test_training_generate_synthetic_logs_provider_usage_and_failure_is_swallowed():
    """A generation run that builds >=1 synthetic case attempts exactly one
    provider_usage POST with the correct provider/source_id/credits/
    endpoint shape; a mocked failed POST never fails generation itself."""
    sb, http = fresh_setter()
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-synth-usage1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 4})
    check("usage log: generation starts (zero real replies -> fully synthetic)",
         status == 200 and resp.get("status") == "started", (status, resp))

    doc = setter._load_training(agent["id"])
    cases = doc.get("cases") or []
    synth_count = sum(1 for c in cases if c.get("synthetic") is True)
    check("usage log: some synthetic cases were built", synth_count > 0, cases)

    check("usage log: exactly one provider_usage row posted", len(sb.provider_usage) == 1, sb.provider_usage)
    row = sb.provider_usage[0] if sb.provider_usage else {}
    check("usage log: row shape is correct (provider/source_id/credits/endpoint)",
         row.get("provider") == "setter_synthetic" and row.get("source_id") == agent["id"]
         and row.get("credits") == synth_count and row.get("endpoint") == "zero_replies:owner", row)

    sb2, http2 = fresh_setter()
    http2.classify_fn = _training_classify_fn
    http2.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}
    sb2.provider_usage_post_error = RuntimeError("simulated Supabase outage")
    agent2 = {"id": "agent-synth-usage2", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb2.agents[agent2["id"]] = {"id": agent2["id"], "doc": agent2}

    status2, resp2 = _generate_and_wait({"agent_id": agent2["id"], "batch_size": 4})
    check("usage log: generation still succeeds even when the usage POST raises",
         status2 == 200 and resp2.get("status") == "started", (status2, resp2))
    doc2 = setter._load_training(agent2["id"])
    gen2 = doc2.get("generating") or {}
    check("usage log: generating still flips to idle (not failed) despite the logging error",
         gen2.get("status") == "idle" and (gen2.get("added") or 0) > 0, gen2)
    check("usage log: no provider_usage row recorded when the POST raised (helper swallows it)",
         sb2.provider_usage == [], sb2.provider_usage)


def test_training_answer_recomputes_readiness_and_counts():
    sb, http = fresh_setter()
    agent = {"id": "agent-train0006", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}, {"id": "case-0001"}], "answers": {}, "used_reply_ids": [101, 102],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_answer({
        "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": True, "reply_ok": True,
        "note": "", "scope": "one_off",
    })
    check("training answer: returns 200", status == 200, (status, resp))
    check("training answer: readiness score present and > 0", resp["readiness"]["score"] > 0, resp)
    check("training answer: answered_count is 1", resp["answered_count"] == 1, resp)
    check("training answer: unanswered_count is 1", resp["unanswered_count"] == 1, resp)

    saved = setter._load_training(agent["id"])
    check("training answer: readiness_history grew by one entry",
         len(saved.get("readiness_history") or []) == 1, saved.get("readiness_history"))
    check("training answer: used_reply_ids is untouched by answering",
         saved.get("used_reply_ids") == [101, 102], saved.get("used_reply_ids"))

    status2, resp2 = setter.route_training_answer({
        "agent_id": agent["id"], "case_id": "case-0001", "decision_ok": True, "reply_ok": None, "scope": "one_off",
    })
    check("training answer: reply_ok=null is accepted", status2 == 200, (status2, resp2))
    check("training answer: answered_count is 2 once both cases are answered", resp2["answered_count"] == 2, resp2)
    check("training answer: unanswered_count is 0", resp2["unanswered_count"] == 0, resp2)

    status3, resp3 = setter.route_training_answer({"agent_id": agent["id"], "case_id": "case-does-not-exist",
                                                    "decision_ok": True})
    check("training answer: unknown case_id -> 404", status3 == 404, (status3, resp3))

    status4, resp4 = setter.route_training_answer({"case_id": "case-0000", "decision_ok": True})
    check("training answer: missing agent_id -> 400", status4 == 400, (status4, resp4))


def test_training_answer_remember_merges_instructions_one_off_does_not():
    """Owner ruling 2026-07-14: scope="remember" on a training answer merges
    into the agent's instructions (never grows agent['memory'] any more);
    scope="one_off" stays audit-only in feedback_log."""
    sb, http = fresh_setter()
    agent = {"id": "agent-train0007", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"],
             "instructions": "Flat $200/mo."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}, {"id": "case-0001"}], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)
    http.merge_fn = None  # default append fallback

    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": False,
        "note": "Always offer the case study before pricing.", "scope": "remember",
    })
    saved = setter._load_agent(agent["id"])
    check("training answer remember: agent memory is NOT touched (nothing writes memory any more)",
         (saved.get("memory") or []) == [], saved.get("memory"))
    check("training answer remember: feedback_log untouched", (saved.get("feedback_log") or []) == [],
         saved.get("feedback_log"))
    check("training answer remember: instructions changed and contain the note",
         "Always offer the case study before pricing." in saved.get("instructions", ""), saved.get("instructions"))
    check("training answer remember: original instructions text is preserved",
         "Flat $200/mo." in saved.get("instructions", ""), saved.get("instructions"))
    edits_after_first = list(saved.get("instruction_edits") or [])
    check("training answer remember: instruction_edits grew by one",
         len(edits_after_first) == 1, edits_after_first)

    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-0001", "decision_ok": True,
        "note": "This one was fine, just a heads up.", "scope": "one_off",
    })
    saved2 = setter._load_agent(agent["id"])
    check("training answer one_off: agent memory still untouched",
         (saved2.get("memory") or []) == [], saved2.get("memory"))
    check("training answer one_off: feedback_log grew by one",
         len(saved2.get("feedback_log") or []) == 1, saved2.get("feedback_log"))
    check("training answer one_off: instruction_edits unchanged (still 1) - a one_off note never merges",
         len(saved2.get("instruction_edits") or []) == 1, saved2.get("instruction_edits"))


# ── training retrain (Feature B, owner ruling 2026-07-14) ───────────────────

def _fixed_training_case(cid, body="Sounds interesting, tell me more", campaign_id=1):
    return {
        "id": cid, "reply_id": f"r-{cid}", "campaign_id": campaign_id,
        "category": "Interested",
        "inbound": {"subject": "Re: our email", "body": body, "raw_body": body},
        "original_outreach": {}, "human_answer_history": {},
        "classification": {"primary_intent": "objection_or_question", "all_intents": ["objection_or_question"],
                           "confidence": 0.5},
        "decision": "review", "decision_reason": "old reason", "draft_html": "<div>old draft</div>",
        "generated_at": "2026-07-01T00:00:00+00:00",
    }


def test_training_retrain_note_updates_unanswered_leaves_answered():
    """ANY feedback re-runs the remaining unanswered training cases with the
    updated brain (owner ruling 2026-07-14): a note left on one case must
    reach classify() as owner_hints for every still-unanswered case, and the
    answered case must be left byte-for-byte untouched."""
    sb, http = fresh_setter()
    agent = {"id": "agent-retrain01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "instructions": "Flat $400/mo."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    case_a = _fixed_training_case("case-r-00", body="answered trigger case")
    case_b = _fixed_training_case("case-r-01", body="unanswered case")
    doc = {"cases": [case_a, case_b], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    captured_hints = []

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        captured_hints.append(payload.get("owner_corrections"))
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.97, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
            "wants": "wants info", "rationale": "",
        }
    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                                "html": '<div>Hi there,</div><br><div>Sure thing.</div><br><div>Bjion</div>'}

    status, resp = _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-r-00", "decision_ok": False,
        "note": "Always mention the free trial when they ask for more info.", "scope": "one_off",
    })
    check("retrain: answering with a note returns 200 and kicks off retrain",
         status == 200 and resp.get("retrain") == "started", (status, resp))

    saved = setter._load_training(agent["id"])
    gen = saved.get("generating") or {}
    check("retrain: generating settles back to idle with kind retrain and an updated count",
         gen.get("status") == "idle" and gen.get("kind") == "retrain" and gen.get("updated") == 1, gen)

    check("retrain: the owner's note reached classify() as owner_hints for the unanswered case",
         len(captured_hints) >= 1 and all(
             "Always mention the free trial when they ask for more info." in (h or "") for h in captured_hints),
         captured_hints)

    cases_by_id = {c["id"]: c for c in saved.get("cases") or []}
    check("retrain: the ANSWERED case is left completely untouched",
         cases_by_id["case-r-00"]["draft_html"] == "<div>old draft</div>"
         and not cases_by_id["case-r-00"].get("updated_by_feedback"), cases_by_id.get("case-r-00"))
    check("retrain: the UNANSWERED case got re-classified and re-drafted with the new brain",
         cases_by_id["case-r-01"].get("updated_by_feedback") is True
         and cases_by_id["case-r-01"]["classification"].get("primary_intent") == "send_resource"
         and "Sure thing" in (cases_by_id["case-r-01"]["draft_html"] or ""), cases_by_id.get("case-r-01"))


def test_training_retrain_trigger_conditions():
    sb, http = fresh_setter()
    agent = {"id": "agent-retrain02", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [_fixed_training_case("case-t-00"), _fixed_training_case("case-t-01"),
                     _fixed_training_case("case-t-02")],
          "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)
    http.classify_fn = lambda _b: {"primary_intent": "send_resource", "all_intents": ["send_resource"],
                                   "simple_ask": True, "confidence": 0.5, "red_flags": [],
                                   "timezone_guess": None, "tz_confidence": 0.0, "wants": "x", "rationale": ""}
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>ok</div><br><div>B</div>"}

    status, resp = setter.route_training_answer({
        "agent_id": agent["id"], "case_id": "case-t-00", "decision_ok": True, "reply_ok": True, "note": "",
    })
    check("retrain trigger: an all-good answer with no note never kicks off retrain",
         status == 200 and resp.get("retrain") is None, resp)

    status2, resp2 = _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-t-01", "decision_ok": False, "reply_ok": True, "note": "",
    })
    check("retrain trigger: a noteless wrong-decision answer still kicks off retrain",
         status2 == 200 and resp2.get("retrain") == "started", resp2)

    status3, resp3 = _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-t-02", "decision_ok": True, "reply_ok": False, "note": "",
    })
    check("retrain trigger: a noteless wrong-draft answer still kicks off retrain",
         status3 == 200 and resp3.get("retrain") == "started", resp3)


def test_training_retrain_lock_contention_with_generate_queued_flag_honoured():
    """The retrain pass uses the EXACT SAME per-agent lock route_training_
    generate uses, so the two kinds of background work never overlap. If a
    generate() batch is already running for this agent, kicking off a
    retrain must flag doc.generating.retrain_queued instead of starting a
    second worker - and that queued retrain must actually run (and be
    consumed - not left stuck true) once the generate batch finishes."""
    sb, http = fresh_setter()
    agent = {"id": "agent-retrain03", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    case_trigger = _fixed_training_case("case-lc-00", body="trigger case")
    case_target = _fixed_training_case("case-lc-01", body="target case")
    doc = {"cases": [case_trigger, case_target], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    started_event = threading.Event()
    release_event = threading.Event()
    real_select = setter._select_training_replies

    def fake_select(doc_, batch_size, allowed_campaign_ids=None):
        started_event.set()
        release_event.wait(timeout=10)
        return []  # nothing new to build - generate finishes fast once released

    setter._select_training_replies = fake_select
    http.classify_fn = lambda _b: {"primary_intent": "send_resource", "all_intents": ["send_resource"],
                                   "simple_ask": True, "confidence": 0.5, "red_flags": [],
                                   "timezone_guess": None, "tz_confidence": 0.0, "wants": "x", "rationale": ""}
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                                "html": "<div>Hi</div><br><div>Updated by retrain.</div><br><div>B</div>"}
    try:
        gstatus, gresp = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 4})
        check("retrain lock contention: generate starts and grabs the agent's lock",
             gstatus == 200 and gresp.get("status") == "started", (gstatus, gresp))
        check("retrain lock contention: generate worker reached its blocked selection step",
             started_event.wait(timeout=5), None)

        astatus, aresp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-lc-00", "decision_ok": False,
            "note": "Never promise same-day availability.", "scope": "one_off",
        })
        check("retrain lock contention: answering while generate holds the lock -> queued, not started",
             astatus == 200 and aresp.get("retrain") == "queued", (astatus, aresp))

        # The "queued" flag is persisted off the request thread now, by a
        # tiny daemon flagger (see setter._kick_off_training_retrain) -
        # join it before inspecting the doc so this assertion is
        # deterministic rather than racing the flagger's own write.
        flagger = setter._TRAINING_GEN_THREADS.get(f"{agent['id']}:flag")
        if flagger is not None:
            flagger.join(timeout=10)

        mid_doc = setter._load_training(agent["id"])
        check("retrain lock contention: doc shows retrain_queued while generate is still running",
             bool((mid_doc.get("generating") or {}).get("retrain_queued")), mid_doc.get("generating"))

        release_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)

        final_doc = setter._load_training(agent["id"])
        gen = final_doc.get("generating") or {}
        check("retrain lock contention: once generate finishes, the queued retrain actually ran (kind retrain, idle)",
             gen.get("status") == "idle" and gen.get("kind") == "retrain", gen)
        check("retrain lock contention: retrain_queued flag consumed, not left stuck true",
             not gen.get("retrain_queued"), gen)
        cases_by_id = {c["id"]: c for c in final_doc.get("cases") or []}
        check("retrain lock contention: the target case was actually reprocessed by the follow-on retrain pass",
             cases_by_id["case-lc-01"].get("updated_by_feedback") is True
             and "Updated by retrain." in (cases_by_id["case-lc-01"].get("draft_html") or ""),
             cases_by_id.get("case-lc-01"))
    finally:
        setter._select_training_replies = real_select
        release_event.set()


def test_training_retrain_failed_case_keeps_old_content():
    sb, http = fresh_setter()
    agent = {"id": "agent-retrain04", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    good_case = _fixed_training_case("case-f-00", body="This one classifies fine")
    bad_case = _fixed_training_case("case-f-01", body="This one blows up")
    trigger_case = _fixed_training_case("case-f-02", body="answered trigger")
    doc = {"cases": [good_case, bad_case, trigger_case], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        if payload.get("reply_body") == "This one blows up":
            raise RuntimeError("simulated classify failure")
        return {"primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
                "confidence": 0.9, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
                "wants": "x", "rationale": ""}
    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>new</div><br><div>B</div>"}

    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-f-02", "decision_ok": False,
        "note": "test note", "scope": "one_off",
    })

    saved = setter._load_training(agent["id"])
    cases_by_id = {c["id"]: c for c in saved.get("cases") or []}
    check("retrain failed case: the case whose classify() raised keeps its OLD content",
         cases_by_id["case-f-01"]["draft_html"] == "<div>old draft</div>"
         and not cases_by_id["case-f-01"].get("updated_by_feedback"), cases_by_id.get("case-f-01"))
    check("retrain failed case: the OTHER unanswered case still gets updated normally",
         cases_by_id["case-f-00"].get("updated_by_feedback") is True, cases_by_id.get("case-f-00"))


def test_training_retrain_concurrent_answer_survives():
    """Lost-update protection: an answer that lands on a DIFFERENT case while
    the retrain pass is still mid-flight on another case must survive the
    worker's final save (reload-before-save)."""
    sb, http = fresh_setter()
    agent = {"id": "agent-retrain05", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    case_trigger = _fixed_training_case("case-cc-00", body="trigger case")
    case_fast = _fixed_training_case("case-cc-01", body="fast case")
    case_slow = _fixed_training_case("case-cc-02", body="slow case")
    doc = {"cases": [case_trigger, case_fast, case_slow], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    started_slow = threading.Event()
    release_slow = threading.Event()

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        if payload.get("reply_body") == "slow case":
            started_slow.set()
            release_slow.wait(timeout=10)
        return {"primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
                "confidence": 0.9, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
                "wants": "x", "rationale": ""}
    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>new</div><br><div>B</div>"}

    try:
        status, resp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-cc-00", "decision_ok": False,
            "note": "test note", "scope": "one_off",
        })
        check("concurrent answer: triggering answer returns 200 and kicks off retrain",
             status == 200 and resp.get("retrain") == "started", (status, resp))
        check("concurrent answer: retrain worker reached the blocked (slow) case",
             started_slow.wait(timeout=5), None)

        astatus, aresp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-cc-01", "decision_ok": True, "reply_ok": True, "note": "",
        })
        check("concurrent answer: the mid-retrain answer itself saves fine", astatus == 200, (astatus, aresp))

        release_slow.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)

        final_doc = setter._load_training(agent["id"])
        check("concurrent answer: the answer that landed mid-retrain survives the worker's final save",
             final_doc.get("answers", {}).get("case-cc-01", {}).get("decision_ok") is True,
             final_doc.get("answers"))
        cases_by_id = {c["id"]: c for c in final_doc.get("cases") or []}
        check("concurrent answer: the slow case still got updated once released",
             cases_by_id["case-cc-02"].get("updated_by_feedback") is True, cases_by_id.get("case-cc-02"))
    finally:
        release_slow.set()


# ── training answer latency fix (2026-07-14): merge moved to the background
# retrain worker via pending_merges, so route_training_answer never blocks
# "Save & continue" on a gpt-5-mini call any more ─────────────────────────

def test_training_answer_remember_returns_fast_without_synchronous_merge():
    """The merge_correction_into_instructions call (gpt-5-mini, 5-15s in
    production) must never run inside route_training_answer's own request
    thread any more - it's deferred to the background retrain worker via
    pending_merges. Proven deterministically: the FakeHTTP merge call blocks
    on an Event this test only releases well after the request already
    returned. If the merge were still synchronous, route_training_answer
    itself would block on that same Event and badly miss the "well under a
    second" bar; instead it must return almost immediately regardless."""
    sb, http = fresh_setter()
    agent = {"id": "agent-async01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Base instructions."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    release_event = threading.Event()
    merge_calls = []

    def merge_fn(body):
        merge_calls.append(body)
        release_event.wait(timeout=10)
        payload = json.loads(body["messages"][1]["content"])
        return {"instructions": ((payload.get("current_instructions") or "") + "\n\n"
                                 + (payload.get("correction") or "")).strip()}
    http.merge_fn = merge_fn

    import time as _time
    started = _time.monotonic()
    status, resp = setter.route_training_answer({
        "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": False,
        "note": "Always mention the trial.", "scope": "remember",
    })
    elapsed = _time.monotonic() - started
    try:
        check("answer remember: returns 200 and kicks off a background retrain",
             status == 200 and resp.get("retrain") == "started", (status, resp))
        check("answer remember: request returns in well under a second even though the merge "
             "call (fired only in the background worker) is still blocked on the release event",
             elapsed < 1.0, elapsed)
    finally:
        release_event.set()

    thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
    if thread is not None:
        thread.join(timeout=10)

    check("answer remember: the merge eventually fired exactly once, in the background",
         len(merge_calls) == 1, merge_calls)
    saved_agent = setter._load_agent(agent["id"])
    check("answer remember: instructions eventually merged with the note",
         "Always mention the trial." in (saved_agent.get("instructions") or ""), saved_agent.get("instructions"))
    saved_doc = setter._load_training(agent["id"])
    check("answer remember: pending_merges drained to empty after the worker finished",
         (saved_doc.get("pending_merges") or []) == [], saved_doc.get("pending_merges"))


def test_training_answer_remember_persists_pending_merge_in_same_write():
    """The queued pending_merges entry is written by the SAME _save_training
    call that stores the answer itself - no extra round trip. Proven by
    holding the agent's own retrain lock BEFORE answering, so
    _kick_off_training_retrain can only queue (never start a worker that
    would immediately drain it), letting the persisted doc be inspected
    deterministically right after the request returns, with the merge
    itself still nowhere near having run."""
    sb, http = fresh_setter()
    agent = {"id": "agent-async02", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Base."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}, {"id": "case-0001"}], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    lock = setter._get_training_gen_lock(agent["id"])
    lock.acquire()
    try:
        status, resp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": False,
            "note": "Always confirm timezone first.", "scope": "remember",
        })
        check("answer remember: with the lock already held, retrain is queued, not started",
             status == 200 and resp.get("retrain") == "queued", (status, resp))

        saved = setter._load_training(agent["id"])
        pending = saved.get("pending_merges") or []
        check("answer remember: pending_merges holds exactly the queued note",
             len(pending) == 1 and pending[0]["note"] == "Always confirm timezone first."
             and pending[0]["source"] == "training:case-0000", pending)
        check("answer remember: the answer itself landed in the SAME persisted doc (one write)",
             saved.get("answers", {}).get("case-0000", {}).get("decision_ok") is False,
             saved.get("answers"))
        check("answer remember: agent instructions NOT yet touched (merge deferred to the worker)",
             setter._load_agent(agent["id"]).get("instructions") == "Base.",
             setter._load_agent(agent["id"]).get("instructions"))
    finally:
        lock.release()


def test_training_retrain_worker_drains_pending_merges_in_order_across_queued_pass():
    """Two rapid "remember" answers: the second lands while the first's
    retrain pass is still busy on an unrelated case, so it must queue
    (retrain_queued) rather than start a second worker. Both notes must
    still end up merged into instructions in submission order - the first
    during the initial pass's own top-of-loop drain, the second during the
    follow-on queued pass's drain (see _training_retrain_worker /
    _drain_pending_merges - the drain always runs at the TOP of every
    pass)."""
    sb, http = fresh_setter()
    agent = {"id": "agent-drain01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Base."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    case_a = _fixed_training_case("case-d-00", body="trigger one")
    case_b = _fixed_training_case("case-d-01", body="trigger two")
    case_target = _fixed_training_case("case-d-02", body="target case")
    doc = {"cases": [case_a, case_b, case_target], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    started_slow = threading.Event()
    release_slow = threading.Event()

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        if payload.get("reply_body") == "target case":
            started_slow.set()
            release_slow.wait(timeout=10)
        return {"primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
                "confidence": 0.9, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
                "wants": "x", "rationale": ""}
    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>ok</div><br><div>B</div>"}

    def merge_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        old = payload.get("current_instructions") or ""
        note = payload.get("correction") or ""
        return {"instructions": (old + "\n\n" + note).strip()}
    http.merge_fn = merge_fn

    try:
        status, resp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-d-00", "decision_ok": False,
            "note": "First note.", "scope": "remember",
        })
        check("drain order: first remember answer starts the retrain worker",
             status == 200 and resp.get("retrain") == "started", (status, resp))
        check("drain order: worker reached the blocked target case (drain + first merge already ran)",
             started_slow.wait(timeout=5), None)

        # The drain-then-merge step for "First note." runs strictly BEFORE the
        # retrain-classify loop that's now blocked on case-d-02, so it must
        # already be on the agent's instructions.
        mid_agent = setter._load_agent(agent["id"])
        check("drain order: the first note is merged into instructions before the retrain step even starts",
             "First note." in (mid_agent.get("instructions") or ""), mid_agent.get("instructions"))

        status2, resp2 = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-d-01", "decision_ok": False,
            "note": "Second note.", "scope": "remember",
        })
        check("drain order: second remember answer while the worker is busy -> queued, not a second worker",
             status2 == 200 and resp2.get("retrain") == "queued", (status2, resp2))

        mid_doc = setter._load_training(agent["id"])
        pending = mid_doc.get("pending_merges") or []
        check("drain order: the second note is queued on the doc, not yet merged",
             len(pending) == 1 and pending[0]["note"] == "Second note.", pending)
        mid_agent2 = setter._load_agent(agent["id"])
        check("drain order: the second note is NOT yet in instructions while the worker is still on pass one",
             "Second note." not in (mid_agent2.get("instructions") or ""), mid_agent2.get("instructions"))

        release_slow.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)

        final_agent = setter._load_agent(agent["id"])
        instr = final_agent.get("instructions") or ""
        check("drain order: both notes ended up merged", "First note." in instr and "Second note." in instr, instr)
        check("drain order: submission order preserved (First before Second)",
             instr.index("First note.") < instr.index("Second note."), instr)
        check("drain order: instruction_edits logged both, in order",
             [e.get("note") for e in (final_agent.get("instruction_edits") or [])]
             == ["First note.", "Second note."], final_agent.get("instruction_edits"))

        final_doc = setter._load_training(agent["id"])
        check("drain order: pending_merges drained to empty after the follow-on pass",
             (final_doc.get("pending_merges") or []) == [], final_doc.get("pending_merges"))
        gen = final_doc.get("generating") or {}
        check("drain order: generating settles idle with the queued flag consumed",
             gen.get("status") == "idle" and not gen.get("retrain_queued"), gen)
    finally:
        release_slow.set()


def test_training_retrain_merge_failure_falls_back_to_append_and_retrain_still_runs():
    """A garbage merge response (no usable "instructions" key) must fall
    back to a dumb, always-safe append - exactly what
    merge_correction_into_instructions already guarantees - and must never
    block the retrain pass that runs right after it in the same worker
    loop."""
    sb, http = fresh_setter()
    agent = {"id": "agent-drain02", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Base instructions."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    trigger_case = _fixed_training_case("case-mf-00", body="trigger")
    target_case = _fixed_training_case("case-mf-01", body="unanswered target")
    doc = {"cases": [trigger_case, target_case], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    http.merge_fn = lambda body: {"unexpected_field": "garbage - no instructions key at all"}
    http.classify_fn = lambda _b: {"primary_intent": "send_resource", "all_intents": ["send_resource"],
                                   "simple_ask": True, "confidence": 0.9, "red_flags": [],
                                   "timezone_guess": None, "tz_confidence": 0.0, "wants": "x", "rationale": ""}
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>new</div><br><div>B</div>"}

    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-mf-00", "decision_ok": False,
        "note": "Never overpromise turnaround time.", "scope": "remember",
    })

    saved_agent = setter._load_agent(agent["id"])
    check("merge failure: falls back to a dumb append (garbage merge response never trusted)",
         "Training note (" in (saved_agent.get("instructions") or "")
         and "Never overpromise turnaround time." in (saved_agent.get("instructions") or ""),
         saved_agent.get("instructions"))
    check("merge failure: original instructions text preserved",
         "Base instructions." in (saved_agent.get("instructions") or ""), saved_agent.get("instructions"))
    edits = saved_agent.get("instruction_edits") or []
    check("merge failure: instruction_edits logged how=appended",
         len(edits) == 1 and edits[0]["how"] == "appended", edits)

    saved_doc = setter._load_training(agent["id"])
    cases_by_id = {c["id"]: c for c in saved_doc.get("cases") or []}
    check("merge failure: the retrain pass still ran on the unanswered case despite the merge failure",
         cases_by_id["case-mf-01"].get("updated_by_feedback") is True, cases_by_id.get("case-mf-01"))
    check("merge failure: pending_merges drained regardless of the merge outcome",
         (saved_doc.get("pending_merges") or []) == [], saved_doc.get("pending_merges"))


def test_training_get_reports_pending_merges_count():
    sb, http = fresh_setter()
    agent = {"id": "agent-pmget01", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status0, resp0 = setter.route_training_get({"agent_id": agent["id"]})
    check("training get: pending_merges defaults to 0 count", resp0.get("pending_merges") == 0, resp0)

    lock = setter._get_training_gen_lock(agent["id"])
    lock.acquire()
    try:
        setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": False,
            "note": "A note stuck behind a busy worker.", "scope": "remember",
        })
        status, resp = setter.route_training_get({"agent_id": agent["id"]})
        check("training get: pending_merges surfaces the queued (not-yet-drained) note count",
             status == 200 and resp.get("pending_merges") == 1, resp)
    finally:
        lock.release()


def test_training_answer_one_off_note_never_enters_pending_merges():
    sb, http = fresh_setter()
    agent = {"id": "agent-oneoff01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Base."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": True,
        "note": "Just a heads up, no change needed.", "scope": "one_off",
    })
    saved_doc = setter._load_training(agent["id"])
    check("answer one_off: note never enters pending_merges",
         (saved_doc.get("pending_merges") or []) == [], saved_doc.get("pending_merges"))
    saved_agent = setter._load_agent(agent["id"])
    check("answer one_off: instructions untouched", saved_agent.get("instructions", "") == "Base.",
         saved_agent.get("instructions"))


def test_training_retrain_worker_retrain_step_uses_freshly_merged_instructions():
    """The worker's retrain step must see the instructions the drain step
    JUST merged (drain-then-reload-agent-fresh, per
    _training_retrain_worker), not a stale pre-merge snapshot."""
    sb, http = fresh_setter()
    agent = {"id": "agent-freshinstr01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Flat $300/mo."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    trigger_case = _fixed_training_case("case-fi-00", body="trigger")
    target_case = _fixed_training_case("case-fi-01", body="unanswered target")
    doc = {"cases": [trigger_case, target_case], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    seen_instructions = []

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        seen_instructions.append((payload.get("agent") or {}).get("instructions") or "")
        return {"primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
                "confidence": 0.9, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
                "wants": "x", "rationale": ""}
    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>new</div><br><div>B</div>"}
    http.merge_fn = lambda body: {
        "instructions": (json.loads(body["messages"][1]["content"]).get("current_instructions") or "")
                        + "\n\nAlways confirm budget before pricing."
    }

    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-fi-00", "decision_ok": False,
        "note": "Always confirm budget before pricing.", "scope": "remember",
    })

    check("retrain uses fresh instructions: classify() for the unanswered case saw the just-merged note",
         len(seen_instructions) >= 1
         and all("Always confirm budget before pricing." in s for s in seen_instructions),
         seen_instructions)


# ── training answer/retrain instant-advance latency fix (2026-07-14, part 2)
# ─────────────────────────────────────────────────────────────────────────
# _kick_off_training_retrain no longer does ANY Supabase round trip on the
# request thread itself - both the "running" marker (lock free) and the
# retrain_queued flag (lock held) moved into background threads - and
# route_training_answer skips the AGENT load entirely once the case_id is
# found in the training doc's own cases. The six tests below prove each
# piece directly against the FakeSB call log / a blocked worker thread.

def test_kick_off_training_retrain_request_thread_makes_no_save_before_worker_runs():
    """Lock-free path: _kick_off_training_retrain itself must do zero
    Supabase round trips of its own - only the spawned worker thread does,
    starting with its own first action (_load_training, then the running-
    marker _save_training). Proven deterministically by blocking the
    worker's FIRST _load_training call itself (not the save after it) on an
    Event: since _save_training can only ever be reached AFTER that load
    returns, this guarantees zero _save_training calls have happened by the
    time _kick_off_training_retrain returns "started" - regardless of how
    the OS happens to schedule the two threads - rather than relying on a
    narrow, scheduler-dependent timing window."""
    sb, http = fresh_setter()
    agent = {"id": "agent-kickfree01", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    real_load_training = setter._load_training
    real_save_training = setter._save_training
    load_calls = []
    save_calls = []
    started_event = threading.Event()
    release_event = threading.Event()

    def fake_load_training(agent_id_):
        load_calls.append(agent_id_)
        if len(load_calls) == 1:  # only the worker's very first load blocks
            started_event.set()
            release_event.wait(timeout=10)
        return real_load_training(agent_id_)

    def fake_save_training(agent_id_, doc_):
        save_calls.append((agent_id_, copy.deepcopy(doc_)))
        real_save_training(agent_id_, doc_)

    setter._load_training = fake_load_training
    setter._save_training = fake_save_training
    try:
        status = setter._kick_off_training_retrain(agent["id"])
        check("kick off retrain (lock free): returns 'started' immediately", status == "started", status)
        check("kick off retrain (lock free): the REQUEST thread itself made zero _save_training calls",
             len(save_calls) == 0, save_calls)

        check("kick off retrain (lock free): the worker thread reached its own (blocked) first load",
             started_event.wait(timeout=5), None)
        check("kick off retrain (lock free): still zero saves while the worker sits blocked on that load",
             len(save_calls) == 0, save_calls)

        release_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)
        check("kick off retrain (lock free): once released, the worker's own save eventually lands",
             len(save_calls) >= 1, save_calls)
    finally:
        setter._load_training = real_load_training
        setter._save_training = real_save_training
        release_event.set()


def test_kick_off_training_retrain_worker_first_action_writes_running_marker():
    """The retrain worker's very FIRST action on every pass - before it
    drains pending_merges, loads the agent, or does any retrain work - is
    persisting doc.generating = {status: running, kind: retrain}. Proven by
    blocking the first _save_training call and inspecting exactly what it
    was about to write: a pending_merges entry seeded up front is still
    sitting there untouched at that point, since the drain (which would
    clear it) only runs AFTER this save."""
    sb, http = fresh_setter()
    agent = {"id": "agent-kickfree02", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00",
          "pending_merges": [{"note": "Should not merge before the marker write.",
                              "source": "training:case-0000", "at": "2026-01-01T00:00:00+00:00"}]}
    setter._save_training(agent["id"], doc)

    real_save_training = setter._save_training
    save_calls = []
    started_event = threading.Event()
    release_event = threading.Event()

    def fake_save_training(agent_id_, doc_):
        save_calls.append((agent_id_, copy.deepcopy(doc_)))
        started_event.set()
        release_event.wait(timeout=10)
        real_save_training(agent_id_, doc_)

    setter._save_training = fake_save_training
    try:
        status = setter._kick_off_training_retrain(agent["id"])
        check("kick off retrain: returns started", status == "started", status)
        check("kick off retrain: worker reached its first (blocked) save",
             started_event.wait(timeout=5), None)
        check("kick off retrain: the worker's first save is exactly the running marker",
             len(save_calls) == 1
             and (save_calls[0][1].get("generating") or {}).get("status") == "running"
             and (save_calls[0][1].get("generating") or {}).get("kind") == "retrain",
             save_calls)
        check("kick off retrain: pending_merges is untouched at that point - the drain runs AFTER this save",
             len(save_calls[0][1].get("pending_merges") or []) == 1, save_calls)

        release_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)
    finally:
        setter._save_training = real_save_training
        release_event.set()


def test_kick_off_training_retrain_lock_held_flagger_persists_queued_flag():
    """Lock-held path (a generate() batch or another retrain already running
    for this agent): _kick_off_training_retrain spawns a tiny daemon
    "flagger" thread - registered under _TRAINING_GEN_THREADS[f"{agent_id}:
    flag"], a separate key from the running worker's own entry - to persist
    generating.retrain_queued=True, rather than writing it itself. The
    response is "queued" immediately regardless of whether the flagger has
    finished."""
    sb, http = fresh_setter()
    agent = {"id": "agent-flagger01", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    lock = setter._get_training_gen_lock(agent["id"])
    lock.acquire()
    try:
        status = setter._kick_off_training_retrain(agent["id"])
        check("kick off retrain (lock held): returns 'queued'", status == "queued", status)

        flagger = setter._TRAINING_GEN_THREADS.get(f"{agent['id']}:flag")
        check("kick off retrain (lock held): a flagger thread is registered under the ':flag' key",
             flagger is not None, list(setter._TRAINING_GEN_THREADS.keys()))
        if flagger is not None:
            flagger.join(timeout=10)

        saved = setter._load_training(agent["id"])
        check("kick off retrain (lock held): the flagger thread persisted retrain_queued=True",
             bool((saved.get("generating") or {}).get("retrain_queued")), saved.get("generating"))
    finally:
        lock.release()


def test_training_answer_existing_doc_skips_agent_load():
    """Latency fix (2026-07-14, part 2): when case_id is found in the
    training doc's own cases, route_training_answer never fetches the agent
    row at all - a training doc's cases only ever came from a real agent's
    generate()/retrain pass, so finding the case there is already proof
    enough. Proven directly against the FakeSB call log: no GET without an
    id filter (the shape _load_agents() always issues) ever fires, and the
    whole request costs exactly one read + one write."""
    sb, http = fresh_setter()
    agent = {"id": "agent-skiploadA1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    sb.calls.clear()
    status, resp = setter.route_training_answer({
        "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": True, "reply_ok": True,
        "note": "", "scope": "one_off",
    })
    check("answer (existing doc): still returns 200", status == 200, (status, resp))
    check("answer (existing doc): no note/wrong mark -> retrain never kicked off (isolates this call count)",
         resp.get("retrain") is None, resp)

    agent_list_gets = [c for c in sb.calls if c[0] == "GET" and c[1].startswith(setter.AGENTS_TABLE)
                       and "id=eq." not in c[1]]
    check("answer (existing doc): the agent row (a full agents-table list load) was never fetched",
         agent_list_gets == [], sb.calls)
    check("answer (existing doc): exactly 2 Supabase round trips total - one training-doc read, one save",
         len(sb.calls) == 2 and sb.calls[0][0] == "GET" and sb.calls[1][0] == "POST", sb.calls)


def test_training_answer_404_when_neither_doc_nor_agent_exists():
    """A case_id lookup miss falls back to loading the agent purely to tell
    apart "the agent itself is gone" (404 Agent not found) from "this
    training doc just doesn't have this case_id" (404 Training scenario not
    found). With no training doc AND no agent row at all for this id, it
    must be the former."""
    sb, http = fresh_setter()
    status, resp = setter.route_training_answer({
        "agent_id": "agent-never-existed-01", "case_id": "case-0000", "decision_ok": True,
    })
    check("answer: 404 when neither the training doc nor the agent exists",
         status == 404, (status, resp))
    check("answer: the error is specifically 'Agent not found', not 'Training scenario not found'",
         resp.get("error") == "Agent not found.", resp)


def test_training_answer_note_path_still_returns_started_without_agent_load():
    """The note (or wrong-mark) path that triggers a retrain must still
    report retrain:"started" (lock free) exactly as before, AND must skip
    the agent load on its own synchronous path just like the no-note path.
    scope="remember" is used here (not "one_off") specifically so the note
    goes onto pending_merges - the pre-existing one_off feedback_log path
    (_append_agent_feedback_log) does its own separate agent load/save and
    is untouched by this latency fix, so mixing it in here would test the
    wrong thing. The background worker's own _load_agent call (a separate,
    expected read - already covered by the retrain-worker tests) is blocked
    out here so it can't race into the call log this test inspects."""
    sb, http = fresh_setter()
    agent = {"id": "agent-noteA1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    real_threadmain = setter._training_retrain_threadmain
    block_event = threading.Event()

    def blocked_threadmain(agent_id_, lock_):
        block_event.wait(timeout=10)
        real_threadmain(agent_id_, lock_)

    setter._training_retrain_threadmain = blocked_threadmain
    try:
        sb.calls.clear()
        status, resp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": "case-0000", "decision_ok": False,
            "note": "Always confirm timezone.", "scope": "remember",
        })
        check("answer (note path): still returns 200 and retrain:'started'",
             status == 200 and resp.get("retrain") == "started", (status, resp))

        agent_list_gets = [c for c in sb.calls if c[0] == "GET" and c[1].startswith(setter.AGENTS_TABLE)
                           and "id=eq." not in c[1]]
        check("answer (note path): the request thread never fetched the agent row either",
             agent_list_gets == [], sb.calls)
        check("answer (note path): exactly 2 Supabase round trips in the request thread - "
             "the retrain kick adds none of its own",
             len(sb.calls) == 2 and sb.calls[0][0] == "GET" and sb.calls[1][0] == "POST", sb.calls)
    finally:
        setter._training_retrain_threadmain = real_threadmain
        block_event.set()
        thread = setter._TRAINING_GEN_THREADS.get(agent["id"])
        if thread is not None:
            thread.join(timeout=10)


def test_training_pending_merges_survive_and_drain_on_next_kick_after_dead_worker():
    """Crash-safety: pending_merges lives on the persisted training doc, so a
    note queued right before a process restart (simulated here by a stale
    "running" marker with no live lock/thread - exactly what
    route_training_get's self-heal already detects) is drained by the next
    answer's own kick-off, not lost."""
    sb, http = fresh_setter()
    agent = {"id": "agent-crash01", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "instructions": "Base."}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    case_a = _fixed_training_case("case-cr-00", body="already answered before restart")
    case_b = _fixed_training_case("case-cr-01", body="still unanswered")
    old_started = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=900)).isoformat(timespec="seconds")
    doc = {
        "cases": [case_a, case_b],
        "answers": {"case-cr-00": {"decision_ok": False, "reply_ok": None,
                                   "note": "Queued right before the crash.", "scope": "remember",
                                   "at": old_started}},
        "pending_merges": [{"note": "Queued right before the crash.", "source": "training:case-cr-00",
                            "at": old_started}],
        "used_reply_ids": [], "readiness_history": [],
        # Stale "running" marker - the process died mid-pass, no live lock/thread.
        "generating": {"status": "running", "kind": "retrain", "started_at": old_started},
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    setter._save_training(agent["id"], doc)

    status_get, resp_get = setter.route_training_get({"agent_id": agent["id"]})
    check("crash-safety: pending_merges count is visible even behind a stale running marker",
         status_get == 200 and resp_get.get("pending_merges") == 1, resp_get)

    http.merge_fn = lambda body: {
        "instructions": (json.loads(body["messages"][1]["content"]).get("current_instructions") or "")
                        + "\n\nQueued right before the crash."
    }
    http.classify_fn = lambda _b: {"primary_intent": "send_resource", "all_intents": ["send_resource"],
                                   "simple_ask": True, "confidence": 0.9, "red_flags": [],
                                   "timezone_guess": None, "tz_confidence": 0.0, "wants": "x", "rationale": ""}
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "<div>Hi</div><br><div>new</div><br><div>B</div>"}

    # The next answer's own kick-off starts a FRESH worker (this process
    # never held the old lock - it died with the old process), which drains
    # the leftover pending_merges before doing anything else.
    _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-cr-01", "decision_ok": False, "reply_ok": True, "note": "",
    })

    saved_agent = setter._load_agent(agent["id"])
    check("crash-safety: the note queued before the crash was eventually merged",
         "Queued right before the crash." in (saved_agent.get("instructions") or ""),
         saved_agent.get("instructions"))
    saved_doc = setter._load_training(agent["id"])
    check("crash-safety: pending_merges drained to empty",
         (saved_doc.get("pending_merges") or []) == [], saved_doc.get("pending_merges"))


def test_draft_system_fallback_ladder_text():
    """Feature C: DRAFT_SYSTEM's fallback ladder - step ONE (propose a
    meeting using what the instructions say) must appear before step TWO
    (the existing plain availability-ask), and the never-invent / never-
    mention-a-failure rules must still be present."""
    check("draft ladder: step ONE example block present (instructions-stated availability)",
         "NO LIVE SLOTS BUT THE INSTRUCTIONS GIVE AVAILABILITY" in setter.DRAFT_SYSTEM, None)
    check("draft ladder: step TWO example block present (no availability anywhere)",
         "NO TIMES AVAILABLE ANYWHERE" in setter.DRAFT_SYSTEM, None)
    check("draft ladder: the FIRST/SECOND ordering rule is spelled out in the rules section",
         "FIRST, if the instructions state an availability window" in setter.DRAFT_SYSTEM
         and "SECOND, only when the instructions say nothing at all about availability" in setter.DRAFT_SYSTEM,
         None)
    check("draft ladder: never-invent-a-time rule present",
         "Never invent a time, day, or window that isn't in the slots you were given or literally stated "
         "in the instructions." in setter.DRAFT_SYSTEM, None)
    check("draft ladder: never-mention-a-failed-tool rule still present",
         "Never mention that a calendar, tool, or booking system failed or wasn't available" in setter.DRAFT_SYSTEM,
         None)
    idx_one = setter.DRAFT_SYSTEM.index("NO LIVE SLOTS BUT THE INSTRUCTIONS GIVE AVAILABILITY")
    idx_two = setter.DRAFT_SYSTEM.index("NO TIMES AVAILABLE ANYWHERE")
    check("draft ladder: step ONE's example precedes step TWO's example in the prompt", idx_one < idx_two,
         (idx_one, idx_two))
    check("draft ladder: no em dashes anywhere in DRAFT_SYSTEM", "—" not in setter.DRAFT_SYSTEM, None)


def test_training_reset_clears_answers_keeps_used_ids():
    sb, http = fresh_setter()
    agent = {"id": "agent-train0008", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {
        "cases": [{"id": "case-0000"}, {"id": "case-0001"}],
        "answers": {"case-0000": {"decision_ok": True, "reply_ok": True, "note": "",
                                  "at": "2026-01-01T00:00:00+00:00"}},
        "used_reply_ids": [201, 202, 203],
        "readiness_history": [{"at": "2026-01-01T00:00:00+00:00", "score": 50, "n_answers": 1}],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_reset({"agent_id": agent["id"]})
    check("training reset: returns 200 ok", status == 200 and resp.get("ok") is True, (status, resp))

    saved = setter._load_training(agent["id"])
    check("training reset: answers cleared", saved.get("answers") == {}, saved.get("answers"))
    check("training reset: readiness_history cleared",
         saved.get("readiness_history") == [], saved.get("readiness_history"))
    check("training reset: used_reply_ids preserved so scenarios never repeat",
         saved.get("used_reply_ids") == [201, 202, 203], saved.get("used_reply_ids"))
    check("training reset: the stored cases list is untouched", len(saved.get("cases") or []) == 2,
         saved.get("cases"))

    status2, resp2 = setter.route_training_reset({})
    check("training reset: missing agent_id -> 400", status2 == 400, (status2, resp2))


def test_training_get_route():
    sb, http = fresh_setter()
    agent = {"id": "agent-train0009", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {
        "cases": [{"id": "case-0000"}, {"id": "case-0001"}, {"id": "case-0002"}],
        "answers": {"case-0000": {"decision_ok": True, "reply_ok": True, "at": "2026-01-01T00:00:00+00:00"}},
        "used_reply_ids": [1, 2, 3], "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00",
    }
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_get({"agent_id": agent["id"]})
    check("training get: returns 200", status == 200, (status, resp))
    ids_in_order = [c["id"] for c in resp["cases"]]
    check("training get: unanswered cases come before the answered one",
         ids_in_order.index("case-0001") < ids_in_order.index("case-0000") and
         ids_in_order.index("case-0002") < ids_in_order.index("case-0000"), ids_in_order)
    check("training get: readiness is present and freshly computed",
         resp["readiness"]["n_answers"] == 1, resp["readiness"])
    check("training get: used_count is reported", resp["used_count"] == 3, resp)
    check("training get: generating defaults to idle when no batch has ever run",
         resp.get("generating") == {"status": "idle"}, resp.get("generating"))

    status2, resp2 = setter.route_training_get({})
    check("training get: missing agent_id -> 400", status2 == 400, (status2, resp2))


def test_training_get_self_heals_stale_running_marker():
    """Mirrors route_grading_get's relearn self-heal: a "running" marker
    left behind by a process restart mid-batch (the in-memory thread and
    per-agent lock both die with the process) is healed to idle in the
    RESPONSE once it's old enough - never persisted, exactly like relearn,
    since the next real generate() call overwrites it anyway."""
    sb, http = fresh_setter()
    agent = {"id": "agent-train-stale1", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    old_started = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=900)).isoformat(timespec="seconds")
    doc = {"cases": [], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "generating": {"status": "running", "started_at": old_started, "batch_size": 8},
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_get({"agent_id": agent["id"]})
    check("training get: a stale running marker (900s old, no live lock) self-heals to idle in the response",
         status == 200 and resp.get("generating", {}).get("status") == "idle"
         and resp.get("generating", {}).get("stale_recovered") is True, resp.get("generating"))

    persisted = setter._load_training(agent["id"])
    check("training get: the self-heal is NOT persisted back to storage (mirrors route_grading_get's relearn heal)",
         persisted.get("generating", {}).get("status") == "running", persisted.get("generating"))

    # A recent (not stale) running marker is left running, not healed.
    recent_started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    doc2 = {"cases": [], "answers": {}, "used_reply_ids": [], "readiness_history": [],
           "generating": {"status": "running", "started_at": recent_started, "batch_size": 8},
           "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc2)
    status2, resp2 = setter.route_training_get({"agent_id": agent["id"]})
    check("training get: a fresh running marker (under 600s old) stays running, not healed",
         status2 == 200 and resp2.get("generating", {}).get("status") == "running"
         and "stale_recovered" not in (resp2.get("generating") or {}), resp2.get("generating"))


def test_compute_readiness_pure_function():
    empty = setter.compute_readiness({"answers": {}})
    check("readiness: 0 answers -> score 0", empty["score"] == 0, empty)
    check("readiness: 0 answers -> n_answers 0", empty["n_answers"] == 0, empty)

    def _answers(n, correct=True, start="2026-01-01T00:00:00+00:00", key_offset=0):
        base = dt.datetime.fromisoformat(start)
        out = {}
        for i in range(n):
            at = (base + dt.timedelta(minutes=i)).isoformat()
            out[f"case-{key_offset + i:04d}"] = {"decision_ok": correct, "reply_ok": correct, "at": at}
        return out

    high = setter.compute_readiness({"answers": _answers(20, True)})
    check("readiness: 20 correct answers -> score >= 90", high["score"] >= 90, high)
    check("readiness: explanation names the answer count", "20" in high["explanation"], high["explanation"])

    all_wrong = setter.compute_readiness({"answers": _answers(20, False)})
    check("readiness: 20 wrong answers -> score near 0", all_wrong["score"] <= 10, all_wrong)

    fifteen_correct = _answers(15, True, key_offset=0)
    ten_then_five_wrong = {}
    ten_then_five_wrong.update(_answers(10, True, start="2026-01-01T00:00:00+00:00", key_offset=0))
    ten_then_five_wrong.update(_answers(5, False, start="2026-01-01T00:20:00+00:00", key_offset=10))
    r_fifteen = setter.compute_readiness({"answers": fifteen_correct})
    r_mixed = setter.compute_readiness({"answers": ten_then_five_wrong})
    check("readiness: 10 correct then 5 wrong scores lower than 15 correct (same n, same coverage)",
         r_mixed["score"] < r_fifteen["score"], (r_mixed, r_fifteen))

    r5 = setter.compute_readiness({"answers": _answers(5, True)})
    r10 = setter.compute_readiness({"answers": _answers(10, True)})
    r20 = setter.compute_readiness({"answers": _answers(20, True)})
    r25 = setter.compute_readiness({"answers": _answers(25, True)})
    check("readiness: coverage rises from n=5 to n=10 (all correct)", r10["coverage"] > r5["coverage"], (r5, r10))
    check("readiness: coverage caps at 1.0 by n=20", r20["coverage"] == 1.0, r20)
    check("readiness: coverage never exceeds 1.0 past n=20", r25["coverage"] == 1.0, r25)


def test_readiness_30_answer_scripted_simulation():
    def _scripted(pattern, start="2026-01-01T00:00:00+00:00"):
        base = dt.datetime.fromisoformat(start)
        out = {}
        for i, ok in enumerate(pattern):
            at = (base + dt.timedelta(minutes=i)).isoformat()
            out[f"case-{i:04d}"] = {"decision_ok": ok, "reply_ok": ok, "at": at}
        return out

    # mostly correct with a few early misses; the last 20 (the RECENT
    # stretch) are overwhelmingly correct.
    pattern_good_tail = [True, False, True, True, False, True, True, True, False, True] + [True] * 20
    r_good_tail = setter.compute_readiness({"answers": _scripted(pattern_good_tail)})
    check("readiness 30-sim: overwhelmingly-correct recent stretch -> score >= 90",
         r_good_tail["score"] >= 90, r_good_tail)

    # same total mistake count, but concentrated in the RECENT stretch instead.
    pattern_bad_tail = [True] * 20 + [True, False, True, False, True, False, True, False, True, False]
    r_bad_tail = setter.compute_readiness({"answers": _scripted(pattern_bad_tail)})
    check("readiness 30-sim: mistakes concentrated in the recent stretch -> score stays below 90",
         r_bad_tail["score"] < 90, r_bad_tail)
    check("readiness 30-sim: a bad recent stretch scores lower than a good recent stretch",
         r_bad_tail["score"] < r_good_tail["score"], (r_bad_tail, r_good_tail))

    r_all_wrong = setter.compute_readiness({"answers": _scripted([False] * 30)})
    check("readiness 30-sim: all-wrong -> score near 0", r_all_wrong["score"] <= 5, r_all_wrong)


# ── public training share links ───────────────────────────────────────────────
# The owner mints a per-agent, no-login link a client can use to train ONLY
# that agent. Covers: mint/verify roundtrip and tamper/expiry rejection, the
# owner-only mint route, the public share-info route, share-token enforcement
# (force + mismatch 403 + invalid 401) across the three training routes, the
# share-mode-only campaign filter and tighter (20 vs 40) unanswered cap, and
# that memory delete refuses a share token in any form.

def test_share_mint_verify_roundtrip():
    sb, http = fresh_setter()
    token = setter.mint_training_share("agent-shr0001", days=30)
    check("share: mint returns a non-empty token", bool(token), token)
    agent_id = setter.verify_training_share(token)
    check("share: verify roundtrips to the same agent_id", agent_id == "agent-shr0001", agent_id)

    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    check("share: a tampered signature -> None", setter.verify_training_share(tampered) is None, tampered)
    check("share: a garbage string -> None", setter.verify_training_share("not-a-real-token") is None)
    check("share: an empty token -> None", setter.verify_training_share("") is None)
    check("share: None -> None", setter.verify_training_share(None) is None)

    # Build an already-expired token directly (mint_training_share clamps
    # days to >= 1, so this exercises the expiry check on its own).
    import base64
    import hashlib
    import hmac
    import time
    payload = f"train|agent-shr0001|{int(time.time()) - 10}".encode()
    sig = hmac.new(setter._share_secret(), payload, hashlib.sha256).hexdigest()
    expired_token = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig
    check("share: an expired token -> None", setter.verify_training_share(expired_token) is None, expired_token)


def test_route_training_share_mints_and_share_info():
    sb, http = fresh_setter()
    agent = {"id": "agent-shr0002", "name": "Ada", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = setter.route_training_share({"agent_id": agent["id"]})
    check("share mint: 200", status == 200, (status, resp))
    check("share mint: url_path points at setter-train.html with a token",
         str(resp.get("url_path") or "").startswith("/app/setter-train.html?share="), resp)
    check("share mint: the minted token verifies to the right agent",
         setter.verify_training_share(resp.get("token")) == agent["id"], resp)
    check("share mint: expires_at is present", bool(resp.get("expires_at")), resp)

    status2, resp2 = setter.route_training_share({"agent_id": "does-not-exist"})
    check("share mint: unknown agent -> 404", status2 == 404, (status2, resp2))

    status3, resp3 = setter.route_training_share({})
    check("share mint: missing agent_id -> 400", status3 == 400, (status3, resp3))

    status4, resp4 = setter.route_training_share_info({"share": resp["token"]})
    check("share-info: 200 for a valid token", status4 == 200, (status4, resp4))
    check("share-info: returns only agent_name + agent_id - no memory/instructions/campaigns leak",
         set(resp4.keys()) == {"agent_name", "agent_id"}, resp4)
    check("share-info: agent_name matches", resp4.get("agent_name") == "Ada", resp4)
    check("share-info: agent_id matches", resp4.get("agent_id") == agent["id"], resp4)

    status5, resp5 = setter.route_training_share_info({"share": "garbage"})
    check("share-info: invalid token -> 401", status5 == 401, (status5, resp5))
    status6, resp6 = setter.route_training_share_info({})
    check("share-info: missing token -> 401", status6 == 401, (status6, resp6))


def test_training_get_share_forces_agent_and_rejects_mismatch():
    sb, http = fresh_setter()
    agent = {"id": "agent-shr0003", "name": "Ada", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"]}
    other = {"id": "agent-shr0004", "name": "Bea", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.agents[other["id"]] = {"id": other["id"], "doc": other}
    token = setter.mint_training_share(agent["id"])

    status, resp = setter.route_training_get({"share": token})
    check("training get share: no agent_id given - the share alone resolves the agent",
         status == 200, (status, resp))

    status2, resp2 = setter.route_training_get({"agent_id": agent["id"], "share": token})
    check("training get share: matching agent_id + share -> 200", status2 == 200, (status2, resp2))

    status3, resp3 = setter.route_training_get({"agent_id": other["id"], "share": token})
    check("training get share: a share for a different agent than the payload asked for -> 403",
         status3 == 403, (status3, resp3))

    status4, resp4 = setter.route_training_get({"share": "garbage-token"})
    check("training get share: invalid token -> 401 with a plain-English message",
         status4 == 401 and "expired" in str(resp4.get("error") or "").lower(), (status4, resp4))


def test_training_get_includes_minimal_agent_memory():
    sb, http = fresh_setter()
    agent = {"id": "agent-shr0005", "name": "Ada", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"],
             "memory": [{"text": "Always confirm the timezone.", "source": "manual", "scope": "remember",
                        "at": "2026-07-01T00:00:00+00:00"}],
             "instruction_edits": [{"note": "Always mention the trial.", "at": "2026-07-05T00:00:00+00:00",
                                    "source": "training:case-01", "how": "merged"}]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = setter.route_training_get({"agent_id": agent["id"]})
    check("training get: 200", status == 200, (status, resp))
    mem = resp.get("agent_memory") or []
    check("training get: agent_memory carries the one lesson", len(mem) == 1, mem)
    check("training get: agent_memory rows are text+at only - source/scope never leak through here",
         bool(mem) and set(mem[0].keys()) == {"text", "at"}, mem)
    check("training get: agent_memory text matches the agent's real memory",
         bool(mem) and mem[0]["text"] == "Always confirm the timezone.", mem)

    edits = resp.get("instruction_edits") or []
    check("training get: instruction_edits (item 9) carries the one edit", len(edits) == 1, edits)
    check("training get: instruction_edits rows are note+how+at only - source never leaks through here",
         bool(edits) and set(edits[0].keys()) == {"note", "how", "at"}, edits)
    check("training get: instruction_edits note/how match the agent's real edit",
         bool(edits) and edits[0]["note"] == "Always mention the trial." and edits[0]["how"] == "merged", edits)

    status2, resp2 = setter.route_training_get({"agent_id": "does-not-exist"})
    check("training get: unknown agent -> 404", status2 == 404, (status2, resp2))


def test_training_generate_share_forces_agent_campaign_filter_and_400_on_no_campaigns():
    sb, http = fresh_setter()
    _seed_training_corpus(sb, per_category=6, campaign_id=7001, start_id=1)
    # a second campaign's replies - must never be drawn by this agent's link
    _seed_training_corpus(sb, per_category=6, campaign_id=7002, start_id=1000)
    http.classify_fn = _training_classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {"id": "agent-shr0006", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r",
             "campaign_ids": [7001]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    token = setter.mint_training_share(agent["id"])

    status, resp = _generate_and_wait({"share": token, "batch_size": 8}, agent_id=agent["id"])
    check("training generate share: 200 and starts", status == 200 and resp.get("status") == "started",
         (status, resp))
    doc = setter._load_training(agent["id"])
    cases = doc.get("cases") or []
    check("training generate share: generates a full 8-case batch", len(cases) == 8, cases)
    campaign_ids_used = {c["campaign_id"] for c in cases}
    check("training generate share: every case is drawn from the agent's own campaign only, "
         "never the other campaign's replies", campaign_ids_used <= {7001}, campaign_ids_used)

    status2, resp2 = setter.route_training_generate(
        {"share": token, "agent_id": "some-other-agent", "batch_size": 2})
    check("training generate share: agent_id in the body disagreeing with the share -> 403",
         status2 == 403, (status2, resp2))

    status3, resp3 = setter.route_training_generate({"share": "garbage", "batch_size": 2})
    check("training generate share: invalid token -> 401", status3 == 401, (status3, resp3))

    status4, resp4 = setter.route_training_generate({"agent_id": agent["id"], "batch_size": 2, "___public": True})
    check("training generate: ___public flag with no share at all -> 401 "
         "(the mechanism server.py uses to gate an unauthenticated caller)",
         status4 == 401, (status4, resp4))

    agent2 = {"id": "agent-shr0007", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent2["id"]] = {"id": agent2["id"], "doc": agent2}
    token2 = setter.mint_training_share(agent2["id"])
    status5, resp5 = setter.route_training_generate({"share": token2, "batch_size": 4})
    check("training generate share: an agent with no campaigns assigned -> 400, plain-English",
         status5 == 400 and "campaign" in str(resp5.get("error") or "").lower(), (status5, resp5))


def test_training_generate_share_unanswered_cap_is_tighter_than_owner():
    sb, http = fresh_setter()
    agent = {"id": "agent-shr0008", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"],
             "campaign_ids": [7101]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    doc = {"cases": [{"id": f"case-{i:04d}"} for i in range(21)], "answers": {}, "used_reply_ids": [],
          "readiness_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)
    token = setter.mint_training_share(agent["id"])

    status, resp = setter.route_training_generate({"share": token, "batch_size": 4})
    check("training generate share: 21 unanswered already refuses (share cap is 20, not the owner's 40)",
         status == 400, (status, resp))

    # the exact same 21-unanswered backlog does NOT trip the owner's 40 cap
    status2, resp2 = _generate_and_wait({"agent_id": agent["id"], "batch_size": 4})
    check("training generate owner: 21 unanswered is fine under the owner's 40 cap (starts)",
         status2 == 200 and resp2.get("status") == "started", (status2, resp2))


def test_training_answer_share_forces_agent_rejects_mismatch_and_response_stays_scoped():
    sb, http = fresh_setter()
    agent = {"id": "agent-shr0009", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    other = {"id": "agent-shr0010", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.agents[other["id"]] = {"id": other["id"], "doc": other}
    doc = {"cases": [{"id": "case-0000"}], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)
    token = setter.mint_training_share(agent["id"])

    http.merge_fn = None  # default append fallback

    status, resp = _answer_and_wait({
        "share": token, "case_id": "case-0000", "decision_ok": True, "reply_ok": True, "scope": "remember",
        "note": "Client-taught lesson.",
    }, agent_id=agent["id"])
    check("training answer share: 200 - scope=remember still works from a share link", status == 200, (status, resp))
    check("training answer share: response carries only this session's own stats, no cross-agent data",
         set(resp.keys()) <= {"ok", "readiness", "answered_count", "unanswered_count", "retrain"}, resp)
    saved = setter._load_agent(agent["id"])
    check("training answer share: the client's note reached THIS agent's instructions (single living manual, "
         "owner ruling 2026-07-14 - remember no longer writes memory)",
         "Client-taught lesson." in saved.get("instructions", ""), saved)
    check("training answer share: agent memory is NOT touched", (saved.get("memory") or []) == [],
         saved.get("memory"))

    status2, resp2 = setter.route_training_answer(
        {"share": token, "agent_id": other["id"], "case_id": "case-0000", "decision_ok": True})
    check("training answer share: agent_id in the body disagreeing with the share -> 403",
         status2 == 403, (status2, resp2))

    status3, resp3 = setter.route_training_answer({"share": "garbage", "case_id": "case-0000", "decision_ok": True})
    check("training answer share: invalid token -> 401", status3 == 401, (status3, resp3))

    status4, resp4 = setter.route_training_answer({"case_id": "case-0000", "decision_ok": True, "___public": True})
    check("training answer: ___public flag with no share at all -> 401", status4 == 401, (status4, resp4))


def test_memory_delete_never_accepts_share_token():
    sb, http = fresh_setter()
    agent = {"id": "agent-shr0011", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"],
             "memory": [{"text": "Old lesson.", "source": "manual", "scope": "remember",
                        "at": "2026-01-01T00:00:00+00:00"}]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    token = setter.mint_training_share(agent["id"])

    status, resp = setter.route_agents_memory_delete({
        "agent_id": agent["id"], "at": "2026-01-01T00:00:00+00:00", "text": "Old lesson.", "share": token,
    })
    check("memory delete: a share token on the payload is rejected outright (403) - even a genuinely valid one",
         status == 403, (status, resp))
    saved = setter._load_agent(agent["id"])
    check("memory delete: the lesson is untouched after the rejected attempt",
         len(saved.get("memory") or []) == 1, saved.get("memory"))

    status2, resp2 = setter.route_agents_memory_delete({
        "agent_id": agent["id"], "at": "2026-01-01T00:00:00+00:00", "text": "Old lesson.", "___public": True,
    })
    check("memory delete: the ___public flag alone is also rejected", status2 == 403, (status2, resp2))

    status3, resp3 = setter.route_agents_memory_delete({
        "agent_id": agent["id"], "at": "2026-01-01T00:00:00+00:00", "text": "Old lesson.",
    })
    check("memory delete: the ordinary owner path (no share, no ___public) is unaffected",
         status3 == 200, (status3, resp3))


# ── instructions-only brain (v3, owner ruling 2026-07-14) ────────────────────
# Agents have NO resource fields at all any more - the `instructions` text is
# the single brain, holding pricing, resource links, and plain-English
# when-to-send-which rules. _extract_urls/_norm_url/_instruction_urls are the
# new single-source-of-truth reads every URL-aware check goes through.

def test_extract_urls_helper():
    check("_extract_urls: a bare URL in prose is found",
         setter._extract_urls("Resource: https://x.example/guide - send on request.") ==
         ["https://x.example/guide"])

    check("_extract_urls: an href attribute value is found",
         setter._extract_urls('<a href="https://x.example/a">click</a>') == ["https://x.example/a"])

    check("_extract_urls: both an href and a bare URL in the same text are both found, order preserved",
         setter._extract_urls('<a href="https://x.example/a">click</a> or see https://x.example/b directly') ==
         ["https://x.example/a", "https://x.example/b"])

    check("_extract_urls: trailing prose punctuation is stripped",
         setter._extract_urls("See https://x.example/guide, or https://x.example/other.") ==
         ["https://x.example/guide", "https://x.example/other"])

    check("_extract_urls: a trailing slash is stripped so it compares equal to the same URL without one",
         setter._extract_urls("https://x.example/guide/") == ["https://x.example/guide"])

    check("_extract_urls: de-duplicates case-insensitively (values normalised to lowercase)",
         setter._extract_urls("https://x.example/Guide and again https://X.EXAMPLE/Guide") ==
         ["https://x.example/guide"])

    check("_extract_urls: no URLs at all -> empty list", setter._extract_urls("just plain text, no links") == [])
    check("_extract_urls: empty/None text -> empty list",
         setter._extract_urls("") == [] and setter._extract_urls(None) == [])


def test_instruction_urls_helper():
    check("_instruction_urls: pulls every URL out of the agent's instructions text",
         setter._instruction_urls({"instructions": "Pricing: $500/mo. Resource: the guide - "
                                                    "https://x.example/guide - send on request."}) ==
         ["https://x.example/guide"])
    check("_instruction_urls: two distinct links in the instructions both come back",
         len(setter._instruction_urls({"instructions": "A: https://x.example/a. B: https://x.example/b."})) == 2)
    check("_instruction_urls: no instructions -> empty list", setter._instruction_urls({}) == [])
    check("_instruction_urls: None agent -> empty list", setter._instruction_urls(None) == [])
    check("_instruction_urls: falls back to legacy pricing_notes like _agent_instructions does",
         setter._instruction_urls({"pricing_notes": "See https://x.example/legacy for details."}) ==
         ["https://x.example/legacy"])


AGENT_TWO_LINKS = {
    "id": "agent-twolink0001", "mode": "autopilot", "enabled": True,
    "allowed_intents": ["send_resource", "pricing", "scheduling"], "confidence_threshold": 0.9,
    "instructions": "Pricing: flat $500/mo, 3 seats included. "
                    "Resource: AEO/GEO teardown - https://x.example/aeo - send when the outreach "
                    "offered the AEO/GEO teardown. Clay to Claude guide - https://x.example/clay - "
                    "send when the outreach offered the Clay-to-Claude guide.",
}


def test_classify_payload_carries_instructions_no_resources_key():
    sb, http = fresh_setter()
    captured = {}

    def classify_fn(body):
        captured["body"] = body
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.95, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
            "live_lead": False, "wants": "wants the guide", "rationale": "unqualified yes",
        }

    http.classify_fn = classify_fn
    setter.classify({"subject": "Re: hi", "body": "sure, send it over"}, AGENT_TWO_LINKS)

    payload = json.loads(captured["body"]["messages"][1]["content"])
    check("classify payload: agent.instructions carries the FULL instructions text (pricing rides on it)",
         payload.get("agent", {}).get("instructions") == AGENT_TWO_LINKS["instructions"],
         payload.get("agent"))
    check("classify payload: no resources array at all any more",
         "resources" not in payload.get("agent", {}), payload.get("agent"))
    check("classify payload: no legacy resource_name/resource_description keys either",
         "resource_name" not in payload["agent"] and "resource_description" not in payload["agent"],
         payload["agent"])


def test_draft_payload_carries_instructions_no_resources_key():
    sb, http = fresh_setter()
    captured = {}

    def draft_fn(body):
        captured["body"] = body
        return {"subject": "Re: hi", "html": '<div>Hi There,</div><br><div>Here it is.</div>'}

    http.draft_fn = draft_fn
    classification = {"primary_intent": "send_resource", "all_intents": ["send_resource"], "wants": "wants it"}
    setter.draft_reply({"first_name": "There", "subject": "Re: hi", "body": "sure"}, AGENT_TWO_LINKS,
                       classification, [], "not_configured", "Bjion")

    payload = json.loads(captured["body"]["messages"][1]["content"])
    check("draft payload: instructions carries the full text",
         payload.get("instructions") == AGENT_TWO_LINKS["instructions"], payload.get("instructions"))
    check("draft payload: no resources key", "resources" not in payload, payload)
    check("draft payload: no legacy resource_name/resource_link/resource_description keys",
         "resource_name" not in payload and "resource_link" not in payload and
         "resource_description" not in payload, payload)


def test_draft_reply_payload_carries_slot_status_and_booking_link_unchanged():
    """No regression from the calendly-fallback rework (owner ruling
    2026-07-14): draft_reply()'s payload still carries slot_status, the
    booking link, and the (possibly empty) slots list through to the model
    exactly as before, whatever slot_status is."""
    sb, http = fresh_setter()
    captured = {}

    def draft_fn(body):
        captured["body"] = body
        return {"subject": "Re: hi", "html": '<div>Hi There,</div><br><div>Here it is.</div>'}

    http.draft_fn = draft_fn
    agent = {"id": "agent-fallback-payload", "instructions": "",
             "calendly_event_url": "https://calendly.com/navreo/book-a-call"}
    classification = {"primary_intent": "scheduling", "all_intents": ["scheduling"], "wants": "wants a call"}
    setter.draft_reply({"first_name": "There", "subject": "Re: hi", "body": "sure"}, agent,
                       classification, [], "not_configured", "Bjion")

    payload = json.loads(captured["body"]["messages"][1]["content"])
    check("draft_reply payload: slot_status still passed through unchanged",
         payload.get("slot_status") == "not_configured", payload.get("slot_status"))
    check("draft_reply payload: booking_link still passed through unchanged",
         payload.get("booking_link") == "https://calendly.com/navreo/book-a-call", payload.get("booking_link"))
    check("draft_reply payload: slots list still passed through (empty in fallback mode)",
         payload.get("slots") == [], payload.get("slots"))


def test_decide_gate_6b_instruction_link_ambiguity():
    """Gate 6b (v3): send_resource + the instructions offering 2+ distinct
    links + no original outreach loaded -> a person should pick."""
    cls_send = _cls("send_resource")

    d, r = setter.decide(cls_send, AGENT_TWO_LINKS, {**CTX_ALL_GOOD, "first_outbound_present": False})
    check("decide: 2-URL instructions + send_resource + no original outreach -> review", d == "review", r)
    check("decide: exact plain-English reason for the instruction-link ambiguity gate",
         r == ("Held for review: the instructions offer more than one link and the original outreach "
              "couldn't be loaded, so a person should pick."), r)

    d, r = setter.decide(cls_send, AGENT_TWO_LINKS, {**CTX_ALL_GOOD, "first_outbound_present": True})
    check("decide: 2-URL instructions + send_resource + original outreach present -> auto_send",
         d == "auto_send", r)

    # scoped to send_resource - a pricing-only ask on the same two-link agent
    # is unaffected by a missing original outreach.
    d, r = setter.decide(_cls("pricing"), AGENT_TWO_LINKS, {**CTX_ALL_GOOD, "first_outbound_present": False})
    check("decide: gate never fires when send_resource isn't in play", d == "auto_send", r)

    # a single-URL (or no-URL) agent's instructions are never held by this
    # gate, first_outbound_present or not.
    d, r = setter.decide(cls_send, AGENT_AUTO, {**CTX_ALL_GOOD, "first_outbound_present": False})
    check("decide: single-URL (or no-URL) instructions are unaffected by the missing-outreach gate",
         d == "auto_send", r)

    single_link_agent = {**AGENT_AUTO, "instructions": "Resource: https://x.example/only - send on request."}
    d, r = setter.decide(cls_send, single_link_agent, {**CTX_ALL_GOOD, "first_outbound_present": False})
    check("decide: an agent whose instructions carry exactly one URL is also unaffected", d == "auto_send", r)

    # default (key entirely absent) is treated as falsy, same as every other
    # ctx.get(...) boolean gate in decide()
    ctx_no_key = {k: v for k, v in CTX_ALL_GOOD.items() if k != "first_outbound_present"}
    d, r = setter.decide(cls_send, AGENT_TWO_LINKS, ctx_no_key)
    check("decide: first_outbound_present absent entirely defaults to falsy -> review", d == "review", r)


# ── positive-only intake gate (CORE_FOUR) ───────────────────────────────────
# ruling 2026-07-14: only Interested / Information Request / Meeting Request /
# positive-re-reply may ever reach process_reply, via either intake path.

def test_core_four_categories_enter_queue_both_paths():
    real_process_reply = setter.process_reply
    try:
        for cat in sorted(setter.CORE_FOUR):
            # -- run_poll path --
            sb, http = fresh_setter()
            agent = {"id": "agent-core-poll", "mode": "draft_only", "enabled": True, "campaign_ids": [9001]}
            sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
            sb.replies.append({
                "workspace": "navreo", "smartlead_campaign_id": 9001, "email": "lead@example.com",
                "subject": "Re: hi", "reply_body": "sounds good", "replied_at": "2026-07-10T00:00:00+00:00",
                "smartlead_message_id": "core-poll-1", "category": cat,
            })
            captured = {}
            setter.process_reply = lambda reply, agent_, settings_, _c=captured: (
                _c.__setitem__("reply", reply) or {"status": "needs_review", "id": 1})
            summary = setter.run_poll()
            check(f"run_poll: category {cat!r} reaches process_reply",
                 captured.get("reply", {}).get("category") == cat, (cat, summary, captured))

            # -- handle_inbound path --
            sb2, http2 = fresh_setter()
            agent2 = {"id": "agent-core-wh", "mode": "draft_only", "enabled": True, "campaign_ids": [9002]}
            sb2.agents[agent2["id"]] = {"id": agent2["id"], "doc": agent2}
            sb2.replies.append({"workspace": "navreo", "smartlead_campaign_id": 9002,
                                "smartlead_message_id": "core-wh-1", "category": cat})
            captured2 = {}
            setter.process_reply = lambda reply, agent_, settings_, _c=captured2: (
                _c.__setitem__("reply", reply) or {"status": "needs_review", "id": 2})
            resp = setter.handle_inbound({
                "event_type": "EMAIL_REPLY", "campaign_id": 9002, "sl_lead_email": "lead2@example.com",
                "reply_message": {"text": "sounds good", "message_id": "core-wh-1",
                                  "time": "2026-07-10T00:00:00+00:00"},
            })
            check(f"handle_inbound: category {cat!r} reaches process_reply",
                 captured2.get("reply", {}).get("category") == cat, (cat, resp, captured2))
    finally:
        setter.process_reply = real_process_reply


def test_non_core_categories_stay_out_both_paths():
    non_core = ["Call Booked", "Contact Forward", "Contact In Future", "Not Interested", None]
    real_process_reply = setter.process_reply
    try:
        for cat in non_core:
            # -- run_poll path --
            sb, http = fresh_setter()
            agent = {"id": "agent-noncore-poll", "mode": "draft_only", "enabled": True, "campaign_ids": [9101]}
            sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
            sb.replies.append({
                "workspace": "navreo", "smartlead_campaign_id": 9101, "email": "lead@example.com",
                "subject": "Re: hi", "reply_body": "no thanks", "replied_at": "2026-07-10T00:00:00+00:00",
                "smartlead_message_id": "noncore-poll-1", "category": cat,
            })
            called = {"n": 0}
            setter.process_reply = lambda reply, agent_, settings_, _c=called: (
                _c.__setitem__("n", _c["n"] + 1) or {"status": "needs_review", "id": 1})
            summary = setter.run_poll()
            check(f"run_poll: category {cat!r} never reaches process_reply, no queue row",
                 called["n"] == 0 and len(sb.queue) == 0, (cat, summary, sb.queue))

            # -- handle_inbound path --
            sb2, http2 = fresh_setter()
            agent2 = {"id": "agent-noncore-wh", "mode": "draft_only", "enabled": True, "campaign_ids": [9102]}
            sb2.agents[agent2["id"]] = {"id": agent2["id"], "doc": agent2}
            if cat is not None:
                # None/uncategorised means the replies row itself is missing or
                # blank category - nothing to seed. A real (but non-core) label
                # does have a replies row, just one the gate must still reject.
                sb2.replies.append({"workspace": "navreo", "smartlead_campaign_id": 9102,
                                    "smartlead_message_id": "noncore-wh-1", "category": cat})
            called2 = {"n": 0}
            setter.process_reply = lambda reply, agent_, settings_, _c=called2: (
                _c.__setitem__("n", _c["n"] + 1) or {"status": "needs_review", "id": 2})
            resp = setter.handle_inbound({
                "event_type": "EMAIL_REPLY", "campaign_id": 9102, "sl_lead_email": "lead2@example.com",
                "reply_message": {"text": "no thanks", "message_id": "noncore-wh-1",
                                  "time": "2026-07-10T00:00:00+00:00"},
            })
            check(f"handle_inbound: category {cat!r} never reaches process_reply, ignored instead",
                 called2["n"] == 0 and "ignored" in resp and len(sb2.queue) == 0, (cat, resp, sb2.queue))
    finally:
        setter.process_reply = real_process_reply


def test_handle_inbound_uncategorised_then_poll_catches_up():
    sb, http = fresh_setter()
    agent = {"id": "agent-catchup", "mode": "draft_only", "enabled": True, "campaign_ids": [9201]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    payload = {"event_type": "EMAIL_REPLY", "campaign_id": 9201, "sl_lead_email": "lead@example.com",
              "reply_message": {"text": "sounds good", "message_id": "catchup-1",
                                "time": "2026-07-10T00:00:00+00:00"}}
    # No matching `replies` row yet - the Make categoriser hasn't landed on
    # this fresh webhook reply (its usual ~15min lag).
    resp = setter.handle_inbound(payload)
    check("handle_inbound: uncategorised reply is ignored pending categorisation",
         resp.get("ignored", "").startswith("awaiting categorisation"), resp)
    check("handle_inbound: uncategorised reply creates no queue row", len(sb.queue) == 0, sb.queue)

    # Make lands the category a little later - the next poll tick now sees a
    # categorised row and picks it up (the 48h window covers the lag).
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 9201, "email": "lead@example.com",
        "subject": "Re: hi", "reply_body": "sounds good", "replied_at": "2026-07-10T00:00:00+00:00",
        "smartlead_message_id": "catchup-1", "category": "Interested",
    })
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.5, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants info", "rationale": "",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Sam"}
    summary = setter.run_poll()
    check("run_poll: the now-categorised reply is picked up on the next tick",
         summary.get("checked") == 1 and len(sb.queue) == 1, (summary, sb.queue))


# ── one-time backfill script (app/setter_backfill.py) ──────────────────────

def test_backfill_assigned_at_bypass_only_in_backfill():
    sb, http = fresh_setter()
    agent = {"id": "agent-bypass", "mode": "draft_only", "enabled": True, "campaign_ids": [9301],
             "campaign_assigned_at": {"9301": "2026-07-05T00:00:00+00:00"}}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 9301, "email": "old@example.com",
        "subject": "Re: hi", "reply_body": "sounds good", "replied_at": "2026-07-01T00:00:00+00:00",
        "smartlead_message_id": "bypass-old-1", "category": "Interested",
    })

    # run_poll: this core-four reply predates campaign_assigned_at -> skipped.
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.5, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants info", "rationale": "",
    }
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Sam"}
    summary = setter.run_poll()
    check("run_poll: a core-four reply older than campaign_assigned_at is still skipped",
         summary.get("checked") == 0 and len(sb.queue) == 0, (summary, sb.queue))

    # setter_backfill.select_candidates: same reply, same agent - but the
    # backfill's own docstring says it deliberately reaches back past the
    # assignment stamp, so it must select this row where run_poll would not.
    real_sb = setter_backfill._SB
    try:
        setter_backfill._SB = setter._SB  # mirror main()'s post-configure rebind
        agents = setter._load_agents()
        enabled = [a for a in agents if a.get("enabled", True) and (a.get("campaign_ids") or [])]
        campaign_ids = sorted({str(c) for a in enabled for c in (a.get("campaign_ids") or [])})
        candidates, skipped_dupe, total_seen = setter_backfill.select_candidates(enabled, campaign_ids)
    finally:
        setter_backfill._SB = real_sb

    emails = {c[2] for c in candidates}
    check("backfill: the pre-assignment reply IS selected (the bypass is only here)",
         "old@example.com" in emails, (emails, skipped_dupe, total_seen))
    check("backfill: nothing was already queued for it (dedupe count is 0)", skipped_dupe == 0, skipped_dupe)


def test_backfill_dry_run_zero_writes():
    sb, http = fresh_setter()
    agent = {"id": "agent-dryrun", "mode": "draft_only", "enabled": True, "campaign_ids": [9401]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 9401, "email": "dry@example.com",
        "subject": "Re: hi", "reply_body": "sounds good", "replied_at": "2026-07-10T00:00:00+00:00",
        "smartlead_message_id": "dry-1", "category": "Interested",
    })

    real_load_keys, real_make_sb = setter_backfill.load_keys, setter_backfill.make_sb
    real_process_reply = setter.process_reply
    real_argv = sys.argv
    called = {"n": 0}
    setter_backfill.load_keys = lambda: {}
    setter_backfill.make_sb = lambda keys: sb  # never hits real Supabase - reuses this test's FakeSB
    setter.process_reply = lambda *a, **k: (called.__setitem__("n", called["n"] + 1)
                                            or {"status": "needs_review", "id": 1})
    calls_before = len(sb.calls)
    sys.argv = ["setter_backfill.py"]  # no flags at all -> dry run is the default
    try:
        rc = setter_backfill.main()
    finally:
        sys.argv = real_argv
        setter_backfill.load_keys = real_load_keys
        setter_backfill.make_sb = real_make_sb
        setter.process_reply = real_process_reply

    check("backfill --dry-run (default, no flags): exits cleanly", rc == 0, rc)
    check("backfill --dry-run: process_reply is never called", called["n"] == 0, called)
    writes = [c for c in sb.calls[calls_before:] if c[0] in ("POST", "PATCH")]
    check("backfill --dry-run: zero POST/PATCH writes to Supabase", writes == [], writes)


# ── recency weighting: LATEST OWNER RULES (trainer-obedience brief 2026-07-14) ──
# Newest lessons DOMINATE: _latest_owner_rules() builds a newest-first block from
# the agent's own instruction_edits notes plus (when given) a training doc's
# answers' notes, and every live/retrain/generation call site prefixes it onto
# whatever digest it already builds for classify()'s owner_hints and
# draft_reply()'s regen_feedback.

def test_latest_owner_rules_helper():
    agent = {
        "id": "agent-rules01",
        "instruction_edits": [
            {"note": "Always mention the free trial.", "at": "2026-07-01T00:00:00+00:00",
             "source": "manual", "how": "merged"},
            {"note": "Never promise a specific onboarding date.", "at": "2026-07-05T00:00:00+00:00",
             "source": "manual", "how": "merged"},
        ],
    }
    block = setter._latest_owner_rules(agent)
    check("latest rules: block starts with the LATEST OWNER RULES header",
         block.startswith(setter._LATEST_RULES_HEADER), block)
    check("latest rules: newest-first ordering (07-05 note before 07-01 note)",
         block.index("Never promise a specific onboarding date.") < block.index("Always mention the free trial."),
         block)
    check("latest rules: numbered list starts at 1", "\n1. Never promise" in block, block)

    # Dedupe: an identical note re-taught later collapses to a single line.
    agent_dupe = {"id": "agent-rules02", "instruction_edits": [
        {"note": "Same note.", "at": "2026-07-01T00:00:00+00:00"},
        {"note": "Same note.", "at": "2026-07-09T00:00:00+00:00"},
    ]}
    block_dupe = setter._latest_owner_rules(agent_dupe)
    check("latest rules: dedupe collapses an identical note to one line",
         block_dupe.count("Same note.") == 1, block_dupe)

    # Cap: max_rules keeps only the newest N.
    agent_many = {"id": "agent-rules03", "instruction_edits": [
        {"note": "Rule A", "at": "2026-07-01T00:00:00+00:00"},
        {"note": "Rule B", "at": "2026-07-02T00:00:00+00:00"},
        {"note": "Rule C", "at": "2026-07-03T00:00:00+00:00"},
    ]}
    block_capped = setter._latest_owner_rules(agent_many, max_rules=2)
    check("latest rules: max_rules keeps only the newest N entries",
         "Rule C" in block_capped and "Rule B" in block_capped and "Rule A" not in block_capped, block_capped)

    # agent-only vs agent+doc merge: a training doc's own answer notes join
    # instruction_edits, still ordered newest-first across BOTH sources.
    doc = {"answers": {"case-1": {"note": "From training answers, newest.",
                                  "at": "2026-07-10T00:00:00+00:00"}}}
    block_agent_only = setter._latest_owner_rules(agent)
    check("latest rules: agent-only call carries no training-answer note",
         "From training answers" not in block_agent_only, block_agent_only)
    block_merged = setter._latest_owner_rules(agent, doc)
    check("latest rules: agent+doc merge includes the doc's answer note ahead of older instruction_edits",
         block_merged.index("From training answers, newest.") < block_merged.index("Never promise"), block_merged)

    check("latest rules: nothing to say (no instruction_edits, no doc) -> empty string",
         setter._latest_owner_rules({}) == "", None)


def test_latest_owner_rules_reaches_process_reply_classify_and_draft():
    sb, http = fresh_setter()
    captured = {}
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "sure, send it over", "message_id": "m-rules1", "stats_id": "st-rules1",
    }]

    def classify_fn(body):
        captured["classify_body"] = body
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.98, "red_flags": [], "timezone_guess": "Europe/London", "tz_confidence": 0.9,
            "wants": "wants the resource", "rationale": "unqualified yes",
        }

    def draft_fn(body):
        captured["draft_body"] = body
        return {"subject": "Re: hi", "html": 'Hi There, <a href="https://x.example/r">Here it is</a>. Best, Sam'}

    http.classify_fn = classify_fn
    http.draft_fn = draft_fn

    agent = {
        "id": "agent-rules-live", "mode": "draft_only", "enabled": True, "campaign_ids": [601],
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r",
        "instruction_edits": [
            {"note": "Newest owner rule: mention the free onboarding call.", "at": "2026-07-12T00:00:00+00:00",
             "source": "manual", "how": "merged"},
        ],
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    reply = {"workspace": "navreo", "campaign_id": 601, "email": "rules@example.com",
             "first_name": "There", "message_id": "m-rules1", "body": "sure, send it over",
             "subject": "Re: hi", "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False}
    setter.process_reply(reply, agent, {})

    classify_payload = json.loads(captured["classify_body"]["messages"][1]["content"])
    draft_payload = json.loads(captured["draft_body"]["messages"][1]["content"])
    check("latest rules -> process_reply: reaches classify() as owner_corrections",
         "Newest owner rule: mention the free onboarding call." in classify_payload.get("owner_corrections", ""),
         classify_payload.get("owner_corrections"))
    check("latest rules -> process_reply: LATEST OWNER RULES header present in owner_corrections",
         "LATEST OWNER RULES" in classify_payload.get("owner_corrections", ""), classify_payload.get("owner_corrections"))
    check("latest rules -> process_reply: reaches draft_reply() as reviewer_feedback",
         "Newest owner rule: mention the free onboarding call." in draft_payload.get("reviewer_feedback", ""),
         draft_payload.get("reviewer_feedback"))


def test_latest_owner_rules_reaches_retrain():
    sb, http = fresh_setter()
    agent = {"id": "agent-rules-retrain", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource", "pricing", "scheduling"], "instructions": "Flat $400/mo.",
             "instruction_edits": [
                 {"note": "Retrain rule: always ask if timing works this week.",
                  "at": "2026-07-13T00:00:00+00:00", "source": "manual", "how": "merged"},
             ]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    case_a = _fixed_training_case("case-lr-00", body="answered trigger case")
    case_b = _fixed_training_case("case-lr-01", body="unanswered case")
    doc = {"cases": [case_a, case_b], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    captured_hints = []

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        captured_hints.append(payload.get("owner_corrections"))
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.97, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
            "wants": "wants info", "rationale": "",
        }
    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi",
                                "html": '<div>Hi there,</div><br><div>Sure thing.</div><br><div>Bjion</div>'}

    status, resp = _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-lr-00", "decision_ok": False,
        "note": "Session note for retrain.", "scope": "one_off",
    })
    check("latest rules -> retrain: answering returns 200 and kicks off retrain",
         status == 200 and resp.get("retrain") == "started", (status, resp))
    check("latest rules -> retrain: instruction_edits note reached classify() owner_hints for the unanswered case",
         len(captured_hints) >= 1 and all(
             "Retrain rule: always ask if timing works this week." in (h or "") for h in captured_hints),
         captured_hints)


def test_latest_owner_rules_reaches_training_generation():
    sb, http = fresh_setter()
    _seed_training_corpus(sb, per_category=6, campaign_id=8200)
    captured = []

    def classify_fn(body):
        payload = json.loads(body["messages"][1]["content"])
        captured.append(payload.get("owner_corrections"))
        return {
            "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
            "confidence": 0.5, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
            "wants": "wants info", "rationale": "",
        }

    http.classify_fn = classify_fn
    http.draft_fn = lambda _b: {"subject": "Re: hi", "html": "Hi there, thanks. Best, Bjion"}

    agent = {
        "id": "agent-rules-gen", "mode": "draft_only", "enabled": True,
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "resource_link": "https://x.example/r",
        "instruction_edits": [
            {"note": "Generation rule: never quote a discount.", "at": "2026-07-14T00:00:00+00:00",
             "source": "manual", "how": "merged"},
        ],
    }
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

    status, resp = _generate_and_wait({"agent_id": agent["id"], "batch_size": 4})
    check("latest rules -> generation: 200 and starts", status == 200 and resp.get("status") == "started", (status, resp))
    check("latest rules -> generation: reaches classify() as owner_corrections",
         len(captured) > 0 and all("Generation rule: never quote a discount." in (c or "") for c in captured),
         captured)


def test_classify_and_draft_system_contain_latest_rules_priority_line():
    priority_line = ("LATEST OWNER RULES block: those rules are the owner's newest teaching and take "
                     "priority over everything else, including older instructions")
    check("CLASSIFY_SYSTEM: LATEST OWNER RULES priority line present", priority_line in setter.CLASSIFY_SYSTEM, None)
    check("DRAFT_SYSTEM: LATEST OWNER RULES priority line present", priority_line in setter.DRAFT_SYSTEM, None)


# ── thumbs-up teaches: confirmed exemplars (trainer-obedience brief 2026-07-14) ─
# route_training_answer(decision_ok=True) appends a compact {gist, decision, at}
# exemplar to doc['confirmed_examples'] (rolling cap 20), and
# _training_session_feedback_digest surfaces the newest ~5 after corrections.

def test_confirmed_examples_thumbs_down_does_not_append():
    sb, http = fresh_setter()
    agent = {"id": "agent-confirm-down", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    case = _fixed_training_case("case-cf-down", body="Not sure this is a good fit for us honestly.")
    doc = {"cases": [case], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status, resp = _answer_and_wait({
        "agent_id": agent["id"], "case_id": "case-cf-down", "decision_ok": False, "scope": "one_off",
    })
    check("confirmed examples: thumbs-down answer returns 200", status == 200, (status, resp))
    saved = setter._load_training(agent["id"])
    check("confirmed examples: decision_ok False never appends an exemplar",
         not (saved.get("confirmed_examples") or []), saved.get("confirmed_examples"))


def test_confirmed_examples_thumbs_up_appends_exemplar():
    sb, http = fresh_setter()
    agent = {"id": "agent-confirm-up", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    body = "Sounds good, send the guide over please, that would be great."
    case = _fixed_training_case("case-cf-up", body=body)
    case["decision"] = "auto_send"
    doc = {"cases": [case], "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    status, resp = setter.route_training_answer({
        "agent_id": agent["id"], "case_id": "case-cf-up", "decision_ok": True, "reply_ok": True, "scope": "one_off",
    })
    check("confirmed examples: thumbs-up returns 200 and does not trigger a retrain (no note, no wrong mark)",
         status == 200 and resp.get("retrain") is None, (status, resp))
    saved = setter._load_training(agent["id"])
    confirmed = saved.get("confirmed_examples") or []
    check("confirmed examples: decision_ok True appends exactly one exemplar", len(confirmed) == 1, confirmed)
    check("confirmed examples: exemplar gist is the first ~90 chars of the case's inbound body",
         confirmed[0].get("gist") == body[:90], confirmed[0])
    check("confirmed examples: exemplar decision matches the case's decision",
         confirmed[0].get("decision") == "auto_send", confirmed[0])
    check("confirmed examples: exemplar carries an 'at' timestamp", bool(confirmed[0].get("at")), confirmed[0])


def test_confirmed_examples_rolling_cap_newest_kept():
    sb, http = fresh_setter()
    agent = {"id": "agent-confirm-cap", "mode": "draft_only", "enabled": True, "allowed_intents": ["send_resource"]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    cases = [_fixed_training_case(f"case-cf-{i:02d}", body=f"Reply body number {i} for this scenario.")
             for i in range(25)]
    for c in cases:
        c["decision"] = "auto_send"
    doc = {"cases": cases, "answers": {}, "used_reply_ids": [], "readiness_history": [],
          "created_at": "2026-01-01T00:00:00+00:00"}
    setter._save_training(agent["id"], doc)

    for i in range(25):
        status, resp = setter.route_training_answer({
            "agent_id": agent["id"], "case_id": f"case-cf-{i:02d}", "decision_ok": True, "scope": "one_off",
        })
        check(f"confirmed examples cap: answer {i} returns 200 with no retrain",
             status == 200 and resp.get("retrain") is None, (status, resp))

    saved = setter._load_training(agent["id"])
    confirmed = saved.get("confirmed_examples") or []
    check("confirmed examples cap: rolling cap keeps at most 20", len(confirmed) == 20, len(confirmed))
    check("confirmed examples cap: the newest (case 24) is kept",
         any("Reply body number 24" in (e.get("gist") or "") for e in confirmed), confirmed)
    check("confirmed examples cap: the oldest (case 0) was dropped",
         not any("Reply body number 0 " in (e.get("gist") or "") for e in confirmed), confirmed)


def test_training_session_digest_confirmations_after_corrections_and_priority():
    doc = {
        "cases": [{"id": "case-d-00", "decision": "review",
                   "inbound": {"body": "A tricky objection about pricing structure and commission."}}],
        "answers": {"case-d-00": {"decision_ok": False, "note": "", "at": "2026-07-10T00:00:00+00:00"}},
        "confirmed_examples": [
            {"gist": "Sure, send it over please", "decision": "auto_send", "at": "2026-07-11T00:00:00+00:00"},
            {"gist": "Not interested right now thanks", "decision": "review", "at": "2026-07-12T00:00:00+00:00"},
        ],
    }
    digest = setter._training_session_feedback_digest(doc)
    check("session digest: the correction line is still present",
         "The owner said the 'review' call was wrong" in digest, digest)
    check("session digest: the confirmations block is present",
         "The owner CONFIRMED these calls were right" in digest, digest)
    idx_correction = digest.index("The owner said the 'review' call was wrong")
    idx_confirmed = digest.index("The owner CONFIRMED these calls were right")
    check("session digest: corrections come BEFORE confirmations", idx_correction < idx_confirmed, digest)
    check("session digest: confirmations are newest-first (07-12 entry before 07-11 entry)",
         digest.index("Not interested right now thanks") < digest.index("Sure, send it over please"), digest)
    check("session digest: decision auto_send maps to 'answer on its own'",
         "'Sure, send it over please' -> answer on its own" in digest, digest)
    check("session digest: a non-auto_send decision maps to 'leave it to a human'",
         "'Not interested right now thanks' -> leave it to a human" in digest, digest)


def test_training_session_digest_corrections_priority_under_cap():
    doc = {
        "cases": [{"id": "case-p-00", "decision": "review", "inbound": {"body": "x" * 100}}],
        "answers": {"case-p-00": {"decision_ok": False, "note": "", "at": "2026-07-10T00:00:00+00:00"}},
        "confirmed_examples": [{"gist": "Sure thing", "decision": "auto_send", "at": "2026-07-11T00:00:00+00:00"}],
    }
    tight_digest = setter._training_session_feedback_digest(doc, limit_chars=40)
    check("session digest priority: under a tight cap, the correction survives",
         "The owner said the 'review'" in tight_digest, tight_digest)
    check("session digest priority: under a tight cap, confirmations are dropped entirely",
         "CONFIRMED" not in tight_digest, tight_digest)
    check("session digest priority: the whole digest still respects the char cap",
         len(tight_digest) <= 40, len(tight_digest))

    roomy_digest = setter._training_session_feedback_digest(doc, limit_chars=2000)
    check("session digest priority: with room, confirmations appear too",
         "CONFIRMED" in roomy_digest, roomy_digest)


# ── second sweep: proofread_draft (trainer-obedience brief 2026-07-14) ──────────

def test_proofread_draft_clean_fix_applies():
    sb, http = fresh_setter()
    original = "<div>Hi Donald,</div><br><div>Thankyou thankyou for reaching out.</div><br><div>Bjion</div>"
    fixed = "<div>Hi Donald,</div><br><div>Thank you for reaching out.</div><br><div>Bjion</div>"
    http.proofread_fn = lambda _b: {"html": fixed}
    result, changed = setter.proofread_draft(original)
    check("proofread: clean fix path returns the corrected html", result == fixed, result)
    check("proofread: clean fix path reports changed=True", changed is True, changed)


def test_proofread_draft_url_mismatch_keeps_original():
    sb, http = fresh_setter()
    original = '<div>Hi Donald,</div><br><div><a href="https://x.example/r">Here it is</a>.</div><br><div>Bjion</div>'
    bad = '<div>Hi Donald,</div><br><div><a href="https://evil.example/x">Here it is</a>.</div><br><div>Bjion</div>'
    http.proofread_fn = lambda _b: {"html": bad}
    result, changed = setter.proofread_draft(original)
    check("proofread: a URL-set mismatch keeps the ORIGINAL html", result == original, result)
    check("proofread: URL-set mismatch reports changed=False", changed is False, changed)


def test_proofread_draft_digit_change_keeps_original():
    sb, http = fresh_setter()
    original = "<div>Hi Donald,</div><br><div>Our price is $500/mo.</div><br><div>Bjion</div>"
    bad = "<div>Hi Donald,</div><br><div>Our price is $5000/mo.</div><br><div>Bjion</div>"
    http.proofread_fn = lambda _b: {"html": bad}
    result, changed = setter.proofread_draft(original)
    check("proofread: a changed visible number keeps the ORIGINAL html", result == original, result)
    check("proofread: digit change reports changed=False", changed is False, changed)


def test_proofread_draft_empty_or_garbage_keeps_original():
    sb, http = fresh_setter()
    original = "<div>Hi Donald,</div><br><div>Thanks for reaching out.</div><br><div>Bjion</div>"

    http.proofread_fn = lambda _b: {"html": ""}
    result, changed = setter.proofread_draft(original)
    check("proofread: an empty model result keeps the ORIGINAL html",
         result == original and changed is False, (result, changed))

    http.proofread_fn = lambda _b: {"html": original + ("x" * len(original) * 2)}
    result2, changed2 = setter.proofread_draft(original)
    check("proofread: a wildly longer result trips the length guard, ORIGINAL kept",
         result2 == original and changed2 is False, (result2, changed2))

    result3, changed3 = setter.proofread_draft("   ")
    check("proofread: a blank input is returned as-is without calling the model",
         result3 == "   " and changed3 is False, (result3, changed3))


def test_proofread_wired_into_process_reply_after_draft_before_lint():
    sb, http = fresh_setter()
    order = []
    http.message_history = [{
        "type": "REPLY", "time": "2026-07-10T09:00:00+00:00", "subject": "Re: hi",
        "email_body": "sure, send it over", "message_id": "m-pf1", "stats_id": "st-pf1",
    }]
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.98, "red_flags": [], "timezone_guess": "Europe/London", "tz_confidence": 0.9,
        "wants": "wants the resource", "rationale": "unqualified yes",
    }

    def draft_fn(_b):
        order.append("draft")
        return {"subject": "Re: hi",
               "html": 'Hi There, <a href="https://x.example/r">Here it is</a> thankyou thankyou. Best, Sam'}

    def proofread_fn(_b):
        order.append("proofread")
        return {"html": 'Hi There, <a href="https://x.example/r">Here it is</a> thank you. Best, Sam'}

    http.draft_fn = draft_fn
    http.proofread_fn = proofread_fn

    agent = {"id": "agent-pf-live", "mode": "draft_only", "enabled": True, "campaign_ids": [701],
             "allowed_intents": ["send_resource"], "resource_link": "https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    reply = {"workspace": "navreo", "campaign_id": 701, "email": "pf@example.com",
             "first_name": "There", "message_id": "m-pf1", "body": "sure, send it over",
             "subject": "Re: hi", "replied_at": "2026-07-10T09:00:00+00:00", "is_test": False}
    row = setter.process_reply(reply, agent, {})

    check("proofread wiring (process_reply): draft ran before proofread", order == ["draft", "proofread"], order)
    check("proofread wiring (process_reply): the stored draft is the PROOFREAD result, not the raw draft",
         "thank you" in (row.get("draft_body") or "") and "thankyou thankyou" not in (row.get("draft_body") or ""),
         row.get("draft_body"))


def test_proofread_wired_into_build_training_case_real_and_synthetic():
    sb, http = fresh_setter()
    order = []
    http.classify_fn = lambda _b: {
        "primary_intent": "send_resource", "all_intents": ["send_resource"], "simple_ask": True,
        "confidence": 0.9, "red_flags": [], "timezone_guess": None, "tz_confidence": 0.0,
        "wants": "wants info", "rationale": "",
    }

    def draft_fn(_b):
        order.append("draft")
        return {"subject": "Re: hi", "html": "<div>Hi there,</div><br><div>Thankyou thankyou.</div><br><div>Bjion</div>"}

    def proofread_fn(_b):
        order.append("proofread")
        return {"html": "<div>Hi there,</div><br><div>Thank you.</div><br><div>Bjion</div>"}

    http.draft_fn = draft_fn
    http.proofread_fn = proofread_fn

    agent = {"id": "agent-pf-train", "resource_link": "https://x.example/r"}
    now = dt.datetime.now(dt.timezone.utc)

    reply_row = {"id": 9301, "smartlead_campaign_id": 1, "email": "pf@example.com",
                "replied_at": "2026-06-10T09:00:00+00:00", "category": "Interested",
                "reply_subject": "Re: our email", "reply_body": "Sounds great, send more info please."}
    real_case = setter._build_training_case(reply_row, agent, {}, [], "not_configured", now, "", idx=0)
    check("proofread wiring (real training case): draft ran before proofread",
         order[:2] == ["draft", "proofread"], order)
    check("proofread wiring (real training case): stored draft_html is the proofread result",
         "Thank you." in (real_case.get("draft_html") or "")
         and "Thankyou thankyou" not in (real_case.get("draft_html") or ""), real_case.get("draft_html"))

    order.clear()
    scenario = {"category": "Interested", "subject": "Re: our email", "body": "Sounds great, tell me more please."}
    synth_case = setter._build_synthetic_training_case(scenario, agent, {}, [], "not_configured", now, "", idx=1)
    check("proofread wiring (synthetic training case): draft ran before proofread",
         order[:2] == ["draft", "proofread"], order)
    check("proofread wiring (synthetic training case): stored draft_html is the proofread result",
         "Thank you." in (synth_case.get("draft_html") or "")
         and "Thankyou thankyou" not in (synth_case.get("draft_html") or ""), synth_case.get("draft_html"))


def test_proofread_wired_into_queue_redraft():
    sb, http = fresh_setter()
    order = []
    agent = {"id": "agent-pf-redraft", "mode": "draft_only", "enabled": True,
             "allowed_intents": ["send_resource"], "resource_link": "https://x.example/r"}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}
    sb.queue.append({
        "id": 701, "workspace": "navreo", "smartlead_campaign_id": 111, "agent_id": agent["id"],
        "lead_email": "pf3@example.com", "lead_first_name": "There", "message_id": "m-pf3",
        "reply_subject": "Re: hi", "reply_body": "sure, send it",
        "classification": {"primary_intent": "send_resource", "all_intents": ["send_resource"]},
        "timezone": None, "thread": [],
    })

    def draft_fn(_b):
        order.append("draft")
        return {"subject": "Re: hi", "html": "Hi There, thankyou thankyou. Best, Sam"}

    def proofread_fn(_b):
        order.append("proofread")
        return {"html": "Hi There, thank you. Best, Sam"}

    http.draft_fn = draft_fn
    http.proofread_fn = proofread_fn

    status, resp = setter.route_queue_redraft({"id": 701, "feedback": "shorter please"})
    check("proofread wiring (redraft): returns 200", status == 200, (status, resp))
    check("proofread wiring (redraft): draft ran before proofread", order == ["draft", "proofread"], order)
    saved_draft = (resp.get("row") or {}).get("draft_body") or ""
    check("proofread wiring (redraft): saved draft_body is the PROOFREAD result, not the raw draft",
         "thank you" in saved_draft and "thankyou thankyou" not in saved_draft, saved_draft)


# ── run everything ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_lexicon()
    test_guess_timezone()
    test_pick_slots()
    test_lint_draft()
    test_lint_draft_url_discipline()
    test_lint_draft_calendly_fallback_booking_link()
    test_lint_draft_calendly_fallback_instructions_link()
    test_lint_draft_slot_status_ok_unchanged_by_fallback_rules()
    test_decide_matrix()
    test_decide_gate7_calendly_fallback_skips_holds()
    test_decide_gate7_calendly_fallback_ignores_tz_confidence()
    test_decide_gate7_slot_status_ok_keeps_holds_unchanged()
    test_decide_gate_3b_same_day_ask_still_holds_under_fallback()
    test_decide_gate7_master_switch_still_last_under_fallback()
    test_fixtures()
    test_idempotent_intake()
    test_inject_never_sends()
    test_env_dry_run_send_never_hits_network()
    test_poll_batching_cap()
    test_poll_never_raises_on_bad_agent_config()
    test_run_poll_assigned_at_filter()
    test_route_queue_action_send_409_when_already_sent()
    test_subsequence_success_pushes_live_and_patches_flag()
    test_subsequence_failure_http200_okfalse_returns_502()
    test_subsequence_failure_smartlead_error_returns_502_flag_untouched()
    test_subsequence_failure_lead_not_found_never_pushes()
    test_subsequence_no_queue_row_route_resolves_by_email_and_pushes()
    test_subsequence_uncheck_makes_no_smartlead_call()
    test_subsequence_ambiguous_multiple_subsequences_needs_override()
    test_claim_race_returns_existing_row_without_classifying()
    test_existing_row_percent_encodes_plus_in_keys()
    test_existing_row_falls_back_to_source_message_id()
    test_run_poll_skips_reply_already_queued_under_swapped_mid()
    test_claim_rows_carry_source_message_id()
    test_hydrate_lead_answered_since_reply()
    test_tz_none_calendly_fallback_no_slots_but_auto_sends()
    test_tz_guessed_low_confidence_shows_local_times_but_holds()
    test_tz_confidence_gate_in_decide()
    test_process_reply_calendly_not_connected_scheduling_ask_auto_sends()
    test_handle_inbound_field_mapping()
    test_handle_inbound_non_reply_event_ignored()
    test_handle_inbound_missing_message_id_ignored()
    test_handle_inbound_unassigned_campaign_ignored()
    test_handle_inbound_missing_campaign_or_email_ignored()
    test_ensure_webhooks_adds_one_and_preserves_existing()
    test_ensure_webhooks_dry_run_skips()
    test_ensure_webhooks_second_call_is_noop()
    test_agent_instructions_fallback()
    test_booking_link_derivation()
    test_decide_multi_turn_autonomy()
    test_draft_reply_thread_continuity()
    test_memory_digest_reaches_classify_and_draft()
    test_memory_digest_empty_is_byte_identical()
    test_merge_correction_into_instructions_success_and_fallbacks()
    test_correction_one_off_does_not_touch_memory()
    test_correction_remember_route_merges_instructions()
    test_agents_memory_delete()
    test_redraft_scope_remember_merges_instructions()
    test_redraft_without_scope_does_not_persist()
    test_agent_duplicate()
    test_grading_endpoints()
    test_grading_relearn_updates_unanswered_cases()
    test_grading_relearn_extracts_real_calendly_slots_from_existing_draft()
    test_training_generate_weighted_excludes_used_and_batch_cap()
    test_training_generate_stores_real_bodies_verbatim()
    test_training_case_includes_original_outreach_and_human_answer_when_present()
    test_training_generate_memory_digest_reaches_classify()
    test_training_generate_concurrent_preserves_selection_order()
    test_training_generate_one_worker_failure_drops_only_that_case()
    test_training_generate_all_workers_fail_marks_generating_failed_plain_english()
    test_training_generate_concurrent_batch_matches_sequential_case_count()
    test_training_generate_refuses_over_40_unanswered()
    test_training_generate_second_call_while_running_is_already_running()
    test_training_generate_lost_update_protection_answer_survives()
    test_training_generate_shortfall_top_up_real_plus_synthetic()
    test_training_generate_pure_synthetic_zero_replies()
    test_training_generate_synthetic_only_preserves_existing_used_reply_ids()
    test_training_synthetic_category_mix_80_20()
    test_training_invent_prompt_includes_reference_sample_gists_and_law()
    test_training_generate_synthetic_never_bypasses_unanswered_cap()
    test_training_generate_synthetic_lost_update_protection_answer_survives()
    test_training_answer_readiness_moves_identically_for_synthetic_case()
    test_training_generate_synthetic_logs_provider_usage_and_failure_is_swallowed()
    test_training_answer_recomputes_readiness_and_counts()
    test_training_answer_remember_merges_instructions_one_off_does_not()
    test_training_retrain_note_updates_unanswered_leaves_answered()
    test_training_retrain_trigger_conditions()
    test_training_retrain_lock_contention_with_generate_queued_flag_honoured()
    test_training_retrain_failed_case_keeps_old_content()
    test_training_retrain_concurrent_answer_survives()
    test_training_answer_remember_returns_fast_without_synchronous_merge()
    test_training_answer_remember_persists_pending_merge_in_same_write()
    test_training_retrain_worker_drains_pending_merges_in_order_across_queued_pass()
    test_training_retrain_merge_failure_falls_back_to_append_and_retrain_still_runs()
    test_training_get_reports_pending_merges_count()
    test_training_answer_one_off_note_never_enters_pending_merges()
    test_training_retrain_worker_retrain_step_uses_freshly_merged_instructions()
    test_kick_off_training_retrain_request_thread_makes_no_save_before_worker_runs()
    test_kick_off_training_retrain_worker_first_action_writes_running_marker()
    test_kick_off_training_retrain_lock_held_flagger_persists_queued_flag()
    test_training_answer_existing_doc_skips_agent_load()
    test_training_answer_404_when_neither_doc_nor_agent_exists()
    test_training_answer_note_path_still_returns_started_without_agent_load()
    test_training_pending_merges_survive_and_drain_on_next_kick_after_dead_worker()
    test_draft_system_fallback_ladder_text()
    test_training_reset_clears_answers_keeps_used_ids()
    test_training_get_route()
    test_training_get_self_heals_stale_running_marker()
    test_compute_readiness_pure_function()
    test_readiness_30_answer_scripted_simulation()
    test_share_mint_verify_roundtrip()
    test_route_training_share_mints_and_share_info()
    test_training_get_share_forces_agent_and_rejects_mismatch()
    test_training_get_includes_minimal_agent_memory()
    test_training_generate_share_forces_agent_campaign_filter_and_400_on_no_campaigns()
    test_training_generate_share_unanswered_cap_is_tighter_than_owner()
    test_training_answer_share_forces_agent_rejects_mismatch_and_response_stays_scoped()
    test_memory_delete_never_accepts_share_token()
    test_extract_urls_helper()
    test_instruction_urls_helper()
    test_classify_payload_carries_instructions_no_resources_key()
    test_draft_payload_carries_instructions_no_resources_key()
    test_draft_reply_payload_carries_slot_status_and_booking_link_unchanged()
    test_decide_gate_6b_instruction_link_ambiguity()
    test_core_four_categories_enter_queue_both_paths()
    test_non_core_categories_stay_out_both_paths()
    test_handle_inbound_uncategorised_then_poll_catches_up()
    test_backfill_assigned_at_bypass_only_in_backfill()
    test_backfill_dry_run_zero_writes()

    test_latest_owner_rules_helper()
    test_latest_owner_rules_reaches_process_reply_classify_and_draft()
    test_latest_owner_rules_reaches_retrain()
    test_latest_owner_rules_reaches_training_generation()
    test_classify_and_draft_system_contain_latest_rules_priority_line()
    test_confirmed_examples_thumbs_down_does_not_append()
    test_confirmed_examples_thumbs_up_appends_exemplar()
    test_confirmed_examples_rolling_cap_newest_kept()
    test_training_session_digest_confirmations_after_corrections_and_priority()
    test_training_session_digest_corrections_priority_under_cap()
    test_proofread_draft_clean_fix_applies()
    test_proofread_draft_url_mismatch_keeps_original()
    test_proofread_draft_digit_change_keeps_original()
    test_proofread_draft_empty_or_garbage_keeps_original()
    test_proofread_wired_into_process_reply_after_draft_before_lint()
    test_proofread_wired_into_build_training_case_real_and_synthetic()
    test_proofread_wired_into_queue_redraft()

    failed = run_report()
    sys.exit(1 if failed else 0)
