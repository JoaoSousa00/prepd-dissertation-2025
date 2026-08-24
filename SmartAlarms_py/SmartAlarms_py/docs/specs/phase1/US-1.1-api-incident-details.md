# Specification ID: US-1.1

## 1) Header

- **Title:** Exposing the incident details API
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Implemented
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`, `docs/contracts/openapi.json`

## 2) Problem Statement

The service needs a first stable entry point so clients can call the incident analysis flow through a documented API contract.

## 3) User Story

> As a client, I want a documented API endpoint for incident details, so that I can start integrating with the service.

## 4) Scope

### In scope
- `GET /incident/details`
- Query parameter validation for `incidentIds`
- Structured success and error responses following the contract
- Basic request routing through the presentation layer

### Out of scope
- External client integrations
- LLM calls
- Metrics
- Logs analysis

## 5) Acceptance Criteria

| ID | Given | When | Then |
|----|-------|------|------|
| CA-1 | The API is running | A client calls `GET /incident/details` with `incidentIds` | The endpoint exists and responds through the documented contract |
| CA-2 | `incidentIds` is missing or invalid | The endpoint is called | The service returns `400` with a structured error response |
| CA-3 | The request is valid but no incidents are available yet | The endpoint is called | The service returns a valid contract-aligned response shape |

## 6) Functional Design

- Entry point: REST API endpoint.
- Inputs: repeated `incidentIds` query values.
- Outputs: contract-aligned JSON response and standard error responses.
- Happy path: validate request, call domain layer to fetch and shape incident data, return a valid response envelope.
- Error path: reject invalid input early.

## 7) Data and Integration Design

- External dependencies: none in this step.
- Cache usage: none.
- Identity/permissions assumptions: none (authentication is handled by API Gateway).

## 8) Token Efficiency Design

- No LLM usage in this step.
- Keep the API response minimal and contract-driven.

## 9) Observability

- Keep observability minimal in Phase 1 step 1.

## 10) Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Endpoint contract drifts from the OpenAPI file | Integration breaks | Keep response shapes aligned with `docs/contracts/openapi.json` |
| Validation becomes inconsistent | Unclear client errors | Centralize query validation in the presentation layer |

## 11) Test Plan

### Unit tests
- Query validation.
- Error response formatting.

### Integration tests
- Endpoint reachable with the documented route.

## 12) Implementation Notes

- Planned files/modules:
  - `src/presentation/api/*`
  - `src/shared/http/*`
- Dependency changes: none yet.

## 13) Definition of Done

- The endpoint is available.
- The contract is respected.
- Invalid requests are rejected cleanly.
