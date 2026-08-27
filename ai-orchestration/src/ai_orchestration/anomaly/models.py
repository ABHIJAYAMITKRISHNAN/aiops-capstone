"""Typed data shapes shared across feature extraction, training, and inference.

Plain dataclasses with explicit `to_dict()` methods (not just `dataclasses.asdict`) so every
structured output field required by Week 7 (and consumed by Week 8) is deliberate, not whatever
happens to be on the object.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FeatureVector:
    """One point-in-time, one-service numerical observation, ready for the Isolation Forest.

    `values` is ordered to match `feature_names` exactly - callers must never assume dict
    iteration order; `feature_names` is the explicit contract."""
    service: str
    timestamp: str
    correlation_id: Optional[str]
    feature_names: list[str]
    values: list[float]
    raw_metrics: dict = field(default_factory=dict)  # the subset of applicable metrics, for evidence/logging

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "feature_names": self.feature_names,
            "values": self.values,
            "raw_metrics": self.raw_metrics,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureVector":
        return cls(**data)


@dataclass
class ModelMetadata:
    """Persisted alongside every trained model - loaded and checked before any inference, so a
    schema mismatch is a loud, explicit error rather than a silently wrong prediction."""
    service: str
    feature_schema_version: str
    feature_names: list[str]
    n_estimators: int
    contamination: str  # "auto" or a stringified float, as configured
    random_state: int
    max_samples: str
    trained_at: str
    training_sample_count: int
    training_source_experiment_ids: list[str]  # audit trail: exactly which real experiments contributed
    model_version: str = "isolation-forest-v1"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelMetadata":
        return cls(**data)


@dataclass
class AnomalyResult:
    """The structured, machine-readable output of one inference call - required fields per
    Week 7's spec: timestamp, service, anomaly_score, is_anomaly, relevant_feature_values,
    model/version information."""
    service: str
    timestamp: str
    correlation_id: Optional[str]
    status: str  # "scored" | "insufficient_data" | "no_model"
    anomaly_score: Optional[float]
    is_anomaly: Optional[bool]
    threshold: float
    relevant_feature_values: dict
    model_version: str
    feature_schema_version: str
    reason: Optional[str] = None  # populated when status != "scored"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "AnomalyResult":
        return cls(**data)
