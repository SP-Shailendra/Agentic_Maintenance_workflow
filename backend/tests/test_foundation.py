from datetime import UTC, datetime

from app.agentweave.policies import evaluate_gate
from app.foundation.audit_ledger import InMemoryAuditLedger
from app.schemas.domain import Asset, Citation, DiagnosisResult, FailureModeCandidate


def make_asset(safety_critical: bool | None, tier: int = 1) -> Asset:
    return Asset(
        asset_id="IC-002",
        name="Imaging chiller",
        asset_class="imaging_chiller",
        criticality_tier=tier,
        safety_critical=safety_critical,
        install_date=datetime(2020, 1, 1, tzinfo=UTC),
        site_id="SITE-1",
        location="Room 1",
    )


def make_diagnosis() -> DiagnosisResult:
    return DiagnosisResult(
        candidates=[
            FailureModeCandidate(
                failure_mode="IC-101",
                confidence=0.9,
                rationale="Temperature drift",
                citations=[
                    Citation(
                        document="chiller.md",
                        section="IC-101",
                        passage="Inspect condenser.",
                    )
                ],
                verified=True,
            )
        ],
        selected_index=0,
    )


def test_gate_is_never_automatic_and_missing_classification_is_safety_critical() -> None:
    decision = evaluate_gate(make_asset(None), make_diagnosis(), None)
    assert decision.required is True
    assert decision.auto_approval_eligible is False
    assert "safety_critical" in decision.reasons
    assert "safety_classification_missing" in decision.reasons


def test_gate_flags_low_confidence_and_missing_citation() -> None:
    diagnosis = DiagnosisResult(
        candidates=[
            FailureModeCandidate(failure_mode="unknown", confidence=0.2, rationale="unclear")
        ],
        selected_index=0,
    )
    decision = evaluate_gate(make_asset(False), diagnosis, None)
    assert {"low_confidence", "missing_citation", "unverified_fault_code"} <= set(decision.reasons)


def test_sla_matches_criticality_tier() -> None:
    assert evaluate_gate(make_asset(False, 1), make_diagnosis(), None).sla_minutes == 15
    assert evaluate_gate(make_asset(False, 2), make_diagnosis(), None).sla_minutes == 60
    assert evaluate_gate(make_asset(False, 3), make_diagnosis(), None).sla_minutes == 240


def test_audit_chain_verifies_and_detects_tampering() -> None:
    ledger = InMemoryAuditLedger()
    ledger.append("corr-1", "system", "started", {"ok": True})
    ledger.append("corr-1", "operator", "approved", {"reason": "reviewed"})
    assert ledger.verify() == (True, None)

    object.__setattr__(ledger._events[0], "payload", {"ok": False})
    assert ledger.verify() == (False, 1)


def test_audit_chain_detects_deletion_and_reordering() -> None:
    ledger = InMemoryAuditLedger()
    for sequence in range(3):
        ledger.append("corr-2", "system", "step", {"step": sequence})
    ledger._events.pop()
    assert ledger.verify() == (False, 3)

    reordered = InMemoryAuditLedger()
    for sequence in range(3):
        reordered.append("corr-3", "system", "step", {"step": sequence})
    reordered._events[0], reordered._events[1] = reordered._events[1], reordered._events[0]
    assert reordered.verify() == (False, 1)
