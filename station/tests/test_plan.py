from datetime import date, datetime

from icalendar import Calendar

import plan


def t(s):
    return datetime.fromisoformat(s)


def test_defaults_6am():
    p = plan.make_plan(t("2026-11-18 06:00"))
    assert p["leave"] == t("2026-11-18 05:40")
    assert p["latest"] == t("2026-11-18 05:12")
    assert (p["window_start"], p["latest"]) == (t("2026-11-18 04:57"), t("2026-11-18 05:12"))
    assert p["asleep_by"] == t("2026-11-17 21:42")
    assert p["steps"][0]["name"] == "Phone stays on charger" and p["steps"][-1]["name"] == "Grab phone, go"


def test_no_calendar_uses_default():
    assert plan.plan_for(date(2026, 11, 18))["latest"] == t("2026-11-18 05:12")


def test_wake_date_rolls_at_noon():
    assert plan.wake_date_for(t("2026-11-17 23:00")) == date(2026, 11, 18)
    assert plan.wake_date_for(t("2026-11-18 05:00")) == date(2026, 11, 18)


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:a
DTSTART:20261118T090000
SUMMARY:late
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART:20261102T073000
RRULE:FREQ=WEEKLY;BYDAY=WE
SUMMARY:weekly
END:VEVENT
BEGIN:VEVENT
UID:c
DTSTART;VALUE=DATE:20261118
SUMMARY:all day
END:VEVENT
END:VCALENDAR
"""


def test_first_event_with_rrule():
    cal = Calendar.from_ical(ICS)
    assert plan.first_event_on(cal, date(2026, 11, 18))[0] == t("2026-11-18 07:30")  # Wednesday repeat beats 9:00
    assert plan.first_event_on(cal, date(2026, 11, 19)) is None


def test_earliest_event_across_calendars(monkeypatch):
    ics = lambda hm: Calendar.from_ical(f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:{hm}\nDTSTART:20261118T{hm}00\nEND:VEVENT\nEND:VCALENDAR".encode())
    cals = {"a": ics("0900"), "b": ics("0730"), "c": None}  # c = failed fetch
    monkeypatch.setenv("ICAL_URL", "a b c")
    monkeypatch.setattr(plan, "_calendar", cals.get)
    assert plan.plan_for(date(2026, 11, 18))["first_event"] == t("2026-11-18 07:30")


def test_walk_time_sets_commute(monkeypatch):
    ev = "BEGIN:VEVENT\nUID:{u}\nDTSTART:20261118T{hm}00\nLOCATION:{loc}\nEND:VEVENT\n"
    cal = Calendar.from_ical(("BEGIN:VCALENDAR\n" + ev.format(u=1, hm="0900", loc="Babbio 221") + "END:VCALENDAR").encode())
    calls = []

    class R:
        def __init__(self, j): self.json = lambda: j

    def get(url, params=None, **kw):
        calls.append(params.get("q"))
        return R([{"lat": "40.746", "lon": "-74.024"}] if "nominatim" in url else {"routes": [{"duration": 720.5}]})
    monkeypatch.setattr(plan, "HOME", "40.7495,-74.0321")
    monkeypatch.setattr(plan, "_travel", {})
    monkeypatch.setenv("ICAL_URL", "a")
    monkeypatch.setattr(plan, "_calendar", lambda u: cal)
    monkeypatch.setattr("httpx.get", get)
    p = plan.plan_for(date(2026, 11, 18))
    assert (p["commute_min"], p["location"], calls[0]) == (13, "Babbio 221", "Babbio")  # room number dropped
    assert p["leave"] == t("2026-11-18 08:37")  # 9:00 - 13 walk - 10 buffer
    plan.plan_for(date(2026, 11, 18))
    assert len(calls) == 2  # cached: one search + one route
    monkeypatch.setattr(plan, "HOME", None)
    assert plan.plan_for(date(2026, 11, 18))["commute_min"] == plan.COMMUTE
