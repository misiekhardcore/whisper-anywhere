import json
import os
import urllib.request
import wave
import zipfile
from pathlib import Path

_VOSK_MODEL_CACHE = os.path.join(os.path.expanduser("~/.cache"), "vosk")
_VOSK_BASE_URL = "https://alphacephei.com/vosk/models"


def _resolve_vosk_model(model_id: str) -> str:
    p = Path(model_id)
    if p.is_dir():
        return str(p.resolve())
    cache_path = Path(_VOSK_MODEL_CACHE) / model_id
    if cache_path.is_dir():
        return str(cache_path)
    print(
        f"Downloading Vosk model '{model_id}' to {cache_path}...",
        file=__import__("sys").stderr,
    )
    os.makedirs(_VOSK_MODEL_CACHE, exist_ok=True)
    url = f"{_VOSK_BASE_URL}/{model_id}.zip"
    zip_path = cache_path.with_suffix(".zip")
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(_VOSK_MODEL_CACHE)
    zip_path.unlink()
    return str(cache_path)


class VoskTranscriber:
    ENGINE_ID = "vosk"
    DEFAULT_MODEL_ID = "vosk-model-en-us-0.22-lgraph"
    DEFAULT_PUNCT_MODEL_PATH = "vosk-recasepunc-en-0.22"

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        language: str | None = None,
    ):
        from vosk import Model

        self._language = language

        model_path = _resolve_vosk_model(model_id)
        print(f"Loading Vosk model '{model_path}'...", file=__import__("sys").stderr)
        self._model = Model(model_path)

    def transcribe(self, audio_path: str, language: str | None = None) -> str:
        from vosk import KaldiRecognizer

        wf = wave.open(audio_path, "rb")
        rec = KaldiRecognizer(self._model, wf.getframerate())
        rec.SetWords(True)
        rec.SetPartialWords(True)
        results: list[str] = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result()).get("text", "")
                if res:
                    results.append(res)
        final = json.loads(rec.FinalResult()).get("text", "")
        if final:
            results.append(final)
        wf.close()

        return " ".join(results)
