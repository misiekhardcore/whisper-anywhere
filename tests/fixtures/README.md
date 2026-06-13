# Test audio fixtures

`test_real_e2e` (in `tests/test_e2e.py`) transcribes a short pre-recorded clip
with a real `tiny.en` model and asserts the result against a known transcript.

## What goes here

- A short (~1–2 s, < 200 KB) **CC0 / public-domain** speech clip with a clear,
  known transcript, named `*.wav` and encoded as **16 kHz mono s16le PCM**.
- `transcript.txt` — the exact expected transcript for that clip (used by the
  test; matching is tolerant, so punctuation/casing don't need to be perfect).

## Adding a test

To enable the real e2e test:

1. Obtain a short CC0/public-domain spoken clip. Suggested sources:
   - Wikimedia Commons (filter by CC0 / public domain), or
   - generate one locally: `espeak-ng -w clip_raw.wav "the quick brown fox jumps over the lazy dog"`.
2. Convert to the required format:
   ```bash
   ffmpeg -y -i clip_raw.wav -ar 16000 -ac 1 -sample_fmt s16 -c:a pcm_s16le clip.wav
   ```
3. Put `clip.wav` in this directory and set `transcript.txt` to its exact words.
4. Record the source URL + license below.

Until a `*.wav` is present, `test_real_e2e` self-skips, so the suite stays green.

## Source / license

_(fill in when the clip is added)_

- Source URL: https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0034_8k.wav
- License: CC0 / public domain
