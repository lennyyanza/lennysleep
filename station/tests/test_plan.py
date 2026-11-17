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
    assert plan.first_event_on(cal, date(2026, 11, 18)) == t("2026-11-18 07:30")  # Wednesday repeat beats 9:00
    assert plan.first_event_on(cal, date(2026, 11, 19)) is None
