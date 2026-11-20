"""Decide when to start the 5-min sunrise. Alarm = trigger + 5 min, never after latest."""
import os
import re
import subprocess
import threading
import time
from datetime import timedelta

from sleep_detect import percentile

SUNRISE = timedelta(minutes=5)
MUSIC_VOL = os.getenv("MUSIC_VOL", "0.25")
# spotify:playlist:ID from the share link; played in the Spotify desktop app (free tier plays full songs there)
SPOTIFY_URI = re.sub(r"^https://open\.spotify\.com/(\w+)/(\w+).*", r"spotify:\1:\2", os.getenv("SPOTIFY_URL", ""))
MOVE_UP = float(os.getenv("MOVE_UP", 10))  # shortcut: fixed mattress-movement count = "you're up"; tune from real nights


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


def up_from_sensor(readings, alarm_at, threshold=MOVE_UP):
    """True once the mattress sensor logs a big movement burst after the alarm started."""
    return any(ts > alarm_at and m is not None and m >= threshold for ts, m, _ in readings)


def power(on):
    """Monitor fully on/off (DPMS) via GNOME Mutter; brightness 0 alone still glows. Any touch/key wakes it."""
    subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
                    "--object-path", "/org/gnome/Mutter/DisplayConfig", "--method", "org.freedesktop.DBus.Properties.Set",
                    "org.gnome.Mutter.DisplayConfig", "PowerSaveMode", f"<int32 {0 if on else 3}>"],
                   capture_output=True, check=False)


def sunrise(seconds=300, steps=60):
    """Monitor on, then ramp backlight 5% -> 100% in a background thread."""
    def run():
        power(True)
        for i in range(steps + 1):
            subprocess.run(["brightnessctl", "-q", "set", f"{5 + 95 * i // steps}%"], check=False)
            time.sleep(seconds / steps)
    threading.Thread(target=run, daemon=True).start()


def _sink(prefix, status=None):
    """wpctl id of the first sink whose node name starts with prefix (alsa_output = speakers, bluez_output = buds)."""
    if status is None:
        status = subprocess.run(["wpctl", "status", "-n"], capture_output=True, text=True, check=False).stdout
    m = re.search(rf"(\d+)\.\s+{prefix}\S*", status)
    return m and m.group(1)


def _use(sink, volume):
    if sink:  # Brave's streams follow the default sink
        for cmd in (["set-default", sink], ["set-mute", sink, "0"], ["set-volume", sink, volume]):
            subprocess.run(["wpctl", *cmd], check=False)


_music = None  # sink music is on; set only on change so your own volume tweaks stick


def alarm_audio():
    """Alarm always on the laptop speakers, unmuted and loud, even if buds are connected."""
    global _music
    _music = None
    _use(_sink("alsa_output"), "0.8")


def music_audio():
    """Morning music: buds if connected, otherwise the speakers, quiet. Called again every tick to follow the buds."""
    global _music
    sink = _sink("bluez_output") or _sink("alsa_output")
    if sink != _music:
        _music = sink
        _use(sink, MUSIC_VOL)


def _pc(cmd, arg=None):
    """Control the Spotify app over MPRIS with gdbus (ships with Ubuntu): status/shuffle/open/play/pause."""
    p = "org.mpris.MediaPlayer2.Player"
    method = {"status": ["org.freedesktop.DBus.Properties.Get", p, "PlaybackStatus"],
              "shuffle": ["org.freedesktop.DBus.Properties.Set", p, "Shuffle", "<true>"],
              "open": [p + ".OpenUri", arg], "play": [p + ".Play"], "pause": [p + ".Pause"]}[cmd]
    try:
        return subprocess.run(["gdbus", "call", "--session", "--timeout", "5", "--dest", "org.mpris.MediaPlayer2.spotify",
                               "--object-path", "/org/mpris/MediaPlayer2", "--method", *method],
                              capture_output=True, check=False).returncode == 0
    except FileNotFoundError:  # no gdbus: no music, alarm unaffected
        return False


def music_start():
    """Play the playlist shuffled in the Spotify app (started by run.sh; launched here if it was closed)."""
    if not SPOTIFY_URI:
        return
    if not _pc("status"):
        try:
            subprocess.Popen(["spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return
        for _ in range(40):
            if _pc("status"):
                break
            time.sleep(0.5)
    _pc("shuffle", "On")
    _pc("open", SPOTIFY_URI)
    time.sleep(2)
    _pc("shuffle", "On")  # Spotify may reset it when the playlist loads
    _pc("play")


_state = {}


def music_tick(day, woke, first_event, now):
    """Each second after you're up: follow the buds; stop once they disconnect or the event starts."""
    if _state.get("day") != day:
        _state.clear()
        _state["day"] = day
    if not woke or _state.get("stopped"):
        return
    buds = bool(_sink("bluez_output"))
    if now >= first_event or (_state.get("buds") and not buds):
        _state["stopped"] = True
        _pc("pause")
        return
    _state["buds"] = _state.get("buds") or buds
    music_audio()
