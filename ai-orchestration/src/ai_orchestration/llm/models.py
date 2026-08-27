"""Typed shapes for the Ollama-based anomaly interpretation step."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# The exact JSON schema the LLM is asked to produce - kept as a plain constant (not a pydantic
# model) so it can be embedded verbatim into the prompt text in prompts.py.
INTERPRETATION_JSON_SCHEMA_KEYS = (
    "abnormal_summary", "affected_service", "significant_metrics", "evidence", "confidence",
)


@dataclass
class AnomalyInterpretation:
    """Structured, machine-readable result of asking the LLM to interpret an anomaly. Week 7 only
    ever produces this - it never executes remediation actions (see PHASE 5's "The LLM should not
    yet execute remediation actions")."""
    status: str  # "interpreted" | "llm_unavailable" | "llm_error" | "skipped_not_anomalous"
    abnormal_summary: Optional[str] = None
    affected_service: Optional[str] = None
    significant_metrics: list[str] = field(default_factory=list)
    evidence: Optional[str] = None
    confidence: Optional[str] = None  # "low" | "medium" | "high"
    model: Optional[str] = None
    reason: Optional[str] = None  # populated when status != "interpreted"

    def to_dict(self) -> dict:
        return dict(self.__dict__)
