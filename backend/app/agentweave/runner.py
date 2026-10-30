"""L4 simulated multi-agent workflow runner with mandatory human approval."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from app.adapters.mock import MockCMMS, MockInventory, MockScheduler
from app.agentweave.nodes.work_order import WorkOrderProposal
from app.agentweave.policies import evaluate_gate
from app.config import get_settings
from app.foundation.audit_ledger import InMemoryAuditLedger
from app.grounding.chunker import ManualChunk
from app.grounding.fault_codes import parse_fault_codes
from app.grounding.retriever import ManualRetriever
from app.grounding.validator import validate_diagnosis
from app.llm.groq_client import FakeGroqLLM
from app.llm.prompts import DIAGNOSIS_SYSTEM_V1, WORK_ORDER_SYSTEM_V1
from app.schemas.domain import (
    AnomalyEvent,
    ApprovalDecision,
    ApprovalPackage,
    Asset,
    DecisionType,
    DiagnosisResult,
    PartsStatus,
    TechnicianProposal,
    WorkOrderDraft,
)


class WorkflowRunner:
    """Offline-first orchestrator; adapters are the only side-effect boundary."""

    def __init__(self) -> None:
        root = Path(__file__).resolve().parents[3]
        self.settings = get_settings()
        self.retriever = ManualRetriever()
        self.fault_codes = parse_fault_codes()
        self.llm = FakeGroqLLM()
        self.cmms = MockCMMS()
        part_seed = json.loads((root / "data" / "seed" / "parts.json").read_text(encoding="utf-8"))
        technician_seed = json.loads(
            (root / "data" / "seed" / "technicians.json").read_text(encoding="utf-8")
        )
        self.inventory = MockInventory(
            {part["part_number"]: part["quantity"] for part in part_seed}
        )
        self.scheduler = MockScheduler(technician_seed)
        self.ledger = InMemoryAuditLedger()
        self.workflows: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, ApprovalPackage] = {}
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.feedback: list[dict[str, Any]] = []

    async def start(self, anomaly: AnomalyEvent, asset: Asset) -> dict[str, Any]:
        correlation_id = str(anomaly.evidence.get("correlation_id") or anomaly.anomaly_id)
        if correlation_id in self.workflows:
            return self.workflows[correlation_id]
        record: dict[str, Any] = {
            "correlation_id": correlation_id,
            "anomaly": anomaly,
            "asset": asset,
            "status": "running",
            "trace": [],
            "errors": [],
            "partial": False,
            "work_order": None,
            "work_order_id": None,
            "parts": PartsStatus(all_available=False),
            "technician": None,
            "approval": None,
            "technician_assigned": False,
        }
        self.workflows[correlation_id] = record
        diagnosis, chunks = await self._diagnose(record)
        record["diagnosis"] = diagnosis
        if anomaly.shadow or self.settings.pipeline_mode == "shadow":
            record["status"] = "shadow"
            self._audit(record, "shadow_complete", {"diagnosis": diagnosis.model_dump(mode="json")})
            return record

        draft = await self._draft_work_order(record, chunks)
        record["work_order"] = draft
        parts_status = await self._check_parts(record, draft)
        record["parts"] = parts_status
        record["technician"] = await self._schedule(record, draft)
        gate = evaluate_gate(
            asset,
            diagnosis,
            draft,
            minimum_confidence=self.settings.hitl_min_confidence,
            spend_threshold_usd=self.settings.spend_approval_threshold_usd,
            known_failure_modes=set(self.fault_codes),
        )
        reasons = list(gate.reasons)
        if record["partial"]:
            reasons.append("partial_approval_package")
        now = datetime.now(UTC)
        package = ApprovalPackage(
            correlation_id=correlation_id,
            asset_id=asset.asset_id,
            anomaly_summary=f"{anomaly.anomaly_type}: severity {anomaly.severity:.2f}",
            diagnosis=diagnosis,
            work_order=draft,
            parts=parts_status,
            technician=record["technician"],
            required_approver_tier=gate.approver_tier,
            reasons_for_hitl=reasons,
            sla_deadline=now + timedelta(minutes=gate.sla_minutes),
            partial=record["partial"],
            degraded_reasons=list(record["errors"]),
        )
        record["approval_package"] = package
        record["status"] = "pending_approval"
        record["approval_requested_at"] = now
        record["sla_warning_sent"] = False
        self.pending[correlation_id] = package
        self._audit(record, "approval_requested", package.model_dump(mode="json"))
        await self.events.put(
            {"type": "approval_requested", "data": package.model_dump(mode="json")}
        )
        return record

    async def _diagnose(self, record: dict[str, Any]) -> tuple[DiagnosisResult, list[ManualChunk]]:
        started = perf_counter()
        anomaly: AnomalyEvent = record["anomaly"]
        asset: Asset = record["asset"]
        query = f"{anomaly.anomaly_type} {json.dumps(anomaly.evidence, default=str)}"
        retrieved = self.retriever.retrieve(query, asset.asset_class)
        chunks = [result.chunk for result in retrieved]
        if not chunks:
            chunks = [
                chunk for chunk in self.retriever.chunks if chunk.asset_class == asset.asset_class
            ]
        user = json.dumps(
            {
                "asset_id": asset.asset_id,
                "asset_class": asset.asset_class,
                "anomaly_type": anomaly.anomaly_type,
                "evidence": anomaly.evidence,
                "manual_passages": [
                    {
                        "document": chunk.document,
                        "section": chunk.section,
                        "passage": chunk.content,
                    }
                    for chunk in chunks[:3]
                ],
            }
        )
        try:
            diagnosis = await self.llm.structured(DiagnosisResult, DIAGNOSIS_SYSTEM_V1, user)
            diagnosis = validate_diagnosis(diagnosis, chunks, set(self.fault_codes))
            outcome = (
                "ok"
                if all(candidate.verified for candidate in diagnosis.candidates)
                else "unverified"
            )
        except Exception as error:
            record["partial"] = True
            record["errors"].append(f"diagnosis_unavailable: {error}")
            diagnosis = DiagnosisResult(candidates=[], selected_index=0, safety_flag=True)
            outcome = "partial"
        self._trace(record, "diagnose", started, outcome, "fake-deterministic")
        return diagnosis, chunks

    async def _draft_work_order(
        self, record: dict[str, Any], chunks: list[ManualChunk]
    ) -> WorkOrderDraft | None:
        started = perf_counter()
        asset: Asset = record["asset"]
        diagnosis: DiagnosisResult = record["diagnosis"]
        selected = diagnosis.candidates[diagnosis.selected_index] if diagnosis.candidates else None
        if selected is None:
            record["partial"] = True
            record["errors"].append("work_order_unavailable: diagnosis has no candidate")
            self._trace(record, "work_order", started, "partial", "fake-deterministic")
            return None
        try:
            proposal_input = json.dumps(
                {
                    "asset_id": asset.asset_id,
                    "site_id": asset.site_id,
                    "failure_mode": selected.failure_mode,
                    "manual_passages": [chunk.content for chunk in chunks[:3]],
                }
            )
            proposal = await self.llm.structured(
                WorkOrderProposal, WORK_ORDER_SYSTEM_V1, proposal_input
            )
            cost = sum(part.quantity * part.unit_cost for part in proposal.parts)
            cost += proposal.estimated_labor_hours * self.settings.labor_rate_usd_per_hour
            priority = min(
                5,
                max(1, asset.criticality_tier + round(record["anomaly"].severity * 2)),
            )
            draft = WorkOrderDraft(
                asset_id=asset.asset_id,
                site_id=asset.site_id,
                failure_mode=selected.failure_mode,
                summary=proposal.summary,
                tasks=proposal.tasks,
                estimated_labor_hours=proposal.estimated_labor_hours,
                required_skills=proposal.required_skills,
                parts=proposal.parts,
                priority=priority,
                estimated_cost_usd=round(cost, 2),
                correlation_id=record["correlation_id"],
            )
            try:
                work_order = await self.cmms.create_work_order(draft.model_dump(mode="json"))
                record["work_order_id"] = work_order["wonum"]
            except Exception as error:
                record["partial"] = True
                record["errors"].append(f"cmms_queued: {error}")
                record["cmms_queued"] = True
                record["work_order_id"] = f"LOCAL-{record['correlation_id']}"
            outcome = "partial" if record.get("cmms_queued") else "ok"
            self._trace(record, "work_order", started, outcome, "fake-deterministic")
            return draft
        except Exception as error:
            record["partial"] = True
            record["errors"].append(f"work_order_draft_failed: {error}")
            self._trace(record, "work_order", started, "partial", "fake-deterministic")
            return None

    async def _check_parts(
        self, record: dict[str, Any], draft: WorkOrderDraft | None
    ) -> PartsStatus:
        started = perf_counter()
        availability: list[dict[str, Any]] = []
        long_lead: list[str] = []
        if draft is None:
            status = PartsStatus(all_available=False, parts_tbc=True)
        else:
            try:
                for part in draft.parts:
                    result = await self.inventory.check_availability(part)
                    availability.append(result)
                    if not result["all_available"]:
                        long_lead.append(part.part_number)
                status = PartsStatus(
                    all_available=all(item["all_available"] for item in availability),
                    reservations=availability,
                    long_lead=long_lead,
                )
            except Exception as error:
                record["partial"] = True
                record["errors"].append(f"inventory_unavailable: {error}")
                status = PartsStatus(all_available=False, reservations=availability, parts_tbc=True)
        self._trace(record, "parts", started, "partial" if status.parts_tbc else "ok")
        return status

    async def _schedule(
        self, record: dict[str, Any], draft: WorkOrderDraft | None
    ) -> TechnicianProposal | None:
        started = perf_counter()
        if draft is None:
            self._trace(record, "schedule", started, "partial")
            return None
        result = await self.scheduler.propose_assignment(draft.required_skills)
        if result is None:
            record["errors"].append("no_qualified_technician_available")
            self._trace(record, "schedule", started, "no_match")
            return None
        proposal = TechnicianProposal(
            technician_id=result["technician_id"],
            name=result["name"],
            skill_match=result["skill_match"],
            slot_start=datetime.now(UTC) + timedelta(hours=4),
            rationale=f"Available technician; {len(result['extra_skills'])} extra skills.",
        )
        self._trace(record, "schedule", started, "ok")
        return proposal

    async def decide(self, decision: ApprovalDecision) -> dict[str, Any]:
        record = self.workflows.get(decision.correlation_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {decision.correlation_id}")
        if record["status"] in {"approved", "rejected"}:
            return record
        if record["status"] != "pending_approval":
            raise ValueError(f"Workflow is not awaiting approval: {record['status']}")
        started = perf_counter()
        if decision.decision == DecisionType.ESCALATE:
            package: ApprovalPackage = record["approval_package"]
            next_tier = min(3, package.required_approver_tier + 1)
            next_sla_minutes = {
                1: self.settings.sla_tier1_minutes,
                2: self.settings.sla_tier2_minutes,
                3: self.settings.sla_tier3_minutes,
            }[next_tier]
            escalated_at = datetime.now(UTC)
            package = package.model_copy(
                update={
                    "required_approver_tier": next_tier,
                    "sla_deadline": escalated_at + timedelta(minutes=next_sla_minutes),
                    "reasons_for_hitl": [*package.reasons_for_hitl, "escalated_by_approver"],
                }
            )
            record["approval_package"] = package
            record["approval_requested_at"] = escalated_at
            record["sla_warning_sent"] = False
            record["approval"] = decision
            self.pending[decision.correlation_id] = package
            self.feedback.append(
                {
                    "correlation_id": decision.correlation_id,
                    "reason": decision.reason,
                    "type": "escalation",
                }
            )
            self._trace(record, "finalize", started, "escalated")
            self._audit(record, "approval_escalated", decision.model_dump(mode="json"))
            await self.events.put(
                {"type": "sla_escalated", "data": package.model_dump(mode="json")}
            )
            return record

        draft: WorkOrderDraft | None = record["work_order"]
        if decision.decision == DecisionType.REJECT:
            if record["work_order_id"] and not record.get("cmms_queued"):
                await self.cmms.update_status(record["work_order_id"], "REJECTED")
            record["status"] = "rejected"
            self.feedback.append(
                {
                    "correlation_id": decision.correlation_id,
                    "failure_mode": draft.failure_mode if draft else None,
                    "asset_class": record["asset"].asset_class,
                    "type": "rejection",
                    "reason": decision.reason,
                }
            )
        else:
            if decision.decision == DecisionType.MODIFY_APPROVE and draft is not None:
                draft = WorkOrderDraft.model_validate(
                    {**draft.model_dump(), **decision.modifications}
                )
                record["work_order"] = draft
            if draft is not None:
                if not record.get("cmms_queued"):
                    await self.cmms.update_status(record["work_order_id"], "APPROVED")
                for part in draft.parts:
                    await self.inventory.reserve(decision.correlation_id, part)
            record["status"] = "approved"
            record["technician_assigned"] = record["technician"] is not None
            if decision.decision == DecisionType.MODIFY_APPROVE:
                self.feedback.append(
                    {
                        "correlation_id": decision.correlation_id,
                        "failure_mode": draft.failure_mode if draft else None,
                        "asset_class": record["asset"].asset_class,
                        "type": "modification",
                        "modifications": decision.modifications,
                    }
                )

        record["approval"] = decision
        self.pending.pop(decision.correlation_id, None)
        self._trace(record, "finalize", started, record["status"])
        self._audit(record, "approval_decided", decision.model_dump(mode="json"))
        await self.events.put(
            {"type": "approval_decided", "data": decision.model_dump(mode="json")}
        )
        return record

    def _trace(
        self,
        record: dict[str, Any],
        node: str,
        started: float,
        outcome: str,
        model: str | None = None,
    ) -> None:
        entry = {
            "node": node,
            "started_at": datetime.now(UTC).isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "model": model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "retries": 0,
            "outcome": outcome,
        }
        record["trace"].append(entry)
        self._audit(record, "workflow_step", entry)
        event = entry | {"correlation_id": record["correlation_id"]}
        self._put_event("workflow_step", event)

    def _audit(self, record: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        event = self.ledger.append(record["correlation_id"], "system", event_type, payload)
        self._put_event("audit_event", event.model_dump(mode="json"))

    def _put_event(self, event_type: str, data: dict[str, Any]) -> None:
        try:
            self.events.put_nowait({"type": event_type, "data": data})
        except asyncio.QueueFull:
            pass
