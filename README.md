# hyper-voice

Fixes muddy dialogue in movie/show rips for playback on a Hisense AX3120Q soundbar (or any setup where the center channel is too quiet). Probes a video's audio streams, picks the best source track, downmixes it to 5.1 with a center-channel boost, applies two-pass loudness normalization, and muxes the result as a **new** audio track alongside the originals — nothing existing is re-encoded or removed.

## Requirements

- Python >= 3.14
- [`uv`](https://docs.astral.sh/uv/)

The application uses PyAV's FFmpeg libraries in-process; it does not require
`ffmpeg` or `ffprobe` executables at runtime.

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

`run` defaults to the `compatible` profile: a 48 kHz, 640 kb/s E-AC-3 5.1
track intended for TV/eARC/soundbar playback. Use `--profile archival` for
48 kHz FLAC, which preserves the processed PCM but may not play as
multichannel audio through every HDMI/eARC path. `--codec` and `--bitrate`
override the profile's codec and bitrate exactly.

### Output

`run` writes to `<input_dir>/boosted_output/<name>_<input-extension>_boosted.mkv` by default (override with `--output-dir`). The input extension prevents `Movie.mkv` and `Movie.mp4` from colliding. The new file has every original stream copied untouched plus one new encoded audio track appended at the end. Existing output is skipped, not overwritten, unless you pass `--overwrite`. If a directory has multiple files, one bad file doesn't abort the batch — the batch exits non-zero at the end if anything failed.

Mono/stereo-only inputs fail clearly by default rather than silently producing a no-op copy. `--allow-stereo` permits selection for inspection, but stereo rendering is not implemented yet.

### Flags (`run`)

```
--output-dir   PATH    Directory for boosted output. [default: <input>/boosted_output]
--language     TEXT    Preferred source-track language. [default: eng]
--loudness-i   FLOAT   Target integrated loudness (LUFS). [default: -16.0]
--true-peak    FLOAT   True peak ceiling (dBTP). [default: -1.5]
--lra          FLOAT   Target loudness range. [default: 11.0]
--profile      TEXT    Output profile: compatible (E-AC-3) or archival (FLAC).
--codec        TEXT    Codec override for the new track.
--bitrate      TEXT    Bitrate override for the new track.
--workers      INT     Max parallel ffmpeg jobs. [default: 4]
--overwrite             Overwrite existing boosted output files.
--source-track INT     Exact input audio stream index to use.
--prefer-5-1           Prefer 5.1 over 7.1 when otherwise equivalent.
--allow-stereo          Permit a stereo/mono source (inspection only today).
```

Run `uv run hyper-voice run --help` or `uv run hyper-voice inspect --help` for the full, current list — flags are the source of truth over this file.

### Examples

```fish
# Batch-process a season, preferring Japanese audio, 6 parallel workers
uv run hyper-voice run /media/show/season-1 --language jpn --workers 6

# Louder target loudness, re-encode files that already have boosted_output
uv run hyper-voice run /media/movie.mkv --loudness-i -14 --overwrite

# Create a lossless representation of the processed PCM
uv run hyper-voice run /media/movie.mkv --profile archival
```

## How source track selection works

1. Commentary tracks are excluded by title keyword match (`commentary`, `director`, `cast`) unless every track is commentary.
2. Among what's left, tracks matching `--language` are preferred (handles the ISO 639-1/639-2 split, e.g. `eng` vs `en`).
3. Among the language pool, discrete surround tracks are required and rank by channel count (7.1 before 5.1 by default); use `--prefer-5-1` to reverse that preference.
4. Codec/fidelity tier and bitrate break remaining ties. Input stream order is retained for an exact tie.

## Development

```fish
uv run pytest
uv run ruff check .
uv run ruff format --check .

# Install the Git hook once per clone. It automatically fixes lint and format issues.
uv run pre-commit install
```

Pure-function unit tests run everywhere. Integration tests (`tests/test_pipeline.py`) are skipped automatically if `ffmpeg`/`ffprobe` aren't on `PATH`.

See `AGENTS.md` for package layout and pipeline internals.
