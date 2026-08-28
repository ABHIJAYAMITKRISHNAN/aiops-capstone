"""RAG retrieval against Week 6's existing ChromaDB `incident_memory` collection.

Reuses `dataset_tools.chroma_store` directly rather than duplicating any ChromaDB setup - this
module never opens a second collection, never re-embeds anything, and never touches
`EVALUATION_INCIDENTS_FILE`.

Defense-in-depth beyond what chroma_store.py already guarantees at build time: every retrieval
here re-checks each returned incident_id against the Evaluation set before it's ever handed to the
RCA stage, so even a future bug in how the collection was built (e.g. a stale/manually-edited
collection on disk) cannot leak an Evaluation incident into a live investigation. This mirrors
chroma_store.py's own "check before trusting the data" pattern, applied at read time instead of
(in addition to) build time.
"""
from __future__ import annotations

import logging

from .. import config as ai_config

ai_config.ensure_sibling_packages_importable()

from dataset_tools import chroma_store as dt_chroma_store, config as dt_config, ingest as dt_ingest  # noqa: E402

from .models import RetrievalResult, RetrievedIncident

log = logging.getLogger("ai_orchestration.rag.retriever")

POSTMORTEM_EXCERPT_LENGTH = 400


def build_query_text(
    service: str,
    relevant_feature_values: dict,
    llm_abnormal_summary: str | None = None,
    top_n_metrics: int = 4,
) -> str:
    """Builds a query from real evidence only - anomaly service, the most notable metric
    values, and (if available) Week 7's LLM-generated abnormal_summary - so the query text reads
    similarly to the postmortem_text prose actually indexed in the collection."""
    # Sort by magnitude as a simple, deterministic proxy for "most notable" - no ML here, just a
    # readable query string.
    sorted_metrics = sorted(relevant_feature_values.items(), key=lambda kv: abs(kv[1] or 0), reverse=True)
    metric_phrases = [f"{name}={value}" for name, value in sorted_metrics[:top_n_metrics] if value is not None]

    parts = [f"Anomaly detected on {service}.", f"Notable metrics: {', '.join(metric_phrases)}."]
    if llm_abnormal_summary:
        parts.append(llm_abnormal_summary)
    return " ".join(parts)


def _evaluation_ids() -> set[str]:
    return {inc["incident_id"] for inc in dt_ingest.read_jsonl(dt_config.EVALUATION_INCIDENTS_FILE)}


def retrieve_similar_incidents(query_text: str, n_results: int = 3) -> RetrievalResult:
    try:
        raw_matches = dt_chroma_store.query_similar(query_text, n_results=n_results)
    except Exception as exc:  # noqa: BLE001 - a ChromaDB/collection problem must not crash the graph
        log.warning("ChromaDB retrieval failed: %s", exc)
        return RetrievalResult(
            query_text=query_text, incidents=[], source_collection=dt_config.CHROMA_COLLECTION_NAME,
            status="collection_unavailable", reason=str(exc),
        )

    if not raw_matches:
        return RetrievalResult(
            query_text=query_text, incidents=[], source_collection=dt_config.CHROMA_COLLECTION_NAME,
            status="empty", reason="No incidents found in the Memory collection for this query",
        )

    evaluation_ids = _evaluation_ids()
    incidents: list[RetrievedIncident] = []
    for match in raw_matches:
        incident_id = match.get("incident_id")
        if not incident_id:
            log.warning("Skipping malformed ChromaDB match with no incident_id: %s", match)
            continue
        if incident_id in evaluation_ids:
            # Should be structurally impossible given chroma_store.py's build-time enforcement -
            # this is the defense-in-depth layer described in this module's docstring.
            log.error("Evaluation incident '%s' returned from ChromaDB query - excluding it", incident_id)
            continue

        metadata = match.get("metadata") or {}
        postmortem_text = match.get("postmortem_text") or ""
        try:
            incidents.append(RetrievedIncident(
                incident_id=incident_id,
                distance=float(match.get("distance", 0.0)),
                fault_type=metadata.get("fault_type", "unknown"),
                root_cause_service=metadata.get("root_cause_service", "unknown"),
                symptom_service=metadata.get("symptom_service", "unknown"),
                severity=metadata.get("severity", "unknown"),
                data_source=metadata.get("data_source", "unknown"),
                postmortem_excerpt=postmortem_text[:POSTMORTEM_EXCERPT_LENGTH],
            ))
        except Exception as exc:  # noqa: BLE001 - one malformed record must not lose the rest
            log.warning("Skipping malformed ChromaDB match %s: %s", incident_id, exc)
            continue

    if not incidents:
        return RetrievalResult(
            query_text=query_text, incidents=[], source_collection=dt_config.CHROMA_COLLECTION_NAME,
            status="empty", reason="All raw matches were filtered out (malformed or Evaluation-set)",
        )

    return RetrievalResult(
        query_text=query_text, incidents=incidents, source_collection=dt_config.CHROMA_COLLECTION_NAME,
        status="retrieved",
    )
