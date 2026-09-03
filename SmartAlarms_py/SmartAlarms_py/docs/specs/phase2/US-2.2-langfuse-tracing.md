# Specification ID: US-2.2

## 1) Header

- **Title:** Distributed tracing with Langfuse and OpenTelemetry
- **Phase:** Phase 2
- **Owner:** Spec Architect
- **Status:** Implemented
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`,
  `docs/specs/phase2/US-2.1-logs-and-observability.md`

## 2) Problem Statement

Phase 2.1 defines structured request logs, but it does not define a consistent tracing backend or cross-component span
model. Without explicit tracing, operators cannot correlate the main analysis flow across ITSM, logs, and LLM calls.
This creates blind spots when latency is high or a dependency fails, and it makes request-level token usage harder to
attribute correctly.

This specification adds a dedicated Langfuse/OpenTelemetry tracing layer for SmartAlarms so each request can be tracked
end-to-end using a shared `request_id` and common span conventions. The project does not define a separate cache layer,
so tracing focuses on actual request stages and external calls instead of inventing a cache tier.

## 3) User Story

> As an operator or developer, I want every significant request stage to emit correlated spans in Langfuse, so that I
> can trace a request end-to-end, diagnose latency outliers, and attribute failures and token usage to a specific
> request.

## 4) Scope

### In scope

- Initialize an OpenTelemetry tracer provider at service startup.
- Configure Langfuse as the trace backend via OTLP-compatible exporter settings.
- Emit a root span for each incoming request and child spans for adapter and LLM operations.
- Propagate `trace_id`/`span_id` through W3C `traceparent` headers on outbound HTTP calls.
- Require a shared `request_id` attribute on all spans.
- Standardize span naming and attribute contracts for the main SmartAlarms components.
- Allow tracing to be disabled cleanly without failing the primary request flow.
- Keep structured logs from US-2.1 and tracing from US-2.2 complementary, not redundant.

### Out of scope

- Full Prometheus metric export design beyond basic exporter health and error reporting.
- Advanced adaptive sampling or custom trace routing.
- Long-term storage and retention management for Langfuse.
- Redesign of the incident analysis domain model.

## 5) Acceptance Criteria

| ID   | Given                                            | When                      | Then                                                                                                                          |
|------|--------------------------------------------------|---------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | a request is processed end-to-end                | tracing is enabled        | a single Langfuse trace includes all relevant spans for the request under one `trace_id`                                      |
| CA-2 | a request enters the service                     | processing begins         | a root span is created with `request_id`, `workflow`, and `status` attributes                                                 |
| CA-3 | an ITSM or logs adapter makes an outbound call   | the call executes         | a child span named `itsm.*` or `logs.*` is emitted with `operation`, `status`, and `latency_ms`                               |
| CA-4 | the LLM gateway completes a request              | the provider call returns | a child span named `llm.complete` includes `provider`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, and `retry_count`      |
| CA-5 | an outbound HTTP call is made by any adapter     | the request is sent       | the `traceparent` header is injected with a valid W3C trace context                                                           |
| CA-6 | any dependency fails                             | the error is handled      | the active span is marked `ERROR`, includes `error.code`, and records the exception                                           |
| CA-7 | tracing is disabled via configuration            | a request runs            | no trace spans are emitted and the request still completes normally                                                           |
| CA-8 | the service starts                               | initialization runs       | the Langfuse exporter is configured from environment variables; failures fall back to a no-op tracer without aborting startup |
| CA-9 | the span conventions are applied across adapters | spans are created         | all names follow the pattern `component.operation` in lowercase and use the shared `request_id`                               |
| CA-10 | the service starts                              | startup observability runs | one startup status log reports whether Langfuse is connected (`connected`/`not_connected`) and includes non-secret diagnostics |

## 6) Functional Design

- Entry point: every request entering the incident analysis pipeline, including API-driven flows and any future IDE or
  automation trigger.
- Inputs: request context, `request_id`, workflow name, dependency metadata, and component-specific identifiers.
- Outputs: span records visible in Langfuse, correlated by `trace_id` and `request_id`, while preserving the domain
  result and structured logs from US-2.1.
- Happy path: start a root request span at the boundary, create child spans for each dependency and LLM call, set
  attributes, close the spans, and keep the analysis flow unchanged.
- Error path: record exception details, mark the span as `ERROR`, propagate the failure safely to the main request
  logic, and ensure graceful degradation remains in place.

### Span naming convention

All spans must follow `component.operation` and remain lowercase, dot-separated.

Examples:

- `request.analysis`
- `itsm.fetch_incident`
- `logs.fetch_events`
- `llm.complete`
- `llm.request_attempt`

### Mandatory span attributes

All spans must include:

- `request_id`: stable per request
- `workflow`: e.g. `incident_summary`
- `component`: logical component name
- `status`: `ok` or `error`
- `latency_ms`: measured duration

Component-specific attributes:

- LLM spans: `provider`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, `retry_count`
- ITSM/logs spans: `endpoint`, `status_code`, `resource_id` where relevant

### Tracer utility

All components must obtain a tracer via a shared utility rather than using the raw OTel SDK directly. This keeps span
naming, request ID propagation, and error handling consistent.

```python
with tracer.start_as_current_span("llm.complete") as span:
    span.set_attribute("request_id", request_id)
    span.set_attribute("workflow", workflow)
    span.set_attribute("provider", provider_name)
    span.set_attribute("model", model_name)
    ...
```

## 7) Data and Integration Design

- External dependency: Langfuse-compatible OTLP exporter for traces.
- Runtime config: `TRACING_ENABLED`, `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY`, and service metadata such as `OTEL_SERVICE_NAME`.
  - `LANGFUSE_BASE_URL` is the browser/UI base URL for the Langfuse instance (for example a self-hosted deployment).
  - OTLP endpoint is derived internally from `LANGFUSE_BASE_URL` using `/api/public/otel/v1/traces`; no separate
    `LANGFUSE_OTLP_ENDPOINT` variable is required.
- Safe attributes: only identifiers and counts are allowed in span attributes; avoid full incident payloads, raw
  prompts, raw logs, or credentials.
- Correlation model: every stage in the pipeline must share the same `request_id` and connect to the same root trace.
- Compatibility: tracing is additive and should not replace the structured JSON logs described in US-2.1.

## 8) Token Efficiency Design

- Span emission should be batched by the OTLP exporter to avoid synchronous overhead on the hot path.
- Only minimal metadata is captured in spans; raw request or response bodies remain out of scope.
- Cost and token data are captured once from the LLM response and reused in both telemetry and Langfuse attributes.

## 9) Observability

- Langfuse trace timeline for the full request lifecycle.
- Latency and error visualization by component and operation.
- Request correlation across ITSM, logs, and LLM stages via a shared `request_id`.
- Cost attribution and token usage per LLM span, enabling evaluation and debugging.
- Startup diagnostics for Langfuse connectivity status and missing config fields without exposing secrets.
- The single summary log in US-2.1 remains the source of highest-level request outcome; Langfuse provides deeper
  operational tracing.

## 10) Risks and Mitigations

| Risk                                    | Impact                   | Mitigation                                                                  |
|-----------------------------------------|--------------------------|-----------------------------------------------------------------------------|
| Tracing adds overhead to every request  | Higher latency and noise | Batch exporter, minimal attribute set, no-op fallback when disabled         |
| Missing `request_id` breaks correlation | Hard-to-debug traces     | Require `request_id` at the entry point and validate in the tracing utility |
| Sensitive data leaks in spans           | Security issue           | Restrict attributes to approved identifiers and counters only               |
| Langfuse unavailable                    | No trace visibility      | Use async exporter and no-op fallback without aborting the request          |

## 11) Test Plan

### Unit tests

- Tracer initialization uses environment config when enabled.
- Disabled tracing returns a no-op tracer and does not raise errors.
- Span attributes include required keys (`request_id`, `workflow`, `status`).
- Exception handling marks the span as `ERROR` and records the exception.
- W3C `traceparent` is injected on outbound HTTP requests.

### Integration tests

- End-to-end request emits a trace with root span plus child spans for ITSM, logs, and LLM stages.
- The same `request_id` appears across all spans in the trace.
- A failing LLM or adapter call produces an `ERROR` span with `error.code`.
- A request with tracing disabled still completes and produces no traces.

## 12) Implementation Notes

- Planned files/modules:
    - `src/infrastructure/observability/`
    - `src/shared/tracing.py` or equivalent tracing utility
    - adapter-level instrumentation around ITSM/logs and LLM calls
- Implemented span set includes: `request.analysis`, `itsm.fetch_incident`, `llm.fetch_token`, `llm.request_attempt`,
  and `llm.complete`.
- Dependencies: OpenTelemetry SDK and Langfuse OTLP exporter packages.
- Initialization should be performed at application startup and fail gracefully when configuration is missing or
  invalid.
- This spec is intentionally narrower than a full platform observability layer; it focuses on request correlation and
  dependency-level visibility for SmartAlarms.

## 13) Definition of Done

- The service emits correlated, request-scoped spans in Langfuse when tracing is enabled.
- Structured logging from US-2.1 and tracing from US-2.2 work together without duplication or conflicts.
- Every major request stage has a consistent span name and attribute contract.
- A disabled tracing configuration keeps the service operational with no trace output.
- The request lifecycle can be debugged through a single trace and common `request_id`.
