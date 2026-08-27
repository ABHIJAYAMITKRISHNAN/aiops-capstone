"""Shared fixtures: small, hand-built raw-JSONL-shaped records mirroring exactly what Week 5's
collector/experiment/payment_probe actually emit, so reconstruction/incident tests exercise the
real schema rather than an invented one.
"""
from __future__ import annotations

import pytest

SERVICES = ["auth-service", "payment-service", "ledger-service", "notification-service"]


def _metrics(base: float = 40_000_000.0, error_count: float = 0.0) -> dict:
    return {
        "jvm_memory_used_bytes": base,
        "jvm_memory_committed_bytes": base * 2,
        "jvm_memory_max_bytes": 4_294_967_296.0,
        "hikaricp_connections_active": None,
        "hikaricp_connections_idle": None,
        "hikaricp_connections_pending": None,
        "hikaricp_connections_acquire_seconds_avg": None,
        "http_server_requests_count": 10.0,
        "http_server_requests_error_count": error_count,
        "http_server_requests_avg_duration_ms": 50.0,
        "http_client_requests_count": None,
        "http_client_requests_avg_duration_ms": None,
        "process_cpu_usage": 0.01,
        "system_cpu_usage": 0.1,
    }


def _tel_record(ts: str, service: str, fault_active: bool, metrics: dict | None = None, collection_error=None) -> dict:
    return {
        "timestamp": ts,
        "service": service,
        "correlation_id": f"corr-{service}-{ts}",
        "metrics": metrics if metrics is not None else _metrics(),
        "fault": {"faultActive": fault_active, "message": "x"},
        "collection_error": collection_error,
    }


def _probe(ts: str, success: bool, http_status: int, error=None) -> dict:
    return {
        "timestamp": ts,
        "type": "payment_probe",
        "correlation_id": f"corr-probe-{ts}",
        "success": success,
        "stage": "payment",
        "http_status": http_status,
        "duration_ms": 12.0,
        "payment_status": "SUCCESS" if success else None,
        "notification_status": "SENT" if success else None,
        "ledger_transaction_id": "tx-1" if success else None,
        "error": error,
    }


@pytest.fixture
def auth_key_error_experiment_data():
    """One complete, real-shaped auth-key-error experiment: root cause on auth-service, symptom
    on payment-service (auth-service's own faultActive=True the whole fault window; every other
    service's own faultActive stays False, mirroring the real bug this dataset exercises)."""
    events = [
        {"timestamp": "2026-01-01T00:00:00+00:00", "event": "EXPERIMENT_START", "fault": "auth-key-error",
         "service": "auth-service", "plan": {"baseline_seconds": 10, "fault_seconds": 10, "recovery_seconds": 10}},
        {"timestamp": "2026-01-01T00:00:10+00:00", "event": "FAULT_INJECTED", "fault": "auth-key-error",
         "service": "auth-service", "response": {"faultActive": True, "message": "injected"}},
        {"timestamp": "2026-01-01T00:00:20+00:00", "event": "FAULT_RESET", "fault": "auth-key-error",
         "service": "auth-service", "response": {"faultActive": False, "message": "reset"}},
        {"timestamp": "2026-01-01T00:00:30+00:00", "event": "EXPERIMENT_END", "fault": "auth-key-error",
         "service": "auth-service"},
    ]

    telemetry = []
    for t in [2, 6]:  # NORMAL phase samples
        ts = f"2026-01-01T00:00:0{t}+00:00"
        for svc in SERVICES:
            telemetry.append(_tel_record(ts, svc, fault_active=False))
    for t in [12, 16]:  # FAULT_ACTIVE phase: auth-service's own flag is True; others stay False
        ts = f"2026-01-01T00:00:{t}+00:00"
        for svc in SERVICES:
            is_target = svc == "auth-service"
            metrics = _metrics(error_count=2.0) if svc == "payment-service" else _metrics()
            telemetry.append(_tel_record(ts, svc, fault_active=is_target, metrics=metrics))
    for t in [22, 26]:  # RECOVERY phase samples
        ts = f"2026-01-01T00:00:{t}+00:00"
        for svc in SERVICES:
            telemetry.append(_tel_record(ts, svc, fault_active=False))

    probes = [
        _probe("2026-01-01T00:00:04+00:00", success=True, http_status=200),
        _probe("2026-01-01T00:00:14+00:00", success=False, http_status=401, error="Invalid or expired token"),
        _probe("2026-01-01T00:00:18+00:00", success=False, http_status=401, error="Invalid or expired token"),
        _probe("2026-01-01T00:00:24+00:00", success=True, http_status=200),
    ]

    return events, telemetry, probes


@pytest.fixture
def incomplete_experiment_events():
    """An experiment whose fault injection never succeeded (only FAULT_INJECT_FAILED, no
    FAULT_INJECTED/FAULT_RESET) - the real shape produced when the target service is unreachable."""
    return [
        {"timestamp": "2026-01-01T01:00:00+00:00", "event": "EXPERIMENT_START", "fault": "db-lock",
         "service": "ledger-service", "plan": {"baseline_seconds": 5, "fault_seconds": 5, "recovery_seconds": 5}},
        {"timestamp": "2026-01-01T01:00:05+00:00", "event": "FAULT_INJECT_FAILED", "fault": "db-lock",
         "service": "ledger-service", "error": "Connection refused"},
        {"timestamp": "2026-01-01T01:00:20+00:00", "event": "EXPERIMENT_END", "fault": "db-lock",
         "service": "ledger-service"},
    ]
