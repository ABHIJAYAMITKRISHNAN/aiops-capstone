"""Categories 10 (ChromaDB indexing only Memory records), 11 (evaluation IDs rejected from
indexing), 12 (retrieval returns valid Memory incidents), and 14 (handling unavailable
services/collection errors).

Uses a real local ChromaDB PersistentClient pointed at a pytest tmp_path (not mocked) - Week 6's
ChromaDB usage is entirely local/offline once the bundled embedding model is cached, so this is
fast and hermetic per test.
"""
from __future__ import annotations

import pytest

from dataset_tools import chroma_store, config, ingest


def _incident(incident_id: str, fault_type: str = "memory-leak", text: str | None = None) -> dict:
    return {
        "incident_id": incident_id,
        "fault_type": fault_type,
        "root_cause_service": "payment-service",
        "symptom_service": "payment-service",
        "severity": "medium",
        "data_source": "synthetic",
        "postmortem_text": text or f"Incident {incident_id}: {fault_type} on payment-service, JVM heap usage rising.",
    }


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "MEMORY_INCIDENTS_FILE", tmp_path / "memory_incidents.jsonl")
    monkeypatch.setattr(config, "EVALUATION_INCIDENTS_FILE", tmp_path / "evaluation_incidents.jsonl")
    monkeypatch.setattr(config, "CHROMA_COLLECTION_NAME", f"test_collection_{tmp_path.name}")
    return tmp_path


def test_build_collection_indexes_only_memory_incidents(isolated_store):
    memory = [_incident("mem-1"), _incident("mem-2")]
    evaluation = [_incident("eval-1"), _incident("eval-2")]
    ingest.write_jsonl(memory, config.MEMORY_INCIDENTS_FILE)
    ingest.write_jsonl(evaluation, config.EVALUATION_INCIDENTS_FILE)

    collection = chroma_store.build_collection()

    assert collection.count() == 2
    assert set(collection.get()["ids"]) == {"mem-1", "mem-2"}


def test_build_collection_raises_if_evaluation_id_leaks_into_memory_file(isolated_store):
    """Defense-in-depth check: even if the Memory file were accidentally contaminated with an
    incident ID that also appears in the Evaluation file, build_collection must refuse rather than
    silently index it - this is the code-level enforcement the task requires, not just convention."""
    memory = [_incident("mem-1"), _incident("shared-id")]  # "shared-id" wrongly present in both
    evaluation = [_incident("eval-1"), _incident("shared-id")]
    ingest.write_jsonl(memory, config.MEMORY_INCIDENTS_FILE)
    ingest.write_jsonl(evaluation, config.EVALUATION_INCIDENTS_FILE)

    with pytest.raises(chroma_store.EvaluationLeakageError):
        chroma_store.build_collection()


def test_validate_no_leakage_passes_on_clean_split(isolated_store):
    ingest.write_jsonl([_incident("mem-1")], config.MEMORY_INCIDENTS_FILE)
    ingest.write_jsonl([_incident("eval-1")], config.EVALUATION_INCIDENTS_FILE)
    chroma_store.build_collection()

    assert chroma_store.validate_no_leakage() is True


def test_query_similar_returns_only_memory_incident_ids(isolated_store):
    memory = [
        _incident("mem-mem-leak", fault_type="memory-leak", text="payment-service JVM heap memory usage rising steadily during the fault window"),
        _incident("mem-db-lock", fault_type="db-lock", text="ledger-service HikariCP connection pool exhausted, connections held"),
    ]
    evaluation = [_incident("eval-1", fault_type="memory-leak")]
    ingest.write_jsonl(memory, config.MEMORY_INCIDENTS_FILE)
    ingest.write_jsonl(evaluation, config.EVALUATION_INCIDENTS_FILE)
    chroma_store.build_collection()

    results = chroma_store.query_similar("JVM heap memory usage growing on payment service", n_results=2)

    memory_ids = {"mem-mem-leak", "mem-db-lock"}
    assert all(r["incident_id"] in memory_ids for r in results)
    assert results[0]["incident_id"] == "mem-mem-leak"  # closer semantic match should rank first


def test_query_similar_never_returns_evaluation_ids(isolated_store):
    memory = [_incident("mem-1", text="payment service memory leak, JVM heap grew")]
    evaluation = [_incident("eval-1", text="payment service memory leak, JVM heap grew")]  # near-identical text
    ingest.write_jsonl(memory, config.MEMORY_INCIDENTS_FILE)
    ingest.write_jsonl(evaluation, config.EVALUATION_INCIDENTS_FILE)
    chroma_store.build_collection()

    results = chroma_store.query_similar("payment service memory leak JVM heap", n_results=5)

    assert all(r["incident_id"] != "eval-1" for r in results)


def test_build_collection_raises_clear_error_when_memory_file_missing(isolated_store):
    # config.MEMORY_INCIDENTS_FILE was never written - simulates the dataset build step having
    # been skipped, which must fail loudly rather than silently building an empty collection.
    with pytest.raises(RuntimeError, match="No memory incidents found"):
        chroma_store.build_collection()


def test_validate_no_leakage_tolerates_missing_evaluation_file(isolated_store):
    # Evaluation file absent (e.g. not yet generated) must not crash validation - there is simply
    # nothing to check leakage against yet.
    ingest.write_jsonl([_incident("mem-1")], config.MEMORY_INCIDENTS_FILE)
    chroma_store.build_collection()

    assert chroma_store.validate_no_leakage() is True
