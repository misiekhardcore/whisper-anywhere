from typing import Protocol, runtime_checkable


@runtime_checkable
class VAD(Protocol):
    def detect(self, audio_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]: ...

    def reset(self) -> None: ...
