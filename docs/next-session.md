# Next Session Punch List

Originally captured 2026-07-03 with two work streams: Chinese wake
word (software) and enclosure (hardware). **Wake word done**
2026-07-04. Enclosure moved from Snips-STL fit-check into our own
OpenSCAD design (v1 → v15c between 2026-07-03 and 2026-09-21; the
v14 print fit-tested clean on 2026-07-19). The v15c mic-port test
print is the last open enclosure piece before the parents' build, but
see §0: re-measure wake recall before printing more.

Also delivered since first capture: Sichuan system-prompt expansion
(2026-07-08, commit `e699d43`) — grandchild persona, brevity cap,
health/finance safety rails.

## 0. START HERE — 2026-09-28 supersedes most of what follows

**The wake word was never the mics' fault.** `max_active_paths` had sat at
sherpa-onnx's default of 4 since the July KWS swap. It was never swept, and it
dominates every knob that was. Measured lid-CLOSED on a 50-utterance corpus:

- beam 4  → 28/50 (56%)
- beam 8  → 43/50 (86%)
- beam 16 → 47/50 (94%)

all three with ZERO false accepts against 20 windows of the user talking and
making noise without saying 麻婆豆腐. Costs 3% CPU on the Pi (RTF 0.349 → 0.360
at one thread) — the zipformer encoder dominates and the beam search is
rounding error beside it. Shipped in `c82bdb0`; beam 16 chosen over the single
best cell because 3.0/4.0/4.5/5.0 all land on exactly 47/50 there, while the
better-scoring 3.0/48 has neighbours that produce false accepts.

`keywords_score` is nearly flat next to beam width and `keywords_threshold` is
inert below 0.1. Voice switched Sunny → Eric (male, Sichuan) in `af60310`.

### What this invalidates

Every wake-path measurement this project has made was taken at beam 4 — the
tools carried the same default. **The 2026-09-19 lid-open vs lid-closed test
that set the whole enclosure agenda below is one of them.** Lid-closed now runs
at 94%, so the 7.8 dB penalty may not matter at all. Re-measure before spending
any more print time on `case.scad`.

Also retired: the "loose thresholds catch fewer utterances" claim and the
mid-range `score` optimum. Both were artifacts of a 19-window corpus.

### Method that produced this, worth reusing

`tools/blind_windows.py` scores a beep-paced take per window with NON-WAKE
windows kept in the corpus, so false accepts have a denominator. Ground truth
stays with the human until the verdicts are read back. Sweeps run on the Mac
against a copy of the model (~40× faster than the Pi, results verified
identical on-device), so a 30-cell grid is 74 s rather than an hour.

Sample size is the whole story: at n=10 windows the same condition measured
14% and 40% ten minutes apart. Do not trust n<50.

## 0a. Endpointer — DONE 2026-09-28, confirmed in live use

The device answered room noise out loud. With webrtcvad, **33 of 50 windows in
which nobody spoke** produced a capture that survived the noise gate and
reached the cloud. Fixed in `c6469cd` by swapping the VAD to Silero (already
shipped inside sherpa-onnx for the wake word):

```
            short  med  long   ALL   noise reaching the cloud
  webrtcvad 30/30   10    10  50/50        33/50
  silero    30/30   10    10  50/50        13/50
```

Same recall, short questions included. RTF 0.100 on the Pi vs webrtcvad's
0.0011 — 90× more, still a tenth of one core, and the wake spotter is idle
during a conversation turn. Verified live by the user the same day.

**The gate was deliberately not retuned**, and that is the finding worth
keeping. The gate scores the longest unbroken voiced run, which is mostly a
proxy for utterance LENGTH. A first attempt tuned on 10 long sentences chose
MIN_VOICED_RUN_MS=1200 and scored 10/10 speech with 0/10 noise; cross-checked
against the older `q2` corpus it kept **3 of 12**. Recall must be reported per
length bucket and never pooled: past run 700 every setting pays almost entirely
in SHORT questions (30 → 24 → 13 of 30) while medium and long hold at 10/10.
`tools/endpoint_tune.py` does this by construction.

### Residual, in priority order

- **13/50 noise windows still reach the cloud.** Improved, not solved. Nobody
  has looked at what those 13 are.
- **Silero keeps 8/12 of `q2` where webrtcvad kept 11/12.** Judged acceptable —
  12 September questions against 50 current ones showing no loss — but it is
  the first thing to suspect if short questions start being ignored in real
  use.
- **Next-room speech and a TV are not solvable this way at all.** `negatives.wav`
  proves it: its 9 captures show voiced runs of 0.8-3.0 s at 43-71% voicing,
  which is speech and indistinguishable from a real question by any voicing
  statistic. Speaker verification or a shorter session window are the only
  candidates.
- TEN VAD is exposed by the same `VadModelConfig` and was never tried.

### Corpora on the Pi (`~/sichuan/wake_data/`)

- `short1-3` (30 short questions), `med1` (10), `speech1` (10 long) — 50 spoken
- `nospeech1-5` — 50 windows, room noise, no voice at all
- `pos1-5` / `neg1-2` — 50 wake utterances + 20 non-wake speech, for the KWS
- `q`, `q2` — 24 older questions, kept as an independent cross-check
- `negatives.wav` — 180 s of room audio that turned out to be speech

## 0b. The two problems of 2026-09-19 — history, partly superseded

**Status as of 2026-09-28.** (2) is resolved: webrtcvad was replaced by
Silero (§0a). (1) is unresolved and its premise is in doubt: every number
below was taken at beam 4 (§0), so re-measure lid-closed recall at beam 16
before acting on it. The text stays as the record of what was measured and
why.

### (1) The microphones need a hardware change

Closing the lid costs **4.9 dB of signal and raises the noise floor by
2.9 dB — a net 7.8 dB SNR penalty**, dropping the wake path from
20.5 dB to 12.7 dB. Measured by recording the same four utterances,
same spot, same settings, lid open vs closed:

- lid **open**: wake fires **4/4**
- lid **closed**: wake fires **1/4**

Nothing in software recovers this, and that is measured, not assumed:
looser KWS thresholds caught *zero* of four, digital gain to +12 dB
stayed at 1/4 and collapsed to 0/4 by +16 dB, four pronunciation
variants (including the Sichuan f→h merge) changed nothing, and
high-pass filtering at 80/150/250 Hz did nothing or made it worse.

Cause, confirmed from photos of the build: both MEMS mics sit on the
HAT **in the base, facing up**, each beside a corner mounting hole —
one immediately left of the HAT's micro-USB, the other diagonally
opposite. With the lid on they look up into a deep sealed cavity that
also contains the speaker, and their only path to outside air is a
3 mm hole in the lid's top face placed on a best-guess.

How Echo / Nest / HomePod solve it: the mic PCB sits directly under
the enclosure's outer surface and **every mic port is sealed by a
gasket to its own hole 1-3 mm away**, so the mic is acoustically
outside the box; the driver lives in a separate sealed chamber. Two
rules, both currently violated: short sealed port, and mics never
share air with the driver.

Options, in order of preference:
1. Relocate the Pi + HAT stack against the top face, mic corners
   1-2 mm under it, a hole over each port, gasket sealing port to
   hole; speaker into its own sub-chamber. Real `case.scad` rework.
2. Cheap proof first: drill ~6-8 mm holes in the base side wall level
   with the HAT's top surface, one beside each mic, and re-run the
   4-utterance test.
3. Fallback only: external USB mic. No commercial product does this;
   it costs a second ALSA device and a cable to knock loose.

#### v15 test print — protocol and what follows

`enclosure/base.stl` (v15c, commit `25a77e9`) has deliberately
oversized openings: four 16.2 × 18 mm slots spanning the -X (GPIO)
wall, and one 18 × 18 mm port in each of the -Y and +Y walls, all in
a z band of 11-29.5 mm straddling the mic plane at ~18.5 mm. Lid
unchanged.

To keep the result comparable, re-run `tools/wake_livecheck.py` from
the same spot at the same volume with the lid **closed**. The baseline
to beat is **1/4 detections closed vs 4/4 open**.

- **Near 4/4 closed** → mechanism confirmed. Then shrink the openings
  — but shrink them the way commercial speakers do: a SMALL hole
  within a few mm of the mic port, covered with acoustically
  transparent mesh. Mesh is what keeps dust out; simply making a hole
  that sits 10 mm away smaller mostly gives the signal back. Use the
  `mic_port_y_walls` / `mic_port_x_wall` flags to find which set of
  openings did the work before deciding what to keep.
- **Still ~1/4** → holes are not the fix. Move the board up under the
  enclosure's outer surface with gasketed ports, per the options
  above.

Also still wrong: the lid's `mic_holes()` uses the old ~28 mm guess,
so its two 3 mm holes have never been over the microphones. Left
alone because the lid is not being reprinted, but fix it whenever the
lid is next touched.

### (2) The voice/environment classifier needs better precision and recall

webrtcvad labelled only **41-46% of real speech frames as voice**,
which causes both failure modes:

- **Recall** — a capture ends after `END_SILENCE_MS` of frames *not
  labelled* voice, which is not the same as silence. At 800 ms this
  cut a 1.5 s question down to ~300 ms and the cloud answered "I
  can't hear you" every time. Now 1400 ms; measured per-utterance at
  that setting, five of six clean utterances capture complete and one
  truncates to a single syllable.
- **Precision** — ~9 captures survive the noise gate across 3 minutes
  of room audio. Each costs two cloud calls and an unwanted spoken
  reply, and none counts as a dead turn (the cloud *did* answer), so
  the session stays open to do it again. Nobody has yet looked at
  *which* 9 — dump them with timestamps and transcripts first, since
  typing, next-room speech and a fridge compressor need different
  fixes.

**Re-measure before tuning.** Every number above was taken at the
degraded SNR of problem (1). Fix the mics, re-run
`tools/sweep_vad.py`, and only then decide whether webrtcvad needs
replacing. What will *not* improve on its own is false accepts:
webrtcvad fires on typing at any SNR.

Caveat on the sweep's false-accept column: the count falls as
`END_SILENCE_MS` rises (20 at 800, 9 at 1400, 7 at 2000) because the
same noise merges into fewer, longer captures. It is only comparable
at a fixed end-silence.

### (3) Also worth doing regardless: a press-to-talk button

The HAT has a user button on GPIO17 and `src/converse.py` already
implements press-to-talk. It works at any distance, in any room, at
any placement — the only option that makes the device usable whatever
happens with (1) and (2), and more discoverable for elderly users than
a wake phrase, not less.

### Tools for this work

- `tools/wake_livecheck.py` — record live, replay through the spotter
  at the live setting and looser ones. Answers "does what the mic
  hears now look like what it was tuned on".
- `tools/sweep_vad.py` — recall / completeness / false accepts for the
  endpointer, replaying the device's own `endpoint()`. Pass
  `--phrase` matching what was actually said; scoring a 麻婆豆腐 corpus
  against 明天天气怎么样 returns a confident 0/12 that means nothing.
- `tools/collect_wake_paced.sh` — beep-paced labelled corpus; takes an
  optional phrase argument. Launched detached, its on-screen prompt
  goes to a log nobody reads, so state the phrase out loud to whoever
  is recording.

Note: `tools/sweep_vad.py` and `tools/vad_gate_sweep.py` build
`webrtcvad.Vad` directly, so they measure the fallback engine, not the
shipped Silero one. `tools/endpoint_tune.py` and `tools/vad_compare.py`
cover Silero.

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

## 2. Enclosure — v15c current, v10 baseline below

Design source of truth is `enclosure/case.scad` (OpenSCAD).
Rendered STLs `enclosure/base.stl` and `enclosure/lid.stl` are
regenerated from it. Iterations 1 → 10 converged on the list below;
later changes are marked in italics. The open item is the v15c test
print (mic ports in the base walls, §0b).


- **Base outer 99 × 99 × 47 mm** (truly square, walls 3 mm)
- **Lid outer 103 × 103 × 32 mm** (overhangs base by 2 mm each side;
  *≈33 mm since v11*)
- **Pi rotated 90°** inside the case: long axis vertical, GPIO on
  the LEFT wall, port edge on the RIGHT wall, USB stack TOP, SD
  card BOTTOM
- **~2 mm breathing room** between the Pi and each wall on install
  (was 0.5 mm in v9, was too tight)
- **Cable grommet on the RIGHT wall**, aligned with the Pi's
  micro-USB port; big +X chamber for plug + cable slack. *Ø12 mm
  since v14, so the plug's strain-relief boot passes.*
- **Speaker mount posts on the lid interior** at 36 mm corner-to-
  corner (Dayton DMA45-4 flange holes, measured 1 5/12″). *v11:
  front-mounted instead, so the driver's foam gasket seals against the
  outside of the lid: a Ø40 mm cutout and four bosses underneath.
  v14: a single Ø3 mm bore per boss.*
- **Grille** on the lid's top face — hex-packed 2.5 mm holes over a
  44 mm circle above the driver cone. *Removed in v11.*
- **Two 3 mm mic openings** on the lid (approximate positions above
  the HAT V2 mics). *Still there, still at the old guess: v15b measured
  the real mic positions ~20 mm away. Fix `mic_holes()` whenever the lid
  is next touched. The v15 test uses ports in the base walls instead.*
- **LED viewing hole** in the lid, 5 mm circle above the Pi's
  PWR + ACT LED corner (for troubleshooting). *Removed in v14; now a
  10×2 mm slit in the -Y wall.*
- **Snap-fit** — bumps on base long walls, matching recesses on lid
  inner lip. Confirmed to mate cleanly on v1 print.

Commits `a7123fd` (v1) through `25a77e9` (v15c) — see `git log
enclosure/` for the full iteration history and the rationale for
each change.

### Next steps

1. ~~Print and fit-check~~ **DONE for v14, 2026-07-19**: everything
   mates, the M3 screws self-tap and hold the speaker, the cable
   passes the grommet. What is left to print is v15c (§0b).
2. **Still-missing features** in `case.scad`:
   - **Ventilation**: the v15 -X wall slots double as vents, but a
     Pi 3B under sustained load has been seen at 58 °C (+10 °C once
     enclosed is realistic), so check temperature in the closed case.
   - **Internal cable clamp / strain-relief boss** near the grommet
     so a tug on the external cable doesn't pull on the Pi's
     micro-USB connector. Still open.
   - **Mic-opening positions**: measured for the base ports in v15b;
     the lid's `mic_holes()` still uses the old guess.
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

- **Voice volume control — built, unmeasured.** A third call in the
  t=0 fan-out (text-only, no search, alongside the search and the
  speculative answer) classifies the utterance into `VOLUME_UP` /
  `VOLUME_DOWN` / `REPEAT` / none, and the Pi moves the HAT's `PCM`
  level itself, acknowledging with a cached spoken phrase. Two things
  need measuring
  on the device before this is trustworthy: the **false-positive rate**
  against the 2026-09-19 question corpus (a device that turns itself
  down mid-answer is worse than one that ignores the request), and
  whether 4 dB per step and the 12 dB floor are the right sizes by ear
  in the parents' room. Also unheard so far: the five acknowledgement
  phrases.

Carried over from `docs/smart-speaker.md`:

- **Rotate the DashScope API key.** Still leaked from 2026-06-20,
  still active. Reset button on Alibaba Model Studio's API Key page.
- ~~End-of-speech VAD~~ **DONE 2026-07-17** with webrtcvad,
  replaced by Silero on 2026-09-28 (§0a). See §4 below for the
  turn/session state machine. Fun-ASR-Realtime is still on the table as an eventual
  replacement (dedicated Sichuan accent support, DashScope same-
  platform integration) if webrtcvad accuracy proves inadequate.
- ~~Multi-turn conversation memory within a session.~~ **DONE**
  (commit `41d81d2`). History now also always stores the user's
  actual audio, never the restyle scaffolding a search turn sends
  to the voice model.
- ~~Web search for real-time questions.~~ **DONE 2026-09-19.**
  Two-round path with a speculative round 2; see §5.1a of the
  roadmap. Residual: on a search turn the reply sometimes softens
  the number ("二十多度" instead of "24到25度") even though the
  facts contain it. Tighten the restyle instruction if it shows up
  in real use.
- ~~Daemon-shape wrapper (systemd, restart)~~ **DONE 2026-07-19.**
  Systemd user service + linger + auto-restart. See
  `docs/deployment.md`. ~~Log caps~~ **DONE 2026-09-19** (see
  "Journal is persistent" in `docs/deployment.md`). Still open:
  cleaner network-blip reconnect.
- **Residual findings from the 2026-09-19 adversarial review** (the
  five serious ones are fixed in `src/wake_then_converse.py`; of the
  three that were left, the last is now fixed too):
  - A failed restyle falls through to a *fourth* cloud call, and the
    holding phrase is not re-armed, so the user waits it out in
    silence.
  - The search branch aborts the speculative thread but never joins
    it. `voice_call` only checks the stop event between SSE chunks,
    so a stream stalled mid-read survives; each zombie pins ~5 MB
    (its base64 audio plus a history copy) on a 1 GB Pi until the
    SDK read timeout kills it.
  - ~~`ensure_filler` writes `checking.wav` non-atomically and
    short-circuits on mere existence, so a power cut mid-write
    caches a truncated file permanently.~~ **Fixed in `1d89ace`**
    (temp file + `os.replace`; the file is also keyed to the voice).
- Cost protection (Alibaba console hard caps + on-device usage
  limits). Partly done: a workspace-scoped key and
  `tools/usage-report.sh` (`4fef894`); hard caps and on-device limits
  are still open.
- Remote access (Tailscale) for post-deployment troubleshooting.
- Health alerting / heartbeat.

## 4. Turn-taking + session boundary — DONE 2026-07-17

Landed in `src/wake_then_converse.py`. Uses an on-device VAD for
end-of-speech (webrtcvad at first, Silero since 2026-09-28, with
webrtcvad as the fallback), plus an adaptive session loop that ends only on
meaningful signal (silence or repeated noise) rather than
arbitrary caps.

### Per-turn (utterance capture)

- 20 ms VAD frames at 16 kHz. Silero decides (threshold 0.7);
  `VAD_AGGRESSIVENESS = 2` applies only to the webrtcvad fallback.
- 300 ms pre-speech ring buffer so the onset isn't clipped.
- Utterance opens after 120 ms of voiced audio.
- Utterance closes on the FIRST of:
  - 1400 ms of trailing silence (`END_SILENCE_MS`; 800 until
    2026-09-19), or
  - 30 s hard cap.
- Sub-400 ms captures are treated as noise: no cloud call, count
  as a dead turn.
- So are captures without speech-like voicing: longest unbroken voiced
  run under 300 ms (`MIN_VOICED_RUN_MS`) or voiced ratio under 10%
  (`MIN_VOICED_RATIO`). Both stats are logged on every turn.

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
`SILERO_VAD_THRESHOLD`, `VAD_AGGRESSIVENESS` (fallback only),
`MIN_UTTERANCE_MS`, `MIN_VOICED_RUN_MS`, `MIN_VOICED_RATIO`,
`START_VOICED_MS`, `END_SILENCE_MS`, `MAX_UTTERANCE_S`, the three
silence-timeout values, and `MAX_CONSECUTIVE_DEAD_TURNS`.
