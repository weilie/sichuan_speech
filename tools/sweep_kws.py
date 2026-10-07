#!/usr/bin/env python3
"""Grid-search the wake-word detector against recorded audio.

    python3 tools/sweep_kws.py --positives wake_data/pos.wav --marks wake_data/pos.marks \
                               --negatives wake_data/neg.wav

Replays each file through sherpa-onnx at every (keywords_score,
keywords_threshold) pair and reports recall and false alarms. Deterministic,
so a change to the wake path can be re-checked against the same corpus
instead of re-tested by hand.

sherpa-onnx exposes no per-result score, so sensitivity can only be explored
by rebuilding the spotter per cell — hence the model reload each row.
"""
import argparse, wave
import numpy as np
from _daemon import W

# Defaults are the Pi's paths; override with --model-dir / --keywords to run
# the sweep on a faster machine. Decoding is deterministic, so results carry
# over — but confirm the chosen setting on the Pi, whose sherpa-onnx build may
# differ from the one doing the sweeping.
MODEL_DIR = W.KWS_MODEL_DIR
KEYWORDS = W.KWS_KEYWORDS_FILE
RATE = W.WAKE_RATE
CHUNK = W.WAKE_CHUNK  # 100 ms, same as the live loop
MIN_GAP_S = 1.0       # two hits closer than this are one utterance
BEEP_LEN_S = 0.35     # skip the beep itself at the head of a window
WINDOW_S = 4.2        # a beep's window: long enough for one slow utterance
LATE_TOLERANCE_S = 0.6


def build(score, threshold, model_dir=MODEL_DIR, keywords=KEYWORDS):
    # The daemon's own builder, so the beam width under test is the one that
    # ships. Two threads only make the replay faster.
    return W.build_kws(score, threshold, model_dir=model_dir,
                       keywords_file=keywords, num_threads=2)


def read_wav(path):
    with wave.open(path) as w:
        assert w.getframerate() == RATE, f"{path}: expected {RATE} Hz, got {w.getframerate()}"
        assert w.getnchannels() == 1, f"{path}: expected mono"
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def score_windows(hits, windows):
    """Which labelled windows contain at least one detection.

    The spotter fires at the END of the phrase, so a hit is allowed to land
    slightly past the window it belongs to."""
    missed = []
    for i, (start, end) in enumerate(windows, 1):
        if not any(start <= h <= end + LATE_TOLERANCE_S for h in hits):
            missed.append(i)
    return missed


def detections(spotter, audio):
    """Return the timestamps (s) at which the phrase fired."""
    stream = spotter.create_stream()
    hits, last = [], -1e9
    for i in range(0, len(audio) - CHUNK, CHUNK):
        stream.accept_waveform(RATE, audio[i:i + CHUNK])
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
        if spotter.get_result(stream):
            t = i / RATE
            spotter.reset_stream(stream)
            if t - last >= MIN_GAP_S:
                hits.append(round(t, 1))
                last = t
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positives", required=True)
    ap.add_argument("--marks", required=True,
                    help=".marks sidecar from collect_wake_paced.sh: one "
                         "'<index> <seconds>' line per beep")
    ap.add_argument("--negatives")
    ap.add_argument("--scores", default="1.0,1.5,2.0,2.5,3.0")
    ap.add_argument("--thresholds", default="0.05,0.10,0.15,0.20,0.25,0.30,0.35")
    ap.add_argument("--model-dir", default=MODEL_DIR)
    ap.add_argument("--keywords", default=KEYWORDS)
    args = ap.parse_args()

    pos = read_wav(args.positives)
    neg = read_wav(args.negatives) if args.negatives else None
    marks = [float(l.split()[1]) for l in open(args.marks) if l.strip()]
    # A beep whose window runs past the end of the recording was never given a
    # chance to be answered; counting it as a miss would understate recall.
    dur = len(pos) / RATE
    windows = [(t + BEEP_LEN_S, min(t + WINDOW_S, dur)) for t in marks
               if t + BEEP_LEN_S + 1.0 <= dur]
    dropped = len(marks) - len(windows)
    print(f"positives {dur:.0f}s, {len(windows)} answerable windows"
          + (f" ({dropped} beep(s) ran past the end of the recording)" if dropped else "")
          + (f", negatives {len(neg)/RATE:.0f}s" if neg is not None else ""))
    print()
    print(f"{'score':>6} {'thresh':>7} {'recall':>9} {'false':>6}  missed windows")

    # The live cell is always in the grid, so every sweep reports the shipped
    # setting beside the alternatives and marks it.
    scores = sorted({float(x) for x in args.scores.split(",")} | {W.KWS_SCORE})
    thresholds = sorted({float(x) for x in args.thresholds.split(",")}
                        | {W.KWS_THRESHOLD})
    best = []
    for score in scores:
        for thr in thresholds:
            hits = detections(build(score, thr, args.model_dir, args.keywords), pos)
            missed = score_windows(hits, windows)
            got = len(windows) - len(missed)
            recall = got / len(windows) if windows else 0.0
            false = (len(detections(build(score, thr, args.model_dir, args.keywords), neg))
                     if neg is not None else -1)
            if not missed and false == 0:
                best.append((score, thr))
            note = "none  <== clean" if not missed and false == 0 else (
                   "none" if not missed else ",".join(str(m) for m in missed[:8])
                   + ("..." if len(missed) > 8 else ""))
            live = "  <-- LIVE" if (score, thr) == (W.KWS_SCORE, W.KWS_THRESHOLD) else ""
            print(f"{score:>6.1f} {thr:>7.2f} {got:>3}/{len(windows):<3} {recall:>4.0%} "
                  f"{false if false >= 0 else '-':>6}  {note}{live}")
    print()
    if best:
        print("Settings with full recall and zero false alarms:")
        for score, thr in best:
            print(f"  keywords_score={score}  keywords_threshold={thr}")
        print("Prefer the least sensitive of these (highest threshold, lowest "
              "score) — it leaves the most headroom against false wakes in a "
              "room this corpus did not capture.")
    else:
        print("No cell achieved both. Pick from the recall/false-alarm trade-off "
              "above, or record more positives — the phrase itself may need "
              "pronunciation variants in wake_keywords.txt.")


if __name__ == "__main__":
    main()
