import json
import subprocess
from pathlib import Path

from . import config


def measure_loudness(
    video: Path,
    stream_index: int,
    filter_chain: str,
    *,
    ffmpeg_path: str = config.FFMPEG_PATH,
    target_i: float = config.LOUDNORM_I,
    target_tp: float = config.LOUDNORM_TP,
    target_lra: float = config.LOUDNORM_LRA,
) -> dict:
    """Runs loudnorm in analysis mode against the given stream + filter chain
    and returns the measured stats (input_i, input_tp, input_lra,
    input_thresh, target_offset) it prints to stderr as JSON."""
    loudnorm = f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json"
    cmd = [
        ffmpeg_path,
        "-i",
        str(video),
        "-map",
        f"0:{stream_index}",
        "-af",
        f"{filter_chain},{loudnorm}",
        "-f",
        "null",
        "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    stderr = result.stderr
    start = stderr.rfind("{")
    end = stderr.rfind("}") + 1
    if start == -1 or end == 0:
        raise RuntimeError(f"loudnorm produced no measurement output for {video}")
    return json.loads(stderr[start:end])


def build_linear_loudnorm_filter(
    stats: dict,
    *,
    target_i: float = config.LOUDNORM_I,
    target_tp: float = config.LOUDNORM_TP,
    target_lra: float = config.LOUDNORM_LRA,
) -> str:
    """Builds the loudnorm filter for the real encode pass, using stats from
    measure_loudness() to do a precise linear correction instead of guessing
    from a single pass. Note the measure-pass keys (input_i, input_tp, ...)
    map to differently-named apply-pass options (measured_I, measured_TP, ...)."""
    return (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
        f":measured_I={stats['input_i']}"
        f":measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}"
        ":linear=true"
    )
