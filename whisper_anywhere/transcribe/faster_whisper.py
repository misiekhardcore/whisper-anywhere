import sys


class FasterWhisperTranscriber:
    ENGINE_ID = "faster-whisper"
    DEFAULT_MODEL_ID = "distil-medium.en"

    def __init__(
        self, model_id: str = DEFAULT_MODEL_ID, language: str | None = None
    ) -> None:
        from faster_whisper import WhisperModel

        self._language = language

        print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
        self._model = WhisperModel(model_id, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str, language: str | None = None) -> str:
        segments, _ = self._model.transcribe(
            audio_path, beam_size=5, language=language or self._language
        )
        return " ".join(segment.text.strip() for segment in segments)
