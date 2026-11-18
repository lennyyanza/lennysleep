# lennysleep

A bedside station: an Arduino logs your room all night, the laptop works out when you fell asleep and wakes
you with a screen sunrise inside a window that still gets you out the door on time. Your phone stays on the charger.

## How it works

1. `plan.py` reads tomorrow's first calendar event and works backwards: event − commute − buffer − routine = **latest** wake, with a 15-min window before it and an **asleep-by** time 7.5 h earlier.
2. The Nano 33 BLE Sense prints movement, temperature, light and loudness (RMS only, never audio) every minute over USB. `collector.py` stores them in SQLite.
3. `sleep_detect.py`: **in bed** = lights below threshold for 5 min. **Asleep** = first 15 calm minutes after that (movement ≤ the night's 25th percentile).
4. `wake_engine.py`: in the window, the first restless minute (> night's 75th percentile) starts a 5-min sunrise and then the alarm. Otherwise it starts at latest−5. If you fell asleep after asleep-by, only the last 5 min. The alarm never rings after latest.
5. After the alarm the camera turns on (on-device pose detection, no frames kept) until you stand for 3 s or tap **I'm up**. Then the routine runs step by step against your leave time. The Watch's sleep arrives later via the iPhone Shortcut and is merged into the same row.

## Setup (once)

```
git clone … ~/lennysleep && cd ~/lennysleep
echo 'ICAL_URL=https://calendar.google.com/calendar/ical/…/basic.ics' > .env   # secret iCal address; optional
arduino-cli compile -b arduino:mbed_nano:nano33ble sensor && arduino-cli upload -b arduino:mbed_nano:nano33ble -p /dev/ttyACM0 sensor
./run.sh demo    # 2-minute demo morning on sample data (separate demo.db); Alt+F4 to exit
```
`run.sh` creates `.venv` and downloads MediaPipe (about 25 MB) the first time. After that everything runs offline.
Settings go in `.env` (all optional): `COMMUTE_MIN=10 BUFFER_MIN=10 TARGET_SLEEP_H=7.5 DEFAULT_EVENT=06:00 LIGHT_DARK=5 LOUD_RMS=300 SERIAL_PORT=/dev/ttyACM0 SPOTIFY_URL=https://open.spotify.com/playlist/… MUSIC_VOL=0.25`. Calendar: `ICAL_URL` takes several links separated by spaces; `HOME_LATLON=lat,lon` turns the commute into walking time.
Routine steps live in `STEPS` in `station/plan.py` (optional steps get dropped when you're behind).
iPhone side: see [SHORTCUT.md](SHORTCUT.md).

## Tonight checklist

- [ ] Nano on the mattress by your pillow, chip side up and uncovered (it needs to see the room light), USB to the laptop.
- [ ] Laptop plugged in, lid open, volume up (not muted), camera facing where you'll stand (knees in view).
- [ ] `./run.sh` → Tonight screen shows the plan and a green **Live** sensor dot (first reading within about 60 s).
- [ ] Tap **Test alarm sound**. You should hear beeps and a voice.
- [ ] Phone on its charger, away from the bed. First night only: keep a backup alarm set for the *latest* time until you trust this.
- [ ] Tap **Going to bed** (or just turn the lights off; the screen goes black and dims on its own).
- [ ] Morning: stand up or tap **I'm up**, follow the steps, then do the check-in tonight from the Tonight screen.
- [ ] (Shortcut) if `ufw` is enabled: `sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp`.

## Data

`station/lennysleep.db` (SQLite) has `readings` (one per minute) and `nights` (one merged row per wake date).
Export: <http://localhost:8000/export.csv> (or `?table=readings`). API: `GET /plan /today /nights`, `POST /sleep /log`.
Tests: `cd station && ../.venv/bin/pytest -q`.

These are suggestions, not medical advice.

## Hardware notes

This board is a Rev1 Sense **without the HTS221**, so humidity is blank. Temperature comes from the LPS22HB, which
reads a few °C warm because the board heats itself. Use the trends rather than the absolute value.

## Later

- External humidity/temperature sensor (or a temp offset calibrated against a thermometer).
- Auto-tune `LIGHT_DARK` and movement threshold from the first nights.
- Per-weekday routines, and holidays with no event → no alarm.
- Filter Health import to Watch-only sources; import HR/HRV history too.
- BLE instead of USB so the Nano can sit anywhere.
- Weekly insight: best predictors of a calm (rushed ≤ 2) morning.
