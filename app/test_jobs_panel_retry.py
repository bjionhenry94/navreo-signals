"""Tasks-panel families, grouping and bounded auto-retry.

Covers: kind -> family mapping, /api/jobs stamping, the pure JS grouping helper
(run through node against the REAL shell.js block), retry re-enqueues once per
backoff step, the 3-attempt cap, non-retryable kinds untouched, and the hard
rule that a retried traffic move goes back through the auto-mover runner (which
owns every gate and the one variant door) rather than replaying a raw save.
"""
import json
import os
import subprocess
import sys
import types
import unittest

os.environ.setdefault("NAVREO_NO_BG", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _row(**kw):
    r = {"id": "j1", "owner": server._SERVER_INSTANCE, "kind": "auto_mover_move",
         "campaign_id": "555", "counts": {}, "resume_count": 0, "auto_resumed": False,
         "error": "boom", "finished_at": "2020-01-01T00:00:00+00:00", "label": ""}
    r.update(kw)
    return r


class FakeSB:
    """Records every sb() call; PATCH returns a representation unless told not to."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.patch_claims = True

    def __call__(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("app_jobs?status=eq.failed"):
            return self.rows
        if method == "PATCH":
            return [{"id": "j1"}] if self.patch_claims else []
        return []


class FamilyMap(unittest.TestCase):
    def test_every_new_job_kind_has_a_family(self):
        for kind in ("variant_action", "auto_mover", "auto_mover_move", "warmup_pause",
                     "warmup_resume", "bounce_pause", "bounce_resume", "rest_enforce",
                     "verify", "remove_bad", "pool_pull", "recontact_buckets",
                     "recontact_create", "reconnect-watch"):
            self.assertIn(kind, server.JOB_FAMILY_OF, kind)
            self.assertNotEqual(server.job_family_of(kind), "other", kind)

    def test_unknown_kind_is_other_and_not_retryable(self):
        self.assertEqual(server.job_family_of("who_knows"), "other")
        self.assertFalse(server.JOB_FAMILY_RETRYABLE["other"])

    def test_retryable_families(self):
        self.assertTrue(server.JOB_FAMILY_RETRYABLE["traffic"])
        self.assertTrue(server.JOB_FAMILY_RETRYABLE["mailbox"])
        self.assertTrue(server.JOB_FAMILY_RETRYABLE["data"])
        self.assertFalse(server.JOB_FAMILY_RETRYABLE["launch"])
        self.assertFalse(server.JOB_FAMILY_RETRYABLE["sync"])

    def test_payload_row_carries_family(self):
        out = server._job_with_family({"id": "x", "kind": "warmup_resume"})
        self.assertEqual(out["family"], "mailbox")
        self.assertEqual(server._job_with_family({"id": "y", "kind": "zzz"})["family"], "other")


class Retry(unittest.TestCase):
    def setUp(self):
        self._on_render = server._ON_RENDER
        server._ON_RENDER = True
        self._auto = server.auto_move_run
        self.moves = []
        server.auto_move_run = lambda campaign_id=None, **k: self.moves.append(campaign_id)
        self._thread = server.threading.Thread
        # run "background" retries inline so the assertions are deterministic
        server.threading.Thread = lambda target=None, **k: types.SimpleNamespace(
            start=(target or (lambda: None)))
        self._sb = server.sb

    def tearDown(self):
        server._ON_RENDER = self._on_render
        server.auto_move_run = self._auto
        server.threading.Thread = self._thread
        server.sb = self._sb

    def _run(self, rows):
        fake = FakeSB(rows)
        server.sb = fake
        server._retry_failed_jobs()
        return fake

    def test_retried_traffic_move_goes_via_the_auto_mover_runner(self):
        fake = self._run([_row()])
        # the door is never replayed raw — the runner re-derives + re-gates
        self.assertEqual(self.moves, ["555"])
        patches = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertTrue(patches)
        body = patches[0][2]
        self.assertEqual(body["resume_count"], 1)
        self.assertTrue(body["auto_resumed"])
        self.assertTrue(body["error"].startswith("retrying (1/3): boom"))
        # compare-and-set on the previous count, so two instances can't both fire
        self.assertIn("resume_count=eq.0", patches[0][1])

    def test_one_attempt_per_backoff_step(self):
        # attempt 2 is only due 5 minutes after the failure
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        recent = (now - dt.timedelta(seconds=90)).isoformat()
        self._run([_row(resume_count=1, finished_at=recent)])
        self.assertEqual(self.moves, [])          # 90s < 300s backoff
        old = (now - dt.timedelta(seconds=400)).isoformat()
        self._run([_row(resume_count=1, finished_at=old)])
        self.assertEqual(self.moves, ["555"])

    def test_caps_at_three_and_stamps_gave_up(self):
        fake = self._run([_row(resume_count=3, error="boom")])
        self.assertEqual(self.moves, [])
        patches = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertTrue(patches[0][2]["error"].startswith("gave up after 3 retries: boom"))
        # already stamped -> never touched again
        fake2 = self._run([_row(resume_count=3, error="gave up after 3 retries: boom")])
        self.assertFalse([c for c in fake2.calls if c[0] == "PATCH"])

    def test_non_retryable_kinds_untouched(self):
        for kind in ("recontact_create", "reconnect-watch"):
            fake = self._run([_row(kind=kind)])
            self.assertEqual(self.moves, [])
            self.assertFalse([c for c in fake.calls if c[0] == "PATCH"], kind)

    def test_other_owners_untouched(self):
        fake = self._run([_row(owner="someone-else")])
        self.assertFalse([c for c in fake.calls if c[0] == "PATCH"])

    def test_unreconstructable_row_hands_the_attempt_back(self):
        # a manual variant_action carries no durable payload — no raw replay
        fake = self._run([_row(kind="variant_action", counts={})])
        self.assertEqual(self.moves, [])
        patches = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertEqual(patches[-1][2]["resume_count"], 0)

    def test_warmup_retry_uses_the_warmup_job_entry(self):
        seen = []
        orig = server.api_warmup_job
        server.api_warmup_job = lambda p: (seen.append(p) or ({"job_id": "n1"}, 202))
        try:
            self._run([_row(kind="warmup_resume",
                            counts={"op": "resume", "domains_list": ["a.com"]})])
        finally:
            server.api_warmup_job = orig
        self.assertEqual(seen, [{"op": "resume", "domains": ["a.com"]}])


NODE_HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const a = src.indexOf("/*__JOBS_GROUP_START__*/"), b = src.indexOf("/*__JOBS_GROUP_END__*/");
if (a < 0 || b < 0) { console.error("markers missing"); process.exit(2); }
eval(src.slice(a, b));
const input = JSON.parse(process.argv[3]);
console.log(JSON.stringify(njGroupJobs(input).map((it) =>
  it.group ? { group: true, n: it.jobs.length, label: it.label, family: it.family }
           : { group: false, id: it.job.id })));
"""


class Grouping(unittest.TestCase):
    """The shipped grouping helper, run by node straight out of shell.js."""

    @classmethod
    def setUpClass(cls):
        cls.harness = os.path.join(HERE, "_jobs_group_harness.js")
        with open(cls.harness, "w") as f:
            f.write(NODE_HARNESS)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.harness)
        except OSError:
            pass

    def group(self, jobs):
        out = subprocess.run(["node", self.harness, os.path.join(HERE, "shell.js"),
                              json.dumps(jobs)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_auto_mover_run_and_moves_become_one_row(self):
        t = "2026-09-03T10:0%d:00Z"
        jobs = [{"id": "p", "kind": "auto_mover", "family": "traffic", "status": "done",
                 "label": "Auto-mover: reviewing 16 campaigns", "finished_at": t % 0}]
        jobs += [{"id": f"m{i}", "kind": "auto_mover_move", "family": "traffic",
                  "status": "done", "label": "Moved Email 1 to Version B",
                  "finished_at": t % (i + 1)} for i in range(4)]
        got = self.group(jobs)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["group"])
        self.assertEqual(got[0]["n"], 5)
        self.assertEqual(got[0]["label"],
                         "Auto-mover moved traffic on 4 of 16 campaigns reviewed")

    def test_wakeups_sum_their_counts(self):
        jobs = [{"id": f"w{i}", "kind": "warmup_resume", "family": "mailbox",
                 "status": "done", "finished_at": "2026-09-03T11:1%d:00Z" % i,
                 "counts": {"resumed": 3, "smartlead_capped": 1, "domains": 1}}
                for i in range(3)]
        got = self.group(jobs)
        self.assertEqual(got[0]["label"], "Woke up 12 inboxes across 3 domains")

    def test_rest_enforcement_group(self):
        jobs = [{"id": f"r{i}", "kind": "rest_enforce", "family": "mailbox",
                 "status": "done", "finished_at": "2026-09-03T12:0%d:00Z" % i,
                 "counts": {"boxes": 25, "domains": 1}} for i in range(2)]
        self.assertEqual(self.group(jobs)[0]["label"], "Re-parked 50 mailboxes on 2 domains")

    def test_different_families_never_merge(self):
        jobs = [{"id": "a", "kind": "auto_mover_move", "family": "traffic", "status": "done",
                 "finished_at": "2026-09-03T10:00:00Z"},
                {"id": "b", "kind": "warmup_resume", "family": "mailbox", "status": "done",
                 "finished_at": "2026-09-03T10:05:00Z"}]
        got = self.group(jobs)
        self.assertEqual([g["group"] for g in got], [False, False])

    def test_different_hour_buckets_never_merge(self):
        jobs = [{"id": "a", "kind": "warmup_resume", "family": "mailbox", "status": "done",
                 "finished_at": "2026-09-03T10:59:00Z"},
                {"id": "b", "kind": "warmup_resume", "family": "mailbox", "status": "done",
                 "finished_at": "2026-09-03T11:01:00Z"}]
        self.assertEqual([g["group"] for g in self.group(jobs)], [False, False])

    def test_failed_and_done_never_merge(self):
        jobs = [{"id": "a", "kind": "warmup_resume", "family": "mailbox", "status": "failed",
                 "finished_at": "2026-09-03T10:01:00Z"},
                {"id": "b", "kind": "warmup_resume", "family": "mailbox", "status": "done",
                 "finished_at": "2026-09-03T10:02:00Z"}]
        self.assertEqual([g["group"] for g in self.group(jobs)], [False, False])

    def test_single_job_stays_a_plain_row(self):
        got = self.group([{"id": "solo", "kind": "verify", "family": "data",
                           "status": "done", "finished_at": "2026-09-03T10:00:00Z"}])
        self.assertEqual(got, [{"group": False, "id": "solo"}])


if __name__ == "__main__":
    unittest.main()
