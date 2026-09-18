#!/usr/bin/env bash
# Record a labelled wake-word corpus through the live mic path.
#
#   ./collect_wake_data.sh positives 90 60
#   ./collect_wake_data.sh negatives 180 60
#
# Args: <name> <seconds> [pga_gain]
# The systemd service holds the mic, so it is stopped for the recording and
# restarted afterwards no matter how this exits. Recordings MUST go through
# the same card and gain as the live detector or the sweep tunes for audio
# the device will never see.
set -euo pipefail

NAME="${1:?usage: collect_wake_data.sh <name> <seconds> [pga_gain]}"
SECS="${2:?usage: collect_wake_data.sh <name> <seconds> [pga_gain]}"
GAIN="${3:-}"
OUT_DIR="$HOME/sichuan/wake_data"
OUT="$OUT_DIR/${NAME}.wav"
CARD=2

mkdir -p "$OUT_DIR"

restart_service() { systemctl --user start sichuan.service 2>/dev/null || true; }
trap restart_service EXIT

echo "[collect] stopping sichuan.service to free the mic..."
systemctl --user stop sichuan.service 2>/dev/null || true
sleep 1

if [ -n "$GAIN" ]; then
  amixer -c "$CARD" sset 'PGA' "$GAIN" >/dev/null
fi
echo "[collect] capture gain: $(amixer -c "$CARD" sget 'PGA' | grep -m1 'Front Left' | sed 's/^ *//')"

echo
echo "  Recording '$NAME' for ${SECS}s to $OUT"
echo "  Starting in 3..."; sleep 1; echo "  2..."; sleep 1; echo "  1..."; sleep 1
echo "  GO — speak now."
arecord -q -f S16_LE -r 16000 -c 1 -d "$SECS" "$OUT"
echo "[collect] done: $(du -h "$OUT" | cut -f1) -> $OUT"
