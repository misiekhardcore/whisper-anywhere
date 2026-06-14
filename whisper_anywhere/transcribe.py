import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>\s*")

SENSEVOICE_SUPPORTED_LANGUAGES: frozenset = frozenset(
    {"auto", "zh", "en", "yue", "ja", "ko", "nospeech"}
)

_MULTILINGUAL_MODEL = "distil-large-v3"

_VOSK_MODEL_CACHE = os.path.join(os.path.expanduser("~/.cache"), "vosk")
_VOSK_BASE_URL = "https://alphacephei.com/vosk/models"
VOSK_LANG_MODELS: dict[str, str] = {
    "en": "vosk-model-small-en-us-0.15",
    "pl": "vosk-model-small-pl-0.22",
    "de": "vosk-model-small-de-0.15",
    "fr": "vosk-model-small-fr-0.22",
    "es": "vosk-model-small-es-0.22",
    "pt": "vosk-model-small-pt-0.3",
    "ru": "vosk-model-small-ru-0.22",
    "it": "vosk-model-small-it-0.22",
    "nl": "vosk-model-small-nl-0.22",
    "tr": "vosk-model-small-tr-0.3",
    "vn": "vosk-model-small-vn-0.3",
    "ja": "vosk-model-small-ja-0.22",
    "cn": "vosk-model-small-cn-0.22",
    "hi": "vosk-model-small-hi-0.22",
    "ar": "vosk-model-small-ar-0.22",
    "fa": "vosk-model-small-fa-0.5",
}


@runtime_checkable
class Transcriber(Protocol):
    """Interface every transcription engine must implement."""

    ENGINE_ID: str
    DEFAULT_MODEL_ID: str

    def __init__(self, model_id: str) -> None: ...

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str: ...


class FasterWhisperTranscriber:
    ENGINE_ID = "faster-whisper"
    DEFAULT_MODEL_ID = "distil-medium.en"

    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
        from faster_whisper import WhisperModel

        print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
        self._model = WhisperModel(model_id, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        segments, _ = self._model.transcribe(audio_path, beam_size=5, language=language)
        return " ".join(segment.text.strip() for segment in segments)


class SenseVoiceTranscriber:
    ENGINE_ID = "sensevoice"
    DEFAULT_MODEL_ID = "iic/SenseVoiceSmall"

    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
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


class VoskTranscriber:
    ENGINE_ID = "vosk"
    DEFAULT_MODEL_ID = "vosk-model-small-en-us-0.15"

    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
        from vosk import Model

        model_path = _resolve_vosk_model(model_id)
        print(f"Loading Vosk model '{model_path}'...", file=sys.stderr)
        self._model = Model(model_path)

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        import json
        import wave

        from vosk import KaldiRecognizer

        wf = wave.open(audio_path, "rb")
        rec = KaldiRecognizer(self._model, wf.getframerate())
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
        result = json.loads(rec.FinalResult())
        wf.close()
        return result.get("text", "").strip()


def _resolve_vosk_model(model_id: str) -> str:
    """Resolve a Vosk model ID to a local filesystem path, downloading if needed."""
    p = Path(model_id)
    if p.is_dir():
        return str(p.resolve())
    cache_path = Path(_VOSK_MODEL_CACHE) / model_id
    if cache_path.is_dir():
        return str(cache_path)
    print(
        f"Downloading Vosk model '{model_id}' to {cache_path}...",
        file=sys.stderr,
    )
    os.makedirs(_VOSK_MODEL_CACHE, exist_ok=True)
    url = f"{_VOSK_BASE_URL}/{model_id}.zip"
    zip_path = cache_path.with_suffix(".zip")
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(_VOSK_MODEL_CACHE)
    zip_path.unlink()
    return str(cache_path)


DEFAULT_ENGINE_ID = SenseVoiceTranscriber.ENGINE_ID
_ENGINES: dict[str, type[Transcriber]] = {}
_ENGINE_DEFAULTS: dict[str, str] = {}


def register_engine(
    cls: type[Transcriber], default_model: Optional[str] = None
) -> None:
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


register_engine(
    FasterWhisperTranscriber,
)
register_engine(
    SenseVoiceTranscriber,
)
register_engine(
    VoskTranscriber,
)


def load_engine(
    engine_id: Optional[str] = DEFAULT_ENGINE_ID,
    model_id: Optional[str] = None,
    language: Optional[str] = None,
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

    return cls(model_id)
