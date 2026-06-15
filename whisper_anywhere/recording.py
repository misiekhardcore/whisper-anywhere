import asyncio
import os
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
from .config import Config
from .output import TextOutput
from .transcribe import Transcriber
from .vad import VAD

_SILENCE_THRESHOLD_S = 0.6


class Recorder:
    def __init__(
        self,
        engine: Transcriber,
        language: str | None,
        vad: VAD | None,
        output: TextOutput,
    ) -> None:
        self._engine = engine
        self._language = language
        self._vad = vad
        self._output = output

    @staticmethod
    async def start():
        buffer = bytearray()
        proc = await asyncio.create_subprocess_exec(
            "parec",
            f"--format={PAREC_FORMAT}",
            f"--rate={SAMPLE_RATE}",
            f"--channels={CHANNELS}",
            "--raw",
            f"--latency-msec={PAREC_LATENCY_MS}",
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,
        )
        read_task = asyncio.create_task(read_audio(proc, buffer))
        return proc, read_task, buffer

    async def live_vad_loop(
        self,
        buffer: bytearray,
        stop_event: asyncio.Event,
    ):
        sample_rate = 16000
        sample_width = 2
        min_audio = int(0.25 * sample_rate * sample_width)
        silence_threshold_bytes = int(_SILENCE_THRESHOLD_S * sample_rate * sample_width)

        vad_pos = 0
        segment_start = 0
        last_speech_pos = 0
        in_segment = False
        current_partial = ""

        consecutive_failures = 0
        max_consecutive_failures = 10

        while not stop_event.is_set():
            try:
                consecutive_failures = 0
                await asyncio.sleep(0.2)

                current_pos = len(buffer)
                if current_pos < min_audio:
                    continue

                new_audio = bytes(buffer[vad_pos:current_pos])
                segments = self._vad.detect(new_audio, sample_rate)

                if segments:
                    if not in_segment:
                        segment_start = vad_pos
                        in_segment = True
                    last_speech_pos = current_pos

                    tmp = os.path.join(Config.runtime_dir(), "live_segment.wav")
                    try:
                        write_wav(tmp, bytes(buffer[segment_start:current_pos]))
                        text = await asyncio.get_running_loop().run_in_executor(
                            None,
                            lambda t=tmp, lang=self._language: self._engine.transcribe(
                                t, language=lang
                            ),
                        )
                        if text != current_partial:
                            self._output.emit_partial(current_partial, text)
                            current_partial = text
                    finally:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                elif in_segment:
                    silence_bytes = current_pos - last_speech_pos
                    if silence_bytes >= silence_threshold_bytes:
                        tmp = os.path.join(Config.runtime_dir(), "live_final.wav")
                        try:
                            write_wav(tmp, bytes(buffer[segment_start:last_speech_pos]))
                            final_text = (
                                await asyncio.get_running_loop().run_in_executor(
                                    None,
                                    lambda t=tmp, lang=self._language: (
                                        self._engine.transcribe(t, language=lang)
                                    ),
                                )
                            )
                            self._output.emit_final(current_partial, final_text)
                            current_partial = ""
                            in_segment = False
                        finally:
                            try:
                                os.remove(tmp)
                            except OSError:
                                pass

                vad_pos = current_pos
            except Exception as exc:
                consecutive_failures += 1
                print(
                    f"VAD loop error ({consecutive_failures}/{max_consecutive_failures}): {exc}",
                    file=sys.stderr,
                )
                if consecutive_failures >= max_consecutive_failures:
                    print(
                        "VAD loop: too many consecutive failures, stopping VAD loop",
                        file=sys.stderr,
                    )
                    break

        tail_start = segment_start if in_segment else vad_pos
        return current_partial, tail_start

    async def finish(
        self,
        proc: asyncio.subprocess.Process,
        read_task: asyncio.Task,
        buffer: bytearray,
        *,
        vad_task: asyncio.Task | None = None,
        stop_vad: asyncio.Event | None = None,
    ):
        if stop_vad is not None:
            stop_vad.set()

        current_partial = ""
        tail_start = 0
        if vad_task is not None:
            current_partial, tail_start = await vad_task

        stop_recording(proc)
        await read_task
        await proc.wait()

        if not buffer:
            return

        if vad_task is not None:
            tail = bytes(buffer[tail_start:])
            if not tail:
                return
            write_wav(AUDIO, tail)
            text = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._engine.transcribe(AUDIO, language=self._language)
            )
            if not any(c.isalpha() for c in text):
                return
            self._output.emit_final(current_partial, text)
        else:
            write_wav(AUDIO, buffer)
            text = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._engine.transcribe(AUDIO, language=self._language)
            )
            self._output.emit(text)
