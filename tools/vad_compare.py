#!/usr/bin/env python3
"""Compare webrtcvad against Silero VAD on the SAME endpointer logic.

    ./.venv/bin/python tools/vad_compare.py

webrtcvad labels a keystroke as voice, so the device defends itself with two
heuristic gates applied AFTER the capture (MIN_VOICED_RUN_MS, MIN_VOICED_RATIO).
Silero is a small RNN trained to reject exactly that, and sherpa-onnx -- already
a dependency for the wake word -- ships it. This replays the device's own
endpoint() with each VAD in turn, changing nothing else, so the difference
reported IS the VAD's contribution.

Two corpora, because the two failure modes are independent:
  questions (q/q2, beep-paced with marks) -- did a capture open, and how much
      speech did it hold? Misses and fragments both send the cloud nothing
      usable.
  negatives (room audio, no marks) -- how many captures SURVIVE the noise gate
      and would really reach the cloud. Each one costs two cloud calls and an
      unwanted spoken reply.
"""
import os, sys, wave
sys.path.insert(0, "/home/weilie/sichuan")
import webrtcvad
import sherpa_onnx
import wake_then_converse as W

DATA = "/home/weilie/sichuan/wake_data"
SILERO = "/home/weilie/sichuan/models/silero_vad.onnx"
WINDOW_S = 7.0        # per-beep window on the question corpora
BEEP_GUARD_S = 0.35   # skip the beep itself


class SileroVad:
    """webrtcvad-compatible shim: .is_speech(frame_bytes, rate) -> bool.

    Silero decides on 512-sample windows; the device feeds 20 ms (320-sample)
    frames. Buffer until a full window is available and hold that verdict for
    the frames in between, so the endpointer's frame grid is untouched.
    """

    def __init__(self, threshold=0.5):
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = SILERO
        cfg.silero_vad.threshold = threshold
        cfg.sample_rate = W.CONV_RATE_IN
        cfg.provider = "cpu"
        cfg.num_threads = 1
        self.model = sherpa_onnx.VadModel.create(cfg)
        self.win = self.model.window_size()
        self.buf = []
        self.last = False

    def reset(self):
        self.model.reset(); self.buf = []; self.last = False

    def is_speech(self, data, rate):
        import numpy as np
        self.buf.extend(np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0)
        while len(self.buf) >= self.win:
            chunk = self.buf[:self.win]; self.buf = self.buf[self.win:]
            self.last = bool(self.model.is_speech(chunk))
        return self.last


def frames(path, start_s=0.0, end_s=None):
    w = wave.open(path)
    assert w.getframerate() == W.CONV_RATE_IN and w.getnchannels() == 1
    pcm = w.readframes(w.getnframes()); n = W.VAD_FRAME_BYTES
    lo = int(start_s * W.CONV_RATE_IN) * 2; lo -= lo % n
    hi = len(pcm) if end_s is None else int(end_s * W.CONV_RATE_IN) * 2
    for i in range(lo, min(hi, len(pcm)) - n + 1, n):
        yield pcm[i:i + n]


def passes_gate(audio, st):
    utt_ms = len(audio) * 1000 // (W.CONV_RATE_IN * 2)
    return not (utt_ms < W.MIN_UTTERANCE_MS
                or st["longest_run_ms"] < W.MIN_VOICED_RUN_MS
                or st["voiced_ratio"] < W.MIN_VOICED_RATIO)


def questions(vad, name):
    """One independent capture per beep, as the device really works."""
    marks = [float(l.split()[1]) for l in open(f"{DATA}/{name}.marks") if l.strip()]
    rows = []
    for m in marks:
        if hasattr(vad, "reset"):
            vad.reset()
        else:
            vad = webrtcvad.Vad(W.VAD_AGGRESSIVENESS)
        audio, reason, st = W.endpoint(
            frames(f"{DATA}/{name}.wav", m + BEEP_GUARD_S, m + WINDOW_S),
            vad, silence_timeout_s=WINDOW_S)
        utt_ms = len(audio) * 1000 // (W.CONV_RATE_IN * 2)
        speech_ms = max(0, utt_ms - W.PRE_SPEECH_PAD_MS - W.END_SILENCE_MS)
        rows.append({"opened": reason == "speech", "utt_ms": utt_ms,
                     "speech_ms": speech_ms, "gate": passes_gate(audio, st) if reason == "speech" else False,
                     "run": st["longest_run_ms"], "ratio": st["voiced_ratio"]})
    return rows


def negatives(vad, name="negatives"):
    """Continuous replay; count captures that survive the gate."""
    if hasattr(vad, "reset"):
        vad.reset()
    src = frames(f"{DATA}/{name}.wav")
    total = survived = 0
    while True:
        audio, reason, st = W.endpoint(src, vad, silence_timeout_s=600.0)
        if reason != "speech" or not audio:
            break
        total += 1
        if passes_gate(audio, st):
            survived += 1
    return total, survived


def main():
    for label, mk in [("webrtcvad", lambda: webrtcvad.Vad(W.VAD_AGGRESSIVENESS)),
                      ("silero@0.5", lambda: SileroVad(0.5)),
                      ("silero@0.3", lambda: SileroVad(0.3))]:
        print(f"\n=== {label} ===")
        allrows = []
        for q in ["q", "q2"]:
            rows = questions(mk(), q)
            allrows += rows
            op = sum(r["opened"] for r in rows); gt = sum(r["gate"] for r in rows)
            sp = [r["speech_ms"] for r in rows if r["opened"]]
            print(f"  {q}: opened {op}/{len(rows)}  passed gate {gt}/{len(rows)}  "
                  f"speech_ms median {sorted(sp)[len(sp)//2] if sp else 0}")
        runs = [r["run"] for r in allrows if r["opened"]]
        print(f"  questions overall: {sum(r['gate'] for r in allrows)}/{len(allrows)} usable, "
              f"longest_run median {sorted(runs)[len(runs)//2] if runs else 0}ms, "
              f"voiced_ratio median {sorted(r['ratio'] for r in allrows)[len(allrows)//2]*100:.0f}%")
        tot, surv = negatives(mk())
        print(f"  negatives (180s room audio): {tot} captures, {surv} SURVIVE the gate")


if __name__ == "__main__":
    main()
