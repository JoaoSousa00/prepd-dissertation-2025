# Specification ID: US-1.3

## 1) Header

- **Title:** Connecting LLM enrichment into `GET /incident/details`
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Approved
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`, `docs/contracts/openapi.json`

## 2) Problem Statement

The service has a base incident API, but no complete LLM enrichment capability yet. This specification defines both: (1)
implementing the LLM enrichment integration needed for incident analysis and (2) wiring it into the existing
`GET /incident/details` request flow so fetched incident data is sent with a basic prompt and enrichment is returned in
the same response.

## 3) User Story

> As a support analyst, I want the incident data to be enriched with LLM-generated guidance, so that I can understand
> possible causes and actions faster.

## 4) Scope

### In scope

- Introduce LLM enrichment capability for incident analysis in the application architecture
- Connect LLM enrichment to the existing `GET /incident/details` flow after incident fetching
- Send fetched incident information to the LLM using a basic prompt template
- Return enrichment in the API response: natural-language summary, mitigation suggestions, and related incident
  references when available
- Store the prompt template under infrastructure in a dedicated `prompt/` folder (recommended path:
  `src/infrastructure/prompt/`)

### Out of scope

- Metrics
- Logs analysis
- MCP integration
- Advanced prompt engineering (few-shot, chain-of-thought, multi-prompt orchestration)
- New API endpoints or contract-breaking response shape changes

## 5) Acceptance Criteria

| ID   | Given                                                                   | When                                  | Then                                                                                                                               |
|------|-------------------------------------------------------------------------|---------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | LLM enrichment capability is not yet implemented                        | US-1.3 is implemented                 | The application has domain and infrastructure integration points to call an LLM for incident enrichment                            |
| CA-2 | The API is running and receives a valid `GET /incident/details` request | Incident data is fetched successfully | The same request flow invokes LLM enrichment before building the final response                                                    |
| CA-3 | Fetched incident data exists for an incident                            | The LLM call is executed              | The response includes a natural-language summary and mitigation suggestions for that incident                                      |
| CA-4 | The LLM can identify related incidents from provided context            | The enrichment is returned            | Related incident references are included when available; if unavailable, the response does not fabricate references                |
| CA-5 | A prompt template is required for enrichment                            | The enrichment step runs              | The prompt is loaded from a file inside `src/infrastructure/prompt/` and receives the fetched incident information                 |
| CA-6 | The LLM is unavailable or fails for a request                           | The endpoint processes the request    | The service still returns base incident data through the existing contract, with enrichment fields absent/empty per contract rules |

## 6) Functional Design

- Entry point: existing `GET /incident/details` presentation route.
- Inputs: validated `incidentIds`, fetched incident payload.
- Outputs: contract-aligned response including LLM enrichment fields.
- Happy path:
    - Presentation validates request and calls domain incident retrieval flow.
    - Domain defines and uses an LLM enrichment port/interface for each fetched incident.
    - Infrastructure provides the concrete LLM adapter implementation.
    - Infrastructure LLM adapter loads the basic prompt from `src/infrastructure/prompt/`, injects incident information,
      calls the LLM, and parses outputs.
    - Domain merges summary, mitigation suggestions, and related references into incident output.
- Error path: if LLM fails, preserve base incident data and return without blocking the endpoint response.

## 7) Data and Integration Design

- External dependencies: incident source adapter + LLM provider/gateway adapter.
- Prompt storage decision: keep prompt files in infrastructure (`src/infrastructure/prompt/`) because prompt formatting
  and provider invocation are integration concerns, while domain remains provider-agnostic.
- Cache usage: reuse incident payload already fetched in the request flow; avoid duplicate LLM calls for the same
  incident within one request.
- Identity/permissions assumptions: server-side credentials only.

## 7a) Environment Configuration

The LLM gateway connection to GAIA is fully configurable via environment variables. See `.env_template` for complete
list.

### Required Configuration

| Variable             | Purpose                                          | Notes                                  |
|----------------------|--------------------------------------------------|----------------------------------------|
| `GAIA_LLM_ENDPOINT`  | Base URL for the GAIA LLM gateway                | Example: `https://gaia.api/v1`         |
| `GAIA_MODEL`         | Model name to send to the gateway                | Example: `gpt-4`                       |
| `GAIA_AUTH_ENDPOINT` | OAuth token endpoint for machine-to-machine auth | Example: `https://auth.api/token`      |
| `LLM_API_KEY`        | OAuth client ID from webEAM token JSON           | Used for OAuth client credentials flow |
| `LLM_CLIENT_SECRET`  | OAuth client secret from webEAM token JSON       | Used for OAuth client credentials flow |
| `CA_CERT_PATH`       | Local path to BMW CA bundle                      | Example: `/path/to/ca/bundle.pem`      |
| `CA_CERT_URL`        | Download URL for BMW CA bundle                   | Used for certificate rotation/updates  |

### Optional Configuration

| Variable                       | Default  | Purpose                              | Notes                                   |
|--------------------------------|----------|--------------------------------------|-----------------------------------------|
| `LLM_X_API_KEY`                | (unset)  | Gateway `x-apikey` header            | Falls back to `LLM_API_KEY` when unset  |
| `LLM_GATEWAY_ENABLED`          | `true`   | Enable/disable LLM gateway           | When `false`, uses stub behavior        |
| `LLM_MAX_RETRIES`              | `3`      | Retry count for transient failures   | Applies exponential backoff             |
| `LLM_RETRY_BASE_DELAY_SECONDS` | `1.0`    | Base delay for exponential backoff   | Backoff formula: `base * (2 ^ attempt)` |
| `LLM_DEFAULT_MAX_TOKENS`       | `100000` | Default max tokens for LLM responses | Used when model config leaves it unset  |
| `LLM_REQUEST_TIMEOUT_SECONDS`  | `240.0`  | Timeout for chat completion requests | Empty, `0`, or `none` disables it       |
| `LLM_AUTH_TIMEOUT_SECONDS`     | `30.0`   | Timeout for OAuth token requests     | `0` or `none` disables it               |

## 8) Token Efficiency Design

- Use one basic deterministic prompt template.
- Include only fetched incident fields required for summary, mitigations, and related references.
- Avoid repeated enrichment calls for the same incident in the same request.

## 9) Observability

- Minimal request and enrichment failure logging only.

## 10) Risks and Mitigations

| Risk                                       | Impact                           | Mitigation                                                                                   |
|--------------------------------------------|----------------------------------|----------------------------------------------------------------------------------------------|
| Verbose prompts increase cost              | Higher latency and token use     | Bound the prompt to the incident scope                                                       |
| LLM failure blocks the response            | Endpoint reliability degradation | Keep the base incident response as the fallback                                              |
| Prompt drifts from integration assumptions | Inconsistent enrichment output   | Version prompt file in `src/infrastructure/prompt/` and keep expected output format explicit |

## 11) Test Plan

### Unit tests

- Prompt template loading from `src/infrastructure/prompt/`.
- Prompt rendering with fetched incident data.
- Merge of LLM outputs into incident response model.
- Fallback behavior on LLM errors.

### Integration tests

- `GET /incident/details` returns base incident data plus LLM enrichment on successful LLM calls.
- `GET /incident/details` still returns base incident data when the LLM call fails.

## 12) Implementation Notes

- Planned files/modules:
    - Existing presentation and domain flow for `GET /incident/details`
    - Domain interface/port for LLM enrichment and response mapping
    - Infrastructure LLM adapter implementation and wiring
    - `src/infrastructure/prompt/*` for basic prompt template files
    - Environment configuration updates in `.env_template`
- Prompt recommendation:
    - Keep template files in `src/infrastructure/prompt/` for phase 1
    - If prompt complexity grows later (shared multi-provider strategies), reevaluate extraction into a shared prompt
      module while keeping domain independent

## 13) Definition of Done

- The existing `GET /incident/details` flow invokes LLM enrichment with fetched incident data.
- LLM enrichment integration capability (domain port + infrastructure adapter) is implemented.
- Prompt template is file-based and stored under `src/infrastructure/prompt/`.
- Response includes summary, mitigation suggestions, and related incident references when available.
- Endpoint remains functional and contract-aligned when LLM fails.
- Unit and integration tests cover the new integration behavior.
