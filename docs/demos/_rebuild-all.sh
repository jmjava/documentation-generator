#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/../../.venv"
source "$VENV/bin/activate"
pip install -e "$SCRIPT_DIR/../.." -q

echo "=== [$(date +%H:%M:%S)] Step 1: Reinstalled docgen ==="

echo "=== [$(date +%H:%M:%S)] Step 2: Rendering Manim ==="
docgen --config docgen.yaml manim

echo "=== [$(date +%H:%M:%S)] Step 3: Rendering VHS tapes ==="
for tape in 02-init-scaffold 04-tts-pipeline 05-compose-validate 06-ci-integration; do
    echo "  --- $tape ---"
    docgen --config docgen.yaml vhs --tape "${tape}.tape"
done

echo "=== [$(date +%H:%M:%S)] Step 4: Durations check ==="
echo "  Manim:"
for f in animations/media/videos/scenes/720p30/*.mp4; do
    dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null)
    echo "    $(basename "$f"): ${dur}s"
done
echo "  VHS:"
for f in terminal/rendered/*.mp4; do
    dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null)
    echo "    $(basename "$f"): ${dur}s"
done
echo "  Audio:"
for f in audio/*.mp3; do
    dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null)
    echo "    $(basename "$f"): ${dur}s"
done

echo "=== [$(date +%H:%M:%S)] Step 5: Composing all segments ==="
docgen --config docgen.yaml compose

echo "=== [$(date +%H:%M:%S)] Step 6: Validating ==="
docgen --config docgen.yaml validate

echo "=== [$(date +%H:%M:%S)] Step 7: Final recording timestamps ==="
ls -la recordings/*.mp4

echo "=== [$(date +%H:%M:%S)] DONE ==="
