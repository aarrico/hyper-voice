import json
from pathlib import Path

import av

from . import config
from .filters import link_filter_chain


def _run_pan_loudnorm_pass(
    video: Path, stream_index: int, filter_chain: str, loudnorm_args: str
):
    """Decodes the given stream through `filter_chain` (a `pan=...` string)
    into `loudnorm`, draining every filtered frame. Returns nothing useful by
    itself — callers either read loudnorm's analysis JSON via a log capture
    (measure pass) or encode the drained frames (apply pass)."""
    with av.open(str(video)) as container:
        stream = next(s for s in container.streams.audio if s.index == stream_index)

        graph = av.filter.Graph()
        abuf = graph.add_abuffer(template=stream)
        pan_ctx = link_filter_chain(graph, filter_chain, abuf)
        loud_ctx = graph.add("loudnorm", loudnorm_args)
        sink = graph.add("abuffersink")
        pan_ctx.link_to(loud_ctx)
        loud_ctx.link_to(sink)
        graph.configure()

        for packet in container.demux(stream):
            for frame in packet.decode():
                graph.push(frame)
                _drain(graph)
        graph.push(None)
        _drain(graph)
        # loudnorm only prints its analysis-mode JSON to the av_log system on
        # filter teardown, so the graph must be torn down before whatever log
        # capture is active around this call sees the stats.
        del sink, loud_ctx, pan_ctx, abuf, graph


def _drain(graph: "av.filter.Graph") -> None:
    while True:
        try:
            graph.pull()
        except (av.error.BlockingIOError, av.error.EOFError):
            return


def _extract_json_stats(text: str, video: Path) -> dict:
    start = text.rfind("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise RuntimeError(f"loudnorm produced no measurement output for {video}")
    return json.loads(text[start:end])


def measure_loudness(
    video: Path,
    stream_index: int,
    filter_chain: str,
    *,
    target_i: float = config.LOUDNORM_I,
    target_tp: float = config.LOUDNORM_TP,
    target_lra: float = config.LOUDNORM_LRA,
) -> dict:
    """Runs `filter_chain` (the center-boost `pan` filter) into `loudnorm` in
    analysis mode and returns the measured stats (input_i, input_tp,
    input_lra, input_thresh, target_offset). Loudness is measured *after* the
    center-channel boost, matching what the final encode pass will actually
    hear, not the raw unboosted source."""
    loudnorm_args = f"I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json"

    # PyAV silently drops all av_log output by default; loudnorm's analysis
    # JSON is only reachable by capturing it, so logging must be turned on.
    # ffmpeg also dedupes byte-identical consecutive log lines ("skip
    # repeated"), which would silently drop this JSON on any file whose
    # measured stats happen to match the previous call's — must stay off.
    av.logging.set_level(av.logging.INFO)
    av.logging.set_skip_repeated(False)
    with av.logging.Capture(local=True) as logs:
        _run_pan_loudnorm_pass(video, stream_index, filter_chain, loudnorm_args)
        text = "".join(msg for _level, _ctx, msg in logs)

    return _extract_json_stats(text, video)


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
