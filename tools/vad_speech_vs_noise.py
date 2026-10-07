#!/usr/bin/env python3
"""Score the endpointer on paired speaking / not-speaking corpora.

    ./.venv/bin/python tools/vad_speech_vs_noise.py --speech speech1 --noise nospeech1

The device's failure in real use is that it captures whatever the room does
after the user stops talking and sends it to the cloud. Diagnosing that needs
audio where nobody is speaking AT ALL -- negatives.wav turned out to be a TV
and the next room, i.e. speech, which no voicing statistic can tell from a real
question.

Both corpora are beep-paced, so each window is one turn the device would take.
Reports, per VAD:
  opened  -- endpoint() returned a capture
  through -- that capture ALSO passed the noise gate, so it reaches the cloud
Then sweeps the gate, since captures are computed once and the grid is applied
offline.
"""
import argparse, wave, itertools
import webrtcvad
from _daemon import W

DATA = "/home/weilie/sichuan/wake_data"
BEEP_GUARD_S = 0.35


def frames(path, start_s, end_s):
    w = wave.open(path)
    pcm = w.readframes(w.getnframes()); n = W.VAD_FRAME_BYTES
    lo = int(start_s * W.CONV_RATE_IN) * 2; lo -= lo % n
    hi = int(end_s * W.CONV_RATE_IN) * 2
    for i in range(lo, min(hi, len(pcm)) - n + 1, n):
        yield pcm[i:i + n]


def captures(mkvad, name, window_s):
    marks = [float(l.split()[1]) for l in open(f"{DATA}/{name}.marks") if l.strip()]
    out = []
    for m in marks:
        vad = mkvad()
        audio, reason, st = W.endpoint(
            frames(f"{DATA}/{name}.wav", m + BEEP_GUARD_S, m + window_s),
            vad, silence_timeout_s=window_s)
        out.append((len(audio) * 1000 // (W.CONV_RATE_IN * 2), st)
                   if reason == "speech" else None)
    return out


def passes(cap, min_ms, run_ms, ratio):
    if cap is None:
        return False
    utt_ms, st = cap
    return not (utt_ms < min_ms or st["longest_run_ms"] < run_ms
                or st["voiced_ratio"] < ratio)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speech", default="speech1")
    ap.add_argument("--noise", default="nospeech1")
    ap.add_argument("--window", type=float, default=7.0)
    a = ap.parse_args()

    vads = [("webrtcvad", lambda: webrtcvad.Vad(W.VAD_AGGRESSIVENESS)),
            # The daemon's own shim, not a copy: what is measured is what ships.
            ("silero@0.5", lambda: W.SileroVad(0.5)),
            ("silero@0.3", lambda: W.SileroVad(0.3)),
            ("silero@0.7", lambda: W.SileroVad(0.7))]
    store = {}
    print(f"gate as shipped: MIN_UTTERANCE_MS={W.MIN_UTTERANCE_MS} "
          f"MIN_VOICED_RUN_MS={W.MIN_VOICED_RUN_MS} MIN_VOICED_RATIO={W.MIN_VOICED_RATIO}\n")
    for label, mk in vads:
        sp = captures(mk, a.speech, a.window)
        nz = captures(mk, a.noise, a.window)
        store[label] = (sp, nz)
        g = (W.MIN_UTTERANCE_MS, W.MIN_VOICED_RUN_MS, W.MIN_VOICED_RATIO)
        print(f"{label:>11}: speech opened {sum(c is not None for c in sp)}/{len(sp)} "
              f"through {sum(passes(c,*g) for c in sp)}/{len(sp)}   |   "
              f"noise opened {sum(c is not None for c in nz)}/{len(nz)} "
              f"THROUGH {sum(passes(c,*g) for c in nz)}/{len(nz)}")

    print(f"\n--- what the gate sees, {a.noise} (not speaking) ---")
    for i, c in enumerate(store["webrtcvad"][1], 1):
        print(f"  w{i:2d}: " + ("no capture" if c is None else
              f"{c[0]/1000:5.1f}s  run {c[1]['longest_run_ms']:5d}ms  voiced {c[1]['voiced_ratio']*100:4.0f}%"))
    print(f"--- {a.speech} (speaking) ---")
    for i, c in enumerate(store["webrtcvad"][0], 1):
        print(f"  w{i:2d}: " + ("no capture" if c is None else
              f"{c[0]/1000:5.1f}s  run {c[1]['longest_run_ms']:5d}ms  voiced {c[1]['voiced_ratio']*100:4.0f}%"))

    # Truncation check. Silero's failure on the question corpus was capturing
    # a fragment, which passes every gate and still gets "I can't hear you"
    # from the cloud -- so a VAD is only better if it holds speech together.
    print("\n--- speech captured, per VAD (speech_ms = capture - preroll - end silence) ---")
    for label, _ in vads:
        sp, _ = store[label]
        ms = sorted(max(0, c[0] - W.PRE_SPEECH_PAD_MS - W.END_SILENCE_MS)
                    for c in sp if c is not None)
        print(f"{label:>11}: speech_ms min {ms[0]} median {ms[len(ms)//2]} max {ms[-1]}")

    for label, _ in vads:
        sp, nz = store[label]
        print(f"\n--- gate sweep on {label} captures ---")
        print(f"{'run_ms':>7} {'ratio':>6} | {'speech kept':>12} | {'noise through':>13}")
        for run_ms, ratio in itertools.product([300, 500, 700, 900, 1200], [0.10, 0.25, 0.40]):
            ks = sum(passes(c, W.MIN_UTTERANCE_MS, run_ms, ratio) for c in sp)
            kn = sum(passes(c, W.MIN_UTTERANCE_MS, run_ms, ratio) for c in nz)
            mark = "  <-- all speech, no noise" if ks == len(sp) and kn == 0 else ""
            print(f"{run_ms:>7} {ratio:>6} | {ks:>8}/{len(sp)}    | {kn:>7}/{len(nz)}{mark}")


if __name__ == "__main__":
    main()
