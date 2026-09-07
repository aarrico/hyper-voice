# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Typer-based CLI tool, `hyper-voice`, that fixes muddy dialogue in movie/show rips for playback on a Hisense AX3120Q soundbar. It probes a video's audio streams, picks the best source track, downmixes it to 5.1 with a center-channel boost, applies two-pass loudness normalization, and muxes the result as a new added audio track (in `eac3`) alongside the original streams (all copied, untouched).

Runtime dependencies: `typer`, `av` (PyAV — binds `libavformat`/`libavcodec`/`libavfilter` directly; the wheel bundles its own shared libraries, so no external `ffmpeg`/`ffprobe` binary is required). All demuxing, decoding, filtering, encoding, and muxing happens in-process — no `subprocess` calls, no temp files besides the atomic-rename `.tmp.mkv` output itself.

## Running it

```fish
uv run hyper-voice inspect /path/to/video_or_folder   # dry run: probe + print measured loudness, no encode
uv run hyper-voice run /path/to/video_or_folder        # full pipeline, writes *_boosted.mkv
uv run hyper-voice run --help                          # all tunables as flags (loudness targets, language, codec, workers, ...)
```

Both commands accept a single video file or a directory (non-recursive scan of `EXTENSIONS` = mkv/mp4/avi/mov/m4v). Install globally with `uv tool install .`.

## Package layout (`core/`)

- `config.py` — default tunables (all overridable via CLI flags)
- `probe.py` — `probe_audio_streams`, `select_source_stream`, language-alias handling
- `filters.py` — `DOWNMIX_TO_5_1` pan filters + `CENTER_BOOST`
- `loudness.py` — two-pass `loudnorm` measurement and filter construction
- `pipeline.py` — `process_video`, the per-file pipeline
- `cli.py` — Typer app (`inspect`, `run` commands), `ThreadPoolExecutor` batch driver

Tests in `tests/`: pure-function unit tests run everywhere; integration tests that need a real media file are skipped automatically if `ffmpeg`/`ffprobe` aren't on `PATH` (`conftest.py` shells out to the `ffmpeg` CLI only to generate synthetic test fixtures — the app itself never does). Run with `uv run pytest`.

## Pipeline (`process_video`)

1. `probe_audio_streams` — opens the container with PyAV and reads all audio streams directly (index, codec, profile, channels, layout, title/language tags) — no subprocess.
2. `select_source_stream` — picks which existing track to derive the boosted track from:
   - Filters out commentary tracks (`_is_commentary`, matched by title keywords) unless *all* tracks are commentary.
   - Prefers the requested language (`--language`, default `eng`) if any candidate matches, via `language_aliases` (handles the ISO 639-1/639-2 tagging split, e.g. `eng` vs `en`).
   - Among what's left, ranks by `_codec_tier` (lossless/PCM/DTS-MA > everything else) then channel count.
3. If the selected source has >2 channels: `get_downmix_filter` picks a `pan=` filter from `DOWNMIX_TO_5_1` keyed by `channel_layout` (falls back to a generic `aformat` + `CENTER_BOOST` when the layout is unmapped *or absent* — some PCM-in-MKV streams don't carry a `channel_layout` tag at all). All the downmix filters bake in the same center-channel boost (`1.25*FC`) as `CENTER_BOOST`.
4. `measure_loudness` — first pass: builds an in-process PyAV filter graph (`pan` boost → `loudnorm` in analysis mode, `print_format=json`) and decodes the source stream through it once. loudnorm only emits its analysis JSON via ffmpeg's `av_log` system on filter teardown, not as a return value, so the pass captures it with `av.logging.Capture` (log level and `set_skip_repeated(False)` both have to be set explicitly — PyAV drops `av_log` output by default, and ffmpeg dedupes byte-identical consecutive log lines, which would silently swallow the JSON on a second file with matching stats). Raises `RuntimeError` if no JSON block is found instead of silently misparsing. Loudness is measured *after* the center-channel boost, matching what the final encode actually produces.
5. `build_linear_loudnorm_filter` — second pass: builds a `linear=true` loudnorm filter using the first pass's measured stats. Note the key rename between passes (`input_i` → `measured_I`, etc.) — this is ffmpeg's naming, not a bug.
6. `pipeline.py` opens the input once more, `add_stream_from_template`s every original stream (video, all audio, subs, attachments) into the output container unmodified (packets remuxed as-is, PTS/DTS untouched, metadata copied manually since templating doesn't carry it), and in the same pass decodes just the selected source stream through a second filter graph (`pan` boost → linear `loudnorm` → `aformat` to the target encoder's supported sample format/rate) into the new encoded track, tagged with `NEW_TRACK_TITLE` and the source track's language. Writes to a `.tmp.mkv` sibling path, then atomically renames to `*_boosted.mkv` on success — a failed/interrupted encode never leaves a broken file at the final name.

Mono/stereo sources (≤2 channels) skip steps 3–6 entirely — the command becomes a plain stream copy with no new track added.

Existing output is skipped (not overwritten) unless `--overwrite` is passed. A batch with any per-file failure exits non-zero; one bad file doesn't abort the rest of the batch.

## Tuning knobs

Exposed as CLI flags on `run`/`inspect` (see `--help`), backed by defaults in `config.py`: `LOUDNORM_I/TP/LRA` (normalization targets), `NEW_TRACK_CODEC`/`NEW_TRACK_BITRATE`, `PREFERRED_LANGUAGE`, `MAX_WORKERS`. Not CLI-exposed (edit directly): `COMMENTARY_KEYWORDS`, `LOSSLESS_CODECS` in `config.py`, and the `DOWNMIX_TO_5_1` / `CENTER_BOOST` pan filters in `filters.py` (edit the boost multiplier here to change how aggressive the dialogue lift is).
