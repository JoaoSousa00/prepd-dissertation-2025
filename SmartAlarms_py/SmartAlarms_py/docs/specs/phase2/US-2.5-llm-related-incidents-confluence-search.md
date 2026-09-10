# Specification ID: US-2.5

## 1) Header

- **Title:** Using an LLM to discover related incidents and Confluence service documentation
- **Phase:** Phase 2
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`,
  `docs/specs/phase1/US-1.3-llm-enrichment.md`,
  `docs/specs/phase2/US-2.3-related-incident-context.md`

## 2) Problem Statement

The current incident analysis flow relies on manual or heuristic related-incident identification and does not yet use
Confluence service documentation as first-class context. This makes the incident enrichment path inconsistent and
requires too many separate context-building steps before the final LLM call.

This specification replaces that manual discovery step with a preliminary LLM pass over the full incident payload. The
LLM must return a compact list of relevant related incidents for the incident under analysis, plus a string that can be
used to search service documentation in Confluence. The service then searches only the `CD Location Services` space,
summarizes the returned documentation, and feeds that summarized context into the existing LLM enrichment call.

## 3) User Story

> As a support analyst, I want the service to automatically identify related incidents and service documentation from a
> full incident payload, so that the final incident summary and suggestions are richer without manual context gathering.

## 4) Scope

### In scope

- Send the full non-sensitive incident payload to a simple LLM prompt for context discovery
- Require the discovery prompt to return:
    - relevant related incident identifiers for the specified issue based solely on the incident payload
    - a Confluence search string for service documentation lookup
- Search Confluence only within the `CD Location Services` space
- Retrieve matching documentation pages from Confluence, including subpages of the matched page tree, and summarize
  their contents before the final enrichment call
- Pass the summarized documentation together with the discovered related incidents into the already existing LLM
  enrichment call
- Return `relatedPages` at the incident level and per suggestion, using full Confluence URLs
- Extend the final enrichment prompt to include the summarized Confluence documentation
- Extend the final response schema with `relatedPages` at the incident level and per suggestion

### Out of scope

- Manual curator-driven related-incident selection
- Cross-space Confluence searching
- Semantic/vector search over Confluence content
- Writing back to Confluence or incident records

## 5) Acceptance Criteria

| ID   | Given                                                                                    | When                            | Then                                                                                                                  |
|------|------------------------------------------------------------------------------------------|---------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| CA-1 | A valid incident analysis request is received                                            | Context discovery runs          | The full non-sensitive incident payload is sent to a simple LLM prompt and a structured result is returned            |
| CA-2 | The discovery LLM returns related incident identifiers and a documentation search string | The result is parsed            | The related incidents are normalized, deduplicated, and the search string is preserved for documentation lookup       |
| CA-3 | Documentation lookup runs                                                                | The Confluence request is built | The request is restricted to the `CD Location Services` space only                                                    |
| CA-4 | Confluence returns one or more matching pages or page trees                              | Documentation preparation runs  | The parent page and its subpages are summarized into bounded documentation context before the final enrichment call   |
| CA-5 | The existing enrichment call runs                                                        | The final payload is built      | The payload includes the main incident, the discovered related incidents, and the summarized Confluence context       |
| CA-6 | Context discovery or Confluence lookup fails                                             | The request continues           | The service still returns the incident analysis using any available context and does not fail the whole request       |
| CA-7 | Discovery output is empty or partially malformed                                         | Parsing runs                    | Invalid identifiers are ignored and the service degrades gracefully without inventing related incidents               |
| CA-8 | Documentation pages are available for the incident                                       | The response is built           | The incident response includes `relatedPages`, and each suggestion includes its own list of full Confluence page URLs |

## 6) Functional Design

- Entry point: existing `GET /incident/details` analysis flow.
- Inputs:
    - validated incident identifier (s)
    - full non-sensitive incident payload from the incident source adapter
- Outputs:
    - discovered related incident identifiers
    - Confluence documentation search string
    - summarized documentation context for the final enrichment call
    - incident-level `relatedPages` with page titles and full URLs
    - per-suggestion `relatedPages` with page titles and full URLs
- Happy path:
    1. Fetch the incident payload with the existing ITSM adapter.
    2. Send the full non-sensitive incident context to a small discovery prompt.
    3. Parse the structured LLM output into related incident identifiers and one documentation search string.
    4. In parallel, fetch related incidents, same-title incidents, and fallback incidents when needed.
    5. Search Confluence only in `CD Location Services`, then fetch the matched page tree including subpages.
    6. Summarize the page tree into short, bounded context and keep the page URLs for the response.
    7. Pass the main incident, discovered related incidents, and summarized Confluence documentation to the existing
       enrichment prompt.
- Error path:
    - If discovery fails, continue with the incident payload and any other available context.
    - If Confluence returns no matches or fails, continue without documentation context.

### Response shape

- Incident-level response must include:
    - `relatedPages`: list of page objects with at least `title` and `url`
- Each suggestion must include:
    - `relatedPages`: list of page objects with at least `title` and `url`
- `url` must be the full, user-openable Confluence URL, not a relative path or API URL.
- The response must keep existing summary and suggestion fields intact.

## 7) Data and Integration Design

- External dependencies: ITSM incident adapter, LLM gateway adapter, and Confluence adapter.
- LLM discovery contract:
    - simple prompt
    - structured output with incident identifiers and one documentation search string
    - no final summary generation in this step
- Confluence access:
    - use the ATC-compatible Confluence REST API available for the deployment
    - constrain all search and fetch operations to the `CD Location Services` space
    - prefer the deployment-supported content/search endpoint pair that can return page metadata, page body, and child
      page results
- Context handling:
    - deduplicate related incident identifiers before downstream use
    - keep documentation summaries short enough to fit the existing final enrichment prompt
    - preserve the page metadata needed to build the incident-level and suggestion-level `relatedPages` lists
- Identity/permissions assumptions:
    - server-side credentials only
    - no user-managed Confluence login state in the request path

## 7a) Environment Configuration

| Variable                     | Default                               | Purpose                          | Notes                        |
|------------------------------|---------------------------------------|----------------------------------|------------------------------|
| `CONFLUENCE_BASE_URL`        | `https://atc.bmwgroup.net/confluence` | Base URL for Confluence requests | Deployment-specific base URL |
| `CONFLUENCE_TIMEOUT_SECONDS` | `30`                                  | Timeout for Confluence requests  | Must stay bounded            |

The `CD Location Services` space restriction is fixed by the feature and does not need to be user-configurable.

## 8) Token Efficiency Design

- Use one compact discovery prompt instead of multiple manual heuristics.
- Restrict Confluence searches to one space and a small result set, then summarize the parent page with its children.
- Summarize page content before the existing enrichment prompt to avoid sending raw documentation text twice.
- Keep the discovery output structured so the second LLM call receives only the useful context.

## 9) Observability

- Record discovery LLM duration and Confluence search duration.
- Track discovered related incident count and summarized documentation count.
- Trace the pipeline stages:
    - incident fetch
    - discovery prompt
    - Confluence search
    - Confluence page tree fetch
    - documentation summary
    - final enrichment call

## 10) Risks and Mitigations

| Risk                                                | Impact                          | Mitigation                                                  |
|-----------------------------------------------------|---------------------------------|-------------------------------------------------------------|
| Discovery prompt returns noisy incident identifiers | Weak related-incident context   | Normalize, deduplicate, and validate identifiers before use |
| Confluence search string is too broad               | Irrelevant documentation        | Limit result count and summarize only the top matches       |
| Searches escape the intended space                  | Wrong project context           | Hard-restrict the adapter to `CD Location Services`         |
| Raw documentation is too large                      | Prompt overflow and higher cost | Summarize before the final enrichment call                  |

## 11) Test Plan

### Unit tests

- Discovery prompt output parsing and identifier normalization
- Confluence query builder space restriction
- Documentation summarization bounds
- Context merge into the final enrichment payload
- Graceful degradation when discovery or Confluence lookup fails

### Integration tests

- End-to-end request with discovery output and summarized Confluence context
- Request where discovery succeeds but Confluence returns no matches or no subpages
- Request where discovery fails and the service still returns the available incident analysis

## 12) Implementation Notes

- Planned files/modules:
    - `src/infrastructure/prompt/` for the discovery prompt
    - `src/infrastructure/adapters/confluence/` for Confluence search and page retrieval
    - existing incident analysis orchestration for the two-step LLM flow
    - `.env_template` for Confluence base URL and timeout
- Keep the discovery step separate from the final enrichment step so the final LLM call remains the current summary and
  suggestions generator.

## 13) Definition of Done

- The full incident payload is sent to a discovery LLM prompt.
- The discovery output returns related incidents and a Confluence search string.
- Documentation is searched only in `CD Location Services`.
- Returned documentation is summarized before the existing enrichment call.
- Final summary/suggestions use the richer combined context.
- Fallback behavior remains graceful when either discovery or Confluence lookup fails.
