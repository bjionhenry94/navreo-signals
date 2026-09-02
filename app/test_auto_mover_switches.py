"""Variant Auto-Mover — Step 3 switch tests.

Covers the two switches and nothing else (the mover itself is Step 4):
  * ui_prefs is now a KEYED PATCH — patching one key must not drop a sibling,
    and show_demo_clients must behave exactly as it did before.
  * auto_mover_enabled defaults to False (the mover is inert until armed).
  * the per-campaign switch defaults to `inherit` with no stored row, persists
    on/off, and rejects anything else with a 400.

Supabase is mocked at server.sb() the way the other server tests do it.
Run: NAVREO_NO_BG=1 python3 app/test_auto_mover_switches.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NAVREO_NO_BG", "1")
import server

_fail = 0
def check(name, cond, detail=""):
    global _fail
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _fail += 1


# ── a tiny in-memory Supabase ───────────────────────────────────────────────
STORE = {"ui_prefs": None, "prefs": {}, "moves": []}
CALLS = []

def fake_sb(method, path, body=None, prefer="", **kw):
    CALLS.append((method, path))
    if path.startswith("deliverability_audit_cache?id=eq.ui_prefs"):
        return [{"blob": STORE["ui_prefs"]}] if STORE["ui_prefs"] is not None else []
    if path.startswith("deliverability_audit_cache?on_conflict=id"):
        STORE["ui_prefs"] = dict(body.get("blob") or {})
        return []
    if path.startswith("auto_mover_campaign_prefs?on_conflict"):
        STORE["prefs"][str(body["campaign_id"])] = dict(body)
        return []
    if path.startswith("auto_mover_campaign_prefs?campaign_id=eq."):
        cid = path.split("campaign_id=eq.", 1)[1].split("&", 1)[0]
        row = STORE["prefs"].get(cid)
        return [row] if row else []
    if path.startswith("auto_mover_moves?campaign_id=eq."):
        cid = path.split("campaign_id=eq.", 1)[1].split("&", 1)[0]
        return [m for m in STORE["moves"] if str(m.get("campaign_id")) == cid][:1]
    if path.startswith("auto_mover_moves?select="):
        rows = list(STORE["moves"])
        if "or=(outcome.eq.issue" in path:
            rows = [m for m in rows if m.get("outcome") == "issue" or m.get("issue_kind")]
        return rows
    return []

server.sb = fake_sb

def reset():
    STORE["ui_prefs"] = None
    STORE["prefs"] = {}
    STORE["moves"] = []
    server._UI_PREFS_TS = 0.0
    for k, (_c, d) in server._UI_PREFS_KEYS.items():
        server._UI_PREFS[k] = d.copy() if isinstance(d, dict) else d


# ── 1. defaults ─────────────────────────────────────────────────────────────
reset()
p = server._ui_prefs(force=True)
check("auto_mover_enabled defaults False", p.get("auto_mover_enabled") is False, p)
check("show_demo_clients defaults False", p.get("show_demo_clients") is False, p)
check("auto_mover_breaker defaults to an empty dict", p.get("auto_mover_breaker") == {}, p)
check("auto_mover_enabled() helper is False by default",
      server.auto_mover_enabled(force=True) is False)

# ── 2. legacy show_demo_clients behaviour is unchanged ──────────────────────
reset()
blob = server._ui_prefs_set(True)            # the ORIGINAL bare-bool call shape
check("legacy bool call sets show_demo_clients", blob.get("show_demo_clients") is True, blob)
check("legacy bool call leaves auto_mover_enabled off",
      blob.get("auto_mover_enabled") is False, blob)
check("show_demo_clients() reads True", server.show_demo_clients() is True)
blob = server._ui_prefs_set(False)
check("legacy bool call turns it back off", blob.get("show_demo_clients") is False, blob)
check("show_demo_clients() reads False", server.show_demo_clients() is False)

# the POST-shaped dict patch is the same behaviour
reset()
blob = server._ui_prefs_set({"show_demo_clients": True})
check("dict patch sets show_demo_clients", blob.get("show_demo_clients") is True, blob)
check("stored blob carries every declared key",
      set(STORE["ui_prefs"] or {}) == set(server._UI_PREFS_KEYS), STORE["ui_prefs"])

# ── 3. keyed patch round-trip: one key never drops a sibling ────────────────
reset()
server._ui_prefs_set({"show_demo_clients": True})
blob = server._ui_prefs_set({"auto_mover_enabled": True})
check("patching auto_mover_enabled keeps show_demo_clients",
      blob.get("show_demo_clients") is True and blob.get("auto_mover_enabled") is True, blob)
blob = server._ui_prefs_set({"show_demo_clients": False})
check("patching show_demo_clients keeps auto_mover_enabled",
      blob.get("show_demo_clients") is False and blob.get("auto_mover_enabled") is True, blob)
fresh = server._ui_prefs(force=True)
check("a fresh read agrees with the patch",
      fresh.get("auto_mover_enabled") is True and fresh.get("show_demo_clients") is False, fresh)
check("auto_mover_enabled() helper follows the patch",
      server.auto_mover_enabled(force=True) is True)

# the breaker rides the same blob
blob = server._ui_prefs_set({"auto_mover_breaker":
                             {"tripped": True, "reason": "counter drop", "at": "2026-09-02T00:00:00Z"}})
check("breaker persists as a dict", blob["auto_mover_breaker"]["tripped"] is True, blob)
check("breaker patch keeps the other keys",
      blob.get("auto_mover_enabled") is True, blob)
check("a fresh read gets the breaker back",
      server._ui_prefs(force=True)["auto_mover_breaker"].get("reason") == "counter drop")

# unknown keys are ignored, never stored
blob = server._ui_prefs_set({"nonsense_key": 1})
check("unknown patch keys are ignored", "nonsense_key" not in blob, blob)

# ── 4. per-campaign switch ──────────────────────────────────────────────────
reset()
s, b = server.api_campaign_auto_move_get("3445988")
check("per-campaign GET defaults to inherit", s == 200 and b.get("mode") == "inherit", (s, b))
check("per-campaign GET has no last_auto_move yet", b.get("last_auto_move") is None, b)
check("per-campaign GET reports the global switch",
      b.get("global_enabled") is False, b)
check("a default read stores nothing", STORE["prefs"] == {}, STORE["prefs"])

s, b = server.api_campaign_auto_move_set("3445988", {"mode": "on"}, "bjion@navreo.ai")
check("POST on -> 200", s == 200 and b.get("mode") == "on", (s, b))
check("POST records the actor", b.get("set_by") == "bjion@navreo.ai", b)
check("POST persists", server.auto_mover_campaign_mode("3445988") == "on")
s, b = server.api_campaign_auto_move_get("3445988")
check("GET reads back on", b.get("mode") == "on", b)

s, b = server.api_campaign_auto_move_set("3445988", {"mode": "off"}, "bjion@navreo.ai")
check("POST off -> 200", s == 200 and b.get("mode") == "off", (s, b))
check("GET reads back off", server.api_campaign_auto_move_get("3445988")[1].get("mode") == "off")
s, b = server.api_campaign_auto_move_set("3445988", {"mode": "inherit"}, "bjion@navreo.ai")
check("POST inherit -> 200", s == 200 and b.get("mode") == "inherit", (s, b))

# case is normalised, so "ON" is the same choice as "on" — not an error
s, b = server.api_campaign_auto_move_set("3445988", {"mode": "ON"}, "x@y.z")
check("mode is case-insensitive", s == 200 and b.get("mode") == "on", (s, b))
server.api_campaign_auto_move_set("3445988", {"mode": "inherit"}, "x@y.z")

# invalid modes
for bad in ("yes", "", None, "delete", 1, "on;drop", "  ", "off off"):
    s, b = server.api_campaign_auto_move_set("3445988", {"mode": bad}, "x@y.z")
    check("invalid mode %r -> 400" % (bad,), s == 400 and not b.get("ok"), (s, b))
check("an invalid POST did not change the stored mode",
      server.auto_mover_campaign_mode("3445988") == "inherit")
s, b = server.api_campaign_auto_move_set("", {"mode": "on"}, "x@y.z")
check("missing campaign id -> 400", s == 400, (s, b))
s, b = server.api_campaign_auto_move_get("")
check("missing campaign id on GET -> 400", s == 400, (s, b))

# a stored mode outside the allowlist still reads as inherit
STORE["prefs"]["999"] = {"campaign_id": "999", "mode": "garbage"}
check("a corrupt stored mode reads as inherit",
      server.auto_mover_campaign_mode("999") == "inherit")

# ── 5. last_auto_move + the moves feed ──────────────────────────────────────
STORE["moves"] = [{"id": 2, "campaign_id": "3445988", "step": 1, "action": "scale_winner",
                   "winner": "A", "outcome": "moved", "issue_kind": None,
                   "created_at": "2026-09-02T10:00:00Z"},
                  {"id": 1, "campaign_id": "3445988", "step": 1, "action": "back_winner",
                   "winner": "B", "outcome": "issue", "issue_kind": "flap",
                   "created_at": "2026-09-01T10:00:00Z"}]
s, b = server.api_campaign_auto_move_get("3445988")
check("GET surfaces the latest move", (b.get("last_auto_move") or {}).get("id") == 2, b)
feed = server.api_auto_mover_moves(50)
check("moves feed returns rows", feed.get("ok") and feed.get("count") == 2, feed)
feed = server.api_auto_mover_moves(50, issues_only=True)
check("issues filter returns only the flagged row",
      [m["id"] for m in feed["moves"]] == [1], feed)

# a Supabase blow-up on the feed degrades to empty, never a 500
_old = server.sb
server.sb = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
feed = server.api_auto_mover_moves(50)
check("a feed read error degrades to an empty list",
      feed.get("ok") and feed.get("moves") == [] and feed.get("warning"), feed)
check("a campaign-mode read error inherits, it never arms",
      server.auto_mover_campaign_mode("3445988") == "inherit")
server.sb = _old

print(("\nFAILED %d check(s)" % _fail) if _fail else "\nAll checks passed.")
sys.exit(1 if _fail else 0)
