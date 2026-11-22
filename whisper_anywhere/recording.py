import asyncio
import sys

from .audio import (
    AUDIO,
    CHANNELS,
    PAREC_FORMAT,
    PAREC_LATENCY_MS,
    SAMPLE_RATE,
    read_audio,
    stop_recording,
    write_wav,
)
from .output import TextOutput
from .transcribe import Transcriber


class Recording:
    """The capture of one dictation: the parec process, its reader and the PCM buffer."""

    def __init__(
        self,
        process: asyncio.subprocess.Process | None,
        reader: asyncio.Task,
        buffer: bytearray,
    ) -> None:
        self.process = process
        self.reader = reader
        self.buffer = buffer


class Recorder:
    def __init__(
        self,
        engine: Transcriber,
        language: str | None,
        output: TextOutput,
    ) -> None:
        self._engine = engine
        self._language = language
        self._output = output

    @staticmethod
    async def start() -> Recording:
        buffer = bytearray()
        process = await asyncio.create_subprocess_exec(
            "parec",
            f"--format={PAREC_FORMAT}",
            f"--rate={SAMPLE_RATE}",
            f"--channels={CHANNELS}",
            "--raw",
            f"--latency-msec={PAREC_LATENCY_MS}",
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,
        )
        reader = asyncio.create_task(read_audio(process, buffer))
        return Recording(process, reader, buffer)

    async def finish(self, recording: Recording) -> None:
        """Stop capture, transcribe the whole recording once and emit the transcript once."""
        stop_recording(recording.process)
        await recording.reader
        await recording.process.wait()

        if not recording.buffer:
            return
        try:
            text = await self._transcribe(recording.buffer)
        except Exception as exc:
            print(f"Transcription failed: {exc}", file=sys.stderr)
            return
        if not text.strip():
            return
        self._output.emit(text)

    async def _transcribe(self, pcm: bytes | bytearray) -> str:
        write_wav(AUDIO, pcm)
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._engine.transcribe(AUDIO, language=self._language)
        )
