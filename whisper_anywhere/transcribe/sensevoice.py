import re
import sys

_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>\s*")

SENSEVOICE_SUPPORTED_LANGUAGES: frozenset = frozenset(
    {"auto", "zh", "en", "yue", "ja", "ko", "nospeech"}
)


class SenseVoiceTranscriber:
    ENGINE_ID = "sensevoice"
    DEFAULT_MODEL_ID = "iic/SenseVoiceSmall"

    def __init__(
        self, model_id: str = DEFAULT_MODEL_ID, language: str | None = None
    ) -> None:
        from funasr import AutoModel

        self._language = language

        print(f"Loading SenseVoice model '{model_id}'...", file=sys.stderr)
        self._model = AutoModel(model=model_id, device="cpu")

    def transcribe(self, audio_path: str, language: str | None = None) -> str:
        kwargs = {"input": audio_path, "use_itn": True}
        if language is not None:
            kwargs["language"] = language
        else:
            kwargs["language"] = self._language
        result = self._model.generate(**kwargs)
        if isinstance(result, list) and len(result) > 0:
            text = result[0].get("text", "")
        else:
            text = str(result) if result else ""
        return _SENSEVOICE_TAG_RE.sub("", text).strip()
