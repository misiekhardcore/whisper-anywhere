import re
import sys
from typing import Optional, Protocol, runtime_checkable

_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>\s*")


@runtime_checkable
class Transcriber(Protocol):
    """Interface every transcription engine must implement."""

    ENGINE_ID: str
    DEFAULT_MODEL: str

    def __init__(self, model_id: str) -> None: ...

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str: ...


class FasterWhisperTranscriber:
    ENGINE_ID = "faster-whisper"
    DEFAULT_MODEL = "distil-medium.en"

    def __init__(self, model_id: str = DEFAULT_MODEL):
        from faster_whisper import WhisperModel

        print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
        self._model = WhisperModel(model_id, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        segments, _ = self._model.transcribe(audio_path, beam_size=5, language=language)
        return " ".join(segment.text.strip() for segment in segments)


class SenseVoiceTranscriber:
    ENGINE_ID = "sensevoice"
    DEFAULT_MODEL = "iic/SenseVoiceSmall"

    def __init__(self, model_id: str = DEFAULT_MODEL):
        from funasr import AutoModel

        print(f"Loading SenseVoice model '{model_id}'...", file=sys.stderr)
        self._model = AutoModel(model=model_id, device="cpu")

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        kwargs = {"input": audio_path, "use_itn": True}
        if language is not None:
            kwargs["language"] = language
        result = self._model.generate(**kwargs)
        if isinstance(result, list) and len(result) > 0:
            text = result[0].get("text", "")
        else:
            text = str(result) if result else ""
        return _SENSEVOICE_TAG_RE.sub("", text).strip()


DEFAULT_ENGINE = SenseVoiceTranscriber.ENGINE_ID
_ENGINES: dict[str, type[Transcriber]] = {}
_ENGINE_DEFAULTS: dict[str, str] = {}


def register_engine(
    cls: type[Transcriber], default_model: Optional[str] = None
) -> None:
    _ENGINES[cls.ENGINE_ID] = cls
    resolved = (
        default_model
        if default_model is not None
        else getattr(cls, "DEFAULT_MODEL", None)
    )
    if resolved is not None:
        _ENGINE_DEFAULTS[cls.ENGINE_ID] = resolved


def registered_engines() -> list[str]:
    return list(_ENGINES)


register_engine(
    FasterWhisperTranscriber,
)
register_engine(
    SenseVoiceTranscriber,
)


def load_model(
    engine_id: Optional[str] = DEFAULT_ENGINE, model_id: Optional[str] = None
) -> Transcriber:
    if engine_id not in _ENGINES:
        raise ValueError(
            f"Unknown engine: {engine_id!r}. Registered engines: {registered_engines()}"
        )
    cls = _ENGINES[engine_id]
    if model_id is None:
        model_id = _ENGINE_DEFAULTS.get(engine_id)
    return cls(model_id)
