"""The hosted-clients registry is the ONE source for client attribution in
capacity and deliverability too (Bjion 2026-09-16: "automatically start
adjusting whenever we onboard a new client"). server.py must DERIVE its
attribution maps from setter.NAVREO_HOSTED_CLIENTS - never hand-list a hosted
client - and every registry row must carry the display label those maps use.
Pure-python: reads server.py as text so importing server (and its threads) is
never needed."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import setter  # noqa: E402

SERVER_SRC = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
HOSTED = setter.NAVREO_HOSTED_CLIENTS


def _block(name):
    m = re.search(r"^%s = (?:tuple)?\((.*?)^\)" % re.escape(name), SERVER_SRC, re.S | re.M)
    assert m, f"{name} not found in server.py"
    return m.group(0)


def test_registry_has_rows_and_every_row_has_a_label():
    assert len(HOSTED) >= 5
    for c in HOSTED:
        assert c.get("label") and c["label"].strip(), c
        assert c.get("token") and c.get("client_id"), c


def test_server_attribution_maps_derive_from_the_registry():
    for name in ("_SHARED_WS_CLIENTS", "_RESTORE_CLIENT_KEYWORDS"):
        blk = _block(name)
        assert "NAVREO_HOSTED_CLIENTS" in blk, f"{name} must derive from setter.NAVREO_HOSTED_CLIENTS"
        for c in HOSTED:
            assert ('"%s"' % c["token"]) not in blk, (
                f"{name} hand-lists hosted token {c['token']!r} - remove it; the registry row is the source")


def test_labels_are_the_display_labels_the_tool_always_used():
    want = {"touchpoint": "TouchPoint", "thunderbird": "ThunderBird",
            "altius": "Altius Reach", "revive": "REViVE", "greenshift": "Greenshift"}
    got = {c["token"]: c["label"] for c in HOSTED}
    for k, v in want.items():
        assert got.get(k) == v, (k, got.get(k))


def test_navreo_is_last_in_both_maps():
    for name in ("_SHARED_WS_CLIENTS", "_RESTORE_CLIENT_KEYWORDS"):
        blk = _block(name)
        assert blk.rstrip().endswith('("navreo", "Navreo")]\n)'), name


if __name__ == "__main__":
    for fn in (test_registry_has_rows_and_every_row_has_a_label,
               test_server_attribution_maps_derive_from_the_registry,
               test_labels_are_the_display_labels_the_tool_always_used,
               test_navreo_is_last_in_both_maps):
        fn(); print("ok", fn.__name__)
