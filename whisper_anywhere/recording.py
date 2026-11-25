import asyncio
import sys

from .audio import (
    AUDIO,
    CHANNELS,
    DEFAULT_MAX_RECORDING_SECONDS,
    PAREC_FORMAT,
    PAREC_LATENCY_MS,
    SAMPLE_RATE,
    read_audio,
    recording_bytes,
    stop_recording,
    write_wav,
)
from .output import TextOutput
from .segments import split_pcm
from .state import FAILURE_NOTE, DaemonState, NullStatus, StatePublisher
from .transcribe import Transcriber


class Recording:
    """The capture of one dictation: the parec process, its reader and the PCM buffer."""

    def __init__(
        self,
        process: asyncio.subprocess.Process | None,
        reader: asyncio.Task,
        buffer: bytearray,
        cap_reached: asyncio.Event | None = None,
    ) -> None:
        self.process = process
        self.reader = reader
        self.buffer = buffer
        self.cap_reached = cap_reached or asyncio.Event()


class Recorder:
    def __init__(
        self,
        engine: Transcriber,
        language: str | None,
        output: TextOutput,
        status: StatePublisher | None = None,
    ) -> None:
        self._engine = engine
        self._language = language
        self._output = output
        self._status = status or NullStatus()

    @staticmethod
    async def start(
        max_seconds: float = DEFAULT_MAX_RECORDING_SECONDS,
    ) -> Recording:
        buffer = bytearray()
        cap_reached = asyncio.Event()
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
        reader = asyncio.create_task(
            read_audio(
                process,
                buffer,
                max_bytes=recording_bytes(max_seconds),
                cap_reached=cap_reached,
            )
        )
        return Recording(process, reader, buffer, cap_reached)

    async def finish(self, recording: Recording, note: str | None = None) -> None:
        """Stop capture, transcribe the recording in segments and emit once."""
        stop_recording(recording.process)
        await recording.reader
        await recording.process.wait()

        if not recording.buffer:
            self._status.publish(DaemonState.IDLE)
            return
        self._status.publish(DaemonState.PROCESSING)
        try:
            text = await self._transcribe(recording.buffer)
        except Exception as exc:
            print(f"Transcription failed: {exc}", file=sys.stderr)
            self._status.publish(DaemonState.IDLE, FAILURE_NOTE)
            return
        if not text.strip():
            self._status.publish(DaemonState.IDLE)
            return
        # The transcript exists, so processing is over before anything is inserted.
        self._status.publish(DaemonState.IDLE, note)
        if not await self._output.emit(text):
            self._status.publish(DaemonState.IDLE, FAILURE_NOTE)

    async def _transcribe(self, pcm: bytes | bytearray) -> str:
        """Decode each segment in order and join the transcripts into one text."""
        loop = asyncio.get_running_loop()
        segments = await loop.run_in_executor(None, split_pcm, pcm)
        transcripts: list[str] = []
        for segment in segments:
            write_wav(AUDIO, segment)
            text: str = await loop.run_in_executor(
                None, lambda: self._engine.transcribe(AUDIO, language=self._language)
            )
            if text.strip():
                transcripts.append(text.strip())
        return " ".join(transcripts)
