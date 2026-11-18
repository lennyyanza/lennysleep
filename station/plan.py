"""Wake plan: latest = first_event - commute - buffer - tasks; window = [latest-15, latest]."""
import math
import os
import re
import time
from datetime import date, datetime, time as dtime, timedelta

COMMUTE = int(os.getenv("COMMUTE_MIN", 10))
BUFFER = int(os.getenv("BUFFER_MIN", 10))
TARGET_H = float(os.getenv("TARGET_SLEEP_H", 7.5))
DEFAULT_EVENT = os.getenv("DEFAULT_EVENT", "06:00")
HOME = os.getenv("HOME_LATLON")  # "lat,lon"; walking time from here replaces COMMUTE when the event has a location
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


_cache = {}  # url -> (fetched_at, cal)


def _calendar(url):
    import httpx
    from icalendar import Calendar
    at, cal = _cache.get(url, (0.0, None))
    if time.time() - at > 900 or cal is None:
        try:
            cal = Calendar.from_ical(httpx.get(url.replace("webcal://", "https://", 1), timeout=15, follow_redirects=True).content)
        except Exception as e:  # keep last good copy, fall back to default
            print("ical fetch failed:", type(e).__name__)
        _cache[url] = (time.time(), cal)
    return cal


_travel = {}  # location -> walking minutes or None; cleared by POST /refresh
_UA = {"User-Agent": "lennysleep/1.0 (personal sleep station)"}  # OpenStreetMap usage policy wants a UA


def walk_min(location, geo=""):
    """Walking minutes from HOME (OpenStreetMap search + foot routing), or None if unknown."""
    if not HOME or not (key := geo or location):
        return None
    if key not in _travel:
        import httpx
        _travel[key] = None
        try:
            hlat, hlon = map(float, HOME.split(","))
            if geo.startswith("geo:"):  # Apple Maps pick: exact coordinates
                lat, lon = map(float, geo[4:].split(",")[:2])
            else:
                q = location.splitlines()[0]
                d = 0.15  # full address: search the wider area
                if "," not in q:  # building name like "Babbio 221": drop room/floor, search ~2 km around home
                    q, d = re.sub(r"\b(room\s*)?\d+\w*(\s*floor)?\b", "", q, flags=re.I).strip(" ,-"), 0.02
                r = httpx.get("https://nominatim.openstreetmap.org/search", headers=_UA, timeout=15, params={
                    "q": q, "format": "jsonv2", "limit": 1, "bounded": 1,
                    "viewbox": f"{hlon - d},{hlat + d},{hlon + d},{hlat - d}"}).json()
                if not r:
                    return None
                lat, lon = float(r[0]["lat"]), float(r[0]["lon"])
            route = httpx.get(f"https://routing.openstreetmap.de/routed-foot/route/v1/driving/{hlon},{hlat};{lon},{lat}",
                              params={"overview": "false"}, headers=_UA, timeout=15).json()
            m = math.ceil(route["routes"][0]["duration"] / 60)
            if m <= 90:  # a bad match far away would wake you hours early; fall back to COMMUTE instead
                _travel[key] = m
        except Exception as e:
            print("walk lookup failed:", type(e).__name__)
    return _travel[key]


def _local(dt):
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def first_event_on(cal, day: date):
    """(start, event) of the earliest timed event on `day` (local), including simple RRULE repeats, or None."""
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
            if lo <= s < hi and (best is None or s < best[0]):
                best = (s, ev)
    return best


def plan_for(day: date):
    event, source = None, "default"
    cals = [c for u in os.getenv("ICAL_URL", "").split() if (c := _calendar(u)) is not None]  # space-separated
    location, commute = "", COMMUTE
    if cals:
        hits = [h for c in cals if (h := first_event_on(c, day))]
        if hits:
            event, ev = min(hits, key=lambda h: h[0])
            location = str(ev.get("LOCATION", "")).strip()
            commute = walk_min(location, str(ev.get("X-APPLE-STRUCTURED-LOCATION", ""))) or COMMUTE
        source = "calendar" if event else "default (no event)"
    if event is None:
        event = datetime.combine(day, dtime.fromisoformat(DEFAULT_EVENT))
    return make_plan(event, commute=commute) | {"source": source, "wake_date": day.isoformat(),
                                                "location": location, "commute_min": commute}
