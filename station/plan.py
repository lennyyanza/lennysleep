"""Wake plan: latest = first_event - commute - buffer - tasks; window = [latest-15, latest]."""
import os
import time
from datetime import date, datetime, time as dtime, timedelta

COMMUTE = int(os.getenv("COMMUTE_MIN", 10))
BUFFER = int(os.getenv("BUFFER_MIN", 10))
TARGET_H = float(os.getenv("TARGET_SLEEP_H", 7.5))
DEFAULT_EVENT = os.getenv("DEFAULT_EVENT", "06:00")
# (name, minutes, optional). First and last are the phone bookends.
STEPS = [
    ("Phone stays on charger", 0, False),
    ("Lights + water", 3, False),
    ("Shower", 10, True),
    ("Dress", 5, False),
    ("Breakfast", 7, True),
    ("Pack", 3, False),
    ("Grab phone, go", 0, False),
]


def make_plan(first_event: datetime, commute=COMMUTE, buffer=BUFFER, target_h=TARGET_H, steps=STEPS):
    tasks = sum(m for _, m, _ in steps)
    leave = first_event - timedelta(minutes=commute + buffer)
    latest = leave - timedelta(minutes=tasks)
    return {
        "first_event": first_event, "leave": leave, "latest": latest,
        "window_start": latest - timedelta(minutes=15), "asleep_by": latest - timedelta(hours=target_h),
        "steps": [{"name": n, "min": m, "optional": o} for n, m, o in steps],
    }


def wake_date_for(now: datetime) -> date:
    """Mornings belong to today until noon, after that we plan for tomorrow."""
    return now.date() if now.hour < 12 else now.date() + timedelta(days=1)


_cache = {"at": 0.0, "cal": None}


def _calendar(url):
    import httpx
    from icalendar import Calendar
    if time.time() - _cache["at"] > 900 or _cache["cal"] is None:
        try:
            _cache["cal"] = Calendar.from_ical(httpx.get(url, timeout=15, follow_redirects=True).content)
        except Exception as e:  # keep last good copy, fall back to default
            print("ical fetch failed:", type(e).__name__)
        _cache["at"] = time.time()
    return _cache["cal"]


def _local(dt):
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def first_event_on(cal, day: date):
    """Earliest timed event on `day` (local), including simple RRULE repeats."""
    from dateutil.rrule import rrulestr
    lo = datetime.combine(day, dtime())
    hi = lo + timedelta(days=1)
    best = None
    for ev in cal.walk("VEVENT"):
        start = ev.decoded("DTSTART")
        if not isinstance(start, datetime) or str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        starts = [start]
        if ev.get("RRULE"):
            rule = rrulestr(ev["RRULE"].to_ical().decode(), dtstart=start)
            a, b = (lo, hi) if start.tzinfo is None else (lo.astimezone(), hi.astimezone())
            starts = rule.between(a, b, inc=True)
            ex = ev.get("EXDATE", [])
            exd = {_local(d.dt) for e in (ex if isinstance(ex, list) else [ex]) for d in e.dts}
            starts = [s for s in starts if _local(s) not in exd]
        for s in map(_local, starts):
            if lo <= s < hi and (best is None or s < best):
                best = s
    return best


def plan_for(day: date):
    event, source = None, "default"
    url = os.getenv("ICAL_URL")
    if url and (cal := _calendar(url)) is not None:
        event = first_event_on(cal, day)
        source = "calendar" if event else "default (no event)"
    if event is None:
        event = datetime.combine(day, dtime.fromisoformat(DEFAULT_EVENT))
    return make_plan(event) | {"source": source, "wake_date": day.isoformat()}
