from core.filters import CENTER_BOOST, DOWNMIX_TO_5_1, get_downmix_filter


def test_get_downmix_filter_returns_mapped_layout():
    assert get_downmix_filter("5.1") == DOWNMIX_TO_5_1["5.1"]


def test_get_downmix_filter_falls_back_for_unmapped_layout():
    result = get_downmix_filter("quad")
    assert result == f"aformat=channel_layouts=5.1,{CENTER_BOOST}"
