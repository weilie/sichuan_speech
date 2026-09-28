import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

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


class TestDeviceToday(unittest.TestCase):
    def _frozen(self, instant):
        class FrozenDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
        return patch.object(W.datetime, "datetime", FrozenDatetime)

    def test_uses_device_timezone_not_the_pi_clock(self):
        # 16:12 in New York (where the Pi was set up) is already tomorrow in
        # Chengdu, and the prompt must say tomorrow's date.
        instant = datetime.datetime(2026, 9, 28, 16, 12, tzinfo=ZoneInfo("America/New_York"))
        with self._frozen(instant):
            self.assertEqual(W.device_today(), "2026年09月29日")

    def test_falls_back_when_tzdata_is_missing(self):
        with patch.object(W, "ZoneInfo", side_effect=KeyError("no tzdata")):
            self.assertRegex(W.device_today(), r"^\d{4}年\d{2}月\d{2}日$")


if __name__ == '__main__':
    unittest.main()
