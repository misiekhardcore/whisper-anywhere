import sys
from unittest.mock import MagicMock, patch

import pytest

# Optional deps may not be installed; provide mock modules so patch targets resolve.
for mod in ("faster_whisper", "funasr"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from whisper_anywhere.transcribe import (
    FASTER_WHISPER_DEFAULT,
    SENSEVOICE_DEFAULT,
    FasterWhisperTranscriber,
    SenseVoiceTranscriber,
    load_model,
)


class TestFasterWhisperTranscriber:
    @patch("faster_whisper.WhisperModel")
    def test_init(self, mock_whisper):
        t = FasterWhisperTranscriber("tiny.en")
        mock_whisper.assert_called_once_with("tiny.en", device="cpu", compute_type="int8")

    @patch("faster_whisper.WhisperModel")
    def test_transcribe_returns_text(self, mock_whisper):
        seg = MagicMock()
        seg.text = "hello world"
        mock_whisper.return_value.transcribe.return_value = ([seg], None)

        t = FasterWhisperTranscriber("tiny.en")
        result = t.transcribe("/tmp/t.wav")
        assert result == "hello world"
        mock_whisper.return_value.transcribe.assert_called_once_with("/tmp/t.wav", beam_size=5, language=None)

    @patch("faster_whisper.WhisperModel")
    def test_transcribe_with_language(self, mock_whisper):
        seg = MagicMock()
        seg.text = "cześć"
        mock_whisper.return_value.transcribe.return_value = ([seg], None)

        t = FasterWhisperTranscriber("tiny.en")
        result = t.transcribe("/tmp/t.wav", language="pl")
        assert result == "cześć"
        mock_whisper.return_value.transcribe.assert_called_once_with("/tmp/t.wav", beam_size=5, language="pl")

    @patch("faster_whisper.WhisperModel")
    def test_transcribe_concatenates_multiple_segments(self, mock_whisper):
        segs = [MagicMock(text="hello"), MagicMock(text="world")]
        mock_whisper.return_value.transcribe.return_value = (segs, None)

        t = FasterWhisperTranscriber("tiny.en")
        result = t.transcribe("/tmp/t.wav")
        assert result == "hello world"


class TestSenseVoiceTranscriber:
    @patch("funasr.AutoModel")
    def test_init(self, mock_auto):
        t = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        mock_auto.assert_called_once_with(model="iic/SenseVoiceSmall", device="cpu")

    @patch("funasr.AutoModel")
    def test_transcribe_returns_text(self, mock_auto):
        mock_auto.return_value.generate.return_value = [{"text": "hello world"}]

        t = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result = t.transcribe("/tmp/t.wav")
        assert result == "hello world"
        mock_auto.return_value.generate.assert_called_once_with(input="/tmp/t.wav")

    @patch("funasr.AutoModel")
    def test_transcribe_with_language(self, mock_auto):
        mock_auto.return_value.generate.return_value = [{"text": "witaj świecie"}]

        t = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result = t.transcribe("/tmp/t.wav", language="pl")
        assert result == "witaj świecie"
        mock_auto.return_value.generate.assert_called_once_with(input="/tmp/t.wav", language="pl")

    @patch("funasr.AutoModel")
    def test_transcribe_empty_result(self, mock_auto):
        mock_auto.return_value.generate.return_value = []

        t = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result = t.transcribe("/tmp/t.wav")
        assert result == ""

    @patch("funasr.AutoModel")
    def test_transcribe_missing_text_key(self, mock_auto):
        mock_auto.return_value.generate.return_value = [{"key": "test"}]

        t = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result = t.transcribe("/tmp/t.wav")
        assert result == ""


class TestLoadModel:
    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_default_model(self, mock_whisper):
        t = load_model(None, "faster-whisper")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with(
            FASTER_WHISPER_DEFAULT, device="cpu", compute_type="int8"
        )

    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_custom_model(self, mock_whisper):
        t = load_model("tiny.en", "faster-whisper")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with("tiny.en", device="cpu", compute_type="int8")

    @patch("funasr.AutoModel")
    def test_sensevoice_default_model(self, mock_auto):
        t = load_model(None, "sensevoice")
        assert isinstance(t, SenseVoiceTranscriber)
        mock_auto.assert_called_once_with(model=SENSEVOICE_DEFAULT, device="cpu")

    @patch("funasr.AutoModel")
    def test_sensevoice_custom_model(self, mock_auto):
        t = load_model("iic/SenseVoiceSmall", "sensevoice")
        assert isinstance(t, SenseVoiceTranscriber)
        mock_auto.assert_called_once_with(model="iic/SenseVoiceSmall", device="cpu")

    def test_invalid_engine_raises(self):
        with pytest.raises(ValueError, match="Unknown engine"):
            load_model(None, "invalid")


class TestConstants:
    def test_faster_whisper_default(self):
        assert FASTER_WHISPER_DEFAULT == "distil-medium.en"

    def test_sensevoice_default(self):
        assert SENSEVOICE_DEFAULT == "iic/SenseVoiceSmall"
