import json
import re
from pathlib import Path

import av

from . import config
from .filters import link_dialogue_filter_graph, link_filter_chain


def extract_normalization_mode(text: str, video: Path) -> str:
    """Return the normalization strategy that ``loudnorm`` actually used.

    ``linear=true`` is a request, not a guarantee: FFmpeg falls back to its
    dynamic algorithm when the measured program cannot meet the requested
    targets with a single linear gain.  The filter's summary is authoritative.
    """
    match = re.search(r"Normalization Type:\s*(Linear|Dynamic)", text)
    if match is None:
        raise RuntimeError(f"loudnorm produced no normalization mode for {video}")
    return match.group(1).lower()


def _run_pan_loudnorm_pass(
    video: Path,
    stream_index: int,
    filter_chain: str,
    loudnorm_args: str,
    *,
    dialogue_mode: bool = False,
    true_peak: float = config.LOUDNORM_TP,
):
    """Decodes the given stream through `filter_chain` (a `pan=...` string)
    into `loudnorm`, draining every filtered frame. Returns nothing useful by
    itself — callers either read loudnorm's analysis JSON via a log capture
    (measure pass) or encode the drained frames (apply pass)."""
    with av.open(str(video)) as container:
        stream = next(s for s in container.streams.audio if s.index == stream_index)
        stream.codec_context.thread_count = 0
        stream.codec_context.thread_type = "AUTO"

        graph = av.filter.Graph()
        abuf = graph.add_abuffer(template=stream)
        filter_ctx = link_filter_chain(graph, filter_chain, abuf)
        if dialogue_mode:
            filter_ctx = link_dialogue_filter_graph(
                graph, filter_ctx, true_peak=true_peak
            )
        loud_ctx = graph.add("loudnorm", loudnorm_args)
        sink = graph.add("abuffersink")
        filter_ctx.link_to(loud_ctx)
        loud_ctx.link_to(sink)
        graph.configure()

        for packet in container.demux(stream):
            for frame in packet.decode():
                graph.push(frame)
                _drain(graph)
        graph.push(None)
        _drain(graph)

        del sink, loud_ctx, filter_ctx, abuf, graph


def _drain(graph: av.filter.Graph) -> None:
    while True:
        try:
            graph.pull()
        except av.error.BlockingIOError, av.error.EOFError:
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
    dialogue_mode: bool = False,
) -> dict:
    """Measure the audio emitted by the processing chain before loudnorm.

    With ``dialogue_mode``, this includes the full documented chain: remix,
    center-only compression and makeup, rejoin, and limiting.  Measuring that
    exact signal keeps pass two's supplied stats valid for its render chain.
    """
    loudnorm_args = f"I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json"

    av.logging.set_level(av.logging.INFO)
    av.logging.set_skip_repeated(False)
    with av.logging.Capture(local=True) as logs:
        _run_pan_loudnorm_pass(
            video,
            stream_index,
            filter_chain,
            loudnorm_args,
            dialogue_mode=dialogue_mode,
            true_peak=target_tp,
        )
        text = "".join(msg for _level, _ctx, msg in logs)

    return _extract_json_stats(text, video)


def build_linear_loudnorm_filter(
    stats: dict,
    *,
    target_i: float = config.LOUDNORM_I,
    target_tp: float = config.LOUDNORM_TP,
    target_lra: float = config.LOUDNORM_LRA,
) -> str:
    """Build the two-pass apply filter and request linear normalization.

    FFmpeg can still select dynamic normalization when a linear correction
    cannot satisfy the targets.  ``print_format=summary`` lets the caller
    report the strategy FFmpeg actually selected after rendering.
    """
    return (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
        f":measured_I={stats['input_i']}"
        f":measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}"
        ":linear=true:print_format=summary"
    )
