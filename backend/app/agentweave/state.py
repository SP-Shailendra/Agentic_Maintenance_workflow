"""L4 serializable workflow state and per-node trace contract."""

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    correlation_id: str
    anomaly: dict[str, Any]
    asset: dict[str, Any]
    diagnosis: dict[str, Any]
    work_order: dict[str, Any]
    work_order_id: str | None
    cmms_queued: bool
    parts: dict[str, Any]
    technician: dict[str, Any] | None
    approval_package: dict[str, Any]
    approval: dict[str, Any]
    status: str
    errors: list[str]
    trace: list[dict[str, Any]]
