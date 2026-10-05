# Sichuan Smart Speaker — Roadmap

A standalone, Alexa-style smart speaker that listens and responds in
Sichuan dialect, built on a Raspberry Pi 3 (decided 2026-07-02; see
Phase 1) and deployed at the maintainer's parents' home, roughly 1000 km
away.

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
  paths were built — `qwen3-omni-flash-realtime` over a WebSocket
  (low latency; barge-in is blocked by the half-duplex HAT codec, see
  §5.3) and the non-realtime `qwen3-omni-flash` request/response API
  (simpler, validated end-to-end on Pi 3). The non-realtime path shipped
  (`wake_then_converse.py`); `chat_omni.py` is not used by the service.
  The Pi only does audio I/O, wake-word, end-of-speech detection and
  orchestration — no heavy local ML.
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
| Raspberry Pi 3 Model B | **Decided 2026-07-02: the on-hand Pi 3 ships** (see §6 Phase 1); the Pi 4/5 analysis below is kept for reference. Phase 0 already showed: 2.4 GHz Wi-Fi is fast enough for the cloud call (5–6 s round-trip), and 1 GB RAM is sufficient for `chat_omni.py` or `converse.py` running alone. The open question then, whether continuous wake-word detection fits *alongside* the chat daemon, was answered yes. Pi 4 4 GB ~$100 (CanaKit/PiShop), Pi 5 4 GB ~$130 (Adafruit); Pi 3 is $0 (already on hand). | $0–130 |
| Official USB-C PSU | Pi 5 needs the 27 W official PSU; Pi 4 is happy with any ~15 W USB-C. Off-brand chargers cause undervoltage. | $8–12 |
| Active cooler | Pi 5: official Active Cooler. Pi 4: heatsink + small fan. Without it the Pi throttles under sustained load. | $5 |
| ReSpeaker 2-Mics Pi HAT (genuine Seeed) | Dual mics, JST speaker connector (the listing says WM8960; the codec is actually a TI TLV320AIC3104). The HAT's button and 3 RGB LEDs are left unused. Ordered 2026-06-13 from Amazon (B07CXSW6LB). Cheaper KEYESTUDIO clones exist (~$12) but the genuine board has better driver/community support. Compatible with Pi 3, 4, and 5. | $40 |
| USB SSD 128 GB (preferred) **or** A2 high-endurance microSD 64 GB | SSD is far more reliable for 24/7 operation. SD cards are the #1 failure mode for always-on Pi deployments. Pi 5 boots from USB 3.0 SSD or NVMe (with adapter HAT); Pi 4 boots from USB 3.0 SSD. | $20 / $12 |
| Full-range speaker driver, 3 W / 4 Ω | Ordered the Dayton Audio DMA45-4 (1½", aluminum cone) from Amazon (B07N1YW3SV). This is a substitute for the originally spec'd Dayton CE32A-4 (1¼", paper cone, Parts Express SKU 295-356 at ~$6), which would have cost more once Parts Express's flat $9.95 shipping is included. | $17 |

**Subtotal:** ~$190 (Pi 4 + microSD) to ~$215 (Pi 5 + SSD). Higher than initial roadmap estimates: Pi board prices have crept up since the original BOM, and the genuine ReSpeaker HAT is ~2× the clone.

### Maintainer-supplied
- Raspberry Pi 3 Model B v1.2 on hand — used as the Phase 0 bench. Not shipped to parents; limits to remember are 1 GB RAM, 2.4 GHz-only Wi-Fi, and onboard Bluetooth that can't do HFP reliably.
- 3D-printed enclosure (designed and printed at home).
- Power supply and a short, thick micro-USB cable (Pi 3; cable quality matters more than the brick, see the Phase 1 gotchas).
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

Three programs matter in `src/`:

- `wake_then_converse.py` — **the deployed daemon.** Wake word
  (sherpa-onnx), on-device end-of-speech detection (Silero VAD),
  multi-turn conversation within a session, and the two-round search
  path (§5.1a), run as a systemd user service (`docs/deployment.md`).
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

The last two have none of the daemon's machinery. Cross-session
memory, health alerting and the rest of the reliability layer (§5.3)
are still open.

### 5.1a Web search: the two-round path (2026-09-19)

Real-time questions (weather, prices, news) are answered by two
cloud calls per turn, because search and persona cannot coexist in
one call on this API:

- **Round 1 — research.** Raw audio in, text out, `enable_search`
  on, and deliberately **no system prompt and no instruction of any
  kind**. Measured on this Pi, *any* instruction in the search call
  drops `search_results` to empty and the model invents a number
  instead — asked one city's temperature it answered 24, 30, 32 on
  consecutive tries. This is the single non-obvious finding of the
  whole feature.
- **Round 2 — voice.** Round 1's facts as text, restyled through
  the Sichuan persona. Text-only input measures 3.4 s against
  4.6–5.2 s with the audio re-attached, and time-to-first-audio
  halves.

**Round 2 runs speculatively, in parallel with round 1.** It
answers the raw audio on the bet that the turn needs no search
(the common case). If round 1 reports sources, the speculative
stream is aborted mid-flight and the restyle runs instead. Serial
rounds made every ordinary turn slower than before search existed;
speculation gives that back — a chat turn is ~4.7 s end-to-end, a
search turn ~8 s. The decision keys on **sources, not on whether
round 1 returned text**: round 1 answers plenty from its own
knowledge, and when it did not search, the speculative reply is
the better one because it heard the question itself.

Two prompt bugs found while validating this, both worth
remembering because both produced *plausible* wrong output:

- Rail 7 stated the "我这儿查不到" refusal twice (a leftover from
  the pre-search wording). With 15 sources in hand the model still
  refused, then hedged. One statement of a refusal, never two.
- The restyle instruction never said where the text came from, so
  the model treated verified search results as background chatter.
  It must say the facts are looked-up and correct.

### 5.1b qwen3.8-omni-flash evaluated and rejected (2026-09-19)

Released 2026-09-18. Text/image/audio/video in, **text out only** —
no speech synthesis, so it can never replace round 2. It fits round
1's shape exactly and prices audio input ~98% lower, so it looked
like a free upgrade. It is not. Medians over 3 reps from the Pi,
with `enable_thinking=False` (its default reasoning is far worse —
5.1 s and 11.7 s):

- chat turn: 3.5-omni-flash **1.2 s** vs 3.8 **1.9 s**
- search turn: 3.5-omni-flash **3.2 s** vs 3.8 **7.0 s**

Round 1 is on the critical path of every turn under speculation, so
that is the speculation win handed straight back.

The disqualifying result was not latency. Fed a near-silent capture
(a dead turn), 3.5 said the message seemed incomplete; **3.8
invented a question, ran 29 searches, and answered confidently
about UC Berkeley.** A weak mic in an elderly household produces
marginal captures constantly, and confabulating through them is the
wrong failure mode for this device. `RESEARCH_MODEL` is a separate
constant so the swap is one line if a later revision degrades more
gracefully. Note the model id is `qwen3.8-omni-flash`; the
`qwen3-8-omni-flash` spelling some write-ups use returns
`Model not exist`.

### 5.2 Target shape

```
                ┌──────────────────────────────┐
                │  systemd service             │
                │  Restart=on-failure           │
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

- **End-of-speech detection.** Landed: `wake_then_converse.py` stops
  when the user pauses, using an on-device VAD (Silero, with webrtcvad
  as fallback). `converse.py` still uses a fixed 5 s window. The
  realtime path gets this from server-side VAD.

- **Multi-turn memory within a conversation.** The bot should
  remember "what we were just talking about" across two or three
  follow-up turns. Realtime path: server keeps state per session.
  Press-to-talk path: client sends prior `messages` array each turn,
  capped at a small history window (3 exchanges in
  `wake_then_converse.py`). Do not confuse with cross-conversation
  memory, which is out of scope.

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

- **Reliability.** `systemd` user service with restart, and a
  persistent, size-capped journal (both landed; `network-online`
  ordering is a no-op in a user unit, see `docs/deployment.md`). Still
  open: clean reconnect after network blips, detecting a hung (not
  crashed) process, SSD boot if used. The daemon should also wait for
  `systemd-timesyncd` before opening a TLS connection — after a power
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
- ✅ Pi 3 → Pi 4/5 decision resolved 2026-07-02: **Pi 3 ships.**
  Rebenchmarked wake + converse under load, all four gating
  criteria met. Detail in the Phase 1 block below.

### Phase 1 — Standalone wake-word device (MVP shipped to parents)

Conversation-shape work (turns the prototype into a usable Alexa-like
interaction):
- ✅ Wake-word library + phrase. **Switched to sherpa-onnx KWS
  with the pretrained `sherpa-onnx-kws-zipformer-wenetspeech-3.3M-
  2024-01-01` Chinese pinyin model** on 2026-07-04 (commit
  `8566def`), replacing an initial openWakeWord + `hey_jarvis`
  prototype. Rationale: research on 2026-07-03 found no public
  community-trained Chinese openWakeWord models and the official
  training pipeline is broken on current Colab, whereas sherpa-onnx
  ships a working pretrained Chinese KWS model with dialect
  robustness that plays fine on Pi 3. Wake phrase is 麻婆豆腐,
  encoded as pinyin tokens in a keywords file; swapping to another
  Chinese phrase is a one-line change after re-tokenising via
  `sherpa_onnx.text2token`. Detail in `docs/next-session.md` §1.
- ✅ **Pi 3 vs Pi 4 gating benchmark.** With the chosen wake-word
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

   **2026-06-20 status (partial):** openWakeWord (`hey_jarvis`) on
   Pi 3 v1.2 + HAT V2 fired with scores 0.63–1.00 when CPU was not
   throttled. RSS ~244 MB, predict ~92 ms/chunk (one core saturated,
   three idle). Detection then **stopped firing** as sustained load
   pushed the Pi into `throttled=0x50005` (under-voltage AND
   currently-throttled). Temp was only 52 °C — *the throttle is from
   inadequate 5 V supply, not heat*. The benchmark is therefore
   inconclusive: Pi 3 may be CPU-sufficient if given a proper
   5.1 V / 2.5 A PSU. To re-run cleanly: swap to a known-good Pi 3
   PSU (or compare with Pi 4 + official 27 W USB-C), then rerun
   the four-criterion soak.

   **2026-07-02 verdict: Pi 3 ships.** Rebenchmarked wake +
   converse end-to-end with a MacBook Pro USB-C brick +
   USB-C→USB-A adapter + a better micro-USB cable. Throttle
   stayed at `0x50000` (only "occurred since boot" latches, no
   currently-active under-voltage) through repeated wake +
   converse turns. RSS ~267 MB, one core ~55 %, three cores idle,
   temp peaks 58 °C. Wake fires at scores 0.78–0.98. Full turn
   latency ~15 s (0.34 s beep + 5 s record + ~10 s cloud round
   trip + playback). All four gating criteria met. Prototype code:
   `src/wake_then_converse.py`.

   Session-fixed gotchas worth carrying forward:

   - **PulseAudio hijacked the codec.** The default Raspberry Pi
     OS install runs `pulseaudio.socket`/`pulseaudio.service` in
     the user session; PulseAudio holds `/dev/snd/pcmC2D0c` open
     continuously, which turns each `aplay` cold-open into a
     ~30 s stall. Mask both units (`systemctl --user mask
     pulseaudio.socket pulseaudio.service`, then `pkill -9
     pulseaudio`) so the ALSA-direct path through `plughw:2,0`
     is unobstructed. After the fix, `wake→beep` dropped from
     5.28 s to 0.34 s.
   - **Cable dominates power delivery; brick capacity is
     secondary.** Initial failure was a 12 W wall brick + a
     random micro-USB cable → `throttled=0x50005` at idle. A
     Xiaomi 10000 mAh power bank (rated 5.1 V / 2.4 A) with the
     same cable → also inadequate. Swapping in a better
     micro-USB cable made a **5 V / 1 A** brick sufficient to
     run a full wake + converse turn end-to-end, with only brief
     transient under-voltage blips during the burst (cloud
     decode + wake-word + speaker output firing at once) that
     immediately recovered. So the "Pi 3 needs 2.5 A" spec is
     conservative for this workload — the real sustained draw is
     ~400 mA idle and ~800 mA – 1 A under load. Guidance for the
     parents' final unit: budget ≥10 W (5.1 V / 2 A) for
     headroom, but pair with a short thick cable — a marginal
     cable defeats any brick. `vcgencmd get_throttled` at idle
     is the free diagnostic; anything other than `0x0` or
     `0x50000` means the delivery chain is dropping voltage.
   - **API-key export lines with trailing comments are
     fragile.** `~/.bashrc` has
     `export DASHSCOPE_API_KEY=<key> # comment`. Extracting the
     value via `grep | cut -d= -f2` grabs the trailing comment
     along with the key and the cloud rejects it with 401
     `InvalidApiKey`. Prefer
     `eval $(grep '^export DASHSCOPE_API_KEY=' ~/.bashrc)` in
     scripted launches; `bash` correctly discards the comment.
   - **Mixer levels need explicit persistence.** After
     `alsactl store 2`: PCM 85 % (~-10 dB), Line DAC 85 %,
     Line 100 %, HP DAC 0 % (muted) survives reboot. HP muted
     eliminates any accidental audio to a 3.5 mm jack; all
     playback goes through the HAT speaker terminals.
- ✅ End-of-speech detection for the press-to-talk path (on-device VAD).
  Replaces the fixed 5 s window in `wake_then_converse.py`. Landed
  2026-07-17 with webrtcvad; swapped to Silero 2026-09-28, webrtcvad kept
  as the fallback. Turn-taking + session-boundary logic:
  - **Utterance:** 20 ms VAD frames, 300 ms pre-speech ring buffer,
    120 ms voiced-onset threshold, 1400 ms trailing-silence close
    (800 ms until 2026-09-19), 30 s hard cap per utterance.
  - **Session:** after wake beep, keep listening for follow-ups
    with no arbitrary turn or wall-clock cap. Silence timeout is
    adaptive — 8 s on turn 1, 6 s on follow-ups, 2.5 s after a
    dead turn.
  - **Noise guardrail:** a "dead turn" is any turn where the
    capture was < 400 ms or had no speech-like voicing (local
    reject, no cloud call), or the cloud returned no audio. Two consecutive dead turns end the
    session. Any successful reply zeros the counter and relaxes
    the silence window. Effect: a noisy room burns at most 2 cloud calls.
    Speech-like noise (a TV) is not caught by this, so a session
    is also capped at 10 cloud turns (`MAX_SESSION_TURNS`), ending
    with a spoken sign-off.
  - Only applies to the press-to-talk (`wake_then_converse.py`)
    path. Realtime path gets end-of-speech from server-side VAD.
- ✅ Multi-turn conversation memory within a session (commit
  `41d81d2`). The press-to-talk path replays the last 3 exchanges,
  audio included; the realtime path keeps state server-side.
- ✅ Transport: the non-realtime request/response path ships
  (`wake_then_converse.py`). Realtime would give ~1–2 s lower
  time-to-first-audio, at the cost of a fragile WebSocket lifecycle
  and the codec hand-off; `chat_omni.py` is kept as a reference and
  the service does not use it.
- ✅ Daemon shape: wake → record/stream → reply → follow-up window →
  idle. Follow-up window landed 2026-07-17; systemd user service
  with auto-restart landed 2026-07-19. See `docs/deployment.md`.
  Still open: cleaner reconnect on network blips. Journal caps landed
  2026-09-19.

Device-shape work (makes it deployable to parents):
- ⬜ Record audio cues and ship as WAV assets.
- ⬜ Echo handling: at minimum gate the wake-word detector during bot
  speech. Decide on additional AEC after measuring on real hardware
  in the enclosure.
- 🟨 Cost protection: a workspace-scoped API key plus
  `tools/usage-report.sh` landed (`4fef894`). Still open: Alibaba console
  hard caps and on-device usage limits with a graceful degraded mode.
- 🟨 Reliability layer: systemd unit (2026-07-19) and persistent, capped
  journal (2026-09-19) landed. Open: time-sync wait before any cloud call,
  detecting a hung (not crashed) process, SSD boot if used.
- ⬜ Remote access: Tailscale + fallback hotspot SSID + parents' Wi-Fi
  pre-flashed before transport.
- ⬜ Health alerting: heartbeat endpoint, daemon posts to it,
  missing-heartbeat alert to maintainer's phone.
- 🟨 3D-printed enclosure. Design in `enclosure/case.scad` (v15c as
  of 2026-09-21): 99×99×47 mm square base + 103×103×33 mm lid,
  snap-fit, Pi rotated 90° for long-axis vertical fit, front-mounted
  DMA45-4 speaker (36 mm screw pattern), cable grommet, LED side slit.
  The v14 print fit-tested cleanly (2026-07-19). **Still open:** the
  v15c test print, with oversized mic ports in the base walls, to see
  whether it recovers the lid-closed wake penalty (re-measure that
  penalty at the current beam width first), and an internal cable
  strain-relief boss. See `docs/next-session.md` §0 and §2.
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
- 🟨 Stronger Sichuanese persona prompt. First expansion landed
  2026-07-08 (commit `e699d43`): grandchild persona, 2-3 sentence
  brevity cap, health/finance safety rails, list of colloquialisms
  to sprinkle. Remaining: measure Mandarin drift on real code-
  switched input from parents and tune further.
- ⬜ Bot-initiated speech for reminders or notifications.

---

## 7. Document Status

- Created: 2026-06-11
- Last updated: 2026-09-28 (status brought in line with the code: Silero VAD, two-round search, in-session memory, systemd service and persistent journal, enclosure v15c; earlier: 2026-07-19 systemd user service, enclosure v14)
- Owner: maintainer
- Next review: when Phase 1's first conversation-shape items (wake
  word, end-of-speech, multi-turn memory) start landing — at that
  point the Pi 4 vs Pi 5 decision should be informed by real
  numbers and the realtime-vs-press-to-talk decision should be
  answerable.
