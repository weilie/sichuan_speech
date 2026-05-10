"""
Transcription script using Alibaba DashScope's qwen3-asr-flash model.
"""
import os
import sys
import base64
import mimetypes
import argparse
import dashscope

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
MAX_SIZE_BYTES = 10 * 1024 * 1024

def transcribe(audio_file, language="zh", hotwords=None):
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        sys.exit("Error: DASHSCOPE_API_KEY environment variable not set.")

    if not os.path.exists(audio_file):
        sys.exit(f"Error: File '{audio_file}' not found.")
    
    if os.path.getsize(audio_file) > MAX_SIZE_BYTES:
        sys.exit("Error: File exceeds 10 MB limit.")

    mime_type = mimetypes.guess_type(audio_file)[0]
    if not mime_type:
        ext = os.path.splitext(audio_file)[1].lower()
        mime_type = {
            ".mp3": "audio/mpeg", 
            ".wav": "audio/wav", 
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac"
        }.get(ext, "audio/wav")

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

        if response.status_code != 200:
            sys.exit(f"API Error ({response.status_code}): {response.message}")

        print(response.output.choices[0].message.content[0]["text"])

    except Exception as e:
        sys.exit(f"Transcription failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe audio using Qwen3-ASR")
    parser.add_argument("audio_file", help="Path to local audio file")
    parser.add_argument("--hotwords", help="Context terms to bias recognition")
    parser.add_argument("--language", default="zh", help="Language (default: zh)")
    args = parser.parse_args()
    
    transcribe(args.audio_file, args.language, args.hotwords)
