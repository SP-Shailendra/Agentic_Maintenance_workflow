# Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| ADR-001 | In-memory adapters are the default runtime integration. | Plant, CMMS, inventory, and scheduling are explicitly simulated; vendor adapters remain non-operational stubs. |
| ADR-002 | Every workflow requires a human decision; no auto-approval policy exists. | Spend, dispatch, reservation, and safety control stay behind approval. |
| ADR-003 | Missing safety classification is treated as safety-critical. | Unknown classification must fail toward the stronger safety control. |
| ADR-004 | Part availability checks are read-only; reservations happen only after approval. | Prevents unapproved work from consuming inventory. |
| ADR-005 | Use a plain append-only application ledger with canonical JSON and SHA-256 chaining. | Provides deterministic verification without relying on database extensions. |
| ADR-006 | A deterministic fake LLM is the offline default. | Tests and demos work without credentials; Groq is opt-in. |