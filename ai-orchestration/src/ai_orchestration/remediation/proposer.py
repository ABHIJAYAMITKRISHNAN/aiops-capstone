"""Deterministic remediation proposal generation - no LLM involved at all. Remediation is exactly
the kind of decision this project's rules say should be "deterministic structured data" rather
than free-form AI output (and the LLM "must not bypass deterministic safety logic") - so unlike
RCA's optional LLM narrative, remediation proposals here are 100% Python logic, always.

`propose_remediation()` never executes anything - it returns a RemediationProposal describing what
a human operator (or, in a later week, an approved automated action) *could* do; nothing in this
module calls Kubernetes, the fault-injection endpoints, or any other side-effecting API.
"""
from __future__ import annotations

from ..rca.models import RootCauseAnalysis
from .models import RemediationProposal

# Keyed by fault_type. Every action described here is a *reset of this project's own controlled
# fault injection* (see CLAUDE.md "Fault injection" section) or a well-scoped, conventional
# operational response - never a made-up action name.
_FAULT_REMEDIATION_TEMPLATES: dict[str, dict] = {
    "auth-key-error": {
        "recommended_action": (
            "Restore auth-service's JWT signing key to its original, valid value (reset the "
            "auth-key-error fault injection)."
        ),
        "target_service": "auth-service",
        "action_category": "restore_configuration",
        "expected_outcome": (
            "Token validation succeeds again for both existing and newly issued tokens; "
            "payment-service's elevated http_server_requests_error_count returns to baseline."
        ),
        "risk_level": "medium",
    },
    "memory-leak": {
        "recommended_action": (
            "Reset the payment-service memory-leak fault injection to stop further retained "
            "allocation. If JVM heap usage remains critically high after reset, restart the "
            "payment-service instance to reclaim memory immediately."
        ),
        "target_service": "payment-service",
        "action_category": "reset_fault_configuration",
        "expected_outcome": (
            "New allocation stops immediately; heap usage plateaus and recovers via normal "
            "garbage collection, or immediately if a restart is performed."
        ),
        "risk_level": "medium",
    },
    "db-lock": {
        "recommended_action": (
            "Reset the ledger-service DB-pool-exhaustion fault injection to release the held "
            "HikariCP connections and restore full pool capacity."
        ),
        "target_service": "ledger-service",
        "action_category": "release_resources",
        "expected_outcome": (
            "hikaricp_connections_active returns to baseline; new ledger transactions stop "
            "timing out waiting for a connection."
        ),
        "risk_level": "medium",
    },
    "notification-latency": {
        "recommended_action": (
            "Reset the notification-service latency fault injection to restore immediate "
            "response timing. If elevated latency persists after reset, investigate "
            "notification-service directly, not payment-service - payment-service is only the "
            "symptom-visible service, not the root cause."
        ),
        "target_service": "notification-service",
        "action_category": "reset_fault_configuration",
        "expected_outcome": (
            "payment-service's outbound calls to notification-service return to their normal "
            "~10-60ms duration and no longer approach the client-side timeout."
        ),
        "risk_level": "medium",
    },
}


def propose_remediation(rca: RootCauseAnalysis) -> RemediationProposal:
    """Deterministic fault_type -> action lookup, but the action is never chosen "solely based on
    fault names": a template is only used when the RCA's own confidence is at least "medium" (i.e.
    the fault_type determination was itself evidence-based, not a low-confidence guess); a "low"
    confidence RCA always falls back to a generic, low-risk "investigate_manually" proposal
    regardless of which fault_type happened to be suspected, since that suspicion wasn't strong
    enough to act on."""
    template = _FAULT_REMEDIATION_TEMPLATES.get(rca.suspected_fault_type or "")

    if template is not None and rca.confidence != "low":
        return RemediationProposal(
            recommended_action=template["recommended_action"],
            target_service=template["target_service"],
            action_category=template["action_category"],
            rationale=(
                f"RCA determined suspected_fault_type='{rca.suspected_fault_type}' with "
                f"confidence='{rca.confidence}' (method: {rca.determination_method}), pointing to "
                f"{rca.suspected_root_cause_service} as the root cause."
            ),
            supporting_evidence=[rca.evidence_summary] + [
                f"{m.metric_name}={m.observed_value} ({m.deviation_description})" for m in rca.metric_anomalies
            ],
            expected_outcome=template["expected_outcome"],
            risk_level=template["risk_level"],
            confidence=rca.confidence,
        )

    return RemediationProposal(
        recommended_action=(
            f"Insufficient evidence to confidently determine a specific automated remediation for "
            f"{rca.suspected_root_cause_service}. Escalate to a human operator to investigate "
            f"directly before taking any action."
        ),
        target_service=rca.suspected_root_cause_service,
        action_category="investigate_manually",
        rationale=(
            f"RCA confidence was '{rca.confidence}' (method: {rca.determination_method}) - too low "
            f"to safely propose a specific state-changing action."
        ),
        supporting_evidence=[rca.evidence_summary],
        expected_outcome="A human operator confirms the actual root cause before any remediation is attempted.",
        risk_level="low",
        confidence="low",
    )
