#!/usr/bin/env python3
"""Sweep the post-capture noise gate against questions AND room audio.

The gate (MIN_UTTERANCE_MS / MIN_VOICED_RUN_MS / MIN_VOICED_RATIO) is what
stands between a keystroke and a cloud call. tools/vad_compare.py showed that
at the shipped thresholds it rejects NONE of the 9 captures that 180 s of room
audio produces -- so every one of them reaches the cloud and earns an unwanted
spoken reply.

Captures are computed once per VAD and the gate is then applied offline, so
the whole grid costs one replay rather than one per cell. Questions bound how
tight the gate can go: a setting that blocks all the noise and half the
questions is worse than useless.
"""
import sys, wave, itertools
sys.path.insert(0, "/home/weilie/sichuan")
import webrtcvad
import wake_then_converse as W

DATA = "/home/weilie/sichuan/wake_data"
WINDOW_S, BEEP_GUARD_S = 7.0, 0.35


def frames(path, start_s=0.0, end_s=None):
    w = wave.open(path)
    pcm = w.readframes(w.getnframes()); n = W.VAD_FRAME_BYTES
    lo = int(start_s * W.CONV_RATE_IN) * 2; lo -= lo % n
    hi = len(pcm) if end_s is None else int(end_s * W.CONV_RATE_IN) * 2
    for i in range(lo, min(hi, len(pcm)) - n + 1, n):
        yield pcm[i:i + n]


def collect():
    """Every capture the device would make, with the stats the gate judges."""
    qs, ns = [], []
    for name in ["q", "q2"]:
        marks = [float(l.split()[1]) for l in open(f"{DATA}/{name}.marks") if l.strip()]
        for m in marks:
            vad = webrtcvad.Vad(W.VAD_AGGRESSIVENESS)
            audio, reason, st = W.endpoint(
                frames(f"{DATA}/{name}.wav", m + BEEP_GUARD_S, m + WINDOW_S),
                vad, silence_timeout_s=WINDOW_S)
            if reason == "speech":
                qs.append((len(audio) * 1000 // (W.CONV_RATE_IN * 2), st))
            else:
                qs.append(None)
    vad = webrtcvad.Vad(W.VAD_AGGRESSIVENESS)
    src = frames(f"{DATA}/negatives.wav")
    while True:
        audio, reason, st = W.endpoint(src, vad, silence_timeout_s=600.0)
        if reason != "speech" or not audio:
            break
        ns.append((len(audio) * 1000 // (W.CONV_RATE_IN * 2), st))
    return qs, ns


def passes(cap, min_ms, run_ms, ratio):
    if cap is None:
        return False
    utt_ms, st = cap
    return not (utt_ms < min_ms or st["longest_run_ms"] < run_ms
                or st["voiced_ratio"] < ratio)


def main():
    qs, ns = collect()
    print(f"corpus: {sum(q is not None for q in qs)}/{len(qs)} questions captured, "
          f"{len(ns)} noise captures from 180s of room audio\n")
    print("  the 9 noise captures, as the gate sees them:")
    for utt_ms, st in ns:
        print(f"    {utt_ms/1000:5.1f}s  longest_run {st['longest_run_ms']:5d}ms  "
              f"voiced {st['voiced_ratio']*100:4.0f}%")
    print()
    print(f"{'min_ms':>7} {'run_ms':>7} {'ratio':>6} | {'questions kept':>15} | {'noise through':>13}")
    best = []
    for min_ms, run_ms, ratio in itertools.product(
            [400], [300, 400, 500, 600, 700, 800, 1000], [0.10, 0.20, 0.30, 0.40]):
        kq = sum(passes(c, min_ms, run_ms, ratio) for c in qs)
        kn = sum(passes(c, min_ms, run_ms, ratio) for c in ns)
        flag = ""
        if kq >= 22 and kn <= 2:
            flag = "  <-- keeps all questions, kills most noise"
        print(f"{min_ms:>7} {run_ms:>7} {ratio:>6} | {kq:>10}/{len(qs)}    | {kn:>7}/{len(ns)}{flag}")
        best.append((kq, -kn, min_ms, run_ms, ratio))
    best.sort(reverse=True)
    print("\nbest by questions kept, then least noise through:")
    for kq, nkn, a, b, c in best[:6]:
        print(f"  questions {kq}/{len(qs)}  noise {-nkn}/{len(ns)}   "
              f"MIN_UTTERANCE_MS={a} MIN_VOICED_RUN_MS={b} MIN_VOICED_RATIO={c}")


if __name__ == "__main__":
    main()
