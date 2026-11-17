#!/usr/bin/env bash
# ./run.sh        tonight: collector (no suspend) + Brave kiosk
# ./run.sh demo   10x demo morning on sample data (separate demo.db, no serial, no backlight)
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q pyserial fastapi uvicorn icalendar httpx python-dotenv pytest; }

V=station/static/vendor
if [ ! -f $V/pose_landmarker_lite.task ]; then  # one-time download; runs offline afterwards
  T=$(mktemp -d); (cd "$T" && npm pack -s @mediapipe/tasks-vision@0.10.14 >/dev/null && tar xzf ./*.tgz)
  mkdir -p $V && cp "$T"/package/vision_bundle.mjs $V/ && cp -r "$T"/package/wasm $V/ && rm -rf "$T"
  curl -fsSL -o $V/pose_landmarker_lite.task \
    https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
fi

[ "${1:-}" = demo ] && export DEMO=1
cd station
systemd-inhibit --what=sleep:idle:handle-lid-switch --who=lennysleep --why="logging sleep + alarm" \
  ../.venv/bin/python -m uvicorn collector:app --host 0.0.0.0 --port 8000 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
until curl -fs localhost:8000/plan >/dev/null; do sleep 0.5; done
brave-browser --kiosk --user-data-dir="$HOME/.config/lennysleep-brave" --no-first-run \
  --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream http://localhost:8000 || true
wait $PID
