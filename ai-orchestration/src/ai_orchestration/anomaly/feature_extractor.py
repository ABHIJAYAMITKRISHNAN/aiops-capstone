"""Deterministic numerical feature extraction from raw Week 5 telemetry records, and selection of
which raw telemetry is legitimate Isolation Forest *training* data.

Two separate concerns, both here because they share the same "what counts as a valid record"
logic:

1. `extract_features(record)` - turns ONE raw telemetry record (as collector.py writes it) into a
   FeatureVector for that service, or None if the record can't produce one (collection error, or
   a legitimately-applicable metric is missing this cycle). Used identically for both training and
   inference, so training and scoring can never silently disagree about what a "valid" record is.

2. `load_memory_eligible_baseline_records()` - selects which *raw* telemetry is allowed into
   training at all: NORMAL/RECOVERY-phase telemetry from real experiments whose reconstructed
   incident landed in the Memory set. Synthetic incidents have no raw telemetry behind them (they
   are generated dicts - see dataset_tools/synthetic_model.py) so they can never contribute training
   rows; real experiments whose incident is in the Evaluation set are excluded by construction,
   the same enforcement pattern dataset_tools/chroma_store.py uses for ChromaDB (only ever read
   the Memory-set file's IDs; never open the Evaluation file for anything that feeds training).
"""
from __future__ import annotations

import logging
from typing import Optional

from . import models
from .. import config

config.ensure_sibling_packages_importable()

from dataset_tools import config as dt_config, ingest as dt_ingest, reconstruct as dt_reconstruct  # noqa: E402

log = logging.getLogger("ai_orchestration.anomaly.feature_extractor")


def extract_features(record: dict) -> Optional[models.FeatureVector]:
    """`record` is one raw telemetry record: {timestamp, service, correlation_id, health, metrics,
    fault, collection_error}. Returns None (never a fabricated/imputed vector) if:
    - the service isn't one we have a feature schema for,
    - metrics collection failed this cycle (metrics is None / collection_error is set), or
    - any of *that service's own applicable* features is None this cycle.
    """
    service = record.get("service")
    schema = config.SERVICE_FEATURE_SCHEMAS.get(service)
    if schema is None:
        return None

    metrics = record.get("metrics")
    if not metrics:
        return None

    values: list[float] = []
    raw_metrics: dict = {}
    for name in schema:
        value = metrics.get(name)
        if value is None:
            return None  # an applicable metric missing this cycle - real gap, don't impute
        values.append(float(value))
        raw_metrics[name] = value

    return models.FeatureVector(
        service=service,
        timestamp=record["timestamp"],
        correlation_id=record.get("correlation_id"),
        feature_names=list(schema),
        values=values,
        raw_metrics=raw_metrics,
    )


def _experiment_id(fault_type: str, experiment_start: str) -> str:
    # Must exactly match incidents.build_incident_from_experiment's convention so the two sides
    # (raw experiments here, reconstructed incidents in dataset-tools) refer to the same thing.
    return f"{fault_type}-{experiment_start}"


def _memory_eligible_experiment_ids(memory_incidents: list[dict]) -> set[str]:
    """`memory_incidents` must come from the Memory file ONLY - config.EVALUATION_INCIDENTS_FILE
    is never opened anywhere in this module, matching chroma_store.py's leakage-prevention shape."""
    return {
        inc["experiment_id"]
        for inc in memory_incidents
        if inc.get("data_source") == "real" and inc.get("experiment_id")
    }


def load_memory_eligible_baseline_records(
    events: Optional[list[dict]] = None,
    telemetry: Optional[list[dict]] = None,
    memory_incidents: Optional[list[dict]] = None,
) -> list[dict]:
    """Returns raw telemetry records from NORMAL and RECOVERY phases of real experiments whose
    incident is in the Memory set - i.e. telemetry captured while no fault was active, from
    experiments this project has already decided are safe to learn from. Both phases represent
    non-faulty system behavior (RECOVERY = fault already reset).

    `events`, `telemetry`, and `memory_incidents` are all optional and default to loading from
    disk (real Week 5 telemetry + the real Week 6 Memory file) - they're accepted as explicit
    parameters, rather than only ever read from module-level config, so this function's dataset-
    separation behavior can be unit-tested against hand-built fixtures without touching disk, and
    so a caller can never accidentally point it at the Evaluation file by construction (there is
    no `evaluation_incidents` parameter at all)."""
    events = events if events is not None else dt_ingest.load_events()
    telemetry = telemetry if telemetry is not None else dt_ingest.load_telemetry()
    memory_incidents = memory_incidents if memory_incidents is not None else dt_ingest.read_jsonl(dt_config.MEMORY_INCIDENTS_FILE)
    eligible_ids = _memory_eligible_experiment_ids(memory_incidents)

    experiments = dt_reconstruct.group_experiments(events)
    baseline_records: list[dict] = []
    used_experiment_ids: list[str] = []

    for experiment in experiments:
        if experiment.get("fault_injected_at") is None or experiment.get("fault_reset_at") is None:
            continue
        exp_id = _experiment_id(experiment["fault_type"], experiment["experiment_start"])
        if exp_id not in eligible_ids:
            continue

        tel_slice, _ = dt_reconstruct.slice_experiment_records(experiment, telemetry, probes=[])
        labeled = dt_reconstruct.phase_label_telemetry(experiment, tel_slice)
        # Tag each record with the experiment it came from (not part of the original telemetry
        # schema) purely so train.py can record an audit trail of which experiments contributed
        # to each service's model - see ModelMetadata.training_source_experiment_ids.
        phase_records = [{**r, "_experiment_id": exp_id} for r in labeled if r["phase"] in ("NORMAL", "RECOVERY")]
        baseline_records.extend(phase_records)
        used_experiment_ids.append(exp_id)

    log.info(
        "Loaded %d baseline (NORMAL/RECOVERY) telemetry records from %d Memory-eligible real experiments: %s",
        len(baseline_records), len(used_experiment_ids), used_experiment_ids,
    )
    return baseline_records


def feature_matrix_for_service(records: list[dict], service: str) -> tuple[list[models.FeatureVector], list[list[float]], list[str]]:
    """Extracts every valid FeatureVector for `service` out of a batch of raw records. Returns the
    vectors, the corresponding raw value matrix, and the experiment IDs that contributed each
    row (all three lists index-aligned) - `_experiment_id`, when present, was tagged on by
    `load_memory_eligible_baseline_records`; absent for records from any other source (e.g. a
    single live telemetry record passed straight to `extract_features` for inference)."""
    vectors: list[models.FeatureVector] = []
    matrix: list[list[float]] = []
    experiment_ids: list[str] = []
    for record in records:
        if record.get("service") != service:
            continue
        fv = extract_features(record)
        if fv is None:
            continue
        vectors.append(fv)
        matrix.append(fv.values)
        experiment_ids.append(record.get("_experiment_id"))
    return vectors, matrix, experiment_ids
