"""RCA category: analyze() end-to-end for each of the four faults, plus RAG agreement/disagreement
and LLM-unavailable graceful behavior."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from ai_orchestration.rag.models import RetrievalResult, RetrievedIncident
from ai_orchestration.rca.analyzer import analyze


def _anomaly_result(service: str, **feature_values) -> dict:
    return {
        "service": service, "timestamp": "2026-01-01T00:00:00+00:00", "correlation_id": "c1",
        "status": "scored", "anomaly_score": 0.5, "is_anomaly": True, "threshold": 0.0,
        "relevant_feature_values": feature_values,
        "model_version": "isolation-forest-v1", "feature_schema_version": "v1",
    }


def _empty_retrieval() -> RetrievalResult:
    return RetrievalResult(query_text="q", incidents=[], source_collection="incident_memory", status="empty")


def _unavailable_ollama() -> MagicMock:
    client = MagicMock()
    client.is_available.return_value = False
    client.base_url = "http://localhost:11434"
    return client


def test_memory_leak_identifies_payment_service_as_root_cause():
    anomaly = _anomaly_result("payment-service", jvm_memory_used_bytes=500_000_000.0)

    rca = analyze(anomaly, _empty_retrieval(), _unavailable_ollama())

    assert rca.suspected_fault_type == "memory-leak"
    assert rca.suspected_root_cause_service == "payment-service"
    assert rca.symptom_service == "payment-service"
    assert rca.confidence in ("medium", "high")


def test_db_pool_pressure_identifies_ledger_service_as_root_cause():
    anomaly = _anomaly_result("ledger-service", hikaricp_connections_active=9.0)

    rca = analyze(anomaly, _empty_retrieval(), _unavailable_ollama())

    assert rca.suspected_fault_type == "db-lock"
    assert rca.suspected_root_cause_service == "ledger-service"
    assert rca.symptom_service == "ledger-service"


def test_auth_key_failure_identifies_auth_service_as_root_cause():
    anomaly = _anomaly_result("payment-service", http_server_requests_error_count=6.0)

    rca = analyze(anomaly, _empty_retrieval(), _unavailable_ollama())

    assert rca.suspected_fault_type == "auth-key-error"
    assert rca.suspected_root_cause_service == "auth-service"
    assert rca.symptom_service == "payment-service"
    assert rca.suspected_root_cause_service != rca.symptom_service


def test_notification_latency_identifies_notification_service_while_payment_is_symptom():
    anomaly = _anomaly_result("payment-service", http_client_requests_avg_duration_ms=6000.0)

    rca = analyze(anomaly, _empty_retrieval(), _unavailable_ollama())

    assert rca.suspected_fault_type == "notification-latency"
    assert rca.suspected_root_cause_service == "notification-service"
    assert rca.symptom_service == "payment-service"
    assert rca.suspected_root_cause_service != rca.symptom_service
    assert "notification-service" in rca.affected_services
    assert "payment-service" in rca.affected_services


def test_rag_agreement_raises_confidence_to_high():
    anomaly = _anomaly_result("payment-service", jvm_memory_used_bytes=500_000_000.0)
    retrieval = RetrievalResult(
        query_text="q", source_collection="incident_memory", status="retrieved",
        incidents=[RetrievedIncident(
            incident_id="inc-0001", distance=0.1, fault_type="memory-leak",
            root_cause_service="payment-service", symptom_service="payment-service",
            severity="high", data_source="real", postmortem_excerpt="...",
        )],
    )

    rca = analyze(anomaly, retrieval, _unavailable_ollama())

    assert rca.confidence == "high"
    assert rca.determination_method == "metric_signature+rag_agreement"


def test_rag_disagreement_keeps_signature_conclusion_not_retrieval():
    """Must not blindly trust retrieved incidents - a disagreeing retrieval must not override the
    deterministic signature match."""
    anomaly = _anomaly_result("payment-service", jvm_memory_used_bytes=500_000_000.0)
    retrieval = RetrievalResult(
        query_text="q", source_collection="incident_memory", status="retrieved",
        incidents=[RetrievedIncident(
            incident_id="inc-0002", distance=0.1, fault_type="auth-key-error",
            root_cause_service="auth-service", symptom_service="payment-service",
            severity="high", data_source="real", postmortem_excerpt="...",
        )],
    )

    rca = analyze(anomaly, retrieval, _unavailable_ollama())

    assert rca.suspected_fault_type == "memory-leak"  # unchanged despite disagreeing retrieval
    assert rca.suspected_root_cause_service == "payment-service"
    assert rca.determination_method == "metric_signature+rag_disagreement"


def test_no_signature_match_falls_back_to_rag_only_suggestion():
    anomaly = _anomaly_result("notification-service", jvm_memory_used_bytes=35_000_000.0)  # normal, no signature
    retrieval = RetrievalResult(
        query_text="q", source_collection="incident_memory", status="retrieved",
        incidents=[RetrievedIncident(
            incident_id="inc-0003", distance=0.2, fault_type="notification-latency",
            root_cause_service="notification-service", symptom_service="payment-service",
            severity="medium", data_source="real", postmortem_excerpt="...",
        )],
    )

    rca = analyze(anomaly, retrieval, _unavailable_ollama())

    assert rca.determination_method == "rag_only"
    assert rca.confidence == "low"
    assert rca.suspected_fault_type == "notification-latency"
    # symptom_service must stay the service the anomaly was actually observed on, not whatever
    # the retrieved incident's own symptom_service metadata says.
    assert rca.symptom_service == "notification-service"


def test_no_signature_and_no_retrieval_is_fallback_unknown():
    anomaly = _anomaly_result("notification-service", jvm_memory_used_bytes=35_000_000.0)

    rca = analyze(anomaly, _empty_retrieval(), _unavailable_ollama())

    assert rca.determination_method == "fallback_unknown"
    assert rca.suspected_fault_type is None
    assert rca.suspected_root_cause_service == rca.symptom_service == "notification-service"
    assert rca.confidence == "low"


def test_llm_reasoning_is_none_when_ollama_unavailable():
    anomaly = _anomaly_result("payment-service", jvm_memory_used_bytes=500_000_000.0)

    rca = analyze(anomaly, _empty_retrieval(), _unavailable_ollama())

    assert rca.llm_reasoning is None
    # Determinism is unaffected by LLM availability - the conclusion must not depend on it.
    assert rca.suspected_root_cause_service == "payment-service"


def test_llm_reasoning_populated_when_ollama_returns_valid_json():
    anomaly = _anomaly_result("payment-service", jvm_memory_used_bytes=500_000_000.0)
    client = MagicMock()
    client.is_available.return_value = True
    client.generate.return_value = json.dumps({
        "observed_evidence": "jvm_memory_used_bytes is 500000000.0, well above the documented baseline.",
        "inference": "This pattern is consistent with the memory-leak fault signature.",
    })

    rca = analyze(anomaly, _empty_retrieval(), client)

    assert rca.llm_reasoning is not None
    assert "OBSERVED EVIDENCE" in rca.llm_reasoning
    assert "INFERENCE" in rca.llm_reasoning
    # The LLM narrative must never change the deterministic conclusion.
    assert rca.suspected_root_cause_service == "payment-service"


def test_llm_reasoning_none_when_response_missing_required_keys():
    anomaly = _anomaly_result("payment-service", jvm_memory_used_bytes=500_000_000.0)
    client = MagicMock()
    client.is_available.return_value = True
    client.generate.return_value = json.dumps({"observed_evidence": "only one field"})

    rca = analyze(anomaly, _empty_retrieval(), client)

    assert rca.llm_reasoning is None
