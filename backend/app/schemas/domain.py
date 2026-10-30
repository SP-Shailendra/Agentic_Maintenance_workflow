"""Domain schemas shared by the API, agents, and adapters."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeasurementType(StrEnum):
    VIBRATION_RMS = "vibration_rms"
    TEMPERATURE = "temperature"
    CURRENT = "current"
    PRESSURE = "pressure"


class QualityFlag(StrEnum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"


class TelemetryReading(StrictModel):
    asset_id: str
    sensor_id: str
    scenario_id: str | None = None
    timestamp_utc: datetime
    measurement_type: MeasurementType
    value: float
    unit: str
    quality_flag: QualityFlag = QualityFlag.GOOD


class Asset(StrictModel):
    asset_id: str
    name: str
    asset_class: str
    criticality_tier: int = Field(ge=1, le=3)
    safety_critical: bool | None
    install_date: datetime
    site_id: str
    location: str
    days_since_last_pm: int = Field(default=0, ge=0)

    @property
    def is_safety_critical(self) -> bool:
        return self.safety_critical is not False


class AnomalyEvent(StrictModel):
    anomaly_id: str
    asset_id: str
    detected_at: datetime
    detected_at_tick: int | None = None
    scenario_id: str | None = None
    anomaly_type: str
    severity: float = Field(ge=0, le=1)
    shadow: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class Citation(StrictModel):
    document: str
    section: str
    passage: str


class FailureModeCandidate(StrictModel):
    failure_mode: str
    confidence: float = Field(ge=0, le=1)
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    verified: bool = False


class DiagnosisResult(StrictModel):
    candidates: list[FailureModeCandidate] = Field(max_length=3)
    selected_index: int = Field(ge=0)
    safety_flag: bool = False

    @model_validator(mode="after")
    def selected_index_exists(self) -> "DiagnosisResult":
        if self.candidates and self.selected_index >= len(self.candidates):
            raise ValueError("selected_index must refer to a candidate")
        return self


class PartRequirement(StrictModel):
    part_number: str
    description: str
    quantity: int = Field(gt=0)
    unit_cost: float = Field(ge=0)


class WorkOrderDraft(StrictModel):
    asset_id: str
    site_id: str
    failure_mode: str
    summary: str
    tasks: list[str]
    estimated_labor_hours: float = Field(ge=0)
    required_skills: list[str]
    parts: list[PartRequirement]
    priority: int = Field(ge=1, le=5)
    estimated_cost_usd: float = Field(ge=0)
    correlation_id: str


class PartsStatus(StrictModel):
    all_available: bool
    reservations: list[dict[str, Any]] = Field(default_factory=list)
    availability_checks: list[dict[str, Any]] = Field(default_factory=list)
    long_lead: list[str] = Field(default_factory=list)
    parts_tbc: bool = False


class TechnicianProposal(StrictModel):
    technician_id: str
    name: str
    skill_match: list[str]
    slot_start: datetime
    rationale: str


class ApprovalPackage(StrictModel):
    correlation_id: str
    asset_id: str
    anomaly_summary: str
    diagnosis: DiagnosisResult
    work_order: WorkOrderDraft | None
    parts: PartsStatus
    technician: TechnicianProposal | None
    required_approver_tier: int = Field(ge=1)
    reasons_for_hitl: list[str]
    sla_deadline: datetime
    partial: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)


class DecisionType(StrEnum):
    APPROVE = "approve"
    MODIFY_APPROVE = "modify_approve"
    REJECT = "reject"
    ESCALATE = "escalate"


class ApprovalDecision(StrictModel):
    correlation_id: str
    decision: DecisionType
    approver: str
    reason: str | None = None
    modifications: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def required_reason(self) -> "ApprovalDecision":
        if (
            self.decision in {DecisionType.REJECT, DecisionType.ESCALATE}
            and not (self.reason or "").strip()
        ):
            raise ValueError(f"reason is required for {self.decision.value}")
        return self


class AuditEvent(StrictModel):
    seq: int
    correlation_id: str
    timestamp_utc: datetime
    actor: str
    event_type: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str