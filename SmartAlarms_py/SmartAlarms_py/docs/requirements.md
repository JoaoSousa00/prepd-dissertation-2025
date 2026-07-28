# SmartAlarms Requirements

**Status:** Draft v1  
**Last updated:** 2026-07-28  
**Scope:** Academic incident analysis service for CI/IDE and API usage

## 1) Product Goal

SmartAlarms provides incident analysis and mitigation support for developers in an academic context, helping teams understand incidents faster and resolve them more efficiently through a modular pipeline with controllable external integrations.

## 2) In Scope

- Analyze incident context and produce actionable diagnosis and mitigation suggestions.
- Provide an API endpoint that returns a full analysis payload.
- Allow per-request control of external integrations (logs, Confluence, ITSM history).
- Keep architecture aligned with layered design (`domain`, `application`, `infrastructure`, `presentation`).
- Measure token usage, latency, and source usage for experiments and evaluation.

## 3) Out of Scope (Current)

- Persistent database for long-term state/cache.
- Autonomous remediation execution in production systems.
- Full enterprise SLA/SLO commitments.
- Mandatory dependency on all external systems for every analysis request.

## 4) Functional Requirements

### 4.1 Entry Points

- **FR-1.1 API analysis trigger:** users can request incident analysis via HTTP endpoint.
- **FR-1.2 IDE/automation compatibility:** endpoint and service design must support IDE-assisted and automation-driven workflows.

### 4.2 Configurable Analysis Endpoint

- **FR-2.1 Full analysis response:** endpoint returns a complete analysis object (incident summary, correlated signals, probable causes, mitigation suggestions, confidence/justification metadata).
- **FR-2.2 External integration toggles:** request supports flags to enable/disable external calls:
    - `use_logs` (Kibana/Elastic/CloudWatch)
    - `use_confluence` (knowledge/guidelines)
    - `use_itsm_history` (historical incidents)
- **FR-2.3 Incident details always available:** even when `use_itsm_history=false`, the analysis must still use incident details provided in the request or primary incident record.
- **FR-2.4 Graceful degradation:** if a disabled or unavailable source exists, pipeline continues with available sources and records source availability in output.
- **FR-2.5 Source traceability:** response explicitly states which sources were used, skipped by config, or failed.

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
- Track source usage fields: `logs_used`, `confluence_used`, `itsm_history_used`.
- Attribute requests by `user` (when available), `workflow`, and `credential_source`.
- Export metrics to Prometheus-compatible format and traces to OTel/Langfuse-compatible backends.

## 8) Success Metrics

- Reduced mean time to understand incidents in evaluation scenarios.
- Higher relevance of mitigation suggestions in human assessment.
- Lower token consumption when optional sources are disabled versus full-source baseline.
- Stable p95 latency under expected academic concurrency.

## 9) Assumptions

- Incident payload contains enough minimum context for baseline analysis.
- External systems (ITSM/logs/Confluence) may be intermittently unavailable.
- Users can choose analysis depth by toggling source usage per request.
- The system can run useful analysis even with only incident-local data.

## 10) Open Questions

- Exact request/response schema for source toggles and source-status reporting.
- Confidence scoring strategy and thresholds for low-confidence guidance.
- Default toggle policy per workflow (API direct vs IDE-assisted).
- Minimum dataset and benchmark protocol for academic evaluation.
