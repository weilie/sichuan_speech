import sys
import os

# Add src to sys.path so we can import the modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import unittest
from unittest.mock import patch, MagicMock

# dashscope is only installed on the Pi. Stub it for the import if missing,
# then take the stub back out so it cannot make another test file's import
# look healthy. The tests patch through the module's own reference below.
_stubbed = "dashscope" not in sys.modules
if _stubbed:
    try:
        __import__("dashscope")
        _stubbed = False
    except ImportError:
        sys.modules["dashscope"] = MagicMock()

# Import from the new location
import transcribe as transcribe_mod
import synthesize as synthesize_mod
from transcribe import transcribe
from synthesize import synthesize

if _stubbed:
    del sys.modules["dashscope"]

class TestSichuanSpeech(unittest.TestCase):

    @patch.object(transcribe_mod.dashscope.MultiModalConversation, 'call')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    @patch('os.getenv')
    def test_transcribe_success(self, mock_getenv, mock_getsize, mock_exists, mock_call):
        mock_getenv.return_value = "fake_key"
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output.choices = [
            MagicMock(message=MagicMock(content=[{"text": "你好"}]))
        ]
        mock_call.return_value = mock_response

        from io import StringIO
        captured_output = StringIO()
        sys.stdout = captured_output
        
        with patch('builtins.open', unittest.mock.mock_open(read_data=b"dummy")):
            transcribe("test.wav")
            
        sys.stdout = sys.__stdout__
        self.assertEqual(captured_output.getvalue().strip(), "你好")

    @patch.object(synthesize_mod.dashscope.MultiModalConversation, 'call')
    @patch('urllib.request.urlretrieve')
    @patch('os.getenv')
    def test_synthesize_success(self, mock_getenv, mock_retrieve, mock_call):
        mock_getenv.return_value = "fake_key"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output = {
            "audio": {"url": "http://fake.url/audio.wav"}
        }
        mock_call.return_value = mock_response

        synthesize("你好", "output.wav", "female")
        
        args, kwargs = mock_call.call_args
        self.assertEqual(kwargs['voice'], "Sunny")
        self.assertEqual(kwargs['text'], "你好")
        mock_retrieve.assert_called_once_with("http://fake.url/audio.wav", "output.wav")

if __name__ == '__main__':
    unittest.main()
