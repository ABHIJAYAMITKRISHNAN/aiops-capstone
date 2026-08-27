"""A minimal, real LangGraph workflow:

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
       \\           /
         finalize
            |
           END

The LLM is only ever invoked on the anomaly branch - a normal reading never calls Ollama.
Detectors and the Ollama client are injected into `build_graph()` rather than constructed inside
node functions, so tests can supply fakes/mocks and so models are loaded once, not per call.

This is intentionally the full extent of Week 7's graph. Week 8 adds RCA/RAG/remediation nodes
after "anomaly" without needing to touch anything upstream of it - see
ai-orchestration/README.md "How Week 7 feeds Week 8".
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


def _finalize_node(state: WorkflowState) -> dict:
    """Assembles the final structured result. Required fields (Week 7 spec): correlation/incident
    identifiers where available, telemetry evidence, anomaly result, LLM interpretation, and
    confidence/limitations - present on every path, not just the anomaly one, so Week 8 can rely
    on a single consistent output shape regardless of which branch ran."""
    record = state["raw_record"]
    anomaly_result = state.get("anomaly_result") or {}
    llm_interpretation = state.get("llm_interpretation")
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
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "extract_features")
    graph.add_edge("extract_features", "detect_anomaly")
    graph.add_conditional_edges(
        "detect_anomaly", _route_after_detection,
        {"anomaly": "interpret", "normal": "finalize", "insufficient_data": "finalize"},
    )
    graph.add_edge("interpret", "finalize")
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
