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

## Amendment 2026-11-25 - no length cap on a dictation

The 60 s cap was a hard, silent truncation: `read_audio()` stopped `parec` and the
tail of the dictation was lost while the daemon still showed `recording`. The
decision above still holds for insertion - one dictation, one insertion - but the
single decode does not scale to long audio. SenseVoice's encoder cost grows
quadratically with duration and it is trained on utterance-length audio, so one
unbounded pass is slow and inaccurate, while a hard cutoff destroys speech.

A hold is now cut by `segments.split_pcm()` into chunks of at most 30 s at the
quietest frame near each boundary, every chunk is decoded by the same engine, and
the transcripts are joined into the one insertion. Segmentation happens at the
transcription layer, not the insertion layer, so no seam is exposed to the focused
application.

The recording itself has no cap of any kind: it continues until the hotkey is
released, and no option or config key can cut it short. The only bound is memory,
32 KB/s of PCM (about 115 MB per hour), which is the accepted cost of never
blocking or truncating a dictation.

## Alternatives rejected

- **Chunk-only insertion.** Closing a chunk on 0.6 s of silence splits sentences
  mid-clause, and the seams become visible in the target document.
- **Pipelined chunks with a single insertion on release.** Hides transcription
  latency behind speech, but keeps the seam-quality risk and adds concurrency
  for a latency gain that the SenseVoice engine does not need.
