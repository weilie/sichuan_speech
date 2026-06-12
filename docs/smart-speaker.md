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
- **Inference is cloud-side.** DashScope `qwen3-omni-flash-realtime`
  over full-duplex WebSocket. The Pi only does audio I/O, wake-word,
  and orchestration — no heavy local ML.
- **Latency budget.** Conversational. Dominated by network RTT to
  Alibaba Singapore, not the Pi.
- **Cost-bounded.** DashScope is metered. The device must not be
  able to silently burn through the budget if something gets stuck.

---

## 3. Hardware Bill of Materials

### Core build

| Item | Notes | ~USD |
|---|---|---|
| Raspberry Pi 5, 4 GB | Wi-Fi 5 dual-band matters for latency to Alibaba SG | $60 |
| Official 27 W USB-C PSU | Pi 5 is strict about power; off-brand chargers cause undervoltage | $12 |
| Active Cooler for Pi 5 | Without it the Pi throttles under sustained load | $5 |
| ReSpeaker 2-Mic Pi HAT | Dual mics, WM8960 codec, JST speaker connector. The HAT's button and 3 RGB LEDs are left unused. | $15–18 |
| USB SSD 128 GB (preferred) **or** A2 high-endurance microSD 64 GB | SSD is far more reliable for 24/7 operation. SD cards are the #1 failure mode for always-on Pi deployments. | $20 / $12 |
| Full-range speaker driver, 3 W / 4 Ω | E.g. Dayton Audio CE32A-4. Far better than the $3 JST blob commonly bundled with the HAT. | $12 |

**Subtotal:** ~$125 with SSD, ~$115 with endurance microSD.

### Maintainer-supplied
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

`src/chat_omni.py` is a working CLI tool that does full-duplex voice
chat over a WebSocket to DashScope's `qwen3-omni-flash-realtime`. It
runs on a laptop today. It is not yet a daemon, has no wake-word
detection, no reliability layer, and assumes a human is at the terminal.

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
                            │         └──▶ local wake-word detector
                            │
                            │ WebSocket (wss) — opened only on wake
                            ▼
                  DashScope Qwen3-Omni-Flash-Realtime
                        (Alibaba Singapore)
```

A single Python daemon owns audio I/O, the local wake-word detector,
the DashScope WebSocket session (opened on wake, closed at end of
conversation), audio-cue playback, and reconnect logic. A lightweight
heartbeat task within the daemon publishes liveness to a maintainer-
controlled endpoint.

### 5.3 Concerns to address (specifics decided per phase)

- **Wake-word detection.** Runs on-device; no audio leaves the Pi
  until it fires. Library (openWakeWord, Porcupine, etc.) and phrase
  chosen in Phase 1.

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

Voice barge-in, bot-initiated speech, on-device Wi-Fi onboarding,
battery backup, cross-conversation memory beyond the model's default,
and a polished Sichuanese persona prompt — all deferred to later phases.

---

## 6. Phased Roadmap

### Phase 0 — Bench prototype (in progress)
- ✅ `chat_omni.py` works end-to-end from a laptop, over WebSocket, in
  Sichuan dialect.
- ⬜ Bring up the same script on a Raspberry Pi 5 with the ReSpeaker
  HAT and a real speaker.
- ⬜ Confirm round-trip latency over residential Wi-Fi is
  conversational.
- ⬜ Confirm the ReSpeaker HAT and chosen speaker driver work
  together at acceptable volume and clarity in a representative room.

### Phase 1 — Standalone wake-word device (MVP shipped to parents)
- ⬜ Pick a wake-word library and phrase; get continuous on-device
  detection working without burning CPU.
- ⬜ Refactor `chat_omni.py` into a daemon: wake → open WebSocket →
  stream conversation → follow-up window → close. Clean reconnect.
- ⬜ Record audio cues and ship as WAV assets.
- ⬜ Decide and implement echo handling (gate, AEC, or both) on real
  hardware.
- ⬜ Cost protection: Alibaba console caps + on-device usage limits
  with a graceful degraded mode.
- ⬜ Reliability layer: systemd unit, time-sync wait before WSS, log
  caps, SSD boot if used.
- ⬜ Remote access: Tailscale + fallback hotspot SSID + parents'
  Wi-Fi all pre-flashed before transport.
- ⬜ Health alerting: heartbeat endpoint, daemon posts to it,
  missing-heartbeat alert to maintainer's phone.
- ⬜ 3D-printed enclosure v1.
- ⬜ Multi-week soak at maintainer's home, including forced Wi-Fi
  outage, unclean shutdown, and WebSocket kill. Verify recovery
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
- Last updated: 2026-06-11
- Owner: maintainer
- Next review: after Phase 0 bench validation on real Pi 5 hardware.
