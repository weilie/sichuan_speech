# Sichuan Speech Scripts

A pair of streamlined Python scripts for transcribing and synthesizing Sichuan dialect speech using Alibaba Cloud's DashScope API (Qwen-ASR and Qwen-TTS).

## Features
- **ASR (Transcription)**: Uses `qwen3-asr-flash` to accurately transcribe Sichuanese audio.
- **TTS (Synthesis)**: Uses `qwen3-tts-flash` with authentic Sichuan voices (`Sunny` and `Eric`).
- **Region Support**: Optimized for the International (Singapore) endpoint, supporting both services with a single API key.
- **CLI Friendly**: Simple command-line arguments for quick usage.

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API Key
Get your API key from [Alibaba Cloud Model Studio](https://dashscope.console.aliyun.com/apiKey) and export it as an environment variable:
```bash
export DASHSCOPE_API_KEY="your_api_key_here"
```

## Usage

### Transcription (ASR)
```bash
python3 src/transcribe.py path/to/audio.wav
```

### Synthesis (TTS)
```bash
# Female voice (Sunny)
python3 src/synthesize.py "今天天气好安逸哦" -g female -o output.wav

# Male voice (Eric)
python3 src/synthesize.py "今天天气好安逸哦" -g male -o output.wav
```

### Real-Time Voice-to-Voice Chat
Start a live, full-duplex voice conversation in the Sichuan dialect. This requires a working microphone and speakers.
```bash
# Start a chat with the female voice (Sunny)
python3 src/chat_omni.py -g female

# Start a chat with the male voice (Eric)
python3 src/chat_omni.py -g male
```

*(Press `Ctrl+C` to end the conversation).*

### Press-to-Talk Voice Chat
Single-turn voice exchange against `qwen3-omni-flash` (non-realtime). Records
a fixed-length clip, sends it as one request, and plays the response. This is
the path validated on the Raspberry Pi 3 + ReSpeaker 2-Mics HAT in Phase 0 of
the smart-speaker roadmap.
```bash
python3 src/converse.py -g female              # default 5 s recording, Sunny
python3 src/converse.py -g male -d 8           # 8 s recording, Eric
python3 src/converse.py --ready-wav ready.wav  # play a cue immediately before recording
```

## Testing
Run the unit tests:
```bash
PYTHONPATH=src python3 tests/test_scripts.py
```

## Repository Contents
- `src/`: Core Python scripts.
- `tests/`: Unit tests.
- `requirements.txt`: Python dependencies.

## License
MIT
