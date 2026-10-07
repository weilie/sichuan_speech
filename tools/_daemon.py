"""Import the deployed daemon so the tools measure what actually ships.

    from _daemon import W

Every sweep and live check reads KWS_SCORE, KWS_THRESHOLD, build_kws(),
SileroVad, endpoint() and the gate constants from wake_then_converse itself
rather than carrying a copy. A copy is a second place for the measured value
to drift from the deployed one -- beam width sat unswept for three months
because the daemon and the tools each held an implicit default nobody
compared.

The daemon imports the Pi's audio stack at module level. On a Mac running a
sweep against a copy of the model, pyaudio / dashscope / webrtcvad may be
absent, so whichever of those is missing is stubbed for the import and the
stub is removed again afterwards (the same trick tests/ uses), so a tool
that really needs webrtcvad still gets an honest ImportError. numpy and
sherpa_onnx are never stubbed: every tool needs them for real.
"""
import os
import sys
from unittest.mock import MagicMock

_here = os.path.dirname(os.path.abspath(__file__))
# Searched last-inserted first: the Pi's deployed copy wins when it exists,
# then the repo checkout (tools/ beside src/ on the Mac, beside the daemon
# itself under ~/sichuan on the Pi).
sys.path.insert(0, os.path.join(_here, "..", "src"))
sys.path.insert(0, os.path.join(_here, ".."))
sys.path.insert(0, "/home/weilie/sichuan")

_stubbed = []
for _mod in ("pyaudio", "dashscope", "webrtcvad"):
    try:
        __import__(_mod)
    except ImportError:
        sys.modules[_mod] = MagicMock()
        _stubbed.append(_mod)

import wake_then_converse as W  # noqa: E402

for _mod in _stubbed:
    del sys.modules[_mod]

__all__ = ["W"]
