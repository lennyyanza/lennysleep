"""lennysleep station: serial -> SQLite, wake engine loop, HTTP API + app on :8000."""
import csv
import glob
import io
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE.parent / ".env")

import plan as planmod  # noqa: E402  (env must be loaded first)
import sleep_detect  # noqa: E402
import wake_engine  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, PlainTextResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

DEMO = os.getenv("DEMO") == "1"
SPEED = float(os.getenv("DEMO_SPEED", 10)) if DEMO else 1.0
DB = os.getenv("DB", str(HERE / ("demo.db" if DEMO else "lennysleep.db")))
LOUD = float(os.getenv("LOUD_RMS", 300))
# practice run (./run.sh test N): real sensor/sunrise/audio/camera, alarm N min after start, own DB
REHEARSE_AT = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=float(os.getenv("REHEARSE_MIN", 0)))
NIGHT_COLS = """first_event leave latest window_start asleep_by in_bed asleep watch_onset watch_wake onset_gap_min
watch_asleep_min hr hrv stages trigger_at trigger_reason alarm_at woke_at up_by left_at steps_dropped
rushed feel_wake feel_30 window_open note room_temp loud_events""".split()
LOG_FIELDS = {"woke_at", "up_by", "left_at", "steps_dropped", "rushed", "feel_wake", "feel_30", "window_open", "note"}
STATUS = {"serial": "not started"}
SEED = {"wake_date": "2026-11-17", "woke_at": "2026-11-17T05:27:00", "left_at": "2026-11-17T05:50:00",
        "rushed": 5, "note": "Day 0 baseline: rushed, phone first"}

# ---- clock (demo runs SPEED x faster, starting just before the window) ----
_t0, _sim0 = time.time(), None


def now():
    if _sim0 is None:
        return datetime.now().replace(microsecond=0)
    return (_sim0 + timedelta(seconds=(time.time() - _t0) * SPEED)).replace(microsecond=0)


def iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


# ---- db ----
def q(sql, args=()):
    with closing(sqlite3.connect(DB)) as c, c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def init_db(seed=True):
    q("CREATE TABLE IF NOT EXISTS readings(ts TEXT, movement INT, temp REAL, humidity REAL, light REAL, loud REAL)")
    q("CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts)")
    q(f"CREATE TABLE IF NOT EXISTS nights(wake_date TEXT PRIMARY KEY, {', '.join(NIGHT_COLS)})")
    if seed and not q("SELECT 1 FROM nights LIMIT 1"):
        upsert(**SEED)


def upsert(wake_date, **fields):
    fields = {k: iso(v) for k, v in fields.items() if k in NIGHT_COLS}
    q("INSERT OR IGNORE INTO nights(wake_date) VALUES(?)", (str(wake_date),))
    if fields:
        q(f"UPDATE nights SET {', '.join(f'{k}=?' for k in fields)} WHERE wake_date=?", (*fields.values(), str(wake_date)))
    q("""UPDATE nights SET onset_gap_min=round((julianday(asleep)-julianday(watch_onset))*1440)
         WHERE wake_date=? AND asleep IS NOT NULL AND watch_onset IS NOT NULL""", (str(wake_date),))
    return night(wake_date)


def night(wake_date):
    rows = q("SELECT * FROM nights WHERE wake_date=?", (str(wake_date),))
    return rows[0] if rows else {"wake_date": str(wake_date)}


def add_reading(ts, movement, temp, humidity, light, loud):
    q("INSERT INTO readings VALUES(?,?,?,?,?,?)", (iso(ts), movement, temp, humidity, light, loud))


def night_readings(day, until):
    lo = datetime.combine(day - timedelta(days=1), dtime(19))
    return q("SELECT * FROM readings WHERE ts>=? AND ts<=? ORDER BY ts", (iso(lo), iso(until)))


# ---- serial ----
def _num(s):
    try:
        v = float(s)
        return None if v != v else v
    except ValueError:
        return None


def parse_line(line):
    parts = line.strip().split(",")
    if len(parts) != 5 or line.startswith("#"):
        return None
    mov, temp, hum, light, loud = map(_num, parts)
    return None if mov is None else (int(mov), temp, hum, light, loud)


def serial_loop():
    import serial
    while True:
        port = os.getenv("SERIAL_PORT") or next(iter(sorted(glob.glob("/dev/ttyACM*"))), None)
        try:
            if not port:
                raise OSError("no /dev/ttyACM*")
            with serial.Serial(port, 115200, timeout=150) as s:
                STATUS["serial"] = f"connected {port}"
                while True:
                    raw = s.readline()
                    if not raw:
                        raise TimeoutError("no data for 150 s")
                    if (r := parse_line(raw.decode(errors="ignore"))) is not None:
                        add_reading(now(), *r)
        except Exception as e:
            STATUS["serial"] = f"reconnecting ({type(e).__name__}: {e})"
            time.sleep(5)


# ---- engine ----
def get_plan(day):
    if os.getenv("REHEARSE_MIN"):  # plan so that latest == REHEARSE_AT
        lead = planmod.COMMUTE + planmod.BUFFER + sum(m for _, m, _ in planmod.STEPS)
        return planmod.make_plan(REHEARSE_AT + timedelta(minutes=lead)) | {"source": "practice run", "wake_date": str(day),
                                                                              "asleep_by": REHEARSE_AT}
    return planmod.make_plan(datetime.combine(day, dtime(6))) | {"source": "demo", "wake_date": str(day)} \
        if DEMO else planmod.plan_for(day)


def tick():
    t = now()
    day = planmod.wake_date_for(t)
    p = get_plan(day)
    rows = night_readings(day, t)
    rd = [(datetime.fromisoformat(r["ts"]), r["movement"], r["light"]) for r in rows]
    in_bed, asleep = sleep_detect.detect(rd)
    f = {k: p[k] for k in ("first_event", "leave", "latest", "window_start", "asleep_by")}
    if in_bed:
        if not DEMO and not night(day).get("in_bed"):  # lights out: backlight off so it doesn't light the room
            screen(0)
        f["in_bed"] = in_bed
        after = [r for r in rows if r["ts"] >= iso(in_bed)]
        temps = [r["temp"] for r in after if r["temp"] is not None]
        f["room_temp"] = round(sum(temps) / len(temps), 1) if temps else None
        f["loud_events"] = sum(1 for r in after if (r["loud"] or 0) > LOUD)
    if asleep:
        f["asleep"] = asleep
    if not night(day).get("trigger_at") and (d := wake_engine.decide(t, p, rd, asleep)):
        f["trigger_at"], f["alarm_at"], f["trigger_reason"] = d
        if not DEMO:
            wake_engine.alarm_audio()
            wake_engine.sunrise((d[1] - d[0]).total_seconds())
    n = night(day)
    if (n.get("alarm_at") and not n.get("woke_at") and t >= datetime.fromisoformat(n["alarm_at"])
            and wake_engine.up_from_sensor(rd, datetime.fromisoformat(n["alarm_at"]))):
        f["woke_at"], f["up_by"] = iso(t), "sensor"  # the page sees woke_at and stops the alarm
        if not DEMO:
            woke_up()
    return upsert(day, **f)


def woke_up():
    wake_engine.music_audio()
    threading.Thread(target=wake_engine.music_start, daemon=True).start()


def audio_loop():
    """Every second: music follows the buds the moment they connect, stops when they disconnect or the event starts."""
    while True:
        try:
            day = planmod.wake_date_for(now())
            n = night(day)
            if n.get("first_event"):
                wake_engine.music_tick(day, n.get("woke_at"), datetime.fromisoformat(n["first_event"]), now())
        except Exception as e:
            print("audio error:", repr(e))
        time.sleep(1)


def engine_loop():
    while True:
        try:
            tick()
        except Exception as e:
            print("tick error:", repr(e))
        time.sleep(1 if DEMO else 15)


# ---- demo: labeled sample night, then live sample minutes ----
def start_demo():
    global _sim0, _t0
    day = date.today() + timedelta(days=1)
    p = get_plan(day)
    for t in ("readings", "nights"):
        q(f"DELETE FROM {t}")
    start = p["first_event"] - timedelta(hours=9)  # 21:00
    _sim0, _t0 = p["latest"] - timedelta(minutes=7), time.time()
    t = start
    while t < _sim0:  # lights out 21:15, settles by 21:25
        lit, restless = t < start + timedelta(minutes=15), t < start + timedelta(minutes=25)
        add_reading(t, 12 if restless else (3 if t.minute % 47 == 0 else 0), 19.5, None, 120 if lit else 0,
                    400 if t.hour == 2 and t.minute == 10 else 25)
        t += timedelta(minutes=1)
    upsert(day, note="DEMO sample data")

    def feed():
        while True:
            time.sleep(60 / SPEED)
            up = night(day).get("woke_at")
            add_reading(now(), 15 if up else 0, 19.5, None, 200 if up else 0, 30)
    threading.Thread(target=feed, daemon=True).start()


# ---- watch sleep ----
def parse_dt(s):
    s = re.sub(r"\s+", " ", s.replace(" ", " ")).strip()
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%b %d, %Y at %I:%M %p", "%b %d, %Y at %H:%M", "%d %b %Y at %H:%M",
                    "%m/%d/%Y, %I:%M %p", "%m/%d/%y, %I:%M %p"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
        else:
            raise ValueError(f"unknown date format: {s!r}")
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def is_asleep(stage):
    s = stage.lower().replace(" ", "")
    return "awake" not in s and "inbed" not in s and any(k in s for k in ("core", "deep", "rem", "asleep"))


def merge_watch(segs, hr=None, hrv=None):
    """segs: [(stage, start, end)]. Groups into nights, merges each. Returns merged rows."""
    nights = {}
    for st, a, b in segs:
        day = planmod.wake_date_for(b)
        if a >= datetime.combine(day - timedelta(days=1), dtime(18)):
            nights.setdefault(day, []).append((st, a, b))
    out = []
    for day, ss in sorted(nights.items()):
        sl = [s for s in ss if is_asleep(s[0])]
        if not sl:
            continue
        f = {"watch_onset": min(s[1] for s in sl), "watch_wake": max(s[2] for s in sl),
             "watch_asleep_min": round(sum((b - a).total_seconds() for _, a, b in sl) / 60),
             "stages": json.dumps([[st, iso(a), iso(b)] for st, a, b in sorted(ss, key=lambda s: s[1])])}
        if hr is not None:
            f["hr"] = hr
        if hrv is not None:
            f["hrv"] = hrv
        out.append(upsert(day, **f))
    return out


def parse_sleep_text(text):
    hr = hrv = None
    segs = []
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith(("hrv", "hr")):
            v = re.findall(r"[\d.]+", low)
            if v:
                hr, hrv = (hr, float(v[0])) if low.startswith("hrv") else (float(v[0]), hrv)
        elif line.count(",") >= 2:
            st, a, b = _split3(line)
            segs.append((st, parse_dt(a), parse_dt(b)))
    return segs, hr, hrv


def _split3(line):
    """'Stage,start,end' where dates may contain commas ('Nov 17, 2026 at 1:00 AM')."""
    st, *parts = [p.strip() for p in line.split(",")]
    for i in range(1, len(parts)):
        try:
            a, b = ", ".join(parts[:i]), ", ".join(parts[i:])
            parse_dt(a), parse_dt(b)
            return st, a, b
        except ValueError:
            pass
    raise ValueError(f"bad sleep line: {line!r}")


# ---- http ----
@asynccontextmanager
async def lifespan(app):
    init_db(seed=not DEMO)
    if DEMO:
        start_demo()
        STATUS["serial"] = "demo (sample data)"
    elif os.getenv("NO_SERIAL") != "1":
        threading.Thread(target=serial_loop, daemon=True).start()
    if os.getenv("NO_ENGINE") != "1":
        threading.Thread(target=engine_loop, daemon=True).start()
        if not DEMO:
            threading.Thread(target=audio_loop, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/plan")
def get_plan_api(day: str | None = None):
    d = date.fromisoformat(day) if day else planmod.wake_date_for(now())
    return {k: iso(v) for k, v in get_plan(d).items()}


@app.post("/audio/test")
def audio_test():
    if not DEMO:
        wake_engine.alarm_audio()
    return {"ok": True}


@app.post("/refresh")
def refresh_calendar():
    """Re-read the calendar(s) and walking times now instead of waiting up to 15 min."""
    planmod._cache.clear()
    planmod._travel.clear()
    return get_plan_api()


@app.get("/today")
def today():
    t = now()
    day = planmod.wake_date_for(t)
    last = q("SELECT * FROM readings ORDER BY ts DESC LIMIT 1")
    if last:
        last[0]["age_s"] = (t - datetime.fromisoformat(last[0]["ts"])).total_seconds()
    return {"now": iso(t), "speed": SPEED, "demo": DEMO, "wake_date": str(day), "plan": get_plan_api(str(day)),
            "night": night(day), "last_reading": last[0] if last else None, "serial": STATUS["serial"],
            "light_dark": sleep_detect.LIGHT_DARK}


@app.get("/nights")
def nights(limit: int = 30):
    return q("SELECT * FROM nights ORDER BY wake_date DESC LIMIT ?", (limit,))


@app.get("/export.csv", response_class=PlainTextResponse)
def export(table: str = "nights"):
    if table not in ("nights", "readings"):
        raise HTTPException(400, "table must be nights or readings")
    rows = q(f"SELECT * FROM {table} ORDER BY 1")
    buf = io.StringIO()
    cols = [c["name"] for c in q(f"PRAGMA table_info({table})")]
    w = csv.DictWriter(buf, cols)
    w.writeheader()
    w.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=lennysleep-{table}.csv"})


@app.post("/sleep")
async def post_sleep(request: Request):
    body = (await request.body()).decode(errors="ignore")
    try:
        segs, hr, hrv = parse_sleep_text(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    merged = merge_watch(segs, hr, hrv)
    if not merged:
        raise HTTPException(400, "no asleep segments found")
    return {"merged": merged}


def screen(pct):
    subprocess.run(["brightnessctl", "-q", "set", f"{pct}%"], check=False)


@app.post("/screen/{pct}")
def post_screen(pct: int):
    if not 0 <= pct <= 100:
        raise HTTPException(400, "pct must be 0-100")
    if not DEMO:
        screen(pct)
    return {"brightness": pct}


@app.post("/log")
async def post_log(request: Request):
    data = await request.json()
    day = data.pop("wake_date", None) or str(planmod.wake_date_for(now()))
    bad = set(data) - LOG_FIELDS
    if bad:
        raise HTTPException(400, f"unknown fields: {sorted(bad)}")
    if "woke_at" in data and not DEMO:
        woke_up()
    return upsert(day, **{k: iso(now()) if v == "now" else v for k, v in data.items()})
