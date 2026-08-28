"""Explicit typed state for the Week 7 LangGraph workflow.

`total=False` because the state is built up incrementally node-by-node - not every field is
present at every point in the graph."""
from __future__ import annotations

from typing import Optional, TypedDict


class WorkflowState(TypedDict, total=False):
    # --- input ---
    raw_record: dict  # one raw telemetry record, exactly as telemetry/collector.py writes it
    incident_id: Optional[str]  # caller-supplied, if this run is associated with a known incident

    # --- populated by extract_features_node ---
    feature_vector: Optional[dict]  # anomaly.models.FeatureVector.to_dict(), or None
    correlation_id: Optional[str]

    # --- populated by detect_anomaly_node ---
    anomaly_result: Optional[dict]  # anomaly.models.AnomalyResult.to_dict()

    # --- populated by the routing decision ---
    decision: str  # "normal" | "anomaly" | "insufficient_data"

    # --- populated by interpret_node (anomaly branch only) ---
    llm_interpretation: Optional[dict]  # llm.models.AnomalyInterpretation.to_dict()

    # --- Week 8: populated by retrieve_similar_incidents_node (anomaly branch only) ---
    retrieval: Optional[dict]  # rag.models.RetrievalResult.to_dict()

    # --- Week 8: populated by root_cause_analysis_node (anomaly branch only) ---
    root_cause_analysis: Optional[dict]  # rca.models.RootCauseAnalysis.to_dict()

    # --- Week 8: populated by propose_remediation_node (anomaly branch only) ---
    remediation_proposal: Optional[dict]  # remediation.models.RemediationProposal.to_dict() - a
    # PROPOSAL only; nothing in this graph executes it (see remediation/proposer.py's docstring)

    # --- populated by finalize_node ---
    result: dict  # the final structured output - see workflow.py's finalize_node docstring
