"""Shared fixtures: raw-telemetry-shaped records matching exactly what
telemetry/collector.py's collect_service() produces."""
from __future__ import annotations

import pytest


def _record(service: str, metrics: dict, correlation_id: str = "corr-1", timestamp: str = "2026-01-01T00:00:00+00:00",
            collection_error=None, fault_active: bool = False) -> dict:
    return {
        "timestamp": timestamp,
        "service": service,
        "correlation_id": correlation_id,
        "health": {"status": "UP", "components": {}},
        "metrics": metrics,
        "fault": {"faultActive": fault_active},
        "collection_error": collection_error,
    }


def _base_metrics(jvm_used=40_000_000.0, error_count=0.0, req_count=10.0) -> dict:
    return {
        "jvm_memory_used_bytes": jvm_used,
        "jvm_memory_committed_bytes": jvm_used * 2,
        "jvm_memory_max_bytes": 4_294_967_296.0,
        "hikaricp_connections_active": None,
        "hikaricp_connections_idle": None,
        "hikaricp_connections_pending": None,
        "hikaricp_connections_acquire_seconds_avg": None,
        "http_server_requests_count": req_count,
        "http_server_requests_error_count": error_count,
        "http_server_requests_avg_duration_ms": 50.0,
        "http_client_requests_count": None,
        "http_client_requests_avg_duration_ms": None,
        "process_cpu_usage": 0.01,
        "system_cpu_usage": 0.1,
    }


@pytest.fixture
def auth_record_factory():
    def make(**kwargs):
        overrides = {k: kwargs.pop(k) for k in ("jvm_used", "error_count", "req_count") if k in kwargs}
        return _record("auth-service", _base_metrics(**overrides), **kwargs)
    return make


@pytest.fixture
def notification_record_factory():
    def make(**kwargs):
        overrides = {k: kwargs.pop(k) for k in ("jvm_used", "error_count", "req_count") if k in kwargs}
        return _record("notification-service", _base_metrics(**overrides), **kwargs)
    return make


@pytest.fixture
def payment_record_factory():
    def make(client_count=5.0, client_duration=30.0, **kwargs):
        overrides = {k: kwargs.pop(k) for k in ("jvm_used", "error_count", "req_count") if k in kwargs}
        metrics = _base_metrics(**overrides)
        metrics["http_client_requests_count"] = client_count
        metrics["http_client_requests_avg_duration_ms"] = client_duration
        return _record("payment-service", metrics, **kwargs)
    return make


@pytest.fixture
def ledger_record_factory():
    def make(active=1.0, idle=9.0, pending=0.0, acquire=0.0005, **kwargs):
        overrides = {k: kwargs.pop(k) for k in ("jvm_used", "error_count", "req_count") if k in kwargs}
        metrics = _base_metrics(**overrides)
        metrics["hikaricp_connections_active"] = active
        metrics["hikaricp_connections_idle"] = idle
        metrics["hikaricp_connections_pending"] = pending
        metrics["hikaricp_connections_acquire_seconds_avg"] = acquire
        return _record("ledger-service", metrics, **kwargs)
    return make
