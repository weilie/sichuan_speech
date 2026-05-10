"""
Real-time Voice-to-Voice chat script using Alibaba DashScope's Qwen3-Omni-Flash-Realtime.
Supports full-duplex Sichuan-dialect conversations.
"""
import os
import sys
import argparse
import pyaudio
import dashscope
from dashscope.audio.qwen_omni import OmniRealtimeConversation, OmniRealtimeCallback

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
    def __init__(self):
        super().__init__()
        self.pya = pyaudio.PyAudio()
        self.stream_out = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE_OUT,
            output=True
        )

    def on_open(self):
        print("\n[Bot is listening... Start speaking! Press Ctrl+C to stop]")

    def on_close(self):
        print("\n[Connection Closed]")
        self.stream_out.stop_stream()
        self.stream_out.close()
        self.pya.terminate()

    def on_event(self, event):
        # Print transcription as it arrives
        if event.event_name == 'response.audio_transcript.delta':
            print(event.payload.get('delta', ''), end='', flush=True)
        elif event.event_name == 'response.audio_transcript.done':
            print("\n")
        
        # Also print the user's input transcription (if provided)
        elif event.event_name == 'conversation.item.input_audio_transcription.delta':
             pass # Optionally print user transcription here

        # Play back audio chunks directly to the speaker
        elif event.event_name == 'response.audio.delta':
            audio_data = event.get_audio_data()
            if audio_data:
                self.stream_out.write(audio_data)

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
    
    # Configure the conversation
    conv = OmniRealtimeConversation(
        model=MODEL,
        url=URL,
        callback=callback,
        # Set parameters for the voice
        parameters={
            "voice": voice,
            "format": "pcm",
            "sample_rate": RATE_OUT
        }
    )

    try:
        conv.connect()
        
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
            conv.send_audio(data)

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
