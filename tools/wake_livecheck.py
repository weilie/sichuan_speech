#!/usr/bin/env python3
"""Record the wake phrase live, then replay it through the spotter.

The corpus sweep (tools/sweep_kws.py) answers "does the model still work";
this answers "is what the mic hears now like what it was tuned on". Run it on
the Pi when the wake word stops firing:

    ./.venv/bin/python tools/wake_livecheck.py

Stops the service (the codec is half-duplex, so the daemon must release the
mic), records, restarts the service, then decodes offline at the live setting
and at progressively looser ones. Where the phrase first appears tells you
which knob is wrong:

  - fires at the live setting        -> the mic path is fine; suspect
                                        placement, or that the daemon was not
                                        actually listening at the time
  - fires only looser                -> heard but rejected on threshold
  - never fires, but RMS shows speech -> the audio reaching the model is
                                        wrong (gain, clipping, channel)
  - RMS flat                          -> nothing reached the mic at all
"""
import subprocess, sys, time, wave
import numpy as np
from sherpa_onnx import KeywordSpotter

MODEL_DIR = "/home/weilie/sichuan/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KEYWORDS = "/home/weilie/sichuan/models/wake_keywords.txt"
WAV = "/tmp/wake_livecheck.wav"
SECONDS = 25
SERVICE = "sichuan.service"
# Live setting first, then looser. See sweep_kws.py for why looser is not
# automatically better -- 5.0/0.02 catches FEWER utterances, not more.
GRID = [(4.0, 0.05), (3.0, 0.10), (2.5, 0.10), (2.0, 0.20), (1.5, 0.25)]


def build(score, thresh):
    return KeywordSpotter(
        tokens=f"{MODEL_DIR}/tokens.txt",
        encoder=f"{MODEL_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        decoder=f"{MODEL_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        joiner=f"{MODEL_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        keywords_file=KEYWORDS, num_threads=1, max_active_paths=4,
        keywords_score=score, keywords_threshold=thresh,
        num_trailing_blanks=1, provider="cpu")


def main():
    subprocess.run(["systemctl", "--user", "stop", SERVICE], check=False)
    time.sleep(1.5)
    print(f"\n>>> RECORDING {SECONDS}s — say 麻婆豆腐 clearly, 4 times, "
          f"pausing ~3s between each.\n", flush=True)
    r = subprocess.run(["arecord", "-D", "default", "-f", "S16_LE", "-r", "16000",
                        "-c", "1", "-d", str(SECONDS), WAV],
                       capture_output=True, text=True)
    subprocess.run(["systemctl", "--user", "start", SERVICE], check=False)
    if r.returncode != 0:
        sys.exit(f"arecord failed: {r.stderr.strip()[:300]}")
    print(">>> recording done, service restarted. Decoding...\n")

    with wave.open(WAV) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    # Level first: a detection question is only meaningful if speech arrived.
    win = 1600
    rms = np.array([int(np.sqrt(np.mean(pcm[i:i+win].astype(np.int64)**2)))
                    for i in range(0, len(pcm)-win, win)])
    clipped = 100.0 * np.count_nonzero(np.abs(pcm) >= 32700) / max(len(pcm), 1)
    print(f"level: floor(p10)={np.percentile(rms,10):.0f} "
          f"median={np.median(rms):.0f} peak={rms.max()} "
          f"loud_frames(>3x floor)={np.count_nonzero(rms > 3*np.percentile(rms,10))} "
          f"clipped={clipped:.2f}%")

    audio = (pcm.astype(np.float32) / 32768.0)
    for score, thresh in GRID:
        sp = build(score, thresh)
        st = sp.create_stream()
        hits = []
        for i in range(0, len(audio), win):
            st.accept_waveform(16000, audio[i:i+win])
            while sp.is_ready(st):
                sp.decode_stream(st)
            if sp.get_result(st):
                hits.append(round(i / 16000.0, 1))
                sp.reset_stream(st)
        tag = "  <-- LIVE SETTING" if (score, thresh) == (4.0, 0.05) else ""
        print(f"score={score:<4} thresh={thresh:<5} hits={len(hits)} at {hits}{tag}")


if __name__ == "__main__":
    main()
