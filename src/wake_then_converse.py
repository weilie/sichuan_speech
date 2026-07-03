"""End-to-end Phase 1 prototype:
  wake-word listening (openWakeWord)
  → on detection, close wake mic, play ack tone
  → open mic, record 5 s, send to qwen3-omni-flash, play response
  → resume wake word

Single process. The HAT codec (TLV320AIC3104) is half-duplex; we
close the input stream before playing the ack tone / response, and
reopen it for the next mic phase. Same constraint chat_omni.py
works around.

Prerequisites on Pi:
  - PulseAudio must NOT hold the codec (mask pulseaudio.socket +
    pulseaudio.service) — otherwise aplay stalls ~30 s per call.
  - ~/.asoundrc routes default to plughw:2,0 (HAT card).
  - Adequate 5 V power delivery (throttled=0x0 at idle).

Pi 3 v1.2 validated 2026-07-02: RSS ~267 MB, CPU ~55 % on one
core, wake→beep 0.34 s, full turn ~15 s (5 s record + 10 s cloud).
"""
import os, sys, time, base64, json, math, struct, wave, subprocess
import threading
import numpy as np
import pyaudio
import openwakeword
from openwakeword.model import Model
import dashscope

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

WAKE_RATE = 16000
WAKE_CHUNK = 1280              # openWakeWord wants 80 ms @ 16 kHz
DETECTION_THRESHOLD = 0.5

CONV_RATE_IN = 16000
CONV_CHUNK = 1600              # converse.py uses 100 ms chunks
RECORD_SECONDS = 5
WARMUP_SECS = 3.5

VOICE = "Sunny"
MODEL = "qwen3-omni-flash"
SICHUAN_SYSTEM_PROMPT = (
    "你是一个用四川话回答的语音助手。"
    "无论用户说什么语言，你都必须用四川方言回复，"
    "且只用口语化的中文，不要使用英文或拼音。"
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


def converse_turn(p, api_key):
    """Open mic, record one turn, send to cloud, play reply.
    Returns when done. Reopens mic; caller resumes wake-word loop."""
    stream = p.open(
        format=pyaudio.paInt16, channels=1, rate=CONV_RATE_IN,
        input=True, frames_per_buffer=CONV_CHUNK,
    )
    # Codec just closed after wake detection — brief re-warm only
    t = time.monotonic()
    while time.monotonic() - t < 0.4:
        stream.read(CONV_CHUNK, exception_on_overflow=False)
    # Drain leftover audio from the ack beep
    while stream.get_read_available() >= CONV_CHUNK:
        stream.read(CONV_CHUNK, exception_on_overflow=False)

    print(f"[turn] recording {RECORD_SECONDS} s...", flush=True)
    frames = []
    for _ in range(int(CONV_RATE_IN / CONV_CHUNK * RECORD_SECONDS)):
        frames.append(stream.read(CONV_CHUNK, exception_on_overflow=False))
    stream.stop_stream(); stream.close()

    with wave.open(RECORDING_WAV, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(CONV_RATE_IN)
        w.writeframes(b"".join(frames))

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
        return
    audio_bytes = b"".join(base64.b64decode(p_) for p_ in audio_chunks)
    if audio_bytes[:4] == b"RIFF":
        with open(RESPONSE_WAV, "wb") as f:
            f.write(audio_bytes)
    else:
        with wave.open(RESPONSE_WAV, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(audio_bytes)
    play_wav(RESPONSE_WAV)


def main():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("DASHSCOPE_API_KEY not set")

    make_beep("/tmp/ack.wav")

    print("[boot] loading openWakeWord (hey_jarvis)...", flush=True)
    oww = Model(wakeword_model_paths=[openwakeword.models["hey_jarvis"]["model_path"]])

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
        print("[ready] LISTENING for 'hey jarvis'. Speak the phrase to trigger a turn.", flush=True)

        # Stats every 5 s so we can confirm audio is reaching the model
        last_stats = time.monotonic()
        frames_w = 0
        peak_score_w = 0.0
        peak_rms_w = 0
        try:
            while True:
                data = wake_stream.read(WAKE_CHUNK, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.int16)
                # peak RMS for visibility
                if len(audio) > 0:
                    rms = int(math.sqrt(float(np.mean(audio.astype(np.int64) ** 2))))
                    if rms > peak_rms_w: peak_rms_w = rms
                scores = oww.predict(audio)
                fired = max(scores.values()) if scores else 0.0
                if fired > peak_score_w: peak_score_w = fired
                frames_w += 1
                if time.monotonic() - last_stats >= 5.0:
                    print(f"[wake] frames={frames_w}/5s peak_score={peak_score_w:.2f} peak_rms={peak_rms_w}", flush=True)
                    frames_w = 0; peak_score_w = 0.0; peak_rms_w = 0
                    last_stats = time.monotonic()
                if fired >= DETECTION_THRESHOLD:
                    print(f"\n*** WAKE WORD detected (score={fired:.2f}) — opening turn ***", flush=True)
                    # Free codec for the conversation
                    wake_stream.stop_stream(); wake_stream.close(); wake_stream = None
                    oww.reset()
                    play_wav("/tmp/ack.wav")
                    converse_turn(p, api_key)
                    print("[turn] done. resuming wake-word listening.\n", flush=True)
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
