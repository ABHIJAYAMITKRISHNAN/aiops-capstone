"""RAG category: retrieval against a real, isolated ChromaDB collection (not mocked) - mirrors
dataset-tools/tests/test_chroma_store.py's isolation pattern (monkeypatch dataset_tools.config
paths to a pytest tmp_path) so these tests never touch the project's real Memory collection."""
from __future__ import annotations

import pytest

from ai_orchestration import config as ai_config
from ai_orchestration.rag import retriever

ai_config.ensure_sibling_packages_importable()

from dataset_tools import chroma_store, config as dt_config, ingest as dt_ingest  # noqa: E402


def _incident(incident_id: str, fault_type: str, root: str, symptom: str, text: str) -> dict:
    return {
        "incident_id": incident_id, "fault_type": fault_type, "root_cause_service": root,
        "symptom_service": symptom, "severity": "medium", "data_source": "synthetic",
        "postmortem_text": text,
    }


@pytest.fixture
def isolated_chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(dt_config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(dt_config, "MEMORY_INCIDENTS_FILE", tmp_path / "memory_incidents.jsonl")
    monkeypatch.setattr(dt_config, "EVALUATION_INCIDENTS_FILE", tmp_path / "evaluation_incidents.jsonl")
    monkeypatch.setattr(dt_config, "CHROMA_COLLECTION_NAME", f"test_collection_{tmp_path.name}")
    return tmp_path


def test_build_query_text_includes_service_and_metrics_and_llm_summary():
    query = retriever.build_query_text(
        "payment-service", {"jvm_memory_used_bytes": 500_000_000.0, "process_cpu_usage": 0.01},
        llm_abnormal_summary="Memory usage is unusually high.",
    )

    assert "payment-service" in query
    assert "jvm_memory_used_bytes=500000000.0" in query
    assert "Memory usage is unusually high." in query


def test_retrieval_queries_memory_collection_successfully(isolated_chroma):
    memory = [
        _incident("mem-1", "memory-leak", "payment-service", "payment-service",
                  "payment-service JVM heap memory usage rising steadily during the incident"),
        _incident("mem-2", "db-lock", "ledger-service", "ledger-service",
                  "ledger-service HikariCP connection pool exhausted"),
    ]
    dt_ingest.write_jsonl(memory, dt_config.MEMORY_INCIDENTS_FILE)
    dt_ingest.write_jsonl([], dt_config.EVALUATION_INCIDENTS_FILE)
    chroma_store.build_collection()

    result = retriever.retrieve_similar_incidents("JVM heap memory usage growing on payment service")

    assert result.status == "retrieved"
    assert len(result.incidents) >= 1
    assert result.incidents[0].incident_id == "mem-1"
    assert result.source_collection == dt_config.CHROMA_COLLECTION_NAME


def test_evaluation_incidents_are_never_returned(isolated_chroma):
    """Defense-in-depth: even if a build-time bug somehow got an Evaluation ID into the collection,
    retrieve_similar_incidents() must filter it out before it reaches the RCA stage."""
    memory = [_incident("mem-1", "memory-leak", "payment-service", "payment-service", "payment-service memory leak")]
    evaluation = [_incident("eval-1", "memory-leak", "payment-service", "payment-service", "payment-service memory leak, evaluation only")]
    dt_ingest.write_jsonl(memory, dt_config.MEMORY_INCIDENTS_FILE)
    dt_ingest.write_jsonl(evaluation, dt_config.EVALUATION_INCIDENTS_FILE)
    chroma_store.build_collection()

    result = retriever.retrieve_similar_incidents("payment service memory leak", n_results=5)

    assert all(inc.incident_id != "eval-1" for inc in result.incidents)


def test_retriever_own_filter_rejects_an_evaluation_id_even_if_chromadb_returned_it(isolated_chroma, monkeypatch):
    """Directly exercises retriever.py's own defense-in-depth filter (independent of
    chroma_store.py's build-time enforcement, which this test bypasses on purpose by mocking
    query_similar to simulate a hypothetical future bug that let an Evaluation ID into the
    collection)."""
    dt_ingest.write_jsonl(
        [_incident("eval-leaked", "memory-leak", "payment-service", "payment-service", "leaked")],
        dt_config.EVALUATION_INCIDENTS_FILE,
    )
    monkeypatch.setattr(chroma_store, "query_similar", lambda query_text, n_results=3: [
        {"incident_id": "eval-leaked", "distance": 0.05,
         "metadata": {"fault_type": "memory-leak", "root_cause_service": "payment-service",
                      "symptom_service": "payment-service", "severity": "high", "data_source": "synthetic"},
         "postmortem_text": "leaked"},
    ])

    result = retriever.retrieve_similar_incidents("anything")

    assert all(inc.incident_id != "eval-leaked" for inc in result.incidents)
    assert result.status == "empty"


def test_empty_collection_returns_empty_status(isolated_chroma, monkeypatch):
    monkeypatch.setattr(chroma_store, "query_similar", lambda query_text, n_results=3: [])

    result = retriever.retrieve_similar_incidents("anything")

    assert result.status == "empty"
    assert result.incidents == []


def test_collection_unavailable_is_handled_safely(isolated_chroma, monkeypatch):
    def _raise(query_text, n_results=3):
        raise RuntimeError("simulated ChromaDB failure")
    monkeypatch.setattr(chroma_store, "query_similar", _raise)

    result = retriever.retrieve_similar_incidents("anything")

    assert result.status == "collection_unavailable"
    assert "simulated ChromaDB failure" in result.reason


def test_malformed_match_missing_incident_id_is_skipped_not_crashed(isolated_chroma, monkeypatch):
    monkeypatch.setattr(chroma_store, "query_similar", lambda query_text, n_results=3: [
        {"distance": 0.1, "metadata": {}, "postmortem_text": "no incident_id here"},
    ])

    result = retriever.retrieve_similar_incidents("anything")

    assert result.status == "empty"  # the only match was malformed and got filtered out
    assert result.incidents == []


def test_malformed_match_missing_metadata_falls_back_to_unknown(isolated_chroma, monkeypatch):
    monkeypatch.setattr(chroma_store, "query_similar", lambda query_text, n_results=3: [
        {"incident_id": "inc-9999", "distance": 0.2, "metadata": {}, "postmortem_text": "text"},
    ])

    result = retriever.retrieve_similar_incidents("anything")

    assert result.status == "retrieved"
    assert result.incidents[0].fault_type == "unknown"
    assert result.incidents[0].root_cause_service == "unknown"
