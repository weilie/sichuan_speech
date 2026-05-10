"""
Sichuan-dialect Text-to-Speech script using Alibaba DashScope.
Uses qwen3-tts-flash with Sichuan voices (Sunny/Eric).
"""
import os
import sys
import argparse
import urllib.request
import dashscope
from utils import setup_dashscope, handle_api_response

def synthesize(text, output_file, gender):
    api_key = setup_dashscope()

    # Map gender to specific Sichuan voices
    voice_map = {"female": "Sunny", "male": "Eric"}
    voice = voice_map.get(gender, "Sunny")

    print(f"Synthesizing with {gender} voice ({voice})...")

    try:
        response = dashscope.MultiModalConversation.call(
            model="qwen3-tts-flash",
            api_key=api_key,
            text=text,
            voice=voice,
            language_type="Chinese",
            stream=False,
        )

        output = handle_api_response(response, "Synthesis failed")

        # Extract URL (handles different possible response shapes)
        audio_url = output.get("audio", {}).get("url") or \
                    output["choices"][0]["message"]["content"][0]["audio"]["url"]

        urllib.request.urlretrieve(audio_url, output_file)
        print(f"Successfully saved to: {output_file}")

    except Exception as e:
        sys.exit(f"Synthesis failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthesize Sichuan-dialect TTS using Qwen3-TTS")
    parser.add_argument("text", help="Text to synthesize")
    parser.add_argument("-o", "--output", default="sichuan_output.wav", help="Output WAV file path")
    parser.add_argument("-g", "--gender", default="female", choices=["female", "male"], 
                        help="Sichuan voice gender: female (Sunny) or male (Eric)")
    args = parser.parse_args()
    
    synthesize(args.text, args.output, args.gender)
