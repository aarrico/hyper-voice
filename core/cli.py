from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import typer

from . import config
from .benchmark import benchmark_videos
from .filters import get_dialogue_remix_filter
from .loudness import measure_loudness
from .pipeline import process_video
from .probe import explain_source_candidates, probe_audio_streams, select_source_stream

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() not in config.EXTENSIONS:
            typer.echo(f"[✘] Unsupported file type: {target.suffix}", err=True)
            raise typer.Exit(code=1)
        return [target]
    return sorted(
        f
        for f in target.iterdir()
        if f.is_file() and f.suffix.lower() in config.EXTENSIONS
    )


@app.command()
def inspect(
    path: Path = typer.Argument(
        ..., exists=True, help="Video file or directory to inspect."
    ),
    language: str = typer.Option(
        config.PREFERRED_LANGUAGE, help="Preferred source-track language."
    ),
    source_track: int | None = typer.Option(
        None, help="Exact input audio stream index to use."
    ),
    prefer_5_1: bool = typer.Option(
        False, help="Prefer 5.1 over 7.1 when otherwise equivalent."
    ),
    allow_stereo: bool = typer.Option(
        False, help="Permit a stereo/mono source (currently inspection only)."
    ),
) -> None:
    """Probe files and measure the precise-mode dialogue chain without encoding."""
    files = _collect_files(path)
    if not files:
        typer.echo(f"[✘] No supported video files found: {path}", err=True)
        raise typer.Exit(code=1)

    had_failure = False
    for video in files:
        try:
            streams = probe_audio_streams(video)
            for candidate in explain_source_candidates(
                streams,
                preferred_language=language,
                source_track=source_track,
                prefer_5_1=prefer_5_1,
                allow_stereo=allow_stereo,
            ):
                typer.echo(f"  stream #{candidate.stream['index']}: {candidate.reason}")
            source = select_source_stream(
                streams,
                preferred_language=language,
                source_track=source_track,
                prefer_5_1=prefer_5_1,
                allow_stereo=allow_stereo,
            )
            typer.echo(f"  selected: stream #{source['index']}")
            if source.get("channels", 0) <= 2:
                typer.echo(
                    f"{video.name}: stereo/mono selected; no surround loudness analysis performed"
                )
                continue
            filter_chain = get_dialogue_remix_filter(source.get("channel_layout", ""))
            stats = measure_loudness(
                video, source["index"], filter_chain, dialogue_mode=True
            )
            typer.echo(f"{video.name} (precise pre-normalization): {stats}")
        except Exception as e:
            had_failure = True
            typer.echo(f"[✘] Failed: {video.name}: {e}", err=True)

    if had_failure:
        raise typer.Exit(code=1)


@app.command()
def run(
    path: Path = typer.Argument(
        ..., exists=True, help="Video file or directory to process."
    ),
    output_dir: Path | None = typer.Option(
        None, help="Directory for boosted output (default: <input>/boosted_output)."
    ),
    language: str = typer.Option(
        config.PREFERRED_LANGUAGE, help="Preferred source-track language."
    ),
    loudness_i: float = typer.Option(
        config.LOUDNORM_I, help="Target integrated loudness (LUFS)."
    ),
    true_peak: float = typer.Option(
        config.LOUDNORM_TP, help="True peak ceiling (dBTP)."
    ),
    lra: float = typer.Option(config.LOUDNORM_LRA, help="Target loudness range."),
    codec: str | None = typer.Option(
        None, help="Codec override for the new track (overrides profile)."
    ),
    bitrate: str | None = typer.Option(
        None, help="Bitrate override for the new track (overrides profile)."
    ),
    profile: str = typer.Option(
        config.DEFAULT_PROFILE,
        help="Output profile: compatible (E-AC-3) or archival (FLAC).",
    ),
    workers: int = typer.Option(
        config.MAX_WORKERS, min=1, help="Max parallel encode jobs."
    ),
    overwrite: bool = typer.Option(
        False, help="Overwrite existing boosted output files."
    ),
    source_track: int | None = typer.Option(
        None, help="Exact input audio stream index to use."
    ),
    prefer_5_1: bool = typer.Option(
        False, help="Prefer 5.1 over 7.1 when otherwise equivalent."
    ),
    allow_stereo: bool = typer.Option(
        False, help="Permit a stereo/mono source (not yet renderable)."
    ),
    mode: str = typer.Option(
        config.DEFAULT_PROCESSING_MODE,
        help="Processing mode: boost, dialogue (center compression), or precise (two-pass loudnorm).",
    ),
) -> None:
    """Add a dialogue-boosted audio track while preserving every original stream."""
    files = _collect_files(path)
    if not files:
        typer.echo(f"[✘] No supported video files found: {path}", err=True)
        raise typer.Exit(code=1)

    out_dir = output_dir or (
        path.parent / "boosted_output" if path.is_file() else path / "boosted_output"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    effective_workers = 1 if len(files) == 1 else workers
    had_failure = False
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(
                process_video,
                video,
                out_dir,
                preferred_language=language,
                target_i=loudness_i,
                target_tp=true_peak,
                target_lra=lra,
                profile=profile,
                new_track_codec=codec,
                new_track_bitrate=bitrate,
                overwrite=overwrite,
                source_track=source_track,
                prefer_5_1=prefer_5_1,
                allow_stereo=allow_stereo,
                processing_mode=mode,
            ): video
            for video in files
        }
        for future in as_completed(futures):
            result = future.result()
            typer.echo(result)
            if result.failed:
                had_failure = True

    if had_failure:
        raise typer.Exit(code=1)


@app.command()
def benchmark(
    path: Path = typer.Argument(
        ..., exists=True, help="Video file or directory to benchmark."
    ),
    output_dir: Path | None = typer.Option(
        None, help="Directory for benchmarked media output."
    ),
    results: Path | None = typer.Option(
        None, help="JSON results path (default: <output-dir>/benchmark.json)."
    ),
    mode: str = typer.Option("precise", help="Processing mode to measure."),
    profile: str = typer.Option(
        config.DEFAULT_PROFILE, help="Output profile to benchmark."
    ),
    workers: int = typer.Option(
        config.MAX_WORKERS, min=1, help="Concurrent files to process."
    ),
    overwrite: bool = typer.Option(
        False, help="Overwrite prior benchmarked media output."
    ),
) -> None:
    """Process real media and save local performance measurements as JSON."""
    files = _collect_files(path)
    if not files:
        typer.echo(f"[✘] No supported video files found: {path}", err=True)
        raise typer.Exit(code=1)
    if mode not in config.PROCESSING_MODES:
        available = ", ".join(config.PROCESSING_MODES)
        typer.echo(f"[✘] Unknown processing mode '{mode}'; choose one of: {available}")
        raise typer.Exit(code=1)

    benchmark_dir = output_dir or (
        path.parent / "benchmark_output"
        if path.is_file()
        else path / "benchmark_output"
    )
    results_path = results or benchmark_dir / "benchmark.json"
    report = benchmark_videos(
        files,
        benchmark_dir,
        results_path,
        mode=mode,
        profile=profile,
        workers=workers,
        overwrite=overwrite,
    )
    typer.echo(
        f"[✔] Wrote benchmark results for {len(report['records'])} file(s): {results_path}"
    )
    if any(record["status"] == "failed" for record in report["records"]):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
