"""Categories 3 (Isolation Forest training), 4 (inference), 5 (model persistence/loading),
6 (feature-schema compatibility validation), 7 (normal telemetry behavior), and 8 (known fault
telemetry behavior)."""
from __future__ import annotations

import random

import pytest

from ai_orchestration import config
from ai_orchestration.anomaly.detector import AnomalyDetector, FeatureSchemaMismatchError
from ai_orchestration.anomaly.feature_extractor import extract_features
from ai_orchestration.anomaly.models import FeatureVector


@pytest.fixture(autouse=True)
def isolated_models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    # An explicit, small contamination gives a stable, predictable inlier/outlier boundary for
    # these tests' small synthetic training sets - "auto"'s fixed -0.5 offset (sklearn's default)
    # is tuned for larger, more realistic datasets than a 30-50 row unit-test fixture.
    monkeypatch.setattr(config, "ISOLATION_FOREST_CONTAMINATION", "0.05")


def _normal_vectors(record_factory, n=50):
    # Independently-jittered features (not just one or two) so IsolationForest sees genuine
    # within-class variance rather than several near-constant columns, which is what real
    # multi-metric telemetry looks like even during a healthy baseline window.
    rng = random.Random(42)
    vectors = []
    for _ in range(n):
        record = record_factory(
            jvm_used=40_000_000.0 + rng.uniform(-500_000, 500_000),
            error_count=max(0.0, rng.uniform(-0.3, 0.3)),
            req_count=10.0 + rng.uniform(-2, 2),
        )
        vectors.append(extract_features(record))
    return vectors


def test_train_produces_metadata_with_expected_fields(auth_record_factory):
    vectors = _normal_vectors(auth_record_factory)
    detector = AnomalyDetector("auth-service")

    metadata = detector.train(vectors, training_source_experiment_ids=["auth-key-error-2026-01-01T00:00:00+00:00"])

    assert detector.is_trained
    assert metadata.service == "auth-service"
    assert metadata.training_sample_count == len(vectors)
    assert metadata.feature_names == config.SERVICE_FEATURE_SCHEMAS["auth-service"]
    assert metadata.random_state == config.ISOLATION_FOREST_RANDOM_STATE


def test_train_rejects_empty_vector_list():
    detector = AnomalyDetector("auth-service")
    with pytest.raises(ValueError, match="No training vectors"):
        detector.train([], training_source_experiment_ids=[])


def test_train_rejects_mismatched_feature_names(auth_record_factory):
    vectors = _normal_vectors(auth_record_factory, n=5)
    bad_vector = FeatureVector(service="auth-service", timestamp="t", correlation_id=None,
                                feature_names=["wrong_feature"], values=[1.0])
    detector = AnomalyDetector("auth-service")

    with pytest.raises(FeatureSchemaMismatchError):
        detector.train(vectors + [bad_vector], training_source_experiment_ids=[])


def test_score_on_normal_telemetry_returns_scored_status(auth_record_factory):
    vectors = _normal_vectors(auth_record_factory)
    detector = AnomalyDetector("auth-service")
    detector.train(vectors, training_source_experiment_ids=[])

    normal_record = auth_record_factory(jvm_used=40_000_100.0, req_count=10.0)
    fv = extract_features(normal_record)

    result = detector.score(fv)

    assert result.status == "scored"
    assert result.is_anomaly is not None
    assert result.anomaly_score is not None
    assert result.relevant_feature_values["jvm_memory_used_bytes"] == 40_000_100.0


def test_score_on_extreme_fault_like_telemetry_is_flagged_anomalous(auth_record_factory):
    """Simulates known-fault-shaped telemetry: trained on tight normal-range JVM memory, scored
    against a value far outside that range (as memory-leak fault telemetry would look like on the
    root-cause service) - the model must flag it, not silently score it as normal."""
    vectors = _normal_vectors(auth_record_factory)
    detector = AnomalyDetector("auth-service")
    detector.train(vectors, training_source_experiment_ids=[])

    fault_like_record = auth_record_factory(jvm_used=4_000_000_000.0, error_count=50.0, req_count=500.0)
    fv = extract_features(fault_like_record)

    result = detector.score(fv)

    assert result.status == "scored"
    assert result.is_anomaly is True
    assert result.anomaly_score > result.threshold


def test_score_raises_on_wrong_service_vector(auth_record_factory, payment_record_factory):
    vectors = _normal_vectors(auth_record_factory)
    detector = AnomalyDetector("auth-service")
    detector.train(vectors, training_source_experiment_ids=[])

    payment_fv = extract_features(payment_record_factory())
    with pytest.raises(ValueError, match="cannot score"):
        detector.score(payment_fv)


def test_score_with_no_trained_model_returns_no_model_status(auth_record_factory):
    detector = AnomalyDetector("auth-service")
    fv = extract_features(auth_record_factory())

    result = detector.score(fv)

    assert result.status == "no_model"
    assert result.is_anomaly is None


def test_save_and_load_round_trip_preserves_scoring_behavior(auth_record_factory):
    vectors = _normal_vectors(auth_record_factory)
    detector = AnomalyDetector("auth-service")
    detector.train(vectors, training_source_experiment_ids=["exp-1"])
    detector.save()

    loaded = AnomalyDetector.load("auth-service")
    record = auth_record_factory(jvm_used=40_000_100.0)
    fv = extract_features(record)

    original_result = detector.score(fv)
    loaded_result = loaded.score(fv)

    assert loaded_result.status == "scored"
    assert loaded_result.anomaly_score == original_result.anomaly_score
    assert loaded_result.is_anomaly == original_result.is_anomaly


def test_load_raises_file_not_found_when_no_model_persisted():
    with pytest.raises(FileNotFoundError):
        AnomalyDetector.load("auth-service")


def test_load_raises_schema_mismatch_when_persisted_schema_differs(auth_record_factory, monkeypatch):
    vectors = _normal_vectors(auth_record_factory)
    detector = AnomalyDetector("auth-service")
    detector.train(vectors, training_source_experiment_ids=[])
    detector.save()

    # Simulate the configured schema changing after this model was trained (e.g. a new metric
    # added to auth-service's schema in a future week) - load() must refuse, not misalign columns.
    monkeypatch.setitem(config.SERVICE_FEATURE_SCHEMAS, "auth-service",
                         config.SERVICE_FEATURE_SCHEMAS["auth-service"] + ["a_new_metric"])

    with pytest.raises(FeatureSchemaMismatchError):
        AnomalyDetector.load("auth-service")
