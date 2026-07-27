"""Times the setter's Regenerate button end to end, the way the browser sees it.

Drives the SAME two calls setter.html's runRedraftJob makes — POST
/api/setter/queue/redraft with async:true, then poll
/api/setter/queue/redraft/status — and reports the wall clock from the POST to
the status response that says "done". Polls every 250ms so the harness itself
never becomes the thing being measured (the UI's own 2s first-sleep is measured
separately, in the browser).

Run:  python3 app/test_redraft_speed.py                 # production
      BASE=http://127.0.0.1:7911 python3 app/test_redraft_speed.py
      python3 app/test_redraft_speed.py 1222 1226 1223  # override the rows

Done-rule (setter-regen-speed-fix): p50 <= 3.0s, max <= 5.0s, 0 errors over 5
runs. Exits non-zero when that fails.

NB a regenerate REWRITES that row's draft — exactly what the button does, agent
is draft_only, nothing sends. The default rows are deliberately fixed so the
same three get churned every run rather than a fresh set each time.
"""

import base64
import hashlib
import hmac
import json
import os
import ssl
import statistics
import sys
import time
import urllib.request

BASE = os.environ.get("BASE", "https://navreo-signals.onrender.com")
RUNS = int(os.environ.get("RUNS", "5"))
# small / mid / large reply bodies (1.3KB, 2.6KB, 8.3KB) — the 8KB row is the
# one the 25-42s measurement in setter.py was taken on.
ROWS = [int(x) for x in sys.argv[1:]] or [1222, 1226, 1223]

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                                        # noqa: BLE001
    SSL_CTX = ssl.create_default_context()
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE


def _cookie() -> str:
    env = {}
    for line in open(os.path.expanduser("~/.navreo-keys.env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    secret = hashlib.sha256((env.get("SUPABASE_SERVICE_ROLE_KEY", "")
                             + ":navreo-session-v1").encode()).digest()
    payload = f"bjion@navreo.ai|{int(time.time()) + 3600}".encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return "navreo_session=" + base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


COOKIE = _cookie()


def call(method, path, body=None, timeout=300):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Cookie", COOKIE)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read() or b"{}")


def one_run(row_id):
    """-> (seconds, error_or_None, stages_dict). Mirrors runRedraftJob."""
    t0 = time.time()
    try:
        started = call("POST", "/api/setter/queue/redraft", {"id": row_id, "async": True})
    except Exception as e:                               # noqa: BLE001
        return time.time() - t0, f"POST failed: {e}", {}
    job = started.get("job_id")
    if not job:                                          # answered synchronously
        return time.time() - t0, started.get("error"), started.get("stages") or {}
    while time.time() - t0 < 300:
        time.sleep(0.25)
        try:
            st = call("GET", f"/api/setter/queue/redraft/status?job={job}")
        except Exception:                                # noqa: BLE001
            continue                                     # a blip must not kill the wait
        state = st.get("state")
        if state == "running":
            continue
        stages = st.get("stages") or {}
        if state == "error":
            return time.time() - t0, st.get("error") or "the regenerate failed", stages
        if state == "unknown":
            return time.time() - t0, "job lost (server restart)", stages
        return time.time() - t0, None, stages           # done
    return time.time() - t0, "timed out waiting for the job", {}


def main():
    ver = ""
    try:
        ver = (call("GET", "/api/version") or {}).get("commit", "")[:7]
    except Exception:                                    # noqa: BLE001
        pass
    print(f"BASE={BASE}  commit={ver or '?'}  rows={ROWS}  runs={RUNS}\n")

    times, errors, all_stages = [], [], []
    for i in range(RUNS):
        row_id = ROWS[i % len(ROWS)]
        secs, err, stages = one_run(row_id)
        times.append(secs)
        if err:
            errors.append(err)
        if stages:
            all_stages.append(stages)
        stage_txt = ("  " + " ".join(f"{k}={v}ms" for k, v in stages.items())) if stages else ""
        print(f"  run {i + 1}  row {row_id}  {secs:6.2f}s  {'ERROR: ' + err if err else 'ok'}{stage_txt}")

    p50 = statistics.median(times)
    worst = max(times)
    print(f"\n  p50 {p50:.2f}s   max {worst:.2f}s   errors {len(errors)}/{RUNS}")
    if all_stages:
        keys = sorted({k for s in all_stages for k in s})
        print("  stages (median ms): "
              + "  ".join(f"{k}={statistics.median([s.get(k, 0) for s in all_stages]):.0f}" for k in keys))

    ok = p50 <= 3.0 and worst <= 5.0 and not errors
    print("\n" + ("[PASS] done-rule met (p50<=3.0s, max<=5.0s, 0 errors)"
                  if ok else "[FAIL] done-rule not met (p50<=3.0s, max<=5.0s, 0 errors)"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
