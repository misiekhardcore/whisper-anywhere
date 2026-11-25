"""Split a captured dictation into engine-sized pieces at the quietest points."""

import array
import sys

from .audio import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

FRAME_SECONDS = 0.02
DEFAULT_SEGMENT_SECONDS = 30.0
SILENCE_SEARCH_SECONDS = 5.0
MIN_SEGMENT_SECONDS = 1.0

SAMPLE_BYTES = SAMPLE_WIDTH * CHANNELS
_FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_SECONDS)


def _frame_levels(pcm: bytes | bytearray) -> list[int]:
    """Mean square of every 20 ms frame, the energy the cut points are chosen on."""
    samples = array.array("h")
    samples.frombytes(bytes(pcm[: len(pcm) // SAMPLE_BYTES * SAMPLE_BYTES]))
    if sys.byteorder == "big":
        samples.byteswap()
    return [
        sum(sample * sample for sample in samples[frame : frame + _FRAME_SAMPLES])
        for frame in range(0, len(samples) - _FRAME_SAMPLES + 1, _FRAME_SAMPLES)
    ]


def split_pcm(
    pcm: bytes | bytearray, max_seconds: float = DEFAULT_SEGMENT_SECONDS
) -> list[bytes]:
    """Cut PCM into chunks of at most max_seconds, preferring the quietest frame.

    Cutting where the speaker is quietest keeps words whole, so the transcripts
    of neighbouring chunks join without a lost or doubled seam word.
    """
    data = bytes(pcm)
    if not data:
        return []

    levels = _frame_levels(data)
    frame_samples_bytes = _FRAME_SAMPLES * SAMPLE_BYTES
    max_frames = max(1, int(max_seconds / FRAME_SECONDS))
    min_frames = max(1, int(MIN_SEGMENT_SECONDS / FRAME_SECONDS))
    search_frames = max(1, int(SILENCE_SEARCH_SECONDS / FRAME_SECONDS))
    total_frames = len(levels)

    chunks: list[bytes] = []
    start = 0
    while total_frames - start > max_frames:
        limit = start + max_frames
        window_start = max(start + min_frames, limit - search_frames)
        # Latest quietest frame, so a uniformly loud stretch cuts at the limit.
        cut = min(range(window_start, limit + 1), key=lambda i: (levels[i], -i))
        chunks.append(data[start * frame_samples_bytes : cut * frame_samples_bytes])
        start = cut

    chunks.append(data[start * frame_samples_bytes :])
    return chunks
