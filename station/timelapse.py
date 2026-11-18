"""Night timelapse: one webcam frame every 30 s, stamped with time + sensor readings.
Stops when the alarm fires (the browser needs the camera for the stand-up check) or the app goes away,
then writes timelapse/<date>/night.mp4. Frames stay on this laptop."""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import httpx

API = "http://localhost:8000/today"
EVERY = int(os.getenv("TIMELAPSE_S", 30))
OUT = Path(__file__).parent / "timelapse" / datetime.now().strftime("%Y-%m-%d")


def grab(cam=0):
    """One frame, camera released right after so nothing else is blocked."""
    cap = cv2.VideoCapture(cam)
    try:
        for _ in range(10):  # let auto-exposure settle; the first frames are dark
            ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def stamp(frame, lines):
    for i, text in enumerate(lines):
        y = 30 + 28 * i
        cv2.putText(frame, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def label(today):
    r = today.get("last_reading") or {}
    return [datetime.now().strftime("%H:%M"),
            f"light {r.get('light', '-')}  move {r.get('movement', '-')}  loud {r.get('loud', '-')}  temp {r.get('temp', '-')}"]


def assemble(folder, fps=24):
    frames = sorted(folder.glob("*.jpg"), key=lambda f: f.stat().st_mtime)  # names are HHMMSS, which wrap at midnight
    if not frames:
        return None
    h, w = cv2.imread(str(frames[0])).shape[:2]
    out = folder / "night.mp4"
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(cv2.resize(cv2.imread(str(f)), (w, h)))
    vw.release()
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("timelapse ->", OUT, flush=True)
    try:
        while True:
            try:
                today = httpx.get(API, timeout=10).json()
            except Exception:
                break  # app stopped
            if (today.get("night") or {}).get("alarm_at"):
                break  # hand the camera to the browser
            frame = grab()
            if frame is not None:
                cv2.imwrite(str(OUT / f"{datetime.now():%H%M%S}.jpg"), stamp(frame, label(today)))
            time.sleep(EVERY)
    except KeyboardInterrupt:
        pass
    print("timelapse video:", assemble(OUT), flush=True)


if __name__ == "__main__":
    sys.exit(main())
