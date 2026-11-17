# iPhone Shortcut: send Watch sleep to the station

Runs each morning about 15 min after you wake (gives the Watch time to sync), over home Wi-Fi.
Nothing leaves your network: the phone talks straight to the laptop.

## Build the shortcut (Shortcuts app → + → name it "lennysleep")

1. **Find Health Samples** where *Type* is **Sleep Analysis**, *Start Date* is **in the last 1 day**.
   Sort by **Start Date**, **Oldest First**.
2. **Repeat with Each** item in Health Samples:
   - **Format Date** *Start Date* → **ISO 8601**, include time.
   - **Format Date** *End Date* → **ISO 8601**, include time.
   - **Text**: `Value,Formatted Start,Formatted End` (tap each variable: `Repeat Item › Value`, then the two formatted dates)
3. **Combine Text** (Repeat Results) with **New Lines**.
4. **Find Health Samples** where *Type* is **Resting Heart Rate**, sort **Start Date Latest First**, limit **1**.
5. **Find Health Samples** where *Type* is **Heart Rate Variability**, sort **Start Date Latest First**, limit **1**.
6. **Text**:
   ```
   hr <Resting Heart Rate value>
   hrv <Heart Rate Variability value>
   <Combined Text>
   ```
7. **Get Contents of URL** `http://lenny.local:8000/sleep`.
   Method **POST**, Request Body **File**, File = the Text from step 6.
   (`lenny` is this laptop's hostname. If `.local` doesn't resolve, use the laptop's Wi-Fi IP.)

The body ends up looking like this:
```
hr 54
hrv 41
In Bed,2026-11-17T21:40:00-05:00,2026-11-18T05:15:00-05:00
Core,2026-11-17T21:52:00-05:00,2026-11-17T23:10:00-05:00
Deep,...
```
Stage names Core/Deep/REM/Asleep count as asleep. Awake and In Bed are stored but don't count.
Non-ISO dates such as `Nov 17, 2026 at 9:52 PM` also parse.

## Make it automatic

Shortcuts → **Automation** → **+** → **Time of Day**, about 15 min after your usual wake (e.g. **5:30 AM**), **Daily** →
**Run Immediately** (turn off *Notify When Run*) → pick **lennysleep**.

## Test

Run it by hand once. The station responds with the merged row; Insights shows *Nano vs Watch* for that date.
From the laptop you can fake one:
```
curl -X POST --data-binary $'hr 55\nCore,2026-11-18T22:00,2026-11-19T05:00' localhost:8000/sleep
```
If the phone can't reach the laptop and `ufw` is on: `sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp`.

## Backfill history

Health app → profile → **Export All Health Data** → AirDrop the zip to the laptop, unzip, then:
```
cd station && ../.venv/bin/python import_health.py ~/Downloads/apple_health_export/export.xml
```
