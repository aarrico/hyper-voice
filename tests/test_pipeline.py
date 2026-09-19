from conftest import requires_ffmpeg

from core.pipeline import output_path_for, process_video
from core.probe import probe_audio_streams


@requires_ffmpeg
def test_process_video_adds_boosted_track_for_surround_source(surround_clip, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(surround_clip, output_dir)

    assert result.startswith("[✔]")
    output_path = output_dir / f"{surround_clip.stem}_mkv_boosted.mkv"
    assert output_path.exists()

    original_streams = probe_audio_streams(surround_clip)
    boosted_streams = probe_audio_streams(output_path)
    assert len(boosted_streams) == len(original_streams) + 1


@requires_ffmpeg
def test_process_video_rejects_stereo_source_by_default(stereo_clip, tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = process_video(stereo_clip, output_dir)

    assert result.startswith("[✘] Failed")
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

    assert result.startswith("[✘] Skipped")
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

    assert result.startswith("[✘] Failed")
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
