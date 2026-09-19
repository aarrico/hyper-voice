import shutil
import subprocess

import pytest

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not found on PATH",
)


def _make_clip(path, *, channel_layout: str, pan_expr: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=5:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-filter_complex",
            f"[1:a]pan={channel_layout}|{pan_expr}[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_distinct_channel_clip(path) -> None:
    """Create a 5.1 fixture whose standard-position channels have unique tones."""
    frequencies = (300, 400, 500, 100, 600, 700)
    expressions = "|".join(f"0.08*sin(2*PI*{frequency}*t)" for frequency in frequencies)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=5:duration=1",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={expressions}:c=5.1:s=48000:d=1",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def surround_clip(tmp_path):
    """A tiny synthetic 5.1 clip (1s, mono sine spread across all 6 channels)."""
    path = tmp_path / "surround.mkv"
    _make_clip(
        path, channel_layout="5.1", pan_expr="FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0"
    )
    return path


@pytest.fixture
def distinct_channel_surround_clip(tmp_path):
    """A 5.1 clip with tones for FL, FR, FC, LFE, BL, and BR respectively."""
    path = tmp_path / "distinct-surround.mkv"
    _make_distinct_channel_clip(path)
    return path


@pytest.fixture
def tagged_surround_clip(tmp_path):
    """A surround fixture with tags and a default audio disposition."""
    path = tmp_path / "tagged-surround.mkv"
    _make_clip(
        path, channel_layout="5.1", pan_expr="FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-map",
            "0",
            "-c",
            "copy",
            "-metadata",
            "title=Fixture container title",
            "-metadata:s:a:0",
            "title=Original surround track",
            "-metadata:s:a:0",
            "language=eng",
            "-disposition:a:0",
            "default",
            str(tmp_path / "tagged-output.mkv"),
        ],
        check=True,
        capture_output=True,
    )
    return tmp_path / "tagged-output.mkv"


@pytest.fixture
def stereo_clip(tmp_path):
    """A tiny synthetic stereo clip (1s, mono sine duplicated to both channels)."""
    path = tmp_path / "stereo.mkv"
    _make_clip(path, channel_layout="stereo", pan_expr="FL=c0|FR=c0")
    return path
