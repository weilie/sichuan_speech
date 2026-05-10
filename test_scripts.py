import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Import the functions from our scripts
from transcribe import transcribe
from synthesize import synthesize

class TestSichuanSpeech(unittest.TestCase):

    @patch('dashscope.MultiModalConversation.call')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    @patch('os.getenv')
    def test_transcribe_success(self, mock_getenv, mock_getsize, mock_exists, mock_call):
        # Setup mocks
        mock_getenv.return_value = "fake_key"
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output.choices = [
            MagicMock(message=MagicMock(content=[{"text": "你好"}]))
        ]
        mock_call.return_value = mock_response

        # We use a context manager to capture stdout since transcribe prints the result
        from io import StringIO
        captured_output = StringIO()
        sys.stdout = captured_output
        
        # Test with a dummy file name
        with patch('builtins.open', unittest.mock.mock_open(read_data=b"dummy")):
            transcribe("test.wav")
            
        sys.stdout = sys.__stdout__
        self.assertEqual(captured_output.getvalue().strip(), "你好")

    @patch('dashscope.MultiModalConversation.call')
    @patch('urllib.request.urlretrieve')
    @patch('os.getenv')
    def test_synthesize_success(self, mock_getenv, mock_retrieve, mock_call):
        # Setup mocks
        mock_getenv.return_value = "fake_key"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output = {
            "audio": {"url": "http://fake.url/audio.wav"}
        }
        mock_call.return_value = mock_response

        # Test synthesis
        synthesize("你好", "output.wav", "female")
        
        # Verify dashscope was called with correct voice
        args, kwargs = mock_call.call_args
        self.assertEqual(kwargs['voice'], "Sunny")
        self.assertEqual(kwargs['text'], "你好")
        
        # Verify download was attempted
        mock_retrieve.assert_called_once_with("http://fake.url/audio.wav", "output.wav")

if __name__ == '__main__':
    unittest.main()
