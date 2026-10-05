"""End-to-end Phase 1 prototype:
  wake-word listening (sherpa-onnx KWS, Chinese "麻婆豆腐")
  → on detection, close wake mic, play ack tone
  → open mic, VAD-gated recording, send to qwen3-omni-flash, play reply
  → loop for follow-up turns until silence timeout
  → resume wake-word listening

Single process. The HAT codec (TLV320AIC3104) is half-duplex; we
close the input stream before playing the ack tone / response, and
reopen it for the next mic phase. Same constraint chat_omni.py
works around.

Prerequisites on Pi:
  - PulseAudio must NOT hold the codec (mask pulseaudio.socket +
    pulseaudio.service) — otherwise aplay stalls ~30 s per call.
  - ~/.asoundrc routes default to plughw:2,0 (HAT card).
  - Adequate 5 V power delivery (throttled=0x0 at idle).
  - sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01 model
    extracted at MODEL_DIR (see docs/next-session.md).
  - Custom keywords file at KEYWORDS_FILE with the wake phrase(s)
    encoded as pinyin tokens.
  - silero_vad.onnx at SILERO_VAD_MODEL for end-of-speech detection
    (`pip install webrtcvad` too: it is the fallback engine, and is
    imported unconditionally).
"""
import os, sys, time, datetime, base64, json, math, struct, wave, subprocess
import glob, hashlib, itertools, re
import numpy as np
import pyaudio
import dashscope
import webrtcvad
import queue
import threading
from zoneinfo import ZoneInfo
from sherpa_onnx import KeywordSpotter, VadModel, VadModelConfig

dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

# Sherpa-onnx KWS model + custom wake phrase
KWS_MODEL_DIR = "/home/weilie/sichuan/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
KWS_KEYWORDS_FILE = "/home/weilie/sichuan/models/wake_keywords.txt"

WAKE_RATE = 16000
# Wake-word sensitivity. KWS_THRESHOLD/KWS_SCORE drive the real detector.
# A second "loose" spotter runs on the same audio at NEARMISS_THRESHOLD so
# an utterance that ALMOST fired gets logged instead of vanishing silently.
# sherpa-onnx exposes no per-result score, so a parallel spotter is the only
# way to see near misses. The second decode runs on its own thread — done
# inline it cost the Pi 3 40% of its frame rate (51 -> 31 frames/5s), which
# would starve the real detector. Set NEARMISS_LOGGING = False to drop it.
# Chosen by tools/sweep_kws.py over a labelled corpus (19 beep-paced
# utterances + 3 min of room audio): 17/19 recall with ZERO false alarms.
# The sweep found no false alarm anywhere in the grid, even at the most
# sensitive corner — precision is simply not the binding constraint here,
# so sensitivity is set high. That 17/19 sweep was taken at the default beam
# width and its two "missed at every setting" utterances turned out to be the
# beam, not the model (see KWS_MAX_ACTIVE_PATHS below). Re-run the sweep before
# changing these.
KWS_SCORE = 4.0
# Capture gain, applied at every start. This is the highest-impact setting in
# the whole wake path: replaying the corpus at simulated gains gives 63%
# recall at the card default (~16 dB) against 89% here, and it DECLINES above
# this point (84% at +3 dB). The KWS tuning above was swept at this gain, so
# the two belong together. Addressed by card NAME — .asoundrc hardcodes card
# 2, but index ordering is not guaranteed across kernel updates.
CAPTURE_CARD = "seeed2micvoicec"
CAPTURE_PGA = 60          # 30.00 dB on this codec (range 0-119)
KWS_THRESHOLD = 0.05
# Beam width for the keyword search. sherpa-onnx defaults to 4 and this stayed
# at the default for three months, which cost most of the wake path's recall:
# on a lid-CLOSED corpus of 50 wake utterances plus 20 windows of ordinary
# speech and household noise (NOT silence — the negatives are the speaker
# talking and making noise without saying the wake phrase), 4 gives 28/50 and
# 16 gives 47/50, both rejecting all 20 negatives. The two knobs above
# are nearly flat by comparison — every score from 3.0 to 5.0 lands on exactly
# 47/50 at beam 16, and that agreement is why 16 is the safe choice rather
# than the single best cell (3.0/48 scored 50/50, but its neighbours 4.0/48
# and 5.0/48 produce 2-3 false accepts, so that cell is corpus luck).
# Above 16 recall gains ~2 points and false accepts appear, which is the wrong
# trade for an always-on device. Costs almost nothing: measured on the Pi,
# RTF 0.349 at beam 4 vs 0.360 at beam 16 — the zipformer encoder dominates
# and the beam search is rounding error next to it.
KWS_MAX_ACTIVE_PATHS = 16
# Off: the live detector sits at 4.0/0.05 and score/threshold are nearly flat
# next to beam width, so the watcher has not told us anything since, and its
# second decode thread is pure cost. Flip back on only if the live tuning is
# loosened again.
NEARMISS_LOGGING = False
NEARMISS_SCORE = 2.5
NEARMISS_THRESHOLD = 0.10
WAKE_CHUNK = 1600              # 100 ms @ 16 kHz

CONV_RATE_IN = 16000
CONV_CHUNK = 1600
WARMUP_SECS = 3.5

# VAD-gated recording
VAD_AGGRESSIVENESS = 2                # 0..3 (higher = more aggressive filtering).
                                      # Dropped 3 -> 2 on 2026-08-29: at 3 a real
                                      # answer after the wake beep was discarded
                                      # as non-speech and the session timed out
                                      # in silence. Mic level is weak (floor
                                      # ~1700 RMS, speech only ~2600), so the
                                      # strictest setting rejects genuine speech.
                                      # 3 rejects more marginal audio so faint
                                      # bleed / echo doesn't open a fake turn.
VAD_FRAME_MS = 20                     # webrtcvad accepts 10/20/30 ms frames
# Which VAD labels each frame voice / not-voice. webrtcvad is a signal-
# processing heuristic that calls a keystroke, a chair scrape and a door voice
# -- it was built to detect "is anyone on this call", not "is this a human".
# Silero is a small RNN, shipped inside sherpa-onnx (already a dependency for
# the wake word), and it declines to open on most non-speech.
#
# Measured 2026-09-28 on 50 spoken windows (30 SHORT questions, 10 medium, 10
# long) and 50 windows of room noise with no voice at all, replaying this same
# endpoint():
#
#             short  med  long   ALL   noise reaching the cloud
#   webrtcvad 30/30   10    10  50/50        33/50
#   silero    30/30   10    10  50/50        13/50
#
# Same recall, 60% less noise. Costs RTF 0.100 on the Pi against webrtcvad's
# 0.0011 -- 90x more, still a tenth of one core, and the wake spotter is not
# running during a conversation turn.
#
# Known cost: on the older q2 corpus Silero keeps 8/12 where webrtcvad keeps
# 11/12. 12 questions from September against 50 current ones that show no loss;
# revisit if short questions start being dropped in real use.
#
# The gate below is deliberately NOT retuned to match. Every setting that
# tightens MIN_VOICED_RUN_MS past 700 pays for it almost entirely in SHORT
# questions (30 -> 24 -> 13 of 30) while medium and long stay at 10/10, and
# short questions are what this device will actually be asked.
VAD_ENGINE = "silero"                 # "silero" or "webrtcvad"
SILERO_VAD_MODEL = "/home/weilie/sichuan/models/silero_vad.onnx"
SILERO_VAD_THRESHOLD = 0.7            # 0.5 gives 21/50 noise through, 0.7 gives 13
VAD_FRAME_SAMPLES = CONV_RATE_IN * VAD_FRAME_MS // 1000  # 320 samples
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * 2                  # int16 mono
START_VOICED_MS = 120                 # need this much voiced audio to open an utterance
END_SILENCE_MS = 1400                 # this much trailing silence closes an utterance
                                      # 800 -> 1400 on 2026-09-19. At 800 a real
                                      # question was cut after ~300 ms: the
                                      # captures were 1.4-2.4 s, which after
                                      # subtracting pre-roll and trailing
                                      # silence is a fragment, and the cloud
                                      # answered "I can't hear you" to all of
                                      # them. On a quiet mic webrtcvad drops
                                      # frames mid-sentence, and 800 ms of those
                                      # dropouts is an ordinary pause between
                                      # words, not the end of a thought. Costs
                                      # 600 ms of latency on every turn; elderly
                                      # speakers pause more, not less.
MAX_UTTERANCE_S = 30                  # hard cap on a single utterance
PRE_SPEECH_PAD_MS = 300               # keep a ring buffer so we don't clip the onset
# A session ends when the user goes silent for these many seconds. The first
# turn allows more time (user may still be forming the question after the
# beep). After a dead turn (noise-only, see below), we tighten to a short
# window so a noisy room can't string us along.
FIRST_TURN_SILENCE_TIMEOUT_S = 8
FOLLOWUP_SILENCE_TIMEOUT_S = 6
POST_DEAD_SILENCE_TIMEOUT_S = 2.5
POST_ACK_MIC_DISCARD_S = 0.5

# Guardrails against perpetual sessions in noisy rooms.
#   - MIN_UTTERANCE_MS: anything shorter than this is treated as noise and
#     skips the cloud call entirely (cheap, purely local).
#   - MAX_CONSECUTIVE_DEAD_TURNS: after N turns in a row that either got
#     rejected locally or came back with no cloud audio, end the session.
# A room with just background noise burns at most MAX_CONSECUTIVE_DEAD_TURNS
# turns before we drop out.
#   - MAX_SESSION_TURNS: cap on cloud turns in one session. The dead-turn
#     guard cannot see a TV: broadcast speech passes every local gate, the
#     cloud answers it, and each "successful" turn keeps the session open.
#     At the cap the device says so and goes back to the wake word.
MIN_UTTERANCE_MS = 400
# A capture long enough to pass MIN_UTTERANCE_MS can still be nothing but
# keyboard clicks, and that is not a harmless case: it costs two cloud calls,
# the model answers "I can't hear you", the turn counts as a SUCCESS, and the
# session stays open to do it again. Observed doing exactly that on 2026-09-19.
#
# What separates typing from talking is not energy but continuity. Speech holds
# voiced frames together in syllable-length runs; a keystroke is a 20-40 ms
# impulse. So the gate is on the longest unbroken voiced run, with the voiced
# ratio as a weaker second check. Both are deliberately loose -- the mic is
# quiet and VAD_AGGRESSIVENESS had to come down to 2 for real speech to survive
# -- and both are logged on every turn so they can be tuned from field logs
# rather than guessed at again.
# The longest unbroken voiced run is the real discriminator, and it is the one
# that is duration-independent: a keystroke is a 20-40 ms impulse no matter how
# long the capture around it runs. 300 ms blocks the keyboard turn that got
# through on 2026-09-19 (it measured 240 ms) and passes real speech comfortably.
MIN_VOICED_RUN_MS = 300
# The ratio is only a backstop against a long capture that got one lucky run.
# It was 0.35 for an hour and that was a mistake: the ratio falls as the capture
# gets LONGER, so a 7 s capture holding a perfectly good 1.5 s question scores
# 21% and was thrown away unheard -- measured doing exactly that against the
# 2026-09-19 question corpus. Judging speech by a number that shrinks the longer
# the recorder runs is unsound; keep this loose and let the run length decide.
MIN_VOICED_RATIO = 0.10
# How many previous exchanges to replay to the model so a session feels
# like one conversation instead of N unrelated questions. Each retained
# user turn re-uploads its base64 WAV (~40 KB per second of speech), so
# this trades upload time on the Pi's Wi-Fi against context depth.
MAX_HISTORY_TURNS = 3
# Two-pass cloud path. Pass 1 (research) sends the raw audio with web search
# enabled and NOTHING else — measured on this Pi, ANY system prompt or even an
# instruction in the user turn drops search_results to empty and the model
# invents a number instead (asked one city's temperature it answered 24, 30,
# 32 on consecutive tries). So pass 1 gets no instructions at all and pass 2
# carries the whole persona. max_tokens caps round 1's verbosity; it does not
# suppress search. 160, not 100: a weather answer at 100 truncated mid-number,
# and a fact round 2 cannot see is a fact it will not say.
RESEARCH_MAX_TOKENS = 160
# Round 1 gets no system prompt, so it also has no idea where the device is.
# Measured 2026-09-19: "明天天气怎么样？" returns ZERO sources and a reply asking
# which city; the same question with a location line returns 14. This is the
# single most common question this device will ever be asked, and it was
# failing every time.
#
# Note what this does NOT contradict: an INSTRUCTION in round 1's user turn
# still kills search (see above). A statement of fact does not. Context is
# safe to add here; commands are not.
#
# The date is included because "明天" is meaningless without it — without the
# date the model dated tomorrow inconsistently (周五 in one reply, 周六 in the
# next). It is computed in DEVICE_TZ, NOT read from the Pi's own timezone: the
# Pi was set up on America/New_York, 12 h behind Chengdu, which made "今天" the
# wrong date for half of every day. Change the two together if the device moves.
DEVICE_LOCATION = "四川成都"
DEVICE_TZ = "Asia/Shanghai"
# Round 2 is launched at the same moment as round 1, on the bet that this turn
# needs no search. See SpeculativeVoice. Set False for strictly serial rounds.
SPECULATIVE_VOICE = True
# Bound on waiting for the speculative call. 12 s, not 60: a normal turn
# completes in ~4.7 s, so anything past ~12 s is a sick stream, and 60 s of
# silence is indistinguishable from a hang to someone standing in a kitchen.
SPEC_WAIT_TIMEOUT_S = 12
# Deadlines on the two FOREGROUND cloud calls. These matter more than the one
# above: the speculative call runs on a daemon thread that can be abandoned for
# free, while these block the main loop with the mic closed and no wake word
# being heard — and the process stays alive, so systemd's Restart= never fires.
#
# Both halves are needed. request_timeout is what the DashScope SDK hands to
# requests as a PER-SOCKET-READ timeout (default 300 s), so on its own it lets
# a stream that trickles bytes block forever; the deadline check inside each
# stream loop is the actual wall-clock bound.
REQUEST_TIMEOUT_S = 10
RESEARCH_DEADLINE_S = 20
VOICE_DEADLINE_S = 30
# A search turn costs ~6 s in pass 1 alone, so say something out loud rather
# than leaving an elderly listener in silence. Non-search turns come back in
# ~1.5 s and never reach the timer.
# 3.5 s, not 2.0: the research pass takes ~2.3 s even when it does not search,
# so a 2 s timer announced "let me look that up" on every single turn — including
# 你好. Only a turn that is actually slow should get the holding phrase.
FILLER_DELAY_S = 3.5
MAX_CONSECUTIVE_DEAD_TURNS = 2
MAX_SESSION_TURNS = 10

# Sichuan-dialect voices on the omni models: Sunny (female), Eric (male).
# Eric verified against qwen3.5-omni-flash on 2026-09-28 and chosen by ear.
VOICE = "Eric"
# A pool, not one line: a turn that needs a search is usually followed by more
# of them, and hearing the identical recording back three times in a row is
# what makes a device sound like a machine. Rotated in order, so all of them
# are heard before any repeats. Keep them short -- this plays while the user is
# already waiting -- and in dialect, since the voice alone does not choose the
# words.
FILLER_PHRASES = [
    "等哈儿，我帮你查一下哈。",
    "莫慌哈，我这就去帮你看看。",
    "稍等哈，我帮你问一下噻。",
    "等一哈儿，我马上查给你听。",
]
PHRASE_DIR = "/home/weilie/sichuan"


def phrase_path(kind, phrase):
    """Cache filename for one canned line, keyed to the voice AND the text on
    purpose. These are synthesised once and kept on disk, and ensure_phrases()
    skips any file that already exists -- so a plain filename meant that
    switching VOICE left the holding phrase in the OLD voice forever (observed
    2026-09-28: the device greeted in Sunny and answered in Eric), and editing
    a wording here would likewise have kept playing the old recording."""
    digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()[:8]
    return os.path.join(PHRASE_DIR, f"{kind}_{VOICE}_{digest}.wav")


# Filled in by ensure_filler(): the phrases that actually reached the disk.
# Empty is a supported state -- HoldingPhrase then arms no timer at all.
FILLER_WAVS = []
_FILLER_ROTATION = itertools.count()

# ---- Device commands -------------------------------------------------------
# The third call of the t=0 fan-out, alongside the search and the speculative
# answer. A separate call, not a tag bolted onto one of those two, for two
# measured reasons. Round 1 cannot take an instruction at all: any instruction collapses
# search_results and the model starts inventing numbers (see
# RESEARCH_MAX_TOKENS). Round 2's text IS its speech, so a tag there would be
# read out loud -- and on a search turn the round-2 instance holding the user's
# audio is aborted, so on exactly the turns that search there would be nobody
# left who heard the command. This runs in PARALLEL with both, so it costs no
# wall-clock, and it keeps control intent from competing with persona or search
# for a prompt. Cost is one short text-only call per turn.
COMMAND_DETECTION = True
COMMAND_MODEL = "qwen3.5-omni-flash"
# One tag is 3-4 tokens. The cap is a backstop against a chatty answer, not a
# budget -- the strict parse already rejects anything that is not a bare tag.
COMMAND_MAX_TOKENS = 8
# A command is only worth acting on while it can still change this turn. Past
# this, round 2's answer is already on its way to the speaker and adjusting the
# volume would mean talking over it.
COMMAND_DEADLINE_S = 6
COMMAND_TAGS = ("VOLUME_UP", "VOLUME_DOWN", "REPEAT")
# No STOP tag: by the time a turn is being transcribed the device is listening,
# not speaking -- the codec is half duplex -- so there is nothing for it to
# interrupt. Revisit if playback ever becomes cancellable.
COMMAND_PROMPT = (
    "你是一个智能音箱的指令识别模块，不是聊天助手。"
    "唯一任务：判断这段话是不是在直接吩咐这台音箱做事。"
    "只输出一个标签，不准输出任何别的字、标点或者解释。\n"
    "标签：\n"
    "VOLUME_UP：要音箱说大声点（大声点、听不清、音量大一点）\n"
    "VOLUME_DOWN：要音箱说小声点（小声点、太吵了、音量小一点）\n"
    "REPEAT：要音箱把刚才的话再说一遍\n"
    "NONE：其他任何情况\n"
    "规则：\n"
    "1. 拿不准就输出 NONE。宁可漏掉一次吩咐，也不要误判——"
    "误判会让音箱在聊天中间自己改音量。\n"
    "2. 必须是在吩咐这台音箱。说别的东西吵（电视、楼上、隔壁），"
    "或者聊天里头提到“声音”“音量”这些词，都输出 NONE。\n"
    "3. 一句话里头既有吩咐又有问题（“小声点，今天天气怎么样”），"
    "输出 NONE，让聊天照常走。\n"
    "4. 听不清、或者录到的是杂音，输出 NONE。"
)
# Spoken, not a beep. A chirp can signal "something happened" but it cannot say
# 已经是最小声咯, and the difference between "turned it down" and "already at the
# bottom" is exactly what stops someone asking a third time. These cost nothing
# at runtime -- same cached-WAV mechanism as the holding phrases -- so the only
# thing a beep would buy is a first boot with no network, which the fallback in
# play_ack already covers.
#
# Played AFTER the change lands, so they are heard at the new level and the
# result is self-evidencing. That is the only feedback channel this device has.
BEEP_ACK = "/tmp/ack.wav"
COMMAND_ACKS = {
    "up": "要得，我说大声点哈。",
    "down": "要得，我说小声点哈。",
    "at_max": "已经是最大声咯。",
    "at_min": "已经是最小声咯。",
    "nothing_to_repeat": "我刚才还没说啥子喃。",
    # Not a command, but it needs the same thing the acks do: a cached spoken
    # line with the beep as fallback. Spoken when MAX_SESSION_TURNS ends a
    # session, because a silent cut-off mid-conversation looks like a fault.
    "session_cap": "我们摆了好一阵咯，我先歇一哈。还要摆的话，再喊一声麻婆豆腐哈。",
}
ACK_WAVS = {}

# Verified on the Pi 2026-09-30: the HAT (TLV320AIC3104) exposes the DAC volume
# as PCM, 0-127 in 0.5 dB steps -- 127 is 0 dB and the 108 it ships at is
# -9.5 dB. The speaker runs off the Line output, whose own amp already sits at
# its 9 dB maximum, so PCM is the knob with both the headroom and the fine
# steps. HP is muted and irrelevant here.
PLAYBACK_CONTROL = "PCM"
VOLUME_DEFAULT = 108
VOLUME_STEP = 8        # 4 dB per request: clearly audible, not drastic
VOLUME_CEILING = 127   # 0 dB, the codec's own limit
# 12 dB below default. A floor exists because this device has no screen: if they
# turn it down past hearing, the only way back is to ASK for it louder, and they
# have to be able to hear the acknowledgement to know it worked.
VOLUME_FLOOR = 84
# ALSA mixer state does not survive a reboot (same reason set_capture_gain
# exists), so an adjustment the parents made has to be remembered here and
# re-applied at boot, or it silently reverts on the next restart.
VOLUME_STATE = "/home/weilie/sichuan/volume"
# Round 2, the voice. 3.5 series: required for enable_search (the 3.0 models
# have no search at all), and it is the newest series that can still SPEAK —
# 3.8-Omni-Flash is text-out only.
MODEL = "qwen3.5-omni-flash"
# Round 1, the research. Split from MODEL so the two rounds can move
# independently: this pass is audio in / text out, so it does not need a model
# that can speak.
#
# qwen3.8-omni-flash was measured here on 2026-09-19 and REJECTED, despite
# fitting the shape and pricing audio input ~98% lower. Medians over 3 reps
# from the Pi, 3.8 with enable_thinking=False (its default reasoning is far
# worse still — 5.1 s and 11.7 s):
#   chat turn:   3.5 -> 1.2 s   3.8 -> 1.9 s
#   search turn: 3.5 -> 3.2 s   3.8 -> 7.0 s
# Round 1 sits on the critical path of EVERY turn now that round 2 runs
# speculatively, so +0.7 s on chat and +3.8 s on search is the whole
# speculation win given back and then some.
#
# The disqualifying result was not latency though. Fed a near-silent capture
# (a dead turn), 3.5 said the message seemed incomplete; 3.8 invented a
# question, ran 29 searches and answered confidently about UC Berkeley. A weak
# mic in an elderly household produces marginal captures constantly, and a
# model that confabulates through them is the wrong failure mode for this
# device. Revisit if a later 3.8 revision degrades more gracefully.
RESEARCH_MODEL = "qwen3.5-omni-flash"
SICHUAN_SYSTEM_PROMPT = (
    "你是一个用四川话回答的语音助手，扮演的角色像家里孝顺的孙辈，"
    "在跟长辈聊天。回答要求："
    "1. 无论用户说什么语言，都要用四川方言回复；只用口语化的中文，"
    "不要用英文或拼音。"
    "2. 语气要温暖、耐心、亲切，像跟自家爷爷奶奶讲话一样。"
    "多用四川口头禅（巴适、安逸、要得、莫慌、撒子、噻）让感觉更自然。"
    "3. 回答要简短，一般两三句话就够了，不要长篇大论。"
    "4. 用简单好懂的词，不用复杂或者技术性的词。"
    "5. 遇到医疗、健康、钱财这些严肃话题，要温柔地建议对方跟"
    "家里人或者医生商量，不要自己给判断。"
    "6. 万一听不清对方说的啥子，就温和地请他们再讲一遍，"
    "不要瞎猜。"
    "7. 有时候我会把刚刚查到的最新资料附在问题后头。只要有资料，"
    "就照资料回答，该报的数字（温度好多度、价钱好多钱）一定要报出来，"
    "用你自己的话两三句讲完，不要念资料原文，更不准说“查不到”。"
    "只有在没得资料、又问的是实时的事情时，才老实说“我这儿查不到”，"
    "喊他们看手机或者问屋头的人。任何时候都不准自己编数字。"
    # Round 2 receives the user's raw audio, not a transcript, so the model can
    # hear the speaker. Two people live with this device, one man and one
    # woman, which makes this about the easiest call there is -- but getting it
    # WRONG is worse than not addressing them at all, hence the explicit out.
    # If this proves unreliable in use, the real fix is sherpa-onnx speaker
    # embeddings enrolled per person, not a stronger prompt.
    "8. 从说话人的声音判断是爷爷还是奶奶在说话：男声就喊“爷爷”，"
    "女声就喊“奶奶”，回答的时候带上对应的称呼。"
    "只有听得清楚、很有把握的时候才这样喊；只要有一点拿不准，"
    "就用“您”，千万不要瞎猜——喊错了比不喊还要伤人。"
)
RECORDING_WAV = "/tmp/wake_recording.wav"
RESPONSE_WAV = "/tmp/wake_response.wav"


def log_stage(stage, message, **fields):
    suffix = ""
    if fields:
        suffix = " " + " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"[{stage}] {message}{suffix}", flush=True)


def pcm_rms(data):
    audio_i16 = np.frombuffer(data, dtype=np.int16)
    if len(audio_i16) == 0:
        return 0
    return int(math.sqrt(float(np.mean(audio_i16.astype(np.int64) ** 2))))


# Every aplay in this process goes through this lock. The codec is half-duplex
# and ~/.asoundrc points default at a bare plughw:2,0 with no dmix, so a second
# concurrent open returns -EBUSY and that audio is simply lost. The holding
# phrase plays from a timer thread while the main thread may be ready to play
# the reply, so "concurrent" is a real state here, not a theoretical one.
AUDIO_LOCK = threading.Lock()
# Bound on one aplay. Replies run a few seconds, so 60 s is never reached by
# audio that is actually playing -- it exists because a stalled aplay holds
# AUDIO_LOCK with the process still alive, which systemd's Restart= never sees.
# A stall therefore ends the process: a codec wedged badly enough to hang aplay
# will hang the next one too, and a restart is the only recovery available
# from 1000 km away.
APLAY_TIMEOUT_S = 60


def _aplay(path):
    """Unlocked playback primitive. Callers must hold AUDIO_LOCK."""
    if not os.path.exists(path):
        print(f"[audio] missing {path}", flush=True)
        return False
    t0 = time.monotonic()
    log_stage("audio", "playback start", file=os.path.basename(path))
    try:
        r = subprocess.run(["aplay", "-q", path], capture_output=True,
                           text=True, timeout=APLAY_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"[audio] aplay stalled on {path} — killed after "
              f"{APLAY_TIMEOUT_S}s. Exiting so systemd restarts the service.",
              flush=True)
        # os._exit, not sys.exit: this also runs on the holding-phrase timer
        # thread, where SystemExit would end only that thread.
        os._exit(1)
        return False
    if r.returncode != 0:
        # Never silent. A reply that failed to play looks exactly like a
        # successful turn in the logs otherwise, and "it answered but we heard
        # nothing" is the most expensive thing to diagnose from 1000 km away.
        print(f"[audio] aplay failed on {path}: rc={r.returncode} "
              f"{r.stderr.strip()[:160]}", flush=True)
        return False
    log_stage("audio", "playback done", file=os.path.basename(path),
              elapsed=f"{time.monotonic()-t0:.2f}s")
    return True


def play_wav(path):
    with AUDIO_LOCK:
        return _aplay(path)


def wait_for_audio_idle():
    """Block until nothing is playing. Called before opening the mic: the
    holding phrase runs on its own thread and can still be emitting when a
    turn ends, and opening input while the speaker runs is exactly what the
    half-duplex codec cannot do."""
    with AUDIO_LOCK:
        pass


class HoldingPhrase:
    """Plays "let me look that up" if the turn is still unresolved when the
    timer fires, and nothing at all once it has been cancelled.

    Timer.cancel() alone is not enough: it is a no-op once the timer has
    already fired, and by then play_wav is blocking inside aplay holding the
    codec — so the reply's own aplay collided with it, lost to -EBUSY, while
    cloud_reply went on to report the turn as a success. The flag is checked
    under AUDIO_LOCK so a cancel racing with playback resolves one way or the
    other, never into an overlap."""

    def __init__(self):
        self._cancelled = False
        self._timer = None
        if FILLER_WAVS:
            self._timer = threading.Timer(FILLER_DELAY_S, self._fire)
            self._timer.start()

    def _fire(self):
        with AUDIO_LOCK:
            if self._cancelled:
                return
            # Advance the rotation only when a phrase is actually HEARD. Most
            # turns arm the timer and then cancel it, so advancing in __init__
            # would burn entries on silence and let the same wording come up
            # twice running for the listener. AUDIO_LOCK serialises this.
            _aplay(FILLER_WAVS[next(_FILLER_ROTATION) % len(FILLER_WAVS)])

    def cancel(self):
        self._cancelled = True
        if self._timer is not None:
            self._timer.cancel()


def make_beep(path, freq=880, secs=0.15):
    rate = 16000
    n = int(rate * secs)
    samples = [int(15000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    raw = b"".join(struct.pack("<h", s) for s in samples)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(raw)


def stream_frames(stream):
    """20 ms frames off a live pyaudio input stream, forever."""
    while True:
        data = stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
        # pyaudio may hand back a short buffer on shutdown; skip those.
        if len(data) != VAD_FRAME_BYTES:
            continue
        yield data


def record_utterance(stream, vad, silence_timeout_s):
    """Capture one utterance from a live input stream. Thin wrapper so the
    device and tools/sweep_vad.py share one endpointer -- a sweep against a
    reimplementation measures the reimplementation."""
    return endpoint(stream_frames(stream), vad, silence_timeout_s)


class SileroVad:
    """webrtcvad-compatible shim so endpoint() is untouched by the swap.

    Silero decides on fixed windows (512 samples at 16 kHz); the device feeds
    20 ms (320-sample) frames. Buffer until a full window is available and hold
    that verdict for the frames in between, leaving the endpointer's frame grid
    exactly as webrtcvad saw it.
    """

    def __init__(self, threshold=SILERO_VAD_THRESHOLD):
        cfg = VadModelConfig()
        cfg.silero_vad.model = SILERO_VAD_MODEL
        cfg.silero_vad.threshold = threshold
        cfg.sample_rate = CONV_RATE_IN
        cfg.provider = "cpu"
        cfg.num_threads = 1
        self.model = VadModel.create(cfg)
        self.win = self.model.window_size()
        self.buf = np.empty(0, dtype=np.float32)
        self.last = False

    def reset(self):
        """Called between turns; the model carries state across frames."""
        self.model.reset()
        self.buf = np.empty(0, dtype=np.float32)
        self.last = False

    def is_speech(self, data, rate):
        s = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        self.buf = np.concatenate([self.buf, s])
        while len(self.buf) >= self.win:
            self.last = bool(self.model.is_speech(self.buf[:self.win].tolist()))
            self.buf = self.buf[self.win:]
        return self.last


def build_vad():
    """The frame-level voice detector. Falls back to webrtcvad if the Silero
    model is missing -- a stale SD card should degrade the endpointer, not stop
    the device answering at all."""
    if VAD_ENGINE == "silero" and os.path.exists(SILERO_VAD_MODEL):
        return SileroVad()
    if VAD_ENGINE == "silero":
        print(f"[vad] {SILERO_VAD_MODEL} missing — falling back to webrtcvad.",
              flush=True)
    return webrtcvad.Vad(VAD_AGGRESSIVENESS)


def endpoint(frames, vad, silence_timeout_s,
             end_silence_ms=None, start_voiced_ms=None, pre_pad_ms=None):
    """Consume 20 ms frames until one utterance is captured or
    silence_timeout_s elapses with no speech.

    The timing parameters default to the module constants; the sweep overrides
    them to measure settings other than the shipped ones.

    Returns (raw_pcm_bytes, reason, stats):
      reason == "speech"  → utterance captured, bytes contain int16 mono PCM
      reason == "timeout" → no speech in silence_timeout_s, bytes is b""
    stats carries voiced_ratio and longest_run_ms over the captured segment, so
    the caller can tell talking from typing before paying for a cloud call.
    """
    pre_speech_frames = max(1, (pre_pad_ms if pre_pad_ms is not None
                                else PRE_SPEECH_PAD_MS) // VAD_FRAME_MS)
    start_voiced_needed = max(1, (start_voiced_ms if start_voiced_ms is not None
                                  else START_VOICED_MS) // VAD_FRAME_MS)
    end_silence_needed = max(1, (end_silence_ms if end_silence_ms is not None
                                 else END_SILENCE_MS) // VAD_FRAME_MS)
    max_frames = MAX_UTTERANCE_S * 1000 // VAD_FRAME_MS
    silence_timeout_frames = int(silence_timeout_s * 1000 // VAD_FRAME_MS)

    ring = []                # rolling pre-speech buffer
    captured = []
    in_speech = False
    voiced_run = 0
    silence_run = 0
    total_frames = 0
    leading_silence = 0
    voiced_frames = 0
    cur_run = 0
    longest_run = 0
    opened_after_frames = None

    def stats(stop_reason=None):
        return {"voiced_ratio": (voiced_frames / total_frames) if total_frames else 0.0,
                "longest_run_ms": longest_run * VAD_FRAME_MS,
                "leading_silence_ms": leading_silence * VAD_FRAME_MS,
                "opened_after_ms": (opened_after_frames * VAD_FRAME_MS
                                    if opened_after_frames is not None else None),
                "stop_reason": stop_reason}

    for data in frames:
        is_speech = vad.is_speech(data, CONV_RATE_IN)

        if not in_speech:
            ring.append(data)
            if len(ring) > pre_speech_frames:
                ring.pop(0)
            if is_speech:
                voiced_run += 1
                if voiced_run >= start_voiced_needed:
                    in_speech = True
                    opened_after_frames = leading_silence
                    captured.extend(ring); ring = []
                    silence_run = 0
                    total_frames = len(captured)
                    voiced_frames = voiced_run
                    cur_run = voiced_run
                    longest_run = voiced_run
            else:
                voiced_run = 0
                leading_silence += 1
                if leading_silence >= silence_timeout_frames:
                    return b"", "timeout", stats("silence_timeout_before_speech")
        else:
            captured.append(data)
            total_frames += 1
            if is_speech:
                silence_run = 0
                voiced_frames += 1
                cur_run += 1
                if cur_run > longest_run:
                    longest_run = cur_run
            else:
                cur_run = 0
                silence_run += 1
                if silence_run >= end_silence_needed:
                    return b"".join(captured), "speech", stats("end_silence")
            if total_frames >= max_frames:
                return b"".join(captured), "speech", stats("max_utterance")
    # Offline only: the frame source ended. Live, stream_frames never stops.
    return (b"".join(captured) if in_speech else b""), \
           ("speech" if in_speech else "timeout"), stats("source_ended")


def set_capture_gain():
    """Force the mic gain the wake tuning was measured at.

    ALSA mixer state does not survive a reboot unless someone ran alsactl
    store, and a hand-run command on one SD card is invisible to this repo —
    so the service sets it itself on every start. Never fatal: a speaker that
    refuses to boot is worse than one running at the wrong gain. But never
    silent either, because wrong gain presents as "it doesn't hear me
    sometimes", which is expensive to diagnose from 1000 km away."""
    try:
        r = subprocess.run(
            ["amixer", "-c", CAPTURE_CARD, "sset", "PGA", str(CAPTURE_PGA)],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"[boot] WARNING could not set capture gain on "
                  f"{CAPTURE_CARD}: {r.stderr.strip()[:200]}", flush=True)
            return
        level = next((ln.strip() for ln in r.stdout.splitlines()
                      if "Front Left: Capture" in ln), "")
        print(f"[boot] capture gain -> {level or CAPTURE_PGA}", flush=True)
    except Exception as e:
        print(f"[boot] WARNING could not set capture gain: "
              f"{type(e).__name__}: {e}", flush=True)


def synthesise_phrase(api_key, phrase, path):
    """Speak one fixed sentence through the omni model and cache it at `path`.
    The prompt has to forbid embellishment: this is a chat model being used as
    a synthesiser, and left alone it answers the sentence instead of reading
    it."""
    chunks = []
    for resp in dashscope.MultiModalConversation.call(
        api_key=api_key, model=MODEL,
        messages=[{"role": "user", "content": [{"text":
            f"只念这一句，不要加别的字：{phrase}"}]}],
        modalities=["text", "audio"], audio={"voice": VOICE, "format": "wav"},
        # Ten of these run before the wake loop on a first boot. Without a
        # timeout one hung stream keeps the daemon from ever listening.
        request_timeout=REQUEST_TIMEOUT_S,
        result_format="message", stream=True):
        j = json.loads(str(resp))
        for ch in (j.get("output") or {}).get("choices", []) or []:
            for c in ch.get("message", {}).get("content", []):
                if isinstance(c, dict):
                    au = c.get("audio")
                    if isinstance(au, dict) and au.get("data"):
                        chunks.append(au["data"])
    if not chunks:
        return False
    raw = b"".join(base64.b64decode(c) for c in chunks)
    # Write then rename: the existence check in ensure_filler() cannot tell a
    # whole file from a truncated one, so a power cut part-way through a direct
    # write would cache the truncation forever.
    tmp = path + ".tmp"
    if raw[:4] == b"RIFF":
        with open(tmp, "wb") as f:
            f.write(raw)
    else:
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(raw)
    os.replace(tmp, path)
    return True


def ensure_phrases(api_key, kind, phrases):
    """Synthesise each phrase once and keep it on disk. Returns {phrase: path}
    for the ones that are actually there. Best-effort per phrase: one failure
    costs that wording, not the feature. Only the first boot pays for this --
    afterwards every file is cached and this makes no network call at all."""
    wanted = {phrase_path(kind, ph): ph for ph in phrases}
    ready = {}
    for path, phrase in wanted.items():
        if not os.path.exists(path):
            try:
                if not synthesise_phrase(api_key, phrase, path):
                    print(f"[boot] no audio came back for {phrase!r}", flush=True)
                    continue
                print(f"[boot] cached {kind}: {phrase}", flush=True)
            except Exception as e:
                print(f"[boot] could not cache {phrase!r}: "
                      f"{type(e).__name__}: {e}", flush=True)
                continue
        ready[phrase] = path
    # Wordings edited out of the source list would otherwise sit on the SD card
    # forever, one orphan per revision. Safe here: this runs before the wake
    # loop, so no playback can be holding one of these files.
    for stale in glob.glob(os.path.join(PHRASE_DIR, f"{kind}_{VOICE}_*.wav")):
        if stale not in wanted:
            try:
                os.remove(stale)
            except OSError:
                pass
    print(f"[boot] {len(ready)}/{len(wanted)} {kind} phrases ready.", flush=True)
    return ready


def ensure_acks(api_key):
    """Cache the command acknowledgements. A missing one falls back to the beep
    in play_ack, so this failing degrades the feedback rather than the
    feature."""
    ready = ensure_phrases(api_key, "ack", list(COMMAND_ACKS.values()))
    ACK_WAVS.clear()
    ACK_WAVS.update({key: ready[text] for key, text in COMMAND_ACKS.items()
                     if text in ready})


def ensure_filler(api_key):
    """Publish the holding-phrase rotation pool. Empty is supported: with no
    files HoldingPhrase arms no timer and we simply stay silent while
    searching."""
    ready = ensure_phrases(api_key, "filler", FILLER_PHRASES)
    FILLER_WAVS[:] = [ready[ph] for ph in FILLER_PHRASES if ph in ready]


def device_today():
    """Today's date where the device SITS, formatted for the research prompt.
    Falls back to the Pi's own clock if tzdata is missing rather than losing
    the turn -- and says so, since a wrong date is a quiet failure."""
    try:
        now = datetime.datetime.now(ZoneInfo(DEVICE_TZ))
    except Exception as e:
        print(f"[research] no tz data for {DEVICE_TZ} ({type(e).__name__}) — "
              f"using the Pi's local date.", flush=True)
        now = datetime.datetime.now()
    return now.strftime("%Y年%m月%d日")


def research_pass(audio_b64, api_key, on_search=None, give_up=None):
    """Round 1: raw audio in, facts out. No system prompt, no instructions —
    see RESEARCH_MAX_TOKENS. Returns (facts_text, n_sources); facts_text is
    "" if the call failed, in which case round 2 answers unaided.

    on_search() fires the moment the stream first reports a non-empty
    search_info. That is the signal that this turn genuinely needed the web,
    and it is what lets the speculative voice call be killed early instead of
    generating audio nobody will hear.

    give_up() is polled per chunk and abandons the stream when it returns True.
    It exists for device commands: "音量小一点" is something this round will
    happily go and SEARCH for, and waiting that out meant the volume moved only
    after a web round-trip, with the holding phrase announcing a lookup nobody
    asked for."""
    t0 = time.monotonic()
    parts, n_sources = [], 0
    log_stage("research", "start", model=RESEARCH_MODEL,
              deadline=f"{RESEARCH_DEADLINE_S}s")
    try:
        for resp in dashscope.MultiModalConversation.call(
            api_key=api_key, model=RESEARCH_MODEL,
            messages=[{"role": "user", "content": [
                {"audio": f"data:audio/wav;base64,{audio_b64}"},
                {"text": f"（我在{DEVICE_LOCATION}，今天是"
                         f"{device_today()}）"}]}],
            modalities=["text"],
            enable_search=True,
            search_options={"search_strategy": "agent", "enable_source": True},
            max_tokens=RESEARCH_MAX_TOKENS,
            request_timeout=REQUEST_TIMEOUT_S,
            result_format="message", stream=True):
            if give_up is not None and give_up():
                print(f"[research] abandoned at {time.monotonic()-t0:.1f}s — "
                      f"the turn no longer needs facts.", flush=True)
                return "", 0
            if time.monotonic() - t0 > RESEARCH_DEADLINE_S:
                print(f"[research] deadline {RESEARCH_DEADLINE_S}s exceeded — "
                      f"going with what arrived ({n_sources} sources).", flush=True)
                break
            j = json.loads(str(resp))
            status = j.get("status_code")
            if status and status != 200:
                print(f"[research] cloud error: {status} {j.get('code')}", flush=True)
                return "", 0
            out = j.get("output") or {}
            hits = (out.get("search_info") or {}).get("search_results") or []
            if hits and not n_sources:
                # How early this lands decides how much speculative audio we
                # pay for on a search turn. Logged so it can be checked in
                # the field rather than assumed.
                print(f"[research] search fired at {time.monotonic()-t0:.1f}s "
                      f"({len(hits)} sources).", flush=True)
                if on_search is not None:
                    on_search()
            n_sources = max(n_sources, len(hits))
            for ch in out.get("choices", []) or []:
                for c in ch.get("message", {}).get("content", []):
                    if isinstance(c, dict) and c.get("text"):
                        parts.append(c["text"])
    except Exception as e:
        print(f"[research] failed after {time.monotonic()-t0:.1f}s: "
              f"{type(e).__name__}: {e}", flush=True)
        return "", 0
    print(f"[research] {time.monotonic()-t0:.1f}s, {n_sources} sources "
          f"({RESEARCH_MODEL}).", flush=True)
    return "".join(parts), n_sources


def voice_call(content, history, api_key, stop_event=None):
    """Round 2: one call to the voice model carrying the full persona and the
    session history. `content` is either the user's audio (answering the
    question directly) or round 1's facts as text (restyling them). Returns
    (text, audio_chunks), or None on failure or abort.

    Transient DNS / socket / TLS errors — Pi 3 Wi-Fi is flaky — would
    otherwise raise out of the streaming iterator and take the daemon down.
    Any failure here is a dead turn, which converse_session already counts."""
    t0 = time.monotonic()
    audio_chunks, text_parts = [], []
    content_kind = "audio" if any("audio" in item for item in content) else "text"
    log_stage("voice", "start", model=MODEL, content=content_kind,
              history_turns=len(history) // 2)
    try:
        responses = dashscope.MultiModalConversation.call(
            api_key=api_key, model=MODEL,
            messages=(
                [{"role": "system", "content": [{"text": SICHUAN_SYSTEM_PROMPT}]}]
                + history
                + [{"role": "user", "content": content}]
            ),
            modalities=["text", "audio"],
            audio={"voice": VOICE, "format": "wav"},
            request_timeout=REQUEST_TIMEOUT_S,
            result_format="message", stream=True,
        )
        for resp in responses:
            if stop_event is not None and stop_event.is_set():
                print(f"[voice] aborted at {time.monotonic()-t0:.1f}s.", flush=True)
                return None
            if time.monotonic() - t0 > VOICE_DEADLINE_S:
                print(f"[voice] deadline {VOICE_DEADLINE_S}s exceeded after "
                      f"{len(audio_chunks)} chunks — stopping.", flush=True)
                break
            j = json.loads(str(resp))
            status = j.get("status_code")
            if status and status != 200:
                print(f"[voice] cloud error: {status} {j.get('code')}: "
                      f"{j.get('message')}", flush=True)
                return None
            for ch in (j.get("output") or {}).get("choices", []) or []:
                for c in ch.get("message", {}).get("content", []):
                    if not isinstance(c, dict): continue
                    if c.get("text"): text_parts.append(c["text"])
                    au = c.get("audio")
                    if isinstance(au, dict) and au.get("data"):
                        audio_chunks.append(au["data"])
    except Exception as e:
        print(f"[voice] request failed after {time.monotonic()-t0:.1f}s: "
              f"{type(e).__name__}: {e}", flush=True)
        return None
    print(f"[voice] {time.monotonic()-t0:.1f}s, {len(audio_chunks)} chunks.",
          flush=True)
    return "".join(text_parts), audio_chunks


class SpeculativeVoice:
    """Round 2 launched in PARALLEL with round 1, betting the turn needs no
    web search — which is the common case. 你好 and 你吃了没 do not need the
    internet, and paying round 1's ~2.3 s serially before round 2 even started
    made every ordinary turn slower than it had been before search existed.

    Win (round 1 reports no sources): this call IS the answer and the turn
    costs one round-trip again. Lose: round 1's on_search fires, the stream is
    abandoned mid-flight, and the restyle path runs with no latency lost — the
    discarded call overlapped the research that beat it. The wasted audio
    tokens on a search turn buy the latency back on every other turn, and the
    early abort keeps that waste small."""

    def __init__(self, audio_b64, history, api_key):
        self.stop = threading.Event()
        self.result = None
        log_stage("voice", "speculative start")
        # History is copied, not shared: cloud_reply mutates the real list
        # once the turn resolves, and this thread may still be reading it.
        self._thread = threading.Thread(
            target=self._run, args=(audio_b64, list(history), api_key),
            daemon=True)
        self._thread.start()

    def _run(self, audio_b64, history, api_key):
        self.result = voice_call(
            [{"audio": f"data:audio/wav;base64,{audio_b64}"}],
            history, api_key, stop_event=self.stop)

    def abort(self):
        log_stage("voice", "speculative abort requested")
        self.stop.set()

    def wait(self):
        log_stage("voice", "waiting for speculative result",
                  timeout=f"{SPEC_WAIT_TIMEOUT_S}s")
        self._thread.join(SPEC_WAIT_TIMEOUT_S)
        if self._thread.is_alive():
            print("[voice] speculative call still running after "
                  f"{SPEC_WAIT_TIMEOUT_S}s — abandoning it.", flush=True)
            self.abort()
            return None
        return self.result


def load_volume():
    """The remembered playback level, or the shipped default. Any unreadable or
    nonsense state file is treated as absent rather than fatal: a speaker that
    refuses to boot is worse than one at the wrong volume."""
    try:
        with open(VOLUME_STATE) as f:
            return max(VOLUME_FLOOR, min(VOLUME_CEILING, int(f.read().strip())))
    except Exception:
        return VOLUME_DEFAULT


def save_volume(level):
    """Write then rename, so a power cut cannot leave a half-written level that
    load_volume() would silently round into something arbitrary."""
    try:
        tmp = VOLUME_STATE + ".tmp"
        with open(tmp, "w") as f:
            f.write(str(int(level)))
        os.replace(tmp, VOLUME_STATE)
    except Exception as e:
        print(f"[volume] could not persist {level}: {type(e).__name__}: {e}",
              flush=True)


def apply_volume(level):
    """Set the DAC volume on the HAT. Returns True on success. Never fatal, but
    never silent either: a wrong level presents as "it got quiet by itself",
    which is expensive to diagnose from 1000 km away."""
    try:
        r = subprocess.run(
            ["amixer", "-c", CAPTURE_CARD, "sset", PLAYBACK_CONTROL, str(int(level))],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"[volume] WARNING amixer failed on {CAPTURE_CARD}: "
                  f"{r.stderr.strip()[:200]}", flush=True)
            return False
        shown = next((ln.strip() for ln in r.stdout.splitlines()
                      if "Front Left: Playback" in ln), "")
        print(f"[volume] {PLAYBACK_CONTROL} -> {shown or level}", flush=True)
        return True
    except Exception as e:
        print(f"[volume] WARNING could not set volume: "
              f"{type(e).__name__}: {e}", flush=True)
        return False


def detect_command(audio_b64, api_key):
    """Is the user telling the DEVICE to do something, rather than asking it? Returns one of
    COMMAND_TAGS, or None meaning "this is conversation, carry on".

    Fail-closed, deliberately: every error, every timeout and every answer that
    is not exactly a known tag returns None. A missed command costs one repeated
    request; a false positive changes the volume in the middle of someone's
    question, which is the failure the whole prompt is written against."""
    t0 = time.monotonic()
    parts = []
    log_stage("command", "start", model=COMMAND_MODEL,
              deadline=f"{COMMAND_DEADLINE_S}s")
    try:
        for resp in dashscope.MultiModalConversation.call(
            api_key=api_key, model=COMMAND_MODEL,
            messages=[
                {"role": "system", "content": [{"text": COMMAND_PROMPT}]},
                {"role": "user", "content": [
                    {"audio": f"data:audio/wav;base64,{audio_b64}"}]},
            ],
            modalities=["text"],
            max_tokens=COMMAND_MAX_TOKENS,
            request_timeout=REQUEST_TIMEOUT_S,
            result_format="message", stream=True):
            j = json.loads(str(resp))
            status = j.get("status_code")
            if status and status != 200:
                print(f"[command] cloud error: {status} {j.get('code')}",
                      flush=True)
                return None
            for ch in (j.get("output") or {}).get("choices", []) or []:
                for c in ch.get("message", {}).get("content", []):
                    if isinstance(c, dict) and c.get("text"):
                        parts.append(c["text"])
    except Exception as e:
        print(f"[command] failed after {time.monotonic()-t0:.1f}s: "
              f"{type(e).__name__}: {e}", flush=True)
        return None
    raw = "".join(parts).strip()
    # Strip surrounding punctuation and an optional label ("标签：VOLUME_UP"),
    # then require the WHOLE remainder to be a tag. Deleting every non-letter
    # instead would turn any sentence that merely mentions a tag into that tag:
    # "不是 VOLUME_UP 指令" would have become VOLUME_UP, which is the exact
    # false positive this call exists to avoid.
    tag = raw.upper().strip(" \t\r\n。．.!！?？、，,;；:：\"'“”‘’()（）[]【】*`")
    tag = re.sub(r"^[^A-Z]*[:：]\s*", "", tag)
    print(f"[command] {time.monotonic()-t0:.1f}s -> {raw!r}", flush=True)
    return tag if tag in COMMAND_TAGS else None


class CommandWatcher:
    """Command detection on its own thread, started with the search and the
    speculative answer so it adds no wall-clock. result() is what the turn waits on, bounded: a verdict that
    arrives after round 2 has started speaking is no longer actionable."""

    def __init__(self, audio_b64, api_key, on_decide=None):
        self.tag = None
        self._on_decide = on_decide
        # Guards the hand-off between a verdict landing and result() giving
        # up on it, so exactly one of the two wins.
        self._lock = threading.Lock()
        self._gave_up = False
        self._thread = threading.Thread(
            target=self._run, args=(audio_b64, api_key), daemon=True)
        self._thread.start()

    def _run(self, audio_b64, api_key):
        tag = detect_command(audio_b64, api_key)
        with self._lock:
            # The turn already went ahead as conversation. Acting now would
            # abort the speculative reply it is waiting on and execute nothing.
            if self._gave_up:
                return
            self.tag = tag
        # Fire the moment we know, not when the turn gets around to asking.
        # give_up is only polled when a research chunk ARRIVES, so on a stream
        # that goes quiet mid-search the holding phrase would otherwise still
        # announce a lookup for a turn that was never a question.
        if self.tag is not None and self._on_decide is not None:
            try:
                self._on_decide()
            except Exception as e:
                print(f"[command] on_decide failed: {type(e).__name__}: {e}",
                      flush=True)

    def decided(self):
        """True once a tag is in hand. Polled from inside round 1's stream so a
        command does not have to wait out a search it never wanted."""
        return self.tag is not None

    def result(self, timeout):
        self._thread.join(max(0.0, timeout))
        with self._lock:
            if self.tag is None and self._thread.is_alive():
                self._gave_up = True
                print("[command] no verdict in time — treating as conversation.",
                      flush=True)
            return self.tag


def play_ack(key, beep_fallback=True):
    """Speak the outcome of a command. Silent success is indistinguishable from
    a device that did not hear, and that is what makes someone say it again,
    louder -- so a phrase that never cached still beeps rather than saying
    nothing. beep_fallback=False is for a line the beep would contradict."""
    path = ACK_WAVS.get(key)
    if path and os.path.exists(path):
        return play_wav(path)
    if not beep_fallback:
        print(f"[command] no cached ack for {key!r} — staying silent.",
              flush=True)
        return False
    print(f"[command] no cached ack for {key!r} — beeping instead.", flush=True)
    return play_wav(BEEP_ACK)


def handle_command(tag):
    """Act on a device command locally. Returns True if the user got audible
    confirmation; the caller counts that as a live turn, so adjusting the volume
    does not look like a dead turn and end the session.

    A command never joins the history. It is not part of the conversation, and
    replaying it would invite the model to discuss it on the next turn."""
    if tag == "REPEAT":
        if os.path.exists(RESPONSE_WAV):
            return play_wav(RESPONSE_WAV)
        return play_ack("nothing_to_repeat")
    step = VOLUME_STEP if tag == "VOLUME_UP" else -VOLUME_STEP
    before = load_volume()
    after = max(VOLUME_FLOOR, min(VOLUME_CEILING, before + step))
    if after == before:
        # Already at the stop. Saying so beats acknowledging a change that did
        # not happen: a cheerful "要得" at the floor has them ask again, hear the
        # same reply, and conclude the device is broken.
        return play_ack("at_max" if step > 0 else "at_min")
    if not apply_volume(after):
        return False
    save_volume(after)
    return play_ack("up" if step > 0 else "down")


def cloud_reply(audio_bytes, api_key, history):
    """One user turn. Round 1 researches while a speculative round 2 answers
    the audio directly; whichever way round 1 settles decides which reply is
    spoken. Returns True on success, False on cloud error / no audio."""
    with wave.open(RECORDING_WAV, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(CONV_RATE_IN)
        w.writeframes(audio_bytes)
    log_stage("turn", "recording saved", file=RECORDING_WAV,
              bytes=len(audio_bytes),
              duration=f"{len(audio_bytes)/(CONV_RATE_IN*2):.2f}s")
    with open(RECORDING_WAV, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    t0 = time.monotonic()
    log_stage("turn", "cloud turn start", history_turns=len(history)//2,
              speculative=SPECULATIVE_VOICE, command_detection=COMMAND_DETECTION)

    spec = (SpeculativeVoice(audio_b64, history, api_key)
            if SPECULATIVE_VOICE else None)

    # The holding phrase only reaches a turn slow enough to mean a real search
    # is happening: a speculative win cancels it first, and so does a device
    # command -- see CommandWatcher's on_decide.
    holding = HoldingPhrase()

    def _on_command():
        holding.cancel()
        if spec is not None:
            spec.abort()

    # Built after `holding` on purpose: it has to be able to silence it.
    watcher = (CommandWatcher(audio_b64, api_key, on_decide=_on_command)
               if COMMAND_DETECTION else None)
    # Whether round 1 SEARCHED, tracked separately from whether it SUCCEEDED.
    # on_search kills the speculative call irreversibly, and round 1 can still
    # fail after that point and report 0 sources — which used to send us to
    # spec.wait() on a thread guaranteed to return None, throwing away a good
    # reply and paying for a third round-trip to rediscover that.
    search_fired = threading.Event()

    def _on_search():
        search_fired.set()
        if spec is not None:
            spec.abort()

    facts, n_sources = research_pass(
        audio_b64, api_key, on_search=_on_search,
        give_up=(watcher.decided if watcher else None))
    holding.cancel()
    log_stage("turn", "research finished", facts=bool(facts),
              sources=n_sources, search_fired=search_fired.is_set())

    # The command verdict settles first, because a command is not a question:
    # if the user asked for a volume change there is no answer to speak, and the
    # speculative reply -- which is busy answering "音量小一点" as conversation --
    # has to be thrown away rather than played.
    tag = (watcher.result(COMMAND_DEADLINE_S - (time.monotonic() - t0))
           if watcher else None)
    if tag:
        print(f"[turn] device command: {tag}", flush=True)
        if spec is not None:
            spec.abort()
        return handle_command(tag)

    # Restyle only when round 1 both SEARCHED and produced text. Round 1
    # answers plenty of questions from its own knowledge without searching;
    # when it did not search, the speculative reply is missing nothing — and it
    # is the better answer anyway, because it heard the question itself rather
    # than a paraphrase of it.
    result = None
    if facts and (n_sources > 0 or search_fired.is_set()):
        log_stage("turn", "voice path", mode="restyle_search_facts")
        if spec is not None:
            spec.abort()
        result = voice_call(
            [{"text": "下面是我刚才帮你查到的最新资料，是准的。"
                      "照着它用四川话回答长辈的问题，两三句话讲完，"
                      "温度、价钱这些数字一定要讲出来，不要念原文，"
                      "也不要说查不到。称呼直接用“您”，不准写成"
                      "“爷爷/奶奶”这种带杠的写法——这段话是要念出来的：\n" + facts}],
            history, api_key)
    elif spec is not None and not search_fired.is_set():
        log_stage("turn", "voice path", mode="speculative_direct")
        result = spec.wait()
    elif spec is not None:
        # Search fired and then round 1 failed. The speculative stream is
        # already dead and joining it can only return None, so skip straight
        # to answering unaided rather than waiting to be told that.
        print("[turn] search fired but research failed — answering unaided.",
              flush=True)
    if result is None:
        # Nothing usable from either path — answer the audio unaided rather
        # than drop the turn. Also the path taken when SPECULATIVE_VOICE=False
        # and the turn did not search.
        log_stage("turn", "voice path", mode="fallback_direct")
        result = voice_call(
            [{"audio": f"data:audio/wav;base64,{audio_b64}"}], history, api_key)
    if result is None:
        log_stage("turn", "cloud turn failed", reason="no_voice_result")
        return False
    text, audio_chunks = result

    print(f"[turn] {time.monotonic()-t0:.1f}s total, {n_sources} sources.",
          flush=True)
    print("[turn] reply:", text, flush=True)
    if not audio_chunks:
        print("[turn] no audio in response.", flush=True)
        log_stage("turn", "cloud turn failed", reason="text_without_audio")
        return False
    reply_bytes = b"".join(base64.b64decode(p_) for p_ in audio_chunks)
    if reply_bytes[:4] == b"RIFF":
        with open(RESPONSE_WAV, "wb") as f:
            f.write(reply_bytes)
    else:
        with wave.open(RESPONSE_WAV, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(reply_bytes)
    if not play_wav(RESPONSE_WAV):
        # The audio was generated but never reached the room. Count it as a
        # dead turn and keep it out of the history: as far as the user is
        # concerned this answer does not exist, and a session that silently
        # "remembers" something never spoken drifts from there on.
        log_stage("turn", "cloud turn failed", reason="playback_failed")
        return False
    # History carries the user's ACTUAL question as audio, never the restyle
    # instruction a search turn sends to the voice model. That blob is
    # scaffolding; storing it made turn N+1 see "把下面这段内容…" as something
    # the user had said. Only successful turns join the history, so a failed
    # call cannot leave a dangling user turn with no answer after it.
    history.append({"role": "user",
                    "content": [{"audio": f"data:audio/wav;base64,{audio_b64}"}]})
    history.append({"role": "assistant", "content": [{"text": text}]})
    del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
    log_stage("turn", "cloud turn success", elapsed=f"{time.monotonic()-t0:.1f}s",
              history_turns=len(history)//2)
    return True


def converse_session(p, api_key):
    """Multi-turn session. Listens after each reply and continues as long as
    the user keeps producing real speech. Ends on natural silence, after
    MAX_CONSECUTIVE_DEAD_TURNS turns of noise-only input, or at
    MAX_SESSION_TURNS cloud turns. Returns when the
    session ends; caller resumes wake-word listening."""
    vad = build_vad()
    # Fresh history per session: a new wake word starts a new conversation.
    history = []
    turn = 0
    dead_turns = 0
    cloud_turns = 0
    log_stage("session", "start", vad=VAD_ENGINE,
              first_timeout=f"{FIRST_TURN_SILENCE_TIMEOUT_S}s",
              discard_after_open=f"{POST_ACK_MIC_DISCARD_S}s")
    while True:
        turn += 1
        if hasattr(vad, "reset"):
            vad.reset()
        # The holding-phrase timer fires on its own thread and can still be
        # emitting when a turn ends early (a failed call, a dead turn). Opening
        # input on a half-duplex codec while it plays either raises OSError —
        # which escapes main(), killing the daemon — or lets the device hear
        # its own voice.
        wait_for_audio_idle()
        log_stage("turn", "opening conversation mic", turn=turn)
        stream = p.open(
            format=pyaudio.paInt16, channels=1, rate=CONV_RATE_IN,
            input=True, frames_per_buffer=VAD_FRAME_SAMPLES,
        )
        # Discard the first N seconds after opening the mic. aplay can
        # return before the codec buffer is fully drained, so speaker
        # audio may still be emitting for a moment; plus room echo of
        # the reply lingers a bit.
        t = time.monotonic()
        discard_frames = 0
        discard_peak_rms = 0
        while time.monotonic() - t < POST_ACK_MIC_DISCARD_S:
            data = stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
            discard_frames += 1
            discard_peak_rms = max(discard_peak_rms, pcm_rms(data))
        # Drain anything still queued after the warmup window.
        drained_frames = 0
        drained_peak_rms = 0
        while stream.get_read_available() >= VAD_FRAME_SAMPLES:
            data = stream.read(VAD_FRAME_SAMPLES, exception_on_overflow=False)
            drained_frames += 1
            drained_peak_rms = max(drained_peak_rms, pcm_rms(data))
        log_stage("turn", "post-open discard complete", turn=turn,
                  discard_frames=discard_frames,
                  discard_peak_rms=discard_peak_rms,
                  drained_frames=drained_frames,
                  drained_peak_rms=drained_peak_rms)

        if dead_turns > 0:
            timeout = POST_DEAD_SILENCE_TIMEOUT_S
        elif turn == 1:
            timeout = FIRST_TURN_SILENCE_TIMEOUT_S
        else:
            timeout = FOLLOWUP_SILENCE_TIMEOUT_S
        print(f"[turn {turn}] listening (VAD; silence timeout {timeout}s)...", flush=True)
        log_stage("turn", "vad listen start", turn=turn, timeout=f"{timeout}s")
        audio_bytes, reason, st = record_utterance(stream, vad, timeout)
        stream.stop_stream(); stream.close()
        log_stage("turn", "vad listen done", turn=turn, reason=reason,
                  stop=st.get("stop_reason"),
                  leading_silence_ms=st.get("leading_silence_ms"),
                  opened_after_ms=st.get("opened_after_ms"))

        if reason == "timeout":
            print(f"[turn {turn}] silence — ending session.", flush=True)
            log_stage("session", "end", reason="silence_timeout", turn=turn)
            return

        utt_ms = len(audio_bytes) * 1000 // (CONV_RATE_IN * 2)
        # Logged on every turn, including good ones, so the thresholds can be
        # tuned against what the parents' room actually produces.
        # speech_ms is what the cloud actually gets to work with: the capture
        # minus the pre-roll and the trailing silence that ended it. When this
        # is small the model hears a fragment, however healthy utt_ms looks.
        speech_ms = max(0, utt_ms - PRE_SPEECH_PAD_MS - END_SILENCE_MS)
        print(f"[turn {turn}] captured {utt_ms/1000:.1f}s "
              f"(~{speech_ms}ms speech, voiced {st['voiced_ratio']*100:.0f}%, "
              f"longest run {st['longest_run_ms']}ms).", flush=True)
        too_short = utt_ms < MIN_UTTERANCE_MS
        not_speechlike = (st["longest_run_ms"] < MIN_VOICED_RUN_MS
                          or st["voiced_ratio"] < MIN_VOICED_RATIO)
        if too_short or not_speechlike:
            dead_turns += 1
            why = "too short" if too_short else "no speech-like voicing"
            print(f"[turn {turn}] {why} — treating as noise, no cloud call "
                  f"(dead {dead_turns}/{MAX_CONSECUTIVE_DEAD_TURNS}).", flush=True)
            if dead_turns >= MAX_CONSECUTIVE_DEAD_TURNS:
                print(f"[session] {dead_turns} consecutive dead turns — ending.", flush=True)
                log_stage("session", "end", reason="dead_turns", turn=turn)
                return
            continue
        ok = cloud_reply(audio_bytes, api_key, history)
        if ok:
            dead_turns = 0
        else:
            dead_turns += 1
            print(f"[turn {turn}] cloud returned no audio (dead {dead_turns}/{MAX_CONSECUTIVE_DEAD_TURNS}).", flush=True)
            if dead_turns >= MAX_CONSECUTIVE_DEAD_TURNS:
                print(f"[session] {dead_turns} consecutive dead turns — ending.", flush=True)
                log_stage("session", "end", reason="dead_turns", turn=turn)
                return
        cloud_turns += 1
        if cloud_turns >= MAX_SESSION_TURNS:
            print(f"[session] {cloud_turns} cloud turns — session cap reached, "
                  f"ending.", flush=True)
            # No beep if the phrase never cached: the beep means "I'm
            # listening", and this is the moment the device stops.
            play_ack("session_cap", beep_fallback=False)
            log_stage("session", "end", reason="turn_cap", turn=turn)
            return


class NearMissWatcher:
    """Runs a deliberately over-sensitive copy of the spotter on a worker
    thread. When it fires and the live detector did not, the phrase was
    spoken and rejected on threshold — which is the thing the logs could
    not distinguish from silence before. Diagnostic only: it never wakes
    the device. Frames are dropped rather than queued without bound, so a
    slow decode degrades this watcher and never the real detector."""

    def __init__(self):
        self.q = queue.Queue(maxsize=40)
        self.last_detection = 0.0
        self.dropped = 0
        threading.Thread(target=self._run, daemon=True).start()

    def feed(self, audio_f32, peak_rms):
        try:
            self.q.put_nowait((audio_f32, peak_rms))
        except queue.Full:
            self.dropped += 1

    def note_detection(self):
        self.last_detection = time.monotonic()

    def _run(self):
        spotter = build_kws(NEARMISS_SCORE, NEARMISS_THRESHOLD)
        stream = spotter.create_stream()
        while True:
            audio_f32, peak_rms = self.q.get()
            stream.accept_waveform(WAKE_RATE, audio_f32)
            while spotter.is_ready(stream):
                spotter.decode_stream(stream)
            if not spotter.get_result(stream):
                continue
            spotter.reset_stream(stream)
            # The live detector fires first; anything within 2 s of a real
            # wake is that same utterance, not a miss.
            if time.monotonic() - self.last_detection < 2.0:
                continue
            print(f"[wake] NEAR-MISS: heard at threshold={NEARMISS_THRESHOLD}/"
                  f"score={NEARMISS_SCORE}, rejected by live "
                  f"{KWS_THRESHOLD}/{KWS_SCORE} (peak_rms={peak_rms}, "
                  f"dropped_frames={self.dropped})", flush=True)


def build_kws(keywords_score=KWS_SCORE, keywords_threshold=KWS_THRESHOLD):
    return KeywordSpotter(
        tokens=f"{KWS_MODEL_DIR}/tokens.txt",
        encoder=f"{KWS_MODEL_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        decoder=f"{KWS_MODEL_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        joiner=f"{KWS_MODEL_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        keywords_file=KWS_KEYWORDS_FILE,
        num_threads=1,
        max_active_paths=KWS_MAX_ACTIVE_PATHS,
        keywords_score=keywords_score,
        keywords_threshold=keywords_threshold,
        num_trailing_blanks=1,
        provider="cpu",
    )


def main():
    # Alibaba bills Model Studio per WORKSPACE, not per key, so a key created
    # in the shared workspace is indistinguishable from every other Qwen call
    # on the account. A key made inside a workspace of its own gives this
    # device its own line on the bill -- see tools/usage-report.sh.
    # Falls back to the shared key so the device keeps working before the
    # switch, and on any Pi whose ~/.bashrc has not been updated yet.
    api_key = (os.getenv("SICHUAN_DASHSCOPE_API_KEY")
               or os.getenv("DASHSCOPE_API_KEY"))
    if not api_key:
        sys.exit("neither SICHUAN_DASHSCOPE_API_KEY nor DASHSCOPE_API_KEY is set")
    if not os.getenv("SICHUAN_DASHSCOPE_API_KEY"):
        print("[boot] using the shared DASHSCOPE_API_KEY — this device's spend "
              "is not separable on the bill.", flush=True)

    make_beep(BEEP_ACK)
    set_capture_gain()
    apply_volume(load_volume())
    ensure_filler(api_key)
    ensure_acks(api_key)

    print("[boot] loading sherpa-onnx KeywordSpotter (麻婆豆腐)...", flush=True)
    kws = build_kws()
    nearmiss = NearMissWatcher() if NEARMISS_LOGGING else None

    p = pyaudio.PyAudio()

    while True:
        print("[boot] opening mic for wake word + warming up...", flush=True)
        wake_stream = p.open(
            format=pyaudio.paInt16, channels=1, rate=WAKE_RATE,
            input=True, frames_per_buffer=WAKE_CHUNK,
        )
        t = time.monotonic()
        while time.monotonic() - t < WARMUP_SECS:
            wake_stream.read(WAKE_CHUNK, exception_on_overflow=False)

        kws_stream = kws.create_stream()
        print("[ready] LISTENING for 麻婆豆腐. Say the phrase to trigger a turn.", flush=True)

        # Stats every 5 s so we can confirm audio is reaching the model
        last_stats = time.monotonic()
        frames_w = 0
        peak_rms_w = 0
        clipped_w = 0
        samples_w = 0
        try:
            while True:
                data = wake_stream.read(WAKE_CHUNK, exception_on_overflow=False)
                audio_i16 = np.frombuffer(data, dtype=np.int16)
                # peak RMS for visibility
                if len(audio_i16) > 0:
                    rms = int(math.sqrt(float(np.mean(audio_i16.astype(np.int64) ** 2))))
                    if rms > peak_rms_w: peak_rms_w = rms
                    # Samples pinned near full scale mean the ADC is
                    # saturating: the waveform the model sees is a
                    # distorted version of the phrase, which is exactly
                    # how "louder makes it worse" happens.
                    clipped_w += int(np.count_nonzero(np.abs(audio_i16) > 32000))
                    samples_w += len(audio_i16)
                # sherpa-onnx wants float32 in [-1, 1]
                audio_f32 = audio_i16.astype(np.float32) / 32768.0
                kws_stream.accept_waveform(WAKE_RATE, audio_f32)
                while kws.is_ready(kws_stream):
                    kws.decode_stream(kws_stream)
                result = kws.get_result(kws_stream)
                if nearmiss is not None:
                    nearmiss.feed(audio_f32, peak_rms_w)
                frames_w += 1
                if time.monotonic() - last_stats >= 5.0:
                    clip_pct = (100.0 * clipped_w / samples_w) if samples_w else 0.0
                    print(f"[wake] frames={frames_w}/5s peak_rms={peak_rms_w} "
                          f"clipped={clip_pct:.2f}%", flush=True)
                    frames_w = 0; peak_rms_w = 0; clipped_w = 0; samples_w = 0
                    last_stats = time.monotonic()
                if result:
                    if nearmiss is not None:
                        nearmiss.note_detection()
                    print(f"\n*** WAKE detected ({result!r}) — opening session ***", flush=True)
                    log_stage("wake", "detected", result=repr(result))
                    # Free codec for the conversation
                    log_stage("wake", "closing wake mic")
                    wake_stream.stop_stream(); wake_stream.close(); wake_stream = None
                    log_stage("wake", "ack start")
                    ack_ok = play_wav("/tmp/ack.wav")
                    log_stage("wake", "ack done", ok=ack_ok)
                    converse_session(p, api_key)
                    print("[session] done. resuming wake-word listening.\n", flush=True)
                    log_stage("wake", "resuming wake loop")
                    break
        except KeyboardInterrupt:
            print("\n[exit] Ctrl+C", flush=True)
            if wake_stream is not None:
                try:
                    wake_stream.stop_stream(); wake_stream.close()
                except Exception: pass
            p.terminate()
            return
        # Loop back: reopen wake_stream and listen again


if __name__ == "__main__":
    main()
