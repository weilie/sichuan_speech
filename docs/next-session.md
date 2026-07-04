# Next Session Punch List

Captured 2026-07-03 while a Snips-case boitier print was running and
before the chat session reboot. Two work streams to pick up: Chinese
wake word (software) and enclosure (hardware).

## 1. Chinese wake word — switch from openWakeWord to sherpa-onnx KWS

### Why we're switching
- We validated that "hey_jarvis" via openWakeWord works end-to-end on
  Pi 3 (see `docs/smart-speaker.md` 2026-07-02 entry). But "hey_jarvis"
  is a no-go for parents' unit — needs a Chinese wake word.
- Session research (2026-07-03) established:
  - **No public community-trained Chinese openWakeWord models exist**
    (HuggingFace + GitHub searches all zero hits).
  - openWakeWord's official training pipeline is **broken on current
    Colab** (2-year-old pinned deps) and would need substantial rework
    for Chinese (English-only Piper voices bundled, English-only
    phonemizer, English-only adversarial-negative generator).
  - Better alternative found: **sherpa-onnx keyword spotting** ships
    a pre-trained Chinese/English bilingual model, no retraining
    required, Apache-2.0, ARM wheels, Pi 3 feasible.

### Path A (primary): drop in sherpa-onnx KWS

Pretrained model to use:
`sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` (bilingual zh+en) or
`sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01` (zh only,
trained on 10 000 hrs WenetSpeech). Both on
<https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html>.

Integration into `src/wake_then_converse.py` — a code refactor, not
an ML project:
1. `pip install sherpa-onnx` in the Pi's venv
2. Replace the `openwakeword.model.Model(...)` block and the
   `oww.predict(...)` inner loop with sherpa-onnx's `KeywordSpotter`.
3. Declare wake phrase(s) in a `keywords.txt` file — use the CLI
   `sherpa-onnx-cli text2token` to convert the Chinese phrase to the
   required token string.
4. Per-keyword `:score` / `#threshold` knobs tune sensitivity if
   Sichuan tones cause false-positives or misses.
5. Same code shape otherwise — mic loop, wake fires → converse_turn,
   mask PulseAudio same way.

Estimated engineering: **1–2 hours** to swap, then field-tune scores.

Pick a phrase before starting:
- 3–4 syllables, distinct vowels, uncommon in daily speech
- Candidates: 小四川, 小助手, 阿川, a family nickname
- Avoid single-syllable, or common phrases like 你好, 起来, 走开

### Path B (fallback if A trips on Sichuan tones): real-audio openWakeWord training

Only pursue if Path A field-tests poorly for our 3-speaker family
population.

- Record ~200–500 utterances of the target phrase from each family
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
- Deploy the resulting `.onnx` back into the openWakeWord code we
  already have

Estimated engineering: **1.5–2 focused days** including recording,
glue-scripting, training, deploying.

Overfitting to family voices is a *feature*, not a bug, for this
deployment.

### Ruled out (don't revisit unless something changes)

- **Piper zh_CN synthetic data + upstream openWakeWord notebook** —
  Piper Chinese quality is mediocre due to espeak-ng tone bugs, and
  the upstream notebook is broken on current Colab.
- **Snowboy legacy** — discontinued 2020-12-31, doesn't build on
  modern Debian/Python.
- **Vosk / Kaldi keyword spotting** — usable but 300 MB RAM footprint
  and not designed as always-on KWS; too heavy for Pi 3.
- **Mycroft Precise** — abandoned in 2023, no Chinese models exist.
- **Picovoice Porcupine** — free tier bans custom wake words on ARM.
- **wukong-robot / dingdang-robot** — just wrap Snowboy/Porcupine.
- **XiaoZhi ESP32** — uses Espressif ESP-SR/MultiNet, only runs on
  ESP32-S3 NPU, not portable to Pi.
- **Baidu / Alibaba / iFlyTek APIs** — cloud-based (adds latency,
  requires internet per wake) or per-device commercial licensing.

## 2. Enclosure

Current state:
- **Snips case for RPi3 + ReSpeaker 2-Mics + 3W speaker** downloaded
  from Cults3D
  (<https://cults3d.com/en/3d-model/tool/snips-case-for-rpi3-respeaker-2-mics-pi-hat-speaker-3w>)
- STLs stashed at `enclosure/snips-reference/`:
  - `boitier.stl` — base body, holds Pi (**this is what's printing**)
  - `couvercle.stl` — top lid with speaker chamber
  - `cache_ethernet.stl`, `cache_usb.stl` — port covers
- No `.scad` or CAD source available in the download — STLs only

### Next steps in this order

1. **Finish print of `boitier.stl`** and test-fit Pi 3B v1.2:
   - Do the mounting holes align with the Pi's holes?
   - Do the USB / HDMI / micro-USB / audio cutouts align?
   - Note: this case's title says "rpi3" so it should fit Pi 3B, but
     many similar cases on Thingiverse are actually for Pi 3A+ (the
     smaller 65×56 mm board). Our Pi 3B v1.2 is 85×56 mm.
2. **If it fits well** — proceed to design a new OpenSCAD source
   using the Snips case's geometry as reference. Modifications:
   - Adapt the speaker chamber to the **Dayton DMA45-4** (~48 mm
     round, ~25 mm deep) — the Snips original targets a small
     rectangular ~3 W speaker
   - Add cable-entry grommet hole and internal cable-clamp boss for
     the CanaKit 5.1 V / 2.5 A PSU (ordered 2026-07-03, arriving
     shortly)
   - Add ventilation slots for the Pi SoC
   - Route mic openings to the ReSpeaker HAT V2 mic positions
3. **If it doesn't fit** — measure the Pi 3B v1.2 board and mounting
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
