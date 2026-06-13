import re
import sys
from typing import Optional, Protocol, runtime_checkable

DEFAULT_ENGINE = "faster-whisper"
FASTER_WHISPER_DEFAULT = "distil-medium.en"
SENSEVOICE_DEFAULT = "iic/SenseVoiceSmall"
DEFAULT_MODEL = FASTER_WHISPER_DEFAULT

_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>\s*")


@runtime_checkable
class Transcriber(Protocol):
    """Interface every transcription engine must implement."""

    def __init__(self, model_id: str) -> None: ...

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str: ...


class FasterWhisperTranscriber:
    def __init__(self, model_id: str):
        from faster_whisper import WhisperModel

        print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
        self._model = WhisperModel(model_id, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        segments, _ = self._model.transcribe(audio_path, beam_size=5, language=language)
        return " ".join(segment.text.strip() for segment in segments)


class SenseVoiceTranscriber:
    def __init__(self, model_id: str):
        from funasr import AutoModel

        print(f"Loading SenseVoice model '{model_id}'...", file=sys.stderr)
        self._model = AutoModel(model=model_id, device="cpu")

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        kwargs = {"input": audio_path}
        if language is not None:
            kwargs["language"] = language
        result = self._model.generate(**kwargs)
        if isinstance(result, list) and len(result) > 0:
            text = result[0].get("text", "")
        else:
            text = str(result) if result else ""
        return _SENSEVOICE_TAG_RE.sub("", text).strip()


_ENGINES: dict[str, type[Transcriber]] = {}
_ENGINE_DEFAULTS: dict[str, str] = {}


def register_engine(
    name: str, cls: type[Transcriber], default_model: Optional[str] = None
) -> None:
    _ENGINES[name] = cls
    if default_model is not None:
        _ENGINE_DEFAULTS[name] = default_model


def registered_engines() -> list[str]:
    return list(_ENGINES)


register_engine("faster-whisper", FasterWhisperTranscriber, FASTER_WHISPER_DEFAULT)
register_engine("sensevoice", SenseVoiceTranscriber, SENSEVOICE_DEFAULT)


def load_model(
    model_id: Optional[str] = None, engine: str = "faster-whisper"
) -> Transcriber:
    if engine not in _ENGINES:
        raise ValueError(
            f"Unknown engine: {engine!r}. "
            f"Registered engines: {registered_engines()}"
        )
    cls = _ENGINES[engine]
    if model_id is None:
        model_id = _ENGINE_DEFAULTS.get(engine)
    return cls(model_id)
