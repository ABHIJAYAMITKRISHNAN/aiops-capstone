"""Pydantic model for a remediation proposal - a recommendation only. Week 8 never executes
anything; `requires_human_approval` is always True, per CLAUDE.md's permanent rule 21 ("Human
approval must remain mandatory") - not a field a heuristic or the LLM is ever allowed to turn
off."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActionCategory = Literal[
    "restore_configuration", "reset_fault_configuration", "release_resources",
    "investigate_manually", "no_action_needed",
]
RiskLevel = Literal["low", "medium", "high"]
Confidence = Literal["low", "medium", "high"]


class RemediationProposal(BaseModel):
    recommended_action: str
    target_service: str
    action_category: ActionCategory
    rationale: str
    supporting_evidence: list[str] = Field(default_factory=list)
    expected_outcome: str
    risk_level: RiskLevel
    confidence: Confidence
    requires_human_approval: Literal[True] = True

    def to_dict(self) -> dict:
        return self.model_dump()
