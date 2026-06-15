import sys

from .faster_whisper import FasterWhisperTranscriber
from .protocol import Transcriber
from .sensevoice import SENSEVOICE_SUPPORTED_LANGUAGES, SenseVoiceTranscriber
from .vosk import VoskTranscriber

_MULTILINGUAL_MODEL = "distil-large-v3"

DEFAULT_ENGINE_ID = SenseVoiceTranscriber.ENGINE_ID
_ENGINES: dict[str, type[Transcriber]] = {}
_ENGINE_DEFAULTS: dict[str, str] = {}


def register_engine(cls: type[Transcriber], default_model: str | None = None) -> None:
    _ENGINES[cls.ENGINE_ID] = cls
    resolved = (
        default_model
        if default_model is not None
        else getattr(cls, "DEFAULT_MODEL_ID", None)
    )
    if resolved is not None:
        _ENGINE_DEFAULTS[cls.ENGINE_ID] = resolved


def registered_engines() -> list[str]:
    return list(_ENGINES)


register_engine(FasterWhisperTranscriber)
register_engine(SenseVoiceTranscriber)
register_engine(VoskTranscriber)


def load_engine(
    engine_id: str | None = DEFAULT_ENGINE_ID,
    model_id: str | None = None,
    language: str | None = None,
) -> Transcriber:
    if engine_id not in _ENGINES:
        raise ValueError(
            f"Unknown engine: {engine_id!r}. Registered engines: {registered_engines()}"
        )
    cls = _ENGINES[engine_id]
    explicit_model = model_id is not None
    if model_id is None:
        model_id = _ENGINE_DEFAULTS.get(engine_id)

    if (
        engine_id == FasterWhisperTranscriber.ENGINE_ID
        and language is not None
        and language != "en"
        and not explicit_model
        and model_id == _ENGINE_DEFAULTS.get(engine_id)
    ):
        model_id = _MULTILINGUAL_MODEL
        print(
            f"Switching to multilingual model '{_MULTILINGUAL_MODEL}' "
            f"for language '{language}'",
            file=sys.stderr,
        )

    if (
        engine_id == SenseVoiceTranscriber.ENGINE_ID
        and language is not None
        and language not in SENSEVOICE_SUPPORTED_LANGUAGES
    ):
        print(
            f"Warning: SenseVoice does not officially support language '{language}'. "
            f"Supported codes: {', '.join(sorted(SENSEVOICE_SUPPORTED_LANGUAGES))}. "
            f"The language parameter will be ignored and auto-detection used instead.",
            file=sys.stderr,
        )

    return cls(model_id, language)
