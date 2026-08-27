"""Builds the anomaly-interpretation prompt.

Only actual telemetry/anomaly evidence goes into the prompt - the feature values embedded below
are read directly from the AnomalyResult/FeatureVector that already went through the Isolation
Forest, never invented. The instruction text explicitly tells the model not to reference any
metric not listed, and to answer only from the given evidence.
"""
from __future__ import annotations

import json

from ..anomaly.models import AnomalyResult

INTERPRETATION_SCHEMA_DESCRIPTION = """{
  "abnormal_summary": "<one or two sentences describing what looks abnormal>",
  "affected_service": "<the service name from the evidence below>",
  "significant_metrics": ["<metric names from the evidence below that appear most abnormal>"],
  "evidence": "<which specific values from the evidence below support this>",
  "confidence": "<low, medium, or high>"
}"""


def build_interpretation_prompt(anomaly_result: AnomalyResult) -> str:
    evidence = {
        "service": anomaly_result.service,
        "timestamp": anomaly_result.timestamp,
        "anomaly_score": anomaly_result.anomaly_score,
        "threshold": anomaly_result.threshold,
        "feature_values": anomaly_result.relevant_feature_values,
    }
    evidence_json = json.dumps(evidence, indent=2)

    return f"""You are helping an AIOps monitoring system interpret an anomaly detected by a
statistical model (Isolation Forest) running against a microservices payment platform.

An anomaly was flagged for the service and metrics below. This is the ONLY evidence available -
do not reference, assume, or invent any metric, service, or fact not present in this evidence.

Evidence:
{evidence_json}

Respond with ONLY a single JSON object matching exactly this shape (no extra text, no markdown
fences):
{INTERPRETATION_SCHEMA_DESCRIPTION}

Rules:
- "affected_service" must be exactly "{anomaly_result.service}" (the service this evidence is about).
- "significant_metrics" must only contain metric names that appear in "feature_values" above.
- Base "evidence" only on the numeric values shown above - do not fabricate numbers.
- If the evidence is too limited to say anything specific, say so plainly in "abnormal_summary"
  and set "confidence" to "low"."""
