import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# wake_then_converse imports audio / model libraries at module level that only
# exist on the Pi. Stub whichever are missing for the import, then take the
# stubs back out so they cannot make another test file's import look healthy.
_stubbed = []
for _mod in ("pyaudio", "dashscope", "webrtcvad", "sherpa_onnx", "numpy"):
    try:
        __import__(_mod)
    except ImportError:
        sys.modules[_mod] = MagicMock()
        _stubbed.append(_mod)

import wake_then_converse as W

for _mod in _stubbed:
    del sys.modules[_mod]


class _Chunk:
    """One streamed chunk. detect_command parses json.loads(str(resp)), which is
    how the real SDK objects serialise, so a plain dict would not reach the
    parser at all."""

    def __init__(self, payload):
        self._payload = payload

    def __str__(self):
        return json.dumps(self._payload)


def _reply(text):
    """A stream shaped like DashScope's message result_format."""
    return [_Chunk({"status_code": 200, "output": {"choices": [
        {"message": {"content": [{"text": text}]}}]}})]


class TestCommandParse(unittest.TestCase):
    """Command detection is fail-closed: anything that is not exactly a known tag is
    conversation, because a false positive changes the volume mid-question."""

    def _tag(self, text):
        with patch.object(W.dashscope.MultiModalConversation, "call",
                          return_value=_reply(text)):
            return W.detect_command("Zm9v", "key")

    def test_bare_tags_are_accepted(self):
        for tag in W.COMMAND_TAGS:
            self.assertEqual(self._tag(tag), tag)

    def test_punctuation_and_labels_are_stripped(self):
        self.assertEqual(self._tag("VOLUME_DOWN。"), "VOLUME_DOWN")
        self.assertEqual(self._tag(" 标签：VOLUME_UP\n"), "VOLUME_UP")

    def test_a_sentence_that_merely_mentions_a_tag_is_not_a_command(self):
        # Deleting every non-letter would collapse these into the tag they
        # mention, which is the false positive the whole prompt guards against.
        self.assertIsNone(self._tag("不是 VOLUME_UP 指令"))
        self.assertIsNone(self._tag("音量太大了，输出 VOLUME_DOWN"))
        self.assertIsNone(self._tag("VOLUME_UP 还是 VOLUME_DOWN"))

    def test_none_and_chatter_mean_conversation(self):
        for text in ("NONE", "", "这不是指令", "VOLUME", "SHUTDOWN",
                     "不是指令，所以输出 NONE"):
            self.assertIsNone(self._tag(text))

    def test_cloud_error_means_conversation(self):
        with patch.object(W.dashscope.MultiModalConversation, "call",
                          return_value=[_Chunk({"status_code": 400, "code": "nope"})]):
            self.assertIsNone(W.detect_command("Zm9v", "key"))

    def test_exception_means_conversation(self):
        with patch.object(W.dashscope.MultiModalConversation, "call",
                          side_effect=RuntimeError("socket")):
            self.assertIsNone(W.detect_command("Zm9v", "key"))


class TestResearchGivesUp(unittest.TestCase):
    """A device command must not wait out a search it never wanted: round 1 will
    happily go and look up "音量小一点"."""

    def _stream(self, chunks=3):
        payload = {"status_code": 200, "output": {"choices": [
            {"message": {"content": [{"text": "x"}]}}]}}
        return [_Chunk(payload) for _ in range(chunks)]

    def test_give_up_abandons_the_stream(self):
        with patch.object(W.dashscope.MultiModalConversation, "call",
                          return_value=self._stream()):
            self.assertEqual(
                W.research_pass("Zm9v", "key", give_up=lambda: True), ("", 0))

    def test_without_give_up_the_stream_is_consumed(self):
        with patch.object(W.dashscope.MultiModalConversation, "call",
                          return_value=self._stream()):
            facts, n = W.research_pass("Zm9v", "key")
        self.assertEqual((facts, n), ("xxx", 0))

    def test_the_turn_wires_the_watcher_in_as_give_up(self):
        with patch.object(W, "SpeculativeVoice"), \
             patch.object(W, "HoldingPhrase"), \
             patch.object(W, "CommandWatcher") as watcher, \
             patch.object(W, "research_pass", return_value=("", 0)) as research, \
             patch.object(W, "handle_command", return_value=True):
            watcher.return_value.result.return_value = "VOLUME_UP"
            W.cloud_reply(b"\x00\x00" * 800, "key", [])
        self.assertIs(research.call_args.kwargs["give_up"],
                      watcher.return_value.decided)


class TestWatcherSilencesTheFiller(unittest.TestCase):
    """give_up is only polled when a research chunk arrives, so on a stream that
    goes quiet the holding phrase would still announce a lookup for a turn that
    was never a question. The watcher cancels it the moment it decides."""

    def test_a_tag_fires_on_decide(self):
        fired = []
        with patch.object(W, "detect_command", return_value="VOLUME_DOWN"):
            watcher = W.CommandWatcher("Zm9v", "key",
                                       on_decide=lambda: fired.append(True))
            self.assertEqual(watcher.result(2), "VOLUME_DOWN")
        self.assertEqual(fired, [True])

    def test_no_tag_leaves_the_turn_alone(self):
        fired = []
        with patch.object(W, "detect_command", return_value=None):
            watcher = W.CommandWatcher("Zm9v", "key",
                                       on_decide=lambda: fired.append(True))
            self.assertIsNone(watcher.result(2))
        self.assertEqual(fired, [])

    def test_a_raising_callback_does_not_lose_the_tag(self):
        def boom():
            raise RuntimeError("aplay gone")
        with patch.object(W, "detect_command", return_value="VOLUME_UP"):
            watcher = W.CommandWatcher("Zm9v", "key", on_decide=boom)
            self.assertEqual(watcher.result(2), "VOLUME_UP")

    def test_the_turn_builds_the_watcher_able_to_silence_the_filler(self):
        holding = MagicMock()
        spec = MagicMock()
        with patch.object(W, "SpeculativeVoice", return_value=spec), \
             patch.object(W, "HoldingPhrase", return_value=holding), \
             patch.object(W, "CommandWatcher") as watcher, \
             patch.object(W, "research_pass", return_value=("", 0)), \
             patch.object(W, "handle_command", return_value=True):
            watcher.return_value.result.return_value = "VOLUME_UP"
            W.cloud_reply(b"\x00\x00" * 800, "key", [])
            watcher.call_args.kwargs["on_decide"]()
        holding.cancel.assert_called()
        spec.abort.assert_called()

    def test_a_verdict_after_the_deadline_does_not_fire(self):
        # The turn has moved on to the speculative reply by then; firing would
        # abort that reply and execute nothing.
        import threading
        release = threading.Event()
        fired = []

        def slow(*_):
            release.wait(2)
            return "VOLUME_DOWN"
        with patch.object(W, "detect_command", side_effect=slow):
            watcher = W.CommandWatcher("Zm9v", "key",
                                       on_decide=lambda: fired.append(True))
            self.assertIsNone(watcher.result(0.05))
            release.set()
            watcher._thread.join(2)
        self.assertEqual(fired, [])
        self.assertFalse(watcher.decided())


class TestVolumeCommands(unittest.TestCase):
    def setUp(self):
        self.set = patch.object(W, "apply_volume", return_value=True).start()
        self.saved = []
        patch.object(W, "save_volume", self.saved.append).start()
        self.played = []
        patch.object(W, "play_ack",
                     lambda key: self.played.append(key) or True).start()
        self.addCleanup(patch.stopall)

    def _at(self, level):
        return patch.object(W, "load_volume", return_value=level)

    def test_down_then_up_moves_one_step_each_way(self):
        with self._at(W.VOLUME_DEFAULT):
            self.assertTrue(W.handle_command("VOLUME_DOWN"))
        self.assertEqual(self.saved, [W.VOLUME_DEFAULT - W.VOLUME_STEP])
        with self._at(W.VOLUME_DEFAULT):
            W.handle_command("VOLUME_UP")
        self.assertEqual(self.saved[-1], W.VOLUME_DEFAULT + W.VOLUME_STEP)
        self.assertEqual(self.played, ["down", "up"])

    def test_floor_and_ceiling_say_so_and_change_nothing(self):
        with self._at(W.VOLUME_FLOOR):
            self.assertTrue(W.handle_command("VOLUME_DOWN"))
        with self._at(W.VOLUME_CEILING):
            self.assertTrue(W.handle_command("VOLUME_UP"))
        self.assertEqual(self.played, ["at_min", "at_max"])
        self.assertEqual(self.saved, [])
        self.set.assert_not_called()

    def test_a_step_never_overshoots_a_stop(self):
        # One step from just inside the floor must land ON it, not below.
        with self._at(W.VOLUME_FLOOR + 1):
            W.handle_command("VOLUME_DOWN")
        self.assertEqual(self.saved, [W.VOLUME_FLOOR])

    def test_a_failed_mixer_call_is_a_dead_turn_and_is_not_persisted(self):
        self.set.return_value = False
        with self._at(W.VOLUME_DEFAULT):
            self.assertFalse(W.handle_command("VOLUME_DOWN"))
        self.assertEqual(self.saved, [])
        self.assertEqual(self.played, [])


class TestRepeat(unittest.TestCase):
    def test_repeat_replays_the_last_reply(self):
        with patch.object(W.os.path, "exists", return_value=True), \
             patch.object(W, "play_wav", return_value=True) as play:
            self.assertTrue(W.handle_command("REPEAT"))
        play.assert_called_once_with(W.RESPONSE_WAV)

    def test_repeat_with_nothing_to_replay_says_so(self):
        with patch.object(W.os.path, "exists", return_value=False), \
             patch.object(W, "play_ack", return_value=True) as ack:
            self.assertTrue(W.handle_command("REPEAT"))
        ack.assert_called_once_with("nothing_to_repeat")


class TestVolumeState(unittest.TestCase):
    def test_a_corrupt_state_file_falls_back_to_the_default(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".vol", delete=False) as f:
            f.write("not a number")
        with patch.object(W, "VOLUME_STATE", f.name):
            self.assertEqual(W.load_volume(), W.VOLUME_DEFAULT)
        os.unlink(f.name)

    def test_a_remembered_level_is_clamped_into_range(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".vol", delete=False) as f:
            f.write("999")
        with patch.object(W, "VOLUME_STATE", f.name):
            self.assertEqual(W.load_volume(), W.VOLUME_CEILING)
        os.unlink(f.name)

    def test_a_round_trip_survives(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "volume")
        with patch.object(W, "VOLUME_STATE", path):
            W.save_volume(100)
            self.assertEqual(W.load_volume(), 100)


class TestCommandTurn(unittest.TestCase):
    """A command is not a question: nothing is spoken as an answer, the
    speculative reply is thrown away, and the turn leaves no trace in the
    history for the model to comment on next time."""

    def test_a_command_turn_abandons_the_reply_and_the_history(self):
        history = []
        spec = MagicMock()
        with patch.object(W, "SpeculativeVoice", return_value=spec), \
             patch.object(W, "HoldingPhrase"), \
             patch.object(W, "CommandWatcher") as watcher, \
             patch.object(W, "research_pass", return_value=("", 0)), \
             patch.object(W, "handle_command", return_value=True) as handled, \
             patch.object(W, "voice_call") as voice:
            watcher.return_value.result.return_value = "VOLUME_DOWN"
            self.assertTrue(W.cloud_reply(b"\x00\x00" * 800, "key", history))
        handled.assert_called_once_with("VOLUME_DOWN")
        spec.abort.assert_called_once()
        voice.assert_not_called()
        self.assertEqual(history, [])

    def test_an_ordinary_turn_is_unaffected_by_command_detection(self):
        history = []
        spec = MagicMock()
        spec.wait.return_value = ("嗯", ["AAAA"])
        with patch.object(W, "SpeculativeVoice", return_value=spec), \
             patch.object(W, "HoldingPhrase"), \
             patch.object(W, "CommandWatcher") as watcher, \
             patch.object(W, "research_pass", return_value=("", 0)), \
             patch.object(W, "handle_command") as handled, \
             patch.object(W, "play_wav", return_value=True):
            watcher.return_value.result.return_value = None
            self.assertTrue(W.cloud_reply(b"\x00\x00" * 800, "key", history))
        handled.assert_not_called()
        self.assertEqual(len(history), 2)


class TestPlaybackTimeout(unittest.TestCase):
    def test_a_stalled_aplay_exits_so_systemd_restarts_the_service(self):
        stalled = W.subprocess.TimeoutExpired("aplay", W.APLAY_TIMEOUT_S)
        with patch.object(W.os.path, "exists", return_value=True), \
             patch.object(W.subprocess, "run", side_effect=stalled) as run, \
             patch.object(W.os, "_exit") as bail:
            self.assertFalse(W.play_wav("/tmp/x.wav"))
        self.assertEqual(run.call_args.kwargs["timeout"], W.APLAY_TIMEOUT_S)
        bail.assert_called_once_with(1)

    def test_the_session_cap_line_never_falls_back_to_the_listen_beep(self):
        with patch.dict(W.ACK_WAVS, {}, clear=True), \
             patch.object(W, "play_wav") as play:
            self.assertFalse(W.play_ack("session_cap", beep_fallback=False))
            play.assert_not_called()
            W.play_ack("up")
            play.assert_called_once_with(W.BEEP_ACK)
        self.assertIn("session_cap", W.COMMAND_ACKS)


class TestSessionCap(unittest.TestCase):
    """A TV passes every local gate and gets answered, so successful turns
    alone must not be able to keep a session open for ever."""

    def _run(self, replies):
        st = {"voiced_ratio": 0.9, "longest_run_ms": 1000}
        speech = (b"\x00\x00" * 16000, "speech", st)
        with patch.object(W, "build_vad", return_value=MagicMock()), \
             patch.object(W, "wait_for_audio_idle"), \
             patch.object(W, "pcm_rms", return_value=0), \
             patch.object(W, "POST_ACK_MIC_DISCARD_S", 0), \
             patch.object(W, "record_utterance", return_value=speech), \
             patch.object(W, "cloud_reply", side_effect=replies) as cloud, \
             patch.object(W, "play_ack") as ack:
            p = MagicMock()
            p.open.return_value.get_read_available.return_value = 0
            W.converse_session(p, "key")
        return cloud, ack

    def test_the_session_ends_at_the_cap_and_says_so(self):
        cloud, ack = self._run([True] * (W.MAX_SESSION_TURNS + 5))
        self.assertEqual(cloud.call_count, W.MAX_SESSION_TURNS)
        ack.assert_called_once_with("session_cap", beep_fallback=False)

    def test_dead_turns_still_end_it_first_without_the_sign_off(self):
        cloud, ack = self._run([True, False, False, True])
        self.assertEqual(cloud.call_count, 3)
        ack.assert_not_called()


if __name__ == '__main__':
    unittest.main()
