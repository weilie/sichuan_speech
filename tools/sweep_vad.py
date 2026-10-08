#!/usr/bin/env python3
"""Measure the utterance endpointer: recall, truncation, and false accepts.

    python3 tools/sweep_vad.py --positives wake_data/q.wav --marks wake_data/q.marks \
                               --phrase 明天天气怎么样 --negatives wake_data/negatives.wav

Companion to sweep_kws.py, which measures the WAKE detector. This measures
what happens after the beep: does the capture contain the whole question, or
a fragment the cloud cannot answer?

Three numbers per setting, because they fail independently:

  recall     — utterances that produced a capture at all. Misses here mean the
               VAD never opened; the user said something and nothing was sent.
  complete   — captures whose transcript contains the whole phrase. This is the
               one that matters. A capture can be 100% recalled and still be a
               truncated fragment, which is exactly the 2026-09-19 bug: 1.4 s
               captures of a 1.5 s question, every one of them answered with
               "I can't hear you".
  false      — captures from the negatives file (room noise, typing) that
               SURVIVE the device's noise gate, i.e. that would really reach
               the cloud. Each one costs two cloud calls and an unwanted spoken
               reply. Counting raw captures instead overstates this badly: the
               gate exists precisely to throw most of them away.

Completeness is scored by ASR because no local proxy is trustworthy at this
SNR: energy-based endpoint detection is the very thing under test, so using it
as ground truth would be circular. Pass --no-asr for a quick structural run
that reports recall and false accepts only.

Replays the DEVICE's endpointer (wake_then_converse.endpoint), not a copy,
with the DEVICE's VAD: Silero at the shipped threshold by default. Pass
--vad webrtcvad to measure the fallback engine instead. The false-accept
column is only comparable between runs at the same --end-silence.
"""
import argparse, json, os, sys, wave, base64, io as _io

from _daemon import W


def wav_frames(path, start_s=0.0, end_s=None):
    w = wave.open(path)
    assert w.getframerate() == W.CONV_RATE_IN and w.getnchannels() == 1
    pcm = w.readframes(w.getnframes())
    n = W.VAD_FRAME_BYTES
    lo = int(start_s * W.CONV_RATE_IN) * 2
    hi = len(pcm) if end_s is None else int(end_s * W.CONV_RATE_IN) * 2
    lo -= lo % n
    for i in range(lo, min(hi, len(pcm)) - n + 1, n):
        yield pcm[i:i + n]


def capture_per_beep(path, marks, mkvad, end_silence_ms, window, beep_guard):
    """One independent capture per beep, which is how the DEVICE works: each
    turn opens the mic, takes one utterance and closes it.

    Replaying the corpus as one continuous stream instead let a single capture
    run across several beeps whenever the VAD never found enough quiet between
    them -- three utterances merged into one 11.9 s blob on the 7 s corpus.
    That is an artifact of continuous replay, not something the device can do,
    and it silently inflated completeness by crediting a window with its
    neighbour's words. Restarting at each beep removes it.

    The guard skips the beep tone itself: the corpus records it, the device
    never hears it (mic opens after playback, then discards 0.5 s), and being a
    loud tone the VAD calls it voice -- so it both fakes a capture and keeps
    the silence counter from ever advancing.
    """
    out = []
    vad = mkvad()
    for m in marks:
        # As the device does between turns: one model, reset() per capture.
        # (webrtcvad has no reset and the device reuses it across turns too.)
        if hasattr(vad, "reset"):
            vad.reset()
        frames = wav_frames(path, m + beep_guard, m + window)
        audio, reason, st = W.endpoint(frames, vad, window,
                                       end_silence_ms=end_silence_ms)
        if reason != "speech" or not audio:
            out.append(None)
            continue
        out.append({"audio": audio, "stats": st,
                    "dur_s": len(audio) / (W.CONV_RATE_IN * 2),
                    "gated": not passes_gate(audio, st)})
    return out


def passes_gate(audio, st):
    """The device's own gate (wake_then_converse.passes_gate), not a copy."""
    return W.passes_gate(len(audio) * 1000 // (W.CONV_RATE_IN * 2), st)


def captures(path, mkvad, end_silence_ms, silence_timeout_s=600.0):
    """Every utterance the endpointer would produce over a whole file, with
    the frame index each one started at."""
    vad = mkvad()
    frames = wav_frames(path)
    out = []
    consumed = [0]

    def counting():
        for f in frames:
            consumed[0] += 1
            yield f

    src = counting()
    while True:
        before = consumed[0]
        # Each capture stands for one device turn, so reset the VAD as the
        # device does: no state carries from one capture into the next.
        if hasattr(vad, "reset"):
            vad.reset()
        audio, reason, st = W.endpoint(src, vad, silence_timeout_s,
                                       end_silence_ms=end_silence_ms)
        if reason != "speech" or not audio:
            return out
        dur_frames = len(audio) // W.VAD_FRAME_BYTES
        end_s = consumed[0] * W.VAD_FRAME_MS / 1000.0
        out.append({"start_s": max(0.0, end_s - dur_frames * W.VAD_FRAME_MS / 1000.0),
                    "end_s": end_s, "audio": audio, "stats": st,
                    "gated": not passes_gate(audio, st)})
        if consumed[0] == before:
            return out


def transcribe(audio, api_key):
    import dashscope
    dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
    b = _io.BytesIO()
    with wave.open(b, "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(W.CONV_RATE_IN)
        o.writeframes(audio)
    b64 = base64.b64encode(b.getvalue()).decode()
    txt = []
    for r in dashscope.MultiModalConversation.call(
            api_key=api_key, model=W.MODEL,
            messages=[{"role": "user", "content": [
                {"audio": f"data:audio/wav;base64,{b64}"},
                {"text": "逐字写出这段音频里说的话，只输出原话，不要加任何解释。"}]}],
            modalities=["text"], max_tokens=60, request_timeout=30,
            result_format="message", stream=True):
        j = json.loads(str(r))
        if (j.get("status_code") or 200) != 200:
            return ""
        for c_ in (j.get("output") or {}).get("choices", []) or []:
            for c in c_.get("message", {}).get("content", []):
                if isinstance(c, dict) and c.get("text"):
                    txt.append(c["text"])
    return "".join(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positives", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--phrase", required=True,
                    help="the phrase spoken after each beep, for scoring completeness")
    ap.add_argument("--negatives")
    ap.add_argument("--window", type=float, default=6.0,
                    help="seconds after a beep that belong to that utterance")
    ap.add_argument("--beep-guard", type=float, default=0.5,
                    help="ignore captures that are only the beep itself. The "
                         "corpus records the beep; the device never hears it, "
                         "because the mic opens after playback and discards "
                         "0.5 s. Without this the beep IS the first capture in "
                         "every window and the real utterance looks missed.")
    ap.add_argument("--vad", choices=["silero", "webrtcvad"], default="silero",
                    help="engine to replay: the shipped Silero (default) or "
                         "the webrtcvad fallback")
    ap.add_argument("--silero-threshold", default=str(W.SILERO_VAD_THRESHOLD),
                    help="comma-separated Silero thresholds to try (silero only)")
    ap.add_argument("--aggressiveness", default=str(W.VAD_AGGRESSIVENESS),
                    help="comma-separated webrtcvad levels to try (webrtcvad only)")
    ap.add_argument("--end-silence", default="800,1400,2000",
                    help="comma-separated END_SILENCE_MS values to try")
    ap.add_argument("--no-asr", action="store_true")
    a = ap.parse_args()

    marks = [float(l.split()[1]) for l in open(a.marks) if l.strip()]
    api_key = (os.environ.get("SICHUAN_DASHSCOPE_API_KEY")
               or os.environ.get("DASHSCOPE_API_KEY", ""))
    if not a.no_asr and not api_key:
        sys.exit("neither SICHUAN_DASHSCOPE_API_KEY nor DASHSCOPE_API_KEY is "
                 "set (or pass --no-asr)")
    # One VAD factory per setting, labelled for the table.
    if a.vad == "silero":
        settings = [(f"th{t:g}", lambda t=t: W.SileroVad(t))
                    for t in (float(x) for x in a.silero_threshold.split(","))]
    else:
        import webrtcvad
        settings = [(f"agg{g}", lambda g=g: webrtcvad.Vad(g))
                    for g in (int(x) for x in a.aggressiveness.split(","))]
    # Score each distinct capture once even when settings agree on it.
    seen = {}
    print(f"{len(marks)} utterances, phrase {a.phrase!r}, engine {a.vad}\n")
    print(f"{'vad':>6} {'end_ms':>7} {'recall':>9} {'complete':>10} {'false':>6}  missed")
    for label, mkvad in settings:
        for end_ms in [int(x) for x in a.end_silence.split(",")]:
            caps = capture_per_beep(a.positives, marks, mkvad, end_ms,
                                    a.window, a.beep_guard)
            hit, complete, missed = 0, 0, []
            for i, c in enumerate(caps, 1):
                if c is None or c["gated"]:
                    missed.append(i)
                    continue
                hit += 1
                if a.no_asr:
                    continue
                k = (label, end_ms, i)
                if k not in seen:
                    seen[k] = transcribe(c["audio"], api_key)
                if a.phrase in seen[k].replace(" ", ""):
                    complete += 1
            nfalse = (len([c for c in captures(a.negatives, mkvad, end_ms)
                           if not c["gated"]]) if a.negatives else -1)
            comp = "n/a" if a.no_asr else f"{complete}/{len(marks)}"
            fa = "n/a" if nfalse < 0 else str(nfalse)
            print(f"{label:>6} {end_ms:>7} {hit:>4}/{len(marks):<4} {comp:>10} {fa:>6}  "
                  f"{missed if missed else ''}")


if __name__ == "__main__":
    main()
