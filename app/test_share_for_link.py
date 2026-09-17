"""Any shared conversation link opens without a login (owner ruling 2026-09-17):
the (email, message-id) exchange only ever hands out the OWNING client's token."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import setter

MID = "<BY3PR19MB4977ABCDEF@BY3PR19MB4977.namprd19.prod.outlook.com>"


def _wire(monkeypatch, rows_for, client_map):
    calls = []

    def sb(method, q, *a, **k):
        calls.append(q)
        return rows_for(q)
    monkeypatch.setattr(setter, "_SB", sb)
    monkeypatch.setattr(setter, "_client_campaign_map", lambda force=False: client_map)
    return calls


def test_client_reply_gets_that_clients_token(monkeypatch):
    _wire(monkeypatch, lambda q: [{"smartlead_campaign_id": 3966401}] if q.startswith("replies?") else [],
          {"remission": frozenset({"3966401"}), "revive": frozenset({"1"})})
    st, body = setter.route_share_for_link_get({"email": ["A@x.org"], "message_id": [MID]})
    assert st == 200
    assert setter.verify_client_share(body["share"])[0] == "remission"


def test_navreo_own_reply_stays_behind_login(monkeypatch):
    _wire(monkeypatch, lambda q: [{"smartlead_campaign_id": 777}], {"remission": frozenset({"3966401"})})
    st, body = setter.route_share_for_link_get({"email": ["a@x.org"], "message_id": [MID]})
    assert st == 404 and "share" not in body


def test_email_alone_or_unknown_pair_is_a_uniform_miss(monkeypatch):
    calls = _wire(monkeypatch, lambda q: [], {"remission": frozenset({"3966401"})})
    assert setter.route_share_for_link_get({"email": ["a@x.org"]})[0] == 404
    assert calls == []          # no message-id -> never even looks
    assert setter.route_share_for_link_get({"email": ["a@x.org"], "message_id": [MID]}) == \
        setter.route_share_for_link_get({"email": [""], "message_id": [MID]})


def test_route_is_registered_and_public():
    assert setter.GET_ROUTES["/api/setter/share-for-link"] is setter.route_share_for_link_get
    assert "/api/setter/share-for-link" not in setter.CLIENT_SHARE_GET
    src = open(os.path.join(os.path.dirname(__file__), "server.py")).read()
    blk = src[src.index("_AUTH_PUBLIC_GET = {"):][:3000]
    assert '"/api/setter/share-for-link"' in blk
