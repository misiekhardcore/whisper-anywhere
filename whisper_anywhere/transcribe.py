import sys
from faster_whisper import WhisperModel

DEFAULT_MODEL = "distil-large-v3"


def load_model(model_id):
    print(f"Loading faster-whisper model '{model_id}'...", file=sys.stderr)
    model = WhisperModel(model_id, device="cpu", compute_type="int8")
    return model
