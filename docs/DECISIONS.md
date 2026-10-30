# Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| ADR-001 | In-memory adapters are the default runtime integration. | Plant, CMMS, inventory, and scheduling are explicitly simulated; vendor adapters remain non-operational stubs. |
| ADR-002 | Every workflow requires a human decision; no auto-approval policy exists. | Spend, dispatch, reservation, and safety control stay behind approval. |
| ADR-003 | Missing safety classification is treated as safety-critical. | Unknown classification must fail toward the stronger safety control. |
| ADR-004 | Part availability checks are read-only; reservations happen only after approval. | Prevents unapproved work from consuming inventory. |
| ADR-005 | Use a plain append-only application ledger with canonical JSON and SHA-256 chaining. | Provides deterministic verification without relying on database extensions. |
| ADR-006 | A deterministic fake LLM is the offline default. | Tests and demos work without credentials; Groq is opt-in. |
| ADR-007 | Availability is checked before approval; reservations are committed only after approval. | The source design notes conflict on reservation timing; the explicit safety rule forbids pre-approval reservations. |
| ADR-008 | The current API demo uses process-local state, while PostgreSQL tables/checkpointer helpers remain an opt-in foundation. | This keeps fake-mode demos runnable without a database; the API explicitly reports that state is not durable. |
| ADR-009 | The offline workflow facade is used by the API; the separately declared LangGraph graph is not yet the API's decision-resume path. | The local environment lacks LangGraph, so the actual interrupt/resume integration remains a hardening milestone rather than an unverified claim. |
| ADR-010 | Simulator ground truth is recorded separately from detector output; direct workflow demos use an explicit non-detector event source. | This prevents fallback events from masking detector misses and keeps synthetic evaluation honest. |
| ADR-011 | Scenario run outcomes use scenario IDs plus detector tick metadata; scenario labels are attached after scoring and excluded from detector features. | Enables reproducible latency/miss/false-positive reporting without leaking labels into detection. |