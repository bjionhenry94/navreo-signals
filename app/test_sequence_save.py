"""Unit gate for save_sequence_ids_intact — THE one door to Smartlead's
sequences-save endpoint (variant-action-wire loop, Step 3 done-rule).

Proves, with a stubbed HTTP layer (zero live Smartlead calls):
  (a) a normal edit round-trips with EVERY pre-existing step + variant id
      echoed in the POST body, delayInDays remapped to delay_in_days, and the
      post-verify passing;
  (b) a mutate_fn that drops an id is rejected by the guard BEFORE any POST;
  (c) appending a new id-less variant is allowed (that's how a challenger is
      added) and rides the POST without an id;
  (d) a SequenceActionRefused from the mutate aborts with no POST.

Run:  python3 app/test_sequence_save.py
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


FIXTURE = [
    {"id": 111, "seq_number": 1,
     "seq_delay_details": {"delayInDays": 0},
     "subject": "step-one subject",
     "sequence_variants": [
         {"id": 901, "variant_label": "A", "subject": "subj A", "email_body": "<p>A body</p>",
          "variant_distribution_percentage": 60},
         {"id": 902, "variant_label": "B", "subject": None, "email_body": "<p>B body</p>",
          "variant_distribution_percentage": 40},
     ]},
    {"id": 222, "seq_number": 2,
     "seq_delay_details": {"delayInDays": 3},
     "email_body": "<p>step two inline body</p>",
     "sequence_variants": []},
]


class StubHTTP:
    """Records every call; serves the fixture on GET, echoes ok on POST.
    After a POST, GETs serve the posted state mapped back to GET shape so the
    helper's post-verify sees what was 'saved'."""

    def __init__(self, fixture):
        self.state = copy.deepcopy(fixture)
        self.calls = []

    def __call__(self, method, url, headers, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "body": copy.deepcopy(body)})
        if method == "GET":
            return copy.deepcopy(self.state)
        if method == "POST":
            posted = (body or {}).get("sequences") or []
            new_state = []
            next_vid = [5000]

            def _vid(v):
                if v.get("id") is not None:
                    return v["id"]
                next_vid[0] += 1  # Smartlead mints ids for id-less newcomers
                return next_vid[0]

            for s in posted:
                new_state.append({
                    "id": s.get("id"), "seq_number": s.get("seq_number"),
                    "seq_delay_details": {"delayInDays": (s.get("seq_delay_details") or {}).get("delay_in_days", 0)},
                    "subject": s.get("subject"), "email_body": s.get("email_body"),
                    "sequence_variants": [
                        {"id": _vid(v), "variant_label": v.get("variant_label"),
                         "subject": v.get("subject"), "email_body": v.get("email_body"),
                         "variant_distribution_percentage": v.get("variant_distribution_percentage")}
                        for v in (s.get("seq_variants") or [])],
                })
            self.state = new_state
            return {"ok": True, "data": {"sequences": [{"id": s.get("id")} for s in posted]}}
        raise AssertionError(f"unexpected method {method}")

    @property
    def posts(self):
        return [c for c in self.calls if c["method"] == "POST"]


PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok  " if cond else "  FAIL") + f" {name}" + (f" - {detail}" if detail and not cond else ""))


def test_roundtrip_preserves_ids():
    print("(a) normal edit round-trips, ids echoed, delay remapped")
    stub = StubHTTP(FIXTURE)

    def mutate(steps):
        v = server._find_variant(server._find_step(steps, 1), "B")
        v["variant_distribution_percentage"] = 0
        server._find_variant(server._find_step(steps, 1), "A")["variant_distribution_percentage"] = 100
        return steps

    out = server.save_sequence_ids_intact(3999999, mutate, api_key="stub", http=stub)
    check("returns ok", out["ok"] is True)
    check("one POST fired", len(stub.posts) == 1)
    posted = stub.posts[0]["body"]["sequences"]
    posted_step_ids = sorted(str(s["id"]) for s in posted)
    posted_var_ids = sorted(str(v["id"]) for s in posted for v in (s.get("seq_variants") or []))
    check("every step id echoed", posted_step_ids == ["111", "222"], str(posted_step_ids))
    check("every variant id echoed", posted_var_ids == ["901", "902"], str(posted_var_ids))
    d1 = next(s for s in posted if s["id"] == 111)["seq_delay_details"]
    d2 = next(s for s in posted if s["id"] == 222)["seq_delay_details"]
    check("delayInDays -> delay_in_days", d1 == {"delay_in_days": 0} and d2 == {"delay_in_days": 3},
          f"{d1} {d2}")
    check("untouched copy carried verbatim",
          next(v for s in posted if s["id"] == 111 for v in s["seq_variants"] if v["id"] == 901)["email_body"]
          == "<p>A body</p>")
    check("post-verify ids intact", out["after_ids"]["variants"] == ["901", "902"])
    check("target change took", server._variant_pct_in(out["steps_after"], 1, 902) == 0)
    # Bjion 2026-08-02: a save that omits variant_distribution_type flips the
    # step back to EQUAL mode in Smartlead (all versions re-enabled, even
    # split shown, stored pcts ignored). Every variant-carrying step MUST
    # ship MANUAL_PERCENTAGE.
    s1 = next(s for s in posted if s["id"] == 111)
    check("variant-carrying step ships MANUAL_PERCENTAGE",
          s1.get("variant_distribution_type") == "MANUAL_PERCENTAGE", str(s1.get("variant_distribution_type")))
    s2 = next(s for s in posted if s["id"] == 222)
    check("variant-less step ships no distribution type", "variant_distribution_type" not in s2)


def test_id_drop_rejected_before_post():
    print("(b) id-dropping mutate rejected BEFORE any POST")
    stub = StubHTTP(FIXTURE)

    def mutate(steps):
        step = server._find_step(steps, 1)
        step["sequence_variants"] = [v for v in step["sequence_variants"] if v["id"] != 902]
        return steps

    try:
        server.save_sequence_ids_intact(3999999, mutate, api_key="stub", http=stub)
        check("guard raised", False, "no exception")
    except server.SequenceIdGuardError as e:
        check("guard raised", True)
        check("names the dropped id", "902" in str(e), str(e))
    check("NO POST fired", len(stub.posts) == 0, f"{len(stub.posts)} posts")


def test_new_variant_allowed():
    print("(c) appending an id-less challenger passes the guard")
    stub = StubHTTP(FIXTURE)

    def mutate(steps):
        step = server._find_step(steps, 1)
        server._find_variant(step, "B")["variant_distribution_percentage"] = 0
        step["sequence_variants"].append(
            {"variant_label": "C", "email_body": "<p>challenger</p>",
             "variant_distribution_percentage": 40})
        return steps

    out = server.save_sequence_ids_intact(3999999, mutate, api_key="stub", http=stub)
    posted = stub.posts[0]["body"]["sequences"]
    newcomer = next(v for s in posted if s["id"] == 111
                    for v in s["seq_variants"] if v["variant_label"] == "C")
    check("newcomer posted without id", "id" not in newcomer)
    check("pre-existing ids still echoed",
          sorted(str(v.get("id")) for s in posted for v in s.get("seq_variants", []) if v.get("id"))
          == ["901", "902"])
    check("post-verify: originals survive alongside newcomer",
          {"901", "902"}.issubset(set(out["after_ids"]["variants"])))


def test_refused_aborts_cleanly():
    print("(d) SequenceActionRefused aborts with no POST")
    stub = StubHTTP(FIXTURE)

    def mutate(steps):
        raise server.SequenceActionRefused(400, {"ok": False, "message": "nope"})

    try:
        server.save_sequence_ids_intact(3999999, mutate, api_key="stub", http=stub)
        check("refusal surfaced", False, "no exception")
    except server.SequenceActionRefused as e:
        check("refusal surfaced", e.status == 400)
    check("NO POST fired", len(stub.posts) == 0)


class HTTP429Once(StubHTTP):
    """Raises a 429 HTTPError on the first N calls, then behaves normally.
    Reproduces the Messaging-tab-then-write burst that used to hard-fail."""
    def __init__(self, fixture, fail_first=2):
        super().__init__(fixture)
        self.left = fail_first

    def __call__(self, method, url, headers, body=None, timeout=60):
        if self.left > 0:
            self.left -= 1
            import urllib.error
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return super().__call__(method, url, headers, body, timeout)


def test_429_retries_then_succeeds():
    print("(e) a transient 429 burst is retried, not surfaced as failure")
    _orig_sleep = server.time.sleep
    server.time.sleep = lambda *_a, **_k: None  # no real waiting in the test
    try:
        stub = HTTP429Once(FIXTURE, fail_first=2)

        def mutate(steps):
            server._find_variant(server._find_step(steps, 1), "B")["variant_distribution_percentage"] = 0
            server._find_variant(server._find_step(steps, 1), "A")["variant_distribution_percentage"] = 100
            return steps

        out = server.save_sequence_ids_intact(3999999, mutate, api_key="stub", http=stub)
        check("write eventually succeeded through the 429s", out["ok"] is True)
        check("the POST did land", len(stub.posts) == 1)
        check("ids intact after retry", out["after_ids"]["variants"] == ["901", "902"])
    finally:
        server.time.sleep = _orig_sleep


def test_persistent_429_raises_clean():
    print("(f) a persistent 429 raises SequenceRateLimited, never a partial write")
    _orig_sleep = server.time.sleep
    server.time.sleep = lambda *_a, **_k: None
    try:
        stub = HTTP429Once(FIXTURE, fail_first=99)  # never clears

        def mutate(steps):
            return steps

        try:
            server.save_sequence_ids_intact(3999999, mutate, api_key="stub", http=stub)
            check("rate-limit surfaced", False, "no exception")
        except server.SequenceRateLimited:
            check("rate-limit surfaced", True)
        check("NO POST fired on persistent 429", len(stub.posts) == 0)
    finally:
        server.time.sleep = _orig_sleep


if __name__ == "__main__":
    test_roundtrip_preserves_ids()
    test_id_drop_rejected_before_post()
    test_new_variant_allowed()
    test_refused_aborts_cleanly()
    test_429_retries_then_succeeds()
    test_persistent_429_raises_clean()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)
