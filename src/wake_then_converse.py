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
from sherpa_onnx import KeywordSpotter

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

# Sherpa-onnx KWS model + custom wake phrase
KWS_MODEL_DIR = "/home/weilie/sichuan/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KWS_KEYWORDS_FILE = "/home/weilie/sichuan/models/wake_keywords.txt"

WAKE_RATE = 16000
WAKE_CHUNK = 1600              # 100 ms @ 16 kHz

CONV_RATE_IN = 16000
CONV_CHUNK = 1600
WARMUP_SECS = 3.5

# VAD-gated recording
VAD_AGGRESSIVENESS = 2                # 0..3 (higher = more aggressive filtering)
VAD_FRAME_MS = 20                     # webrtcvad accepts 10/20/30 ms frames
VAD_FRAME_SAMPLES = CONV_RATE_IN * VAD_FRAME_MS // 1000  # 320 samples
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * 2                  # int16 mono
START_VOICED_MS = 120                 # need this much voiced audio to open an utterance
END_SILENCE_MS = 800                  # this much trailing silence closes an utterance
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
MAX_CONSECUTIVE_DEAD_TURNS = 2

VOICE = "Sunny"
MODEL = "qwen3-omni-flash"
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
)
RECORDING_WAV = "/tmp/wake_recording.wav"
RESPONSE_WAV = "/tmp/wake_response.wav"


def play_wav(path):
    if os.path.exists(path):
        subprocess.run(["aplay", "-q", path], check=False)


def make_beep(path, freq=880, secs=0.15):
    rate = 16000
    n = int(rate * secs)
    samples = [int(15000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    raw = b"".join(struct.pack("<h", s) for s in samples)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(raw)


def record_utterance(stream, vad, silence_timeout_s):
    """Read 20 ms VAD frames from an already-open input stream until one
    utterance is captured or silence_timeout_s elapses with no speech.

    Returns (raw_pcm_bytes, reason):
      reason == "speech"  → utterance captured, bytes contain int16 mono PCM
      reason == "timeout" → no speech in silence_timeout_s, bytes is b""
    """
    pre_speech_frames = max(1, PRE_SPEECH_PAD_MS // VAD_FRAME_MS)
    start_voiced_needed = max(1, START_VOICED_MS // VAD_FRAME_MS)
    end_silence_needed = max(1, END_SILENCE_MS // VAD_FRAME_MS)
    max_frames = MAX_UTTERANCE_S * 1000 // VAD_FRAME_MS
    silence_timeout_frames = int(silence_timeout_s * 1000 // VAD_FRAME_MS)

    ring = []                # rolling pre-speech buffer
    captured = []
    in_speech = False
    voiced_run = 0
    silence_run = 0
    total_frames = 0
    leading_silence = 0

    while True:
        data = stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
        # pyaudio may hand back a short buffer on shutdown; skip those.
        if len(data) != VAD_FRAME_BYTES:
            continue
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
            else:
                voiced_run = 0
                leading_silence += 1
                if leading_silence >= silence_timeout_frames:
                    return b"", "timeout"
        else:
            captured.append(data)
            total_frames += 1
            if is_speech:
                silence_run = 0
            else:
                silence_run += 1
                if silence_run >= end_silence_needed:
                    return b"".join(captured), "speech"
            if total_frames >= max_frames:
                return b"".join(captured), "speech"


def cloud_reply(audio_bytes, api_key):
    """Send one utterance to qwen3-omni-flash and play the audio reply.
    Returns True on success, False on cloud error / no audio."""
    with wave.open(RECORDING_WAV, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(CONV_RATE_IN)
        w.writeframes(audio_bytes)
    with open(RECORDING_WAV, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    print("[turn] sending to cloud...", flush=True)
    t0 = time.monotonic()
    responses = dashscope.MultiModalConversation.call(
        api_key=api_key, model=MODEL,
        messages=[
            {"role": "system", "content": [{"text": SICHUAN_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"audio": f"data:audio/wav;base64,{audio_b64}"}]},
        ],
        modalities=["text", "audio"],
        audio={"voice": VOICE, "format": "wav"},
        result_format="message", stream=True,
    )
    audio_chunks = []
    text_parts = []
    for resp in responses:
        j = json.loads(str(resp))
        status = j.get("status_code")
        if status and status != 200:
            print(f"[turn] cloud error: {status} {j.get('code')}: {j.get('message')}", flush=True)
            return False
        for ch in (j.get("output") or {}).get("choices", []) or []:
            for c in ch.get("message", {}).get("content", []):
                if not isinstance(c, dict): continue
                if c.get("text"): text_parts.append(c["text"])
                au = c.get("audio")
                if isinstance(au, dict) and au.get("data"):
                    audio_chunks.append(au["data"])
    print(f"[turn] cloud round-trip {time.monotonic()-t0:.1f} s.", flush=True)
    print("[turn] reply:", "".join(text_parts), flush=True)
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
    play_wav(RESPONSE_WAV)
    return True


def converse_session(p, api_key):
    """Multi-turn session. Listens after each reply and continues as long as
    the user keeps producing real speech. Ends on natural silence, or after
    MAX_CONSECUTIVE_DEAD_TURNS turns of noise-only input. Returns when the
    session ends; caller resumes wake-word listening."""
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    turn = 0
    dead_turns = 0
    while True:
        turn += 1
        stream = p.open(
            format=pyaudio.paInt16, channels=1, rate=CONV_RATE_IN,
            input=True, frames_per_buffer=VAD_FRAME_SAMPLES,
        )
        # Half-duplex codec just closed after playback / wake — brief re-warm.
        t = time.monotonic()
        while time.monotonic() - t < 0.4:
            stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
        # Drain any residual audio from the ack beep or the previous reply.
        while stream.get_read_available() >= VAD_FRAME_SAMPLES:
            stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)

        if dead_turns > 0:
            timeout = POST_DEAD_SILENCE_TIMEOUT_S
        elif turn == 1:
            timeout = FIRST_TURN_SILENCE_TIMEOUT_S
        else:
            timeout = FOLLOWUP_SILENCE_TIMEOUT_S
        print(f"[turn {turn}] listening (VAD; silence timeout {timeout}s)...", flush=True)
        audio_bytes, reason = record_utterance(stream, vad, timeout)
        stream.stop_stream(); stream.close()

        if reason == "timeout":
            print(f"[turn {turn}] silence — ending session.", flush=True)
            return

        utt_ms = len(audio_bytes) * 1000 // (CONV_RATE_IN * 2)
        if utt_ms < MIN_UTTERANCE_MS:
            dead_turns += 1
            print(f"[turn {turn}] {utt_ms}ms — too short, treating as noise (dead {dead_turns}/{MAX_CONSECUTIVE_DEAD_TURNS}).", flush=True)
            if dead_turns >= MAX_CONSECUTIVE_DEAD_TURNS:
                print(f"[session] {dead_turns} consecutive dead turns — ending.", flush=True)
                return
            continue

        print(f"[turn {turn}] captured {utt_ms/1000:.1f}s of speech.", flush=True)
        ok = cloud_reply(audio_bytes, api_key)
        if ok:
            dead_turns = 0
        else:
            dead_turns += 1
            print(f"[turn {turn}] cloud returned no audio (dead {dead_turns}/{MAX_CONSECUTIVE_DEAD_TURNS}).", flush=True)
            if dead_turns >= MAX_CONSECUTIVE_DEAD_TURNS:
                print(f"[session] {dead_turns} consecutive dead turns — ending.", flush=True)
                return


def build_kws():
    return KeywordSpotter(
        tokens=f"{KWS_MODEL_DIR}/tokens.txt",
        encoder=f"{KWS_MODEL_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        decoder=f"{KWS_MODEL_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        joiner=f"{KWS_MODEL_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        keywords_file=KWS_KEYWORDS_FILE,
        num_threads=1,
        max_active_paths=4,
        keywords_score=1.5,
        keywords_threshold=0.25,
        num_trailing_blanks=1,
        provider="cpu",
    )


def main():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("DASHSCOPE_API_KEY not set")

    make_beep("/tmp/ack.wav")

    print("[boot] loading sherpa-onnx KeywordSpotter (麻婆豆腐)...", flush=True)
    kws = build_kws()

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
        try:
            while True:
                data = wake_stream.read(WAKE_CHUNK, exception_on_overflow=False)
                audio_i16 = np.frombuffer(data, dtype=np.int16)
                # peak RMS for visibility
                if len(audio_i16) > 0:
                    rms = int(math.sqrt(float(np.mean(audio_i16.astype(np.int64) ** 2))))
                    if rms > peak_rms_w: peak_rms_w = rms
                # sherpa-onnx wants float32 in [-1, 1]
                audio_f32 = audio_i16.astype(np.float32) / 32768.0
                kws_stream.accept_waveform(WAKE_RATE, audio_f32)
                while kws.is_ready(kws_stream):
                    kws.decode_stream(kws_stream)
                result = kws.get_result(kws_stream)
                frames_w += 1
                if time.monotonic() - last_stats >= 5.0:
                    print(f"[wake] frames={frames_w}/5s peak_rms={peak_rms_w}", flush=True)
                    frames_w = 0; peak_rms_w = 0
                    last_stats = time.monotonic()
                if result:
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
