# Deployment on the Pi

The speaker runs as a systemd **user** service on the Pi so it starts
at boot, restarts on crash, and doesn't depend on anyone being SSHed
in. Unit file: [`deploy/sichuan.service`](../deploy/sichuan.service).

Installed on the Pi 2026-07-19.

## Prerequisites (one-time, per Pi)

Assume `~/sichuan/` is populated (venv + code + models) and PulseAudio
is masked (see `docs/smart-speaker.md §5` for the codec / PulseAudio
notes).

```bash
# In the venv.
~/sichuan/.venv/bin/pip install -r ~/sichuan/requirements.txt
# webrtcvad needs the legacy pkg_resources shim; setuptools ≥81 drops it
~/sichuan/.venv/bin/pip install "setuptools<81"
```

Models, in `~/sichuan/models/` (paths are constants at the top of
`wake_then_converse.py`):

```bash
cd ~/sichuan/models
# Wake-word model. Extract it here; the service reads the dir by name.
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2
tar xf sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2
# End-of-speech VAD. If it is missing the service still starts but silently
# falls back to webrtcvad, logged as "[vad] ... missing" -- and noise reaches
# the cloud about 2.5x as often.
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
# Also needed: wake_keywords.txt (pinyin tokens for 麻婆豆腐; see
# docs/next-session.md §1).
```

## Install / update the service

From this repo on the maintainer machine:

```bash
scp deploy/sichuan.service weilie@sichuan-pi.local:~/.config/systemd/user/sichuan.service
scp src/wake_then_converse.py weilie@sichuan-pi.local:~/sichuan/wake_then_converse.py
ssh weilie@sichuan-pi.local 'systemctl --user daemon-reload && systemctl --user restart sichuan.service'
```

The measurement tools are not part of the service. When one is needed on
the Pi, copy the directory whole — they import the deployed daemon through
`tools/_daemon.py`, so a single tool copied on its own fails to import:

```bash
scp -r tools weilie@sichuan-pi.local:~/sichuan/
```

## First-time setup on the Pi

```bash
# 1. API key → env file (mode 600). Uses the same eval-based extraction
#    that avoids the ~/.bashrc trailing-comment gotcha. Writes whichever of
#    SICHUAN_DASHSCOPE_API_KEY (preferred: the workspace-scoped key) and
#    DASHSCOPE_API_KEY (shared fallback) is in ~/.bashrc, under its own name.
mkdir -p ~/.config/sichuan
umask 077
eval "$(grep -E '^export (SICHUAN_)?DASHSCOPE_API_KEY=' ~/.bashrc)"
for k in SICHUAN_DASHSCOPE_API_KEY DASHSCOPE_API_KEY; do
  [ -n "${!k}" ] && printf '%s=%s\n' "$k" "${!k}"
done > ~/.config/sichuan/env
chmod 600 ~/.config/sichuan/env

# 2. Enable user linger so the service starts at boot without SSH login
sudo loginctl enable-linger weilie

# 3. Enable + start
systemctl --user daemon-reload
systemctl --user enable sichuan.service
systemctl --user start sichuan.service
```

## Verify

```bash
systemctl --user status sichuan.service --no-pager
journalctl --user -u sichuan.service -n 40 --no-pager
```

Look for `[ready] LISTENING for 麻婆豆腐.` in the log — that's the app
past the sherpa-onnx model load and waiting for the wake phrase.

## Reboot test (proves auto-start)

```bash
ssh weilie@sichuan-pi.local sudo reboot
# wait ~60 s
ssh weilie@sichuan-pi.local 'systemctl --user status sichuan.service --no-pager | head -5'
```

Expect `Active: active (running)` without having launched anything.

## Day-to-day commands

```bash
systemctl --user status sichuan.service       # is it up?
systemctl --user restart sichuan.service      # after code changes
systemctl --user stop sichuan.service         # temp stop
systemctl --user disable sichuan.service      # take out of boot
journalctl --user -u sichuan.service -f       # live logs
journalctl --user -u sichuan.service --since '10 min ago' --no-pager
```

## Journal is persistent (changed 2026-09-19)

Raspberry Pi OS ships `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf`
with `Storage=volatile` to spare the SD card, so the whole journal
lived in `/run/log/journal` (tmpfs) and was erased by every reboot —
i.e. the one event most worth investigating destroyed its own
evidence. `/var/log/journal` existed but stayed empty, which is why
`journalctl --user -u sichuan.service` reported "No journal files
were found".

Overridden by `/etc/systemd/journald.conf.d/50-persistent.conf`
(on the Pi, not in this repo):

```
[Journal]
Storage=persistent
SystemMaxUse=50M
SystemMaxFileSize=10M
```

Apply with `sudo systemctl restart systemd-journald && sudo journalctl --flush`.
The caps bound SD-card wear — this service logs a few lines per
turn, not a stream. `weilie` is in the `adm` group, so both of these
work without sudo:

```
journalctl --user -u sichuan.service -n 50     # the service's own output
journalctl -b -1 -n 200                        # the PREVIOUS boot, now retained
```

If this Pi is ever reimaged, re-apply the drop-in: without it every
remote diagnosis starts from zero.

## Non-obvious gotchas

- **User service, not system service.** Under `~/.config/systemd/user/`,
  managed with `systemctl --user`. System-level would need root, more
  awkward audio-group and env plumbing. User + linger is cleaner.
- **`EnvironmentFile=` cannot re-run shell.** The file must be
  `KEY=VALUE` lines (no `export`, no quoting rules). The setup script
  above produces that format from the `export …` line in `.bashrc`.
- **PulseAudio startup noise in the journal is expected.** ALSA
  probes non-existent devices, JACK isn't installed, PulseAudio is
  masked. All harmless. Wait for `[ready] LISTENING…`.
- **The service can start before Wi-Fi is up.** The user manager has no
  `network-online.target` (`systemctl --user status network-online.target`
  says "could not be found"), so the `After=` line that used to name it did
  nothing and was removed 2026-10-07. Harmless today: the first cloud call
  happens on the first wake, and the only boot-time network calls, one TTS
  call per cached phrase (four holding phrases plus six command
  acknowledgements, ten on a first boot), are all skipped once the files
  exist. A wording added to `FILLER_PHRASES` or `COMMAND_ACKS` costs one such
  call on the next boot, so a boot with no network simply leaves that phrase
  out until the next one. Revisit if boot ever needs the network.
- **The Pi's timezone does not matter to the search date.** The date sent
  with search queries is pinned to `DEVICE_TZ` (Asia/Shanghai) in code. The Pi
  itself is set to America/New_York, which is fine.
- **Restart=on-failure, RestartSec=5** — a hung `KeyboardInterrupt`
  exits cleanly and won't restart; a real crash restarts in 5 s.
