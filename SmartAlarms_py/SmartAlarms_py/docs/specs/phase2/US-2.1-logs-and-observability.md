# Specification ID: US-2.1

## 1) Header

- **Title:** Adding logs analysis and richer observability
- **Phase:** Phase 2
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`

## 2) Problem Statement

After the Phase 1 flow works, the service should incorporate log analysis and structured observability without changing
the core domain model.

## 3) User Story

> As an operator, I want logs analysis and better telemetry, so that I can understand the service behavior and incident
> context more clearly.

## 4) Scope

### In scope

- Logs adapter integration
- Structured logging
- Request tracing
- Token and cost attribution

### Out of scope

- Radical architectural changes
- Full distributed tracing platform design and Langfuse instrumentation (covered separately in
  `US-2.2-langfuse-tracing.md`)
- Mandatory MCP adoption in every flow

## 5) Acceptance Criteria

| ID   | Given                                   | When                                              | Then                                                                                                                                                      |
|------|-----------------------------------------|---------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | Logs are enabled                        | The analysis runs                                 | Relevant log signals are fetched and used when available                                                                                                  |
| CA-2 | Structured INFO logging is configured   | A request is processed                            | Exactly one structured JSON summary log is emitted per request containing `request_id`, `itsm_summary`, `llm_summary`, and `latency_ms`                   |
| CA-3 | Debug/error event logging is configured | An ITSM, log, or LLM dependency fails or executes | The system emits structured event-level debug/error records with `request_id`, component, status, and error details while preserving graceful degradation |
| CA-4 | Tracing is configured                   | A request is processed                            | The main analysis stages are traceable through a common `request_id`                                                                                      |
| CA-5 | Token and cost tracking is enabled      | The request completes                             | Usage metadata is recorded per request and associated with the same request identifier                                                                    |

## 6) Functional Design

- Entry point: domain layer in the existing analysis flow.
- Inputs: incident context, optional log sources, LLM request metadata, and request timing.
- Outputs: enriched incident response plus telemetry records.
- Happy path: domain calls the logs infrastructure adapter, normalizes signals, includes only useful data, and records
  telemetry.
- Error path: log-source failures do not block the main analysis response; the system instead emits a structured error
  log and continues with the best available data.
- Logging model: two levels are required:
    - `INFO`: exactly one summary log per processed request with aggregated outcome metrics.
    - `DEBUG`/`ERROR`: event-level execution and failure logs for tool and external dependency execution; this level is
      used for operational visibility and troubleshooting.

### INFO log contract

The `INFO`-level structured log must follow the format below and must be emitted once per request after the pipeline has
produced the final operational summary:

```json
{
  "request_id": "UUID",
  "itsm_summary": {
    "status": "200",
    "error": "error message",
    "main_incident": "INC001",
    "fetched_incidents": [
      "INC002",
      "INC003"
    ],
    "fetched_incidents_by_title": [
      "INC003",
      "INC004"
    ],
    "summary": true,
    "suggestions_number": 7
  },
  "llm_summary": {
    "status": "200",
    "error": "error message",
    "tokens_in": 333,
    "tokens_out": 3000,
    "cost_usd": 0.0333213
  },
  "latency_ms": 40000.23
}
```

Notes:

- `request_id` must be a UUID generated once per request and propagated through all downstream stages.
- `itsm_summary.status` represents the worst external HTTP status code observed across all ITSM calls in the request.
  The value must be the most negative response code seen in the phase: `"200"` for full success, `"400"` when any ITSM
  call returns a degraded or partial failure that still allows the request to continue, and higher values only when a
  true failure is encountered. In other words, in the range `200` to `400`, the effective value stays at `400` rather
  than a more optimistic intermediate status.
- `itsm_summary.error` must be empty or null when the phase succeeds; in failure cases it must contain the
  human-readable exception or reason. If more than one ITSM error occurs, the messages must be concatenated in a single
  string, preserving the order in which the failures were observed.
- `main_incident` identifies the primary incident being investigated.
- `fetched_incidents` contains the list of related incident IDs returned from the ITSM correlation/fetch stage for the
  main incident.
- `fetched_incidents_by_title` contains the list of incident IDs obtained from the title-based LLM correlation step for
  the `main_incident`.
- `summary` indicates whether the final summary generation was completed.
- `suggestions_number` records the number of mitigation suggestions produced.
- `llm_summary.status` is the HTTP status code returned by the external LLM service for the summarization/enrichment
  call. When multiple LLM calls are involved, the worst status code must be retained, using the same rule as the ITSM
  phase.
- `llm_summary.error` must be empty when the LLM call succeeds; if the call fails, the message must contain the external
  error description, and multiple failures must be concatenated in order.
- `llm_summary` captures the LLM call outcome for the summation/enrichment stage, including input/output tokens and
  cumulative estimated cost in USD.
- `latency_ms` is the total request latency in milliseconds, measured from request entry to final response assembly.

### DEBUG / ERROR log contract

A structured `DEBUG` or `ERROR` event log must be emitted whenever a dependency is invoked or fails. This level captures
execution detail and failure context without replacing the single request summary. The minimum required contract is:

```json
{
  "request_id": "UUID",
  "level": "DEBUG|ERROR",
  "component": "itsm|llm|logs|analysis",
  "status": "500",
  "error": "error message",
  "workflow": "incident_summary",
  "latency_ms": 42000.12
}
```

When multiple errors happen in the same request, their messages must be concatenated in the same order they occurred.
This log complements the `INFO` summary log and is intended for troubleshooting, while preserving graceful degradation
in the main response.

## 7) Data and Integration Design

- External dependencies: logs providers, ITSM, LLM providers, and observability backends.
- Identity/permissions assumptions: server-managed access.
- Correlation: all stages must share a common `request_id` so logs can be linked across the pipeline.
- Normalization: ITSM and LLM summary fields must be standardized before logging to ensure consistent `status`, `error`,
  and numeric fields.

## 8) Token Efficiency Design

- Filter logs before prompt construction.
- Keep only the most relevant signals.
- Log summary metrics after the pipeline, rather than logging oversized raw payloads.

## 9) Observability

- Structured `INFO` logs with final request outcome, incident summary metadata, LLM metrics, and latency.
- Structured `DEBUG`/`ERROR` event logs with request correlation, failing component, error details, and external HTTP
  status codes.
- Traces across fetch, normalize, analyze, and respond steps using a common `request_id`.
- Usage fields for token count and cost.
- Source attribution for the main incident, related incidents, and title-based correlation decisions.

## 10) Risks and Mitigations

| Risk                               | Impact                  | Mitigation                                                                                              |
|------------------------------------|-------------------------|---------------------------------------------------------------------------------------------------------|
| Log noise expands prompts too much | Cost and latency growth | Filter and rank logs before use                                                                         |
| Telemetry becomes inconsistent     | Harder evaluation       | Standardize request metadata early and enforce a shared `request_id`                                    |
| Error logs hide the main outcome   | Lower operator clarity  | Emit both the single `INFO` summary log and targeted `DEBUG`/`ERROR` event logs when a dependency fails |

## 11) Test Plan

### Unit tests

- Log filtering and selection.
- Telemetry payload generation.
- INFO log schema validation for `request_id`, `itsm_summary`, `llm_summary`, and `latency_ms`.
- DEBUG/ERROR log schema validation for failure and execution event cases.
- Validation that exactly one INFO summary is emitted per request.

### Integration tests

- Analysis with logs enabled.
- Request with degraded ITSM or LLM failure still emits exactly one INFO summary and a corresponding DEBUG/ERROR event
  log.
- Request lifecycle traces all stages under the same `request_id`.

## 12) Implementation Notes

- Planned files/modules:
    - `src/infrastructure/adapters/logs/*`
    - `src/infrastructure/observability/*`
    - request correlation and structured logging utilities in `src/shared/`
- Implementation must preserve two log levels only for this phase: `INFO` for the single summary record and `DEBUG`/
  `ERROR` for operational details and dependency failures.

## 13) Definition of Done

- Logs can be used in the analysis flow.
- Structured observability is available for Phase 2.
- Each processed request emits exactly one valid INFO summary log with the required fields and a common `request_id`.
- Dependency failures emit structured DEBUG/ERROR event logs without blocking the primary analysis response.
