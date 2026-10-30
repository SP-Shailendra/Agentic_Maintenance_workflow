# Five-Minute Demo Script

## 0:00-0:45 | Establish the boundary

Open the Command Center. Point out that the plant is simulated, integrations are in-memory mocks, and the dashboard is a development demo. Show the stream status, live/shadow mode, fleet safety markings, and the L1-L8 pipeline strip. State that there is no OT connection.

## 0:45-1:30 | Inject a safety-critical event

Open Simulator. Select `IC-001` and inject `Safety-critical case`. The simulator advances a deterministic run of ticks; the pipeline emits telemetry and an anomaly. Open the approval queue and show the `safety_critical` reason.

## 1:30-2:30 | Inspect evidence and draft

Open the approval package. Expand the diagnosis citation and compare its passage with the synthetic chiller manual. Review the draft tasks, cost, parts availability, and technician proposal. Show that the work order is still a draft and inventory counts have not changed.

## 2:30-3:15 | Demonstrate a rejection path

For a separate package, enter a decision reason and reject it. Confirm the work order is rejected and no reservation was committed. Rejection reasons are structured feedback and part of the audit record.

## 3:15-4:00 | Demonstrate approval and parts commit

Open another non-safety demo package. Approve it. Confirm that the work order changes status and parts are reserved only after the decision. In a real plant, use the required qualified approver and approved site process; the development header is not authentication.

## 4:00-4:35 | Demonstrate degraded behavior

On Simulator, enable the inventory failure toggle and inject a fault. Review the package's `partial` label and parts-TBC status. Clear the toggle. The package remains with a human; dependency failure does not become silent continuation.

## 4:35-5:00 | Verify the ledger

Open Audit Ledger and press `Verify chain`. Point out sequence numbers and hash prefixes. Close by stating that the live demo ledger is in-memory and that the Postgres schema/checkpointer helpers are not yet wired to preserve runtime state across restarts.
