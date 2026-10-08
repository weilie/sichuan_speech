# Sichuan Speech

Sichuan-dialect voice tools on Alibaba Cloud's DashScope API, and the
Raspberry Pi smart speaker built from them: say the wake phrase 麻婆豆腐,
ask a question, hear a Sichuan-dialect answer. See `docs/smart-speaker.md`
for the roadmap and `docs/deployment.md` for running it on the Pi.

## What's here
- `src/wake_then_converse.py`: **the smart speaker.** Wake-word listening
  (sherpa-onnx), on-device end-of-speech detection, multi-turn conversation
  against `qwen3.5-omni-flash` with web search for real-time questions. Runs
  on the Pi as a systemd user service.
- `src/converse.py`: press-to-talk, single turn, non-realtime.
- `src/chat_omni.py`: realtime WebSocket chat. Half-duplex, no barge-in, and
  not used by the service.
- `src/transcribe.py`, `src/synthesize.py`: ASR (`qwen3-asr-flash`) and TTS
  (`qwen3-tts-flash`, voices `Sunny` and `Eric`) command-line tools.
- `tools/`: wake-word and VAD measurement scripts, corpus recording, and
  `usage-report.sh` (month-to-date spend and device activity).
- `deploy/`, `docs/`, `enclosure/`: systemd unit, documentation, and the
  OpenSCAD source for the 3D-printed case.

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```
The smart speaker also needs the model files listed in `docs/deployment.md`.

### 2. Configure API Key
Get your API key from [Alibaba Cloud Model Studio](https://dashscope.console.aliyun.com/apiKey)
(the code uses the International / Singapore endpoint) and export it:
```bash
export SICHUAN_DASHSCOPE_API_KEY="your_api_key_here"
```
`SICHUAN_DASHSCOPE_API_KEY` is preferred: Model Studio bills per workspace, so
a key created in its own workspace gives this project its own line on the bill.
Every script except `chat_omni.py` falls back to `DASHSCOPE_API_KEY`;
`chat_omni.py` reads only that one.

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

### Press-to-Talk Voice Chat
Single-turn voice exchange against `qwen3-omni-flash` (non-realtime). Records
a fixed-length clip, sends it as one request, and plays the response.
```bash
python3 src/converse.py -g female              # default 5 s recording, Sunny
python3 src/converse.py -g male -d 8           # 8 s recording, Eric
python3 src/converse.py --ready-wav ready.wav  # play a cue immediately before recording
```

### Real-Time Voice-to-Voice Chat
Live voice conversation over the realtime API. The ReSpeaker HAT's codec is
half-duplex, so the mic is closed while the bot speaks and you cannot interrupt
it. Needs a working microphone and speaker. Press `Ctrl+C` to end.
```bash
python3 src/chat_omni.py -g female    # Sunny
python3 src/chat_omni.py -g male      # Eric
```

### Smart speaker
Runs on the Pi under systemd; to run it by hand, stop the service first (it
holds the mic) and run `python3 wake_then_converse.py` from `~/sichuan`. See
`docs/deployment.md`.

## Testing
```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## License
MIT
