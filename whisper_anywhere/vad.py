import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class VAD(Protocol):
    def detect(self, audio_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]: ...

    def reset(self) -> None: ...


class FsmnVAD:
    ENGINE_ID = "fsmn-vad"

    def __init__(self):
        from funasr import AutoModel

        print(f"Loading VAD model '{self.ENGINE_ID}'...", file=sys.stderr)
        self._model = AutoModel(model=self.ENGINE_ID, device="cpu")

    def detect(self, audio_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]:
        import numpy as np

        audio_float = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )
        result = self._model.generate(input=audio_float)
        return _parse_vad_result(result)

    def reset(self) -> None:
        pass  # FSMN-VAD is stateless between recordings


def _parse_vad_result(result: object) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []

    match result:
        case {"value": value}:
            return _parse_vad_result(value)
        case dict():
            return []
        case list():
            pass
        case _:
            return []

    for item in result:
        match item:
            case {"value": value}:
                segments.extend(_parse_vad_result(value))
            case {"start": s, "end": e} | {"beg": s, "end": e} | {"begin": s, "end": e}:
                segments.append((_to_samples(s), _to_samples(e)))
            case [s, e, *_]:
                segments.append((_to_samples(s), _to_samples(e)))

    return _merge_overlapping(segments)


def _to_samples(value) -> int:
    return int(value)


def _merge_overlapping(
    segments: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda x: x[0])
    merged = [sorted_segs[0]]
    for start, end in sorted_segs[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


DEFAULT_VAD_ENGINE = FsmnVAD.ENGINE_ID
_VAD_ENGINES: dict[str, type[VAD]] = {}


def register_vad_engine(cls: type[VAD]) -> None:
    _VAD_ENGINES[cls.ENGINE_ID] = cls


def registered_vad_engines() -> list[str]:
    return list(_VAD_ENGINES)


register_vad_engine(FsmnVAD)


def load_vad(engine_id: str | None = DEFAULT_VAD_ENGINE) -> VAD:
    if engine_id not in _VAD_ENGINES:
        raise ValueError(
            f"Unknown VAD engine: {engine_id!r}. "
            f"Registered engines: {registered_vad_engines()}"
        )
    cls = _VAD_ENGINES[engine_id]
    return cls()
