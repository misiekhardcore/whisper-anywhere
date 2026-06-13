import sys
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class VAD(Protocol):
    def detect(self, audio_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]:
        ...

    def reset(self) -> None:
        ...


class FsmnVAD:
    MODEL_ID = "iic/speech_fsmn_vad_zh-cn_16k-common-pytorch"

    def __init__(self):
        from funasr import AutoModel

        print(f"Loading VAD model '{self.MODEL_ID}'...", file=sys.stderr)
        self._model = AutoModel(model=self.MODEL_ID, device="cpu")

    def detect(self, audio_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]:
        import numpy as np

        audio_float = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )
        result = self._model.generate(input=audio_float)
        return _parse_vad_result(result)

    def reset(self) -> None:
        pass


def _parse_vad_result(result) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []

    if isinstance(result, dict):
        if "value" in result:
            return _parse_vad_result(result["value"])
        return segments

    if not isinstance(result, list):
        return segments

    for item in result:
        if isinstance(item, dict):
            start = item.get("start") or item.get("beg") or item.get("begin")
            end = item.get("end")
            if start is not None and end is not None:
                segments.append((_to_samples(start), _to_samples(end)))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            start, end = item[0], item[1]
            segments.append((_to_samples(start), _to_samples(end)))

    return _merge_overlapping(segments)


def _to_samples(value) -> int:
    value = int(value)
    return value


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


def load_vad(engine: str = "fsmn-vad") -> VAD:
    if engine == "fsmn-vad":
        return FsmnVAD()
    raise ValueError(f"Unknown VAD engine: {engine!r}")
