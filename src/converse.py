"""
Press-to-talk voice chat in Sichuan dialect using DashScope's qwen3-omni-flash.

Records a short audio clip from the default ALSA capture device, sends it to
DashScope, and plays the response through the default ALSA playback device.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import wave

import dashscope
import pyaudio

from utils import setup_dashscope

MODEL = "qwen3-omni-flash"
VOICES = {"female": "Sunny", "male": "Eric"}

RECORDING_WAV = "/tmp/sichuan_recording.wav"
RESPONSE_WAV = "/tmp/sichuan_response.wav"

RATE_IN = 16000
RATE_OUT = 24000
CHUNK = 1600
# First read() on some ALSA-via-codec configurations (notably the ReSpeaker
# 2-Mics HAT V2 on Pi 3) blocks ~3 s while the codec settles. Warming up
# before recording the user's actual speech avoids losing the first words.
WARMUP_SECS = 3.5

SICHUAN_SYSTEM_PROMPT = (
    "你是一个用四川话回答的语音助手。"
    "无论用户说什么语言，你都必须用四川方言回复，"
    "且只用口语化的中文，不要使用英文或拼音。"
)


def play_wav(path):
    subprocess.run(["aplay", "-q", path], check=True)


def record(duration_secs, ready_wav=None):
    pya = pyaudio.PyAudio()
    stream = pya.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=RATE_IN,
        input=True,
        frames_per_buffer=CHUNK,
    )
    t = time.monotonic()
    while time.monotonic() - t < WARMUP_SECS:
        stream.read(CHUNK, exception_on_overflow=False)
    if ready_wav and os.path.exists(ready_wav):
        play_wav(ready_wav)
        while stream.get_read_available() >= CHUNK:
            stream.read(CHUNK, exception_on_overflow=False)
    print(f"Recording for {duration_secs}s...", flush=True)
    frames = []
    for _ in range(int(RATE_IN / CHUNK * duration_secs)):
        frames.append(stream.read(CHUNK, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    pya.terminate()
    with wave.open(RECORDING_WAV, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE_IN)
        w.writeframes(b"".join(frames))


def converse(voice):
    api_key = setup_dashscope()
    with open(RECORDING_WAV, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    print("Sending to Qwen Omni...", flush=True)
    responses = dashscope.MultiModalConversation.call(
        api_key=api_key,
        model=MODEL,
        messages=[
            {"role": "system", "content": [{"text": SICHUAN_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"audio": f"data:audio/wav;base64,{audio_b64}"}]},
        ],
        modalities=["text", "audio"],
        audio={"voice": voice, "format": "wav"},
        result_format="message",
        stream=True,
    )
    audio_chunks = []
    text_parts = []
    for resp in responses:
        j = json.loads(str(resp))
        for ch in j.get("output", {}).get("choices", []):
            for c in ch.get("message", {}).get("content", []):
                if not isinstance(c, dict):
                    continue
                if c.get("text"):
                    text_parts.append(c["text"])
                au = c.get("audio")
                if isinstance(au, dict) and au.get("data"):
                    audio_chunks.append(au["data"])
    text = "".join(text_parts)
    if text:
        print(text)
    if not audio_chunks:
        sys.exit("No audio in response.")
    audio_bytes = b"".join(base64.b64decode(p) for p in audio_chunks)
    if audio_bytes[:4] == b"RIFF":
        with open(RESPONSE_WAV, "wb") as f:
            f.write(audio_bytes)
    else:
        # Server-streamed audio is raw PCM16 mono at RATE_OUT (24 kHz).
        with wave.open(RESPONSE_WAV, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE_OUT)
            w.writeframes(audio_bytes)
    play_wav(RESPONSE_WAV)


def main():
    parser = argparse.ArgumentParser(
        description="Press-to-talk voice chat in Sichuan dialect"
    )
    parser.add_argument(
        "-g",
        "--gender",
        default="female",
        choices=["female", "male"],
        help="Sichuan voice: female (Sunny) or male (Eric)",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=5,
        help="Recording duration in seconds (default 5)",
    )
    parser.add_argument(
        "--ready-wav",
        default=None,
        help="Optional WAV played just before recording starts",
    )
    args = parser.parse_args()
    record(args.duration, ready_wav=args.ready_wav)
    converse(VOICES[args.gender])


if __name__ == "__main__":
    main()
