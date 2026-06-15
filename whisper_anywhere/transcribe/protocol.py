from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    ENGINE_ID: str
    DEFAULT_MODEL_ID: str

    def __init__(self, model_id: str, language: str | None = None) -> None: ...

    def transcribe(self, audio_path: str, language: str | None = None) -> str: ...
