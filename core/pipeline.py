from pathlib import Path

import av

from . import config
from .filters import get_downmix_filter, link_filter_chain
from .loudness import build_linear_loudnorm_filter, measure_loudness
from .probe import probe_audio_streams, select_source_stream


def _parse_bitrate(bitrate: str) -> int:
    """Converts a CLI-style bitrate string ("448k", "1.5M", "192000") to bits/sec."""
    text = bitrate.strip().lower()
    if text.endswith("k"):
        return int(float(text[:-1]) * 1_000)
    if text.endswith("m"):
        return int(float(text[:-1]) * 1_000_000)
    return int(text)


def _encoder_sample_rate(codec_name: str, preferred_rate: int) -> int:
    """Picks a sample rate the target encoder actually accepts, preferring the
    source's own rate when it's in the encoder's supported list (e.g. eac3
    only accepts 48000/44100/32000)."""
    rates = av.codec.Codec(codec_name, "w").audio_rates
    if not rates or preferred_rate in rates:
        return preferred_rate
    return min(rates, key=lambda r: abs(r - preferred_rate))


def _encoder_sample_format(codec_name: str) -> str:
    formats = av.codec.Codec(codec_name, "w").audio_formats
    return formats[0].name if formats else "fltp"


def _drain(graph: av.filter.Graph, encoder: av.stream.Stream, out_container: av.container.OutputContainer) -> None:
    while True:
        try:
            frame = graph.pull()
        except (av.error.BlockingIOError, av.error.EOFError):
            return
        for packet in encoder.encode(frame):
            out_container.mux(packet)


def process_video(
    video: Path,
    output_dir: Path,
    *,
    preferred_language: str = config.PREFERRED_LANGUAGE,
    target_i: float = config.LOUDNORM_I,
    target_tp: float = config.LOUDNORM_TP,
    target_lra: float = config.LOUDNORM_LRA,
    new_track_codec: str = config.NEW_TRACK_CODEC,
    new_track_bitrate: str = config.NEW_TRACK_BITRATE,
    new_track_title: str = config.NEW_TRACK_TITLE,
    overwrite: bool = False,
) -> str:
    # mkv container: non-mkv subtitle codecs (e.g. mov_text from mp4) will fail
    # the stream-copy remux below and surface as a normal [✘] failure, not silently.
    output_path = output_dir / f"{video.stem}_boosted.mkv"
    temp_path = output_dir / f"{video.stem}_boosted.tmp.mkv"

    if output_path.exists() and not overwrite:
        return f"[✘] Skipped (output exists): {video.name}"

    in_container = None
    out_container = None
    try:
        streams = probe_audio_streams(video)
        if not streams:
            return f"[✘] No audio streams found: {video.name}"

        source = select_source_stream(streams, preferred_language=preferred_language)
        channels = source.get("channels", 0)

        in_container = av.open(str(video))
        out_container = av.open(str(temp_path), mode="w")

        # Always keep every original stream (video, all audio tracks, subs) untouched.
        stream_map = {}
        for stream in in_container.streams:
            out_stream = out_container.add_stream_from_template(stream)
            out_stream.metadata.update(stream.metadata)
            stream_map[stream.index] = out_stream

        graph = None
        new_stream = None
        source_stream = None

        if channels > 2:
            source_stream = next(s for s in in_container.streams.audio if s.index == source["index"])
            filter_chain = get_downmix_filter(source_stream.layout.name if source_stream.layout else "")
            stats = measure_loudness(
                video, source["index"], filter_chain, target_i=target_i, target_tp=target_tp, target_lra=target_lra
            )
            loudnorm_args = build_linear_loudnorm_filter(
                stats, target_i=target_i, target_tp=target_tp, target_lra=target_lra
            ).split("=", 1)[1]

            sample_rate = _encoder_sample_rate(new_track_codec, source_stream.codec_context.sample_rate)
            sample_format = _encoder_sample_format(new_track_codec)

            graph = av.filter.Graph()
            abuf = graph.add_abuffer(template=source_stream)
            pan_ctx = link_filter_chain(graph, filter_chain, abuf)
            loud_ctx = graph.add("loudnorm", loudnorm_args)
            fmt_ctx = graph.add(
                "aformat", f"sample_fmts={sample_format}:sample_rates={sample_rate}:channel_layouts=5.1"
            )
            sink = graph.add("abuffersink")
            pan_ctx.link_to(loud_ctx)
            loud_ctx.link_to(fmt_ctx)
            fmt_ctx.link_to(sink)
            graph.configure()

            new_stream = out_container.add_stream(new_track_codec, rate=sample_rate, layout="5.1")
            new_stream.codec_context.bit_rate = _parse_bitrate(new_track_bitrate)
            new_stream.metadata["title"] = new_track_title
            language = source.get("tags", {}).get("language")
            if language:
                new_stream.metadata["language"] = language

        for packet in in_container.demux(list(in_container.streams)):
            if graph is not None and packet.stream.index == source_stream.index:
                for frame in packet.decode():
                    graph.push(frame)
                    _drain(graph, new_stream, out_container)
            if packet.dts is not None:
                packet.stream = stream_map[packet.stream.index]
                out_container.mux(packet)

        if graph is not None:
            graph.push(None)
            _drain(graph, new_stream, out_container)
            for packet in new_stream.encode(None):
                out_container.mux(packet)

        out_container.close()
        in_container.close()
        temp_path.replace(output_path)  # atomic: no partial file left at the final name on failure
        return f"[✔] Finished: {video.name}"
    except Exception as e:  # noqa: BLE001 — one bad file must not abort the batch (see cli.py)
        # best-effort cleanup after a real failure above: a secondary error
        # closing an already-broken container must not shadow the actual
        # failure being returned, so it's deliberately swallowed here.
        if out_container is not None:
            try:
                out_container.close()
            except Exception:  # noqa: BLE001, S110 — cleanup-only, must not shadow `e`
                pass
        if in_container is not None:
            try:
                in_container.close()
            except Exception:  # noqa: BLE001, S110 — cleanup-only, must not shadow `e`
                pass
        temp_path.unlink(missing_ok=True)
        return f"[✘] Failed: {video.name}: {e}"
