#!/usr/bin/env python3
"""Clone a voice with Qwen-TTS and speak text through it.

  voice_clone.py enroll sample.wav [--name NAME] [--text TRANSCRIPT]
  voice_clone.py speak VOICE_ID "要念的话" out.wav

Plain HTTP against the international endpoint, so it runs on the Mac without
the dashscope SDK. The sample must be >= 24 kHz; convert a Voice Memos .m4a
with `afconvert -f WAVE -d LEI16@24000 -c 1 in.m4a out.wav`.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

BASE = "https://dashscope-intl.aliyuncs.com/api/v1"
ENROLL_MODEL = "qwen-voice-enrollment"
TTS_MODEL = "qwen3-tts-vc-2026-01-22"


def api_key():
    key = (os.getenv("SICHUAN_DASHSCOPE_API_KEY")
           or os.getenv("DASHSCOPE_API_KEY"))
    if not key:
        sys.exit("Error: neither SICHUAN_DASHSCOPE_API_KEY nor "
                 "DASHSCOPE_API_KEY is set.")
    return key


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key()}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"API Error ({e.code}): {e.read().decode(errors='replace')}")


def enroll(args):
    mime = mimetypes.guess_type(args.sample)[0] or "audio/wav"
    with open(args.sample, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    inp = {"action": "create", "target_model": TTS_MODEL,
           "preferred_name": args.name,
           "audio": {"data": f"data:{mime};base64,{data}"}}
    if args.text:
        inp["text"] = args.text
    out = post("/services/audio/tts/customization",
               {"model": ENROLL_MODEL, "input": inp})
    print(json.dumps(out, ensure_ascii=False, indent=2))


def speak(args):
    out = post("/services/aigc/multimodal-generation/generation",
               {"model": TTS_MODEL,
                "input": {"text": args.text, "voice": args.voice}})
    audio = (out.get("output") or {}).get("audio") or {}
    if audio.get("url"):
        urllib.request.urlretrieve(audio["url"], args.out)
    elif audio.get("data"):
        with open(args.out, "wb") as f:
            f.write(base64.b64decode(audio["data"]))
    else:
        sys.exit(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {args.out}  usage={out.get('usage')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll")
    e.add_argument("sample")
    e.add_argument("--name", default="weilie")
    e.add_argument("--text", help="transcript of the sample (optional)")
    e.set_defaults(fn=enroll)
    s = sub.add_parser("speak")
    s.add_argument("voice")
    s.add_argument("text")
    s.add_argument("out")
    s.set_defaults(fn=speak)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
