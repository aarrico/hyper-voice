import pytest

from core.filters import (
    CENTER_BOOST,
    DIALOGUE_REMIX_TO_5_1,
    DOWNMIX_TO_5_1,
    dialogue_settings,
    get_boost_filter,
    get_dialogue_remix_filter,
    get_downmix_filter,
)


def test_get_downmix_filter_returns_mapped_layout():
    assert get_downmix_filter("5.1") == DOWNMIX_TO_5_1["5.1"]


def test_get_downmix_filter_falls_back_for_unmapped_layout():
    result = get_downmix_filter("quad")
    assert result == f"aformat=channel_layouts=5.1,{CENTER_BOOST}"


def test_get_boost_filter_adds_a_limiter_at_the_requested_ceiling():
    result = get_boost_filter("5.1", true_peak=-1.5)
    assert result.startswith(f"{DOWNMIX_TO_5_1['5.1']},")
    assert result.endswith("alimiter=limit=0.841395:level=false")


def test_get_boost_filter_rejects_an_unsupported_limiter_ceiling():
    with pytest.raises(ValueError, match="true_peak"):
        get_boost_filter("5.1", true_peak=1.0)


def test_dialogue_preset_is_conservative_and_described_for_listening_review():
    settings = dialogue_settings()
    assert "ratio=2:1" in settings
    assert "makeup=1.15x" in settings


def test_dialogue_remix_does_not_apply_the_boost_mode_static_center_gain():
    remix = get_dialogue_remix_filter("5.1")
    assert remix == DIALOGUE_REMIX_TO_5_1["5.1"]
    assert "FC=FC" in remix
    assert "1.3*FC" not in remix
