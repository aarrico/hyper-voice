import json

from conftest import requires_ffmpeg

from core.benchmark import benchmark_videos


@requires_ffmpeg
def test_benchmark_writes_machine_readable_local_measurements(surround_clip, tmp_path):
    output_dir = tmp_path / "benchmark-output"
    results_path = tmp_path / "measurements.json"

    report = benchmark_videos(
        [surround_clip],
        output_dir,
        results_path,
        mode="boost",
        profile="archival",
        workers=4,
        overwrite=False,
    )

    assert results_path.exists()
    assert json.loads(results_path.read_text()) == report
    assert report["workers"] == 1
    assert report["wall_seconds"] > 0
    assert report["cpu_seconds"] >= 0
    assert report["peak_memory_kib"] > 0
    record = report["records"][0]
    assert record["status"] == "finished"
    assert record["input_duration_seconds"] == 1.0
    assert record["processing_speed"] > 0
    assert record["output_bytes"] > 0
    assert record["loudnorm_mode"] is None
    assert record["output_audio_streams"][-1]["sample_rate"] == 48_000
