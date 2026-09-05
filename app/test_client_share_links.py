"""Pure-python tests for the client share scope map and the client-facing Slack
link (2026-09-05, Bjion: "whichever chat it is for, that is the client - it
should only show their messages"). NO network: Supabase is an in-memory fake.
Run: python3 test_client_share_links.py  (exit 1 on any failure)."""
import sys
from urllib.parse import unquote

import setter

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS: " if cond else "FAIL: ") + name + (f"  {extra}" if (extra and not cond) else ""))


class FakeSB:
    def __init__(self, drafts, registry):
        self.drafts, self.registry, self.calls = drafts, registry, []

    def __call__(self, method, path, body=None, prefer=""):
        self.calls.append((method, path))
        table = path.split("?", 1)[0]
        if table == "campaign_drafts":
            return [dict(d) for d in self.drafts]
        if table == "campaigns":
            return [dict(r) for r in self.registry]
        return []


DRAFTS = [
    {"id": "camp-sl-3879940", "client_id": "navreo", "name": "REViVE | Beauty & Personal Care | Cold - Aug26"},
    {"id": "camp-sl-3813824", "client_id": "touchpoint", "name": "TouchPoint C3 - Shopping"},
    {"id": "camp-sl-3602157", "client_id": "navreo", "name": "Navreo · Companies hiring sales reps"},
    {"id": "camp-sl-3999999", "client_id": "navreo", "name": "Old | superseded", "superseded_by": "x"},
    {"id": "cdraft-abc", "client_id": "revive", "name": "REViVE draft never launched"},
]
REGISTRY = [
    {"workspace": "krg", "smartlead_campaign_id": 3421811, "client_id": None, "name": "KRG Advisors - GLP-1"},
    {"workspace": "grout", "smartlead_campaign_id": 3729147, "client_id": "grout", "name": "Grout - SaaS CEOs"},
    {"workspace": "navreo", "smartlead_campaign_id": 3872154, "client_id": "navreo", "name": "Greenshift - C8 - Engineering Leaders"},
    {"workspace": "navreo", "smartlead_campaign_id": 3700001, "client_id": "amplifyy", "name": "Amplifyy · Hiring SDRs"},
    {"workspace": "navreo", "smartlead_campaign_id": 3700002, "client_id": "navreo", "name": "Navreo | Agencies | v3"},
    {"workspace": "navreo", "smartlead_campaign_id": "", "client_id": "navreo", "name": "no id"},
    {"workspace": "", "smartlead_campaign_id": 3700003, "client_id": "krg", "name": "no workspace"},
]


def wire(drafts=DRAFTS, registry=REGISTRY):
    sb = FakeSB(drafts, registry)
    setter._SB = sb
    setter._KEYS = {"SUPABASE_SERVICE_ROLE_KEY": "test-secret"}
    setter._CLIENT_CAMPAIGNS_CACHE.update({"at": 0.0, "map": None})
    setter._PARENT_CACHE.update({"at": 0.0, "map": None})
    return sb


def share_client(url):
    """(client_id, test_flag) verified from a share URL, or None."""
    if "?share=" not in url:
        return None
    tok = unquote(url.split("?share=", 1)[1].split("#", 1)[0])
    return setter.verify_client_share(tok)


def test_map_two_sources():
    wire()
    m = setter._client_campaign_map(force=True)
    check("1a REViVE draft (client_id navreo) attributes by NAME to revive", "3879940" in m.get("revive", ()))
    check("1b explicit touchpoint draft keeps its client", "3813824" in m.get("touchpoint", ()))
    check("1c Navreo-own draft belongs to no client", not any("3602157" in ids for ids in m.values()))
    check("1d superseded draft ignored", not any("3999999" in ids for ids in m.values()))
    check("1e non camp-sl draft ignored", not any("abc" in i for ids in m.values() for i in ids))
    check("1f KRG registry campaign (no draft) -> krg by WORKSPACE", "3421811" in m.get("krg", ()))
    check("1g grout registry campaign -> grout", "3729147" in m.get("grout", ()))
    check("1h navreo-hosted Greenshift registry row -> greenshift by NAME", "3872154" in m.get("greenshift", ()))
    check("1i navreo registry row with explicit amplifyy client_id -> amplifyy", "3700001" in m.get("amplifyy", ()))
    check("1j Navreo-own registry row -> nobody", not any("3700002" in ids for ids in m.values()))
    check("1k registry rows without id / workspace skipped", not any("3700003" in ids for ids in m.values()))
    check("1l map values are frozensets", all(isinstance(v, frozenset) for v in m.values()))


def test_client_id_of():
    f = setter._client_id_of
    check("2a explicit non-navreo client wins over name", f("touchpoint", "REViVE | x") == "touchpoint")
    check("2b navreo + REViVE name -> revive", f("navreo", "REViVE | Pet | Cold") == "revive")
    check("2c empty + altius name -> 'altius reach' (the drafts' id)", f("", "Altius Reach - C1") == "altius reach")
    check("2d navreo + Navreo name -> ''", f("navreo", "Navreo | Agencies") == "")
    check("2e lower-cases explicit ids", f("KRG", "") == "krg")


def test_inverse_lookup():
    wire()
    check("3a campaign -> client (revive)", setter._client_id_for_campaign(3879940) == "revive")
    check("3b campaign -> client (krg, registry-only)", setter._client_id_for_campaign("3421811") == "krg")
    check("3c unknown campaign -> ''", setter._client_id_for_campaign(1) == "")
    check("3d None -> ''", setter._client_id_for_campaign(None) == "")


def test_alert_chat_link():
    wire()
    row = {"email": "Nik@Example.com", "smartlead_message_id": "m-1", "smartlead_campaign_id": 3879940}
    shared = setter.POSITIVE_SHARED_CHANNELS["revive"]
    url = setter._alert_chat_link(row, shared)
    check("4a client-facing channel -> share link", "?share=" in url, url)
    check("4b share= sits BEFORE the #/r/ hash", url.index("?share=") < url.index("#/r/"), url)
    check("4c token verifies to revive, not test-flagged", share_client(url) == ("revive", False), url)
    check("4d deep link keeps email + message id", url.endswith("#/r/nik%40example.com/m-1"), url)
    owner = setter._alert_chat_link(row, setter.CLIENT_INTERNAL_CHANNEL)
    check("4e internal #client-interested-replies -> owner permalink", owner == setter._chat_permalink("nik@example.com", "m-1"), owner)
    check("4f no channel (hook default) -> owner permalink", setter._alert_chat_link(row, None) == owner)
    unknown = setter._alert_chat_link(dict(row, smartlead_campaign_id=1), shared)
    check("4g client-facing channel but no client resolves -> owner permalink (status quo)", unknown == owner, unknown)
    krg_row = {"email": "j@krg-lead.com", "smartlead_message_id": "", "smartlead_campaign_id": 3421811}
    kurl = setter._alert_chat_link(krg_row, setter.CLIENT_ALERT_CHANNELS["krg"])
    check("4h KRG own channel -> krg share link", share_client(kurl) == ("krg", False), kurl)
    check("4i every client channel set is covered", setter.CLIENT_ALERT_CHANNELS["grout"] in setter.CLIENT_FACING_CHANNELS
          and setter.FLIP_NAME_CHANNELS["revive"] in setter.CLIENT_FACING_CHANNELS
          and setter.CLIENT_INTERNAL_CHANNEL not in setter.CLIENT_FACING_CHANNELS)


def test_composers():
    wire()
    row = {"email": "nik@example.com", "smartlead_message_id": "m-9", "smartlead_campaign_id": 3879940,
           "category": "Interested", "replied_at": "2026-09-05T10:00:00+00:00", "workspace": "navreo"}
    shared = setter.POSITIVE_SHARED_CHANNELS["revive"]
    t = setter._ep_positive_shared_text(row, "REViVE | Pet", "", channel=shared)
    link = t.split("<", 1)[1].split("|", 1)[0]
    check("5a shared positive text carries the revive share link", share_client(link) == ("revive", False), t)
    check("5b ...and no owner permalink", "setter.html#/r/" not in t, t)
    t2 = setter._ep_positive_shared_text(row, "REViVE | Pet", "")
    check("5c no channel -> owner permalink (backwards compatible)", "setter.html#/r/" in t2 and "?share=" not in t2, t2)
    krg = {"email": "j@krg-lead.com", "smartlead_message_id": "", "smartlead_campaign_id": 3421811,
           "category": "Meeting Request", "replied_at": "2026-09-05T10:00:00+00:00", "workspace": "krg"}
    t3 = setter._cp_compose(krg, "KRG - GLP-1", "", channel=setter.CLIENT_ALERT_CHANNELS["krg"])
    link3 = t3.split("<", 1)[1].split("|", 1)[0]
    check("5d client positive into #krg-advisors-navreo -> krg share link", share_client(link3) == ("krg", False), t3)
    t4 = setter._cp_compose(krg, "KRG - GLP-1", "", channel=setter.CLIENT_INTERNAL_CHANNEL)
    check("5e client positive into internal lane -> owner permalink", "setter.html#/r/" in t4 and "?share=" not in t4, t4)
    prior = {"category": "Interested", "replied_at": "2026-09-01T10:00:00+00:00", "smartlead_campaign_id": 3879940}
    t5 = setter._ep_compose(dict(row, category="Not Interested"), prior, {"3879940": "REViVE | Pet"},
                            channel=setter.FLIP_NAME_CHANNELS["revive"])
    link5 = t5.split("<", 1)[1].split("|", 1)[0]
    check("5f REViVE churn flip into the shared channel -> revive share link", share_client(link5) == ("revive", False), t5)
    t6 = setter._ep_compose(dict(row, category="Not Interested"), prior, {"3879940": "REViVE | Pet"}, channel=None)
    check("5g flip into the hook default -> owner permalink", "setter.html#/r/" in t6 and "?share=" not in t6, t6)


def test_registry_failure_keeps_drafts():
    class Flaky(FakeSB):
        def __call__(self, method, path, body=None, prefer=""):
            if path.startswith("campaigns?"):
                raise OSError("registry down")
            return super().__call__(method, path, body, prefer)
    sb = Flaky(DRAFTS, REGISTRY)
    setter._SB = sb
    setter._KEYS = {"SUPABASE_SERVICE_ROLE_KEY": "test-secret"}
    setter._CLIENT_CAMPAIGNS_CACHE.update({"at": 0.0, "map": None})
    m = setter._client_campaign_map(force=True)
    check("6a registry read failure keeps the drafts-based scope", "3879940" in m.get("revive", ()) and "krg" not in m)


if __name__ == "__main__":
    test_map_two_sources()
    test_client_id_of()
    test_inverse_lookup()
    test_alert_chat_link()
    test_composers()
    test_registry_failure_keeps_drafts()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} pass")
    sys.exit(1 if failed else 0)
