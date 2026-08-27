"""Verifies training-data selection never crosses into Evaluation-set territory - the property
Week 7's spec calls "Never train on Evaluation incidents" / "Keep dataset separation explicit in
code", mirroring dataset-tools' chroma_store leakage tests for the anomaly detector's training
data instead of ChromaDB."""
from __future__ import annotations

from ai_orchestration.anomaly.feature_extractor import load_memory_eligible_baseline_records


def _event(ts, event, fault, service, **extra):
    return {"timestamp": ts, "event": event, "fault": fault, "service": service, **extra}


def _telemetry(ts, service, phase_hint_active):
    return {
        "timestamp": ts, "service": service, "correlation_id": f"c-{ts}",
        "metrics": {"jvm_memory_used_bytes": 40_000_000.0},
        "fault": {"faultActive": phase_hint_active}, "collection_error": None,
    }


def test_only_memory_associated_experiments_contribute_records():
    events = [
        _event("2026-01-01T00:00:00+00:00", "EXPERIMENT_START", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:05+00:00", "FAULT_INJECTED", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:10+00:00", "FAULT_RESET", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:15+00:00", "EXPERIMENT_END", "memory-leak", "payment-service"),

        _event("2026-01-01T01:00:00+00:00", "EXPERIMENT_START", "db-lock", "ledger-service"),
        _event("2026-01-01T01:00:05+00:00", "FAULT_INJECTED", "db-lock", "ledger-service"),
        _event("2026-01-01T01:00:10+00:00", "FAULT_RESET", "db-lock", "ledger-service"),
        _event("2026-01-01T01:00:15+00:00", "EXPERIMENT_END", "db-lock", "ledger-service"),
    ]
    telemetry = [
        _telemetry("2026-01-01T00:00:02+00:00", "payment-service", False),  # NORMAL, memory-leak exp (eligible)
        _telemetry("2026-01-01T01:00:02+00:00", "ledger-service", False),   # NORMAL, db-lock exp (NOT eligible)
    ]
    # Only the memory-leak experiment's incident is in the Memory set.
    memory_incidents = [
        {"data_source": "real", "experiment_id": "memory-leak-2026-01-01T00:00:00+00:00"},
    ]

    records = load_memory_eligible_baseline_records(events=events, telemetry=telemetry, memory_incidents=memory_incidents)

    assert len(records) == 1
    assert records[0]["service"] == "payment-service"


def test_synthetic_memory_incidents_contribute_no_records():
    """Synthetic incidents have no raw telemetry behind them at all - even if one appeared in the
    Memory file (it does - synthetic incidents are eligible for ChromaDB), it must not somehow
    inject records here, since it has no experiment_id."""
    events, telemetry = [], []
    memory_incidents = [
        {"data_source": "synthetic", "experiment_id": None},
        {"data_source": "synthetic"},  # no experiment_id key at all
    ]

    records = load_memory_eligible_baseline_records(events=events, telemetry=telemetry, memory_incidents=memory_incidents)

    assert records == []


def test_experiment_with_no_matching_memory_incident_contributes_nothing():
    events = [
        _event("2026-01-01T00:00:00+00:00", "EXPERIMENT_START", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:05+00:00", "FAULT_INJECTED", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:10+00:00", "FAULT_RESET", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:15+00:00", "EXPERIMENT_END", "memory-leak", "payment-service"),
    ]
    telemetry = [_telemetry("2026-01-01T00:00:02+00:00", "payment-service", False)]
    memory_incidents = []  # nothing in Memory at all - e.g. this real experiment landed in Evaluation

    records = load_memory_eligible_baseline_records(events=events, telemetry=telemetry, memory_incidents=memory_incidents)

    assert records == []


def test_fault_active_phase_telemetry_is_excluded_even_from_eligible_experiments():
    events = [
        _event("2026-01-01T00:00:00+00:00", "EXPERIMENT_START", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:05+00:00", "FAULT_INJECTED", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:10+00:00", "FAULT_RESET", "memory-leak", "payment-service"),
        _event("2026-01-01T00:00:15+00:00", "EXPERIMENT_END", "memory-leak", "payment-service"),
    ]
    telemetry = [
        _telemetry("2026-01-01T00:00:02+00:00", "payment-service", False),  # NORMAL
        _telemetry("2026-01-01T00:00:07+00:00", "payment-service", True),   # FAULT_ACTIVE - must be excluded
    ]
    memory_incidents = [{"data_source": "real", "experiment_id": "memory-leak-2026-01-01T00:00:00+00:00"}]

    records = load_memory_eligible_baseline_records(events=events, telemetry=telemetry, memory_incidents=memory_incidents)

    assert len(records) == 1
    assert records[0]["timestamp"] == "2026-01-01T00:00:02+00:00"
