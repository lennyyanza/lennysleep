"""Decide when to start the 5-min sunrise. Alarm = trigger + 5 min, never after latest."""
import subprocess
import threading
import time
from datetime import timedelta

from sleep_detect import percentile

SUNRISE = timedelta(minutes=5)


def decide(now, plan, readings, asleep):
    """readings: (datetime, movement, light) for tonight. Returns (trigger_at, alarm_at, reason) or None."""
    latest = plan["latest"]
    fallback = latest - SUNRISE
    late = asleep is None or asleep > plan["asleep_by"]
    start = fallback if late else plan["window_start"]
    if now < start:
        return None
    if now >= fallback:
        if now > latest + timedelta(hours=1):  # long past: don't ring in the afternoon
            return None
        return now, max(now, latest), "late sleep: last 5 min" if late else "fallback latest-5"
    last = [r for r in readings if r[0] < now][-1:]
    if last and last[0][0] >= now - timedelta(minutes=2) and last[0][1] > percentile([r[1] for r in readings], 75):
        return now, now + SUNRISE, f"movement {last[0][1]} > night p75"
    return None


def sunrise(seconds=300, steps=60):
    """Ramp backlight 5% -> 100% in a background thread."""
    def run():
        for i in range(steps + 1):
            subprocess.run(["brightnessctl", "-q", "set", f"{5 + 95 * i // steps}%"], check=False)
            time.sleep(seconds / steps)
    threading.Thread(target=run, daemon=True).start()
