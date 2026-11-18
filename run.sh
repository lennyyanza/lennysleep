#!/usr/bin/env bash
# ./run.sh        tonight: collector (no suspend) + Brave kiosk
# ./run.sh test 8 practice run: real everything, alarm in 8 min, separate test.db
# TIMELAPSE=1 ./run.sh  same, plus a webcam timelapse in station/timelapse/<date>/
# ./run.sh demo   10x demo morning on sample data (separate demo.db, no serial, no backlight)
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q pyserial fastapi uvicorn icalendar httpx python-dotenv pytest opencv-python-headless; }

V=station/static/vendor
if [ ! -f $V/pose_landmarker_lite.task ]; then  # one-time download; runs offline afterwards
  T=$(mktemp -d); (cd "$T" && npm pack -s @mediapipe/tasks-vision@0.10.14 >/dev/null && tar xzf ./*.tgz)
  mkdir -p $V && cp "$T"/package/vision_bundle.mjs $V/ && cp -r "$T"/package/wasm $V/ && rm -rf "$T"
  curl -fsSL -o $V/pose_landmarker_lite.task \
    https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
fi

[ "${1:-}" = demo ] && export DEMO=1
# ./run.sh test [N]: practice run, alarm in N min (default 8), fresh station/test.db, real hardware
[ "${1:-}" = test ] && export REHEARSE_MIN=${2:-8} DB=$PWD/station/test.db && rm -f station/test.db
cd station
systemd-inhibit --what=sleep:idle:handle-lid-switch --who=lennysleep --why="logging sleep + alarm" \
  ../.venv/bin/python -m uvicorn collector:app --host 0.0.0.0 --port 8000 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
until curl -fs localhost:8000/plan >/dev/null; do sleep 0.5; done
[ -n "${TIMELAPSE:-}" ] && [ -z "${DEMO:-}" ] && { ../.venv/bin/python timelapse.py & }
# Spotify app waits in the background for the morning; started before the kiosk so the kiosk ends up on top
if [ -z "${DEMO:-}" ] && command -v spotify >/dev/null && ! pgrep -x spotify >/dev/null; then
  spotify >/dev/null 2>&1 &
  for _ in $(seq 40); do gdbus call --session --dest org.mpris.MediaPlayer2.spotify --object-path /org/mpris/MediaPlayer2 \
    --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player PlaybackStatus >/dev/null 2>&1 && break; sleep 0.5; done
fi
brave-browser --kiosk --user-data-dir="$HOME/.config/lennysleep-brave" --no-first-run \
  --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream http://localhost:8000 || true
wait $PID
