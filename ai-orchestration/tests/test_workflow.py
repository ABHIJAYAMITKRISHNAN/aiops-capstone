"""Categories 10 (LangGraph normal path) and 11 (LangGraph anomaly path), plus the
insufficient-data path (no valid feature vector), no-model path, and Week 8's RCA/RAG/remediation
extension of the anomaly path."""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from ai_orchestration import config
from ai_orchestration.anomaly.detector import AnomalyDetector
from ai_orchestration.anomaly.feature_extractor import extract_features
from ai_orchestration.graph import workflow
from ai_orchestration.graph.workflow import build_graph
from ai_orchestration.rag.models import RetrievalResult, RetrievedIncident


@pytest.fixture(autouse=True)
def isolated_models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    # See test_detector.py's isolated_models_dir fixture for why: "auto" contamination's fixed
    # -0.5 offset isn't well-calibrated for a tiny unit-test-sized training set.
    monkeypatch.setattr(config, "ISOLATION_FOREST_CONTAMINATION", "0.05")


@pytest.fixture(autouse=True)
def mock_retrieval(monkeypatch):
    """Isolates every graph test from the real on-disk ChromaDB collection - retrieval behavior
    itself is covered exhaustively in test_rag_retriever.py. Defaults to an empty result; tests
    that care about non-empty retrieval override this within their own body."""
    def _empty(query_text, n_results=3):
        return RetrievalResult(query_text=query_text, incidents=[], source_collection="incident_memory", status="empty")
    monkeypatch.setattr(workflow.rag_retriever, "retrieve_similar_incidents", _empty)


def _trained_auth_detector(auth_record_factory) -> AnomalyDetector:
    rng = random.Random(42)
    vectors = [
        extract_features(auth_record_factory(
            jvm_used=40_000_000.0 + rng.uniform(-500_000, 500_000),
            error_count=max(0.0, rng.uniform(-0.3, 0.3)),
            req_count=10.0 + rng.uniform(-2, 2),
        ))
        for _ in range(50)
    ]
    detector = AnomalyDetector("auth-service")
    detector.train(vectors, training_source_experiment_ids=["exp-1"])
    return detector


def test_workflow_normal_path_never_calls_llm(auth_record_factory, monkeypatch):
    detector = _trained_auth_detector(auth_record_factory)
    ollama_client = MagicMock()
    retrieval_spy = MagicMock(side_effect=AssertionError("retrieval must not run on the normal path"))
    monkeypatch.setattr(workflow.rag_retriever, "retrieve_similar_incidents", retrieval_spy)
    graph = build_graph({"auth-service": detector}, ollama_client)

    normal_record = auth_record_factory(jvm_used=40_000_100.0, req_count=10.0)
    final_state = graph.invoke({"raw_record": normal_record, "incident_id": None})

    result = final_state["result"]
    assert result["decision"] == "normal"
    assert result["llm_interpretation"] is None
    assert result["anomaly_result"]["status"] == "scored"
    # Week 8 additions must also stay untouched on the normal path - no RAG, no RCA, no remediation.
    assert result["retrieval"] is None
    assert result["root_cause_analysis"] is None
    assert result["remediation_proposal"] is None
    ollama_client.is_available.assert_not_called()
    ollama_client.generate.assert_not_called()
    retrieval_spy.assert_not_called()


def test_workflow_anomaly_path_calls_llm_and_includes_interpretation(auth_record_factory):
    detector = _trained_auth_detector(auth_record_factory)
    ollama_client = MagicMock()
    ollama_client.is_available.return_value = True
    ollama_client.model = "llama3.2:1b"
    # The anomaly path now makes two distinct LLM calls (Week 8 extension): interpret_anomaly()
    # first, then the RCA narrative in root_cause_analysis - both go through this same mock's
    # generate(), so the mock must be able to answer either shape depending on which prompt it's
    # given, unlike Week 7's single-call version of this test.
    def _generate(prompt, expect_json=True):
        if "observed_evidence" in prompt:
            return '{"observed_evidence": "jvm_memory_used_bytes is far above baseline", "inference": "consistent with a memory-related fault"}'
        return (
            '{"abnormal_summary": "memory spike", "affected_service": "auth-service", '
            '"significant_metrics": ["jvm_memory_used_bytes"], "evidence": "value far above baseline", '
            '"confidence": "high"}'
        )
    ollama_client.generate.side_effect = _generate
    graph = build_graph({"auth-service": detector}, ollama_client)

    fault_like_record = auth_record_factory(jvm_used=4_000_000_000.0, error_count=50.0, req_count=500.0)
    final_state = graph.invoke({"raw_record": fault_like_record, "incident_id": "inc-test"})

    result = final_state["result"]
    assert result["decision"] == "anomaly"
    assert result["incident_id"] == "inc-test"
    assert result["llm_interpretation"]["status"] == "interpreted"
    assert result["llm_interpretation"]["affected_service"] == "auth-service"
    assert ollama_client.generate.call_count == 2  # one for interpretation, one for RCA narrative
    # Week 8: RCA and remediation must both be reached and populated on the anomaly path.
    assert result["root_cause_analysis"] is not None
    assert result["root_cause_analysis"]["suspected_root_cause_service"] == "auth-service"
    assert result["root_cause_analysis"]["llm_reasoning"] is not None
    assert result["remediation_proposal"] is not None
    assert result["remediation_proposal"]["requires_human_approval"] is True
    assert result["retrieval"] is not None


def test_workflow_anomaly_path_degrades_gracefully_when_ollama_unavailable(auth_record_factory):
    detector = _trained_auth_detector(auth_record_factory)
    ollama_client = MagicMock()
    ollama_client.is_available.return_value = False
    ollama_client.base_url = "http://localhost:11434"
    ollama_client.model = "llama3.2:1b"
    graph = build_graph({"auth-service": detector}, ollama_client)

    fault_like_record = auth_record_factory(jvm_used=4_000_000_000.0, error_count=50.0, req_count=500.0)
    final_state = graph.invoke({"raw_record": fault_like_record, "incident_id": None})

    result = final_state["result"]
    assert result["decision"] == "anomaly"
    assert result["llm_interpretation"]["status"] == "llm_unavailable"
    assert any("LLM interpretation unavailable" in limitation for limitation in result["limitations"])
    # Week 8: the rest of the pipeline (RAG, RCA, remediation) still produces deterministic
    # structured output even with no LLM available at all - it just has no narrative text.
    assert result["retrieval"] is not None
    assert result["root_cause_analysis"] is not None
    assert result["root_cause_analysis"]["llm_reasoning"] is None
    assert result["remediation_proposal"] is not None
    assert result["remediation_proposal"]["requires_human_approval"] is True
    ollama_client.generate.assert_not_called()  # never reached generate() at all, on either call site


def test_workflow_insufficient_data_path_skips_detection_and_llm():
    ollama_client = MagicMock()
    graph = build_graph({}, ollama_client)

    broken_record = {
        "timestamp": "2026-01-01T00:00:00+00:00", "service": "auth-service", "correlation_id": "c1",
        "health": None, "metrics": None, "fault": None, "collection_error": "health: Connection refused",
    }
    final_state = graph.invoke({"raw_record": broken_record, "incident_id": None})

    result = final_state["result"]
    assert result["decision"] == "insufficient_data"
    assert result["llm_interpretation"] is None
    ollama_client.generate.assert_not_called()


def _trained_payment_detector(payment_record_factory) -> AnomalyDetector:
    rng = random.Random(7)
    vectors = [
        extract_features(payment_record_factory(
            jvm_used=40_000_000.0 + rng.uniform(-500_000, 500_000),
            error_count=max(0.0, rng.uniform(-0.3, 0.3)),
            req_count=10.0 + rng.uniform(-2, 2),
            client_duration=30.0 + rng.uniform(-10, 10),
        ))
        for _ in range(50)
    ]
    detector = AnomalyDetector("payment-service")
    detector.train(vectors, training_source_experiment_ids=["exp-1"])
    return detector


def test_workflow_anomaly_path_reaches_rca_retrieval_and_remediation_with_correct_fault_signature(payment_record_factory, monkeypatch):
    """End-to-end (mocked LLM/retrieval, real signature matching + remediation) check that the
    full Week 8 extension produces a coherent memory-leak conclusion and matching proposal."""
    detector = _trained_payment_detector(payment_record_factory)
    ollama_client = MagicMock()
    ollama_client.is_available.return_value = False  # keep this test focused on the deterministic path
    graph = build_graph({"payment-service": detector}, ollama_client)

    fault_like_record = payment_record_factory(jvm_used=500_000_000.0, client_duration=100.0)
    final_state = graph.invoke({"raw_record": fault_like_record, "incident_id": None})

    result = final_state["result"]
    assert result["decision"] == "anomaly"
    rca = result["root_cause_analysis"]
    assert rca["suspected_fault_type"] == "memory-leak"
    assert rca["suspected_root_cause_service"] == "payment-service"
    assert rca["symptom_service"] == "payment-service"

    remediation = result["remediation_proposal"]
    assert remediation["target_service"] == "payment-service"
    assert remediation["action_category"] == "reset_fault_configuration"
    assert remediation["requires_human_approval"] is True


def test_workflow_anomaly_path_uses_retrieved_incidents_in_rca(payment_record_factory, monkeypatch):
    retrieved = RetrievalResult(
        query_text="q", source_collection="incident_memory", status="retrieved",
        incidents=[RetrievedIncident(
            incident_id="inc-0037", distance=0.05, fault_type="memory-leak",
            root_cause_service="payment-service", symptom_service="payment-service",
            severity="medium", data_source="real", postmortem_excerpt="payment-service memory leak",
        )],
    )
    monkeypatch.setattr(workflow.rag_retriever, "retrieve_similar_incidents", lambda *a, **k: retrieved)

    detector = _trained_payment_detector(payment_record_factory)
    ollama_client = MagicMock()
    ollama_client.is_available.return_value = False
    graph = build_graph({"payment-service": detector}, ollama_client)

    fault_like_record = payment_record_factory(jvm_used=500_000_000.0, client_duration=100.0)
    final_state = graph.invoke({"raw_record": fault_like_record, "incident_id": None})

    result = final_state["result"]
    assert result["retrieval"]["status"] == "retrieved"
    assert result["retrieval"]["incidents"][0]["incident_id"] == "inc-0037"
    assert result["root_cause_analysis"]["determination_method"] == "metric_signature+rag_agreement"
    assert result["root_cause_analysis"]["confidence"] == "high"


def test_workflow_no_model_path_reports_no_model_status(auth_record_factory):
    ollama_client = MagicMock()
    graph = build_graph({}, ollama_client)  # empty registry - no detector for any service

    record = auth_record_factory()
    final_state = graph.invoke({"raw_record": record, "incident_id": None})

    result = final_state["result"]
    assert result["anomaly_result"]["status"] == "no_model"
    assert result["decision"] == "insufficient_data"
    assert any("No trained model" in limitation for limitation in result["limitations"])
