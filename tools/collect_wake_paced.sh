#!/usr/bin/env bash
# Record a wake-word corpus paced by beeps, so every utterance is labelled.
#
#   ./collect_wake_paced.sh positives 20 4 60
#
# Args: <name> <utterances> <seconds_between> [pga_gain]
#
# Free-form recording turned out to be unlabellable: a 120 s take produced 87
# energy bursts (room noise and other talking), so recall had no trustworthy
# denominator. Here the device sets the pace — it beeps N times, you say the
# phrase once after each beep, and the sidecar file records exactly when each
# beep fired. That gives per-utterance windows, not just a total count, so the
# sweep can say WHICH utterances a setting misses.
set -euo pipefail

NAME="${1:?usage: collect_wake_paced.sh <name> <utterances> <gap_s> [gain]}"
COUNT="${2:?usage: collect_wake_paced.sh <name> <utterances> <gap_s> [gain]}"
GAP="${3:?usage: collect_wake_paced.sh <name> <utterances> <gap_s> [gain]}"
GAIN="${4:-}"
PHRASE="${5:-麻婆豆腐}"   # what to say after each beep
OUT_DIR="$HOME/sichuan/wake_data"
OUT="$OUT_DIR/${NAME}.wav"
MARKS="$OUT_DIR/${NAME}.marks"
CARD=2
LEAD=3          # silence before the first beep
TAIL=6          # keep recording after the last beep. Was 2, which was
                # shorter than one answer window plus aplay drift, so the
                # final beep landed 0.04 s before the recording ended and
                # that utterance was never captured.

mkdir -p "$OUT_DIR"
restart_service() { systemctl --user start sichuan.service 2>/dev/null || true; }
trap restart_service EXIT

systemctl --user stop sichuan.service 2>/dev/null || true
sleep 1
[ -n "$GAIN" ] && amixer -c "$CARD" sset 'PGA' "$GAIN" >/dev/null
echo "[collect] gain: $(amixer -c "$CARD" sget 'PGA' | grep -m1 'Front Left' | sed 's/^ *//')"

DUR=$(( LEAD + COUNT * GAP + TAIL ))
echo "[collect] $COUNT utterances, one per beep, ${GAP}s apart -> ${DUR}s total"
echo "[collect] say $PHRASE ONCE after each beep, then wait for the next"
echo

: > "$MARKS"
arecord -q -f S16_LE -r 16000 -c 1 -d "$DUR" "$OUT" &
REC_PID=$!
START=$(date +%s.%N)
sleep "$LEAD"

for i in $(seq 1 "$COUNT"); do
  NOW=$(date +%s.%N)
  echo "$i $(awk -v a="$NOW" -v b="$START" 'BEGIN{printf "%.2f", a-b}')" >> "$MARKS"
  aplay -q /tmp/ack.wav 2>/dev/null || true
  echo "  beep $i / $COUNT"
  sleep "$GAP"
done

wait "$REC_PID"
echo
echo "[collect] done: $OUT"
echo "[collect] marks: $MARKS ($(wc -l < "$MARKS") beeps)"
