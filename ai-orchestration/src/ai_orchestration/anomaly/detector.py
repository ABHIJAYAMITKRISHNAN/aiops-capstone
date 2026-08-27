"""Per-service Isolation Forest: train, persist, load, score.

One detector instance per service (see config.SERVICE_FEATURE_SCHEMAS for why) - `AnomalyDetector`
is deliberately single-service; `train.py` and the LangGraph nodes both keep a
`dict[str, AnomalyDetector]` registry rather than this class trying to be multi-service itself.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from . import models
from .. import config

log = logging.getLogger("ai_orchestration.anomaly.detector")


class FeatureSchemaMismatchError(RuntimeError):
    """Raised when a loaded model's persisted feature schema doesn't match the currently
    configured schema for that service - refusing to score rather than silently misaligning
    feature columns and producing a meaningless prediction."""


class AnomalyDetector:
    def __init__(self, service: str):
        if service not in config.SERVICE_FEATURE_SCHEMAS:
            raise ValueError(f"No feature schema configured for service '{service}'")
        self.service = service
        self.feature_names = list(config.SERVICE_FEATURE_SCHEMAS[service])
        self._model: Optional[IsolationForest] = None
        self._metadata: Optional[models.ModelMetadata] = None

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def train(self, vectors: list[models.FeatureVector], training_source_experiment_ids: list[str]) -> models.ModelMetadata:
        if not vectors:
            raise ValueError(f"No training vectors provided for service '{self.service}'")
        for v in vectors:
            if v.feature_names != self.feature_names:
                raise FeatureSchemaMismatchError(
                    f"Training vector feature_names {v.feature_names} does not match "
                    f"configured schema {self.feature_names} for service '{self.service}'"
                )

        contamination = config.ISOLATION_FOREST_CONTAMINATION
        contamination_value = contamination if contamination == "auto" else float(contamination)
        max_samples = config.ISOLATION_FOREST_MAX_SAMPLES
        max_samples_value = max_samples if max_samples == "auto" else int(max_samples)

        X = np.array([v.values for v in vectors], dtype=float)
        model = IsolationForest(
            n_estimators=config.ISOLATION_FOREST_N_ESTIMATORS,
            contamination=contamination_value,
            random_state=config.ISOLATION_FOREST_RANDOM_STATE,
            max_samples=max_samples_value,
        )
        model.fit(X)
        self._model = model

        self._metadata = models.ModelMetadata(
            service=self.service,
            feature_schema_version=config.FEATURE_SCHEMA_VERSION,
            feature_names=self.feature_names,
            n_estimators=config.ISOLATION_FOREST_N_ESTIMATORS,
            contamination=str(contamination),
            random_state=config.ISOLATION_FOREST_RANDOM_STATE,
            max_samples=str(max_samples),
            trained_at=datetime.now(timezone.utc).isoformat(),
            training_sample_count=len(vectors),
            training_source_experiment_ids=sorted(set(training_source_experiment_ids)),
        )
        log.info("Trained Isolation Forest for '%s' on %d samples", self.service, len(vectors))
        return self._metadata

    def _model_dir(self) -> Path:
        return config.MODELS_DIR / self.service

    def save(self) -> None:
        if self._model is None or self._metadata is None:
            raise RuntimeError(f"Cannot save an untrained detector for service '{self.service}'")
        model_dir = self._model_dir()
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, model_dir / "model.joblib")
        with open(model_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self._metadata.to_dict(), f, indent=2)
        log.info("Saved model + metadata for '%s' to %s", self.service, model_dir)

    @classmethod
    def load(cls, service: str) -> "AnomalyDetector":
        detector = cls(service)
        model_dir = detector._model_dir()
        model_path, metadata_path = model_dir / "model.joblib", model_dir / "metadata.json"
        if not model_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(f"No trained model found for service '{service}' at {model_dir}")

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = models.ModelMetadata.from_dict(json.load(f))

        if metadata.feature_schema_version != config.FEATURE_SCHEMA_VERSION or metadata.feature_names != detector.feature_names:
            raise FeatureSchemaMismatchError(
                f"Persisted model for '{service}' was trained on feature schema "
                f"{metadata.feature_schema_version}/{metadata.feature_names}, but the currently "
                f"configured schema is {config.FEATURE_SCHEMA_VERSION}/{detector.feature_names}. "
                f"Retrain before using this model."
            )

        detector._model = joblib.load(model_path)
        detector._metadata = metadata
        return detector

    def score(self, vector: models.FeatureVector) -> models.AnomalyResult:
        if vector.service != self.service:
            raise ValueError(f"Detector for '{self.service}' cannot score a vector for '{vector.service}'")

        if not self.is_trained:
            return models.AnomalyResult(
                service=self.service, timestamp=vector.timestamp, correlation_id=vector.correlation_id,
                status="no_model", anomaly_score=None, is_anomaly=None,
                threshold=config.ANOMALY_SCORE_THRESHOLD, relevant_feature_values=vector.raw_metrics,
                model_version="isolation-forest-v1", feature_schema_version=config.FEATURE_SCHEMA_VERSION,
                reason=f"No trained model loaded for service '{self.service}'",
            )

        if vector.feature_names != self.feature_names:
            raise FeatureSchemaMismatchError(
                f"Vector feature_names {vector.feature_names} does not match this detector's "
                f"schema {self.feature_names} for service '{self.service}'"
            )

        X = np.array([vector.values], dtype=float)
        # sklearn's decision_function: higher = more normal. Negate so higher = more anomalous,
        # matching the intuitive meaning of "anomaly_score" in the structured output.
        raw_score = float(self._model.decision_function(X)[0])
        anomaly_score = -raw_score
        is_anomaly = anomaly_score > config.ANOMALY_SCORE_THRESHOLD

        return models.AnomalyResult(
            service=self.service, timestamp=vector.timestamp, correlation_id=vector.correlation_id,
            status="scored", anomaly_score=round(anomaly_score, 6), is_anomaly=is_anomaly,
            threshold=config.ANOMALY_SCORE_THRESHOLD, relevant_feature_values=vector.raw_metrics,
            model_version=self._metadata.model_version, feature_schema_version=config.FEATURE_SCHEMA_VERSION,
        )
