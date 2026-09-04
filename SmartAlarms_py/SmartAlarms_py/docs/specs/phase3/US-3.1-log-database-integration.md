# Specification: Log Database Integration for Enriched Context

- **Specification ID:** US-3.1
- **Title:** Integrate log database (CloudWatch/Kibana) to provide related transaction logs for LLM context
- **Phase:** Phase 3
- **Owner:** Software Engineering Team
- **Status:** Draft
- **Related documents:** `US-2.3-related-incident-context.md`, `docs/contracts/openapi.json`

---

## 1) Problem Statement

In Phase 2, we collected related incidents and enriched the LLM prompt with historical context. However, log data—which
provides real-time error traces, stack traces, and system behavior—is still unavailable to the LLM and not surfaced to
the user in the API response.

**Why now:** Log data directly correlates to incident root cause and resolution paths. Including transaction logs in the
LLM input improves mitigation suggestion accuracy and confidence. Surfacing related transaction IDs in the API response
helps users verify suggestions by examining actual logs.

**Constraints:**

- Log databases (CloudWatch, Kibana/Elastic) may have rate limits—must implement caching and batch queries
- Log queries should be based on transactionID extraction from incident fields (description, comments, work_notes)
- Sensitive data (PII, API keys, credentials) must be filtered before storing or sending to LLM
- Log retrieval must complete within request timeout (configurable per environment)
- Start with basic transactionID extraction; advanced log query filtering is out of scope

---

## 2) User Story

> As a **Support Engineer**, I want to **see related transaction logs linked to an incident** in both the LLM-enriched
> suggestions and the API response, so that I can **verify root cause and trace system behavior during the incident
timeline**.

---

## 3) Scope

### In scope

- Extract transactionID references from incident fields: description, comments, work_notes, close_notes, hold_reason
- Query log database (CloudWatch or Kibana) for logs matching extracted transactionIDs
- Deduplicate transaction IDs across all incident fields
- Cache transaction log results with configurable TTL
- Enrich LLM prompt with log summary (count, date range, log level distribution)
- Include relatedLogIds in LLM response and API response
- Support parallel log fetching for multiple transaction IDs
- Add environment variables for log database configuration (endpoint, credentials, max results per query)
- Add observability: track log query success/failure, cache hit rates, log volume

### Out of scope

- Advanced log filtering (regex, complex DSL queries)
- Log aggregation across multiple databases in a single request
- Real-time log streaming or subscription
- Log encryption/decryption beyond provider-native security
- Custom log field mapping (assume standard CloudWatch/Kibana field names)

---

## 4) Acceptance Criteria

| ID        | Given                                                                                                  | When                                                   | Then                                                                                                                        |
|-----------|--------------------------------------------------------------------------------------------------------|--------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| CA-3.1.1  | An incident with transactionIDs in description, comments, work_notes                                   | I call `/incident/details` endpoint                    | The response includes `relatedLogIds` as a list of unique transaction IDs found                                             |
| CA-3.1.2  | Multiple incident fields contain the same transactionID (e.g., "TXN123" in description and work_notes) | Log extraction runs                                    | transactionID appears only once in `relatedLogIds` (deduplicated, case-insensitive uppercase)                               |
| CA-3.1.3  | A log database adapter (CloudWatch or Kibana) is configured via env vars                               | The service fetches related logs                       | Each transactionID is queried in parallel; results include log count, earliest/latest timestamps, log level distribution    |
| CA-3.1.4  | A query succeeds but returns zero logs for a transactionID                                             | The transactionID is still included in `relatedLogIds` | Missing logs do not cause failure; suggestion confidence may degrade if supporting logs are absent                          |
| CA-3.1.5  | Log fetches are enabled; multiple transactionIDs exist                                                 | Service enriches incident                              | LLM prompt includes log summary section with count and date range for each transactionID                                    |
| CA-3.1.6  | `RELATED_LOGS_MAX_PER_TXN=100` and `RELATED_LOGS_ENABLED=true` env vars are set                        | An incident is enriched                                | Logs are fetched with configured limits and feature flag honored                                                            |
| CA-3.1.7  | A log query timeout occurs (e.g., network latency)                                                     | Enrichment continues                                   | Log fetch error is logged and traced; suggestion generation completes without log context; error does not halt API response |
| CA-3.1.8  | A second request arrives for the same incident within `RELATED_LOGS_CACHE_TTL_SECONDS`                 | Cache is checked                                       | Previously fetched logs are reused (cache hit); no redundant database query                                                 |
| CA-3.1.9  | Log data includes transaction metadata (timestamp, log level, service)                                 | LLM receives the prompt                                | Log summary is human-readable: "3 related logs found (ERROR: 2, WARN: 1) from 2026-09-05 10:00 to 10:15"                    |
| CA-3.1.10 | A log response contains sensitive data (IP addresses, credentials)                                     | Data is prepared for LLM                               | Sensitive patterns are masked before inclusion in LLM prompt (e.g., `192.168.1.1` → `[IP_MASKED]`)                          |

---

## 5) Functional Design

### Entry Point

- Triggered automatically during `/incident/details` enrichment workflow in Phase 2
- Conditional on `RELATED_LOGS_ENABLED=true` environment variable

### Inputs and Outputs

**Input:**

- Incident object from Phase 1 (id, description, comments, work_notes, close_notes, hold_reason)

**Process:**

1. Extract all transactionIDs (regex: `[Tt][Xx][Nn][\d]{8,}` or custom format per org) from incident fields
2. Deduplicate transactionIDs (case-insensitive uppercase)
3. Query log database for each transactionID in parallel (max workers configurable)
4. Aggregate results: for each transactionID, record:
    - `transaction_id`: The ID
    - `log_count`: Number of logs found
    - `earliest_timestamp`: Oldest log entry
    - `latest_timestamp`: Most recent log entry
    - `log_level_distribution`: `{ERROR: N, WARN: N, INFO: N, ...}`
    - `sample_logs`: Up to 3 most recent log entries (for LLM)
5. Return RelatedLogsContext object with deduplicated list of transaction IDs

**Output:**

```python
@dataclass
class RelatedLogContext:
    transaction_ids: List[str]  # Deduplicated
    logs_by_transaction: Dict[str, TransactionLogSummary]  # transaction_id -> summary
    total_logs_fetched: int
    fetch_errors: List[str]  # Log query failures


@dataclass
class TransactionLogSummary:
    transaction_id: str
    log_count: int
    earliest_timestamp: Optional[str]
    latest_timestamp: Optional[str]
    log_level_distribution: Dict[str, int]  # {ERROR: 5, WARN: 2, ...}
    sample_logs: List[str]  # Human-readable snippets
```

### Happy-Path Flow

1. Incident enrichment triggered
2. Extract transactionIDs from all text fields (description, comments, work_notes, close_notes, hold_reason)
3. Deduplicate transaction IDs
4. Query log database for each ID (parallel ThreadPoolExecutor)
5. Aggregate and summarize results
6. Pass to LLM prompt builder for inclusion in enrichment context
7. Include in API response under `relatedLogIds`

### Error-Path Flow

- Log database unavailable → Log fetch aborts, transaction_ids list remains, enrichment continues
- Timeout on individual transactionID query → Skip that ID, continue with others
- Invalid transactionID format → Filter out, log warning, continue
- All log fetches fail → Return empty RelatedLogContext, enrichment continues

---

## 6) Data and Integration Design

### External Dependencies

- **CloudWatch Logs API:** `describe_log_groups`, `filter_log_events` (boto3)
- **Kibana/Elasticsearch API:** `GET /_search` (HTTP client, basic auth or API key)
- Both via adapter pattern: `LogDatabaseAdapter` interface, concrete implementations for CloudWatch and Kibana

### Configuration

Environment variables (add to `.env_template`):

```
# Log database integration
RELATED_LOGS_ENABLED=true
RELATED_LOGS_DATABASE=cloudwatch  # or 'kibana'
RELATED_LOGS_ENDPOINT=https://logs.aws.region.amazonaws.com  # Kibana URL or CloudWatch region
RELATED_LOGS_API_KEY=xxx  # Bearer token for Kibana or AWS credentials for CloudWatch
RELATED_LOGS_MAX_PER_TXN=100  # Max logs per transaction ID
RELATED_LOGS_CACHE_TTL_SECONDS=3600  # Cache duration for transaction log results
RELATED_LOGS_TIMEOUT_SECONDS=10  # Per-query timeout
RELATED_LOGS_QUERY_PARALLELISM=5  # Max concurrent log database queries
```

### Cache Usage

- **Key format:** `log_cache:{incident_id}:{transaction_id_hash}`
- **TTL:** Configurable, default 3600 seconds
- **Invalidation:** TTL expiry; manual invalidation on incident update (if implemented)
- **Storage:** Redis (assumed to be available from Phase 1)

### Identity/Permissions

- CloudWatch: IAM role with `logs:DescribeLogGroups`, `logs:FilterLogEvents` permissions
- Kibana: API key with read access to relevant indices
- Credentials stored securely in environment variables or secrets manager

---

## 7) Token Efficiency Design

### Minimization Strategy

- **Log fetching is optional:** Disabled by default; gated by `RELATED_LOGS_ENABLED=true`
- **Caching:** Transaction log summaries cached to avoid redundant queries on repeated incidents
- **Aggregation before LLM:** Send log summary (count, date range, level distribution, 3 samples) instead of full log
  entries
- **Filtering before LLM:** Remove sensitive patterns (IPs, credentials, PII) before inclusion
- **Prompt injection guard:** Limit sample log text to 200 chars per log; truncate if exceeds limit

### Prompt Inclusion

Log summary section added to LLM prompt only if logs are available:

```
## Related Logs

3 related logs found:
- Transaction TXN20260905001: 5 logs (ERROR: 2, WARN: 3) from 2026-09-05 10:00:15 to 10:15:42
  Sample: [ERROR] Connection timeout to database at 10:05:20
```

Estimated token cost: ~50 tokens per transaction ID with summary

---

## 8) Observability

### Metrics (Prometheus)

- `smartalarms_log_queries_total{status=success|error|timeout|cache_hit}` – Counter
- `smartalarms_log_query_duration_ms{database=cloudwatch|kibana}` – Histogram
- `smartalarms_log_cache_hit_rate` – Gauge (0.0-1.0)
- `smartalarms_transaction_ids_extracted` – Histogram of count per incident
- `smartalarms_sensitive_data_masked_total{pattern=ip|credential|email}` – Counter

### Tracing (Langfuse)

- Span: `log_database_query`
    - Attributes: `database_type`, `transaction_ids_count`, `query_status`, `cache_hit`
    - Cost: actual log database API cost (if tracked)
- Span: `extract_transaction_ids`
    - Attributes: `incident_id`, `transaction_ids_found`, `extraction_source` (description|comments|work_notes)
- Span: `related_logs_context_build`
    - Attributes: `total_logs_fetched`, `fetch_errors_count`, `cache_hits`

### Cost Attribution

- Tag logs with `incident_id` for per-incident cost tracking
- Track log database API costs separately from LLM costs

---

## 9) Risks and Mitigations

| Risk                                                      | Impact                                     | Mitigation                                                                 |
|-----------------------------------------------------------|--------------------------------------------|----------------------------------------------------------------------------|
| Log database query rate limits                            | Incident enrichment timeout or degradation | Implement exponential backoff, query batching, cache with long TTL         |
| Sensitive data leakage (PII/credentials in logs)          | Privacy/compliance violation               | Regex mask sensitive patterns before LLM; audit log sample content         |
| False transactionID extraction (e.g., "TXN" in comment)   | Noise in log queries, wasted API calls     | Use stricter regex; validate against log database before inclusion         |
| Parallel log fetches overwhelm database                   | Service degradation or rate limit breach   | Limit parallelism with configurable max workers; implement circuit breaker |
| Inconsistent log database behavior (CloudWatch vs Kibana) | Adapter mismatch, user confusion           | Abstract common interface; test both adapters in CI                        |
| Log database credentials exposed in logs                  | Security breach                            | Use environment variables; rotate keys regularly; never log credentials    |

---

## 10) Test Plan

### Unit Tests

- `test_extract_transaction_ids_from_all_fields()` – Extract from description, comments, work_notes, close_notes,
  hold_reason
- `test_extract_transaction_ids_deduplication()` – Duplicate case-insensitive, normalized to uppercase
- `test_extract_transaction_ids_invalid_format_ignored()` – Invalid patterns filtered
- `test_log_cache_key_generation()` – Consistent cache key format
- `test_mask_sensitive_data_in_logs()` – IPs, credentials, emails masked
- `test_related_logs_context_builder_happy_path()` – All logs fetched, aggregated, returned
- `test_related_logs_context_builder_partial_failure()` – Some queries fail, others succeed; no crash
- `test_related_logs_context_builder_timeout()` – Timeout on individual query doesn't halt flow
- `test_log_summary_generation()` – Human-readable summary with count, date range, distribution
- `test_parallel_log_fetches_respect_concurrency_limit()` – Max workers honored

### Integration Tests

- `test_cloudwatch_adapter_queries_logs()` – Real boto3 call to CloudWatch (mocked in CI)
- `test_kibana_adapter_queries_logs()` – Real HTTP call to Kibana (mocked in CI)
- `test_log_cache_integration()` – Redis cache stores/retrieves transaction log summaries
- `test_incident_enrichment_includes_related_logs()` – E2E: incident → extract IDs → fetch logs → enrich → API response
  includes relatedLogIds
- `test_log_disabled_by_feature_flag()` – When RELATED_LOGS_ENABLED=false, no log queries occur

---

## 11) Implementation Notes

### Planned Files/Modules

- `src/infrastructure/log_adapters.py` – Abstract LogDatabaseAdapter, CloudWatchAdapter, KibanaAdapter
- `src/domain/log.py` – Domain models: RelatedLogContext, TransactionLogSummary
- `src/application/log_enrichment.py` – Service: extract_transaction_ids (), fetch_related_logs ()
- `src/infrastructure/cache/log_cache.py` – Cache integration for transaction logs
- `tests/test_log_adapters.py` – Adapter tests
- `tests/test_log_enrichment.py` – Service tests
- `docs/contracts/openapi.json` – Update ResolutionSuggestion and IncidentData to include relatedLogIds

### Dependency Changes

- Add `boto3` (for CloudWatch) to `requirements.txt` (conditional import, optional)
- Ensure `redis` is already available from Phase 1
- Ensure `httpx` or `requests` is available for Kibana HTTP calls

### Migration Notes

- `relatedLogIds` field is re-added to domain models and API contract
- Phase 2 API responses without log context are still valid (field may be None or empty)
- No database schema changes required (logs are external)

---

## 12) Definition of Done

- ✅ All acceptance criteria met and verified
- ✅ All unit and integration tests pass (target: ≥90% coverage on new modules)
- ✅ Log adapters (CloudWatch, Kibana) tested with mocked external calls
- ✅ Cache integration verified (hit rates, TTL expiry)
- ✅ Sensitive data masking tested with real patterns (IPs, credentials, emails)
- ✅ Observability metrics and traces verified in CI
- ✅ OpenAPI contract updated with relatedLogIds schema
- ✅ `.env_template` updated with log database configuration variables
- ✅ Documentation updated: architecture.md, deployment guide
- ✅ Feature flag (RELATED_LOGS_ENABLED) tested in both enabled/disabled states
- ✅ Performance benchmarked: log fetch + parallel parallelism completes within timeout
