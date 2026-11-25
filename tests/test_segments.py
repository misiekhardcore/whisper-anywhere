import math
import struct

from whisper_anywhere.audio import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from whisper_anywhere.segments import split_pcm

SECONDS_PER_CHUNK = 30
BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS


def _tone(seconds: float, amplitude: int = 8000) -> bytes:
    samples = int(SAMPLE_RATE * seconds)
    return struct.pack(
        f"<{samples}h", *(amplitude if i % 2 else -amplitude for i in range(samples))
    )


def _silence(seconds: float) -> bytes:
    return b"\x00" * (int(SAMPLE_RATE * seconds) * SAMPLE_WIDTH * CHANNELS)


def _cut_offsets(pcm: bytes, seconds: float) -> list[float]:
    """Cumulative cut offsets inside the PCM, in seconds."""
    offsets: list[float] = []
    offset = 0
    for chunk in split_pcm(pcm, seconds)[:-1]:
        offset += len(chunk)
        offsets.append(offset / BYTES_PER_SECOND)
    return offsets


class TestSplitPcm:
    def test_empty_audio_yields_no_segments(self) -> None:
        assert split_pcm(b"") == []

    def test_short_audio_is_one_untouched_segment(self) -> None:
        pcm = _tone(2)

        segments = split_pcm(pcm)

        assert len(segments) == 1
        assert segments[0] == pcm

    def test_every_segment_respects_the_maximum(self) -> None:
        pcm = _tone(95)

        segments = split_pcm(pcm)

        assert len(segments) >= math.ceil(95 / SECONDS_PER_CHUNK)
        assert all(
            len(segment) <= SECONDS_PER_CHUNK * BYTES_PER_SECOND for segment in segments
        )

    def test_the_original_audio_is_preserved(self) -> None:
        pcm = _tone(95)

        segments = split_pcm(pcm)

        assert b"".join(segments) == pcm

    def test_cuts_land_in_silence_when_speech_pauses(self) -> None:
        pcm = _tone(27) + _silence(1) + _tone(29) + _silence(1) + _tone(37)

        offsets = _cut_offsets(pcm, SECONDS_PER_CHUNK)

        assert len(offsets) == 3
        assert 27.0 <= offsets[0] <= 28.0
        assert 57.0 <= offsets[1] <= 58.0
        assert 87.0 <= offsets[2] <= 88.0

    def test_continuous_speech_still_splits_at_the_maximum(self) -> None:
        pcm = _tone(95)

        assert _cut_offsets(pcm, SECONDS_PER_CHUNK) == [30.0, 60.0, 90.0]

    def test_segments_stay_sample_aligned(self) -> None:
        pcm = _tone(95)

        segments = split_pcm(pcm)

        assert all(len(segment) % SAMPLE_WIDTH == 0 for segment in segments)
