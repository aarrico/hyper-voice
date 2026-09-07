import pytest

from core.loudness import _extract_json_stats, build_linear_loudnorm_filter, measure_loudness

from conftest import requires_ffmpeg


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


def test_extract_json_stats_parses_json_block_from_log_text():
    text = 'some ffmpeg noise\n{"input_i": "-20.0", "input_tp": "-3.0"}\nmore noise'
    assert _extract_json_stats(text, "video.mkv") == {"input_i": "-20.0", "input_tp": "-3.0"}


def test_extract_json_stats_raises_clear_error_when_no_json_present():
    text = "ffmpeg produced no loudnorm output at all"
    with pytest.raises(RuntimeError, match="no measurement output"):
        _extract_json_stats(text, "video.mkv")


@requires_ffmpeg
def test_measure_loudness_returns_stats_for_a_real_surround_clip(surround_clip):
    stats = measure_loudness(surround_clip, 1, "pan=5.1|FL=FL|FR=FR|FC=1.25*FC|LFE=LFE|BL=0.85*BL|BR=0.85*BR")
    assert "input_i" in stats
    assert "target_offset" in stats
