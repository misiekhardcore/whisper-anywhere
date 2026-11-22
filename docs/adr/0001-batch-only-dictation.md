# ADR 0001 - Transcribe a whole dictation in one pass

- Status: accepted, implemented
- Date: 2026-11-22

## Context

The daemon offered two modes. Batch mode recorded the whole hotkey hold and
transcribed it once on release. Live mode ran an FSMN-VAD loop that re-transcribed
the growing speech segment every 200 ms and repaired the focused window with
backspaces followed by retyped text.

Live mode was the wrong trade for the target application: continuous synthetic
keystrokes and backspaces fight the focused window's own undo, autocomplete and
search state. It also produced worse text, because each partial decode saw a
different prefix of the same sentence.

Measured on the development machine with the 35.5 s fixture in `tests/fixtures/`:
`faster-whisper distil-medium.en` needs 6.4 s for that audio (0.18x realtime).
SenseVoiceSmall could not be measured (model cache absent, ModelScope returned
HTTP 403), and is documented at roughly 15x realtime.

## Decision

A dictation is recorded from hotkey press to hotkey release and transcribed
exactly once. The transcript is inserted once. The VAD module, the `--vad` flag,
the `vad_engine` config key and all live-streaming code are to be removed.

## Consequences

- Insertion never mutates text already in the application, so the daemon cannot
  corrupt the document or the application's undo history.
- Text quality depends on one decode over the full context, so no seam word is
  lost or doubled at a chunk boundary.
- Release-to-text latency equals full transcription time: about 5.5 s for a 30 s
  dictation with `distil-medium.en`, about 2 s with SenseVoiceSmall. A 60 s
  recording, the cap in `audio.py`, is the worst case.
- After the removal, `funasr` will be required only by the SenseVoice engine, not
  by the VAD model.

## Alternatives rejected

- **Chunk-only insertion.** Closing a chunk on 0.6 s of silence splits sentences
  mid-clause, and the seams become visible in the target document.
- **Pipelined chunks with a single insertion on release.** Hides transcription
  latency behind speech, but keeps the seam-quality risk and adds concurrency
  for a latency gain that the SenseVoice engine does not need.
