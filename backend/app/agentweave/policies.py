"""Pure L4 approval policy; automatic approval is deliberately impossible."""

from dataclasses import dataclass

from app.schemas.domain import Asset, DiagnosisResult, WorkOrderDraft


@dataclass(frozen=True)
class GateDecision:
    required: bool
    approver_tier: int
    sla_minutes: int
    reasons: tuple[str, ...]
    auto_approval_eligible: bool = False


def evaluate_gate(
    asset: Asset,
    diagnosis: DiagnosisResult,
    work_order: WorkOrderDraft | None,
    *,
    minimum_confidence: float = 0.70,
    spend_threshold_usd: float = 5000.0,
    known_failure_modes: set[str] | None = None,
) -> GateDecision:
    """Return the mandatory human gate and its escalation policy."""
    reasons: list[str] = []
    if asset.safety_critical is None:
        reasons.extend(("safety_critical", "safety_classification_missing"))
    elif asset.safety_critical:
        reasons.append("safety_critical")

    selected = diagnosis.candidates[diagnosis.selected_index] if diagnosis.candidates else None
    if selected is None or selected.confidence < minimum_confidence:
        reasons.append("low_confidence")
    if selected is None or not selected.citations:
        reasons.append("missing_citation")
    if selected is not None and (
        not selected.verified
        or (known_failure_modes is not None and selected.failure_mode not in known_failure_modes)
    ):
        reasons.append("unverified_fault_code")

    tier = asset.criticality_tier
    if work_order is not None and work_order.estimated_cost_usd > spend_threshold_usd:
        tier = max(tier, 2)
        reasons.append("spend_threshold_exceeded")

    sla_by_tier = {1: 15, 2: 60, 3: 240}
    return GateDecision(
        required=True,
        approver_tier=tier,
        sla_minutes=sla_by_tier[tier],
        reasons=tuple(dict.fromkeys(reasons or ["human_approval_required"])),
        auto_approval_eligible=False,
    )