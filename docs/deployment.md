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
# In the venv
~/sichuan/.venv/bin/pip install -r ~/sichuan/requirements.txt
# webrtcvad needs the legacy pkg_resources shim; setuptools ≥81 drops it
~/sichuan/.venv/bin/pip install "setuptools<81"
```

## Install / update the service

From this repo on the maintainer machine:

```bash
scp deploy/sichuan.service weilie@sichuan-pi.local:~/.config/systemd/user/sichuan.service
scp src/wake_then_converse.py weilie@sichuan-pi.local:~/sichuan/wake_then_converse.py
ssh weilie@sichuan-pi.local 'systemctl --user daemon-reload && systemctl --user restart sichuan.service'
```

## First-time setup on the Pi

```bash
# 1. API key → env file (mode 600). Uses the same eval-based extraction
#    that avoids the ~/.bashrc trailing-comment gotcha.
mkdir -p ~/.config/sichuan
umask 077
eval $(grep '^export DASHSCOPE_API_KEY=' ~/.bashrc | tail -1)
printf 'DASHSCOPE_API_KEY=%s\n' "$DASHSCOPE_API_KEY" > ~/.config/sichuan/env
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
- **`After=network-online.target`** is important: first cloud call
  will 500 if it fires before DHCP/DNS settle.
- **Restart=on-failure, RestartSec=5** — a hung `KeyboardInterrupt`
  exits cleanly and won't restart; a real crash restarts in 5 s.
