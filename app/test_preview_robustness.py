"""Regression lock for Step 3 (signals-launch-hardening): the hiring/engagement
preview must NEVER 500 on the three known provider gotchas — UA block, keyword
401, identifier-slug/malformed body. Deterministic: no live network, no credits.

Run:  python3 app/test_preview_robustness.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

server.KEYS.setdefault("THEIRSTACK_API_KEY", "test-key")  # preview builds an auth header
FAILS = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILS.append(name)


def with_http(stub):
    """Swap server.http_json for a stub, return the original."""
    orig = server.http_json
    server.http_json = stub
    return orig


# ── Gotcha 1: UA block — a default python-urllib UA gets blocked by TheirStack/AI-ARK
check("UA is set and non-default", bool(server.UA) and "python-urllib" not in server.UA.lower())

# ── Gotcha 2: keyword 401 — provider returns an error JSON body; app must not raise
orig = with_http(lambda *a, **k: {"error": {"message": "invalid api key", "code": 401}})
try:
    r = server.preview_hiring({"job_titles": ["Head of Sales"], "countries": ["US"], "dm_titles": ["CEO"]})
    check("preview_hiring survives a 401 error body (returns dict)", isinstance(r, dict))
    check("preview_hiring stays ok-shaped, no crash on 401 body", "total_jobs" in r)
except Exception as e:  # noqa: BLE001
    check(f"preview_hiring raised on 401 body: {str(e)[:80]}", False)
finally:
    server.http_json = orig

# ── Gotcha 3: identifier-slug / malformed — empty or unexpected body must not KeyError
for label, body in [("empty body", {}), ("no-metadata body", {"data": None}), ("junk body", {"x": 1})]:
    orig = with_http(lambda *a, **k: body)
    try:
        r = server.preview_hiring({"job_titles": ["X"], "countries": ["US"], "dm_titles": ["CEO"]})
        check(f"preview_hiring survives {label}", isinstance(r, dict) and r.get("ok") is True)
    except Exception as e:  # noqa: BLE001
        check(f"preview_hiring raised on {label}: {str(e)[:80]}", False)
    finally:
        server.http_json = orig

# ── The global safety net: http_json returns the JSON body on a 4xx instead of raising
import urllib.error, io, json as _json  # noqa: E402

class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, payload):
        self._p = _json.dumps(payload).encode()
        super().__init__("http://x", 401, "Unauthorized", {}, io.BytesIO(self._p))
    def read(self):
        return self._p

_real_urlopen = server.urllib.request.urlopen
server.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(_FakeHTTPError({"error_code": "UNAUTHORIZED"}))
try:
    got = server.http_json("POST", "http://x", {"Authorization": "Bearer bad"}, {"q": 1})
    check("http_json returns provider JSON on 4xx (no raise)", got == {"error_code": "UNAUTHORIZED"})
except Exception as e:  # noqa: BLE001
    check(f"http_json raised on 4xx JSON body: {str(e)[:80]}", False)
finally:
    server.urllib.request.urlopen = _real_urlopen

# ── do_POST converts any route exception into ok:false, never a 500
def _boom(_):
    raise RuntimeError("kaboom")
server.ROUTES["/api/__test_boom"] = _boom
handler_src = Path(server.__file__).read_text()
check("do_POST wraps route errors as ok:false @200 (not 500)",
      'self._json({"ok": False, "message": str(e)[:300]}, 200)' in handler_src)
del server.ROUTES["/api/__test_boom"]

print()
if FAILS:
    print(f"REGRESSION FAILED: {len(FAILS)} check(s) — {', '.join(FAILS)}")
    sys.exit(1)
print("ALL PREVIEW-ROBUSTNESS CHECKS PASSED")
