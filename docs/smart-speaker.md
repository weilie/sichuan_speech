# Sichuan Smart Speaker — Roadmap

A standalone, Alexa-style smart speaker that listens and responds in
Sichuan dialect, built on Raspberry Pi 5 and deployed at the maintainer's
parents' home, roughly 1000 km away.

Roadmap, not design. It captures goal, constraints, BOM, enclosure
considerations, software shape, and phases. It does **not** lock in
specific libraries, cadences, thresholds, or protocols — those are
decided when each phase is reached. Updated as we learn things.

---

## 1. Goal

A self-contained, always-on device the parents can talk to naturally in
Sichuan dialect. The interaction should feel like Alexa: power on once,
walk away, and from then on it just works. Wake word → speak → reply.

No keyboard, monitor, or app. No visible controls — no buttons,
switches, screens, or LEDs. Audio-only feedback (end users are seniors;
small visual indicators are not a reliable channel for them).

The device will live ~1000 km from the maintainer. The maintainer
cannot drive over to fix things. That single fact shapes nearly every
choice below.

---

## 2. Constraints & Operating Assumptions

- **Remote deployment.** Reliability, remote-debuggability, and
  graceful self-recovery dominate every choice.
- **Non-technical users.** Parents won't SSH in, read logs, or notice
  that something has broken. Voice in; everything else invisible.
- **Always plugged in.** Wall power, no battery for v1. Must tolerate
  occasional unplug/power loss without corrupting state.
- **Home Wi-Fi.** Parents' SSID and password pre-flashed before
  transport. No enterprise auth.
- **Inference is cloud-side.** DashScope Qwen Omni. Two transport
  paths are kept on the table — `qwen3-omni-flash-realtime` over a
  full-duplex WebSocket (low latency, supports barge-in) and the
  non-realtime `qwen3-omni-flash` request/response API (simpler,
  validated end-to-end on Pi 3). v1 decides which one ships, or
  supports both behind a runtime flag. The Pi only does audio I/O,
  wake-word, and orchestration — no heavy local ML.
- **Latency budget.** Conversational. Press-to-talk round-trip
  measured at ~5–6 s on Pi 3 over 2.4 GHz Wi-Fi to Alibaba SG,
  which is borderline acceptable; 5 GHz on Pi 4/5 is expected to
  improve it.
- **Cost-bounded.** DashScope is metered. The device must not be
  able to silently burn through the budget if something gets stuck.

---

## 3. Hardware Bill of Materials

### Core build

| Item | Notes | ~USD |
|---|---|---|
| Raspberry Pi (model TBD) | Decision deferred until Phase 0 finishes on the on-hand Pi 3. Realistic prices today: Pi 4 4 GB ~$100 (CanaKit/PiShop), Pi 5 4 GB ~$130 (Adafruit). 5 GHz Wi-Fi (Pi 4 and 5) matters for jitter to Alibaba SG; Pi 5 also has wake-word headroom for Phase 1. | $100–130 |
| Official USB-C PSU | Pi 5 needs the 27 W official PSU; Pi 4 is happy with any ~15 W USB-C. Off-brand chargers cause undervoltage. | $8–12 |
| Active cooler | Pi 5: official Active Cooler. Pi 4: heatsink + small fan. Without it the Pi throttles under sustained load. | $5 |
| ReSpeaker 2-Mics Pi HAT (genuine Seeed) | Dual mics, WM8960 codec, JST speaker connector. The HAT's button and 3 RGB LEDs are left unused. Ordered 2026-06-13 from Amazon (B07CXSW6LB). Cheaper KEYESTUDIO clones exist (~$12) but the genuine board has better driver/community support. Compatible with Pi 3, 4, and 5. | $40 |
| USB SSD 128 GB (preferred) **or** A2 high-endurance microSD 64 GB | SSD is far more reliable for 24/7 operation. SD cards are the #1 failure mode for always-on Pi deployments. Pi 5 boots from USB 3.0 SSD or NVMe (with adapter HAT); Pi 4 boots from USB 3.0 SSD. | $20 / $12 |
| Full-range speaker driver, 3 W / 4 Ω | Ordered the Dayton Audio DMA45-4 (1½", aluminum cone) from Amazon (B07N1YW3SV). This is a substitute for the originally spec'd Dayton CE32A-4 (1¼", paper cone, Parts Express SKU 295-356 at ~$6), which would have cost more once Parts Express's flat $9.95 shipping is included. | $17 |

**Subtotal:** ~$190 (Pi 4 + microSD) to ~$215 (Pi 5 + SSD). Higher than initial roadmap estimates: Pi board prices have crept up since the original BOM, and the genuine ReSpeaker HAT is ~2× the clone.

### Maintainer-supplied
- Raspberry Pi 3 Model B v1.2 on hand — used as the Phase 0 bench. Not shipped to parents; limits to remember are 1 GB RAM, 2.4 GHz-only Wi-Fi, and onboard Bluetooth that can't do HFP reliably.
- 3D-printed enclosure (designed and printed at home).
- USB-C cable for power.
- A laptop, used once, to flash the SD/SSD with Raspberry Pi Imager.

### Explicitly not needed
- HDMI cable, monitor, keyboard, mouse — Imager handles headless setup.
- USB hub or ethernet cable.
- Off-the-shelf case.
- Battery / UPS HAT (not for v1).

---

## 4. Enclosure Considerations

3D-printed by the maintainer. Constraints on the print, not a design:

- **Sealed speaker chamber** behind the driver (~50–150 mL for a
  1–2" full-range). Open-back sounds thin; sealed is simpler than a
  tuned port and sufficient for voice.
- **Mic ports**: small holes over the HAT's two mic locations, thin
  walls (1–2 mm), no long tunnels (they create resonance peaks).
- **Mechanical mic isolation** between mic-bearing PCB and speaker
  mount (rubber grommet or TPU). Cuts vibration coupling, which is
  what mainly breaks echo cancellation.
- **Pi 5 thermal venting** on the opposite side from the speaker
  chamber, so vents don't break the acoustic seal.
- **No external controls or indicators.** Smooth surface except for
  mic ports, speaker grille, USB-C entry, and vents.
- **Strain-relieved USB-C entry** so the cable can't yank the
  connector off the Pi when the device is moved.

---

## 5. Software Architecture

### 5.1 Current state

Two single-turn CLI tools exist, both in `src/`:

- `converse.py` — **press-to-talk, validated.** Records a fixed
  window, sends it to `qwen3-omni-flash` as a streaming request,
  plays the response. Confirmed end-to-end on Pi 3 + ReSpeaker
  2-Mics HAT V2 + Dayton DMA45-4 driver, replying in Sichuan
  dialect with the Sunny voice. Round-trip ~5–6 s over 2.4 GHz.
- `chat_omni.py` — **realtime, partly working on Pi.** Full-duplex
  WebSocket to `qwen3-omni-flash-realtime`. Session opens, mic
  audio uploads, server-VAD fires, transcript and `response.done`
  arrive — but no `response.audio.delta` payloads. Same code works
  from the Mac; root cause not yet found. Suspected Pi-specific
  buffering or SDK behavior. Tracked as a Phase 1 open item.

Neither is yet a daemon. Neither has wake-word detection, end-of-
speech detection, multi-turn memory, or a reliability layer.

### 5.2 Target shape

```
                ┌──────────────────────────────┐
                │  systemd service             │
                │  Restart=always               │
                └──────────────┬───────────────┘
                               │
                               ▼
   ┌────────────┐        ┌────────────────┐     audio I/O
   │ ReSpeaker  │◀──────▶│ speaker daemon │◀───────────▶ PyAudio
   │   HAT      │        │ (Python)       │
   └────────────┘        └──┬─────────┬───┘
                            │         │
                            │         └──▶ local wake-word + VAD
                            │
                            │  realtime: WebSocket (wss)
                            │  or
                            │  press-to-talk: HTTPS request/response
                            ▼
                  DashScope Qwen Omni (Alibaba Singapore)
                  (qwen3-omni-flash-realtime
                   or qwen3-omni-flash)
```

A single Python daemon owns audio I/O, the local wake-word detector,
end-of-speech detection, the DashScope session, audio-cue playback,
reconnect logic, and multi-turn message history within a conversation.
Transport — realtime WebSocket vs press-to-talk HTTPS — is a runtime
choice; the same daemon supports both, and v1 may ship one or both.
A lightweight heartbeat task within the daemon publishes liveness to
a maintainer-controlled endpoint.

### 5.3 Concerns to address (specifics decided per phase)

- **Wake-word detection.** Runs on-device; no audio leaves the Pi
  until it fires. Library (openWakeWord, Porcupine, etc.) and phrase
  chosen in Phase 1. Pi 3 RAM (1 GB) may rule out heavier libraries —
  this is part of the Pi 4/5 decision.

- **End-of-speech detection.** Press-to-talk currently uses a fixed
  5 s window. v1 needs "stop when user pauses" so utterances are not
  truncated and silences are not wasted. Realtime path gets this
  for free from server-side VAD; press-to-talk needs an on-device
  VAD (WebRTC VAD or similar).

- **Multi-turn memory within a conversation.** The bot should
  remember "what we were just talking about" across two or three
  follow-up turns. Realtime path: server keeps state per session.
  Press-to-talk path: client sends prior `messages` array each turn,
  capped at a small history window. Required for v1; do not confuse
  with cross-conversation memory which is out of scope.

- **Realtime audio-delta missing on Pi.** `chat_omni.py` from a Pi
  receives `response.audio_transcript.delta` and `response.audio.done`
  but never the actual `response.audio.delta` payload. Same code,
  same SDK, same key works from Mac. Debug owner: Phase 1.

- **Audio cues for state.** Short pre-recorded WAVs for boot, wake,
  errors, and prolonged offline. Replaces the LED feedback we don't
  have. Shipped with the app — no TTS round-trip for status events.

- **Echo handling.** The bot's voice plays while the mic is hot. At
  minimum, pause the wake-word detector during bot speech. Whether
  we additionally need software AEC depends on what real hardware
  in the enclosure actually does — a Phase 1 finding.

- **Reliability.** `systemd` with restart and network-online deps;
  clean WebSocket reconnect; log size caps; SSD boot if used. Daemon
  waits for `systemd-timesyncd` before opening WSS — after a power
  outage the clock is wrong, which silently breaks TLS.

- **Remote access.** Tailscale installed and authenticated at the
  maintainer's home before transport, so SSH works regardless of the
  parents' router/NAT/ISP. A fallback Wi-Fi SSID (e.g. maintainer's
  hotspot) is also pre-configured.

- **Health alerting.** Device pushes a heartbeat to a maintainer-
  controlled endpoint; missing heartbeats notify the maintainer's
  phone. This is the only signal that something broke — parents will
  not call to report it. Cadence, escalation, payload, and channel
  decided in Phase 1.

- **Cost protection.** Two layers: hard caps in the Alibaba console
  (last-line safety net) and on-device usage limits with a graceful
  degraded mode. Units and thresholds depend on DashScope's billing
  granularity and a real-world baseline.

### 5.4 Deliberately out of v1

Voice barge-in (requires realtime path to be working and a real AEC
strategy), bot-initiated speech, on-device Wi-Fi onboarding, battery
backup, cross-conversation memory across sessions, and a polished
Sichuanese persona prompt — all deferred to later phases.

---

## 6. Phased Roadmap

### Phase 0 — Bench prototype (complete)
- ✅ `chat_omni.py` works end-to-end from a laptop, over WebSocket, in
  Sichuan dialect.
- ✅ `chat_omni.py` boots and runs the WebSocket against DashScope from
  the on-hand Pi 3 Model B v1.2 (driven over SSH from the laptop).
- ✅ Mount the ReSpeaker 2-Mics HAT V2 + Dayton DMA45-4 driver on the
  Pi 3. Audio I/O verified — mic captures, speaker plays via Sunny
  voice. Driver = upstream Pi OS `respeaker-2mic-v2_0` overlay (the
  HAT codec is actually a TI TLV320AIC3104, not the WM8960 the listing
  claims). `~/.asoundrc` routes the ALSA default through `plughw:2,0`.
- ✅ `converse.py` (press-to-talk) runs end-to-end on Pi 3 over 2.4 GHz
  Wi-Fi to Alibaba SG. Round-trip ~5–6 s. Reply quality acceptable in
  Sichuan dialect with a system prompt.
- ⏸ `chat_omni.py` (realtime) connects from the Pi and sees server
  transcript/done events, but no `response.audio.delta` payloads arrive
  on Pi specifically. Same code works from Mac. Carried into Phase 1 as
  an explicit debug task; do not block Phase 1 on it.
- ⏸ Pi 3 → Pi 4/5 decision deferred to Phase 1 once wake-word library
  is picked and RAM/CPU footprint is known.

### Phase 1 — Standalone wake-word device (MVP shipped to parents)

Conversation-shape work (turns the prototype into a usable Alexa-like
interaction):
- ⬜ Wake-word library + phrase. Continuous on-device detection,
  acceptable CPU/RAM (gates the Pi 4/5 choice).
- ⬜ End-of-speech detection for the press-to-talk path (WebRTC VAD
  on-device, or equivalent). Replaces the fixed 5 s window in
  `converse.py`.
- ⬜ Multi-turn conversation memory within a session. Both paths.
- ⬜ Resolve realtime `response.audio.delta` missing on Pi (carried
  from Phase 0). If solvable, ship both realtime and press-to-talk
  behind a runtime flag; if not, ship press-to-talk only.
- ⬜ Daemon shape: wake → record/stream → reply → follow-up window →
  idle. Clean reconnect on network blips.

Device-shape work (makes it deployable to parents):
- ⬜ Record audio cues and ship as WAV assets.
- ⬜ Echo handling: at minimum gate the wake-word detector during bot
  speech. Decide on additional AEC after measuring on real hardware
  in the enclosure.
- ⬜ Cost protection: Alibaba console hard caps + on-device usage
  limits with a graceful degraded mode.
- ⬜ Reliability layer: systemd unit, time-sync wait before any cloud
  call, log caps, SSD boot if used.
- ⬜ Remote access: Tailscale + fallback hotspot SSID + parents' Wi-Fi
  pre-flashed before transport.
- ⬜ Health alerting: heartbeat endpoint, daemon posts to it,
  missing-heartbeat alert to maintainer's phone.
- ⬜ 3D-printed enclosure v1.
- ⬜ Multi-week soak at maintainer's home, including forced Wi-Fi
  outage, unclean shutdown, and cloud-session kill. Verify recovery
  and that health alerts fire.
- ⬜ Transport and install at parents'.

### Phase 2 — Quality of life
- ⬜ Safer OTA updates with rollback (so a bad update doesn't brick a
  device 1000 km away).
- ⬜ Surface multi-turn conversation memory cleanly.
- ⬜ Refine wake-word with real false-wake and miss data from actual use.
- ⬜ Tune cues, follow-up window, and persona based on observed
  behavior at the parents'.

### Phase 3 — Nice-to-haves
- ⬜ On-device Wi-Fi onboarding (AP-mode setup flow) so a future
  router change doesn't require a re-flash.
- ⬜ UPS HAT and battery for power-blip tolerance.
- ⬜ Far-field upgrade (e.g. ReSpeaker 4-Mic Array) if room acoustics
  require it.
- ⬜ Stronger Sichuanese persona prompt to resist Mandarin drift
  when the user code-switches.
- ⬜ Bot-initiated speech for reminders or notifications.

---

## 7. Document Status

- Created: 2026-06-11
- Last updated: 2026-06-20
- Owner: maintainer
- Next review: when Phase 1's first conversation-shape items (wake
  word, end-of-speech, multi-turn, realtime audio-delta debug) start
  landing — at that point the Pi 4 vs Pi 5 decision should be
  informed by real numbers and the realtime-vs-press-to-talk
  ship/skip question should be answerable.
