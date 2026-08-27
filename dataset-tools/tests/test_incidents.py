"""Categories 4 (incident construction), 5 (metric deltas), 6 (fault labeling), and 13 (handling
incomplete/partial telemetry)."""
from __future__ import annotations

from dataset_tools import config, incidents, reconstruct


def test_compute_deltas_only_includes_pairs_present_in_both():
    baseline = {"svc-a": {"m1": 10.0, "m2": 5.0}, "svc-b": {"m1": 1.0}}
    fault = {"svc-a": {"m1": 15.0}, "svc-c": {"m1": 99.0}}  # m2 missing in fault; svc-b/svc-c one-sided

    deltas = incidents.compute_deltas(baseline, fault)

    assert deltas == {"svc-a": {"m1": 5.0}}


def test_build_incident_from_experiment_produces_complete_record(auth_key_error_experiment_data):
    events, telemetry, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]

    incident = incidents.build_incident_from_experiment(experiment, telemetry, probes, incident_id="inc-test-1")

    assert incident is not None
    assert incident["incident_id"] == "inc-test-1"
    assert incident["data_source"] == "real"
    assert incident["fault_type"] == "auth-key-error"
    # fault labeling: root cause vs symptom must be looked up from config, not guessed
    assert incident["root_cause_service"] == "auth-service"
    assert incident["symptom_service"] == "payment-service"
    assert set(incident["affected_services"]) == {"auth-service", "payment-service"}
    for required_key in (
        "start_time", "end_time", "phases", "baseline_metrics", "fault_metrics", "recovery_metrics",
        "metric_deltas", "payment_probe_summary", "errors_observed", "correlation_ids",
        "fault_configuration", "severity", "root_cause_description", "symptom_description",
        "summary", "postmortem_text",
    ):
        assert required_key in incident, f"missing {required_key}"


def test_build_incident_symptom_service_metrics_present_not_dropped(auth_key_error_experiment_data):
    """Regression test for the phase-mislabeling bug: the symptom service's fault-phase metrics
    must be present (not None) once reconstruct.py's cross-service fix is applied."""
    events, telemetry, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]

    incident = incidents.build_incident_from_experiment(experiment, telemetry, probes, incident_id="inc-test-1")

    assert incident["fault_metrics"].get("payment-service") is not None
    assert incident["severity"] != "unknown"


def test_build_incident_postmortem_text_contains_full_content_for_same_service_fault(auth_key_error_experiment_data):
    """Regression test for the postmortem_text ternary-precedence bug: even for a fault type whose
    root_cause_service == symptom_service, the full timeline/root-cause/symptom text must survive,
    not just the closing sentence."""
    events, telemetry, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    # Force a same-service scenario using db-lock's real mapping (root == symptom == ledger-service).
    experiment["fault_type"] = "db-lock"
    experiment["service"] = "ledger-service"

    incident = incidents.build_incident_from_experiment(experiment, telemetry, probes, incident_id="inc-test-2")

    assert incident is not None
    assert "Timeline:" in incident["postmortem_text"]
    assert "Root cause:" in incident["postmortem_text"]
    assert "Symptom:" in incident["postmortem_text"]


def test_build_incident_returns_none_when_fault_never_injected(incomplete_experiment_events):
    experiment = reconstruct.group_experiments(incomplete_experiment_events)[0]

    incident = incidents.build_incident_from_experiment(experiment, [], [], incident_id="inc-test-3")

    assert incident is None


def test_build_incident_returns_none_for_unknown_fault_type(auth_key_error_experiment_data):
    events, telemetry, probes = auth_key_error_experiment_data
    experiment = reconstruct.group_experiments(events)[0]
    experiment["fault_type"] = "not-a-real-fault"

    incident = incidents.build_incident_from_experiment(experiment, telemetry, probes, incident_id="inc-test-4")

    assert incident is None


def test_fault_service_map_covers_all_four_fault_types():
    assert set(config.FAULT_SERVICE_MAP.keys()) == set(config.FAULT_TYPES)
    for fault_type, mapping in config.FAULT_SERVICE_MAP.items():
        assert mapping["root_cause_service"] in config.SERVICES
        assert mapping["symptom_service"] in config.SERVICES


def test_cross_service_faults_have_different_root_and_symptom_service():
    # Empirically verified against real telemetry (see config.py's FAULT_SERVICE_MAP comment):
    # auth-key-error and notification-latency are cross-service; memory-leak and db-lock are not.
    assert config.FAULT_SERVICE_MAP["auth-key-error"]["root_cause_service"] != config.FAULT_SERVICE_MAP["auth-key-error"]["symptom_service"]
    assert config.FAULT_SERVICE_MAP["notification-latency"]["root_cause_service"] != config.FAULT_SERVICE_MAP["notification-latency"]["symptom_service"]
    assert config.FAULT_SERVICE_MAP["memory-leak"]["root_cause_service"] == config.FAULT_SERVICE_MAP["memory-leak"]["symptom_service"]
    assert config.FAULT_SERVICE_MAP["db-lock"]["root_cause_service"] == config.FAULT_SERVICE_MAP["db-lock"]["symptom_service"]


def test_estimate_severity_unknown_when_delta_missing():
    severity = incidents.estimate_severity("memory-leak", deltas={}, probe_summary_fault={})

    assert severity == "unknown"


def test_estimate_severity_notification_latency_uses_probe_success_rate():
    high = incidents.estimate_severity("notification-latency", deltas={}, probe_summary_fault={"success_rate": 0.1})
    low = incidents.estimate_severity("notification-latency", deltas={}, probe_summary_fault={"success_rate": 1.0})

    assert high == "high"
    assert low == "low"
