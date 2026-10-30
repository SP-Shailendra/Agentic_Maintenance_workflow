# 14-Day Work Plan

| Day | Gate | Deliverable |
| --- | --- | --- |
| 1 | Foundation | Schemas, config, policies, adapters, ledger, CI, local tooling |
| 2 | Data | Database models/migrations and seeded plant data |
| 3 | Data | Deterministic simulator, normalizer, bus, persisted pipeline |
| 4 | Detection | Rolling features, health index, SPC, suppression |
| 5 | Detection | Isolation Forest, ensemble, shadow path, evaluation report |
| 6 | Grounding | Synthetic manuals, chunking, fault codes, keyword retrieval |
| 7 | LLM | Groq structured outputs, strict schema, fake model, tests |
| 8 | Agents | Diagnosis, draft work order, parts check, scheduling |
| 9 | HITL | Graph interrupt/resume, mandatory approval, decisions |
| 10 | HITL | SLA timers, audit coverage, feedback and KPI calculations |
| 11 | API | REST endpoints, authentication hook, SSE |
| 12 | Dashboard | Live shell, command center, anomalies, assets |
| 13 | Dashboard | Approvals, trace, ledger, system, simulator |
| 14 | Release gate | Failure injection, synthetic SLO run, docs, fresh-clone check |

## Risks

- Groq model availability and strict-schema support may change; model names are configurable and fake mode remains available.
- Embedding downloads can fail or be unavailable offline; retrieval must retain a keyword fallback.
- Durable approval resume depends on the configured PostgreSQL checkpointer.
- Synthetic detections do not establish real plant performance.

## Cut-list

Defer stretch features (LSTM, public dataset replay, real CMMS connectivity, MQTT, and outbound email/Teams) until the acceptance gates pass. No OT connectivity is in scope.