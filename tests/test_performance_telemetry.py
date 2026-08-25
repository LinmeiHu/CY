from pathlib import Path

from cyq_game.performance.telemetry import TelemetryRecorder


def test_stage_telemetry_records_required_metrics(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"abc")
    recorder = TelemetryRecorder()
    with recorder.stage("source_read", rows=3, read_paths=(source,)):
        assert source.read_bytes() == b"abc"
    record = recorder.records[0]
    assert record.stage == "source_read"
    assert record.rows == 3
    assert record.bytes_read == 3
    assert record.wall_seconds >= 0
    assert record.cpu_seconds >= 0
    assert record.peak_rss_bytes > 0
