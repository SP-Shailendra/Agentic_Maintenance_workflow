# API Reference

Base URL: `http://localhost:8000/api/v1`. Interactive OpenAPI documentation is at `/docs`.

In development, approval identity comes from the `X-Approver-Id` header (defaults to `dev-approver`). This is an identity hook, not production authentication. An OIDC/API-key middleware must replace it before deployment. Decision bodies must include a matching `correlation_id`; rejection and escalation require a non-empty reason.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness, runtime mode, and component status |
| GET | `/system/config` | Non-secret models, adapters, guardrails, and layers |
| GET | `/assets` | Seeded fleet with health index |
| GET | `/assets/{id}` | Asset details |
| GET | `/assets/{id}/telemetry?window=1h` | Telemetry (`1m`, `5m`, `15m`, `1h`, `24h`) |
| GET | `/anomalies?asset_id=&shadow=&limit=` | Detected anomalies |
| GET | `/anomalies/suppressed` | Suppression counts and examples |
| GET | `/workflows` | Workflow records |
| GET | `/workflows/{correlation_id}` | State, trace, and decisions |
| GET | `/approvals?status=pending` | Pending packages sorted by SLA |
| GET | `/approvals/{correlation_id}` | Approval package |
| GET | `/technicians` | Available technicians for human-approved reassignment |
| POST | `/approvals/{correlation_id}/decision` | Approve, modify_approve, reject, or escalate |
| GET | `/audit?correlation_id=` | Hash-chained audit events |
| GET | `/audit/verify` | Chain validity and first failing sequence |
| GET | `/kpis` | Runtime workflow and suppression metrics |
| GET | `/llm/stats` | LLM call outcomes, token totals, and latency |
| POST | `/simulator/scenarios` | Configure a timed, seeded scenario; returns ground truth separately from detector output |
| GET | `/simulator/scenarios` | List active scenarios and remaining ticks |
| DELETE | `/simulator/scenarios/{asset_id}` | Clear an asset's active scenario |
| POST | `/simulator/demo-workflow` | Send a clearly labeled event directly to workflow approval, bypassing detection |
| POST | `/simulator/pause` | Pause simulator loop |
| POST | `/simulator/resume` | Resume simulator loop |
| POST | `/simulator/reset` | Reset in-memory demo services and simulator |
| POST | `/simulator/failures` | Inject CMMS, inventory, and fake-LLM failures |
| GET | `/stream` | Server-sent event stream |

Scenario injection accepts `asset_id`, `scenario`, `severity` (0-1), `duration_ticks` (default 120), and optional `seed`. Its response keeps scenario ground truth separate from `anomalies`; a detector miss remains a miss. Use `/simulator/demo-workflow` only when demonstrating the approval workflow independently of anomaly detection.

## Decision Body

```json
{
  "correlation_id": "AN-WD-001",
  "decision": "approve",
  "approver": "ignored-in-dev-header-wins",
  "reason": null,
  "modifications": {}
}
```

Allowed decisions are `approve`, `modify_approve`, `reject`, and `escalate`. The route overwrites the submitted approver with the development header identity. `reject` and `escalate` require `reason`. Modifications are validated by revalidating the resulting work-order schema.

## SSE Events

`GET /stream` uses `text/event-stream`; each message has the event name and a JSON `data` field. Implemented event names are `telemetry`, `anomaly`, `suppressed`, `workflow_step`, `approval_requested`, `approval_decided`, `sla_warning`, `sla_escalated`, `audit_event`, `scenario_started`, `scenario_cleared`, and `workflow_demo_injected`. The stream emits a comment heartbeat while idle. The current demo runtime is process-local; events are not durable across backend restarts.

The current API reports database readiness as `configured_not_connected_in_memory_mode`. PostgreSQL metadata, Alembic schema, and a durable LangGraph checkpointer are included, but the demo API does not claim that its runtime records are persisted to those tables.