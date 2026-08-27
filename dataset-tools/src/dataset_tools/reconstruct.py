"""Reconstructs experiment phase timelines from Week 5's raw JSONL.

Phase assignment follows exactly the recipe documented in telemetry/README.md:

- timestamp < FAULT_INJECTED                                   -> NORMAL
- FAULT_INJECTED <= timestamp < (first fault.faultActive=true)  -> FAULT_INTRODUCTION
- fault.faultActive == true (or, if unknown, timestamp in [FAULT_INJECTED, FAULT_RESET))
                                                                 -> FAULT_ACTIVE
- timestamp >= FAULT_RESET                                      -> RECOVERY

Nothing here fabricates values: every number in the resulting phase-metric dicts is a direct
average of real fields captured by Week 5's collector for that specific experiment window.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

CURATED_METRIC_KEYS = [
    "jvm_memory_used_bytes", "jvm_memory_committed_bytes", "jvm_memory_max_bytes",
    "hikaricp_connections_active", "hikaricp_connections_idle", "hikaricp_connections_pending",
    "hikaricp_connections_acquire_seconds_avg",
    "http_server_requests_count", "http_server_requests_error_count", "http_server_requests_avg_duration_ms",
    "http_client_requests_count", "http_client_requests_avg_duration_ms",
    "process_cpu_usage", "system_cpu_usage",
]


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def group_experiments(events: list[dict]) -> list[dict]:
    """Walks the (already time-sorted) events list and pairs up EXPERIMENT_START/END blocks,
    each with its FAULT_INJECTED/FAULT_RESET timestamps if present."""
    experiments: list[dict] = []
    current: Optional[dict] = None

    for event in events:
        kind = event["event"]
        if kind == "EXPERIMENT_START":
            current = {
                "fault_type": event["fault"],
                "service": event.get("service"),
                "experiment_start": event["timestamp"],
                "experiment_end": None,
                "fault_injected_at": None,
                "fault_reset_at": None,
                "inject_response": None,
                "reset_response": None,
            }
        elif current is None:
            continue  # stray event with no open experiment - ignore rather than crash
        elif kind == "FAULT_INJECTED":
            current["fault_injected_at"] = event["timestamp"]
            current["inject_response"] = event.get("response")
        elif kind == "FAULT_RESET":
            current["fault_reset_at"] = event["timestamp"]
            current["reset_response"] = event.get("response")
        elif kind == "EXPERIMENT_END":
            current["experiment_end"] = event["timestamp"]
            experiments.append(current)
            current = None
        # FAULT_INJECT_FAILED / FAULT_RESET_FAILED are intentionally not treated as fatal here;
        # an experiment missing fault_injected_at/fault_reset_at is still returned and callers
        # can decide whether it has enough information to build a full incident.

    return experiments


def _in_window(ts: str, start: Optional[str], end: Optional[str]) -> bool:
    t = _parse_ts(ts)
    if start is not None and t < _parse_ts(start):
        return False
    if end is not None and t >= _parse_ts(end):
        return False
    return True


def assign_phase(record_ts: str, experiment: dict, fault_active: Optional[bool]) -> str:
    injected = experiment.get("fault_injected_at")
    reset = experiment.get("fault_reset_at")

    if injected is None or _parse_ts(record_ts) < _parse_ts(injected):
        return "NORMAL"
    if reset is not None and _parse_ts(record_ts) >= _parse_ts(reset):
        return "RECOVERY"
    # Between injection and reset: FAULT_ACTIVE once the service itself confirms the fault is on;
    # the brief gap before that is FAULT_INTRODUCTION. `fault_active` is None for any record whose
    # own self-reported fault state isn't a meaningful signal for *this* fault (see
    # phase_label_telemetry) - for those, fall back to the same time-window rule used for probes:
    # the injected->reset window is FAULT_ACTIVE, since injection/reset happen synchronously.
    if fault_active is True:
        return "FAULT_ACTIVE"
    if fault_active is False:
        return "FAULT_INTRODUCTION"
    return "FAULT_ACTIVE"  # fault_active unknown/not applicable to this record - time-window rule


def slice_experiment_records(
    experiment: dict,
    telemetry: list[dict],
    probes: list[dict],
) -> tuple[list[dict], list[dict]]:
    start, end = experiment["experiment_start"], experiment["experiment_end"]
    tel = [r for r in telemetry if _in_window(r["timestamp"], start, end)]
    prb = [r for r in probes if _in_window(r["timestamp"], start, end)]
    return tel, prb


def phase_label_telemetry(experiment: dict, telemetry_records: list[dict]) -> list[dict]:
    """Each telemetry record's `fault.faultActive` is that record's *own service's* self-reported
    fault status (from its own /fault-status endpoint) - it only tells us anything about *this*
    experiment's fault when the record's service is the one the fault was actually injected into
    (experiment["service"]). For every other service - notably the symptom service in the two
    cross-service faults (auth-key-error, notification-latency), which never has a fault of its
    own active - that field is always False and must NOT be read as "fault not active yet"; doing
    so previously caused the symptom service's entire FAULT_ACTIVE window to be mislabeled as
    FAULT_INTRODUCTION and silently dropped from fault-phase metrics. So the self-reported flag is
    only trusted for the target service; all other services fall back to the time-window rule."""
    target_service = experiment.get("service")
    labeled = []
    for r in telemetry_records:
        fault_active = None
        if r.get("service") == target_service and r.get("fault") is not None and "faultActive" in r["fault"]:
            fault_active = r["fault"]["faultActive"]
        phase = assign_phase(r["timestamp"], experiment, fault_active)
        labeled.append({**r, "phase": phase})
    return labeled


def phase_label_probes(experiment: dict, probe_records: list[dict]) -> list[dict]:
    labeled = []
    for r in probe_records:
        # Probes don't carry their own fault-status reading; classify by time window only,
        # treating the whole injected->reset window as FAULT_ACTIVE (the simplification is
        # reasonable for probes specifically, since the effect they'd observe - a slow/failing
        # request - only exists once the fault is actually on, which for all four fault
        # mechanisms happens synchronously inside the inject() call itself).
        injected, reset = experiment.get("fault_injected_at"), experiment.get("fault_reset_at")
        if injected is None or _parse_ts(r["timestamp"]) < _parse_ts(injected):
            phase = "NORMAL"
        elif reset is not None and _parse_ts(r["timestamp"]) >= _parse_ts(reset):
            phase = "RECOVERY"
        else:
            phase = "FAULT_ACTIVE"
        labeled.append({**r, "phase": phase})
    return labeled


def average_metrics_by_service(labeled_telemetry: list[dict], phase: str) -> dict[str, dict[str, Optional[float]]]:
    """Per-service average of each curated metric, across records in the given phase."""
    by_service: dict[str, list[dict]] = {}
    for r in labeled_telemetry:
        if r["phase"] != phase or r.get("metrics") is None:
            continue
        by_service.setdefault(r["service"], []).append(r["metrics"])

    result: dict[str, dict[str, Optional[float]]] = {}
    for service, metric_dicts in by_service.items():
        service_result: dict[str, Optional[float]] = {}
        for key in CURATED_METRIC_KEYS:
            values = [m[key] for m in metric_dicts if m.get(key) is not None]
            service_result[key] = round(sum(values) / len(values), 4) if values else None
        result[service] = service_result
    return result


def summarize_probes(labeled_probes: list[dict], phase: str) -> dict:
    phase_probes = [p for p in labeled_probes if p["phase"] == phase]
    if not phase_probes:
        return {"count": 0, "success_rate": None, "avg_duration_ms": None, "notification_status_counts": {}}

    successes = sum(1 for p in phase_probes if p.get("success") is True)
    durations = [p["duration_ms"] for p in phase_probes if p.get("duration_ms") is not None]
    status_counts: dict[str, int] = {}
    for p in phase_probes:
        status = p.get("notification_status") or ("no_response" if not p.get("success") else "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "count": len(phase_probes),
        "success_rate": round(successes / len(phase_probes), 4),
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "notification_status_counts": status_counts,
    }


def collect_errors(labeled_telemetry: list[dict], labeled_probes: list[dict], phase: str) -> list[str]:
    errors = set()
    for r in labeled_telemetry:
        if r["phase"] == phase and r.get("collection_error"):
            errors.add(r["collection_error"])
    for p in labeled_probes:
        if p["phase"] == phase and p.get("error"):
            errors.add(p["error"])
    return sorted(errors)


def sample_correlation_ids(labeled_telemetry: list[dict], labeled_probes: list[dict], phase: str, limit: int = 5) -> list[str]:
    ids = [r["correlation_id"] for r in labeled_telemetry if r["phase"] == phase and r.get("correlation_id")]
    ids += [p["correlation_id"] for p in labeled_probes if p["phase"] == phase and p.get("correlation_id")]
    return ids[:limit]
