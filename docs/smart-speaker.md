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
| Raspberry Pi (model TBD) | Decision now gates on the Phase 1 wake-word benchmark on the on-hand Pi 3 (see §6 Phase 1). Phase 0 already showed: 2.4 GHz Wi-Fi is fast enough for the cloud call (5–6 s round-trip), and 1 GB RAM is sufficient for `chat_omni.py` or `converse.py` running alone. The open question is whether continuous wake-word detection fits *alongside* the chat daemon. Pi 4 4 GB ~$100 (CanaKit/PiShop), Pi 5 4 GB ~$130 (Adafruit); Pi 3 is $0 (already on hand). | $0–130 |
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

Two CLI tools exist, both in `src/`:

- `converse.py` — **press-to-talk, validated.** Records a fixed
  window, sends it to `qwen3-omni-flash` as a streaming request,
  plays the response. Confirmed end-to-end on Pi 3 + ReSpeaker
  2-Mics HAT V2 + Dayton DMA45-4 driver, replying in Sichuan
  dialect with the Sunny voice. Round-trip ~5–6 s over 2.4 GHz.
- `chat_omni.py` — **realtime, multi-turn validated.** WebSocket
  to `qwen3-omni-flash-realtime`. Server-VAD detects end of
  speech; client opens/closes the mic around bot reply because
  the HAT codec (TLV320AIC3104) does not let ALSA hold input and
  output concurrently. Multi-turn Sichuan dialect conversation
  reproduced on the bench Pi 3.

Neither is yet a daemon. Neither has wake-word detection, on-
device end-of-speech detection, persistent multi-turn memory
across sessions, or a reliability layer.

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

- **HAT codec is half-duplex.** Reproduced in isolation: when
  PyAudio holds the mic open, output through any path (PyAudio,
  `aplay`, PulseAudio) is silenced. Even a single full-duplex
  PortAudio stream is silenced. This is an ALSA/codec exclusivity
  on the TLV320AIC3104, not a software bug. `chat_omni.py` works
  around it by closing the mic when bot speech starts and
  reopening on `response.done`. Barge-in is *unachievable* on
  this hardware path; pursuing it would require a different audio
  topology (e.g. separate USB mic + USB speaker).

- **PortAudio ALSA errors during mic close/reopen.** The
  transition prints `PaAlsaStream_WaitForFrames` failures to
  stderr but the system recovers each turn. Cosmetic for now;
  worth filing if Phase 1 surfaces an actual reliability impact.

- **Server-side "Response timeout" if user dithers.** Realtime
  WebSocket sessions get killed by the server when there is no
  clear speech soon after `session.updated`. v1 should either
  open the session lazily at wake-time, or send periodic pings.

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
- ✅ `chat_omni.py` (realtime) multi-turn Sichuan-dialect conversation
  works on the Pi 3 + HAT V2 with a half-duplex codec hand-off. Hidden
  hardware constraint discovered: the HAT codec does not allow ALSA to
  hold mic input and audio output at the same time, so barge-in is not
  possible on this hardware path. Documented in §5.3.
- ⏸ Pi 3 → Pi 4/5 decision deferred to Phase 1 once wake-word library
  is picked and RAM/CPU footprint is known.

### Phase 1 — Standalone wake-word device (MVP shipped to parents)

Conversation-shape work (turns the prototype into a usable Alexa-like
interaction):
- ⬜ Wake-word library + phrase. Continuous on-device detection,
  acceptable CPU/RAM (gates the Pi 4/5 choice — see below). Try
  Porcupine first (C, ~10 MB RAM). Fall back to openWakeWord
  (Python + TFLite, ~80–150 MB RAM) only if Porcupine's phrase
  set or false-wake rate is unacceptable.
- ⬜ **Pi 3 vs Pi 4 gating benchmark.** With the chosen wake-word
  library running continuously *alongside* `chat_omni.py`, soak
  for ≥30 min on the bench Pi 3 and measure:
   - `free -m`: working set stays under ~750 MB (≤80% of 1 GB).
   - `top`: idle CPU stays under ~50% on each core; no thermal
     throttling (`vcgencmd get_throttled` returns `throttled=0x0`).
   - End-to-end conversation latency stays under ~6 s on 2.4 GHz Wi-Fi.
   - No PortAudio/ALSA errors that wedge the daemon over the soak.

   If all four pass: Pi 3 ships for v1 (huge BOM savings, SD-card
   lifetime is the only residual risk — mitigated by the A2 high-
   endurance card already in the BOM). If any fail: upgrade to
   Pi 4 (4 GB), which also opens the door to SSD boot for 24/7
   reliability.
- ⬜ End-of-speech detection for the press-to-talk path (WebRTC VAD
  on-device, or equivalent). Replaces the fixed 5 s window in
  `converse.py`.
- ⬜ Multi-turn conversation memory within a session. Both paths.
- ⬜ Decide which transport (or both) ships in v1. Realtime gives
  ~1–2 s lower time-to-first-audio and free server-side VAD, at the
  cost of a fragile WebSocket lifecycle and the codec hand-off
  complexity. Press-to-talk is simpler but needs client-side VAD
  for end-of-speech detection.
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
- Last updated: 2026-06-20 (second pass — realtime path validated)
- Owner: maintainer
- Next review: when Phase 1's first conversation-shape items (wake
  word, end-of-speech, multi-turn memory) start landing — at that
  point the Pi 4 vs Pi 5 decision should be informed by real
  numbers and the realtime-vs-press-to-talk decision should be
  answerable.
