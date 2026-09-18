"""End-to-end Phase 1 prototype:
  wake-word listening (sherpa-onnx KWS, Chinese "麻婆豆腐")
  → on detection, close wake mic, play ack tone
  → open mic, VAD-gated recording, send to qwen3-omni-flash, play reply
  → loop for follow-up turns until silence timeout
  → resume wake-word listening

Single process. The HAT codec (TLV320AIC3104) is half-duplex; we
close the input stream before playing the ack tone / response, and
reopen it for the next mic phase. Same constraint chat_omni.py
works around.

Prerequisites on Pi:
  - PulseAudio must NOT hold the codec (mask pulseaudio.socket +
    pulseaudio.service) — otherwise aplay stalls ~30 s per call.
  - ~/.asoundrc routes default to plughw:2,0 (HAT card).
  - Adequate 5 V power delivery (throttled=0x0 at idle).
  - sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01 model
    extracted at MODEL_DIR (see docs/next-session.md).
  - Custom keywords file at KEYWORDS_FILE with the wake phrase(s)
    encoded as pinyin tokens.
  - `pip install webrtcvad` for end-of-speech detection.
"""
import os, sys, time, base64, json, math, struct, wave, subprocess
import numpy as np
import pyaudio
import dashscope
import webrtcvad
import queue
import threading
from sherpa_onnx import KeywordSpotter

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

# Sherpa-onnx KWS model + custom wake phrase
KWS_MODEL_DIR = "/home/weilie/sichuan/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KWS_KEYWORDS_FILE = "/home/weilie/sichuan/models/wake_keywords.txt"

WAKE_RATE = 16000
# Wake-word sensitivity. KWS_THRESHOLD/KWS_SCORE drive the real detector.
# A second "loose" spotter runs on the same audio at NEARMISS_THRESHOLD so
# an utterance that ALMOST fired gets logged instead of vanishing silently.
# sherpa-onnx exposes no per-result score, so a parallel spotter is the only
# way to see near misses. The second decode runs on its own thread — done
# inline it cost the Pi 3 40% of its frame rate (51 -> 31 frames/5s), which
# would starve the real detector. Set NEARMISS_LOGGING = False to drop it.
# Chosen by tools/sweep_kws.py over a labelled corpus (19 beep-paced
# utterances + 3 min of room audio): 17/19 recall with ZERO false alarms.
# The sweep found no false alarm anywhere in the grid, even at the most
# sensitive corner — precision is simply not the binding constraint here,
# so sensitivity is set high. Two utterances are missed at every setting;
# ASR confirms both clearly say 麻婆豆腐, so that residue is a limit of the
# KWS model, not of this tuning. Re-run the sweep before changing these.
KWS_SCORE = 4.0
# Capture gain, applied at every start. This is the highest-impact setting in
# the whole wake path: replaying the corpus at simulated gains gives 63%
# recall at the card default (~16 dB) against 89% here, and it DECLINES above
# this point (84% at +3 dB). The KWS tuning above was swept at this gain, so
# the two belong together. Addressed by card NAME — .asoundrc hardcodes card
# 2, but index ordering is not guaranteed across kernel updates.
CAPTURE_CARD = "seeed2micvoicec"
CAPTURE_PGA = 60          # 30.00 dB on this codec (range 0-119)
KWS_THRESHOLD = 0.05
# Off since the live detector was tuned to 4.0/0.05: there is no meaningfully
# looser setting left to compare against (the sweep shows 5.0/0.02 catches
# FEWER utterances, not more), so the watcher can no longer tell us anything
# and its second decode thread is pure cost. Flip back on only if the live
# tuning is loosened again.
NEARMISS_LOGGING = False
NEARMISS_SCORE = 2.5
NEARMISS_THRESHOLD = 0.10
WAKE_CHUNK = 1600              # 100 ms @ 16 kHz

CONV_RATE_IN = 16000
CONV_CHUNK = 1600
WARMUP_SECS = 3.5

# VAD-gated recording
VAD_AGGRESSIVENESS = 2                # 0..3 (higher = more aggressive filtering).
                                      # Dropped 3 -> 2 on 2026-08-29: at 3 a real
                                      # answer after the wake beep was discarded
                                      # as non-speech and the session timed out
                                      # in silence. Mic level is weak (floor
                                      # ~1700 RMS, speech only ~2600), so the
                                      # strictest setting rejects genuine speech.
                                      # 3 rejects more marginal audio so faint
                                      # bleed / echo doesn't open a fake turn.
VAD_FRAME_MS = 20                     # webrtcvad accepts 10/20/30 ms frames
VAD_FRAME_SAMPLES = CONV_RATE_IN * VAD_FRAME_MS // 1000  # 320 samples
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * 2                  # int16 mono
START_VOICED_MS = 120                 # need this much voiced audio to open an utterance
END_SILENCE_MS = 1400                 # this much trailing silence closes an utterance
                                      # 800 -> 1400 on 2026-09-19. At 800 a real
                                      # question was cut after ~300 ms: the
                                      # captures were 1.4-2.4 s, which after
                                      # subtracting pre-roll and trailing
                                      # silence is a fragment, and the cloud
                                      # answered "I can't hear you" to all of
                                      # them. On a quiet mic webrtcvad drops
                                      # frames mid-sentence, and 800 ms of those
                                      # dropouts is an ordinary pause between
                                      # words, not the end of a thought. Costs
                                      # 600 ms of latency on every turn; elderly
                                      # speakers pause more, not less.
MAX_UTTERANCE_S = 30                  # hard cap on a single utterance
PRE_SPEECH_PAD_MS = 300               # keep a ring buffer so we don't clip the onset
# A session ends when the user goes silent for these many seconds. The first
# turn allows more time (user may still be forming the question after the
# beep). After a dead turn (noise-only, see below), we tighten to a short
# window so a noisy room can't string us along.
FIRST_TURN_SILENCE_TIMEOUT_S = 8
FOLLOWUP_SILENCE_TIMEOUT_S = 6
POST_DEAD_SILENCE_TIMEOUT_S = 2.5

# Guardrails against perpetual sessions in noisy rooms.
#   - MIN_UTTERANCE_MS: anything shorter than this is treated as noise and
#     skips the cloud call entirely (cheap, purely local).
#   - MAX_CONSECUTIVE_DEAD_TURNS: after N turns in a row that either got
#     rejected locally or came back with no cloud audio, end the session.
# A real conversation runs unbounded; a room with just background noise
# burns at most MAX_CONSECUTIVE_DEAD_TURNS turns before we drop out.
MIN_UTTERANCE_MS = 400
# A capture long enough to pass MIN_UTTERANCE_MS can still be nothing but
# keyboard clicks, and that is not a harmless case: it costs two cloud calls,
# the model answers "I can't hear you", the turn counts as a SUCCESS, and the
# session stays open to do it again. Observed doing exactly that on 2026-09-19.
#
# What separates typing from talking is not energy but continuity. Speech holds
# voiced frames together in syllable-length runs; a keystroke is a 20-40 ms
# impulse. So the gate is on the longest unbroken voiced run, with the voiced
# ratio as a weaker second check. Both are deliberately loose -- the mic is
# quiet and VAD_AGGRESSIVENESS had to come down to 2 for real speech to survive
# -- and both are logged on every turn so they can be tuned from field logs
# rather than guessed at again.
# The longest unbroken voiced run is the real discriminator, and it is the one
# that is duration-independent: a keystroke is a 20-40 ms impulse no matter how
# long the capture around it runs. 300 ms blocks the keyboard turn that got
# through on 2026-09-19 (it measured 240 ms) and passes real speech comfortably.
MIN_VOICED_RUN_MS = 300
# The ratio is only a backstop against a long capture that got one lucky run.
# It was 0.35 for an hour and that was a mistake: the ratio falls as the capture
# gets LONGER, so a 7 s capture holding a perfectly good 1.5 s question scores
# 21% and was thrown away unheard -- measured doing exactly that against the
# 2026-09-19 question corpus. Judging speech by a number that shrinks the longer
# the recorder runs is unsound; keep this loose and let the run length decide.
MIN_VOICED_RATIO = 0.10
# How many previous exchanges to replay to the model so a session feels
# like one conversation instead of N unrelated questions. Each retained
# user turn re-uploads its base64 WAV (~40 KB per second of speech), so
# this trades upload time on the Pi's Wi-Fi against context depth.
MAX_HISTORY_TURNS = 3
# Two-pass cloud path. Pass 1 (research) sends the raw audio with web search
# enabled and NOTHING else — measured on this Pi, ANY system prompt or even an
# instruction in the user turn drops search_results to empty and the model
# invents a number instead (asked one city's temperature it answered 24, 30,
# 32 on consecutive tries). So pass 1 gets no instructions at all and pass 2
# carries the whole persona. max_tokens caps round 1's verbosity; it does not
# suppress search. 160, not 100: a weather answer at 100 truncated mid-number,
# and a fact round 2 cannot see is a fact it will not say.
RESEARCH_MAX_TOKENS = 160
# Round 1 gets no system prompt, so it also has no idea where the device is.
# Measured 2026-09-19: "明天天气怎么样？" returns ZERO sources and a reply asking
# which city; the same question with a location line returns 14. This is the
# single most common question this device will ever be asked, and it was
# failing every time.
#
# Note what this does NOT contradict: an INSTRUCTION in round 1's user turn
# still kills search (see above). A statement of fact does not. Context is
# safe to add here; commands are not.
#
# The date is included because "明天" is meaningless without it — without the
# date the model dated tomorrow inconsistently (周五 in one reply, 周六 in the
# next). It comes from the Pi's clock, so the Pi's timezone must match where
# the device physically sits, not where it was set up.
DEVICE_LOCATION = "四川成都"
# Round 2 is launched at the same moment as round 1, on the bet that this turn
# needs no search. See SpeculativeVoice. Set False for strictly serial rounds.
SPECULATIVE_VOICE = True
# Bound on waiting for the speculative call. 12 s, not 60: a normal turn
# completes in ~4.7 s, so anything past ~12 s is a sick stream, and 60 s of
# silence is indistinguishable from a hang to someone standing in a kitchen.
SPEC_WAIT_TIMEOUT_S = 12
# Deadlines on the two FOREGROUND cloud calls. These matter more than the one
# above: the speculative call runs on a daemon thread that can be abandoned for
# free, while these block the main loop with the mic closed and no wake word
# being heard — and the process stays alive, so systemd's Restart= never fires.
#
# Both halves are needed. request_timeout is what the DashScope SDK hands to
# requests as a PER-SOCKET-READ timeout (default 300 s), so on its own it lets
# a stream that trickles bytes block forever; the deadline check inside each
# stream loop is the actual wall-clock bound.
REQUEST_TIMEOUT_S = 10
RESEARCH_DEADLINE_S = 20
VOICE_DEADLINE_S = 30
# A search turn costs ~6 s in pass 1 alone, so say something out loud rather
# than leaving an elderly listener in silence. Non-search turns come back in
# ~1.5 s and never reach the timer.
# 3.5 s, not 2.0: the research pass takes ~2.3 s even when it does not search,
# so a 2 s timer announced "let me look that up" on every single turn — including
# 你好. Only a turn that is actually slow should get the holding phrase.
FILLER_DELAY_S = 3.5
FILLER_WAV = "/home/weilie/sichuan/checking.wav"
MAX_CONSECUTIVE_DEAD_TURNS = 2

VOICE = "Sunny"
# Round 2, the voice. 3.5 series: required for enable_search (the 3.0 models
# have no search at all), and it is the newest series that can still SPEAK —
# 3.8-Omni-Flash is text-out only.
MODEL = "qwen3.5-omni-flash"
# Round 1, the research. Split from MODEL so the two rounds can move
# independently: this pass is audio in / text out, so it does not need a model
# that can speak.
#
# qwen3.8-omni-flash was measured here on 2026-09-19 and REJECTED, despite
# fitting the shape and pricing audio input ~98% lower. Medians over 3 reps
# from the Pi, 3.8 with enable_thinking=False (its default reasoning is far
# worse still — 5.1 s and 11.7 s):
#   chat turn:   3.5 -> 1.2 s   3.8 -> 1.9 s
#   search turn: 3.5 -> 3.2 s   3.8 -> 7.0 s
# Round 1 sits on the critical path of EVERY turn now that round 2 runs
# speculatively, so +0.7 s on chat and +3.8 s on search is the whole
# speculation win given back and then some.
#
# The disqualifying result was not latency though. Fed a near-silent capture
# (a dead turn), 3.5 said the message seemed incomplete; 3.8 invented a
# question, ran 29 searches and answered confidently about UC Berkeley. A weak
# mic in an elderly household produces marginal captures constantly, and a
# model that confabulates through them is the wrong failure mode for this
# device. Revisit if a later 3.8 revision degrades more gracefully.
RESEARCH_MODEL = "qwen3.5-omni-flash"
SICHUAN_SYSTEM_PROMPT = (
    "你是一个用四川话回答的语音助手，扮演的角色像家里孝顺的孙辈，"
    "在跟长辈聊天。回答要求："
    "1. 无论用户说什么语言，都要用四川方言回复；只用口语化的中文，"
    "不要用英文或拼音。"
    "2. 语气要温暖、耐心、亲切，像跟自家爷爷奶奶讲话一样。"
    "多用四川口头禅（巴适、安逸、要得、莫慌、撒子、噻）让感觉更自然。"
    "3. 回答要简短，一般两三句话就够了，不要长篇大论。"
    "4. 用简单好懂的词，不用复杂或者技术性的词。"
    "5. 遇到医疗、健康、钱财这些严肃话题，要温柔地建议对方跟"
    "家里人或者医生商量，不要自己给判断。"
    "6. 万一听不清对方说的啥子，就温和地请他们再讲一遍，"
    "不要瞎猜。"
    "7. 有时候我会把刚刚查到的最新资料附在问题后头。只要有资料，"
    "就照资料回答，该报的数字（温度好多度、价钱好多钱）一定要报出来，"
    "用你自己的话两三句讲完，不要念资料原文，更不准说“查不到”。"
    "只有在没得资料、又问的是实时的事情时，才老实说“我这儿查不到”，"
    "喊他们看手机或者问屋头的人。任何时候都不准自己编数字。"
)
RECORDING_WAV = "/tmp/wake_recording.wav"
RESPONSE_WAV = "/tmp/wake_response.wav"


# Every aplay in this process goes through this lock. The codec is half-duplex
# and ~/.asoundrc points default at a bare plughw:2,0 with no dmix, so a second
# concurrent open returns -EBUSY and that audio is simply lost. The holding
# phrase plays from a timer thread while the main thread may be ready to play
# the reply, so "concurrent" is a real state here, not a theoretical one.
AUDIO_LOCK = threading.Lock()


def _aplay(path):
    """Unlocked playback primitive. Callers must hold AUDIO_LOCK."""
    if not os.path.exists(path):
        print(f"[audio] missing {path}", flush=True)
        return False
    r = subprocess.run(["aplay", "-q", path], capture_output=True, text=True)
    if r.returncode != 0:
        # Never silent. A reply that failed to play looks exactly like a
        # successful turn in the logs otherwise, and "it answered but we heard
        # nothing" is the most expensive thing to diagnose from 1000 km away.
        print(f"[audio] aplay failed on {path}: rc={r.returncode} "
              f"{r.stderr.strip()[:160]}", flush=True)
        return False
    return True


def play_wav(path):
    with AUDIO_LOCK:
        return _aplay(path)


def wait_for_audio_idle():
    """Block until nothing is playing. Called before opening the mic: the
    holding phrase runs on its own thread and can still be emitting when a
    turn ends, and opening input while the speaker runs is exactly what the
    half-duplex codec cannot do."""
    with AUDIO_LOCK:
        pass


class HoldingPhrase:
    """Plays "let me look that up" if the turn is still unresolved when the
    timer fires, and nothing at all once it has been cancelled.

    Timer.cancel() alone is not enough: it is a no-op once the timer has
    already fired, and by then play_wav is blocking inside aplay holding the
    codec — so the reply's own aplay collided with it, lost to -EBUSY, while
    cloud_reply went on to report the turn as a success. The flag is checked
    under AUDIO_LOCK so a cancel racing with playback resolves one way or the
    other, never into an overlap."""

    def __init__(self):
        self._cancelled = False
        self._timer = None
        if os.path.exists(FILLER_WAV):
            self._timer = threading.Timer(FILLER_DELAY_S, self._fire)
            self._timer.start()

    def _fire(self):
        with AUDIO_LOCK:
            if self._cancelled:
                return
            _aplay(FILLER_WAV)

    def cancel(self):
        self._cancelled = True
        if self._timer is not None:
            self._timer.cancel()


def make_beep(path, freq=880, secs=0.15):
    rate = 16000
    n = int(rate * secs)
    samples = [int(15000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    raw = b"".join(struct.pack("<h", s) for s in samples)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(raw)


def stream_frames(stream):
    """20 ms frames off a live pyaudio input stream, forever."""
    while True:
        data = stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
        # pyaudio may hand back a short buffer on shutdown; skip those.
        if len(data) != VAD_FRAME_BYTES:
            continue
        yield data


def record_utterance(stream, vad, silence_timeout_s):
    """Capture one utterance from a live input stream. Thin wrapper so the
    device and tools/sweep_vad.py share one endpointer -- a sweep against a
    reimplementation measures the reimplementation."""
    return endpoint(stream_frames(stream), vad, silence_timeout_s)


def endpoint(frames, vad, silence_timeout_s,
             end_silence_ms=None, start_voiced_ms=None, pre_pad_ms=None):
    """Consume 20 ms frames until one utterance is captured or
    silence_timeout_s elapses with no speech.

    The timing parameters default to the module constants; the sweep overrides
    them to measure settings other than the shipped ones.

    Returns (raw_pcm_bytes, reason, stats):
      reason == "speech"  → utterance captured, bytes contain int16 mono PCM
      reason == "timeout" → no speech in silence_timeout_s, bytes is b""
    stats carries voiced_ratio and longest_run_ms over the captured segment, so
    the caller can tell talking from typing before paying for a cloud call.
    """
    pre_speech_frames = max(1, (pre_pad_ms if pre_pad_ms is not None
                                else PRE_SPEECH_PAD_MS) // VAD_FRAME_MS)
    start_voiced_needed = max(1, (start_voiced_ms if start_voiced_ms is not None
                                  else START_VOICED_MS) // VAD_FRAME_MS)
    end_silence_needed = max(1, (end_silence_ms if end_silence_ms is not None
                                 else END_SILENCE_MS) // VAD_FRAME_MS)
    max_frames = MAX_UTTERANCE_S * 1000 // VAD_FRAME_MS
    silence_timeout_frames = int(silence_timeout_s * 1000 // VAD_FRAME_MS)

    ring = []                # rolling pre-speech buffer
    captured = []
    in_speech = False
    voiced_run = 0
    silence_run = 0
    total_frames = 0
    leading_silence = 0
    voiced_frames = 0
    cur_run = 0
    longest_run = 0

    def stats():
        return {"voiced_ratio": (voiced_frames / total_frames) if total_frames else 0.0,
                "longest_run_ms": longest_run * VAD_FRAME_MS}

    for data in frames:
        is_speech = vad.is_speech(data, CONV_RATE_IN)

        if not in_speech:
            ring.append(data)
            if len(ring) > pre_speech_frames:
                ring.pop(0)
            if is_speech:
                voiced_run += 1
                if voiced_run >= start_voiced_needed:
                    in_speech = True
                    captured.extend(ring); ring = []
                    silence_run = 0
                    total_frames = len(captured)
                    voiced_frames = voiced_run
                    cur_run = voiced_run
                    longest_run = voiced_run
            else:
                voiced_run = 0
                leading_silence += 1
                if leading_silence >= silence_timeout_frames:
                    return b"", "timeout", stats()
        else:
            captured.append(data)
            total_frames += 1
            if is_speech:
                silence_run = 0
                voiced_frames += 1
                cur_run += 1
                if cur_run > longest_run:
                    longest_run = cur_run
            else:
                cur_run = 0
                silence_run += 1
                if silence_run >= end_silence_needed:
                    return b"".join(captured), "speech", stats()
            if total_frames >= max_frames:
                return b"".join(captured), "speech", stats()
    # Offline only: the frame source ended. Live, stream_frames never stops.
    return (b"".join(captured) if in_speech else b""), \
           ("speech" if in_speech else "timeout"), stats()


def set_capture_gain():
    """Force the mic gain the wake tuning was measured at.

    ALSA mixer state does not survive a reboot unless someone ran alsactl
    store, and a hand-run command on one SD card is invisible to this repo —
    so the service sets it itself on every start. Never fatal: a speaker that
    refuses to boot is worse than one running at the wrong gain. But never
    silent either, because wrong gain presents as "it doesn't hear me
    sometimes", which is expensive to diagnose from 1000 km away."""
    try:
        r = subprocess.run(
            ["amixer", "-c", CAPTURE_CARD, "sset", "PGA", str(CAPTURE_PGA)],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"[boot] WARNING could not set capture gain on "
                  f"{CAPTURE_CARD}: {r.stderr.strip()[:200]}", flush=True)
            return
        level = next((ln.strip() for ln in r.stdout.splitlines()
                      if "Front Left: Capture" in ln), "")
        print(f"[boot] capture gain -> {level or CAPTURE_PGA}", flush=True)
    except Exception as e:
        print(f"[boot] WARNING could not set capture gain: "
              f"{type(e).__name__}: {e}", flush=True)


def ensure_filler(api_key):
    """Synthesise the 'let me look that up' holding phrase once and keep it
    on disk. Best-effort: if it fails we simply stay silent while searching."""
    if os.path.exists(FILLER_WAV):
        return
    try:
        chunks = []
        for resp in dashscope.MultiModalConversation.call(
            api_key=api_key, model=MODEL,
            messages=[{"role": "user", "content": [{"text":
                "只念这一句，不要加别的字：等哈儿，我帮你查一下哈。"}]}],
            modalities=["text", "audio"], audio={"voice": VOICE, "format": "wav"},
            result_format="message", stream=True):
            j = json.loads(str(resp))
            for ch in (j.get("output") or {}).get("choices", []) or []:
                for c in ch.get("message", {}).get("content", []):
                    if isinstance(c, dict):
                        au = c.get("audio")
                        if isinstance(au, dict) and au.get("data"):
                            chunks.append(au["data"])
        if not chunks:
            return
        raw = b"".join(base64.b64decode(c) for c in chunks)
        if raw[:4] == b"RIFF":
            with open(FILLER_WAV, "wb") as f:
                f.write(raw)
        else:
            with wave.open(FILLER_WAV, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(raw)
        print("[boot] cached holding phrase.", flush=True)
    except Exception as e:
        print(f"[boot] could not cache holding phrase: {type(e).__name__}: {e}",
              flush=True)


def research_pass(audio_b64, api_key, on_search=None):
    """Round 1: raw audio in, facts out. No system prompt, no instructions —
    see RESEARCH_MAX_TOKENS. Returns (facts_text, n_sources); facts_text is
    "" if the call failed, in which case round 2 answers unaided.

    on_search() fires the moment the stream first reports a non-empty
    search_info. That is the signal that this turn genuinely needed the web,
    and it is what lets the speculative voice call be killed early instead of
    generating audio nobody will hear."""
    t0 = time.monotonic()
    parts, n_sources = [], 0
    try:
        for resp in dashscope.MultiModalConversation.call(
            api_key=api_key, model=RESEARCH_MODEL,
            messages=[{"role": "user", "content": [
                {"audio": f"data:audio/wav;base64,{audio_b64}"},
                {"text": f"（我在{DEVICE_LOCATION}，今天是"
                         f"{time.strftime('%Y年%m月%d日')}）"}]}],
            modalities=["text"],
            enable_search=True,
            search_options={"search_strategy": "agent", "enable_source": True},
            max_tokens=RESEARCH_MAX_TOKENS,
            request_timeout=REQUEST_TIMEOUT_S,
            result_format="message", stream=True):
            if time.monotonic() - t0 > RESEARCH_DEADLINE_S:
                print(f"[research] deadline {RESEARCH_DEADLINE_S}s exceeded — "
                      f"going with what arrived ({n_sources} sources).", flush=True)
                break
            j = json.loads(str(resp))
            status = j.get("status_code")
            if status and status != 200:
                print(f"[research] cloud error: {status} {j.get('code')}", flush=True)
                return "", 0
            out = j.get("output") or {}
            hits = (out.get("search_info") or {}).get("search_results") or []
            if hits and not n_sources:
                # How early this lands decides how much speculative audio we
                # pay for on a search turn. Logged so it can be checked in
                # the field rather than assumed.
                print(f"[research] search fired at {time.monotonic()-t0:.1f}s "
                      f"({len(hits)} sources).", flush=True)
                if on_search is not None:
                    on_search()
            n_sources = max(n_sources, len(hits))
            for ch in out.get("choices", []) or []:
                for c in ch.get("message", {}).get("content", []):
                    if isinstance(c, dict) and c.get("text"):
                        parts.append(c["text"])
    except Exception as e:
        print(f"[research] failed after {time.monotonic()-t0:.1f}s: "
              f"{type(e).__name__}: {e}", flush=True)
        return "", 0
    print(f"[research] {time.monotonic()-t0:.1f}s, {n_sources} sources "
          f"({RESEARCH_MODEL}).", flush=True)
    return "".join(parts), n_sources


def voice_call(content, history, api_key, stop_event=None):
    """Round 2: one call to the voice model carrying the full persona and the
    session history. `content` is either the user's audio (answering the
    question directly) or round 1's facts as text (restyling them). Returns
    (text, audio_chunks), or None on failure or abort.

    Transient DNS / socket / TLS errors — Pi 3 Wi-Fi is flaky — would
    otherwise raise out of the streaming iterator and take the daemon down.
    Any failure here is a dead turn, which converse_session already counts."""
    t0 = time.monotonic()
    audio_chunks, text_parts = [], []
    try:
        responses = dashscope.MultiModalConversation.call(
            api_key=api_key, model=MODEL,
            messages=(
                [{"role": "system", "content": [{"text": SICHUAN_SYSTEM_PROMPT}]}]
                + history
                + [{"role": "user", "content": content}]
            ),
            modalities=["text", "audio"],
            audio={"voice": VOICE, "format": "wav"},
            request_timeout=REQUEST_TIMEOUT_S,
            result_format="message", stream=True,
        )
        for resp in responses:
            if stop_event is not None and stop_event.is_set():
                print(f"[voice] aborted at {time.monotonic()-t0:.1f}s.", flush=True)
                return None
            if time.monotonic() - t0 > VOICE_DEADLINE_S:
                print(f"[voice] deadline {VOICE_DEADLINE_S}s exceeded after "
                      f"{len(audio_chunks)} chunks — stopping.", flush=True)
                break
            j = json.loads(str(resp))
            status = j.get("status_code")
            if status and status != 200:
                print(f"[voice] cloud error: {status} {j.get('code')}: "
                      f"{j.get('message')}", flush=True)
                return None
            for ch in (j.get("output") or {}).get("choices", []) or []:
                for c in ch.get("message", {}).get("content", []):
                    if not isinstance(c, dict): continue
                    if c.get("text"): text_parts.append(c["text"])
                    au = c.get("audio")
                    if isinstance(au, dict) and au.get("data"):
                        audio_chunks.append(au["data"])
    except Exception as e:
        print(f"[voice] request failed after {time.monotonic()-t0:.1f}s: "
              f"{type(e).__name__}: {e}", flush=True)
        return None
    print(f"[voice] {time.monotonic()-t0:.1f}s, {len(audio_chunks)} chunks.",
          flush=True)
    return "".join(text_parts), audio_chunks


class SpeculativeVoice:
    """Round 2 launched in PARALLEL with round 1, betting the turn needs no
    web search — which is the common case. 你好 and 你吃了没 do not need the
    internet, and paying round 1's ~2.3 s serially before round 2 even started
    made every ordinary turn slower than it had been before search existed.

    Win (round 1 reports no sources): this call IS the answer and the turn
    costs one round-trip again. Lose: round 1's on_search fires, the stream is
    abandoned mid-flight, and the restyle path runs with no latency lost — the
    discarded call overlapped the research that beat it. The wasted audio
    tokens on a search turn buy the latency back on every other turn, and the
    early abort keeps that waste small."""

    def __init__(self, audio_b64, history, api_key):
        self.stop = threading.Event()
        self.result = None
        # History is copied, not shared: cloud_reply mutates the real list
        # once the turn resolves, and this thread may still be reading it.
        self._thread = threading.Thread(
            target=self._run, args=(audio_b64, list(history), api_key),
            daemon=True)
        self._thread.start()

    def _run(self, audio_b64, history, api_key):
        self.result = voice_call(
            [{"audio": f"data:audio/wav;base64,{audio_b64}"}],
            history, api_key, stop_event=self.stop)

    def abort(self):
        self.stop.set()

    def wait(self):
        self._thread.join(SPEC_WAIT_TIMEOUT_S)
        if self._thread.is_alive():
            print("[voice] speculative call still running after "
                  f"{SPEC_WAIT_TIMEOUT_S}s — abandoning it.", flush=True)
            self.abort()
            return None
        return self.result


def cloud_reply(audio_bytes, api_key, history):
    """One user turn. Round 1 researches while a speculative round 2 answers
    the audio directly; whichever way round 1 settles decides which reply is
    spoken. Returns True on success, False on cloud error / no audio."""
    with wave.open(RECORDING_WAV, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(CONV_RATE_IN)
        w.writeframes(audio_bytes)
    with open(RECORDING_WAV, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    t0 = time.monotonic()

    spec = (SpeculativeVoice(audio_b64, history, api_key)
            if SPECULATIVE_VOICE else None)

    # The holding phrase only reaches a turn slow enough to mean a real search
    # is happening: a speculative win cancels it first.
    holding = HoldingPhrase()
    # Whether round 1 SEARCHED, tracked separately from whether it SUCCEEDED.
    # on_search kills the speculative call irreversibly, and round 1 can still
    # fail after that point and report 0 sources — which used to send us to
    # spec.wait() on a thread guaranteed to return None, throwing away a good
    # reply and paying for a third round-trip to rediscover that.
    search_fired = threading.Event()

    def _on_search():
        search_fired.set()
        if spec is not None:
            spec.abort()

    facts, n_sources = research_pass(audio_b64, api_key, on_search=_on_search)
    holding.cancel()

    # Restyle only when round 1 both SEARCHED and produced text. Round 1
    # answers plenty of questions from its own knowledge without searching;
    # when it did not search, the speculative reply is missing nothing — and it
    # is the better answer anyway, because it heard the question itself rather
    # than a paraphrase of it.
    result = None
    if facts and (n_sources > 0 or search_fired.is_set()):
        if spec is not None:
            spec.abort()
        result = voice_call(
            [{"text": "下面是我刚才帮你查到的最新资料，是准的。"
                      "照着它用四川话回答长辈的问题，两三句话讲完，"
                      "温度、价钱这些数字一定要讲出来，不要念原文，"
                      "也不要说查不到。称呼直接用“您”，不准写成"
                      "“爷爷/奶奶”这种带杠的写法——这段话是要念出来的：\n" + facts}],
            history, api_key)
    elif spec is not None and not search_fired.is_set():
        result = spec.wait()
    elif spec is not None:
        # Search fired and then round 1 failed. The speculative stream is
        # already dead and joining it can only return None, so skip straight
        # to answering unaided rather than waiting to be told that.
        print("[turn] search fired but research failed — answering unaided.",
              flush=True)
    if result is None:
        # Nothing usable from either path — answer the audio unaided rather
        # than drop the turn. Also the path taken when SPECULATIVE_VOICE=False
        # and the turn did not search.
        result = voice_call(
            [{"audio": f"data:audio/wav;base64,{audio_b64}"}], history, api_key)
    if result is None:
        return False
    text, audio_chunks = result

    print(f"[turn] {time.monotonic()-t0:.1f}s total, {n_sources} sources.",
          flush=True)
    print("[turn] reply:", text, flush=True)
    if not audio_chunks:
        print("[turn] no audio in response.", flush=True)
        return False
    reply_bytes = b"".join(base64.b64decode(p_) for p_ in audio_chunks)
    if reply_bytes[:4] == b"RIFF":
        with open(RESPONSE_WAV, "wb") as f:
            f.write(reply_bytes)
    else:
        with wave.open(RESPONSE_WAV, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(reply_bytes)
    if not play_wav(RESPONSE_WAV):
        # The audio was generated but never reached the room. Count it as a
        # dead turn and keep it out of the history: as far as the user is
        # concerned this answer does not exist, and a session that silently
        # "remembers" something never spoken drifts from there on.
        return False
    # History carries the user's ACTUAL question as audio, never the restyle
    # instruction a search turn sends to the voice model. That blob is
    # scaffolding; storing it made turn N+1 see "把下面这段内容…" as something
    # the user had said. Only successful turns join the history, so a failed
    # call cannot leave a dangling user turn with no answer after it.
    history.append({"role": "user",
                    "content": [{"audio": f"data:audio/wav;base64,{audio_b64}"}]})
    history.append({"role": "assistant", "content": [{"text": text}]})
    del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
    return True


def converse_session(p, api_key):
    """Multi-turn session. Listens after each reply and continues as long as
    the user keeps producing real speech. Ends on natural silence, or after
    MAX_CONSECUTIVE_DEAD_TURNS turns of noise-only input. Returns when the
    session ends; caller resumes wake-word listening."""
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    # Fresh history per session: a new wake word starts a new conversation.
    history = []
    turn = 0
    dead_turns = 0
    while True:
        turn += 1
        # The holding-phrase timer fires on its own thread and can still be
        # emitting when a turn ends early (a failed call, a dead turn). Opening
        # input on a half-duplex codec while it plays either raises OSError —
        # which escapes main(), killing the daemon — or lets the device hear
        # its own voice.
        wait_for_audio_idle()
        stream = p.open(
            format=pyaudio.paInt16, channels=1, rate=CONV_RATE_IN,
            input=True, frames_per_buffer=VAD_FRAME_SAMPLES,
        )
        # Discard the first N seconds after opening the mic. aplay can
        # return before the codec buffer is fully drained, so speaker
        # audio may still be emitting for a moment; plus room echo of
        # the reply lingers a bit. 2 s covers both without cutting into
        # real user response time (silence timeout starts after this).
        t = time.monotonic()
        while time.monotonic() - t < 2.0:
            stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
        # Drain anything still queued after the warmup window.
        while stream.get_read_available() >= VAD_FRAME_SAMPLES:
            stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)

        if dead_turns > 0:
            timeout = POST_DEAD_SILENCE_TIMEOUT_S
        elif turn == 1:
            timeout = FIRST_TURN_SILENCE_TIMEOUT_S
        else:
            timeout = FOLLOWUP_SILENCE_TIMEOUT_S
        print(f"[turn {turn}] listening (VAD; silence timeout {timeout}s)...", flush=True)
        audio_bytes, reason, st = record_utterance(stream, vad, timeout)
        stream.stop_stream(); stream.close()

        if reason == "timeout":
            print(f"[turn {turn}] silence — ending session.", flush=True)
            return

        utt_ms = len(audio_bytes) * 1000 // (CONV_RATE_IN * 2)
        # Logged on every turn, including good ones, so the thresholds can be
        # tuned against what the parents' room actually produces.
        # speech_ms is what the cloud actually gets to work with: the capture
        # minus the pre-roll and the trailing silence that ended it. When this
        # is small the model hears a fragment, however healthy utt_ms looks.
        speech_ms = max(0, utt_ms - PRE_SPEECH_PAD_MS - END_SILENCE_MS)
        print(f"[turn {turn}] captured {utt_ms/1000:.1f}s "
              f"(~{speech_ms}ms speech, voiced {st['voiced_ratio']*100:.0f}%, "
              f"longest run {st['longest_run_ms']}ms).", flush=True)
        too_short = utt_ms < MIN_UTTERANCE_MS
        not_speechlike = (st["longest_run_ms"] < MIN_VOICED_RUN_MS
                          or st["voiced_ratio"] < MIN_VOICED_RATIO)
        if too_short or not_speechlike:
            dead_turns += 1
            why = "too short" if too_short else "no speech-like voicing"
            print(f"[turn {turn}] {why} — treating as noise, no cloud call "
                  f"(dead {dead_turns}/{MAX_CONSECUTIVE_DEAD_TURNS}).", flush=True)
            if dead_turns >= MAX_CONSECUTIVE_DEAD_TURNS:
                print(f"[session] {dead_turns} consecutive dead turns — ending.", flush=True)
                return
            continue
        ok = cloud_reply(audio_bytes, api_key, history)
        if ok:
            dead_turns = 0
        else:
            dead_turns += 1
            print(f"[turn {turn}] cloud returned no audio (dead {dead_turns}/{MAX_CONSECUTIVE_DEAD_TURNS}).", flush=True)
            if dead_turns >= MAX_CONSECUTIVE_DEAD_TURNS:
                print(f"[session] {dead_turns} consecutive dead turns — ending.", flush=True)
                return


class NearMissWatcher:
    """Runs a deliberately over-sensitive copy of the spotter on a worker
    thread. When it fires and the live detector did not, the phrase was
    spoken and rejected on threshold — which is the thing the logs could
    not distinguish from silence before. Diagnostic only: it never wakes
    the device. Frames are dropped rather than queued without bound, so a
    slow decode degrades this watcher and never the real detector."""

    def __init__(self):
        self.q = queue.Queue(maxsize=40)
        self.last_detection = 0.0
        self.dropped = 0
        threading.Thread(target=self._run, daemon=True).start()

    def feed(self, audio_f32, peak_rms):
        try:
            self.q.put_nowait((audio_f32, peak_rms))
        except queue.Full:
            self.dropped += 1

    def note_detection(self):
        self.last_detection = time.monotonic()

    def _run(self):
        spotter = build_kws(NEARMISS_SCORE, NEARMISS_THRESHOLD)
        stream = spotter.create_stream()
        while True:
            audio_f32, peak_rms = self.q.get()
            stream.accept_waveform(WAKE_RATE, audio_f32)
            while spotter.is_ready(stream):
                spotter.decode_stream(stream)
            if not spotter.get_result(stream):
                continue
            spotter.reset_stream(stream)
            # The live detector fires first; anything within 2 s of a real
            # wake is that same utterance, not a miss.
            if time.monotonic() - self.last_detection < 2.0:
                continue
            print(f"[wake] NEAR-MISS: heard at threshold={NEARMISS_THRESHOLD}/"
                  f"score={NEARMISS_SCORE}, rejected by live "
                  f"{KWS_THRESHOLD}/{KWS_SCORE} (peak_rms={peak_rms}, "
                  f"dropped_frames={self.dropped})", flush=True)


def build_kws(keywords_score=KWS_SCORE, keywords_threshold=KWS_THRESHOLD):
    return KeywordSpotter(
        tokens=f"{KWS_MODEL_DIR}/tokens.txt",
        encoder=f"{KWS_MODEL_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        decoder=f"{KWS_MODEL_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        joiner=f"{KWS_MODEL_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        keywords_file=KWS_KEYWORDS_FILE,
        num_threads=1,
        max_active_paths=4,
        keywords_score=keywords_score,
        keywords_threshold=keywords_threshold,
        num_trailing_blanks=1,
        provider="cpu",
    )


def main():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("DASHSCOPE_API_KEY not set")

    make_beep("/tmp/ack.wav")
    set_capture_gain()
    ensure_filler(api_key)

    print("[boot] loading sherpa-onnx KeywordSpotter (麻婆豆腐)...", flush=True)
    kws = build_kws()
    nearmiss = NearMissWatcher() if NEARMISS_LOGGING else None

    p = pyaudio.PyAudio()

    while True:
        print("[boot] opening mic for wake word + warming up...", flush=True)
        wake_stream = p.open(
            format=pyaudio.paInt16, channels=1, rate=WAKE_RATE,
            input=True, frames_per_buffer=WAKE_CHUNK,
        )
        t = time.monotonic()
        while time.monotonic() - t < WARMUP_SECS:
            wake_stream.read(WAKE_CHUNK, exception_on_overflow=False)

        kws_stream = kws.create_stream()
        print("[ready] LISTENING for 麻婆豆腐. Say the phrase to trigger a turn.", flush=True)

        # Stats every 5 s so we can confirm audio is reaching the model
        last_stats = time.monotonic()
        frames_w = 0
        peak_rms_w = 0
        clipped_w = 0
        samples_w = 0
        try:
            while True:
                data = wake_stream.read(WAKE_CHUNK, exception_on_overflow=False)
                audio_i16 = np.frombuffer(data, dtype=np.int16)
                # peak RMS for visibility
                if len(audio_i16) > 0:
                    rms = int(math.sqrt(float(np.mean(audio_i16.astype(np.int64) ** 2))))
                    if rms > peak_rms_w: peak_rms_w = rms
                    # Samples pinned near full scale mean the ADC is
                    # saturating: the waveform the model sees is a
                    # distorted version of the phrase, which is exactly
                    # how "louder makes it worse" happens.
                    clipped_w += int(np.count_nonzero(np.abs(audio_i16) > 32000))
                    samples_w += len(audio_i16)
                # sherpa-onnx wants float32 in [-1, 1]
                audio_f32 = audio_i16.astype(np.float32) / 32768.0
                kws_stream.accept_waveform(WAKE_RATE, audio_f32)
                while kws.is_ready(kws_stream):
                    kws.decode_stream(kws_stream)
                result = kws.get_result(kws_stream)
                if nearmiss is not None:
                    nearmiss.feed(audio_f32, peak_rms_w)
                frames_w += 1
                if time.monotonic() - last_stats >= 5.0:
                    clip_pct = (100.0 * clipped_w / samples_w) if samples_w else 0.0
                    print(f"[wake] frames={frames_w}/5s peak_rms={peak_rms_w} "
                          f"clipped={clip_pct:.2f}%", flush=True)
                    frames_w = 0; peak_rms_w = 0; clipped_w = 0; samples_w = 0
                    last_stats = time.monotonic()
                if result:
                    if nearmiss is not None:
                        nearmiss.note_detection()
                    print(f"\n*** WAKE detected ({result!r}) — opening session ***", flush=True)
                    # Free codec for the conversation
                    wake_stream.stop_stream(); wake_stream.close(); wake_stream = None
                    play_wav("/tmp/ack.wav")
                    converse_session(p, api_key)
                    print("[session] done. resuming wake-word listening.\n", flush=True)
                    break
        except KeyboardInterrupt:
            print("\n[exit] Ctrl+C", flush=True)
            if wake_stream is not None:
                try:
                    wake_stream.stop_stream(); wake_stream.close()
                except Exception: pass
            p.terminate()
            return
        # Loop back: reopen wake_stream and listen again


if __name__ == "__main__":
    main()
