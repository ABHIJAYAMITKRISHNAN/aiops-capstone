"""Trains and persists one Isolation Forest per service from Memory-eligible baseline telemetry.

    python -m ai_orchestration.anomaly.train
"""
from __future__ import annotations

import logging

from . import feature_extractor
from .detector import AnomalyDetector
from .. import config

log = logging.getLogger("ai_orchestration.anomaly.train")


def train_all_services() -> dict[str, dict]:
    baseline_records = feature_extractor.load_memory_eligible_baseline_records()
    if not baseline_records:
        raise RuntimeError(
            "No Memory-eligible baseline telemetry found. Build the Week 6 dataset first: "
            "cd dataset-tools && python -m dataset_tools.build_dataset"
        )

    results: dict[str, dict] = {}
    for service in config.SERVICE_FEATURE_SCHEMAS:
        vectors, _matrix, experiment_ids = feature_extractor.feature_matrix_for_service(baseline_records, service)
        if not vectors:
            log.warning("No valid feature vectors for '%s' - skipping (not trained)", service)
            results[service] = {"trained": False, "reason": "no valid feature vectors"}
            continue

        detector = AnomalyDetector(service)
        metadata = detector.train(vectors, training_source_experiment_ids=experiment_ids)
        detector.save()
        results[service] = {"trained": True, "metadata": metadata.to_dict()}

    return results


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    print(json.dumps(train_all_services(), indent=2))
