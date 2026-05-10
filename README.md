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
Transcribe any local audio file to text:
```bash
python3 transcribe.py path/to/audio.wav
```
Supports `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, and `.aac`.

### Synthesis (TTS)
Generate Sichuan dialect speech from text:
```bash
# Female voice (Sunny)
python3 synthesize.py "今天天气好安逸哦" -g female -o output.wav

# Male voice (Eric)
python3 synthesize.py "今天天气好安逸哦" -g male -o output.wav
```

## Repository Contents
- `transcribe.py`: Streamlined transcription script.
- `synthesize.py`: Streamlined synthesis script with Sichuan voice mapping.
- `requirements.txt`: Python dependencies.

## License
MIT
