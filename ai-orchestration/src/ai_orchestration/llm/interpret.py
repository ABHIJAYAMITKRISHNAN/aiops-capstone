"""Turns one anomalous AnomalyResult into a structured AnomalyInterpretation via Ollama, degrading
gracefully (never raising, never crashing the workflow) whenever the LLM is unavailable, times
out, or returns something unparseable.
"""
from __future__ import annotations

import json
import logging

from ..anomaly.models import AnomalyResult
from . import prompts
from .models import AnomalyInterpretation, INTERPRETATION_JSON_SCHEMA_KEYS
from .ollama_client import OllamaClient, OllamaUnavailableError

log = logging.getLogger("ai_orchestration.llm.interpret")


def interpret_anomaly(anomaly_result: AnomalyResult, client: OllamaClient) -> AnomalyInterpretation:
    if anomaly_result.status != "scored" or not anomaly_result.is_anomaly:
        return AnomalyInterpretation(status="skipped_not_anomalous", reason="Only anomalous, successfully-scored results are sent to the LLM")

    if not client.is_available():
        log.warning("Ollama unavailable at %s - returning graceful degradation result", client.base_url)
        return AnomalyInterpretation(
            status="llm_unavailable",
            reason=f"Ollama server not reachable at {client.base_url}",
            model=client.model,
        )

    prompt = prompts.build_interpretation_prompt(anomaly_result)
    try:
        raw_response = client.generate(prompt, expect_json=True)
    except OllamaUnavailableError as exc:
        log.warning("Ollama generate() failed: %s", exc)
        return AnomalyInterpretation(status="llm_unavailable", reason=str(exc), model=client.model)

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        log.warning("Ollama response was not valid JSON: %s", exc)
        return AnomalyInterpretation(status="llm_error", reason=f"Response was not valid JSON: {exc}", model=client.model)

    missing_keys = [k for k in INTERPRETATION_JSON_SCHEMA_KEYS if k not in parsed]
    if missing_keys:
        return AnomalyInterpretation(
            status="llm_error", reason=f"Response missing required keys: {missing_keys}", model=client.model,
        )

    significant_metrics = parsed.get("significant_metrics") or []
    if not isinstance(significant_metrics, list):
        significant_metrics = [str(significant_metrics)]

    return AnomalyInterpretation(
        status="interpreted",
        abnormal_summary=str(parsed.get("abnormal_summary") or ""),
        affected_service=str(parsed.get("affected_service") or anomaly_result.service),
        significant_metrics=[str(m) for m in significant_metrics],
        evidence=str(parsed.get("evidence") or ""),
        confidence=str(parsed.get("confidence") or "low"),
        model=client.model,
    )
