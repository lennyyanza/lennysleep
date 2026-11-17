"""in_bed = first time light stays below threshold 5 min; asleep = first 15 calm min after that.
readings: list of (datetime, movement, light) sorted by time, one per minute."""
import os

LIGHT_DARK = float(os.getenv("LIGHT_DARK", 5))


def percentile(values, p):
    v = sorted(values)
    return v[min(len(v) - 1, int(p / 100 * len(v)))] if v else 0


def _first_run(rows, ok, minutes):
    run = []
    for r in rows:
        run = run + [r] if ok(r) else []
        if len(run) >= minutes:
            return run[0][0]
    return None


def detect(readings, dark=LIGHT_DARK):
    in_bed = _first_run(readings, lambda r: r[2] is not None and r[2] < dark, 5)
    if in_bed is None:
        return None, None
    p25 = percentile([r[1] for r in readings], 25)
    asleep = _first_run([r for r in readings if r[0] >= in_bed], lambda r: r[1] <= p25, 15)
    return in_bed, asleep
