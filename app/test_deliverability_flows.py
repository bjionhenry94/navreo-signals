"""End-to-end tests for the three deliverability flows against DELIV_MOCK=1.

Drives the SAME HTTP calls the deliverability tab makes (per-domain and
per-email scoped fix calls, the run_first self-heal sequence, the native
process-new-selected endpoint) against the mock fleet — zero real network.

Run:  DELIV_MOCK=1 PORT=7911 python3 app/server.py   (in another shell)
      python3 app/test_deliverability_flows.py
Exits non-zero on the first failure. Needs ~/.navreo-keys.env for the
session-cookie mint (same recipe as server.py's _mint_session)."""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:" + os.environ.get("PORT", "7911")


def _cookie() -> str:
    env = {}
    for line in open(os.path.expanduser("~/.navreo-keys.env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    secret = hashlib.sha256((env.get("SUPABASE_SERVICE_ROLE_KEY", "")
                             + ":navreo-session-v1").encode()).digest()
    payload = f"tester@navreo.local|{int(time.time()) + 3600}".encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return "navreo_session=" + base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


COOKIE = _cookie()


def call(method, path, body=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Cookie", COOKIE)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def b64u(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


FAILS = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name + (": " + detail if detail else ""))


def reset():
    call("POST", "/api/deliverability/_mock/scenario", {"reset": True})


def scenario(**kw):
    call("POST", "/api/deliverability/_mock/scenario", kw)


def state():
    return call("GET", "/api/deliverability/_mock/state")


def fresh_audit(max_wait=30):
    """UI sequence: POST _audit/refresh, poll GET _audit until a blob lands."""
    call("POST", "/api/deliverability/_audit/refresh", {"force": True})
    deadline = time.time() + max_wait
    while time.time() < deadline:
        st = call("GET", "/api/deliverability/_audit")
        if st.get("blob") is not None and not st.get("running"):
            return st["blob"]
        time.sleep(0.5)
    raise AssertionError("audit blob never landed")


def heal_and_retry(path_qs):
    """The UI's makeSelfHealingCall: on run_first, refresh audit then retry once."""
    j = call("POST", "/api/deliverability/" + path_qs)
    if j.get("ok") is False and j.get("reason") == "run_first":
        fresh_audit()
        j = call("POST", "/api/deliverability/" + path_qs)
    return j


# ── Flow A: boot + audit blob shape ─────────────────────────────────────────
def test_boot():
    reset()
    camps = call("GET", "/api/deliverability/campaigns")
    check("A1 probe returns campaign roster", isinstance(camps, list) and len(camps) >= 3)
    blob = fresh_audit()
    sig = blob.get("signature", {})
    lc = blob.get("lifecycle", {})
    wc = blob.get("warmupConfig", {})
    check("A2 signature counts 9 missing + 5 mismatch",
          len(sig.get("missing", [])) == 9 and len(sig.get("mismatch", [])) == 5,
          f"got {len(sig.get('missing', []))}/{len(sig.get('mismatch', []))}")
    check("A3 lifecycle 9 new/unprocessed", len(lc.get("newUnprocessed", [])) == 9,
          str(len(lc.get("newUnprocessed", []))))
    check("A4 warmup 14 off + 8 wrong settings",
          len(wc.get("notWarming", [])) == 14 and len(wc.get("wrongSettings", [])) == 8,
          f"got {len(wc.get('notWarming', []))}/{len(wc.get('wrongSettings', []))}")
    row = (lc.get("newUnprocessed") or [{}])[0]
    check("A5 new rows carry email/tagged/inCampaign/created",
          all(k in row for k in ("email", "tagged", "inCampaign", "created")), str(row))


# ── Flow B: process-new-selected (native Smartlead path) ────────────────────
def test_process_new():
    reset()
    blob = fresh_audit()
    rows = blob["lifecycle"]["newUnprocessed"]
    tag_emails = [r["email"] for r in rows]                    # additive: tag ALL ticked
    camp_emails = [r["email"] for r in rows if r.get("inCampaign") is False]
    camp = call("GET", "/api/deliverability/campaigns")[0]["id"]

    j = call("POST", "/api/process-new-selected",
             {"tag": "Mock Batch (Test)", "campaign_id": str(camp),
              "tag_emails": tag_emails, "camp_emails": camp_emails})
    check("B1 happy path ok", j.get("ok") is True, str(j))
    check("B2 tagged == ticked count (additive rule)", j.get("tagged") == len(tag_emails), str(j))
    check("B3 campaign add == not-in-campaign count", j.get("addedToCampaign") == len(camp_emails), str(j))
    blob2 = fresh_audit()
    check("B4 next audit shows 0 new/unprocessed",
          len(blob2["lifecycle"]["newUnprocessed"]) == 0,
          str(len(blob2["lifecycle"]["newUnprocessed"])))

    # New-tag mint must be idempotent by name (duplicate tag objects are undeletable).
    tags_before = [t["name"] for t in state().get("tags", [])]
    j2 = call("POST", "/api/process-new-selected",
              {"tag": "Mock Batch (Test)", "campaign_id": "",
               "tag_emails": tag_emails[:2], "camp_emails": []})
    tags_after = [t["name"] for t in state().get("tags", [])]
    check("B5 re-using a tag name mints no duplicate",
          j2.get("ok") is True and tags_after.count("Mock Batch (Test)") == 1
          and len(tags_after) == len(tags_before), f"{tags_before} -> {tags_after}")

    # 429 storm: the server's backoff must absorb it, not surface an error.
    reset()
    scenario(rate429_next=3)
    rows = fresh_audit()["lifecycle"]["newUnprocessed"]
    t0 = time.time()
    j3 = call("POST", "/api/process-new-selected",
              {"tag": "RateLimit Tag", "campaign_id": "",
               "tag_emails": [r["email"] for r in rows[:3]], "camp_emails": []}, timeout=120)
    check("B6 429 storm absorbed by backoff", j3.get("ok") is True and j3.get("tagged") == 3,
          f"{j3} after {time.time()-t0:.1f}s")

    # Unknown addresses must be reported, never silently dropped.
    j4 = call("POST", "/api/process-new-selected",
              {"tag": "RateLimit Tag", "campaign_id": "",
               "tag_emails": ["ghost@nowhere-mock.test"], "camp_emails": []})
    check("B7 unresolved addresses surfaced", "unresolved" in j4 and j4["unresolved"] == ["ghost@nowhere-mock.test"], str(j4))

    j5 = call("POST", "/api/process-new-selected",
              {"tag": "", "campaign_id": "", "tag_emails": [], "camp_emails": []})
    check("B8 empty request -> nothing_to_do", j5.get("ok") is False and j5.get("reason") == "nothing_to_do", str(j5))


# ── Flow C: fix-signatures (per-domain + per-email, heal, partial fail) ─────
def test_signatures():
    reset()
    blob = fresh_audit()
    broken = blob["signature"]["missing"] + blob["signature"]["mismatch"]
    tpl = "Best,<br>{{name}}<br>Mock Co"
    base = "fix-signatures?tpl=" + b64u(tpl)

    # All-in-scope: one call per domain, exactly as sigApply sends it.
    domains = sorted({r["email"].split("@")[1] for r in broken})
    ok = failed = 0
    for d in domains:
        j = heal_and_retry(base + "&filter=" + b64u("@" + d))
        ok += j.get("ok") or 0
        failed += j.get("failed") or 0
    check("C1 per-domain sweep fixes all 14", ok >= 14 and failed == 0, f"ok={ok} failed={failed}")
    blob2 = fresh_audit()
    check("C2 next audit shows 0 signature issues",
          not blob2["signature"]["missing"] and not blob2["signature"]["mismatch"])

    # Stale snapshot: first call must answer run_first; the UI heal must recover.
    reset()
    victims = fresh_audit()["signature"]["missing"]  # pristine again after reset
    victim = victims[0]
    scenario(stale_snapshot=True)  # AFTER the audit — refreshing clears staleness
    raw = call("POST", "/api/deliverability/" + base + "&filter=" + b64u(victim["email"]))
    check("C3 stale snapshot answers run_first", raw.get("ok") is False and raw.get("reason") == "run_first", str(raw))
    j = heal_and_retry(base + "&filter=" + b64u(victim["email"]))
    check("C4 self-heal (refresh + retry) recovers", j.get("reason") != "run_first" and (j.get("ok") or 0) >= 0 and j.get("failed", 0) == 0, str(j))

    # Partial failure: injected fail lands in fails[] with a reason.
    reset()
    blob = fresh_audit()
    broken = blob["signature"]["missing"]
    bad = broken[0]["email"]
    scenario(fail_emails=[bad])
    d = bad.split("@")[1]
    j = heal_and_retry(base + "&filter=" + b64u("@" + d))
    in_fails = any(f.get("email") == bad for f in j.get("fails", []))
    check("C5 injected failure surfaced in fails[]", j.get("failed", 0) >= 1 and in_fails, str(j))
    blob2 = fresh_audit()
    still = any(r["email"] == bad for r in blob2["signature"]["missing"])
    check("C6 failed mailbox stays on the broken list", still)


# ── Flow D: fix-warmup (selection-scoped, wrongSettings included) ───────────
def test_warmup():
    reset()
    blob = fresh_audit()
    wc = blob["warmupConfig"]
    rows = wc["notWarming"] + wc["wrongSettings"]
    base = "fix-warmup?perDay=35&rampup=5&replyRate=38"

    # Hand-picked subset: one call per full address (wuApply subset path).
    subset = [r["email"] for r in rows[:3]]
    ok = failed = 0
    for e in subset:
        j = heal_and_retry(base + "&filter=" + b64u(e))
        ok += j.get("ok") or 0
        failed += j.get("failed") or 0
    check("D1 per-email subset applies cleanly", ok >= 3 and failed == 0, f"ok={ok} failed={failed}")
    blob2 = fresh_audit()
    left = {r["email"] for r in blob2["warmupConfig"]["notWarming"] + blob2["warmupConfig"]["wrongSettings"]}
    check("D2 only the subset dropped off the list",
          not (set(subset) & left) and len(left) == len(rows) - len(set(subset) & {r["email"] for r in rows}),
          f"left={len(left)} expected={len(rows)-3}")

    # All-in-scope per-domain sweep clears both groups.
    ok = failed = 0
    for d in sorted({e.split("@")[1] for e in left}):
        j = heal_and_retry(base + "&filter=" + b64u("@" + d))
        ok += j.get("ok") or 0
        failed += j.get("failed") or 0
    blob3 = fresh_audit()
    wc3 = blob3["warmupConfig"]
    check("D3 per-domain sweep clears warmup lists (incl. wrong settings)",
          not wc3["notWarming"] and not wc3["wrongSettings"],
          f"off={len(wc3['notWarming'])} wrong={len(wc3['wrongSettings'])}")

    # Stale snapshot heal on warmup too.
    reset()
    scenario(stale_snapshot=True)
    j = heal_and_retry(base + "&filter=" + b64u("@" + rows[0]["email"].split("@")[1]))
    check("D4 warmup self-heal recovers", j.get("reason") != "run_first" and j.get("failed", 0) == 0, str(j))


# ── Flow E: high bounce-rate tab — pause/resume with exact cap restore ──────
def test_bounce_pause_resume():
    """The High bounce-rate tab's contract: >3% domains listed, Pause zeroes
    every sending box on the domain, Resume restores each box's EXACT
    pre-pause cap (stash semantics — never a house default), and a spent
    stash restores nothing on a second Resume."""
    reset()
    dom = "acme-mock-2.test"
    dh = call("GET", "/api/deliverability/domain-health?start=&end=&minSent=500&cutoff=0.7")
    hot = sorted(r["domain"] for r in dh["rows"] if r["bounce_rate"] > 3)
    check("E1 domain-health flags exactly the >3% mock domains",
          hot == ["acme-mock-2.test", "arnic-mock-1.test"], str(hot))

    def dom_caps():
        j = call("GET", "/api/deliverability/inboxes?view=all&batch=")
        return {r["email"]: r["cap"] for r in j["rows"] if r["domain"] == dom}

    before = dom_caps()
    sending = sum(1 for c in before.values() if c > 0)
    check("E2 mock domain has sending boxes to pause", sending > 0, str(before))
    j = call("POST", "/api/deliverability/bounce-pause?domain=" + dom)
    check("E3 pause zeroes every sending box",
          j.get("paused") == sending and not j.get("failed"), str(j))
    check("E4 all caps at 0 after pause", all(c == 0 for c in dom_caps().values()),
          str(dom_caps()))
    j = call("POST", "/api/deliverability/bounce-resume?domain=" + dom)
    check("E5 resume restores the paused boxes",
          j.get("resumed") == sending and not j.get("failed"), str(j))
    check("E6 caps restored EXACTLY (stash, never house defaults)",
          dom_caps() == before, f"before={before} after={dom_caps()}")
    j = call("POST", "/api/deliverability/bounce-resume?domain=" + dom)
    check("E7 stash cleared — a second resume restores nothing",
          (j.get("resumed") or 0) == 0, str(j))


def _page(path, with_cookie=True):
    """Raw GET of an app page. Returns (status, body_text); redirects NOT followed."""
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ANN002, ANN003
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(BASE + path, method="GET")
    if with_cookie:
        req.add_header("Cookie", COOKIE)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def test_pages_layout():
    """The engine room lives on mailboxes.html, and ONLY there (move of 2026-08-03).

    Guards the split: the Analytics page must not quietly re-grow the embed
    (its fold + deferred mount were removed so the hub owns its own boot),
    and the Mailboxes page must actually carry the manager."""
    st, mbx = _page("/app/mailboxes.html")
    check("P1 mailboxes.html serves for a logged-in user", st == 200, f"status {st}")
    check("P2 mailboxes.html mounts the engine room",
          "dlv-embed-slot" in mbx and "deliverability-tab.js" in mbx and "DLV_EMBED" in mbx,
          "missing embed slot / engine script / DLV_EMBED flag")
    st, dlv = _page("/app/deliverability.html")
    check("P3 deliverability.html serves for a logged-in user", st == 200, f"status {st}")
    check("P4 analytics page carries NO engine-room embed",
          "dlv-embed" not in dlv and "DLV_EMBED" not in dlv and "deliverability-tab.js" not in dlv,
          "an engine-room marker crept back into deliverability.html")
    check("P5 analytics page links to the new Mailboxes tab", "mailboxes.html" in dlv,
          "moved-note link missing")
    st, _ = _page("/app/mailboxes.html", with_cookie=False)
    check("P6 mailboxes.html is login-gated", st in (301, 302, 303, 307, 401, 403), f"status {st}")


if __name__ == "__main__":
    for fn in (test_boot, test_process_new, test_signatures, test_warmup,
               test_bounce_pause_resume, test_pages_layout):
        print(f"\n── {fn.__name__} ──")
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a crashed test is a failure, not an abort
            check(fn.__name__ + " crashed", False, repr(e))
    reset()
    print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILURES'}")
    for f in FAILS:
        print("  ✗", f)
    sys.exit(1 if FAILS else 0)
