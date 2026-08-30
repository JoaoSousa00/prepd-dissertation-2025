# Specification ID: US-1.2

## 1) Header

- **Title:** Fetching base incident data from the client
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Implemented
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`, `docs/contracts/openapi.json`

## 2) Problem Statement

After the API exists, the service needs a simple client flow that retrieves the minimum incident fields before any advanced analysis is added.

## 3) User Story

> As a support analyst, I want the service to fetch the base incident record, so that I can see the core incident information first.

## 4) Scope

### In scope
- Client-side or adapter-side retrieval of incident records by ID
- Returning the base incident fields: `id`, `shortDescription`, and `description`
- Explicit filtering of sensitive or oversized source fields before domain mapping
- Handling one or more incident IDs in a single request

### Out of scope
- LLM enrichment
- Related incident correlation
- Logs analysis
- Metrics
- Passing through raw source payload fields unrelated to the base model

## 5) Acceptance Criteria

| ID | Given | When | Then |
|----|-------|------|------|
| CA-1 | One valid incident ID exists | The service requests incident data | The base incident fields are returned |
| CA-2 | Multiple incident IDs are provided | The service requests incident data | The response contains one base record per found incident |
| CA-3 | An incident ID is not found | The service requests incident data | The missing incident is skipped without breaking the whole request |
| CA-4 | The external incident source is unavailable | The service requests incident data | The request degrades gracefully and returns available results |
| CA-5 | Source payload includes `caller_id`, `assigned_to`, `resolved_by`, or `attachments` | The service maps incidents to the base model | These fields are not parsed to domain models and are excluded from any downstream payload (including LLM input) |

## 6) Functional Design

- Entry point: domain service called by the API.
- Inputs: incident IDs.
- Outputs: a normalized base incident model.
- Happy path: domain calls the ITSM infrastructure adapter to fetch incident records, maps to base model, and returns.
- Error path: unavailable optional records do not stop the whole batch.
- Mapping constraint: only `id`, `shortDescription`, and `description` are mapped; `caller_id`, `assigned_to`, `resolved_by`, and `attachments` are dropped at adapter/domain boundary.

## 7) Data and Integration Design

- External dependencies: ITSM/in incident source adapter.
- Cache usage: none required yet.
- Identity/permissions assumptions: the adapter uses server-managed credentials.
- Data minimization rule: sensitive personal fields (`caller_id`, `assigned_to`, `resolved_by`) and potentially large uncontrolled field (`attachments`) must not cross into domain objects.

## 8) Token Efficiency Design

- Reduce analysis scope by fetching only base fields in this step.
- Do not call the LLM.
- If this base model is reused by later phases, excluded fields (`caller_id`, `assigned_to`, `resolved_by`, `attachments`) remain unavailable for LLM prompts.

## 9) Observability

- Minimal request logging only if already present.

## 10) Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Inconsistent incident field mapping | Bad API output | Normalize to a small base model |
| One missing incident breaks the batch | Poor usability | Continue with the remaining incident IDs |

## 11) Test Plan

### Unit tests
- Mapping from source payload to base model.
- Missing-record handling.
- Filtering behavior that drops `caller_id`, `assigned_to`, `resolved_by`, and `attachments`.

### Integration tests
- Multiple incident IDs return multiple base records.

## 12) Implementation Notes

- Planned files/modules:
  - `src/infrastructure/adapters/itsm/*`
  - `src/application/incident_fetching/*`
  - `src/domain/incident/*`

## 13) Definition of Done

- The service can fetch and return base incident data.
- Missing and unavailable sources are handled safely.
