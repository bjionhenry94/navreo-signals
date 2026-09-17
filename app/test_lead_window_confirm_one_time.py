"""Owner HARD RULE 2026-09-17: a lead who offers their own time or window gets
ONE confirmed time inside it - never two fresh times, never a calendar fallback."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import setter as s  # noqa: E402

NOW = dt.datetime(2026, 9, 17, 14, tzinfo=dt.timezone.utc)
MIKE = "You can call me between 10.30 & 3.30 I will be available.\n\n07976207810\n\nMike"
AGENT = {"instructions": "When no slots are supplied, propose two specific times yourself."}


def test_clock_window_parsing():
    assert s._lead_clock_window(MIKE) == (630, 930)
    assert s._lead_clock_window("anytime from 2 to 5pm") == (840, 1020)
    assert s._lead_clock_window("call me between 9 and 12") == (540, 720)
    assert s._lead_clock_window("we sell between 10 and 20 products") is None
    assert s._lead_clock_window("sure, send times") is None


def test_one_slot_inside_window_for_self_time_agent():
    slots, status = s.narrow_slots_to_lead_window([], "not_configured", MIKE, "Europe/London", NOW, {}, AGENT, None)
    assert status == "ok" and len(slots) == 1 and slots[0]["lead_fit"] is True
    assert "11:00 AM" in slots[0]["label"]


def test_no_window_leaves_slots_alone():
    given = [{"iso": "x", "label": "a", "link": ""}, {"iso": "y", "label": "b", "link": ""}]
    assert s.narrow_slots_to_lead_window(given, "ok", "Sure, send me times", "Europe/London", NOW, {}, AGENT, None) == (given, "ok")


def test_agent_without_authorisation_never_gets_invented_time():
    slots, status = s.narrow_slots_to_lead_window([], "not_configured", MIKE, "Europe/London", NOW, {}, {"instructions": "x"}, None)
    assert slots == [] and status == "not_configured"


def test_backstop_confirms_and_stops():
    fit = {"label": "Friday, 18th September at 11:00 AM BST", "link": "", "lead_fit": True}
    html = ("<div>Hi Mike,</div><br><div>I can call you at 07976207810, and I'm free within your window.</div><br>"
            "<div>Would you be open to a call on Monday, 21st September at 9:00 AM BST or Tuesday, 22nd September "
            "at 9:00 AM BST where I could walk through the first moves?</div><br>"
            "<div>If those times aren't suitable, feel free to <a href='x'>see my availability here</a> and book in directly.</div><br>"
            "<div>Nik</div>")
    out = s.confirm_lead_time_only(html, fit, MIKE)
    assert "Would you be open" not in out and "availability" not in out and "21st" not in out
    assert "07976207810" in out and fit["label"] in out
    assert out.startswith("<div>Hi Mike,</div>") and out.endswith("<div>Nik</div>")


def test_outlook_quoted_header_stripped_and_thread_not_doubled():
    body = "You can call me.\n07976207810\nMike\n \nFrom: Nik Hall <n@x.co>\nSent: 16 September 2026 23:57\nTo: a\n\nWould a quick call"
    assert s.clean_body(body) == "You can call me.\n07976207810\nMike"


def test_backstop_drops_second_time_fallback_and_unasked_resource():
    fit = {"label": "Wednesday, 23rd September at 9:00 AM BST", "link": "", "lead_fit": True}
    html = ("<div>Hi Ben,</div><br><div>That works for me, let's do Wednesday, 23rd September at 9:00 AM BST.</div><br>"
            "<div>Yes, I can make Friday 2-4 pm; that slot at 2:00 PM works for me.</div><br>"
            "<div>You can lock it in here: <a href='x'>see my availability</a>.</div><br>"
            "<div>Here's the short Loom I recorded: [LOOM LINK]</div><br><div>Nik</div>")
    out = s.confirm_lead_time_only(html, fit, "Wed morning 9-11am or Fri 2-4pm", wants_resource=False)
    assert "Friday" not in out and "lock it in" not in out and "Loom" not in out
    assert fit["label"] in out
    assert "Loom" in s.confirm_lead_time_only(html, fit, "x", wants_resource=True)
