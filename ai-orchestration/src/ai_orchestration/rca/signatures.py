"""Deterministic fault-signature matching: which known fault_type, if any, does an anomalous
telemetry record's evidence look like?

Every threshold here is traceable to a real, documented value from Week 6's dataset tooling - not
an arbitrary magic number:
- JVM memory thresholds are derived from `synthetic_model.OBSERVED_BASELINE_RANGES`, itself
  anchored to values actually observed live in Week 5/6's real experiments.
- The HikariCP and error-count thresholds reflect the empirically-verified real baseline of 0
  (see dataset-tools/README.md and config.py's FAULT_SERVICE_MAP comment).
- The notification-latency threshold is set well below the real client-side timeout
  (`dataset_tools.config.FAULT_DEFAULTS["notification-latency"]["client_timeout_ms"]`) so it
  triggers on the *symptom* (elevated duration) without requiring the request to have actually
  failed outright.

This module answers "which fault does this look like", using exactly the same
fault_type -> (root_cause_service, symptom_service) mapping Week 6 already established
(`dataset_tools.config.FAULT_SERVICE_MAP`) - reused, not re-derived.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import config as ai_config

ai_config.ensure_sibling_packages_importable()

from dataset_tools import config as dt_config  # noqa: E402
from dataset_tools.incidents import _primary_metric_key  # noqa: E402
from dataset_tools.synthetic_model import OBSERVED_BASELINE_RANGES  # noqa: E402


@dataclass(frozen=True)
class FaultSignature:
    fault_type: str
    primary_metric: str
    symptom_service: str  # the service whose telemetry record must carry the signal
    elevated_if_above: float
    threshold_basis: str  # human-readable citation of where the threshold comes from


def _memory_leak_threshold() -> float:
    # 1.3x the real observed upper bound of payment-service's normal baseline range.
    return OBSERVED_BASELINE_RANGES["payment-service"]["jvm_memory_used_bytes"][1] * 1.3


FAULT_SIGNATURES: list[FaultSignature] = [
    FaultSignature(
        fault_type="memory-leak", primary_metric=_primary_metric_key("memory-leak"),
        symptom_service="payment-service", elevated_if_above=_memory_leak_threshold(),
        threshold_basis="1.3x OBSERVED_BASELINE_RANGES['payment-service']['jvm_memory_used_bytes'] upper bound",
    ),
    FaultSignature(
        fault_type="db-lock", primary_metric=_primary_metric_key("db-lock"),
        symptom_service="ledger-service", elevated_if_above=1.0,
        threshold_basis="normal baseline is 0 active HikariCP connections (empirically verified)",
    ),
    FaultSignature(
        fault_type="auth-key-error", primary_metric=_primary_metric_key("auth-key-error"),
        symptom_service="payment-service", elevated_if_above=0.5,
        threshold_basis="normal baseline is 0 HTTP server errors (empirically verified)",
    ),
    FaultSignature(
        fault_type="notification-latency", primary_metric=_primary_metric_key("notification-latency"),
        symptom_service="payment-service", elevated_if_above=500.0,
        threshold_basis="well below FAULT_DEFAULTS['notification-latency']['client_timeout_ms']=5000, "
                         "well above the real observed normal baseline of 10-60ms",
    ),
]


@dataclass(frozen=True)
class SignatureMatch:
    fault_type: str
    root_cause_service: str
    symptom_service: str
    matched_metric: str
    observed_value: float
    threshold: float
    excess_ratio: float  # observed / threshold - used to break ties between multiple matches


def match_signatures(service: str, relevant_feature_values: dict) -> list[SignatureMatch]:
    """Returns every fault signature whose primary metric is present, applicable to `service`, and
    exceeds its documented elevated-threshold - sorted by excess_ratio descending (best match
    first). Empty list means no known signature matched (see RootCauseAnalysis's
    "fallback_unknown"/"rag_only" determination methods for what happens then)."""
    matches: list[SignatureMatch] = []
    for sig in FAULT_SIGNATURES:
        if sig.symptom_service != service:
            continue
        value = relevant_feature_values.get(sig.primary_metric)
        if value is None or value <= sig.elevated_if_above:
            continue
        mapping = dt_config.FAULT_SERVICE_MAP[sig.fault_type]
        matches.append(SignatureMatch(
            fault_type=sig.fault_type,
            root_cause_service=mapping["root_cause_service"],
            symptom_service=mapping["symptom_service"],
            matched_metric=sig.primary_metric,
            observed_value=value,
            threshold=sig.elevated_if_above,
            excess_ratio=value / sig.elevated_if_above,
        ))
    return sorted(matches, key=lambda m: m.excess_ratio, reverse=True)


def baseline_reference(service: str, metric_name: str) -> Optional[float]:
    """Documented baseline reference for a service/metric pair, for MetricAnomaly's
    `baseline_reference` field - the midpoint of the real observed range, or None if this
    service/metric combination has no documented baseline (only JVM memory metrics are
    documented this way currently; other metrics simply get baseline_reference=None rather than a
    fabricated number)."""
    service_ranges = OBSERVED_BASELINE_RANGES.get(service, {})
    metric_range = service_ranges.get(metric_name)
    if metric_range is None:
        return None
    return (metric_range[0] + metric_range[1]) / 2
