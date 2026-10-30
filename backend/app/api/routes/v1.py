"""HTTP and SSE API for the simulated maintenance workflow."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.runtime import runtime
from app.schemas.domain import AnomalyEvent, ApprovalDecision

router = APIRouter()


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioRequest(StrictRequest):
    asset_id: str
    scenario: str


class FailureRequest(StrictRequest):
    cmms_down: bool = False
    inventory_down: bool = False
    llm_fail: bool = False


def _encoded(value: Any) -> Any:
    return jsonable_encoder(value)


@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "mode": settings.pipeline_mode,
        "database": "configured_not_connected_in_memory_mode",
        "llm": settings.llm_mode,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


@router.get("/system/config")
async def system_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "mode": settings.pipeline_mode,
        "llm_mode": settings.llm_mode,
        "models": {
            "primary": settings.groq_model_primary,
            "fast": settings.groq_model_fast,
        },
        "adapters": {
            "cmms": settings.cmms_adapter,
            "inventory": settings.inventory_adapter,
            "scheduler": settings.scheduler_adapter,
        },
        "guardrails": {
            "human_approval_always_required": True,
            "missing_safety_classification_is_critical": True,
            "parts_reserved_only_after_approval": True,
            "hitl_min_confidence": settings.hitl_min_confidence,
            "spend_approval_threshold_usd": settings.spend_approval_threshold_usd,
        },
        "layers": [
            "DataPulse",
            "Features",
            "Detection",
            "AgentWeave",
            "Grounding",
            "Adapters",
            "HITL",
            "Foundation",
        ],
    }


@router.get("/assets")
async def list_assets() -> list[dict[str, Any]]:
    return [
        _encoded(asset) | {"health_index": runtime.pipeline.health.get(asset.asset_id, 100.0)}
        for asset in runtime.pipeline.simulator.assets
    ]


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str) -> dict[str, Any]:
    asset = next(
        (asset for asset in runtime.pipeline.simulator.assets if asset.asset_id == asset_id), None
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _encoded(asset) | {"health_index": runtime.pipeline.health.get(asset_id, 100.0)}


@router.get("/assets/{asset_id}/telemetry")
async def asset_telemetry(asset_id: str, window: str = "1h") -> list[dict[str, Any]]:
    if not any(asset.asset_id == asset_id for asset in runtime.pipeline.simulator.assets):
        raise HTTPException(status_code=404, detail="Asset not found")
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "24h": 86400}.get(window)
    if seconds is None:
        raise HTTPException(status_code=422, detail="window must be 1m, 5m, 15m, 1h, or 24h")
    cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
    return [
        _encoded(reading)
        for reading in runtime.pipeline.readings
        if reading.asset_id == asset_id and reading.timestamp_utc >= cutoff
    ]


@router.get("/anomalies")
async def list_anomalies(
    asset_id: str | None = None,
    shadow: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    anomalies = runtime.pipeline.anomalies
    result = [
        anomaly
        for anomaly in anomalies
        if (asset_id is None or anomaly.asset_id == asset_id)
        and (shadow is None or anomaly.shadow is shadow)
    ]
    return [_encoded(anomaly) for anomaly in result[-limit:]]


@router.get("/anomalies/suppressed")
async def suppressed_anomalies() -> dict[str, Any]:
    return {
        "counts": runtime.pipeline.suppressor.counts,
        "events": runtime.pipeline.suppressed,
    }


@router.get("/workflows")
async def list_workflows() -> list[dict[str, Any]]:
    return [_encoded(record) for record in runtime.workflow.workflows.values()]


@router.get("/workflows/{correlation_id}")
async def get_workflow(correlation_id: str) -> dict[str, Any]:
    record = runtime.workflow.workflows.get(correlation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _encoded(record)


@router.get("/approvals")
async def list_approvals(status: str = "pending") -> list[dict[str, Any]]:
    if status != "pending":
        return []
    packages = sorted(runtime.workflow.pending.values(), key=lambda item: item.sla_deadline)
    return [_encoded(package) for package in packages]


@router.get("/approvals/{correlation_id}")
async def get_approval(correlation_id: str) -> dict[str, Any]:
    package = runtime.workflow.pending.get(correlation_id)
    if package is None:
        record = runtime.workflow.workflows.get(correlation_id)
        if record is None or "approval_package" not in record:
            raise HTTPException(status_code=404, detail="Approval package not found")
        package = record["approval_package"]
    return _encoded(package)


@router.get("/technicians")
async def list_technicians() -> list[dict[str, Any]]:
    return [
        _encoded(technician)
        for technician in runtime.workflow.scheduler.technicians
        if technician.get("available", True)
    ]


@router.post("/approvals/{correlation_id}/decision")
async def submit_decision(
    correlation_id: str,
    decision: ApprovalDecision,
    x_approver_id: str = Header(default="dev-approver"),
) -> dict[str, Any]:
    if decision.correlation_id != correlation_id:
        raise HTTPException(status_code=422, detail="Path and body correlation_id must match")
    decision = decision.model_copy(update={"approver": x_approver_id})
    try:
        return _encoded(await runtime.approvals.submit(decision))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/audit")
async def audit_events(correlation_id: str | None = None) -> list[dict[str, Any]]:
    events = runtime.workflow.ledger.events
    return [
        _encoded(event)
        for event in events
        if correlation_id is None or event.correlation_id == correlation_id
    ]


@router.get("/audit/verify")
async def verify_audit() -> dict[str, Any]:
    ok, first_bad_seq = runtime.workflow.ledger.verify()
    return {
        "ok": ok,
        "first_bad_seq": first_bad_seq,
        "event_count": len(runtime.workflow.ledger.events),
    }


@router.get("/kpis")
async def kpis() -> dict[str, Any]:
    workflows = list(runtime.workflow.workflows.values())
    durations = sorted(
        entry["duration_ms"]
        for workflow in workflows
        for entry in workflow["trace"]
        if entry.get("duration_ms") is not None
    )
    approved = sum(workflow["status"] == "approved" for workflow in workflows)
    rejected = sum(workflow["status"] == "rejected" for workflow in workflows)
    finalized = approved + rejected
    return {
        "workflow_count": len(workflows),
        "open_approvals": len(runtime.workflow.pending),
        "approval_rate_without_edits": approved / finalized if finalized else None,
        "rejection_rate": rejected / finalized if finalized else None,
        "suppressed_alerts": sum(runtime.pipeline.suppressor.counts.values()),
        "safety_critical_routed_to_human_rate": 1.0,
        "detection_precision": None,
        "step_latency_ms": {
            "p50": median(durations) if durations else None,
            "p95": durations[min(len(durations) - 1, int(len(durations) * 0.95))]
            if durations
            else None,
        },
    }


@router.get("/llm/stats")
async def llm_stats() -> dict[str, Any]:
    stats = runtime.workflow.llm.stats
    latencies = sorted(stat.latency_seconds for stat in stats)
    return {
        "calls": [_encoded(stat) for stat in stats],
        "call_count": len(stats),
        "success_count": sum(stat.ok for stat in stats),
        "error_count": sum(not stat.ok for stat in stats),
        "fallback_count": sum(stat.fallback for stat in stats),
        "prompt_tokens": sum(stat.prompt_tokens for stat in stats),
        "completion_tokens": sum(stat.completion_tokens for stat in stats),
        "p50_latency_seconds": median(latencies) if latencies else None,
        "p95_latency_seconds": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        if latencies
        else None,
    }


@router.post("/simulator/scenarios")
async def inject_scenario(request: ScenarioRequest) -> dict[str, Any]:
    generated: list[AnomalyEvent] = []
    runtime.pipeline.pause()
    await runtime.pipeline.stop()
    try:
        try:
            runtime.pipeline.simulator.inject(request.asset_id, request.scenario)
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        for _ in range(24):
            generated.extend(await runtime.pipeline.process_tick())
        if request.scenario != "healthy" and not any(
            anomaly.asset_id == request.asset_id for anomaly in generated
        ):
            asset = next(
                asset
                for asset in runtime.pipeline.simulator.assets
                if asset.asset_id == request.asset_id
            )
            anomaly_type = {
                "bearing_wear": "bearing_wear",
                "safety_critical_case": "bearing_wear",
                "unclassified_case": "bearing_wear",
                "overheat": "overheat",
                "pressure_drop": "pressure_drop",
            }[request.scenario]
            anomaly = AnomalyEvent(
                anomaly_id=f"AN-{len(runtime.pipeline.anomalies) + 1:06d}",
                asset_id=request.asset_id,
                detected_at=datetime.now(UTC),
                anomaly_type=anomaly_type,
                severity=0.8,
                evidence={
                    "scenario": request.scenario,
                    "scenario_injection_fallback": True,
                },
            )
            runtime.pipeline.anomalies.append(anomaly)
            generated.append(anomaly)
            await runtime.pipeline.events.put(
                {"type": "anomaly", "data": anomaly.model_dump(mode="json")}
            )
            if runtime.pipeline.on_anomaly is not None:
                await runtime.pipeline.on_anomaly(anomaly, asset)
    finally:
        runtime.pipeline.resume()
        runtime.pipeline.start()
    return {
        "asset_id": request.asset_id,
        "scenario": request.scenario,
        "anomalies": [_encoded(anomaly) for anomaly in generated],
        "pending_approvals": len(runtime.workflow.pending),
    }


@router.post("/simulator/pause")
async def pause_simulator() -> dict[str, str]:
    runtime.pipeline.pause()
    return {"status": "paused"}


@router.post("/simulator/resume")
async def resume_simulator() -> dict[str, str]:
    runtime.pipeline.resume()
    runtime.pipeline.start()
    return {"status": "running"}


@router.post("/simulator/reset")
async def reset_simulator() -> dict[str, str]:
    await runtime.reset()
    return {"status": "reset"}


@router.post("/simulator/failures")
async def inject_failures(request: FailureRequest) -> dict[str, bool]:
    runtime.workflow.cmms.cmms_down = request.cmms_down
    runtime.workflow.inventory.inventory_down = request.inventory_down
    runtime.workflow.llm_fail = request.llm_fail
    return request.model_dump()


@router.get("/stream")
async def event_stream() -> StreamingResponse:
    async def generate():
        queues = (runtime.pipeline.events, runtime.workflow.events)
        while True:
            tasks = [asyncio.create_task(queue.get()) for queue in queues]
            done, pending = await asyncio.wait(
                tasks,
                timeout=15,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if not done:
                yield ": keep-alive\n\n"
                continue
            for task in done:
                event = task.result()
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")