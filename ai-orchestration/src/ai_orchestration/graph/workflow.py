"""A real LangGraph workflow:

    raw telemetry record
            |
      extract_features
            |
      detect_anomaly
            |
        (decision)
       /          \\
   normal       anomaly
      |             |
      |        interpret (Ollama)
      |             |
      |     retrieve_similar_incidents (ChromaDB, Memory-set only)
      |             |
      |     root_cause_analysis (deterministic signature match + RAG cross-check + optional LLM narrative)
      |             |
      |     propose_remediation (deterministic - no LLM, never executes)
       \\           /
         finalize
            |
           END

The LLM is only ever invoked on the anomaly branch - a normal reading never calls Ollama, never
queries ChromaDB, and never runs RCA/remediation. Detectors and the Ollama client are injected
into `build_graph()` rather than constructed inside node functions, so tests can supply
fakes/mocks and so models are loaded once, not per call.

Week 7 built `extract_features` -> `detect_anomaly` -> `interpret` -> `finalize`. Week 8 adds the
three nodes between `interpret` and `finalize` without changing anything upstream of `interpret` -
see ai-orchestration/README.md "How Week 7 feeds Week 8" / "Week 8 architecture".
"""
from __future__ import annotations

import logging
from typing import Optional

from langgraph.graph import END, START, StateGraph

from ..anomaly import feature_extractor
from ..anomaly.detector import AnomalyDetector
from ..anomaly.models import AnomalyResult, FeatureVector
from ..llm.interpret import interpret_anomaly
from ..llm.models import AnomalyInterpretation
from ..llm.ollama_client import OllamaClient
from ..rag import retriever as rag_retriever
from ..rag.models import RetrievalResult
from ..rca import analyzer as rca_analyzer
from ..rca.models import RootCauseAnalysis
from ..remediation import proposer as remediation_proposer
from .state import WorkflowState

log = logging.getLogger("ai_orchestration.graph.workflow")


def _extract_features_node(state: WorkflowState) -> dict:
    record = state["raw_record"]
    fv = feature_extractor.extract_features(record)
    if fv is None:
        return {"feature_vector": None, "correlation_id": record.get("correlation_id")}
    return {"feature_vector": fv.to_dict(), "correlation_id": fv.correlation_id}


def _make_detect_anomaly_node(detectors: dict[str, AnomalyDetector]):
    def _detect_anomaly_node(state: WorkflowState) -> dict:
        record = state["raw_record"]
        feature_vector_dict = state.get("feature_vector")

        if feature_vector_dict is None:
            result = AnomalyResult(
                service=record.get("service"), timestamp=record.get("timestamp"),
                correlation_id=record.get("correlation_id"), status="insufficient_data",
                anomaly_score=None, is_anomaly=None, threshold=0.0, relevant_feature_values={},
                model_version="isolation-forest-v1", feature_schema_version="n/a",
                reason="No valid feature vector could be extracted from this record",
            )
            return {"anomaly_result": result.to_dict()}

        fv = FeatureVector.from_dict(feature_vector_dict)
        detector = detectors.get(fv.service)
        if detector is None or not detector.is_trained:
            result = AnomalyResult(
                service=fv.service, timestamp=fv.timestamp, correlation_id=fv.correlation_id,
                status="no_model", anomaly_score=None, is_anomaly=None, threshold=0.0,
                relevant_feature_values=fv.raw_metrics, model_version="isolation-forest-v1",
                feature_schema_version="n/a", reason=f"No trained detector available for service '{fv.service}'",
            )
            return {"anomaly_result": result.to_dict()}

        return {"anomaly_result": detector.score(fv).to_dict()}

    return _detect_anomaly_node


def _route_after_detection(state: WorkflowState) -> str:
    anomaly_result = state.get("anomaly_result") or {}
    if anomaly_result.get("status") != "scored":
        return "insufficient_data"
    return "anomaly" if anomaly_result.get("is_anomaly") else "normal"


def _make_interpret_node(ollama_client: OllamaClient):
    def _interpret_node(state: WorkflowState) -> dict:
        anomaly_result = AnomalyResult.from_dict(state["anomaly_result"])
        interpretation = interpret_anomaly(anomaly_result, ollama_client)
        return {"llm_interpretation": interpretation.to_dict()}

    return _interpret_node


def _retrieve_similar_incidents_node(state: WorkflowState) -> dict:
    anomaly_result = state["anomaly_result"]
    llm_interpretation = state.get("llm_interpretation") or {}
    abnormal_summary = (
        llm_interpretation.get("abnormal_summary") if llm_interpretation.get("status") == "interpreted" else None
    )
    query_text = rag_retriever.build_query_text(
        service=anomaly_result["service"],
        relevant_feature_values=anomaly_result.get("relevant_feature_values") or {},
        llm_abnormal_summary=abnormal_summary,
    )
    result = rag_retriever.retrieve_similar_incidents(query_text)
    return {"retrieval": result.to_dict()}


def _make_root_cause_analysis_node(ollama_client: OllamaClient):
    def _root_cause_analysis_node(state: WorkflowState) -> dict:
        anomaly_result = state["anomaly_result"]
        retrieval = RetrievalResult(**state["retrieval"])
        rca = rca_analyzer.analyze(anomaly_result, retrieval, ollama_client)
        return {"root_cause_analysis": rca.to_dict()}

    return _root_cause_analysis_node


def _propose_remediation_node(state: WorkflowState) -> dict:
    rca = RootCauseAnalysis(**state["root_cause_analysis"])
    proposal = remediation_proposer.propose_remediation(rca)
    return {"remediation_proposal": proposal.to_dict()}


def _finalize_node(state: WorkflowState) -> dict:
    """Assembles the final structured result. Required fields (Week 7 spec): correlation/incident
    identifiers where available, telemetry evidence, anomaly result, LLM interpretation, and
    confidence/limitations - present on every path, not just the anomaly one, so Week 8 can rely
    on a single consistent output shape regardless of which branch ran."""
    record = state["raw_record"]
    anomaly_result = state.get("anomaly_result") or {}
    llm_interpretation = state.get("llm_interpretation")
    retrieval = state.get("retrieval")
    root_cause_analysis = state.get("root_cause_analysis")
    remediation_proposal = state.get("remediation_proposal")
    decision = _route_after_detection(state)

    limitations: list[str] = []
    if anomaly_result.get("status") == "insufficient_data":
        limitations.append("Anomaly detection was not run: no valid feature vector for this record.")
    if anomaly_result.get("status") == "no_model":
        limitations.append("No trained model available for this service.")
    if llm_interpretation and llm_interpretation.get("status") == "llm_unavailable":
        limitations.append("LLM interpretation unavailable: " + str(llm_interpretation.get("reason")))
    if llm_interpretation and llm_interpretation.get("status") == "llm_error":
        limitations.append("LLM interpretation failed: " + str(llm_interpretation.get("reason")))
    if retrieval and retrieval.get("status") == "collection_unavailable":
        limitations.append("RAG retrieval unavailable: " + str(retrieval.get("reason")))
    if retrieval and retrieval.get("status") == "empty":
        limitations.append("RAG retrieval returned no similar incidents.")
    if root_cause_analysis and not root_cause_analysis.get("llm_reasoning"):
        limitations.append("RCA proceeded without an LLM narrative (Ollama unavailable or returned an invalid response).")
    if root_cause_analysis and root_cause_analysis.get("confidence") == "low":
        limitations.append("Root cause analysis confidence is low - treat suspected_root_cause_service as tentative.")

    result = {
        "correlation_id": state.get("correlation_id") or record.get("correlation_id"),
        "incident_id": state.get("incident_id"),
        "service": record.get("service"),
        "timestamp": record.get("timestamp"),
        "decision": decision,
        "telemetry_evidence": {
            "metrics": record.get("metrics"),
            "fault": record.get("fault"),
            "collection_error": record.get("collection_error"),
        },
        "anomaly_result": anomaly_result,
        "llm_interpretation": llm_interpretation,
        "retrieval": retrieval,
        "root_cause_analysis": root_cause_analysis,
        "remediation_proposal": remediation_proposal,
        "limitations": limitations,
    }
    return {"result": result}


def build_graph(detectors: dict[str, AnomalyDetector], ollama_client: Optional[OllamaClient] = None):
    """Compiles the workflow graph. `detectors` is a {service_name: AnomalyDetector} registry
    (see anomaly/detector.py); `ollama_client` defaults to an OllamaClient built from env vars if
    not supplied. Returns a compiled LangGraph graph - call `.invoke(state_dict)` on it."""
    ollama_client = ollama_client or OllamaClient()

    graph = StateGraph(WorkflowState)
    graph.add_node("extract_features", _extract_features_node)
    graph.add_node("detect_anomaly", _make_detect_anomaly_node(detectors))
    graph.add_node("interpret", _make_interpret_node(ollama_client))
    graph.add_node("retrieve_similar_incidents", _retrieve_similar_incidents_node)
    graph.add_node("root_cause_analysis", _make_root_cause_analysis_node(ollama_client))
    graph.add_node("propose_remediation", _propose_remediation_node)
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "extract_features")
    graph.add_edge("extract_features", "detect_anomaly")
    graph.add_conditional_edges(
        "detect_anomaly", _route_after_detection,
        {"anomaly": "interpret", "normal": "finalize", "insufficient_data": "finalize"},
    )
    graph.add_edge("interpret", "retrieve_similar_incidents")
    graph.add_edge("retrieve_similar_incidents", "root_cause_analysis")
    graph.add_edge("root_cause_analysis", "propose_remediation")
    graph.add_edge("propose_remediation", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def load_all_detectors() -> dict[str, AnomalyDetector]:
    """Loads every trained detector found under config.MODELS_DIR. Services with no persisted
    model are simply absent from the returned dict - detect_anomaly_node handles that as
    status="no_model", not an error."""
    from .. import config

    detectors: dict[str, AnomalyDetector] = {}
    for service in config.SERVICE_FEATURE_SCHEMAS:
        try:
            detectors[service] = AnomalyDetector.load(service)
        except FileNotFoundError:
            log.info("No trained model for '%s' - it will report status='no_model'", service)
    return detectors
