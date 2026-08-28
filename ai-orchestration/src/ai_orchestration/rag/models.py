"""Pydantic models for retrieval - a RetrievedIncident is evidence to weigh, never a command to
follow (see rca/analyzer.py for how retrieval results are combined with, and never allowed to
override, deterministic signature-based evidence)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RetrievedIncident(BaseModel):
    incident_id: str
    distance: float
    fault_type: str
    root_cause_service: str
    symptom_service: str
    severity: str
    data_source: str  # "real" or "synthetic" - never hidden from the consumer
    postmortem_excerpt: str


class RetrievalResult(BaseModel):
    query_text: str
    incidents: list[RetrievedIncident] = Field(default_factory=list)
    source_collection: str
    status: Literal["retrieved", "empty", "collection_unavailable"]
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump()
