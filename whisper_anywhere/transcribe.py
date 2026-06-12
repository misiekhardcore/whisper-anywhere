import sys
from faster_whisper import WhisperModel

DEFAULT_MODEL = "distil-medium.en"


def load_model(model_id):
    print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
    model = WhisperModel(model_id, device="cpu", compute_type="int8")
    return model
