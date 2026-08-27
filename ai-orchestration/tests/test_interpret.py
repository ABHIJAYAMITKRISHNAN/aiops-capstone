"""More of category 9 (Ollama unavailable handling), at the interpret_anomaly() orchestration
layer rather than the raw HTTP client - covers graceful degradation for unavailability, timeouts,
and malformed LLM output."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from ai_orchestration.anomaly.models import AnomalyResult
from ai_orchestration.llm.interpret import interpret_anomaly
from ai_orchestration.llm.ollama_client import OllamaUnavailableError


def _anomalous_result() -> AnomalyResult:
    return AnomalyResult(
        service="payment-service", timestamp="2026-01-01T00:00:00+00:00", correlation_id="c1",
        status="scored", anomaly_score=0.42, is_anomaly=True, threshold=0.0,
        relevant_feature_values={"jvm_memory_used_bytes": 200_000_000.0},
        model_version="isolation-forest-v1", feature_schema_version="v1",
    )


def test_interpret_skips_llm_when_not_anomalous():
    normal_result = AnomalyResult(
        service="payment-service", timestamp="t", correlation_id=None, status="scored",
        anomaly_score=-0.1, is_anomaly=False, threshold=0.0, relevant_feature_values={},
        model_version="isolation-forest-v1", feature_schema_version="v1",
    )
    client = MagicMock()

    interpretation = interpret_anomaly(normal_result, client)

    assert interpretation.status == "skipped_not_anomalous"
    client.is_available.assert_not_called()
    client.generate.assert_not_called()


def test_interpret_returns_llm_unavailable_when_server_down():
    client = MagicMock()
    client.is_available.return_value = False
    client.base_url = "http://localhost:11434"
    client.model = "llama3.2:1b"

    interpretation = interpret_anomaly(_anomalous_result(), client)

    assert interpretation.status == "llm_unavailable"
    client.generate.assert_not_called()


def test_interpret_returns_llm_unavailable_on_generate_timeout():
    client = MagicMock()
    client.is_available.return_value = True
    client.model = "llama3.2:1b"
    client.generate.side_effect = OllamaUnavailableError("timed out")

    interpretation = interpret_anomaly(_anomalous_result(), client)

    assert interpretation.status == "llm_unavailable"
    assert "timed out" in interpretation.reason


def test_interpret_returns_llm_error_on_malformed_json():
    client = MagicMock()
    client.is_available.return_value = True
    client.model = "llama3.2:1b"
    client.generate.return_value = "not json at all"

    interpretation = interpret_anomaly(_anomalous_result(), client)

    assert interpretation.status == "llm_error"


def test_interpret_returns_llm_error_when_required_keys_missing():
    client = MagicMock()
    client.is_available.return_value = True
    client.model = "llama3.2:1b"
    client.generate.return_value = json.dumps({"abnormal_summary": "something's off"})  # missing other keys

    interpretation = interpret_anomaly(_anomalous_result(), client)

    assert interpretation.status == "llm_error"
    assert "missing" in interpretation.reason.lower()


def test_interpret_returns_structured_result_on_success():
    client = MagicMock()
    client.is_available.return_value = True
    client.model = "llama3.2:1b"
    client.generate.return_value = json.dumps({
        "abnormal_summary": "JVM memory usage is well above baseline.",
        "affected_service": "payment-service",
        "significant_metrics": ["jvm_memory_used_bytes"],
        "evidence": "jvm_memory_used_bytes = 200000000.0",
        "confidence": "medium",
    })

    interpretation = interpret_anomaly(_anomalous_result(), client)

    assert interpretation.status == "interpreted"
    assert interpretation.affected_service == "payment-service"
    assert interpretation.significant_metrics == ["jvm_memory_used_bytes"]
    assert interpretation.confidence == "medium"


def test_interpret_prompt_only_contains_provided_evidence():
    """The prompt sent to the LLM must be built solely from the AnomalyResult's own fields - no
    metric name outside relevant_feature_values should appear."""
    from ai_orchestration.llm.prompts import build_interpretation_prompt

    result = _anomalous_result()
    prompt = build_interpretation_prompt(result)

    assert "jvm_memory_used_bytes" in prompt
    assert "200000000" in prompt.replace(".0", "")
    assert "hikaricp" not in prompt  # never mentioned in this result's evidence - must not appear
