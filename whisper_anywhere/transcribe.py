import re
import sys

DEFAULT_ENGINE = sensevoice
FASTER_WHISPER_DEFAULT = "distil-medium.en"
SENSEVOICE_DEFAULT = "iic/SenseVoiceSmall"
DEFAULT_MODEL = SENSEVOICE_DEFAULT

_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>\s*")


class FasterWhisperTranscriber:
    def __init__(self, model_id):
        from faster_whisper import WhisperModel

        print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
        self._model = WhisperModel(model_id, device="cpu", compute_type="int8")

    def transcribe(self, audio_path, language=None):
        segments, _ = self._model.transcribe(audio_path, beam_size=5, language=language)
        return " ".join(segment.text.strip() for segment in segments)


class SenseVoiceTranscriber:
    def __init__(self, model_id):
        from funasr import AutoModel

        print(f"Loading SenseVoice model '{model_id}'...", file=sys.stderr)
        self._model = AutoModel(model=model_id, device="cpu")

    def transcribe(self, audio_path, language=None):
        kwargs = {"input": audio_path}
        if language is not None:
            kwargs["language"] = language
        result = self._model.generate(**kwargs)
        if isinstance(result, list) and len(result) > 0:
            text = result[0].get("text", "")
        else:
            text = str(result) if result else ""
        return _SENSEVOICE_TAG_RE.sub("", text).strip()


def load_model(model_id=None, engine="faster-whisper"):
    if engine == "faster-whisper":
        if model_id is None:
            model_id = FASTER_WHISPER_DEFAULT
        return FasterWhisperTranscriber(model_id)
    elif engine == "sensevoice":
        if model_id is None:
            model_id = SENSEVOICE_DEFAULT
        return SenseVoiceTranscriber(model_id)
    raise ValueError(f"Unknown engine: {engine!r}")
