import subprocess
from pathlib import Path

from . import config
from .filters import get_downmix_filter
from .loudness import build_linear_loudnorm_filter, measure_loudness
from .probe import probe_audio_streams, select_source_stream


def process_video(
    video: Path,
    output_dir: Path,
    *,
    ffmpeg_path: str = config.FFMPEG_PATH,
    ffprobe_path: str = config.FFPROBE_PATH,
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
    # the -c copy mux below and surface as a normal [✘] failure, not silently.
    output_path = output_dir / f"{video.stem}_boosted.mkv"
    temp_path = output_dir / f"{video.stem}_boosted.tmp.mkv"

    if output_path.exists() and not overwrite:
        return f"[✘] Skipped (output exists): {video.name}"

    try:
        streams = probe_audio_streams(video, ffprobe_path=ffprobe_path)

        if not streams:
            return f"[✘] No audio streams found: {video.name}"

        source = select_source_stream(streams, preferred_language=preferred_language)
        channels = source.get("channels", 0)

        # Always keep every original stream (video, all audio tracks, subs) untouched.
        cmd = [ffmpeg_path, "-y", "-i", str(video), "-map", "0", "-c", "copy"]

        if channels > 2:
            filter_chain = get_downmix_filter(source.get("channel_layout", ""))
            stats = measure_loudness(
                video,
                source["index"],
                filter_chain,
                ffmpeg_path=ffmpeg_path,
                target_i=target_i,
                target_tp=target_tp,
                target_lra=target_lra,
            )
            final_filter = (
                f"{filter_chain},"
                f"{build_linear_loudnorm_filter(stats, target_i=target_i, target_tp=target_tp, target_lra=target_lra)}"
            )
            new_track = len(streams)  # appended after the existing audio streams

            cmd += [
                "-map",
                f"0:{source['index']}",
                f"-filter:a:{new_track}",
                final_filter,
                f"-c:a:{new_track}",
                new_track_codec,
                f"-b:a:{new_track}",
                new_track_bitrate,
                f"-metadata:s:a:{new_track}",
                f"title={new_track_title}",
            ]
            language = source.get("tags", {}).get("language")
            if language:
                cmd += [f"-metadata:s:a:{new_track}", f"language={language}"]

        cmd.append(str(temp_path))

        subprocess.run(cmd, check=True, capture_output=True, text=True)
        temp_path.replace(output_path)  # atomic: no partial file left at the final name on failure
        return f"[✔] Finished: {video.name}"
    except subprocess.CalledProcessError as e:
        temp_path.unlink(missing_ok=True)
        detail = e.stderr.strip().splitlines()[-1] if e.stderr else ""
        return f"[✘] Failed: {video.name}: {detail}"
    except FileNotFoundError:
        temp_path.unlink(missing_ok=True)
        return "[✘] Error: FFmpeg executable not found."
    except RuntimeError as e:
        temp_path.unlink(missing_ok=True)
        return f"[✘] Failed: {video.name}: {e}"
