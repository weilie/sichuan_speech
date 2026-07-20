# Next Session Punch List

Originally captured 2026-07-03 with two work streams: Chinese wake
word (software) and enclosure (hardware). **Wake word done**
2026-07-04. Enclosure moved from Snips-STL fit-check into our own
OpenSCAD design (v1 → v10 shipped between 2026-07-03 and
2026-07-06). Physical fit-test of v10 print and a handful of
enclosure sub-features are the last open pieces before the parents'
build.

Also delivered since first capture: Sichuan system-prompt expansion
(2026-07-08, commit `e699d43`) — grandchild persona, brevity cap,
health/finance safety rails.

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

To swap the wake phrase, regenerate pinyin tokens via
`sherpa_onnx.text2token(...)` and edit `wake_keywords.txt`. Pick
3-4 syllable phrases with distinct vowels and no retroflex
(zh/ch/sh drift in Sichuan).

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

## 2. Enclosure — v10 rendered, physical fit-test of v10 pending

Design source of truth is `enclosure/case.scad` (OpenSCAD).
Rendered STLs `enclosure/base.stl` and `enclosure/lid.stl` are
regenerated from it. Iterations 1 → 10 have converged on:

- **Base outer 99 × 99 × 47 mm** (truly square, walls 3 mm)
- **Lid outer 103 × 103 × 32 mm** (overhangs base by 2 mm each side)
- **Pi rotated 90°** inside the case: long axis vertical, GPIO on
  the LEFT wall, port edge on the RIGHT wall, USB stack TOP, SD
  card BOTTOM
- **~2 mm breathing room** between the Pi and each wall on install
  (was 0.5 mm in v9, was too tight)
- **Cable grommet on the RIGHT wall**, aligned with the Pi's
  micro-USB port; big +X chamber for plug + cable slack
- **Speaker mount posts on the lid interior** at 36 mm corner-to-
  corner (Dayton DMA45-4 flange holes, measured 1 5/12″)
- **Grille** on the lid's top face — hex-packed 2.5 mm holes over a
  44 mm circle above the driver cone
- **Two 3 mm mic openings** on the lid (approximate positions above
  the HAT V2 mics — still to be verified in a full assembly)
- **LED viewing hole** in the lid, 5 mm circle above the Pi's
  PWR + ACT LED corner (for troubleshooting)
- **Snap-fit** — bumps on base long walls, matching recesses on lid
  inner lip. Confirmed to mate cleanly on v1 print.

Commits `a7123fd` (v1) through `eb870ca` (v10) — see `git log
enclosure/` for the full iteration history and the rationale for
each change.

### Next steps

1. **Print v10 base + lid** and do the fit-check with a Pi 3B v1.2
   + ReSpeaker HAT V2 + Dayton DMA45-4 + PSU cable. Verify:
   - Pi drops in with ~2 mm slop on each wall (no scraping).
   - Micro-USB plug reaches the port through the grommet with cable
     slack inside.
   - HAT stacks on GPIO without hitting the lid ceiling.
   - Speaker mounts to lid interior with 4 × M3 × 10 mm pan-head
     screws into the plastic posts.
   - Snap-fit closes cleanly.
   - LEDs are visible through the lid hole.
2. **Add still-missing features** to `case.scad`:
   - **Ventilation slots** in the base side walls (Pi 3B under
     sustained load has been observed at 58 °C; +10 °C once inside
     an enclosed box is realistic; slots are cheap insurance).
   - **Internal cable clamp / strain-relief boss** near the grommet
     so a tug on the external cable doesn't pull on the Pi's
     micro-USB connector.
   - **Mic-opening positions** verified against real HAT V2 mic
     locations (currently a best-guess based on 55 mm spacing).
3. **Aesthetics pass** (v11+): colour choice, texture, finish. Not
   urgent.

### Tools

- OpenSCAD on the Mac: `brew install --cask openscad`
- Render workflow: `openscad -o base.stl -D 'part="base"' case.scad`
  (same for `"lid"`). Assistant can iterate the `.scad` and render
  headlessly via the Bash tool.
- User prints, test-fits, reports gaps, iterate.

### Screws + hardware

- **Speaker → lid:** 4 × M3 × 10 mm pan-head Phillips machine
  screws. Any style with a shaft ≥ 3 mm and length 8–12 mm works.
- **Power:** CanaKit 5.1 V / 2.5 A micro-USB PSU + short thick
  cable. (See roadmap for the cable-vs-brick finding — cable
  quality matters more than brick rating.)

## 3. Other open items (context, not urgent this session)

Carried over from `docs/smart-speaker.md`:

- **Rotate the DashScope API key.** Still leaked from 2026-06-20,
  still active. Reset button on Alibaba Model Studio's API Key page.
- ~~End-of-speech VAD~~ **DONE 2026-07-17.** webrtcvad in
  `wake_then_converse.py`; see §4 below for the turn/session state
  machine. Fun-ASR-Realtime is still on the table as an eventual
  replacement (dedicated Sichuan accent support, DashScope same-
  platform integration) if webrtcvad accuracy proves inadequate.
- Multi-turn conversation memory within a session. (Each turn
  currently sends only the system prompt + current audio — no
  history yet.)
- ~~Daemon-shape wrapper (systemd, restart)~~ **DONE 2026-07-19.**
  Systemd user service + linger + auto-restart. See
  `docs/deployment.md`. Still open: cleaner network-blip reconnect
  and log caps.
- Cost protection (Alibaba console hard caps + on-device usage
  limits).
- Remote access (Tailscale) for post-deployment troubleshooting.
- Health alerting / heartbeat.

## 4. Turn-taking + session boundary — DONE 2026-07-17

Landed in `src/wake_then_converse.py`. Uses `webrtcvad` for
end-of-speech, plus an adaptive session loop that ends only on
meaningful signal (silence or repeated noise) rather than
arbitrary caps.

### Per-turn (utterance capture)

- 20 ms VAD frames at 16 kHz (`VAD_AGGRESSIVENESS = 2`).
- 300 ms pre-speech ring buffer so the onset isn't clipped.
- Utterance opens after 120 ms of voiced audio.
- Utterance closes on the FIRST of:
  - 800 ms of trailing silence, or
  - 30 s hard cap.
- Sub-400 ms captures are treated as noise: no cloud call, count
  as a dead turn.

### Session (multi-turn loop after wake)

- After the wake beep, `converse_session()` loops turn-by-turn.
- **Silence timeout** (how long to wait for the user to start
  talking before ending the session):
  - Turn 1 after wake: **8 s** (user may still be forming the
    thought after the beep).
  - Follow-up turns: **6 s** (natural conversational pause).
  - After a dead turn: **2.5 s** (tighten so noise can't drag
    the session along).
- **No max turns, no max wall-clock cap.** A real conversation
  runs unbounded.
- **Session ends** on any of:
  - Silence timeout expires with no speech (normal end), or
  - 2 consecutive dead turns (noise-only input; ends the
    session and drops back to wake-word listening).
- Any successful reply (cloud returned audio) zeros the dead-turn
  counter and relaxes the silence window back to 6 s.

Net effect: a noisy room burns at most 2 cloud calls before we
bail out; a real conversation is never artificially truncated.

Tuning knobs (constants at the top of `wake_then_converse.py`):
`VAD_AGGRESSIVENESS`, `MIN_UTTERANCE_MS`, `START_VOICED_MS`,
`END_SILENCE_MS`, `MAX_UTTERANCE_S`, the three silence-timeout
values, and `MAX_CONSECUTIVE_DEAD_TURNS`.
