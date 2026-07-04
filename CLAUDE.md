# Sichuan Speech — session guidance

## Read first

- `docs/next-session.md` — active punch list. Two work streams in flight:
  Chinese wake word (switching to sherpa-onnx KWS) and enclosure
  (test-fitting the Snips reference case).
- `docs/smart-speaker.md` — full roadmap, hardware/software constraints
  we've validated, and non-obvious gotchas (PulseAudio, .bashrc
  key-parsing, ALSA mixer persistence, power-cable dominance).

## Repo shape

- `src/converse.py` — press-to-talk, non-realtime path against
  qwen3-omni-flash. Working.
- `src/chat_omni.py` — realtime WebSocket path. Working on Pi 3 + HAT V2.
- `src/wake_then_converse.py` — Phase 1 wake + converse integration.
  Uses openWakeWord `hey_jarvis` today; will be refactored to
  sherpa-onnx KWS with a Chinese wake word (see `docs/next-session.md`).
- `enclosure/snips-reference/` — STLs from Cults3D for reference only,
  no editable source. Future OpenSCAD redesign will use these as
  visual reference.

## Deployment target

Raspberry Pi 3 Model B v1.2 + ReSpeaker 2-Mics Pi HAT V2 + Dayton
DMA45-4 speaker. Code lives on Pi at `~/sichuan/`. Pi's
`~/.asoundrc` routes ALSA default to `plughw:2,0` (HAT card).
PulseAudio must stay masked (session-fixed gotcha — see roadmap).

Final deployment: parents' home 1000 km away, so reliability and
remote-recovery matter more than performance headroom.

## Reaching the Pi

```
ssh weilie@sichuan-pi.local
```

Password: `zaq1ZAQ!` (user is on the same LAN; `.local` resolves via
mDNS). If mDNS ever fails (Pi's IP changed, resolver flake),
fallback:

```
arp -a | grep -iE 'b8:27:eb|dc:a6:32|d8:3a:dd'   # Pi MAC OUIs
```

Typical health check after any downtime:

```
ssh weilie@sichuan-pi.local "uptime && vcgencmd get_throttled && vcgencmd measure_temp"
```

Interpretation of `vcgencmd get_throttled`:
- `0x0` — clean
- `0x50000` — clean now; under-voltage occurred at boot (expected
  latch, benign)
- `0x50005` — active under-voltage right now. Swap cable or PSU
  before running any load test.

The venv on the Pi is `~/sichuan/.venv/` (activate with
`source ~/sichuan/.venv/bin/activate`). DASHSCOPE_API_KEY lives in
`~/.bashrc` with a trailing comment. To load it non-interactively
(nohup, systemd, etc.):

```
eval $(grep '^export DASHSCOPE_API_KEY=' ~/.bashrc | tail -1)
```
NOT `cut -d= -f2` — that grabs the trailing comment as part of the
key and DashScope rejects it with 401.

## Conventions

- Commit new features and bug fixes; don't commit ephemeral debug
  instrumentation (timings, pprints) unless the finding gets rolled
  into docs.
- Roadmap doc `docs/smart-speaker.md` is the source of truth for
  "what we've learned"; `docs/next-session.md` is the source of
  truth for "what we do next."
- Sichuan-dialect responses are enforced via the system prompt in
  `src/converse.py` / `src/wake_then_converse.py`. Preserve it if
  refactoring.
