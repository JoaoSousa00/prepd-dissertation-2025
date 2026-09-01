# Specification ID: US-1.4

## 1) Header

- **Title:** Capturing LLM usage cost and request latency
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`

## 2) Problem Statement

The project needs request-level telemetry for each live analysis call so LLM usage and runtime behavior can be observed
consistently as the service evolves. Live incidents are dynamic, so this specification focuses on runtime telemetry
instead of offline evaluation artifacts.

## 3) User Story

> As a researcher, I want the service to return or emit LLM usage cost and request latency, so that I can compare
> runtime efficiency across requests and releases.

## 4) Scope

### In scope

- Request-level latency measurement
- LLM usage metadata capture (`tokens_in`, `tokens_out`, total tokens, estimated monetary cost, model name)
- Return or emit runtime telemetry for later comparison by request and release
- Best-effort handling when the LLM provider does not supply all usage fields

### Out of scope

- Dashboards
- Human review tooling
- Advanced experiment tracking
- Benchmark reference management and fixed-dataset evaluation

## 5) Acceptance Criteria

| ID   | Given                                                                      | When                  | Then                                                                                                                                   |
|------|----------------------------------------------------------------------------|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | An analysis request triggers LLM enrichment                                | The request completes | The service records or returns request latency together with the LLM model name and usage metadata when available                      |
| CA-2 | The LLM provider returns usage metadata for a request                      | The request completes | `tokens_in`, `tokens_out`, `tokens_total`, and estimated monetary cost are normalized and linked to the analyzed incident/request      |
| CA-3 | The LLM provider omits some usage fields or cost cannot be derived exactly | The request completes | The main response is still returned, available telemetry is preserved, and missing fields are explicit rather than silently fabricated |
| CA-4 | A live request is processed for a real incident                            | The response is built | Only runtime telemetry fields are included; offline evaluation artifacts are not emitted                                               |

## 6) Functional Design

- Entry point: domain service after LLM enrichment in the normal request flow.
- Inputs: normalized LLM usage metadata from the provider or gateway plus request timing information.
- Outputs: runtime telemetry fields linked to the analyzed incident and request context.
- Happy path:
    - Domain receives provider usage metadata from the LLM adapter.
    - Domain computes end-to-end request latency for the analysis flow.
    - Domain normalizes token counts and estimated cost fields into a stable internal shape.
    - Presentation or observability layers expose the runtime telemetry without adding benchmark-only quality metrics.
- Error path:
    - If provider usage metadata is incomplete, preserve available fields and mark missing values explicitly.
    - If telemetry derivation fails, keep the main analysis response and treat telemetry failure as non-blocking.

## 7) Data and Integration Design

- External dependencies: LLM provider or gateway usage metadata response.
- Cost derivation source: provider-native usage/cost fields when available, otherwise configured pricing rules applied
  to normalized token counts.
- Cache usage: none required for the telemetry values themselves.
- Identity/permissions assumptions: none beyond request context.

## 8) Token Efficiency Design

- Do not add extra model prompts or extra provider calls for telemetry collection.
- Reuse LLM provider usage metadata returned with the request instead of triggering separate accounting calls.

## 9) Observability

- Store or emit `tokens_in`, `tokens_out`, `tokens_total`, estimated cost, model name, and end-to-end request latency.

## 10) Risks and Mitigations

| Risk                                                         | Impact                             | Mitigation                                                                 |
|--------------------------------------------------------------|------------------------------------|----------------------------------------------------------------------------|
| Provider usage metadata is absent or inconsistent            | Cost comparison becomes unreliable | Normalize the gateway response shape and surface missing fields explicitly |
| Latency measurement is captured inconsistently across stages | Release comparisons become noisy   | Define a single end-to-end request timing boundary                         |
| Telemetry derivation interrupts analysis                     | Poor user experience               | Keep telemetry best-effort and non-blocking                                |

## 11) Test Plan

### Unit tests

- Normalization of provider usage metadata and latency fields.
- Non-blocking telemetry failure handling.

### Integration tests

- LLM output produces usage cost and latency records for every completed request.

## 12) Implementation Notes

- Planned files/modules:
    - `src/application/metrics/*`
    - `src/infrastructure/observability/*`
    - Response contract updates when runtime telemetry is returned to clients

## 13) Definition of Done

- The service records request latency and normalized LLM usage cost metadata.
- Benchmark-only lexical quality metrics are excluded from the live request response.
- Telemetry gaps do not block incident analysis.
