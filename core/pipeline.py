import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import av

from . import config
from .filters import (
    dialogue_settings,
    get_boost_filter,
    get_dialogue_remix_filter,
    link_dialogue_filter_graph,
    link_filter_chain,
)
from .loudness import (
    build_linear_loudnorm_filter,
    extract_normalization_mode,
    measure_loudness,
)
from .probe import probe_audio_streams, select_source_stream

# Maximum standard bitrates for lossy surround encoders
MAX_CODEC_BITRATES = {
    "ac3": 640_000,
    "eac3": 1_024_000,
    "aac": 768_000,
}


class ProcessStatus(StrEnum):
    FINISHED = "finished"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessError:
    """A recoverable per-file error, safe for callers to inspect programmatically."""

    kind: str
    message: str


@dataclass(frozen=True)
class ProcessResult:
    """Machine-readable outcome of processing one input video."""

    status: ProcessStatus
    video: Path
    elapsed_seconds: float = 0.0
    output_path: Path | None = None
    error: ProcessError | None = None
    loudnorm_mode: str | None = None

    @property
    def failed(self) -> bool:
        return self.status is ProcessStatus.FAILED

    def __str__(self) -> str:
        if self.status is ProcessStatus.FINISHED:
            return f"[✔] Finished: {self.video.name} ({self.elapsed_seconds:.2f}s)"
        if self.status is ProcessStatus.SKIPPED:
            return f"[✘] Skipped ({self.error.message}): {self.video.name}"
        return f"[✘] Failed: {self.video.name}: {self.error.message}"


def output_path_for(video: Path, output_dir: Path) -> Path:
    """Return a collision-proof derived-track filename for one input file."""
    return output_dir / f"{video.stem}_{video.suffix[1:].lower()}_boosted.mkv"


def _parse_bitrate(bitrate: str) -> int:
    """Converts a CLI-style bitrate string ("448k", "1.5M", "192000") to bits/sec."""
    text = bitrate.strip().lower()
    if text.endswith("k"):
        return int(float(text[:-1]) * 1_000)
    if text.endswith("m"):
        return int(float(text[:-1]) * 1_000_000)
    return int(text)


def _format_bitrate(bitrate: int) -> str:
    """Formats a bitrate integer into a human-readable string."""
    if not bitrate or bitrate <= 0:
        return "Lossless / VBR"
    if bitrate >= 1_000_000:
        return f"{bitrate / 1_000_000:.2f} Mbps"
    return f"{bitrate // 1_000} kbps"


def _encoder_sample_rate(codec_name: str, preferred_rate: int) -> int:
    """Picks a sample rate the target encoder actually accepts, preferring the
    source's own rate when supported."""
    rates = av.codec.Codec(codec_name, "w").audio_rates
    if not rates or preferred_rate in rates:
        return preferred_rate
    return min(rates, key=lambda r: abs(r - preferred_rate))


def _encoder_sample_format(codec_name: str) -> str:
    formats = av.codec.Codec(codec_name, "w").audio_formats
    return formats[0].name if formats else "fltp"


def _is_source_lossless(source_stream: av.stream.Stream) -> bool:
    """Detects whether the source stream is mathematically lossless."""
    codec_name = (source_stream.codec_context.name or "").lower()
    profile = (source_stream.profile or "").upper()
    return (
        codec_name in config.LOSSLESS_CODECS
        or codec_name.startswith("pcm_")
        or (codec_name == "dts" and "MA" in profile)
    )


def _resolve_codec_params(
    source_stream: av.stream.Stream,
    target_codec: str,
    target_bitrate: str | None,
    target_sample_rate: int,
) -> tuple[str, int, int, str, str]:
    """Resolve encoder settings while honoring the caller's codec exactly."""
    codec_context = source_stream.codec_context
    src_codec = (codec_context.name or "").lower()
    target_codec = target_codec.lower()

    if target_codec == "flac":
        sample_rate = _encoder_sample_rate(target_codec, target_sample_rate)
        sample_format = _encoder_sample_format(target_codec)
        return (
            target_codec,
            sample_rate,
            0,
            sample_format,
            "Explicit FLAC output (lossless processed PCM)",
        )

    sample_rate = _encoder_sample_rate(target_codec, target_sample_rate)
    sample_format = _encoder_sample_format(target_codec)
    if target_bitrate is None:
        raise ValueError(f"A bitrate is required for lossy codec '{target_codec}'")
    bitrate = _parse_bitrate(target_bitrate)
    max_allowed = MAX_CODEC_BITRATES.get(target_codec)
    if max_allowed is not None and bitrate > max_allowed:
        raise ValueError(
            f"Bitrate {_format_bitrate(bitrate)} exceeds {target_codec}'s "
            f"supported maximum of {_format_bitrate(max_allowed)}"
        )
    reason = f"{target_codec} output from {src_codec} @ {_format_bitrate(bitrate)}"

    return target_codec, sample_rate, bitrate, sample_format, reason


def _drain(
    graph: av.filter.Graph,
    encoder: av.stream.Stream,
    out_container: av.container.OutputContainer,
) -> None:
    while True:
        try:
            frame = graph.pull()
        except av.error.BlockingIOError, av.error.EOFError:
            return
        for packet in encoder.encode(frame):
            out_container.mux(packet)


def _copy_container_metadata(
    in_container: av.container.InputContainer,
    out_container: av.container.OutputContainer,
) -> None:
    """Copy container-level tags that stream templating deliberately omits."""
    out_container.metadata.update(in_container.metadata)


def _copy_stream_properties(
    source: av.stream.Stream, destination: av.stream.Stream
) -> None:
    """Copy remuxed-stream properties not retained by PyAV's stream template.

    In particular, a track's disposition determines which original stream is
    selected by default in a player.  Preserve it exactly for original streams;
    the derived track is configured separately below.
    """
    destination.metadata.update(source.metadata)
    destination.disposition = source.disposition


def process_video(
    video: Path,
    output_dir: Path,
    *,
    preferred_language: str = config.PREFERRED_LANGUAGE,
    target_i: float = config.LOUDNORM_I,
    target_tp: float = config.LOUDNORM_TP,
    target_lra: float = config.LOUDNORM_LRA,
    profile: str = config.DEFAULT_PROFILE,
    new_track_codec: str | None = None,
    new_track_bitrate: str | None = None,
    new_track_title: str = config.NEW_TRACK_TITLE,
    overwrite: bool = False,
    source_track: int | None = None,
    prefer_5_1: bool = False,
    allow_stereo: bool = False,
    processing_mode: str = config.DEFAULT_PROCESSING_MODE,
) -> ProcessResult:
    start_time = time.perf_counter()

    output_path = output_path_for(video, output_dir)
    temp_path = output_dir / f".{output_path.stem}.{uuid4().hex}.tmp.mkv"

    if output_path.exists() and not overwrite:
        return ProcessResult(
            ProcessStatus.SKIPPED,
            video,
            output_path=output_path,
            error=ProcessError("output_exists", "output exists"),
        )

    print(f"\n[▶] Processing file: {video.name}")

    in_container = None
    out_container = None
    log_capture = None
    try:
        try:
            profile_defaults = config.OUTPUT_PROFILES[profile]
        except KeyError as exc:
            available = ", ".join(config.OUTPUT_PROFILES)
            raise ValueError(
                f"Unknown profile '{profile}'; choose one of: {available}"
            ) from exc
        if processing_mode not in config.PROCESSING_MODES:
            available = ", ".join(config.PROCESSING_MODES)
            raise ValueError(
                f"Unknown processing mode '{processing_mode}'; choose one of: {available}"
            )
        target_codec = new_track_codec or profile_defaults.codec
        target_bitrate = (
            new_track_bitrate
            if new_track_bitrate is not None
            else profile_defaults.bitrate
        )
        streams = probe_audio_streams(video)
        if not streams:
            return ProcessResult(
                ProcessStatus.FAILED,
                video,
                error=ProcessError("no_audio_streams", "No audio streams found"),
            )

        source = select_source_stream(
            streams,
            preferred_language=preferred_language,
            source_track=source_track,
            prefer_5_1=prefer_5_1,
            allow_stereo=allow_stereo,
        )
        channels = source.get("channels", 0)
        lang = source.get("tags", {}).get("language", "und")

        print(
            f"    ├─ Selected Source Track: Stream #{source['index']} "
            f"({source['codec_name']}, {channels} ch, layout: '{source['channel_layout']}', lang: '{lang}')"
        )

        in_container = av.open(str(video))
        out_container = av.open(str(temp_path), mode="w")
        _copy_container_metadata(in_container, out_container)

        # Keep every original stream (video, audio, subtitles, attachments)
        # untouched, including its tags and player-selection disposition.
        stream_map = {}
        for stream in in_container.streams:
            out_stream = out_container.add_stream_from_template(stream)
            _copy_stream_properties(stream, out_stream)
            stream_map[stream.index] = out_stream

        graph = None
        new_stream = None
        source_stream = None

        if channels > 2:
            source_stream = next(
                s for s in in_container.streams.audio if s.index == source["index"]
            )

            # Enable multi-threaded decoding
            source_stream.codec_context.thread_count = 0
            source_stream.codec_context.thread_type = "AUTO"

            layout = source_stream.layout.name if source_stream.layout else ""
            loudnorm_args = None
            dialogue_mode = processing_mode == "dialogue"
            if processing_mode == "precise":
                # Precise mode deliberately measures and renders the same
                # dialogue chain before adding loudnorm as the final stage.
                dialogue_mode = True
                filter_chain = get_dialogue_remix_filter(layout)
                print(f"    ├─ Dialogue Remix Filter: {filter_chain}")
                print(f"    ├─ Center compression: {dialogue_settings()}")
                print(f"    ├─ Pre-normalization limiter ceiling: {target_tp} dBTP")
                print("    ├─ Measuring audio loudness (Pass 1)...")

                stats = measure_loudness(
                    video,
                    source["index"],
                    filter_chain,
                    target_i=target_i,
                    target_tp=target_tp,
                    target_lra=target_lra,
                    dialogue_mode=True,
                )

                print(
                    f"    │  └─ Measured Stats: Input I={stats.get('input_i')} LUFS | "
                    f"TP={stats.get('input_tp')} dBTP | LRA={stats.get('input_lra')} LU | "
                    f"Offset={stats.get('target_offset')}"
                )
                loudnorm_args = build_linear_loudnorm_filter(
                    stats, target_i=target_i, target_tp=target_tp, target_lra=target_lra
                ).split("=", 1)[1]
                print(
                    "    ├─ Processing mode: precise "
                    "(Pass 2 dialogue chain → two-pass loudnorm)"
                )
            elif processing_mode == "boost":
                filter_chain = get_boost_filter(layout, true_peak=target_tp)
                print(f"    ├─ Boost Filter: {filter_chain}")
                print(
                    f"    ├─ Processing mode: boost (one pass, ceiling {target_tp} dBTP)"
                )
            else:
                filter_chain = get_dialogue_remix_filter(layout)
                print(
                    "    ├─ Processing mode: dialogue (one pass, full 5.1 bed preserved)"
                )
                print(f"    │  ├─ Center compression: {dialogue_settings()}")
                print(f"    │  └─ Final limiter ceiling: {target_tp} dBTP")

            # Resolve output encoder options
            (
                encoder_codec,
                sample_rate,
                bitrate,
                sample_format,
                decision_reason,
            ) = _resolve_codec_params(
                source_stream,
                target_codec,
                target_bitrate,
                profile_defaults.sample_rate,
            )

            print("    ├─ Output Audio Track Specs:")
            print(f"    │  ├─ Strategy: {decision_reason}")
            print(
                f"    │  ├─ Encoder: {encoder_codec} ({sample_format}, {sample_rate} Hz)"
            )
            print(f"    │  └─ Bitrate: {_format_bitrate(bitrate)}")

            log_capture = None
            logs = None
            if loudnorm_args is not None:
                av.logging.set_level(av.logging.INFO)
                av.logging.set_skip_repeated(False)
                log_capture = av.logging.Capture(local=True)
                logs = log_capture.__enter__()

            graph = av.filter.Graph()
            abuf = graph.add_abuffer(template=source_stream)
            filter_ctx = link_filter_chain(graph, filter_chain, abuf)
            if dialogue_mode:
                filter_ctx = link_dialogue_filter_graph(
                    graph, filter_ctx, true_peak=target_tp
                )
            fmt_ctx = graph.add(
                "aformat",
                f"sample_fmts={sample_format}:sample_rates={sample_rate}:channel_layouts=5.1",
            )
            sink = graph.add("abuffersink")
            if loudnorm_args is not None:
                loud_ctx = graph.add("loudnorm", loudnorm_args)
                filter_ctx.link_to(loud_ctx)
                loud_ctx.link_to(fmt_ctx)
            else:
                filter_ctx.link_to(fmt_ctx)
            fmt_ctx.link_to(sink)
            graph.configure()

            new_stream = out_container.add_stream(
                encoder_codec, rate=sample_rate, layout="5.1"
            )
            # The derived track is selectable but must not replace the user's
            # existing default (for example, an original Atmos track).
            new_stream.disposition = 0
            if bitrate > 0:
                new_stream.codec_context.bit_rate = bitrate
            new_stream.metadata["title"] = new_track_title
            if lang != "und":
                new_stream.metadata["language"] = lang

            # Enable multi-threaded encoding if supported
            new_stream.codec_context.thread_count = 0
            new_stream.codec_context.thread_type = "AUTO"

        if channels <= 2:
            raise RuntimeError("Stereo/mono source processing is not implemented")

        # Demuxing and remuxing loop
        print("    ├─ Encoding and muxing container (Pass 2)...")
        source_idx = source_stream.index if source_stream else -1
        for packet in in_container.demux():
            if packet.dts is None:
                continue

            if graph is not None and packet.stream.index == source_idx:
                for frame in packet.decode():
                    graph.push(frame)
                _drain(graph, new_stream, out_container)

            packet.stream = stream_map[packet.stream.index]
            out_container.mux(packet)

        if graph is not None:
            graph.push(None)
            _drain(graph, new_stream, out_container)
            for packet in new_stream.encode(None):
                out_container.mux(packet)

        loudnorm_mode = None
        if log_capture is not None:
            # loudnorm emits its summary while its filter graph is torn down.
            # Drop every PyAV reference before leaving the capture context.
            graph = None
            filter_ctx = None
            loud_ctx = None
            fmt_ctx = None
            sink = None
            abuf = None
            log_capture.__exit__(None, None, None)
            log_capture = None
            loudnorm_mode = extract_normalization_mode(
                "".join(msg for _level, _ctx, msg in logs), video
            )
            print(f"    ├─ Loudnorm normalization used: {loudnorm_mode}")

        out_container.close()
        in_container.close()
        temp_path.replace(output_path)

        elapsed = time.perf_counter() - start_time
        print(f"    └─ [✔] Successfully finished in {elapsed:.2f}s")
        return ProcessResult(
            ProcessStatus.FINISHED,
            video,
            elapsed,
            output_path=output_path,
            loudnorm_mode=loudnorm_mode,
        )

    except Exception as e:  # noqa: BLE001
        if log_capture is not None:
            log_capture.__exit__(None, None, None)
        if out_container is not None:
            try:
                out_container.close()
            except Exception:  # noqa: BLE001, S110
                pass
        if in_container is not None:
            try:
                in_container.close()
            except Exception:  # noqa: BLE001, S110
                pass
        temp_path.unlink(missing_ok=True)
        elapsed = time.perf_counter() - start_time
        print(f"    └─ [✘] Failed after {elapsed:.2f}s: {e}")
        return ProcessResult(
            ProcessStatus.FAILED,
            video,
            elapsed,
            error=ProcessError(type(e).__name__, str(e)),
        )
