"""Categories 7 (deterministic dataset splitting), 8 (class/fault distribution across splits), and
9 (strict Memory/Evaluation separation)."""
from __future__ import annotations

from dataset_tools import split


def _make_incidents(fault_type: str, count: int, start: int = 1) -> list[dict]:
    return [{"incident_id": f"inc-{fault_type}-{i:04d}", "fault_type": fault_type} for i in range(start, start + count)]


def test_split_is_deterministic_across_repeated_runs():
    incidents = _make_incidents("memory-leak", 17) + _make_incidents("db-lock", 17)

    memory_a, evaluation_a = split.stratified_split(incidents, memory_fraction=20 / 68, seed=42)
    memory_b, evaluation_b = split.stratified_split(incidents, memory_fraction=20 / 68, seed=42)

    assert [i["incident_id"] for i in memory_a] == [i["incident_id"] for i in memory_b]
    assert [i["incident_id"] for i in evaluation_a] == [i["incident_id"] for i in evaluation_b]


def test_split_different_seed_produces_different_assignment():
    incidents = _make_incidents("memory-leak", 17)

    memory_a, _ = split.stratified_split(incidents, memory_fraction=5 / 17, seed=1)
    memory_b, _ = split.stratified_split(incidents, memory_fraction=5 / 17, seed=2)

    assert {i["incident_id"] for i in memory_a} != {i["incident_id"] for i in memory_b}


def test_split_is_stratified_by_fault_type():
    incidents = (
        _make_incidents("memory-leak", 17) + _make_incidents("db-lock", 17)
        + _make_incidents("auth-key-error", 17) + _make_incidents("notification-latency", 17)
    )

    memory, evaluation = split.stratified_split(incidents, memory_fraction=20 / 68, seed=42)
    summary = split.split_summary(memory, evaluation)

    assert summary["memory_count"] == 20
    assert summary["evaluation_count"] == 48
    for fault_type in ("memory-leak", "db-lock", "auth-key-error", "notification-latency"):
        assert summary["memory_by_fault_type"][fault_type] == 5
        assert summary["evaluation_by_fault_type"][fault_type] == 12


def test_no_incident_id_appears_in_both_sets():
    incidents = _make_incidents("memory-leak", 17) + _make_incidents("db-lock", 17)

    memory, evaluation = split.stratified_split(incidents, memory_fraction=20 / 68, seed=42)

    memory_ids = {i["incident_id"] for i in memory}
    evaluation_ids = {i["incident_id"] for i in evaluation}
    assert memory_ids.isdisjoint(evaluation_ids)


def test_every_incident_lands_in_exactly_one_set():
    incidents = _make_incidents("memory-leak", 17) + _make_incidents("db-lock", 17)

    memory, evaluation = split.stratified_split(incidents, memory_fraction=20 / 68, seed=42)

    assert len(memory) + len(evaluation) == len(incidents)
    assert {i["incident_id"] for i in memory} | {i["incident_id"] for i in evaluation} == {i["incident_id"] for i in incidents}
