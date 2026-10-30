"""L4 schema for an LLM-proposed work order before deterministic costing."""

from pydantic import Field

from app.schemas.domain import PartRequirement, StrictModel


class WorkOrderProposal(StrictModel):
    summary: str
    tasks: list[str]
    estimated_labor_hours: float = Field(ge=0)
    required_skills: list[str]
    parts: list[PartRequirement]
