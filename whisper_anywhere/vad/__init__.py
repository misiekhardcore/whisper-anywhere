from .fsmn import FsmnVAD
from .protocol import VAD

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
