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
