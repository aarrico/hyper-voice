import subprocess
from unittest.mock import patch

import pytest

from core.loudness import build_linear_loudnorm_filter, measure_loudness


def test_build_linear_loudnorm_filter_maps_measure_keys_to_apply_keys():
    stats = {
        "input_i": "-20.0",
        "input_tp": "-3.0",
        "input_lra": "5.0",
        "input_thresh": "-30.0",
        "target_offset": "1.0",
    }
    result = build_linear_loudnorm_filter(stats, target_i=-16.0, target_tp=-1.5, target_lra=11.0)
    assert "measured_I=-20.0" in result
    assert "measured_TP=-3.0" in result
    assert "measured_LRA=5.0" in result
    assert "measured_thresh=-30.0" in result
    assert "offset=1.0" in result
    assert "linear=true" in result


def _fake_completed(stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=stderr)


def test_measure_loudness_parses_json_block_from_stderr():
    stderr = 'some ffmpeg noise\n{"input_i": "-20.0", "input_tp": "-3.0"}\nmore noise'
    with patch("subprocess.run", return_value=_fake_completed(stderr)):
        stats = measure_loudness("video.mkv", 0, "anull")
    assert stats == {"input_i": "-20.0", "input_tp": "-3.0"}


def test_measure_loudness_raises_clear_error_when_no_json_present():
    stderr = "ffmpeg produced no loudnorm output at all"
    with patch("subprocess.run", return_value=_fake_completed(stderr)):
        with pytest.raises(RuntimeError, match="no measurement output"):
            measure_loudness("video.mkv", 0, "anull")
