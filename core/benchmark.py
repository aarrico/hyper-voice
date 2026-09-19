"""Local, opt-in benchmark support for real media files.

Benchmark data is deliberately written only to a user-selected output path.
Downloaded media and its measurements are not repository fixtures.
"""

import json
import resource
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import av

from .pipeline import ProcessResult, process_video
from .probe import probe_audio_streams


def _duration_seconds(path: Path) -> float | None:
    with av.open(str(path)) as container:
        if container.duration is not None:
            return float(container.duration / av.time_base)
    return None


def _peak_memory_kib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes.
    return float(peak if sys.platform != "darwin" else peak / 1024)


def _stream_summary(path: Path) -> list[dict]:
    return [
        {
            "index": stream["index"],
            "codec": stream["codec_name"],
            "channels": stream["channels"],
            "sample_rate": stream["sample_rate"],
            "layout": stream["channel_layout"],
            "bitrate": stream["bit_rate"],
        }
        for stream in probe_audio_streams(path)
    ]


def _record_result(
    result: ProcessResult, input_streams: list[dict], workers: int
) -> dict:
    output_streams = (
        _stream_summary(result.output_path)
        if result.output_path is not None and result.output_path.exists()
        else []
    )
    input_duration = _duration_seconds(result.video)
    return {
        "input": str(result.video),
        "input_bytes": result.video.stat().st_size,
        "input_duration_seconds": input_duration,
        "input_audio_streams": input_streams,
        "status": result.status,
        "error": asdict(result.error) if result.error is not None else None,
        "output": str(result.output_path) if result.output_path is not None else None,
        "output_bytes": (
            result.output_path.stat().st_size
            if result.output_path is not None and result.output_path.exists()
            else None
        ),
        "output_audio_streams": output_streams,
        "elapsed_seconds": result.elapsed_seconds,
        "processing_speed": (
            input_duration / result.elapsed_seconds
            if input_duration is not None and result.elapsed_seconds > 0
            else None
        ),
        "loudnorm_mode": result.loudnorm_mode,
        "workers": workers,
    }


def benchmark_videos(
    files: list[Path],
    output_dir: Path,
    results_path: Path,
    *,
    mode: str,
    profile: str,
    workers: int,
    overwrite: bool,
) -> dict:
    """Run the selected processing mode and write a portable JSON benchmark.

    Per-file elapsed time includes the complete in-process pipeline.  PyAV
    remuxes packets while it filters audio, so rendering and remuxing overlap
    and are intentionally reported as one end-to-end figure rather than
    misleading independent timings.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    input_streams = {str(file): _stream_summary(file) for file in files}
    effective_workers = 1 if len(files) == 1 else workers

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(
                process_video,
                file,
                output_dir,
                profile=profile,
                overwrite=overwrite,
                processing_mode=mode,
            ): file
            for file in files
        }
        results = [future.result() for future in as_completed(futures)]

    report = {
        "mode": mode,
        "profile": profile,
        "workers": effective_workers,
        "wall_seconds": time.perf_counter() - wall_started,
        "cpu_seconds": time.process_time() - cpu_started,
        "peak_memory_kib": _peak_memory_kib(),
        "records": [
            _record_result(result, input_streams[str(result.video)], effective_workers)
            for result in sorted(results, key=lambda item: str(item.video))
        ],
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
