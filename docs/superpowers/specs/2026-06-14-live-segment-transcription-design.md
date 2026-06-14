# Live Segment Transcription Design

**Date:** 2026-06-14
**Branch:** live-vad-streaming
**Status:** approved for implementation

## Problem

The current live VAD loop uses a 3-second sliding window. Each iteration re-transcribes the same audio from a different start point, producing unstable output (e.g., "In." → "It's supposed to be working." → "It's supposed to be working now."). The `_new_text_suffix` prefix comparison fails whenever the model revises an earlier word, causing full duplicates to be typed.

## Goal

Emit complete speech segments in real-time. While a segment is in progress, update the transcription in-place (backspace + retype). Commit a high-quality final transcription at the end of each segment (silence gap). On key release mid-speech, finalize immediately via a full-buffer pass.

## Architecture

### New emit primitives (`__main__.py`)

**`_backspace(n: int)`**
Sends `n` KEY_BACKSPACE events via `ydotool key KEY_BACKSPACE …`. No-op for `n <= 0`.

**`emit_partial(prev_text: str, new_text: str, stdout_mode: bool)`**
Updates an in-progress transcription in-place.
- If `prev_text == new_text`: no-op.
- ydotool mode: backspace `len(prev_text)` chars, then type `new_text`.
- stdout mode: `{"type": "partial", "text": "<new_text>"}`.

**`emit_final(prev_text: str, final_text: str, stdout_mode: bool)`**
Commits a completed segment, replacing any shown partial.
- ydotool mode: backspace `len(prev_text)` chars, then type `final_text`.
- stdout mode: `{"type": "final", "text": "<final_text>"}` (only if `final_text` is non-empty).

The existing `emit(text, stdout_mode)` function is unchanged and used only by non-live (normal) mode.

### Rewritten `_live_vad_loop`

**Signature change:** removes `emit_fn` parameter (was only needed for the old suffix approach). Calls `emit_partial`/`emit_final` directly.

```
_live_vad_loop(buffer, model, language, vad, stop_event, stdout_mode)
              → (current_partial: str, tail_start: int)
```

**State:**
| Variable | Meaning |
|---|---|
| `vad_pos` | Next byte to feed to VAD; advances every iteration |
| `segment_start` | Byte offset where current speech segment started |
| `last_speech_pos` | Last byte where speech was detected |
| `in_segment` | Whether currently inside a speech segment |
| `current_partial` | Text currently showing on screen (empty if nothing typed) |

**Loop body (every 0.2 s):**
1. Run VAD on `buffer[vad_pos:current_pos]`.
2. **Speech detected:**
   - If `not in_segment`: `segment_start = vad_pos`, `in_segment = True`.
   - Update `last_speech_pos = current_pos`.
   - Transcribe `buffer[segment_start:current_pos]` → `text`.
   - If `text != current_partial`: `emit_partial(current_partial, text)`, `current_partial = text`.
3. **Silence, `in_segment`, gap ≥ `_SILENCE_THRESHOLD_S` (0.6 s):**
   - Transcribe `buffer[segment_start:last_speech_pos]` → `final_text`.
   - `emit_final(current_partial, final_text)`.
   - Reset: `current_partial = ""`, `in_segment = False`.
4. **Silence, not in segment:** advance only, no transcription.
5. `vad_pos = current_pos`.

**Return:** `(current_partial, segment_start if in_segment else vad_pos)`

### Updated `_finish_recording`

Unpacks `(current_partial, tail_start)` from `vad_task`. After stopping parec and draining the buffer:

- `tail = buffer[tail_start:]`
- If `tail` is non-empty: transcribe → `emit_final(current_partial, final_text)`.
- If `tail` is empty: nothing to do (`current_partial` is always `""` when `in_segment = False`).
- Non-live (no `vad_task`): unchanged — transcribe full buffer, call `emit(text)`.

`_SILENCE_THRESHOLD_S = 0.6` defined at module level.

### stdout protocol

| Mode | JSON emitted |
|---|---|
| Non-live | `{"text": "..."}` (unchanged) |
| Live partial | `{"type": "partial", "text": "..."}` |
| Live final | `{"type": "final", "text": "..."}` |

## What is removed

- `_new_text_suffix()` — no longer needed; segment boundaries replace suffix comparison.
- `emit_fn` parameter from `_live_vad_loop` — callers no longer pass an emit callback.

## Test changes

### New tests
- `TestEmitPartial`: stdout JSON shape; ydotool backspace + type; no-op when prev == new.
- `TestEmitFinal`: stdout JSON shape; ydotool backspace + type; no emit when final is empty.

### Updated tests
- `TestLiveVADLoop`: test speech → `emit_partial` called; silence gap → `emit_final` called; buffer too short → no calls; return value is `(partial, pos)`.
- `TestFinishRecording`: vad_task returns `(partial, tail_start)`;  tail present → `emit_final` called; no tail → no call.
- `TestRunDaemonLiveMode`: unchanged (still passes `vad=...`, no `live_mode`).
