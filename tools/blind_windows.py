#!/usr/bin/env python3
"""Per-window yes/no for a beep-paced take, for blind recall/precision tests.

collect_wake_paced.sh paces the speaker with beeps and writes a .marks
sidecar; this replays the whole take through the spotter exactly as the live
loop does (continuous decode, no per-window reset) and then buckets each
detection into the window it belongs to.

Unlike sweep_kws.py this makes no assumption about what was said: every
window gets a verdict, so a window where the speaker said anything OTHER than
the wake phrase -- ordinary talk, household noise, near misses -- scores as a
false accept rather than vanishing from the denominator. Ground truth
stays with the human until after the verdicts are read out.

    ./.venv/bin/python tools/blind_windows.py --name blind10 --window 5
"""
import argparse, os, wave
import numpy as np
from sherpa_onnx import KeywordSpotter

MODEL_DIR = "/home/weilie/sichuan/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KEYWORDS = "/home/weilie/sichuan/models/wake_keywords.txt"
DATA_DIR = os.path.expanduser("~/sichuan/wake_data")
RATE = 16000
CHUNK = 1600          # 100 ms, same as the live loop
MIN_GAP_S = 1.0       # two hits closer than this are one utterance
BEEP_LEN_S = 0.35     # the beep itself is not speech; skip it
LATE_TOLERANCE_S = 0.6  # the spotter fires at the END of the phrase


def build(score, threshold):
    return KeywordSpotter(
        tokens=f"{MODEL_DIR}/tokens.txt",
        encoder=f"{MODEL_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        decoder=f"{MODEL_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        joiner=f"{MODEL_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        keywords_file=KEYWORDS, num_threads=2, max_active_paths=16,
        keywords_score=score, keywords_threshold=threshold,
        num_trailing_blanks=1, provider="cpu")


def detections(spotter, audio):
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
    ap.add_argument("--name", required=True)
    ap.add_argument("--window", type=float, default=5.0)
    ap.add_argument("--score", type=float, default=4.0)
    ap.add_argument("--thresh", type=float, default=0.05)
    a = ap.parse_args()

    wav_path = f"{DATA_DIR}/{a.name}.wav"
    with wave.open(wav_path) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0

    marks = []
    with open(f"{DATA_DIR}/{a.name}.marks") as f:
        for line in f:
            if line.strip():
                marks.append(float(line.split()[1]))

    hits = detections(build(a.score, a.thresh), audio)

    # Noise floor from the whole take, so per-window level is comparable.
    win = 1600
    rms = np.array([int(np.sqrt(np.mean(pcm[i:i + win].astype(np.int64) ** 2)))
                    for i in range(0, len(pcm) - win, win)])
    floor = np.percentile(rms, 10)
    print(f"take: {os.path.basename(wav_path)}  {len(pcm)/RATE:.1f}s  "
          f"floor(p10)={floor:.0f}  setting score={a.score} thresh={a.thresh}")
    print(f"raw detections at: {hits}\n")

    for i, m in enumerate(marks, 1):
        start, end = m + BEEP_LEN_S, m + a.window
        fired = [h for h in hits if start <= h <= end + LATE_TOLERANCE_S]
        seg = pcm[int(start * RATE):int(end * RATE)]
        srms = np.array([int(np.sqrt(np.mean(seg[j:j + win].astype(np.int64) ** 2)))
                         for j in range(0, max(len(seg) - win, 1), win)])
        loud = int(np.count_nonzero(srms > 3 * floor)) if len(srms) else 0
        print(f"window {i:2d}  [{start:5.1f}-{end:5.1f}s]  "
              f"{'YES' if fired else 'no ':3}  "
              f"peak={srms.max() if len(srms) else 0:5d} loud={loud:2d}"
              + (f"  at {fired}" if fired else ""))


if __name__ == "__main__":
    main()
