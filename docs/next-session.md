# Next Session Punch List

Originally captured 2026-07-03 with two work streams: Chinese wake
word (software) and enclosure (hardware). **Wake word is DONE** as
of 2026-07-04. Only the enclosure work remains open; wake-word
section is kept below as historical context.

## 1. Chinese wake word — DONE 2026-07-04

Full swap from openWakeWord to sherpa-onnx KWS. Wake phrase 麻婆豆腐
fires reliably on Sichuan-accented pronunciation. Full turn (wake →
beep → question → cloud → Sichuan reply) validated on Pi 3 with
`throttled=0x50000` throughout.

- Model: `sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01`
- Location on Pi: `~/sichuan/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01/`
- Keyword tokens: `~/sichuan/models/wake_keywords.txt`
  (line: `m á p ó d òu f ǔ @麻婆豆腐`)
- No training required. sherpa-onnx pretrained Chinese pinyin KWS.
- Code lives in `src/wake_then_converse.py`.
- Extra deps beyond openWakeWord's stack: `sherpa-onnx`,
  `sentencepiece`, `pypinyin`.

### Original research context (kept for future revisiting)

Session research on 2026-07-03 established:

- **No public community-trained Chinese openWakeWord models exist**
  (HuggingFace + GitHub searches all zero hits).
- openWakeWord's official training pipeline is **broken on current
  Colab** (2-year-old pinned deps) and would need substantial rework
  for Chinese (English-only Piper voices bundled, English-only
  phonemizer, English-only adversarial-negative generator).
- Better alternative found: **sherpa-onnx keyword spotting** ships
  a pre-trained Chinese/English bilingual model, no retraining
  required, Apache-2.0, ARM wheels, Pi 3 feasible.

### Fallback path (only if sherpa-onnx accuracy degrades)

Real-audio openWakeWord training path is documented below in case
the sherpa-onnx model ever proves inadequate for the parents'
specific voices. Not needed today.

- Record ~200-500 utterances of the target phrase from each family
  member (you, mom, dad) using a phone / USB mic
- Also record ~15 min of ambient background noise from the parents'
  living-room location
- Skip Piper synthetic data entirely (bad Mandarin tones)
- Feature-inject the real recordings via
  `openwakeword.utils` embeddings → `.npy` files →
  `feature_data_files["positive"]` in training config
- Train on Colab T4 with the community-fixed
  [alfiedennen/openwakeword-colab-2026](https://github.com/alfiedennen/openwakeword-colab-2026)
  or [briankelley/atlas-voice-training](https://github.com/briankelley/atlas-voice-training)
- Deploy the resulting `.onnx` back into openWakeWord code

Estimated engineering: **1.5-2 focused days** including recording,
glue-scripting, training, deploying.

### Ruled out (don't revisit unless something changes)

- **Piper zh_CN synthetic data + upstream openWakeWord notebook**:
  Piper Chinese quality is mediocre due to espeak-ng tone bugs, and
  the upstream notebook is broken on current Colab.
- **Snowboy legacy**: discontinued 2020-12-31, doesn't build on
  modern Debian/Python.
- **Vosk / Kaldi keyword spotting**: usable but 300 MB RAM footprint
  and not designed as always-on KWS; too heavy for Pi 3.
- **Mycroft Precise**: abandoned in 2023, no Chinese models exist.
- **Picovoice Porcupine**: free tier bans custom wake words on ARM.
- **wukong-robot / dingdang-robot**: just wrap Snowboy/Porcupine.
- **XiaoZhi ESP32**: uses Espressif ESP-SR/MultiNet, only runs on
  ESP32-S3 NPU, not portable to Pi.
- **Baidu / Alibaba / iFlyTek APIs**: cloud-based (adds latency,
  requires internet per wake) or per-device commercial licensing.

## 2. Enclosure

Current state:

- **Snips case for RPi3 + ReSpeaker 2-Mics + 3W speaker** downloaded
  from Cults3D
  (<https://cults3d.com/en/3d-model/tool/snips-case-for-rpi3-respeaker-2-mics-pi-hat-speaker-3w>)
- STLs stashed at `enclosure/snips-reference/`:
  - `boitier.stl` — main enclosure body, holds the Pi (**a print
    was started on 2026-07-03; test-fit status is what remains open**)
  - `couvercle.stl` — top lid with speaker chamber
  - `cache_ethernet.stl`, `cache_usb.stl` — port covers
- No `.scad` or CAD source available in the download; STLs only

### Next steps in this order

1. **Finish print of `boitier.stl`** and test-fit Pi 3B v1.2:
   - Do the mounting holes align with the Pi's holes?
   - Do the USB / HDMI / micro-USB / audio cutouts align?
   - Note: this case's title says "rpi3" so it should fit Pi 3B, but
     many similar cases on Thingiverse are actually for Pi 3A+ (the
     smaller 65×56 mm board). Our Pi 3B v1.2 is 85×56 mm.
2. **If it fits well**: proceed to design a new OpenSCAD source
   using the Snips case's geometry as reference. Modifications:
   - Adapt the speaker chamber to the **Dayton DMA45-4** (~48 mm
     round, ~25 mm deep). The Snips original targets a small
     rectangular ~3 W speaker.
   - Add cable-entry grommet hole and internal cable-clamp boss for
     the CanaKit 5.1 V / 2.5 A PSU (ordered 2026-07-03, arriving
     shortly).
   - Add ventilation slots for the Pi SoC.
   - Route mic openings to the ReSpeaker HAT V2 mic positions.
3. **If it doesn't fit**: measure the Pi 3B v1.2 board and mounting
   hole positions directly, then start OpenSCAD from scratch. The
   printed boitier isn't wasted: use it as physical reference for
   the mic-funnel geometry and general form factor.

### Tools needed for design work

- OpenSCAD on the Mac: `brew install --cask openscad`
- Assistant will write `.scad` source; can then invoke `openscad -o
  file.stl file.scad` headlessly via Bash to render.
- User prints, test-fits, reports gaps, iterate.

### Other open enclosure items (deferred to a later pass)

- Cable strain relief and internal cable clamp geometry
- Ferrite bead for mains hum insurance (probably unnecessary but easy
  insurance)
- Ventilation slot placement — needs thermal-load measurement
- Aesthetics: color, texture, finish
- 3D print farm / service selection if not printing at home

## 3. Other open items (context, not urgent this session)

Carried over from `docs/smart-speaker.md`:

- **Rotate the DashScope API key.** Still leaked from 2026-06-20,
  still active. Reset button on Alibaba Model Studio's API Key page.
- End-of-speech VAD to replace the fixed 5 s recording window in
  `converse.py` / `wake_then_converse.py`
- Multi-turn conversation memory within a session
- Daemon-shape wrapper (systemd, restart, reconnect, log caps)
- Cost protection (Alibaba console hard caps + on-device usage limits)
- Remote access (Tailscale) for post-deployment troubleshooting
- Health alerting / heartbeat
