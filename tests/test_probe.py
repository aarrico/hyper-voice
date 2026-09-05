from core.probe import _codec_tier, _is_commentary, language_aliases, select_source_stream


def test_is_commentary_matches_keyword_in_title():
    assert _is_commentary({"tags": {"title": "Director's Commentary"}})


def test_is_commentary_false_when_no_keyword():
    assert not _is_commentary({"tags": {"title": "English 5.1"}})


def test_is_commentary_false_when_no_tags():
    assert not _is_commentary({})


def test_codec_tier_ranks_lossless_above_lossy():
    lossless = {"codec_name": "truehd"}
    lossy = {"codec_name": "ac3"}
    assert _codec_tier(lossless) > _codec_tier(lossy)


def test_codec_tier_ranks_pcm_as_lossless():
    assert _codec_tier({"codec_name": "pcm_s16le"}) == 2


def test_codec_tier_ranks_dts_ma_as_lossless():
    assert _codec_tier({"codec_name": "dts", "profile": "DTS-HD MA"}) == 2


def test_codec_tier_ranks_plain_dts_as_lossy():
    assert _codec_tier({"codec_name": "dts", "profile": "DTS"}) == 1


def test_language_aliases_covers_iso_639_1_and_2():
    aliases = language_aliases("eng")
    assert "eng" in aliases
    assert "en" in aliases


def test_language_aliases_unknown_code_matches_only_itself():
    assert language_aliases("xyz") == {"xyz"}


def test_select_source_stream_prefers_preferred_language():
    streams = [
        {"index": 0, "codec_name": "ac3", "channels": 6, "tags": {"language": "fre"}},
        {"index": 1, "codec_name": "ac3", "channels": 6, "tags": {"language": "eng"}},
    ]
    assert select_source_stream(streams, preferred_language="eng")["index"] == 1


def test_select_source_stream_falls_back_when_no_language_match():
    streams = [
        {"index": 0, "codec_name": "truehd", "channels": 8, "tags": {"language": "jpn"}},
    ]
    assert select_source_stream(streams, preferred_language="eng")["index"] == 0


def test_select_source_stream_excludes_commentary_unless_all_are_commentary():
    streams = [
        {"index": 0, "codec_name": "ac3", "channels": 6, "tags": {"title": "Commentary", "language": "eng"}},
        {"index": 1, "codec_name": "ac3", "channels": 6, "tags": {"language": "eng"}},
    ]
    assert select_source_stream(streams)["index"] == 1


def test_select_source_stream_keeps_commentary_when_it_is_the_only_option():
    streams = [
        {"index": 0, "codec_name": "ac3", "channels": 6, "tags": {"title": "Commentary", "language": "eng"}},
    ]
    assert select_source_stream(streams)["index"] == 0


def test_select_source_stream_ranks_by_codec_tier_then_channels():
    streams = [
        {"index": 0, "codec_name": "ac3", "channels": 8, "tags": {"language": "eng"}},
        {"index": 1, "codec_name": "truehd", "channels": 6, "tags": {"language": "eng"}},
    ]
    assert select_source_stream(streams)["index"] == 1
