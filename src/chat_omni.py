"""
Real-time Voice-to-Voice chat script using Alibaba DashScope's Qwen3-Omni-Flash-Realtime.
Supports full-duplex Sichuan-dialect conversations.
"""
import os
import sys
import time
import base64
import argparse
import pyaudio
import dashscope
from dashscope.audio.qwen_omni import (
    OmniRealtimeConversation,
    OmniRealtimeCallback,
    MultiModality,
    AudioFormat,
)

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
URL = 'wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime'
MODEL = 'qwen3-omni-flash-realtime'

# Audio parameters for Qwen3-Omni
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE_IN = 16000  # Input rate for mic
RATE_OUT = 24000 # Output rate from model
CHUNK = 1600     # 100ms chunks at 16kHz

class VoiceBotCallback(OmniRealtimeCallback):
    """Handles real-time events from the model."""
    # Mic stays muted for this long after the last assistant audio chunk,
    # to let the speaker tail finish before we resume listening.
    MIC_UNMUTE_DELAY = 0.4

    def __init__(self):
        super().__init__()
        self.pya = pyaudio.PyAudio()
        self.stream_out = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE_OUT,
            output=True
        )
        self.assistant_speaking_until = 0.0

    def mic_muted(self) -> bool:
        return time.monotonic() < self.assistant_speaking_until

    def on_open(self):
        print("\n[Bot is listening... Start speaking! Press Ctrl+C to stop]")

    def on_close(self, close_status_code=None, close_msg=None):
        print("\n[Connection Closed]")
        self.stream_out.stop_stream()
        self.stream_out.close()
        self.pya.terminate()

    def on_event(self, event):
        event_type = event.get('type', '')

        if event_type == 'response.audio_transcript.delta':
            print(event.get('delta', ''), end='', flush=True)
        elif event_type == 'response.audio_transcript.done':
            print("\n")
        elif event_type == 'response.audio.delta':
            delta = event.get('delta')
            if delta:
                self.stream_out.write(base64.b64decode(delta))
                self.assistant_speaking_until = (
                    time.monotonic() + self.MIC_UNMUTE_DELAY
                )

    def on_error(self, error):
        print(f"\n[Error]: {error}")

def run_chat(gender):
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("Error: DASHSCOPE_API_KEY environment variable not set.")
    
    dashscope.api_key = api_key

    # Map gender to specific Sichuan voices
    voice_map = {"female": "Sunny", "male": "Eric"}
    voice = voice_map.get(gender, "Sunny")
    
    print(f"Initializing Real-time Voice Chat...")
    print(f"Using Sichuan voice: {voice} ({gender})")
    
    callback = VoiceBotCallback()
    
    conv = OmniRealtimeConversation(
        model=MODEL,
        url=URL,
        callback=callback,
    )

    try:
        conv.connect()
        conv.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=voice,
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            output_audio_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        )

        # Initialize Microphone
        p = pyaudio.PyAudio()
        stream_in = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE_IN,
            input=True,
            frames_per_buffer=CHUNK
        )

        # Continuous loop to read mic and send to WebSocket
        while True:
            data = stream_in.read(CHUNK, exception_on_overflow=False)
            if callback.mic_muted():
                continue
            conv.append_audio(base64.b64encode(data).decode("ascii"))

    except KeyboardInterrupt:
        print("\nStopping chat...")
    finally:
        conv.close()
        if 'stream_in' in locals():
            stream_in.stop_stream()
            stream_in.close()
        if 'p' in locals():
            p.terminate()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Real-time Voice-to-Voice Chat in Sichuan dialect")
    parser.add_argument("-g", "--gender", default="female", choices=["female", "male"], 
                        help="Sichuan voice gender: female (Sunny) or male (Eric)")
    args = parser.parse_args()
    
    run_chat(args.gender)
