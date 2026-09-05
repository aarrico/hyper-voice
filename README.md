# hyper-voice

Fixes muddy dialogue in movie/show rips for playback on a Hisense AX3120Q soundbar (or any setup where the center channel is too quiet). Probes a video's audio streams, picks the best source track, downmixes it to 5.1 with a center-channel boost, applies two-pass loudness normalization, and muxes the result as a **new** audio track alongside the originals — nothing existing is re-encoded or removed.

## Requirements

- Python >= 3.10
- [`uv`](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` on `PATH` (checked at startup — the CLI exits immediately if either is missing)

## Install

```fish
uv tool install .
```

This puts `hyper-voice` on your `PATH` globally. Alternatively, run it from the repo without installing:

```fish
uv run hyper-voice --help
```

## Usage

```fish
# Dry run: probe audio streams, print measured loudness, encode nothing
uv run hyper-voice inspect /path/to/video_or_folder

# Full pipeline: downmix, boost, normalize, mux a new track, write *_boosted.mkv
uv run hyper-voice run /path/to/video_or_folder
```

Both commands accept either a single video file or a directory. A directory is scanned non-recursively for `.mkv`, `.mp4`, `.avi`, `.mov`, `.m4v` files.

`inspect` is read-only — use it first to see which source track will be picked and what loudness stats will drive normalization, before committing to an encode.

### Output

`run` writes to `<input_dir>/boosted_output/<name>_boosted.mkv` by default (override with `--output-dir`). The new file has every original stream copied untouched (`-map 0 -c copy`) plus one new encoded audio track appended at the end. Existing output is skipped, not overwritten, unless you pass `--overwrite`. If a directory has multiple files, one bad file doesn't abort the batch — the batch exits non-zero at the end if anything failed.

Mono/stereo sources skip the downmix/boost/normalize steps entirely (nothing to boost) — output is a plain stream copy with no new track.

### Flags (`run`)

```
--output-dir   PATH    Directory for boosted output. [default: <input>/boosted_output]
--language     TEXT    Preferred source-track language. [default: eng]
--loudness-i   FLOAT   Target integrated loudness (LUFS). [default: -16.0]
--true-peak    FLOAT   True peak ceiling (dBTP). [default: -1.5]
--lra          FLOAT   Target loudness range. [default: 11.0]
--codec        TEXT    Codec for the new boosted track. [default: eac3]
--bitrate      TEXT    Bitrate for the new boosted track. [default: 448k]
--workers      INT     Max parallel ffmpeg jobs. [default: 4]
--overwrite             Overwrite existing boosted output files.
--ffmpeg-path  TEXT    Path to the ffmpeg executable. [default: ffmpeg]
--ffprobe-path TEXT    Path to the ffprobe executable. [default: ffprobe]
```

Run `uv run hyper-voice run --help` or `uv run hyper-voice inspect --help` for the full, current list — flags are the source of truth over this file.

### Examples

```fish
# Batch-process a season, preferring Japanese audio, 6 parallel workers
uv run hyper-voice run /media/show/season-1 --language jpn --workers 6

# Louder target loudness, re-encode files that already have boosted_output
uv run hyper-voice run /media/movie.mkv --loudness-i -14 --overwrite

# Point at non-PATH ffmpeg/ffprobe binaries
uv run hyper-voice inspect /media/movie.mkv --ffmpeg-path /opt/ffmpeg/bin/ffmpeg --ffprobe-path /opt/ffmpeg/bin/ffprobe
```

## How source track selection works

1. Commentary tracks are excluded by title keyword match (`commentary`, `director`, `cast`) unless every track is commentary.
2. Among what's left, tracks matching `--language` are preferred (handles the ISO 639-1/639-2 split, e.g. `eng` vs `en`).
3. Among what's left, ranked by codec tier (lossless/PCM/DTS-MA beats everything else), then channel count.

## Development

```fish
uv run pytest
```

Pure-function unit tests run everywhere. Integration tests (`tests/test_pipeline.py`) are skipped automatically if `ffmpeg`/`ffprobe` aren't on `PATH`.

See `CLAUDE.md` for package layout and pipeline internals.
