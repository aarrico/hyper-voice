from array import array
from concurrent.futures import ThreadPoolExecutor

import av
import pytest
from conftest import requires_ffmpeg

from core.pipeline import ProcessStatus, output_path_for, process_video
from core.probe import probe_audio_streams


@requires_ffmpeg
def test_process_video_adds_boosted_track_for_surround_source(surround_clip, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(surround_clip, output_dir)

    assert result.status is ProcessStatus.FINISHED
    output_path = output_dir / f"{surround_clip.stem}_mkv_boosted.mkv"
    assert output_path.exists()

    original_streams = probe_audio_streams(surround_clip)
    boosted_streams = probe_audio_streams(output_path)
    assert len(boosted_streams) == len(original_streams) + 1
    assert boosted_streams[-1]["codec_name"] == "eac3"


@requires_ffmpeg
def test_boost_mode_skips_loudness_analysis(surround_clip, tmp_path, monkeypatch):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    def analysis_must_not_run(*args, **kwargs):
        raise AssertionError("boost mode must not run loudness analysis")

    monkeypatch.setattr("core.pipeline.measure_loudness", analysis_must_not_run)
    result = process_video(surround_clip, output_dir, processing_mode="boost")

    assert result.status is ProcessStatus.FINISHED
    assert result.output_path is not None
    with av.open(str(result.output_path)) as container:
        assert len(container.streams.audio) == 2


@requires_ffmpeg
def test_precise_mode_reports_the_loudnorm_strategy(surround_clip, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(surround_clip, output_dir, processing_mode="precise")

    assert result.status is ProcessStatus.FINISHED
    assert result.loudnorm_mode in {"linear", "dynamic"}


@requires_ffmpeg
def test_concurrent_precise_renders_keep_their_loudnorm_measurements(
    surround_clip, tagged_surround_clip, tmp_path
):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda video: process_video(
                    video, output_dir, processing_mode="precise"
                ),
                (surround_clip, tagged_surround_clip),
            )
        )

    assert all(result.status is ProcessStatus.FINISHED for result in results)
    assert {result.loudnorm_mode for result in results} <= {"linear", "dynamic"}


@requires_ffmpeg
def test_dialogue_mode_preserves_a_signal_in_every_5_1_bed_channel(
    surround_clip, tmp_path
):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(
        surround_clip,
        output_dir,
        processing_mode="dialogue",
        new_track_codec="flac",
    )

    assert result.status is ProcessStatus.FINISHED
    assert result.output_path is not None
    with av.open(str(result.output_path)) as container:
        enhanced = container.streams.audio[-1]
        assert enhanced.layout.name == "5.1"
        frames = list(container.decode(enhanced))

    # The fixture supplies a tone to every source channel.  A dialogue graph
    # must retain a complete bed, not leave only the center/voice path.
    channel_has_signal = [False] * 6
    for frame in frames:
        # FLAC decodes to packed signed 16-bit PCM.  Inspect each interleaved
        # channel without adding NumPy as an application dependency.
        assert frame.format.name == "s16"
        samples = array("h", bytes(frame.planes[0]))[: frame.samples * 6]
        for channel in range(6):
            channel_has_signal[channel] |= any(
                abs(sample) > 100 for sample in samples[channel::6]
            )
    assert all(channel_has_signal)


@requires_ffmpeg
def test_boost_mode_preserves_standard_5_1_channel_routing(
    distinct_channel_surround_clip, tmp_path
):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(
        distinct_channel_surround_clip,
        output_dir,
        processing_mode="boost",
        new_track_codec="flac",
    )

    assert result.status is ProcessStatus.FINISHED
    assert result.output_path is not None
    with av.open(str(result.output_path)) as container:
        enhanced = container.streams.audio[-1]
        frames = list(container.decode(enhanced))

    samples_by_channel = [[] for _ in range(6)]
    for frame in frames:
        assert frame.format.name == "s16"
        samples = array("h", bytes(frame.planes[0]))[: frame.samples * 6]
        for channel in range(6):
            samples_by_channel[channel].extend(samples[channel::6])

    def zero_crossing_frequency(samples):
        crossings = sum(
            (before <= 0 < after) or (before >= 0 > after)
            for before, after in zip(samples, samples[1:])
        )
        return crossings * 48_000 / (2 * len(samples))

    expected_frequencies = (300, 400, 500, 100, 600, 700)
    for samples, expected in zip(samples_by_channel, expected_frequencies, strict=True):
        assert zero_crossing_frequency(samples) == pytest.approx(expected, abs=6)


@requires_ffmpeg
def test_process_video_preserves_original_metadata_and_disposition(
    tagged_surround_clip, tmp_path
):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(tagged_surround_clip, output_dir)

    assert result.status is ProcessStatus.FINISHED
    assert result.output_path is not None
    with av.open(str(result.output_path)) as container:
        assert container.metadata["title"] == "Fixture container title"
        original, enhanced = container.streams.audio
        assert original.metadata["title"] == "Original surround track"
        assert original.metadata["language"] == "eng"
        assert original.disposition == 1
        assert enhanced.disposition == 0


@requires_ffmpeg
def test_process_video_rejects_stereo_source_by_default(stereo_clip, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(stereo_clip, output_dir)

    assert result.status is ProcessStatus.FAILED
    assert result.error is not None
    assert result.error.kind == "SourceSelectionError"
    assert not list(output_dir.iterdir())


@requires_ffmpeg
def test_process_video_skips_when_output_exists_and_overwrite_false(
    surround_clip, tmp_path
):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    output_path = output_dir / f"{surround_clip.stem}_mkv_boosted.mkv"
    output_path.write_bytes(b"placeholder")

    result = process_video(surround_clip, output_dir, overwrite=False)

    assert result.status is ProcessStatus.SKIPPED
    assert result.error is not None
    assert result.error.kind == "output_exists"
    assert output_path.read_bytes() == b"placeholder"


@requires_ffmpeg
def test_process_video_no_partial_output_left_on_ffmpeg_failure(
    surround_clip, tmp_path
):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(
        surround_clip, output_dir, new_track_codec="not_a_real_codec"
    )

    assert result.status is ProcessStatus.FAILED
    output_path = output_dir / f"{surround_clip.stem}_mkv_boosted.mkv"
    assert not output_path.exists()
    assert not list(output_dir.iterdir())


def test_output_paths_are_distinct_for_identical_stems_with_different_suffixes(
    tmp_path,
):
    output_dir = tmp_path / "out"
    assert output_path_for(tmp_path / "Movie.mkv", output_dir) != output_path_for(
        tmp_path / "Movie.mp4", output_dir
    )


def test_compatible_profile_is_the_default_and_archival_is_flac():
    from core import config

    assert config.DEFAULT_PROFILE == "compatible"
    assert config.OUTPUT_PROFILES["compatible"].codec == "eac3"
    assert config.OUTPUT_PROFILES["compatible"].bitrate == "640k"
    assert config.OUTPUT_PROFILES["archival"].codec == "flac"
