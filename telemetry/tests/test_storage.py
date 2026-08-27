import json

from telemetry.storage import JsonlWriter


def test_write_produces_one_valid_json_line_per_record(tmp_path):
    writer = JsonlWriter(tmp_path, "telemetry")
    writer.write({"a": 1})
    writer.write({"b": 2})
    writer.close()

    files = list(tmp_path.glob("telemetry_*.jsonl"))
    assert len(files) == 1

    lines = files[0].read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": 2}


def test_rotation_creates_a_new_file_and_closes_the_old_one(tmp_path):
    # write() always rotates to *today's real* date on its own (that's the whole point of daily
    # rotation), so to test _rotate() in isolation without waiting for a real day to pass, drive
    # it directly rather than through write() - which would just rotate itself straight back to
    # today regardless of what date we forced it to a moment earlier.
    writer = JsonlWriter(tmp_path, "telemetry")
    writer.write({"day": "one"})
    first_file_handle = writer._file

    writer._rotate("2099-01-02")

    assert first_file_handle.closed
    assert writer._current_date == "2099-01-02"
    writer._file.write(json.dumps({"day": "two"}) + "\n")
    writer._file.flush()
    writer.close()

    files = sorted(p.name for p in tmp_path.glob("telemetry_*.jsonl"))
    assert len(files) == 2
    assert "telemetry_2099-01-02.jsonl" in files

    second_file_content = (tmp_path / "telemetry_2099-01-02.jsonl").read_text().splitlines()
    assert json.loads(second_file_content[0]) == {"day": "two"}


def test_close_is_safe_to_call_when_nothing_was_written(tmp_path):
    writer = JsonlWriter(tmp_path, "telemetry")
    writer.close()  # must not raise
    assert list(tmp_path.glob("*.jsonl")) == []


def test_serializes_non_json_native_values_via_default_str(tmp_path):
    from datetime import datetime, timezone

    writer = JsonlWriter(tmp_path, "telemetry")
    writer.write({"ts": datetime(2026, 1, 1, tzinfo=timezone.utc)})
    writer.close()

    files = list(tmp_path.glob("telemetry_*.jsonl"))
    line = files[0].read_text().splitlines()[0]
    assert "2026-01-01" in json.loads(line)["ts"]
