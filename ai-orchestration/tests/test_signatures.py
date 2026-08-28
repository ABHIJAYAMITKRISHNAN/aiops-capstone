"""RCA category: each of the four faults' known metric signature is correctly matched, and the
symptom-service vs root-cause-service distinction is correct for the two cross-service faults."""
from __future__ import annotations

from ai_orchestration.rca import signatures


def test_memory_leak_signature_matches_on_payment_service():
    matches = signatures.match_signatures("payment-service", {"jvm_memory_used_bytes": 500_000_000.0})

    assert len(matches) == 1
    assert matches[0].fault_type == "memory-leak"
    assert matches[0].root_cause_service == "payment-service"
    assert matches[0].symptom_service == "payment-service"


def test_db_lock_signature_matches_on_ledger_service():
    matches = signatures.match_signatures("ledger-service", {"hikaricp_connections_active": 9.0})

    assert len(matches) == 1
    assert matches[0].fault_type == "db-lock"
    assert matches[0].root_cause_service == "ledger-service"
    assert matches[0].symptom_service == "ledger-service"


def test_auth_key_error_signature_matches_on_payment_service_not_auth_service():
    """The symptom is visible on payment-service (see dataset-tools' empirically-verified
    FAULT_SERVICE_MAP), so the signature must be keyed to payment-service's telemetry, and must
    still report auth-service as the root cause."""
    matches = signatures.match_signatures("payment-service", {"http_server_requests_error_count": 5.0})

    assert len(matches) == 1
    assert matches[0].fault_type == "auth-key-error"
    assert matches[0].root_cause_service == "auth-service"
    assert matches[0].symptom_service == "payment-service"


def test_auth_key_error_signature_does_not_match_on_auth_service_itself():
    """auth-service's own error count never rises during this fault (verified in Week 6) - an
    elevated error count reported *for auth-service* should not match any signature."""
    matches = signatures.match_signatures("auth-service", {"http_server_requests_error_count": 5.0})

    assert matches == []


def test_notification_latency_signature_matches_on_payment_service_not_notification_service():
    matches = signatures.match_signatures("payment-service", {"http_client_requests_avg_duration_ms": 5000.0})

    assert len(matches) == 1
    assert matches[0].fault_type == "notification-latency"
    assert matches[0].root_cause_service == "notification-service"
    assert matches[0].symptom_service == "payment-service"


def test_no_signature_matches_normal_telemetry():
    matches = signatures.match_signatures("payment-service", {
        "jvm_memory_used_bytes": 35_000_000.0, "http_server_requests_error_count": 0.0,
        "http_client_requests_avg_duration_ms": 30.0,
    })

    assert matches == []


def test_multiple_matches_ranked_by_excess_ratio():
    matches = signatures.match_signatures("payment-service", {
        "jvm_memory_used_bytes": 60_000_000.0,  # ~1.03x threshold - barely over
        "http_server_requests_error_count": 50.0,  # 100x threshold - dramatically over
    })

    assert len(matches) == 2
    assert matches[0].fault_type == "auth-key-error"  # highest excess_ratio must come first


def test_baseline_reference_returns_documented_midpoint_for_jvm_memory():
    ref = signatures.baseline_reference("ledger-service", "jvm_memory_used_bytes")
    assert ref == (60_000_000.0 + 75_000_000.0) / 2


def test_baseline_reference_none_for_undocumented_metric():
    assert signatures.baseline_reference("payment-service", "http_server_requests_error_count") is None
