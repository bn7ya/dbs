#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
OUT="${1:-dbs-reel.mp4}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

node render.cjs cues > "$WORK/cues.json"
python3 music.py "$WORK/cues.json" "$WORK/music.wav"
node render.cjs video "$WORK/silent.mp4"

TARGET="I=-14:TP=-1.5:LRA=11"
MEASURED="$(ffmpeg -hide_banner -i "$WORK/music.wav" -af "loudnorm=$TARGET:print_format=json" -f null - 2>&1 \
  | python3 -c 'import json, sys; t = sys.stdin.read(); m = json.loads(t[t.rindex("{"):]); print("measured_I=%(input_i)s:measured_TP=%(input_tp)s:measured_LRA=%(input_lra)s:measured_thresh=%(input_thresh)s:offset=%(target_offset)s" % m)')"

ffmpeg -y -loglevel error -i "$WORK/silent.mp4" -i "$WORK/music.wav" \
  -map 0:v -map 1:a -c:v copy \
  -af "loudnorm=$TARGET:$MEASURED:linear=true" -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart -shortest "$OUT"

node render.cjs stills 2.4 "$WORK" > /dev/null
mv "$WORK/still-02.40.png" cover.png
echo "$OUT and cover.png written"
