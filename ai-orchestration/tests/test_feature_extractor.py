"""Categories 1 (feature extraction) and 2 (missing/non-applicable metrics)."""
from __future__ import annotations

from ai_orchestration import config
from ai_orchestration.anomaly import feature_extractor


def test_extract_features_auth_service_uses_base_schema_only(auth_record_factory):
    record = auth_record_factory()

    fv = feature_extractor.extract_features(record)

    assert fv is not None
    assert fv.service == "auth-service"
    assert fv.feature_names == config.SERVICE_FEATURE_SCHEMAS["auth-service"]
    assert "hikaricp_connections_active" not in fv.feature_names
    assert "http_client_requests_count" not in fv.feature_names
    assert len(fv.values) == len(fv.feature_names)


def test_extract_features_ledger_service_includes_hikaricp(ledger_record_factory):
    record = ledger_record_factory(active=3.0)

    fv = feature_extractor.extract_features(record)

    assert fv is not None
    assert "hikaricp_connections_active" in fv.feature_names
    idx = fv.feature_names.index("hikaricp_connections_active")
    assert fv.values[idx] == 3.0


def test_extract_features_payment_service_includes_http_client(payment_record_factory):
    record = payment_record_factory(client_duration=123.0)

    fv = feature_extractor.extract_features(record)

    assert fv is not None
    assert "http_client_requests_avg_duration_ms" in fv.feature_names
    idx = fv.feature_names.index("http_client_requests_avg_duration_ms")
    assert fv.values[idx] == 123.0


def test_extract_features_returns_none_when_metrics_missing(auth_record_factory):
    record = auth_record_factory()
    record["metrics"] = None
    record["collection_error"] = "health: Connection refused"

    fv = feature_extractor.extract_features(record)

    assert fv is None


def test_extract_features_returns_none_when_applicable_metric_is_none(auth_record_factory):
    record = auth_record_factory()
    record["metrics"]["jvm_memory_used_bytes"] = None  # applicable but missing this cycle

    fv = feature_extractor.extract_features(record)

    assert fv is None


def test_extract_features_ledger_none_hikaricp_is_not_an_error_when_populated(ledger_record_factory):
    # Sanity: a *populated* ledger record (the normal case) must succeed - hikaricp being legitimately
    # applicable to ledger-service is the point of this fixture.
    record = ledger_record_factory()
    fv = feature_extractor.extract_features(record)
    assert fv is not None


def test_extract_features_unknown_service_returns_none(auth_record_factory):
    record = auth_record_factory()
    record["service"] = "some-other-service"

    fv = feature_extractor.extract_features(record)

    assert fv is None


def test_extract_features_does_not_fail_on_auth_service_missing_hikaricp():
    """auth-service never reports hikaricp_* at all (they're None in the raw metrics dict, always)
    - that must never be treated as an error since auth-service's schema doesn't include them."""
    record = {
        "timestamp": "2026-01-01T00:00:00+00:00", "service": "auth-service", "correlation_id": "c1",
        "health": {"status": "UP", "components": {}},
        "metrics": {
            "jvm_memory_used_bytes": 40_000_000.0, "jvm_memory_committed_bytes": 80_000_000.0,
            "jvm_memory_max_bytes": 4_294_967_296.0,
            "hikaricp_connections_active": None, "hikaricp_connections_idle": None,
            "hikaricp_connections_pending": None, "hikaricp_connections_acquire_seconds_avg": None,
            "http_server_requests_count": 10.0, "http_server_requests_error_count": 0.0,
            "http_server_requests_avg_duration_ms": 50.0,
            "http_client_requests_count": None, "http_client_requests_avg_duration_ms": None,
            "process_cpu_usage": 0.01, "system_cpu_usage": 0.1,
        },
        "fault": {"faultActive": False}, "collection_error": None,
    }

    fv = feature_extractor.extract_features(record)

    assert fv is not None
