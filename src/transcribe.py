"""
Transcription script using Alibaba DashScope's qwen3-asr-flash model.
"""
import os
import sys
import base64
import mimetypes
import argparse
import dashscope
from utils import setup_dashscope, handle_api_response

MAX_SIZE_BYTES = 10 * 1024 * 1024

def transcribe(audio_file, language="zh", hotwords=None):
    api_key = setup_dashscope()

    if not os.path.exists(audio_file):
        sys.exit(f"Error: File '{audio_file}' not found.")
    
    if os.path.getsize(audio_file) > MAX_SIZE_BYTES:
        sys.exit("Error: File exceeds 10 MB limit.")

    mime_type = mimetypes.guess_type(audio_file)[0] or "audio/wav"
    
    try:
        with open(audio_file, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        sys.exit(f"Error reading file: {e}")

    asr_options = {"language": language, "enable_itn": True}
    if hotwords:
        asr_options["text"] = hotwords

    try:
        response = dashscope.MultiModalConversation.call(
            api_key=api_key,
            model="qwen3-asr-flash",
            messages=[{"role": "user", "content": [{"audio": f"data:{mime_type};base64,{audio_b64}"}]}],
            result_format="message",
            asr_options=asr_options,
        )

        output = handle_api_response(response, "Transcription failed")
        print(output.choices[0].message.content[0]["text"])

    except Exception as e:
        sys.exit(f"Transcription failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe audio using Qwen3-ASR")
    parser.add_argument("audio_file", help="Path to local audio file")
    parser.add_argument("--hotwords", help="Context terms to bias recognition")
    parser.add_argument("--language", default="zh", help="Language (default: zh)")
    args = parser.parse_args()
    
    transcribe(args.audio_file, args.language, args.hotwords)
