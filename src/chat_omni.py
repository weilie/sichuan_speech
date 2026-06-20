"""
Real-time Voice-to-Voice chat script using Alibaba DashScope's
Qwen3-Omni-Flash-Realtime.

Architecture: half-duplex. The ReSpeaker 2-Mics Pi HAT V2 codec
(TLV320AIC3104) does not let ALSA hold the mic open while PyAudio
plays sound; output is silenced even via aplay or PulseAudio. So the
mic is paused via `stream_in.stop_stream()` when the bot starts
replying and resumed when the response is done. The first ~4 seconds
after resume are discarded (codec re-warm-up). Barge-in is not
supported on this hardware; the realtime API is used only for its
lower latency-to-first-audio and free server-side VAD.
"""
import os
import sys
import time
import base64
import argparse
import threading
import pyaudio
import dashscope
from dashscope.audio.qwen_omni import (
    OmniRealtimeConversation,
    OmniRealtimeCallback,
    MultiModality,
    AudioFormat,
)

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
MODEL = "qwen3-omni-flash-realtime"

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE_IN = 16000   # mic rate
RATE_OUT = 24000  # response rate from the model
CHUNK = 1600      # 100 ms at 16 kHz
WARMUP_SECS = 3.5         # initial codec warm-up
RESUME_DISCARD_SECS = 4.5  # silence after mic resume; codec re-warms


class VoiceBotCallback(OmniRealtimeCallback):
    """Receives server events. Coordinates with the mic loop via
    `mic_paused` and `discard_until` shared state."""

    def __init__(self):
        super().__init__()
        self.pya = pyaudio.PyAudio()
        self.stream_in = None       # set by run_chat before connect()
        self.stream_out = None      # opened lazily on first audio chunk
        self.mic_paused = False
        self.discard_until = 0.0
        self._state_lock = threading.Lock()

    def _ensure_stream_out(self):
        if self.stream_out is None:
            # Larger frames_per_buffer (~400 ms) absorbs WebSocket jitter so
            # the playback doesn't underrun and glitch between audio chunks.
            self.stream_out = self.pya.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=RATE_OUT,
                output=True,
                frames_per_buffer=RATE_OUT * 4 // 10,
            )

    def _pause_mic(self):
        # Close the mic completely. stop_stream/start_stream on this codec
        # leaves the device in an unrecoverable state.
        with self._state_lock:
            if self.stream_in is None or self.mic_paused:
                return
            self.mic_paused = True
            try:
                self.stream_in.stop_stream()
                self.stream_in.close()
            except Exception as e:
                print(f"\n[!] close stream_in: {e}", flush=True)
            self.stream_in = None

    def _resume_mic(self):
        with self._state_lock:
            if not self.mic_paused:
                return
            if self.stream_out is not None:
                try:
                    self.stream_out.stop_stream()
                    self.stream_out.close()
                except Exception as e:
                    print(f"\n[!] close stream_out: {e}", flush=True)
                self.stream_out = None
            try:
                self.stream_in = self.pya.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE_IN,
                    input=True,
                    frames_per_buffer=CHUNK,
                )
            except Exception as e:
                print(f"\n[!] reopen stream_in: {e}", flush=True)
            self.discard_until = time.monotonic() + RESUME_DISCARD_SECS
            self.mic_paused = False

    def on_open(self):
        print("\n[Bot is listening... Start speaking! Press Ctrl+C to stop]")

    def on_close(self, close_status_code=None, close_msg=None):
        print(f"\n[Connection Closed] code={close_status_code} msg={close_msg}")
        if self.stream_out is not None:
            try:
                self.stream_out.stop_stream()
                self.stream_out.close()
            except Exception:
                pass
        try:
            self.pya.terminate()
        except Exception:
            pass

    def on_error(self, error):
        print(f"\n[Error]: {error}", flush=True)

    def on_event(self, event):
        et = event.get("type", "")
        if et == "input_audio_buffer.speech_stopped":
            # Server detected end of user speech. Pause mic now so the
            # codec is free for the incoming response audio.
            self._pause_mic()
        elif et == "response.audio_transcript.delta":
            print(event.get("delta", ""), end="", flush=True)
        elif et == "response.audio_transcript.done":
            print()
        elif et == "response.audio.delta":
            delta = event.get("delta")
            if delta:
                self._ensure_stream_out()
                self.stream_out.write(base64.b64decode(delta))
        elif et == "response.done":
            # Bot finished. Resume mic; main loop will discard the
            # first few seconds of codec re-warm-up audio.
            self._resume_mic()


def run_chat(gender):
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("Error: DASHSCOPE_API_KEY environment variable not set.")
    dashscope.api_key = api_key

    voice = {"female": "Sunny", "male": "Eric"}.get(gender, "Sunny")
    print(f"Initializing Real-time Voice Chat...")
    print(f"Using Sichuan voice: {voice} ({gender})")

    callback = VoiceBotCallback()

    # Play the "ready" cue BEFORE we open the mic, so the cue doesn't
    # feed back into the input stream and trip the server VAD.
    import subprocess
    if os.path.exists("/tmp/ready.wav"):
        subprocess.run(["aplay", "-q", "/tmp/ready.wav"], check=False)

    # Open mic and warm it up BEFORE opening the WebSocket. The codec's
    # first read() blocks ~3 s; the server would idle-close the session
    # if we paid that cost between session.updated and our first audio.
    p = pyaudio.PyAudio()
    stream_in = p.open(
        format=FORMAT, channels=CHANNELS, rate=RATE_IN,
        input=True, frames_per_buffer=CHUNK,
    )
    print("Warming up mic (~3.5 s)...", flush=True)
    t = time.monotonic()
    while time.monotonic() - t < WARMUP_SECS:
        stream_in.read(CHUNK, exception_on_overflow=False)
    callback.stream_in = stream_in

    conv = OmniRealtimeConversation(model=MODEL, url=URL, callback=callback)

    try:
        conv.connect()
        conv.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=voice,
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        )

        while True:
            stream_in = callback.stream_in  # snapshot — callback may swap it
            if callback.mic_paused or stream_in is None:
                # Bot is speaking; mic stream has been closed.
                time.sleep(0.05)
                continue
            try:
                data = stream_in.read(CHUNK, exception_on_overflow=False)
            except (IOError, OSError):
                time.sleep(0.05)
                continue
            if time.monotonic() < callback.discard_until:
                # Codec re-warm-up window after mic resume; drop frames.
                continue
            try:
                conv.append_audio(base64.b64encode(data).decode("ascii"))
            except Exception as e:
                print(f"\n[SEND_FAILED] {type(e).__name__}: {e}", flush=True)
                break

    except KeyboardInterrupt:
        print("\nStopping chat...")
    finally:
        try:
            conv.close()
        except Exception:
            pass
        if callback.stream_in is not None:
            try:
                callback.stream_in.stop_stream(); callback.stream_in.close()
            except Exception:
                pass
        try:
            p.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Real-time Voice-to-Voice Chat in Sichuan dialect"
    )
    parser.add_argument(
        "-g", "--gender", default="female", choices=["female", "male"],
        help="Sichuan voice gender: female (Sunny) or male (Eric)"
    )
    args = parser.parse_args()
    run_chat(args.gender)
