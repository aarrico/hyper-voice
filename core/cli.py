from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import typer

from . import config
from .filters import get_downmix_filter
from .loudness import measure_loudness
from .pipeline import process_video
from .probe import probe_audio_streams, select_source_stream

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
) -> None:
    """Probe files and print measured loudness stats without encoding anything."""
    files = _collect_files(path)
    if not files:
        typer.echo(f"[✘] No supported video files found: {path}", err=True)
        raise typer.Exit(code=1)

    had_failure = False
    for video in files:
        try:
            streams = probe_audio_streams(video)
            source = select_source_stream(streams, preferred_language=language)
            filter_chain = get_downmix_filter(source.get("channel_layout", ""))
            stats = measure_loudness(video, source["index"], filter_chain)
            typer.echo(f"{video.name}: {stats}")
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
    codec: str = typer.Option(
        config.NEW_TRACK_CODEC, help="Codec for the new boosted track."
    ),
    bitrate: str = typer.Option(
        config.NEW_TRACK_BITRATE, help="Bitrate for the new boosted track."
    ),
    workers: int = typer.Option(
        config.MAX_WORKERS, min=1, help="Max parallel encode jobs."
    ),
    overwrite: bool = typer.Option(
        False, help="Overwrite existing boosted output files."
    ),
) -> None:
    """Downmix, boost, normalize, and mux a new dialogue-boosted audio track."""
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
                new_track_codec=codec,
                new_track_bitrate=bitrate,
                overwrite=overwrite,
            ): video
            for video in files
        }
        for future in as_completed(futures):
            result = future.result()
            typer.echo(result)
            if result.startswith("[✘]"):
                had_failure = True

    if had_failure:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
