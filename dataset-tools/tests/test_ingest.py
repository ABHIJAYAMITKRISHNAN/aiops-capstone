"""Category 1: JSONL ingestion."""
from __future__ import annotations

import json

import pytest

from dataset_tools import ingest


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_load_events_reads_and_sorts_across_multiple_files(tmp_path):
    _write(tmp_path / "events_2026-01-01.jsonl", [{"timestamp": "2026-01-01T00:00:05+00:00", "event": "B"}])
    _write(tmp_path / "events_2026-01-02.jsonl", [{"timestamp": "2026-01-01T00:00:01+00:00", "event": "A"}])

    events = ingest.load_events(tmp_path)

    assert [e["event"] for e in events] == ["A", "B"]


def test_load_telemetry_and_probes_only_read_matching_prefix(tmp_path):
    _write(tmp_path / "telemetry_2026-01-01.jsonl", [{"timestamp": "2026-01-01T00:00:01+00:00", "service": "x"}])
    _write(tmp_path / "payment_probes_2026-01-01.jsonl", [{"timestamp": "2026-01-01T00:00:02+00:00", "type": "payment_probe"}])

    telemetry = ingest.load_telemetry(tmp_path)
    probes = ingest.load_payment_probes(tmp_path)

    assert len(telemetry) == 1 and telemetry[0]["service"] == "x"
    assert len(probes) == 1 and probes[0]["type"] == "payment_probe"


def test_missing_directory_returns_empty_list_not_error(tmp_path):
    assert ingest.load_events(tmp_path / "does-not-exist") == []


def test_malformed_jsonl_line_raises_with_location(tmp_path):
    path = tmp_path / "events_2026-01-01.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"timestamp": "x", "event": "A"}\nNOT JSON\n')

    with pytest.raises(ValueError, match="Malformed JSONL"):
        ingest.load_events(tmp_path)


def test_write_then_read_jsonl_roundtrip(tmp_path):
    records = [{"incident_id": "inc-0001", "n": 1}, {"incident_id": "inc-0002", "n": 2}]
    out = tmp_path / "nested" / "out.jsonl"

    ingest.write_jsonl(records, out)
    result = ingest.read_jsonl(out)

    assert result == records


def test_read_jsonl_missing_file_returns_empty_list(tmp_path):
    assert ingest.read_jsonl(tmp_path / "missing.jsonl") == []


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "events_2026-01-01.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"timestamp": "x", "event": "A"}\n\n   \n{"timestamp": "y", "event": "B"}\n')

    events = ingest.load_events(tmp_path)

    assert len(events) == 2
