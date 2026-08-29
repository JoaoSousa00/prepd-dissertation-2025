# Specification ID: US-2.1

## 1) Header

- **Title:** Adding logs analysis and richer observability
- **Phase:** Phase 2
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`

## 2) Problem Statement

After the Phase 1 flow works, the service should incorporate log analysis and structured observability without changing the core domain model.

## 3) User Story

> As an operator, I want logs analysis and better telemetry, so that I can understand the service behavior and incident context more clearly.

## 4) Scope

### In scope
- Logs adapter integration
- Structured logging
- Request tracing
- Token and cost attribution

### Out of scope
- Radical architectural changes
- Full distributed tracing platform design
- Mandatory MCP adoption in every flow

## 5) Acceptance Criteria

| ID | Given | When | Then |
|----|-------|------|------|
| CA-1 | Logs are enabled | The analysis runs | Relevant log signals are fetched and used when available |
| CA-2 | Structured logging is configured | A request is processed | The request emits structured metadata |
| CA-3 | Tracing is configured | A request is processed | The main analysis stages are traceable |
| CA-4 | Token and cost tracking is enabled | The request completes | Usage metadata is recorded per request |

## 6) Functional Design

- Entry point: domain layer in the existing analysis flow.
- Inputs: incident context and optional log sources.
- Outputs: enriched incident response plus telemetry records.
- Happy path: domain calls the logs infrastructure adapter, normalizes signals, includes only useful data, and records telemetry.
- Error path: log-source failures do not block the main analysis response.

## 7) Data and Integration Design

- External dependencies: logs providers and observability backends.
- Cache usage: reuse previously fetched guidelines or normalized context where appropriate.
- Identity/permissions assumptions: server-managed access.

## 8) Token Efficiency Design

- Filter logs before prompt construction.
- Keep only the most relevant signals.

## 9) Observability

- Structured logs with incident ID, workflow, model, and source usage.
- Traces across fetch, normalize, analyze, and respond steps.
- Usage fields for token count and cost.

## 10) Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Log noise expands prompts too much | Cost and latency growth | Filter and rank logs before use |
| Telemetry becomes inconsistent | Harder evaluation | Standardize request metadata early |

## 11) Test Plan

### Unit tests
- Log filtering and selection.
- Telemetry payload generation.

### Integration tests
- Analysis with logs enabled.

## 12) Implementation Notes

- Planned files/modules:
  - `src/infrastructure/adapters/logs/*`
  - `src/infrastructure/observability/*`

## 13) Definition of Done

- Logs can be used in the analysis flow.
- Structured observability is available for Phase 2.
