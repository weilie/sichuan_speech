# Sichuan Speech — session guidance

## Read first

- `docs/next-session.md` — active punch list. Current focus: re-measure
  lid-closed wake recall at the beam-16 setting (§0) before spending more
  print time; the v15c enclosure test print (mic ports in the base walls)
  is the open enclosure item.
- `docs/smart-speaker.md` — full roadmap, hardware/software constraints
  we've validated, and non-obvious gotchas (PulseAudio, .bashrc
  key-parsing, ALSA mixer persistence, power-cable dominance).
- `docs/deployment.md` — the systemd user service on the Pi: install /
  update commands, env file, persistent journal, gotchas.

## Repo shape

- `src/converse.py` — press-to-talk, non-realtime path against
  qwen3-omni-flash. Working.
- `src/chat_omni.py` — realtime WebSocket path. Works on Pi 3 + HAT V2,
  but the service does not use it, it sends no persona prompt, and it
  reads only `DASHSCOPE_API_KEY`.
- `src/wake_then_converse.py` — the deployed daemon: wake word, then a
  multi-turn conversation (Silero VAD endpointing with a webrtcvad
  fallback; two-round web-search path). Uses sherpa-onnx KWS with wake
  phrase 麻婆豆腐 (pinyin-tokenised; keyword file at
  `~/sichuan/models/wake_keywords.txt` on the Pi). The date sent with
  search queries is pinned to Asia/Shanghai in code, so the Pi's own
  timezone does not matter.
- `src/utils.py`, `src/transcribe.py`, `src/synthesize.py` — ASR / TTS
  CLIs and the shared API-key setup.
- `tools/` — measurement scripts (wake / VAD sweeps, corpus recording,
  `usage-report.sh`). Most import `wake_then_converse` and expect the Pi's
  `~/sichuan` paths.
- `deploy/sichuan.service` — the systemd user unit; see `docs/deployment.md`.
- `enclosure/case.scad` — OpenSCAD source of truth for the enclosure.
  Rendered STLs (`enclosure/base.stl`, `enclosure/lid.stl`) are
  regenerated from this. Iterate: edit `.scad` → `openscad -o
  base.stl -D 'part="base"' case.scad` (same for `"lid"`).
- `enclosure/snips-reference/` — original Cults3D STLs, kept only as
  historical reference (not used for the current design).

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
`source ~/sichuan/.venv/bin/activate`). The API key lives in
`~/.bashrc` with a trailing comment. To load it non-interactively
(nohup, systemd, etc.):

```
eval $(grep -E '^export (SICHUAN_)?DASHSCOPE_API_KEY=' ~/.bashrc | tail -1)
```
NOT `cut -d= -f2` — that grabs the trailing comment as part of the
key and DashScope rejects it with 401.

The code prefers `SICHUAN_DASHSCOPE_API_KEY` and falls back to
`DASHSCOPE_API_KEY`, logging `[boot] using the shared
DASHSCOPE_API_KEY` when it does. Alibaba bills Model Studio per
WORKSPACE, not per key, so only a key created inside its own
workspace gives this device a separate line on the bill —
`tools/usage-report.sh` groups spend that way.

Also: the DashScope SDK must be pointed at the international
endpoint (`dashscope.base_http_api_url =
"https://dashscope-intl.aliyuncs.com/api/v1"`) or a valid key comes
back as `Invalid API-key provided`.

## Conventions

- Commit new features and bug fixes; don't commit ephemeral debug
  instrumentation (timings, pprints) unless the finding gets rolled
  into docs.
- Roadmap doc `docs/smart-speaker.md` is the source of truth for
  "what we've learned"; `docs/next-session.md` is the source of
  truth for "what we do next."
- The system prompt in `src/converse.py` / `src/wake_then_converse.py`
  does more than dialect enforcement — it also fixes persona ("filial
  grandchild talking to elders"), enforces brevity (2-3 sentences),
  and sets safety rails for medical / health / money topics. Preserve
  those aspects if refactoring; feel free to iterate on wording.
