#!/usr/bin/env python3
"""Tune the endpointer's noise gate on a length-stratified corpus.

    ./.venv/bin/python tools/endpoint_tune.py

The gate judges speech by the longest unbroken run of voiced frames, which is
mostly a proxy for utterance LENGTH. So a corpus of only long sentences makes
any threshold look good, and a threshold tuned on one silently eats short
questions -- measured doing exactly that on 2026-09-28, where a setting scoring
10/10 on long utterances kept 3/12 of an older short-question corpus.

Recall is therefore reported per length bucket, never pooled. A setting is only
shippable if it keeps the SHORT questions, because 现在几点 is what this device
will actually be asked.
"""
import wave, itertools
import webrtcvad
from _daemon import W

DATA = "/home/weilie/sichuan/wake_data"
BEEP_GUARD_S, WINDOW_S = 0.35, 7.0

SPEECH = [("short", ["short1", "short2", "short3"]),
          ("med",   ["med1"]),
          ("long",  ["speech1"])]
NOISE = ["nospeech1", "nospeech2", "nospeech3", "nospeech4", "nospeech5"]


def frames(path, start_s, end_s):
    w = wave.open(path)
    pcm = w.readframes(w.getnframes()); n = W.VAD_FRAME_BYTES
    lo = int(start_s * W.CONV_RATE_IN) * 2; lo -= lo % n
    hi = int(end_s * W.CONV_RATE_IN) * 2
    for i in range(lo, min(hi, len(pcm)) - n + 1, n):
        yield pcm[i:i + n]


def captures(mkvad, names):
    out = []
    for name in names:
        marks = [float(l.split()[1]) for l in open(f"{DATA}/{name}.marks") if l.strip()]
        for m in marks:
            audio, reason, st = W.endpoint(
                frames(f"{DATA}/{name}.wav", m + BEEP_GUARD_S, m + WINDOW_S),
                mkvad(), silence_timeout_s=WINDOW_S)
            out.append((len(audio) * 1000 // (W.CONV_RATE_IN * 2), st)
                       if reason == "speech" else None)
    return out


def passes(cap, run_ms, ratio):
    # The device's own gate, with the two thresholds under sweep overridden.
    return cap is not None and W.passes_gate(cap[0], cap[1], run_ms=run_ms, ratio=ratio)


def main():
    vads = [("webrtcvad", lambda: webrtcvad.Vad(W.VAD_AGGRESSIVENESS)),
            # The daemon's own shim, not a copy: what is measured is what ships.
            ("silero@0.5", lambda: W.SileroVad(0.5)),
            ("silero@0.7", lambda: W.SileroVad(0.7))]
    for label, mk in vads:
        buckets = {k: captures(mk, names) for k, names in SPEECH}
        noise = captures(mk, NOISE)
        n_short, n_med, n_long = (len(buckets["short"]), len(buckets["med"]), len(buckets["long"]))
        print(f"\n=== {label} ===")
        print(f"  opened: short {sum(c is not None for c in buckets['short'])}/{n_short}  "
              f"med {sum(c is not None for c in buckets['med'])}/{n_med}  "
              f"long {sum(c is not None for c in buckets['long'])}/{n_long}  "
              f"| noise {sum(c is not None for c in noise)}/{len(noise)}")
        print(f"  {'run_ms':>7} {'ratio':>6} | {'short':>7} {'med':>6} {'long':>6} {'ALL':>7} | {'noise thru':>10}")
        for run_ms, ratio in itertools.product([300, 400, 500, 600, 700, 900, 1200], [0.10, 0.25, 0.40]):
            s = sum(passes(c, run_ms, ratio) for c in buckets["short"])
            m = sum(passes(c, run_ms, ratio) for c in buckets["med"])
            l = sum(passes(c, run_ms, ratio) for c in buckets["long"])
            nz = sum(passes(c, run_ms, ratio) for c in noise)
            tot = s + m + l
            flag = ""
            if s >= n_short - 1 and tot >= 48 and nz <= 5:
                flag = "  <-- keeps short questions, few false wakes"
            print(f"  {run_ms:>7} {ratio:>6} | {s:>4}/{n_short} {m:>3}/{n_med} {l:>3}/{n_long} "
                  f"{tot:>4}/50 | {nz:>6}/{len(noise)}{flag}")


if __name__ == "__main__":
    main()
