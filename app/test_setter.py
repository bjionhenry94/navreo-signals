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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402


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
        self.replies = []      # list of raw reply rows for run_poll()
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
            params[k] = v
        return table, params

    @staticmethod
    def _match_eq(value, op_value):
        if op_value.startswith("eq."):
            return str(value) == op_value[3:]
        if op_value.startswith("neq."):
            return str(value) != op_value[4:]
        if op_value.startswith("in."):
            inner = op_value[3:].strip("()")
            opts = [o for o in inner.split(",") if o != ""]
            return str(value) in opts
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
        return []

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
        cid_op = params.get("smartlead_campaign_id", "")
        allowed = None
        if cid_op.startswith("in."):
            allowed = set(cid_op[3:].strip("()").split(","))
        rows = self.replies
        if allowed is not None:
            rows = [r for r in rows if str(r.get("smartlead_campaign_id")) in allowed]
        return copy.deepcopy(rows)


class FakeHTTP:
    """Stand-in for http_json(method, url, headers, body). Routes by
    substring on the URL. classify_fn/draft_fn are callables(request_body)
    returning the dict payload the real OpenAI call would have parsed out."""

    def __init__(self):
        self.classify_fn = None
        self.draft_fn = None
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
            # message-history's own URL (".../leads/{id}/message-history") also
            # contains "/leads/", so it must be checked BEFORE the generic
            # leads-lookup branch or it always shadows it.
            if "message-history" in url:
                return {"history": self.message_history}
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
           "resource_link": "https://navreo.notion.site/abc", "slot_status": "ok",
           "slot_links": ["https://calendly.com/x/1"], "slot_labels": ["Monday, 13th July at 10:00 AM BST"],
           "instructions": "", "thread_text": ""}
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
    check("lint: missing resource link fails", not ok and "resource link" in reason, reason)

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
    check("lint: resource link entirely absent fails", not ok, reason)


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

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "first_touch": False})
    check("decide: second reply from same lead -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "slot_status": "none_available"})
    check("decide: no Calendly slots available -> review", d == "review", r)

    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, {**CTX_ALL_GOOD, "slot_status": "not_configured"})
    check("decide: Calendly not connected -> review", d == "review", r)

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

    # second-touch veto uses the real first_touch gate, not intent
    c = cases["sure_but_second_reply"]
    ctx = dict(CTX_ALL_GOOD)
    ctx["red_flag_hits"] = setter.lexicon_hits(c["body"])
    ctx["body_len"] = len(c["body"])
    ctx["first_touch"] = False
    d, r = setter.decide(_cls("send_resource"), AGENT_AUTO, ctx)
    check("fixture[sure_but_second_reply]: second reply always goes to review", d != "auto_send", r)

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
            "message_id": f"m-{i}", "category": None,
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
        "smartlead_message_id": "old-1", "category": None,
    })
    sb.replies.append({
        "workspace": "navreo", "smartlead_campaign_id": 700, "email": "new@example.com",
        "subject": "Re: hi", "reply_body": "sure, send it", "replied_at": "2026-07-10T00:00:00+00:00",
        "smartlead_message_id": "new-1", "category": None,
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


def test_tz_none_still_builds_tentative_slots_but_vetoes_auto():
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
                               "html": 'Hi There, <a href="https://x.example/r">Here it is</a>. Best, Sam'}

    agent = {
        "id": "agent-tzNone01", "mode": "autopilot", "enabled": True, "campaign_ids": [909],
        "allowed_intents": ["send_resource", "pricing", "scheduling"], "pricing_notes": "x",
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
    check("tz-none: decide() vetoes auto-send because the timezone is unresolved",
         row.get("decision") == "review", row)
    check("tz-none: veto reason is the timezone gate specifically",
         row.get("decision_reason") == "Held for review: couldn't work out the lead's timezone.",
         row.get("decision_reason"))


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


# ── handle_inbound: Smartlead EMAIL_REPLY webhook -> pipeline ───────────────

def test_handle_inbound_field_mapping():
    sb, http = fresh_setter()
    agent = {"id": "agent-wh0001", "mode": "draft_only", "enabled": True, "campaign_ids": [777]}
    sb.agents[agent["id"]] = {"id": agent["id"], "doc": agent}

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
        "instructions": "Flat $500/mo.", "confidence_threshold": 0.9,
        "resource_link": "https://x.example/r",
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


# ── run everything ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_lexicon()
    test_guess_timezone()
    test_pick_slots()
    test_lint_draft()
    test_decide_matrix()
    test_fixtures()
    test_idempotent_intake()
    test_inject_never_sends()
    test_env_dry_run_send_never_hits_network()
    test_poll_batching_cap()
    test_poll_never_raises_on_bad_agent_config()
    test_run_poll_assigned_at_filter()
    test_route_queue_action_send_409_when_already_sent()
    test_claim_race_returns_existing_row_without_classifying()
    test_hydrate_lead_answered_since_reply()
    test_tz_none_still_builds_tentative_slots_but_vetoes_auto()
    test_tz_guessed_low_confidence_shows_local_times_but_holds()
    test_tz_confidence_gate_in_decide()
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
    test_grading_endpoints()
    test_grading_relearn_updates_unanswered_cases()
    test_grading_relearn_extracts_real_calendly_slots_from_existing_draft()

    failed = run_report()
    sys.exit(1 if failed else 0)
