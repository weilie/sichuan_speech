# Code review — 2026-10-07

Branch `voice-clone-trial`, working tree including the uncommitted v16
enclosure diff, the `usage-report.sh` daily section and the untracked
`tools/voice_clone.py`. Every source file was read in full.

**TL;DR:** no serious defects. Four small real bugs, a cluster of
tool/daemon drift that can make the next measurement describe a detector you
no longer ship, and about 200 lines of dead code plus a dozen stale doc
references left behind by the enclosure and VAD changes.

Revised 2026-10-07 after a second review: six factual slips corrected (noted
inline in items 2, 3, 4, 9, 14, 15), item 11 moved from P2 to P3, and the
fan-out claim under Verified given its proper scope. No finding was
overturned.

**Status (2026-10-07):** implemented on branch `review-fixes-2026-10`, except
three items left on purpose: the `endpoint()` timeout semantics (item 15,
changing it needs a corpus run), the per-session Silero reload (item 15,
unmeasured), and the Y-wall port branch (item 13, waits for the v16
measurement). One deviation from item 3's fix: the shared KWS code stays in
the daemon and the tools reach it through `tools/_daemon.py` rather than a
new `src/kws.py`; the Pi runs a single copied file, and a second module
would be one more thing a redeploy can forget 1000 km away. An independent
agent then reviewed the branch and found two regressions in the first
implementation (items 1 and 4, corrected as described there) plus: mic opens
now go through `open_input()` under `AUDIO_LOCK` instead of a wait at each
call site; the noise gate is one function, `gate_reason()` /
`passes_gate()`, used by the daemon and imported by the tools;
`sweep_vad.py` builds one VAD per setting and resets it per capture;
`sweep_kws.py` builds one spotter per cell; the deployment guide says to
copy `tools/` whole because of `_daemon.py`.

Priority scale:

- **P1** — changes what the parents hear, can crash the deployed daemon, or
  can produce a wrong measurement that drives a decision. Do before the next
  deploy or the next corpus run.
- **P2** — robustness or maintainability; fix the next time the file is
  touched.
- **P3** — hygiene; batch into one cleanup commit.

## Verified

- `PYTHONPATH=src python3 -m unittest discover -s tests`: 33 tests, all pass.
- `enclosure/base.stl` and `enclosure/lid.stl` are byte-identical to a fresh
  OpenSCAD render of the working-tree `case.scad`; both render with no
  warnings. The v16 numbers in `docs/next-session.md` match what the file
  produces: as finally fixed (item 4), 20 slots of 2 × 14 mm on a 4.07 mm
  pitch with a slot centred on both measured mics, lid corner radius 10,
  6 mm top fillet.
- The t=0 fan-out in `cloud_reply` (speculative voice, research, command
  watcher, holding phrase) was traced for races. Within `cloud_reply` and
  `converse_session`, the `CommandWatcher` lock, the `search_fired` event and
  the `AUDIO_LOCK` check in `HoldingPhrase` resolve every ordering I could
  construct without an overlap or a lost verdict. The one state that escapes
  that scope is the holding phrase outliving the turn, which is item 2.
- API-key fallback is consistent across `src/` except `chat_omni.py`, which
  is documented.

## P1

### 1. `REPEAT` replays the previous session's answer

- **Where:** `src/wake_then_converse.py:1174`.
- **Impact:** `handle_command("REPEAT")` only checks that `RESPONSE_WAV`
  exists, and nothing deletes it when a session starts. "再说一遍" on a fresh
  wake replays an answer from hours or days ago. The "我刚才还没说啥子喃" line
  is only heard before the first successful answer since boot (`/tmp` is
  cleared at boot), never at the start of a later session.
- **Fix:** a staleness bound, not deletion. `handle_command` replays the
  file only if its mtime is within `REPEAT_MAX_AGE_S` (10 min); older says
  nothing to repeat. The first attempt deleted the file at session start,
  which an independent review caught as a regression: `docs/next-session.md`
  §3 records cross-session replay as deliberate, and the common case is a
  listener who missed an answer, let the 6 s window close, and wakes the
  device to ask again.

### 2. Wake mic reopened while audio may still be playing

- **Where:** `src/wake_then_converse.py:1536`.
- **Impact:** `converse_session` can return while a holding phrase is still
  inside aplay (timer fired at 3.5 s, then both cloud paths failed fast and
  the dead-turn counter ended the session). `p.open` on the half-duplex
  codec then raises `OSError` (the behaviour the comment at line 1348
  records), which escapes `main()`, and systemd restarts the daemon. The
  outage is roughly `RestartSec` plus model load plus warm-up, on the order
  of 10-15 s, unmeasured. The journal shows an `OSError` traceback at
  `p.open` with nothing linking it to the holding phrase. The turn loop
  already guards this at line 1353; the session-to-wake transition does not.
- **Fix:** every mic open goes through one helper, `open_input()`, which
  takes `AUDIO_LOCK` around `p.open`. The first attempt added a
  `wait_for_audio_idle()` call before the wake-mic open, mirroring the turn
  loop; the independent review pointed out that a per-call-site wait is a
  convention a third mic open can forget, so the lock moved into the helper.

### 3. The wake tools hard-code the live KWS setting

- **Where:** `tools/blind_windows.py:37,62-63`, `tools/sweep_kws.py:39`,
  `tools/wake_livecheck.py:34,43,85` (score 4.0, threshold 0.05,
  `max_active_paths=16`; `num_threads` is 2 in the first two and 1 in the
  third, which only changes speed, not the decode).
- **Impact:** today the values match the daemon, so nothing is currently
  mismeasured. The risk is drift: change a constant in the daemon and every
  sweep silently keeps measuring the old detector, and `wake_livecheck.py`
  labels the wrong cell "LIVE SETTING". Beam width went unswept for three
  months because the daemon and the tools each carried an implicit value
  nobody compared, which is the same failure shape. The next lid-closed
  corpus run is scheduled to happen soon.
- **Fix:** move `KWS_MODEL_DIR`, `KWS_KEYWORDS_FILE`, `KWS_SCORE`,
  `KWS_THRESHOLD`, `KWS_MAX_ACTIVE_PATHS` and `build_kws()` into a small
  `src/kws.py` that imports only `sherpa_onnx`, have the daemon import them
  from there, and have the three tools do the same. Give `build_kws` optional
  `model_dir` / `keywords` parameters so `sweep_kws.py` keeps its
  `--model-dir` / `--keywords` overrides for Mac runs. A dependency-free
  module matters because the Mac sweep environment does not have pyaudio or
  dashscope, so the tools cannot import `wake_then_converse` directly.

### 4. v16 slot band starts exactly on the first mic

- **Where:** `enclosure/case.scad:332` (`y_lo = base_r + 2.5 = 10.5`) versus
  the measured mic position `world y ≈ 10.5` at line 112.
- **Impact:** the band was added so the result would not depend on the Y
  measurement, and inside the band it does not: with 2 mm slots on a 4 mm
  pitch every point is within 1 mm of an opening. The exception is the band's
  end, and the lower clamp lands exactly on the first mic, so an error toward
  the corner puts that mic behind solid wall. Whether 1-3 mm of wall matters
  acoustically is unproven either way. This affects the print you are about
  to make, hence P1 by timing, not severity.
- **Fix:** anchor slot 0 on the first mic and derive the pitch from the mic
  spacing (15 pitches over 61 mm, 4.067 mm), so a slot is centred on both
  measured positions; 20 slots from y = 9.5 to 88.8. The first attempt only
  moved the band's start to 8.5 at a fixed 4 mm pitch, which an independent
  review caught: that put the second mic (71.5) dead behind a rib, where the
  original clamp had it at a slot centre.

## P2

### 5. `usage-report.sh` daily section can abort the whole report

- **Where:** `tools/usage-report.sh:76-91` (uncommitted).
- **Impact:** the script runs under `set -euo pipefail` and the daily loop has
  no fallback, so one failed billing call, or an error message reaching
  `JSON.parse`, kills the script before the device-journal section prints.
  The alert this section exists to raise would disappear along with it. The
  two monthly sections above it have the same exposure; it predates this
  diff.
- **Fix:** wrap the pipeline like the journal section already does
  (`... || echo "  $DAY: (billing API unavailable)"`), list `ALERT_USD` with
  the other optional variables in the header comment, and either paginate
  with `NextToken` like the monthly loop or note that a day never exceeds
  300 items.

### 6. Documented `sweep_kws.py` invocation fails

- **Where:** `tools/sweep_kws.py:4-5`.
- **Impact:** the docstring shows `--said 20`; the parser requires `--marks`
  and has no `--said`. Copying the documented command errors out.
- **Fix:** replace the usage line with
  `--positives wake_data/pos.wav --marks wake_data/pos.marks --negatives
  wake_data/neg.wav`.

### 7. Three private copies of the Silero shim; `vad_compare` never tests 0.7

- **Where:** `tools/endpoint_tune.py:33`, `tools/vad_compare.py:33`,
  `tools/vad_speech_vs_noise.py:31`; thresholds at
  `tools/vad_compare.py:119-121`.
- **Impact:** all three files already `import wake_then_converse as W`, and
  `W.SileroVad(threshold)` is the shipped implementation, so each copy is a
  place for the measured code to diverge from the deployed code.
  `vad_compare.py` sweeps 0.5 and 0.3 but never the shipped 0.7, although
  `docs/next-session.md:236` says it "covers Silero".
- **Fix:** delete the three classes and use `W.SileroVad(threshold)`; if
  `vad_compare.py` is kept (see item 15), add `("silero@0.7", ...)` to its
  list.

### 8. No wall-clock deadline in two stream loops

- **Where:** `detect_command` (`src/wake_then_converse.py:1063`) and
  `synthesise_phrase` (line 736).
- **Impact:** `request_timeout` is a per-socket-read timeout, as the comment
  at line 243 explains. A stream that trickles bytes keeps `detect_command`
  alive on a daemon thread after the turn has moved on, one leaked thread and
  HTTP connection per turn; in `synthesise_phrase` it stalls boot before the
  wake loop starts.
- **Fix:** copy the `if time.monotonic() - t0 > DEADLINE: break` check from
  `research_pass` into both loops, with `COMMAND_DEADLINE_S` and a new
  `PHRASE_DEADLINE_S` (20 s is generous for one sentence). The check only
  runs when a chunk arrives, so a read that blocks outright is still bounded
  by `request_timeout`; total time is then deadline plus one read timeout,
  the same bound `research_pass` and `voice_call` already accept.

### 9. `requirements.txt` omits two hard requirements

- **Where:** `requirements.txt`; `docs/deployment.md:16` calls this out as
  "yet".
- **Impact:** `pip install -r requirements.txt` alone is not enough to run
  the deployed daemon. The README (line 29) and `docs/deployment.md` do name
  the two packages, so someone following them is fine; the cost is a
  workaround sentence in two documents and a requirements file that does not
  describe the main program.
- **Fix:** add `numpy` and `sherpa-onnx`, and drop the workaround note from
  `docs/deployment.md:16` and `README.md:29`.

### 10. Stale `mic_holes()` references in the v16 diff

- **Where:** `docs/next-session.md:177`, `:342`, `:376`;
  `enclosure/case.scad:6-8`, `:93`, `:305`.
- **Impact:** the uncommitted diff deletes `mic_holes()`, and six places
  still tell the reader to fix it when the lid is next touched. The next
  session will look for a module that does not exist.
- **Fix:** in the same commit as the v16 change, replace each with "removed
  in v16; the base grille band is the mic path", and drop the two-mic-holes
  line from the `case.scad` header.

## P3

### 11. `converse.py` persona prompt has drifted from the daemon's

- **Where:** `src/converse.py:35-48` versus `src/wake_then_converse.py:401`.
- **Impact:** older wording, no 50-character cap, no rules 7-8. `CLAUDE.md`
  asks that persona, brevity and safety rails be preserved, not that the two
  texts stay identical, and rule 7 only applies when a research pass supplies
  facts, which `converse.py` has no equivalent of. So this is drift to
  acknowledge, not a defect: bench runs of `converse.py` exercise an older
  brevity rule than the one shipped.
- **Fix:** one line in `CLAUDE.md` or at the top of `converse.py` saying the
  short original prompt is kept on purpose. Importing the daemon's prompt is
  possible (`converse.py` already needs pyaudio and dashscope) but would drag
  rule 7 along.

### 12. `NearMissWatcher` is dead by flag

- **Where:** `src/wake_then_converse.py:1447-1488`, constants at lines
  88-90, `import queue` at line 32, three `nearmiss` call sites in `main()`.
- **Impact:** about 60 lines the reader has to understand before trusting
  the wake loop, guarded by a flag whose own comment says it has not told you
  anything since the beam change.
- **Fix:** delete the class, the three constants, the import and the call
  sites. Git keeps it if the live tuning is ever loosened again.

### 13. Dead geometry in `case.scad`

- **Where:** `led_hole()` at line 428 and `led_hole_dia` at line 180 (unused
  since v14); the Y-wall port branch at lines 313-327 with `rounded_slot_y`
  (282), `mic_port_w/h/r` (104-107) and `mic_port_z` (210), dead since
  `mic_port_y_walls = false`; `scale([1, 1, 1])` at line 352.
- **Impact:** the Y-wall code is also where the stale `mic_holes()` comment
  lives, and the port constants read as if they still shape the part.
- **Fix:** delete `led_hole`, `led_hole_dia` and the `scale` call now. Delete
  the Y-wall branch after the v16 lid-closed measurement, unless that
  measurement sends you back to Y-wall ports.

### 14. Superseded measurement tools

- **Where:** `tools/vad_gate_sweep.py`, `tools/vad_compare.py`.
- **Impact:** both measure webrtcvad, the fallback engine, or a Silero
  threshold you do not ship. `vad_gate_sweep.py`'s output text hard-codes
  "the 9 noise captures" and "180s", and its pass mark `kq >= 22` belongs
  to one corpus. Both are superseded by `endpoint_tune.py` (which reports per
  length bucket) and `vad_speech_vs_noise.py` (paired speech / no-speech
  corpora); both of those include the shipped 0.7.
- **Fix:** delete both and update the note at `docs/next-session.md:234-236`.
  Keep `tools/sweep_vad.py`: it is webrtcvad-only too, but it has the only
  ASR-completeness scoring. Add a `--vad silero` option, or say in its
  docstring that it measures the fallback.

### 15. Small drift and hygiene

- `src/wake_then_converse.py:1591` plays the literal `/tmp/ack.wav`; use
  `BEEP_ACK`. Line 1559 reimplements `pcm_rms`; call it.
- `endpoint()` line 681: the pre-speech timeout counts only unvoiced frames,
  so voiced flicker that never reaches the 120 ms onset stretches it in
  wall-clock terms. Not observed. If it matters, count every frame before
  speech opens.
- `tools/collect_wake_data.sh:19` and `tools/collect_wake_paced.sh:24` use
  `CARD=2`; the daemon addresses the card by name because the index is not
  stable. Use `amixer -c seeed2micvoicec`.
- `tools/sweep_vad.py:171` reads only `DASHSCOPE_API_KEY`; mirror the
  `SICHUAN_` fallback used everywhere else (and fix `README.md:40`, which
  says only `chat_omni.py` lacks it).
- `error_msg` in `src/utils.py:17` is never used; include it in the
  `sys.exit` message or drop the parameter.
- Unused imports (pyflakes): `os` in `src/synthesize.py:5` and
  `tools/vad_compare.py:21`; `math` and `time` in `tools/sweep_kws.py:15`.
  Placeholder-less f-strings at `src/chat_omni.py:152` and
  `tools/vad_speech_vs_noise.py:122`.
- `deploy/sichuan.service:3-4` (`After=`/`Wants=network-online.target`) do
  nothing in a user unit, as `docs/deployment.md:147` says. Delete them or
  leave a one-line comment so nobody relies on them.
- `docs/deployment.md:150-155` says the holding phrases are the only
  boot-time network calls; `ensure_acks` now adds six more (`COMMAND_ACKS`
  has six entries including `session_cap`), ten synthesis calls on a first
  boot as the comment at line 741 says. Update the count.
- `enclosure/case.scad:166-169` still quotes inner 86 × 86 / outer 92 × 92;
  the actual values are 93 and 99.
- `build_vad()` reloads the Silero ONNX model on every wake
  (`converse_session`, line 1335). Build it once in `main()` and `reset()`
  per turn if first-turn latency is ever measured as a problem.

Kept deliberately, not dead: `src/chat_omni.py` (documented reference for
the realtime path), the webrtcvad fallback in `build_vad()`, and the
`VAD_AGGRESSIVENESS` block that only applies to it.

## Uncommitted and untracked

- `tools/voice_clone.py` (untracked) is self-contained and fine as a dev
  tool. It catches only `HTTPError`, so a timeout or DNS failure prints a
  traceback. `TTS_MODEL` is a dated snapshot name; a second review checked
  Alibaba's model list and found it is still the current Singapore snapshot,
  so it needs no change today. Nothing blocks committing it.
- `enclosure/base.3mf`, `enclosure/lid.3mf` and
  `enclosure/snips-reference/boitier.3mf` are untracked slicer projects.
  Decide whether they belong in the repo or in `.gitignore`.

## Suggested order

1. Items 1 and 2: two one-line changes in the deployed daemon, then redeploy.
2. Item 3, then item 4, before the next lid-closed corpus run and the v16
   print.
3. Item 10 in the same commit as the v16 enclosure change; item 5 before
   relying on the daily alert.
4. Items 6-9 as each file is next touched.
5. One cleanup commit for items 11-15, leaving the Y-wall branch until the
   v16 measurement is in.
