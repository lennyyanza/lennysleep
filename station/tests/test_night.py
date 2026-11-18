"""Simulated nights through sleep_detect + wake_engine."""
from datetime import datetime, timedelta

import plan
import sleep_detect
import wake_engine

P = plan.make_plan(datetime(2026, 11, 18, 6))  # latest 5:12, window 4:57, asleep_by 21:42


def night(lights_out="21:20", calm_from="21:30", spike=None):
    """Minute readings 20:00 -> 05:20. Restless before calm_from, then 0 (with sparse 1s)."""
    rows, t = [], datetime(2026, 11, 17, 20)
    out = datetime.combine(t.date(), datetime.strptime(lights_out, "%H:%M").time())
    calm = datetime.combine(t.date(), datetime.strptime(calm_from, "%H:%M").time())
    while t < datetime(2026, 11, 18, 5, 20):
        mov = 10 if t < calm else (1 if t.minute == 59 and t.hour != 4 else 0)
        if spike and t == spike:
            mov = 25
        rows.append((t, mov, 80 if t < out else 0))
        t += timedelta(minutes=1)
    return rows


def run(rows):
    """Step the engine minute by minute like the collector does. Returns decision."""
    _, asleep = sleep_detect.detect(rows)
    t = P["window_start"] - timedelta(minutes=5)
    while t <= P["latest"]:
        seen = [r for r in rows if r[0] < t]
        if d := wake_engine.decide(t, P, seen, sleep_detect.detect(seen)[1]):
            return d
        t += timedelta(minutes=1)


def test_in_bed_and_asleep():
    in_bed, asleep = sleep_detect.detect(night())
    assert in_bed == datetime(2026, 11, 17, 21, 20)
    assert asleep == datetime(2026, 11, 17, 21, 30)


def test_lights_on_means_not_in_bed():
    assert sleep_detect.detect(night(lights_out="23:59")[:200]) == (None, None)


def test_spike_in_window_triggers():
    spike = datetime(2026, 11, 18, 5, 0)
    trig, alarm, why = run(night(spike=spike))
    assert trig == spike + timedelta(minutes=1) and alarm == trig + timedelta(minutes=5)
    assert "movement" in why and alarm <= P["latest"]


def test_no_spike_falls_back_to_latest_minus_5():
    trig, alarm, why = run(night())
    assert trig == datetime(2026, 11, 18, 5, 7) and alarm == P["latest"] and "fallback" in why


def test_late_sleep_ignores_early_spike():
    rows = night(lights_out="23:00", calm_from="23:10", spike=datetime(2026, 11, 18, 5, 0))
    assert sleep_detect.detect(rows)[1] > P["asleep_by"]
    trig, alarm, why = run(rows)
    assert trig == datetime(2026, 11, 18, 5, 7) and alarm == P["latest"] and "late" in why


def test_never_after_latest():
    late = P["latest"] + timedelta(minutes=3)
    trig, alarm, _ = wake_engine.decide(late, P, night(), datetime(2026, 11, 17, 21, 30))
    assert alarm == late  # missed window (e.g. laptop was off): ring now, not later
    assert wake_engine.decide(P["latest"] + timedelta(hours=2), P, night(), None) is None


def test_sink_picks_speakers_and_buds():
    import wake_engine
    status = """ ├─ Sinks:
 │  *   51. alsa_output.pci-0000_00_1f.3.analog-stereo [vol: 0.00 MUTED]
 │      88. bluez_output.B8_7B_D4_18_B8_71.1 [vol: 0.60]
 ├─ Sources:
 │  *   52. alsa_input.pci-0000_00_1f.3.analog-stereo [vol: 1.00]"""
    assert wake_engine._sink("alsa_output", status) == "51"
    assert wake_engine._sink("bluez_output", status) == "88"
    assert wake_engine._sink("bluez_output", status.replace("bluez", "x")) is None


def test_music_follows_buds_once(monkeypatch):
    import wake_engine
    sinks, used = {"alsa_output": "51", "bluez_output": None}, []
    monkeypatch.setattr(wake_engine, "_sink", sinks.get)
    monkeypatch.setattr(wake_engine, "_use", lambda s, v: used.append(s))
    wake_engine.alarm_audio(); wake_engine.music_audio(); wake_engine.music_audio()
    sinks["bluez_output"] = "61"  # buds connect mid-routine
    wake_engine.music_audio(); wake_engine.music_audio()
    assert used == ["51", "51", "61"]  # alarm, music on speakers, then buds; no repeats


def test_up_from_sensor():
    from datetime import datetime, timedelta
    import wake_engine
    a = datetime(2026, 11, 18, 7, 8)
    rows = [(a - timedelta(minutes=1), 30, 0), (a + timedelta(minutes=1), 4, 0)]
    assert not wake_engine.up_from_sensor(rows, a, 10)  # big move before the alarm and a small roll after don't count
    assert wake_engine.up_from_sensor(rows + [(a + timedelta(minutes=2), 12, 0)], a, 10)


def test_music_tick_follows_and_stops(monkeypatch):
    from datetime import datetime, timedelta
    import wake_engine
    sinks, calls = {"alsa_output": "51", "bluez_output": None}, []
    monkeypatch.setattr(wake_engine, "_sink", sinks.get)
    monkeypatch.setattr(wake_engine, "_use", lambda s, v: calls.append(s))
    monkeypatch.setattr(wake_engine, "_pc", lambda *a: calls.append(a[0]))
    ev, t = datetime(2026, 11, 18, 8), datetime(2026, 11, 18, 7, 10)
    wake_engine.alarm_audio(); calls.clear()
    wake_engine.music_tick("d1", None, ev, t)                 # not up yet: nothing
    wake_engine.music_tick("d1", "07:09", ev, t)              # up: speakers
    sinks["bluez_output"] = "61"
    wake_engine.music_tick("d1", "07:09", ev, t)              # buds connect: move
    sinks["bluez_output"] = None
    wake_engine.music_tick("d1", "07:09", ev, t)              # buds out: pause
    wake_engine.music_tick("d1", "07:09", ev, t)              # stays stopped
    assert calls == ["51", "61", "pause"]
    wake_engine.music_tick("d2", "07:09", ev, ev + timedelta(minutes=1))  # new day, event passed: pause
    assert calls[-1] == "pause"
