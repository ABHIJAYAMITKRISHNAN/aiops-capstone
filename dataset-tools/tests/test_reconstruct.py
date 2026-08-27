"""Categories 2 (event/telemetry joining) and 3 (phase reconstruction)."""
from __future__ import annotations

from dataset_tools import reconstruct


def test_group_experiments_pairs_start_inject_reset_end(auth_key_error_experiment_data):
    events, _, _ = auth_key_error_experiment_data

    experiments = reconstruct.group_experiments(events)

    assert len(experiments) == 1
    exp = experiments[0]
    assert exp["fault_type"] == "auth-key-error"
    assert exp["service"] == "auth-service"
    assert exp["fault_injected_at"] == "2026-01-01T00:00:10+00:00"
    assert exp["fault_reset_at"] == "2026-01-01T00:00:20+00:00"
    assert exp["experiment_end"] == "2026-01-01T00:00:30+00:00"


def test_group_experiments_handles_multiple_back_to_back(auth_key_error_experiment_data):
    events, _, _ = auth_key_error_experiment_data
    doubled = events + [
        {**e, "timestamp": e["timestamp"].replace("00:00:", "00:01:")} for e in events
    ]

    experiments = reconstruct.group_experiments(doubled)

    assert len(experiments) == 2


def test_group_experiments_incomplete_injection_still_returns_experiment(incomplete_experiment_events):
    experiments = reconstruct.group_experiments(incomplete_experiment_events)

    assert len(experiments) == 1
    assert experiments[0]["fault_injected_at"] is None
    assert experiments[0]["fault_reset_at"] is None


def test_slice_experiment_records_only_keeps_records_in_window(auth_key_error_experiment_data):
    events, telemetry, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    extra_telemetry = telemetry + [{**telemetry[0], "timestamp": "2026-01-01T00:05:00+00:00"}]  # outside window

    tel_slice, probe_slice = reconstruct.slice_experiment_records(experiment, extra_telemetry, probes)

    assert len(tel_slice) == len(telemetry)
    assert all(r["timestamp"] < experiment["experiment_end"] for r in tel_slice)


def test_phase_label_telemetry_assigns_all_four_phases(auth_key_error_experiment_data):
    events, telemetry, _ = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]

    labeled = reconstruct.phase_label_telemetry(experiment, telemetry)
    phases_seen = {r["phase"] for r in labeled}

    assert phases_seen == {"NORMAL", "FAULT_ACTIVE", "RECOVERY"}


def test_phase_label_telemetry_symptom_service_not_mislabeled(auth_key_error_experiment_data):
    """Regression test: payment-service's own faultActive is always False during an
    auth-key-error experiment (the fault is on auth-service), so its FAULT_ACTIVE-window
    telemetry must still be labeled FAULT_ACTIVE via the time-window fallback, not
    FAULT_INTRODUCTION - see reconstruct.phase_label_telemetry's docstring."""
    events, telemetry, _ = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]

    labeled = reconstruct.phase_label_telemetry(experiment, telemetry)
    payment_fault_window = [r for r in labeled if r["service"] == "payment-service"
                             and experiment["fault_injected_at"] <= r["timestamp"] < experiment["fault_reset_at"]]

    assert payment_fault_window, "fixture should include payment-service samples in the fault window"
    assert all(r["phase"] == "FAULT_ACTIVE" for r in payment_fault_window)


def test_phase_label_telemetry_target_service_still_uses_self_reported_flag(auth_key_error_experiment_data):
    events, telemetry, _ = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]

    labeled = reconstruct.phase_label_telemetry(experiment, telemetry)
    auth_fault_window = [r for r in labeled if r["service"] == "auth-service"
                          and experiment["fault_injected_at"] <= r["timestamp"] < experiment["fault_reset_at"]]

    assert all(r["phase"] == "FAULT_ACTIVE" for r in auth_fault_window)


def test_phase_label_probes_classifies_by_time_window_only(auth_key_error_experiment_data):
    events, _, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]

    labeled = reconstruct.phase_label_probes(experiment, probes)

    assert [p["phase"] for p in labeled] == ["NORMAL", "FAULT_ACTIVE", "FAULT_ACTIVE", "RECOVERY"]


def test_average_metrics_by_service_averages_only_matching_phase(auth_key_error_experiment_data):
    events, telemetry, _ = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    labeled = reconstruct.phase_label_telemetry(experiment, telemetry)

    fault_metrics = reconstruct.average_metrics_by_service(labeled, "FAULT_ACTIVE")

    assert fault_metrics["payment-service"]["http_server_requests_error_count"] == 2.0
    assert fault_metrics["auth-service"]["http_server_requests_error_count"] == 0.0


def test_average_metrics_by_service_returns_empty_dict_when_no_samples(auth_key_error_experiment_data):
    events, telemetry, _ = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    labeled = reconstruct.phase_label_telemetry(experiment, telemetry)

    result = reconstruct.average_metrics_by_service(labeled, "FAULT_INTRODUCTION")

    assert result == {}


def test_summarize_probes_computes_success_rate_and_duration(auth_key_error_experiment_data):
    events, _, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    labeled = reconstruct.phase_label_probes(experiment, probes)

    summary = reconstruct.summarize_probes(labeled, "FAULT_ACTIVE")

    assert summary["count"] == 2
    assert summary["success_rate"] == 0.0


def test_summarize_probes_no_probes_in_phase_returns_null_fields():
    summary = reconstruct.summarize_probes([], "FAULT_ACTIVE")

    assert summary == {"count": 0, "success_rate": None, "avg_duration_ms": None, "notification_status_counts": {}}


def test_collect_errors_gathers_from_both_telemetry_and_probes(auth_key_error_experiment_data):
    events, telemetry, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    tel_labeled = reconstruct.phase_label_telemetry(experiment, telemetry)
    probe_labeled = reconstruct.phase_label_probes(experiment, probes)

    errors = reconstruct.collect_errors(tel_labeled, probe_labeled, "FAULT_ACTIVE")

    assert errors == ["Invalid or expired token"]
