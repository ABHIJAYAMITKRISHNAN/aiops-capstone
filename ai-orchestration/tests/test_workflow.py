"""Categories 10 (LangGraph normal path) and 11 (LangGraph anomaly path), plus the
insufficient-data path (no valid feature vector) and no-model path."""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from ai_orchestration import config
from ai_orchestration.anomaly.detector import AnomalyDetector
from ai_orchestration.anomaly.feature_extractor import extract_features
from ai_orchestration.graph.workflow import build_graph


@pytest.fixture(autouse=True)
def isolated_models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    # See test_detector.py's isolated_models_dir fixture for why: "auto" contamination's fixed
    # -0.5 offset isn't well-calibrated for a tiny unit-test-sized training set.
    monkeypatch.setattr(config, "ISOLATION_FOREST_CONTAMINATION", "0.05")


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


def test_workflow_normal_path_never_calls_llm(auth_record_factory):
    detector = _trained_auth_detector(auth_record_factory)
    ollama_client = MagicMock()
    graph = build_graph({"auth-service": detector}, ollama_client)

    normal_record = auth_record_factory(jvm_used=40_000_100.0, req_count=10.0)
    final_state = graph.invoke({"raw_record": normal_record, "incident_id": None})

    result = final_state["result"]
    assert result["decision"] == "normal"
    assert result["llm_interpretation"] is None
    assert result["anomaly_result"]["status"] == "scored"
    ollama_client.is_available.assert_not_called()
    ollama_client.generate.assert_not_called()


def test_workflow_anomaly_path_calls_llm_and_includes_interpretation(auth_record_factory):
    detector = _trained_auth_detector(auth_record_factory)
    ollama_client = MagicMock()
    ollama_client.is_available.return_value = True
    ollama_client.model = "llama3.2:1b"
    ollama_client.generate.return_value = (
        '{"abnormal_summary": "memory spike", "affected_service": "auth-service", '
        '"significant_metrics": ["jvm_memory_used_bytes"], "evidence": "value far above baseline", '
        '"confidence": "high"}'
    )
    graph = build_graph({"auth-service": detector}, ollama_client)

    fault_like_record = auth_record_factory(jvm_used=4_000_000_000.0, error_count=50.0, req_count=500.0)
    final_state = graph.invoke({"raw_record": fault_like_record, "incident_id": "inc-test"})

    result = final_state["result"]
    assert result["decision"] == "anomaly"
    assert result["incident_id"] == "inc-test"
    assert result["llm_interpretation"]["status"] == "interpreted"
    assert result["llm_interpretation"]["affected_service"] == "auth-service"
    ollama_client.generate.assert_called_once()


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


def test_workflow_no_model_path_reports_no_model_status(auth_record_factory):
    ollama_client = MagicMock()
    graph = build_graph({}, ollama_client)  # empty registry - no detector for any service

    record = auth_record_factory()
    final_state = graph.invoke({"raw_record": record, "incident_id": None})

    result = final_state["result"]
    assert result["anomaly_result"]["status"] == "no_model"
    assert result["decision"] == "insufficient_data"
    assert any("No trained model" in limitation for limitation in result["limitations"])
