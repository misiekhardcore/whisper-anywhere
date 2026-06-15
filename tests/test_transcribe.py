import sys
from unittest.mock import MagicMock, patch

import pytest

from whisper_anywhere import Transcriber
from whisper_anywhere.transcribe import (
    _ENGINE_DEFAULTS,
    _ENGINES,
    SENSEVOICE_SUPPORTED_LANGUAGES,
    FasterWhisperTranscriber,
    SenseVoiceTranscriber,
    VoskTranscriber,
    load_engine,
    register_engine,
    registered_engines,
)

# Optional deps may not be installed; provide mock modules so patch targets resolve.
for mod in ("faster_whisper", "funasr", "vosk"):
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()


class TestFasterWhisperTranscriber:
    @patch("faster_whisper.WhisperModel")
    def test_init(self, mock_whisper: MagicMock) -> None:
        FasterWhisperTranscriber("tiny.en")
        mock_whisper.assert_called_once_with(
            "tiny.en", device="cpu", compute_type="int8"
        )

    @patch("faster_whisper.WhisperModel")
    def test_transcribe_returns_text(self, mock_whisper: MagicMock) -> None:
        seg: MagicMock = MagicMock()
        seg.text = "hello world"
        mock_whisper.return_value.transcribe.return_value = ([seg], None)

        t: FasterWhisperTranscriber = FasterWhisperTranscriber("tiny.en")
        result: str = t.transcribe("/tmp/t.wav")
        assert result == "hello world"
        mock_whisper.return_value.transcribe.assert_called_once_with(
            "/tmp/t.wav", beam_size=5, language=None
        )

    @patch("faster_whisper.WhisperModel")
    def test_transcribe_with_language(self, mock_whisper: MagicMock) -> None:
        seg: MagicMock = MagicMock()
        seg.text = "cześć"
        mock_whisper.return_value.transcribe.return_value = ([seg], None)

        t: FasterWhisperTranscriber = FasterWhisperTranscriber("tiny.en")
        result: str = t.transcribe("/tmp/t.wav", language="pl")
        assert result == "cześć"
        mock_whisper.return_value.transcribe.assert_called_once_with(
            "/tmp/t.wav", beam_size=5, language="pl"
        )

    @patch("faster_whisper.WhisperModel")
    def test_transcribe_concatenates_multiple_segments(
        self, mock_whisper: MagicMock
    ) -> None:
        segs: list[MagicMock] = [MagicMock(text="hello"), MagicMock(text="world")]
        mock_whisper.return_value.transcribe.return_value = (segs, None)

        t: FasterWhisperTranscriber = FasterWhisperTranscriber("tiny.en")
        result: str = t.transcribe("/tmp/t.wav")
        assert result == "hello world"


class TestSenseVoiceTranscriber:
    @patch("funasr.AutoModel")
    def test_init(self, mock_auto: MagicMock) -> None:
        SenseVoiceTranscriber("iic/SenseVoiceSmall")
        mock_auto.assert_called_once_with(model="iic/SenseVoiceSmall", device="cpu")

    @patch("funasr.AutoModel")
    def test_transcribe_returns_text(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = [{"text": "hello world"}]

        t: SenseVoiceTranscriber = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result: str = t.transcribe("/tmp/t.wav")
        assert result == "hello world"
        mock_auto.return_value.generate.assert_called_once_with(
            input="/tmp/t.wav", use_itn=True, language=None
        )

    @patch("funasr.AutoModel")
    def test_transcribe_with_language(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = [{"text": "witaj świecie"}]

        t: SenseVoiceTranscriber = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result: str = t.transcribe("/tmp/t.wav", language="pl")
        assert result == "witaj świecie"
        mock_auto.return_value.generate.assert_called_once_with(
            input="/tmp/t.wav", use_itn=True, language="pl"
        )

    @patch("funasr.AutoModel")
    def test_transcribe_empty_result(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = []

        t: SenseVoiceTranscriber = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result: str = t.transcribe("/tmp/t.wav")
        assert result == ""

    @patch("funasr.AutoModel")
    def test_transcribe_missing_text_key(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = [{"key": "test"}]

        t: SenseVoiceTranscriber = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result: str = t.transcribe("/tmp/t.wav")
        assert result == ""

    @patch("funasr.AutoModel")
    def test_strips_sensevoice_tags(self, mock_auto: MagicMock) -> None:
        mock_auto.return_value.generate.return_value = [
            {"text": "<|en|><|EMO_UNKNOWN|><|Speech|>this is a test recording"}
        ]

        t: SenseVoiceTranscriber = SenseVoiceTranscriber("iic/SenseVoiceSmall")
        result: str = t.transcribe("/tmp/t.wav")
        assert result == "this is a test recording"


class TestVoskTranscriber:
    @patch(
        "whisper_anywhere.transcribe.vosk._resolve_vosk_model",
        return_value="/fake/vosk/model",
    )
    @patch("vosk.Model")
    def test_init(self, mock_model: MagicMock, mock_resolve: MagicMock) -> None:
        VoskTranscriber("custom-model", None)
        mock_resolve.assert_called_once_with("custom-model")
        mock_model.assert_called_once_with("/fake/vosk/model")

    @patch(
        "whisper_anywhere.transcribe.vosk._resolve_vosk_model",
        return_value="/fake/vosk/model",
    )
    @patch("vosk.Model")
    @patch("wave.open")
    @patch("vosk.KaldiRecognizer")
    def test_transcribe_returns_text(
        self,
        mock_kaldi: MagicMock,
        mock_wave_open: MagicMock,
        mock_model: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        mock_wf: MagicMock = MagicMock()
        mock_wf.getframerate.return_value = 16000
        mock_wf.readframes.side_effect = [b"audio data", b""]
        mock_wave_open.return_value = mock_wf

        mock_rec: MagicMock = MagicMock()
        mock_rec.AcceptWaveform.return_value = False
        mock_rec.FinalResult.return_value = '{"text": "Hello world."}'
        mock_kaldi.return_value = mock_rec

        t: VoskTranscriber = VoskTranscriber("custom-model", None)
        result: str = t.transcribe("/tmp/t.wav")
        assert result == "Hello world."
        mock_kaldi.assert_called_once_with(mock_model.return_value, 16000)
        mock_rec.AcceptWaveform.assert_called_once_with(b"audio data")

    @patch(
        "whisper_anywhere.transcribe.vosk._resolve_vosk_model",
        return_value="/fake/vosk/model",
    )
    @patch("vosk.Model")
    @patch("wave.open")
    @patch("vosk.KaldiRecognizer")
    def test_transcribe_empty_result(
        self,
        mock_kaldi: MagicMock,
        mock_wave_open: MagicMock,
        mock_model: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        mock_wf: MagicMock = MagicMock()
        mock_wf.getframerate.return_value = 16000
        mock_wf.readframes.return_value = b""
        mock_wave_open.return_value = mock_wf

        mock_rec: MagicMock = MagicMock()
        mock_rec.FinalResult.return_value = '{"text": ""}'
        mock_kaldi.return_value = mock_rec

        t: VoskTranscriber = VoskTranscriber("custom-model", None)
        result: str = t.transcribe("/tmp/t.wav")
        assert result == ""

    @patch(
        "whisper_anywhere.transcribe.vosk._resolve_vosk_model",
        return_value="/fake/vosk/model",
    )
    @patch("vosk.Model")
    @patch("wave.open")
    @patch("vosk.KaldiRecognizer")
    def test_transcribe_missing_text_key(
        self,
        mock_kaldi: MagicMock,
        mock_wave_open: MagicMock,
        mock_model: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        mock_wf: MagicMock = MagicMock()
        mock_wf.getframerate.return_value = 16000
        mock_wf.readframes.side_effect = [b"audio data", b""]
        mock_wave_open.return_value = mock_wf

        mock_rec: MagicMock = MagicMock()
        mock_rec.AcceptWaveform.return_value = False
        mock_rec.FinalResult.return_value = '{"partial": "hello"}'
        mock_kaldi.return_value = mock_rec

        t: VoskTranscriber = VoskTranscriber("custom-model", None)
        result: str = t.transcribe("/tmp/t.wav")
        assert result == ""

    @patch(
        "whisper_anywhere.transcribe.vosk._resolve_vosk_model",
        return_value="/fake/vosk/model",
    )
    @patch("vosk.Model")
    @patch("wave.open")
    @patch("vosk.KaldiRecognizer")
    def test_transcribe_accumulates_multiple_utterances(
        self,
        mock_kaldi: MagicMock,
        mock_wave_open: MagicMock,
        mock_model: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        mock_wf: MagicMock = MagicMock()
        mock_wf.getframerate.return_value = 16000
        mock_wf.readframes.side_effect = [b"first", b"second", b""]
        mock_wave_open.return_value = mock_wf

        mock_rec: MagicMock = MagicMock()
        mock_rec.AcceptWaveform.side_effect = [True, True]
        mock_rec.Result.side_effect = [
            '{"text": "Could"}',
            '{"text": "you help me with this?"}',
        ]
        mock_rec.FinalResult.return_value = '{"text": ""}'
        mock_kaldi.return_value = mock_rec

        t: VoskTranscriber = VoskTranscriber("custom-model", None)
        result: str = t.transcribe("/tmp/t.wav")
        assert result == "Could you help me with this?"


class TestLoadModel:
    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_default_model(self, mock_whisper: MagicMock) -> None:
        t: Transcriber = load_engine("faster-whisper")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with(
            FasterWhisperTranscriber.DEFAULT_MODEL_ID,
            device="cpu",
            compute_type="int8",
        )

    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_custom_model(self, mock_whisper: MagicMock) -> None:
        t: Transcriber = load_engine("faster-whisper", "tiny.en")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with(
            "tiny.en", device="cpu", compute_type="int8"
        )

    @patch("funasr.AutoModel")
    def test_sensevoice_default_model(self, mock_auto: MagicMock) -> None:
        t: Transcriber = load_engine("sensevoice")
        assert isinstance(t, SenseVoiceTranscriber)
        mock_auto.assert_called_once_with(
            model=SenseVoiceTranscriber.DEFAULT_MODEL_ID, device="cpu"
        )

    @patch("funasr.AutoModel")
    def test_sensevoice_custom_model(self, mock_auto: MagicMock) -> None:
        t: Transcriber = load_engine("sensevoice", "iic/SenseVoiceSmall")
        assert isinstance(t, SenseVoiceTranscriber)
        mock_auto.assert_called_once_with(model="iic/SenseVoiceSmall", device="cpu")

    def test_default_engine_is_sensevoice(self) -> None:
        t: Transcriber = load_engine()
        assert isinstance(t, SenseVoiceTranscriber)

    def test_invalid_engine_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown engine.*sensevoice"):
            load_engine("invalid")


class TestEngineRegistry:
    def test_registered_engines_includes_builtins(self) -> None:
        engines: list[str] = registered_engines()
        assert "faster-whisper" in engines
        assert "sensevoice" in engines
        assert "vosk" in engines

    def test_register_and_dispatch(self) -> None:
        class _DummyEngine:
            ENGINE_ID: str = "dummy"

            def __init__(self, model_id: str, language: str | None = None) -> None:
                self.model_id = model_id

            def transcribe(self, audio_path: str, language: str | None = None) -> str:
                return f"dummy:{self.model_id}:{audio_path}"

        saved: tuple[dict[str, Transcriber], dict[str, str]] = (
            _ENGINES.copy(),
            _ENGINE_DEFAULTS.copy(),
        )
        try:
            register_engine(_DummyEngine, default_model="dummy-default")
            assert "dummy" in registered_engines()

            t: Transcriber = load_engine("dummy")
            assert isinstance(t, _DummyEngine)
            assert t.model_id == "dummy-default"
            assert t.transcribe("/tmp/t.wav") == "dummy:dummy-default:/tmp/t.wav"

            t2: Transcriber = load_engine("dummy", "custom-model")
            assert t2.model_id == "custom-model"
        finally:
            _ENGINES.clear()
            _ENGINES.update(saved[0])
            _ENGINE_DEFAULTS.clear()
            _ENGINE_DEFAULTS.update(saved[1])

    def test_register_without_default(self) -> None:
        saved: tuple[dict[str, Transcriber], dict[str, str]] = (
            _ENGINES.copy(),
            _ENGINE_DEFAULTS.copy(),
        )
        try:
            register_engine(
                type(
                    "_",
                    (),
                    {
                        "ENGINE_ID": "no-default",
                        "__init__": lambda self, m, language=None: setattr(
                            self, "model_id", m
                        ),
                        "transcribe": lambda self, p, language=None: "",
                    },
                ),
            )
            t: Transcriber = load_engine("no-default", "explicit-model")
            assert t.model_id == "explicit-model"
        finally:
            _ENGINES.clear()
            _ENGINES.update(saved[0])
            _ENGINE_DEFAULTS.clear()
            _ENGINE_DEFAULTS.update(saved[1])


class TestTranscriberProtocol:
    def test_faster_whisper_conforms(self) -> None:
        assert isinstance(FasterWhisperTranscriber("tiny.en"), Transcriber)

    def test_sensevoice_conforms(self) -> None:
        assert isinstance(SenseVoiceTranscriber("iic/SenseVoiceSmall"), Transcriber)

    def test_vosk_conforms(self) -> None:
        assert isinstance(VoskTranscriber("vosk-model-small-en-us-0.15"), Transcriber)

    def test_user_class_conforms(self) -> None:
        class GoodEngine:
            ENGINE_ID: str = "good"
            DEFAULT_MODEL_ID: str = "good-default"

            def __init__(self, model_id: str) -> None: ...
            def transcribe(
                self, audio_path: str, language: str | None = None
            ) -> str: ...

        assert isinstance(GoodEngine("x"), Transcriber)

    def test_missing_method_does_not_conform(self) -> None:
        class BadEngine:
            def __init__(self, model_id: str) -> None: ...

        assert not isinstance(BadEngine("x"), Transcriber)

    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_smart_multilingual(self, mock_whisper: MagicMock) -> None:
        t: Transcriber = load_engine("faster-whisper", language="pl")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with(
            FasterWhisperTranscriber.MULTILINGUAL_MODEL,
            device="cpu",
            compute_type="int8",
        )

    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_english_keeps_default(
        self, mock_whisper: MagicMock
    ) -> None:
        t: Transcriber = load_engine("faster-whisper", language="en")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with(
            FasterWhisperTranscriber.DEFAULT_MODEL_ID,
            device="cpu",
            compute_type="int8",
        )

    @patch("faster_whisper.WhisperModel")
    def test_faster_whisper_explicit_model_overrides_smart(
        self, mock_whisper: MagicMock
    ) -> None:
        t: Transcriber = load_engine("faster-whisper", "tiny.en", language="pl")
        assert isinstance(t, FasterWhisperTranscriber)
        mock_whisper.assert_called_once_with(
            "tiny.en", device="cpu", compute_type="int8"
        )

    def test_sensevoice_unsupported_language_warns(self) -> None:
        with patch("funasr.AutoModel"), patch("sys.stderr") as mock_stderr:
            load_engine("sensevoice", language="pl")
            written: str = "".join(c[0][0] for c in mock_stderr.write.call_args_list)
            assert "Warning" in written
            assert "SenseVoice" in written
            assert "pl" in written

    def test_sensevoice_supported_language_no_warn(self) -> None:
        with patch("funasr.AutoModel"), patch("sys.stderr") as mock_stderr:
            load_engine("sensevoice", language="en")
            written: str = "".join(c[0][0] for c in mock_stderr.write.call_args_list)
            assert "Warning" not in written


class TestConstants:
    def test_faster_whisper_default(self) -> None:
        assert FasterWhisperTranscriber.DEFAULT_MODEL_ID == "distil-medium.en"

    def test_sensevoice_default(self) -> None:
        assert SenseVoiceTranscriber.DEFAULT_MODEL_ID == "iic/SenseVoiceSmall"

    def test_vosk_default(self) -> None:
        assert VoskTranscriber.DEFAULT_MODEL_ID == "vosk-model-en-us-0.22-lgraph"

    def test_sensevoice_supported_languages(self) -> None:
        assert SENSEVOICE_SUPPORTED_LANGUAGES == {
            "auto",
            "zh",
            "en",
            "yue",
            "ja",
            "ko",
            "nospeech",
        }

    def test_multilingual_model_constant(self) -> None:
        assert FasterWhisperTranscriber.MULTILINGUAL_MODEL == "distil-large-v3"
