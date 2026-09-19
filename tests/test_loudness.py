from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from conftest import requires_ffmpeg

from core.loudness import (
    _extract_json_stats,
    build_linear_loudnorm_filter,
    extract_normalization_mode,
    measure_loudness,
)


def test_build_linear_loudnorm_filter_maps_measure_keys_to_apply_keys():
    stats = {
        "input_i": "-20.0",
        "input_tp": "-3.0",
        "input_lra": "5.0",
        "input_thresh": "-30.0",
        "target_offset": "1.0",
    }
    result = build_linear_loudnorm_filter(
        stats, target_i=-16.0, target_tp=-1.5, target_lra=11.0
    )
    assert "measured_I=-20.0" in result
    assert "measured_TP=-3.0" in result
    assert "measured_LRA=5.0" in result
    assert "measured_thresh=-30.0" in result
    assert "offset=1.0" in result
    assert "linear=true" in result
    assert "print_format=summary" in result


def test_extract_normalization_mode_reports_ffmpegs_actual_strategy():
    assert (
        extract_normalization_mode("Normalization Type:   Dynamic\n", "video.mkv")
        == "dynamic"
    )


def test_extract_normalization_mode_rejects_an_incomplete_summary():
    with pytest.raises(RuntimeError, match="no normalization mode"):
        extract_normalization_mode("Input Integrated: -20.0 LUFS", "video.mkv")


def test_extract_json_stats_parses_json_block_from_log_text():
    text = 'some ffmpeg noise\n{"input_i": "-20.0", "input_tp": "-3.0"}\nmore noise'
    assert _extract_json_stats(text, "video.mkv") == {
        "input_i": "-20.0",
        "input_tp": "-3.0",
    }


def test_extract_json_stats_raises_clear_error_when_no_json_present():
    text = "ffmpeg produced no loudnorm output at all"
    with pytest.raises(RuntimeError, match="no measurement output"):
        _extract_json_stats(text, "video.mkv")


def test_measure_loudness_serializes_its_global_ffmpeg_log_capture(monkeypatch):
    active = 0
    maximum_active = 0
    state_lock = Lock()

    class FakeCapture:
        def __enter__(self):
            return [(0, "loudnorm", '{"input_i": "-20.0"}')]

        def __exit__(self, *_):
            return False

    def fake_pass(*_, **__):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        # Give the other worker a chance to enter if capture is not locked.
        Event().wait(0.05)
        with state_lock:
            active -= 1

    monkeypatch.setattr("core.loudness.av.logging.Capture", lambda **_: FakeCapture())
    monkeypatch.setattr("core.loudness._run_pan_loudnorm_pass", fake_pass)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: measure_loudness("video.mkv", 0, "anull"), range(2))
        )

    assert maximum_active == 1
    assert results == [{"input_i": "-20.0"}, {"input_i": "-20.0"}]


@requires_ffmpeg
def test_measure_loudness_returns_stats_for_a_real_surround_clip(surround_clip):
    stats = measure_loudness(
        surround_clip, 1, "pan=5.1|FL=FL|FR=FR|FC=1.25*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR"
    )
    assert "input_i" in stats
    assert "target_offset" in stats
