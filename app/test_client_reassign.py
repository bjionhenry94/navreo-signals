"""Click the client pill to re-file a conversation (owner ask 2026-09-17).

Two halves under test: the server's label authority (so "Thunderbird Campaign 4
(financial services)" names ThunderBird, not the page's old "Navreo" default),
and the human override that outranks it - keyed by workspace + lead email so
it survives re-intake id swaps, and never visible inside a client share."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import setter

KOMAL = "komal.vaish@loanfactory.com"


class FakeSB:
    """Just enough PostgREST for the four tables the feature touches."""

    def __init__(self, scorecard=None, workspaces=None):
        self.scorecard = scorecard or {}
        self.workspaces = workspaces or []
        self.overrides = {}          # (ws, email) -> label
        self.calls = []

    def __call__(self, method, q, body=None, prefer=None):
        self.calls.append((method, q))
        if q.startswith("campaign_scorecard?select=client"):
            return [{"client": c} for c in self.scorecard.values()]
        if q.startswith("campaign_scorecard?"):
            ids = q.split("in.(")[1].split(")")[0].split(",")
            return [{"smartlead_campaign_id": int(i), "client": self.scorecard[i]}
                    for i in ids if i in self.scorecard]
        if q.startswith("workspaces?"):
            return self.workspaces
        if q.startswith(setter.CLIENT_OVERRIDE_TABLE):
            if method == "GET":
                return [{"workspace": w, "lead_email": e, "client_label": c}
                        for (w, e), c in self.overrides.items()]
            if method == "POST":
                self.overrides[(body["workspace"], body["lead_email"])] = body["client_label"]
                return None
            if method == "DELETE":
                ws = q.split("workspace=eq.")[1].split("&")[0]
                em = q.split("lead_email=eq.")[1].replace("%40", "@")
                self.overrides.pop((ws, em), None)
                return None
        return []


def _wire(monkeypatch, sb, parents=None, names=None):
    monkeypatch.setattr(setter, "_SB", sb)
    monkeypatch.setattr(setter, "_parent_map", lambda: parents or {})
    monkeypatch.setattr(setter, "_campaign_names_for", lambda ids: dict(names or {}))
    monkeypatch.setattr(setter, "_bust_read_caches", lambda *a, **k: None)
    setter._CLIENT_LABEL_CACHE.clear()
    setter._CLIENT_OVR_CACHE.update(at=0.0, map=None)
    setter._CLIENT_OPTIONS_CACHE.update(at=0.0, val=None)
    setter.client_share_clear()


def _row(cid=3800129, email=KOMAL, ws="navreo"):
    return {"id": 3876, "workspace": ws, "smartlead_campaign_id": cid, "lead_email": email}


def test_scorecard_names_the_campaign_the_page_used_to_call_navreo(monkeypatch):
    _wire(monkeypatch, FakeSB({"3800129": "ThunderBird"}))
    rows = [_row()]
    setter._attach_client_labels(rows)
    assert rows[0]["client_auto"] == "ThunderBird"
    assert "client_override" not in rows[0]


def test_subsequence_asks_its_parent_before_itself(monkeypatch):
    # "Interested Reply" is a shared subsequence the scorecard files under
    # Navreo; the lead came from a TouchPoint campaign, so the parent wins.
    _wire(monkeypatch, FakeSB({"900": "Navreo", "100": "TouchPoint"}), parents={"900": "100"})
    assert setter._client_labels_for([900]) == {"900": "TouchPoint"}


def test_unassigned_falls_to_the_name_marker_then_to_nothing(monkeypatch):
    _wire(monkeypatch, FakeSB({"1": "__unassigned", "2": "__unassigned"}),
          names={"1": "Remission Campaign 2 (clinics)", "2": "Interested Reply"})
    # a name that names nobody is left for the page's own fallbacks - never guessed
    assert setter._client_labels_for([1, 2]) == {"1": "Remission"}


def test_override_is_stored_canonically_and_stamped_on_every_row_of_the_lead(monkeypatch):
    sb = FakeSB({"3800129": "Navreo", "5": "Navreo"})
    _wire(monkeypatch, sb)
    st, body = setter.route_queue_client_post({"email": " Komal.Vaish@LoanFactory.com ",
                                               "workspace": "navreo", "client": "thunderbird"})
    assert st == 200 and body["client_override"] == "ThunderBird"   # the registry's spelling
    assert sb.overrides == {("navreo", KOMAL): "ThunderBird"}
    # a re-intaken row (new id) and a re-reply on another campaign both carry it
    rows = [_row(), {**_row(cid=5), "id": 9999}, _row(email="someone@else.com")]
    setter._attach_client_labels(rows)
    assert [r.get("client_override") for r in rows] == ["ThunderBird", "ThunderBird", None]
    assert setter._client_override_for("navreo", KOMAL.upper()) == "ThunderBird"


def test_same_email_in_another_workspace_is_untouched(monkeypatch):
    sb = FakeSB({"1": "Asteri"})
    _wire(monkeypatch, sb)
    setter.route_queue_client_post({"email": KOMAL, "workspace": "navreo", "client": "ThunderBird"})
    rows = [_row(cid=1, ws="asteri")]
    setter._attach_client_labels(rows)
    assert "client_override" not in rows[0]


def test_blank_client_puts_the_lead_back_on_automatic(monkeypatch):
    sb = FakeSB({"3800129": "ThunderBird"})
    _wire(monkeypatch, sb)
    setter.route_queue_client_post({"email": KOMAL, "workspace": "navreo", "client": "Amplifyy"})
    st, body = setter.route_queue_client_post({"email": KOMAL, "workspace": "navreo", "client": ""})
    assert st == 200 and body["client_override"] == ""
    assert sb.overrides == {}
    rows = [_row()]
    setter._attach_client_labels(rows)
    assert rows[0].get("client_auto") == "ThunderBird" and "client_override" not in rows[0]


def test_unknown_client_and_missing_email_are_refused_and_write_nothing(monkeypatch):
    sb = FakeSB({"1": "Navreo"})
    _wire(monkeypatch, sb)
    assert setter.route_queue_client_post({"email": KOMAL, "client": "Thunderbrid"})[0] == 400
    assert setter.route_queue_client_post({"email": "", "client": "Navreo"})[0] == 400
    assert setter.route_queue_client_post(["not", "a", "dict"])[0] == 400
    assert sb.overrides == {}
    assert not any(m in ("POST", "DELETE") for m, _q in sb.calls)


def test_a_write_the_store_swallowed_is_not_reported_as_saved(monkeypatch):
    sb = FakeSB({"1": "Navreo"})
    _wire(monkeypatch, sb)
    real = sb.__call__

    def lossy(method, q, body=None, prefer=None):
        if method == "POST":
            return None                      # accepted, never stored
        return real(method, q, body, prefer)
    monkeypatch.setattr(setter, "_SB", lossy)
    assert setter.route_queue_client_post({"email": KOMAL, "client": "ThunderBird"})[0] == 502


def test_options_are_canonical_deduped_and_carry_no_bucket_names(monkeypatch):
    _wire(monkeypatch, FakeSB({"1": "Navreo", "2": "thunderbird", "3": "__unassigned", "4": "KRG"},
                              workspaces=[{"id": "krg", "display_label": "KRG"},
                                          {"id": "grout", "display_label": "Grout"}]))
    st, body = setter.route_client_options_get({})
    opts = body["clients"]
    assert st == 200 and "__unassigned" not in opts
    assert opts.count("ThunderBird") == 1 and "thunderbird" not in opts
    assert {"Navreo", "KRG", "Grout", "Remission", "Amplifyy"} <= set(opts)
    assert opts == sorted(opts, key=str.lower)


def test_a_client_share_can_neither_read_nor_write_a_client_label(monkeypatch):
    sb = FakeSB({"3800129": "ThunderBird"})
    _wire(monkeypatch, sb)
    sb.overrides[("navreo", KOMAL)] = "Amplifyy"
    setter._SHARE_LOCAL.ids = frozenset({"3800129"})
    setter._SHARE_LOCAL.client = "thunderbird"
    try:
        rows = [_row()]
        setter._attach_client_labels(rows)
        assert "client_auto" not in rows[0] and "client_override" not in rows[0]
        assert setter.route_queue_client_post({"email": KOMAL, "client": "Navreo"})[0] == 403
        assert setter.route_client_options_get({})[0] == 403
        # second lock: even a stamped row is scrubbed on its way out
        assert setter.share_sanitise({"rows": [{"id": 1, "client_auto": "X", "client_override": "Y"}]}) \
            == {"rows": [{"id": 1}]}
    finally:
        setter.client_share_clear()
    assert sb.overrides == {("navreo", KOMAL): "Amplifyy"}


def test_routes_are_registered_owner_only_and_cache_exempt():
    assert setter.POST_ROUTES["/api/setter/queue/client"] is setter.route_queue_client_post
    assert setter.GET_ROUTES["/api/setter/client-options"] is setter.route_client_options_get
    assert "/api/setter/queue/client" not in setter.CLIENT_SHARE_POST
    assert "/api/setter/client-options" not in setter.CLIENT_SHARE_GET
    src = open(os.path.join(os.path.dirname(__file__), "server.py")).read()
    for gate in ("_AUTH_PUBLIC_POST = {", "_AUTH_PUBLIC_GET = {"):
        blk = src[src.index(gate):]
        blk = blk[:blk.index("}")]
        assert "/api/setter/queue/client" not in blk and "/api/setter/client-options" not in blk
    exempt = src[src.index("_CLEAR_CACHE_EXEMPT_POST = {"):]
    assert '"/api/setter/queue/client"' in exempt[:exempt.index("def do_POST")]


def test_the_page_prefers_override_then_server_label_and_only_the_header_pill_is_a_button():
    html = open(os.path.join(os.path.dirname(__file__), "setter.html")).read()
    fn = html[html.index("function clientForRow(row)"):][:200]
    assert "clientOverrideFor(row) || clientAutoForRow(row)" in fn
    auto = html[html.index("function clientAutoForRow(row)"):]
    assert auto.index("row.client_auto") < auto.index("campaignParentMap[String(sid)]")
    assert "${clientPillHtml(row, true)}" in html            # conversation header
    assert html.count("${clientPillHtml(row)}") == 1         # list row stays a span
    pill = html[html.index("function clientPillHtml(row, editable)"):][:400]
    assert 'if (CLIENT_MODE) return "";' in pill             # never in a client view
