# SmartAlarms Requirements

**Status:** Draft v1  
**Last updated:** 2026-08-15  
**Scope:** Academic incident analysis service for CI/IDE and API usage

## 1) Product Goal

SmartAlarms provides incident analysis and mitigation support for developers in an academic context, helping teams understand incidents faster and resolve them more efficiently through a modular pipeline with controllable external integrations.

## 2) In Scope

- Analyze incident context and produce actionable diagnosis and mitigation suggestions.
- Provide an API endpoint that enriches and analyzes incidents by ID.
- Keep source-selection policy server-side in the initial version (no per-request source toggles).
- Keep architecture aligned with layered design (`domain`, `application`, `infrastructure`, `presentation`).
- Measure token usage, latency, and source usage for experiments and evaluation.

## 3) Out of Scope (Current)

- Persistent database for long-term state/cache.
- Autonomous remediation execution in production systems.
- Full enterprise SLA/SLO commitments.
- Mandatory dependency on all external systems for every analysis request.

## 4) Functional Requirements

### 4.1 Entry Points

- **FR-1.1 API analysis trigger:** users can request incident enrichment and analysis via `GET /incident/details`.
- **FR-1.2 IDE/automation compatibility:** endpoint and service design must support IDE-assisted and automation-driven workflows.

### 4.2 Analysis via GET Details Endpoint

- **FR-2.1 Request model:** endpoint accepts one or more `incidentIds` query parameters.
- **FR-2.2 Response model:** endpoint returns incident details enriched with analysis outputs relevant to mitigation (for example mitigation suggestions and related log/event references).
- **FR-2.3 Incident details availability:** analysis must be based on incident data fetched from the primary incident record (and optional related history when available).
- **FR-2.4 Graceful degradation:** if an optional source is unavailable, pipeline continues with available sources and still returns a valid response for found incidents.
- **FR-2.5 Source policy:** source enablement is controlled by server configuration/default behavior in this phase; client-side per-request toggles are deferred.

### 4.3 Data & Services Layer

- **FR-3.1 Cache:** in-memory cache only; configurable TTL for expensive artifacts (guideline summaries, normalized context).
- **FR-3.2 ITSM integration adapter:** fetch incident data and optional historical context.
- **FR-3.3 Logs integration adapter:** fetch relevant operational signals from configured log providers.
- **FR-3.4 Confluence integration adapter:** fetch operational knowledge/guidelines when enabled.
- **FR-3.5 LLM gateway:** provider abstraction for analysis/summarization tasks.
- **FR-3.6 Isolation by layer:** all external API calls remain in `infrastructure` adapters only.

## 5) Pipeline Constraints (Efficiency)

- Source filtering and normalization happen before expensive LLM calls.
- Prompt construction must be incident-focused and bounded by configurable size limits.
- Cache use must prioritize repeated guideline/context reuse.
- Startup warmup is best-effort; system falls back to on-demand fetch and cache.

## 6) Non-Functional Requirements

- **NFR-1 Academic scale:** support classroom/lab workloads with concurrent users.
- **NFR-2 Reliability:** partial-source failures do not block full response generation.
- **NFR-3 Observability:** tracing + metrics + token/cost attribution per analysis.
- **NFR-4 Security:** secrets through environment/secret manager; no hardcoded credentials.
- **NFR-5 Extensibility:** new providers/sources can be added without rewriting core orchestration.

## 7) Observability & Cost Requirements

- Track `tokens_in`, `tokens_out`, model name, latency, cache hit/miss per request.
- Track source usage fields internally: `logs_used`, `confluence_used`, `itsm_history_used`.
- Attribute requests by `user` (when available), `workflow`, and `credential_source`.
- Export metrics to Prometheus-compatible format and traces to OTel/Langfuse-compatible backends.

## 8) Success Metrics

- Reduced mean time to understand incidents in evaluation scenarios.
- Higher relevance of mitigation suggestions in human assessment.
- Lower token consumption when optional sources are disabled versus full-source baseline.
- Stable p95 latency under expected academic concurrency.

## 9) Assumptions

- Incident identifiers (`incidentIds`) are sufficient to fetch minimum context for baseline analysis.
- External systems (ITSM/logs/Confluence) may be intermittently unavailable.
- Analysis depth is controlled by server defaults/configuration in the initial version.
- The system can run useful analysis even with only incident-local data.

## 10) Open Questions

- Whether source toggles should be reintroduced later (and if so, via query parameters, headers, or a separate endpoint contract).
- Confidence scoring strategy and thresholds for low-confidence guidance.
- Default toggle policy per workflow (API direct vs IDE-assisted).
- Minimum dataset and benchmark protocol for academic evaluation.
