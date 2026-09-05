# Specification ID: US-2.3

## 1) Header

- **Title:** Integrating related incident context for LLM enrichment
- **Phase:** Phase 2
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`, `docs/contracts/openapi.json`,
  `docs/specs/phase1/US-1.2-base-incident-client.md`, `docs/specs/phase1/US-1.3-llm-enrichment.md`

## 2) Problem Statement

US-1.2 fetches only a small base incident model and US-1.3 wires that model into LLM enrichment. That leaves the LLM
with too little operational context and no structured access to related historical incidents that may already contain
resolution notes. This specification expands the incident context available in domain, discovers related incidents from
the main record, fetches same-title historical incidents, and prepares a deduplicated context package for the existing
LLM enrichment flow.

## 3) User Story

> As a support analyst, I want the service to enrich an incident with related historical incident context, so that the
> LLM can generate more grounded summaries and mitigation suggestions.

## 4) Scope

### In scope

- Expand the main incident domain model so all non-sensitive data returned by ITSM for the main incident is available to
  downstream domain orchestration and LLM payload preparation
- Preserve the exclusions already defined in US-1.2 (`caller_id`, `assigned_to`, `resolved_by`, `attachments`)
- Discover candidate related incident numbers from these main-incident fields:
    - `parent_incident`
    - `description`
    - `close_notes`
    - `comments`
    - `work_notes`
    - `hold_reason`
- Normalize and deduplicate discovered related incident numbers before any downstream fetch
- Fetch incidents whose `short_description` exactly matches the main incident `short_description`, using a configurable
  fetch limit, then sort by `resolved_at` and keep only a configurable most-recent subset
- Fetch full related-incident details for the discovered incident numbers in parallel
- Map the same related-incident detail subset for both discovery paths:
    - incident number
    - state
    - description
    - close notes
    - closed at
    - comments
    - work notes
    - hold reason
    - close code
- Prepare a domain-level LLM input context that includes:
    - expanded main-incident context
    - deduplicated related incidents
    - provenance of how each related incident was found
    - recency information for same-title historical incidents
- Rework the prompt used by the LLM enrichment flow so it explicitly understands that it will receive:
    - the main incident
    - incidents explicitly referenced by the main incident
    - incidents with the same `short_description`
- Define summary-writing rules so the summary stays formal, simple, and human-readable
- Define suggestion-writing rules so each suggestion includes:
    - an investigation action
    - a mitigation action
    - a suggested resolution note
    - the incident source (s) the suggestion came from
- Allow the LLM to recommend redirecting the incident to another team when the related historical context supports that
  conclusion
- Reuse the existing LLM enrichment call path from US-1.3 with the richer context package

### Out of scope

- New public API endpoints
- Client-controlled per-request source toggles
- Semantic similarity search beyond exact `short_description` matching
- Non-incident external sources such as logs, Confluence, or MCP
- Changes to the LLM provider abstraction beyond what is required to pass richer incident context

## 5) Acceptance Criteria

| ID    | Given                                                                                                                                         | When                                         | Then                                                                                                                                                                                                                |
|-------|-----------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CA-1  | A main incident is fetched from ITSM                                                                                                          | The incident is mapped into the domain       | All non-sensitive main-incident fields are preserved in a normalized domain context and the exclusions from US-1.2 remain excluded                                                                                  |
| CA-2  | The main incident contains incident references in `parent_incident`, `description`, `close_notes`, `comments`, `work_notes`, or `hold_reason` | Related incident discovery runs              | Incident numbers are extracted, normalized, the main incident number is excluded, and duplicates are removed before fetching                                                                                        |
| CA-3  | The main incident has a non-empty `short_description`                                                                                         | Same-title history lookup runs               | The service queries ITSM for incidents with the same `short_description` using the configured fetch limit, excludes the main incident, sorts by `resolved_at` descending, and keeps only the configured recent-limit subset |
| CA-4  | One or more deduplicated related incident numbers were discovered from the main incident                                                      | Related incident details are fetched         | The service retrieves their detail records in parallel and maps the related-incident field subset defined by this specification                                                                                     |
| CA-5  | The same incident is found by multiple discovery mechanisms                                                                                   | Domain correlation output is built           | That incident appears only once in the deduplicated related-incident context and retains provenance indicating all discovery sources that found it                                                                  |
| CA-6  | Related incident source payloads contain `comments` or `work_notes` and the corresponding server-side inclusion flag is disabled              | Related incidents are mapped for LLM context | The disabled fields are omitted from the related-incident LLM context while the rest of the related-incident record remains available                                                                               |
| CA-7  | Related incident records are missing, unavailable, or partially failing                                                                       | The request flow continues                   | The service preserves the main incident context, keeps successfully fetched related incidents, and does not fail the whole incident analysis request solely because optional related context failed                 |
| CA-8  | The existing LLM enrichment flow runs after incident and related-context preparation                                                          | The LLM request payload is built             | The payload includes the expanded main incident context plus deduplicated related incidents without reintroducing any fields excluded by US-1.2                                                                     |
| CA-9  | The LLM prompt is rendered for incident enrichment                                                                                            | The prompt is built from domain context      | The prompt explicitly distinguishes the main incident, explicitly referenced related incidents, and same-title incidents so the model knows how each context block was obtained                                     |
| CA-10 | The LLM generates a user-facing summary                                                                                                       | The response is built                        | The summary is formal, simple, and human-readable, and it excludes operational metadata that is not useful for the summary itself, including incident state, priority, impact, urgency, and assignment team         |
| CA-11 | The LLM generates mitigation guidance                                                                                                         | Suggestions are returned                     | Each suggestion includes, in order, an investigation step, a mitigation step, and a suggested resolution note, and each suggestion cites the source incident number or numbers that support it                      |
| CA-12 | Same-title historical incidents contain recent closed tickets with meaningful `close_notes`                                                   | The LLM generates suggestions                | The prompt instructs the model to prioritize the latest relevant closed historical tickets when deriving investigation and mitigation guidance                                                                      |
| CA-13 | Historical incident context indicates the issue is commonly redirected to another team                                                        | The LLM generates suggestions                | The model may include reassignment or redirection to another team as a suggestion, but only when that recommendation is grounded in the provided incident context and still cites the supporting incident source(s) |

## 6) Functional Design

- Entry point: existing `GET /incident/details` request flow defined by US-1.1 and extended by US-1.3.
- Inputs:
    - validated incident ID (s)
    - ITSM main incident payload
    - ITSM related-incident payloads from discovery and same-title lookup
- Outputs:
    - internal domain context for LLM enrichment
    - existing response flow from US-1.3, now produced from richer context
- Happy path:
    - Fetch the main incident.
    - Map all non-sensitive main-incident fields into a normalized domain context object.
    - Discover candidate related incident numbers from the configured structured and free-text fields.
    - Deduplicate candidate incident numbers using normalized incident-number keys.
    - Query ITSM for same-title incidents using the main incident `short_description` and the configured fetch limit.
    - Exclude the main incident from same-title results when present.
    - Sort same-title incidents by `resolved_at` in descending order and keep only the configured most-recent subset.
    - Fetch discovered related incidents in parallel.
    - Map both discovered-related and same-title incidents into a common related-incident domain model.
    - Merge both discovery streams into a deduplicated related-incident collection, preserving provenance such as
      `referenced_in_parent_incident`, `referenced_in_description`, and `same_short_description`.
    - Build the LLM input context from:
        - expanded main incident context
        - deduplicated related incidents
        - discovery provenance metadata
        - recency metadata for same-title historical incidents such as `resolved_at`
    - Render a prompt that clearly separates:
        - current incident context
        - explicitly referenced related incidents
        - same-title historical incidents
    - Instruct the LLM that same-title historical incidents are candidate precedent, especially when they are recently
      closed and contain meaningful resolution notes.
    - Instruct the LLM to produce:
        - one concise formal summary for the current incident
        - grounded suggestions that always include investigation, mitigation, and a proposed resolution note
        - source attribution for every suggestion using incident number references
        - reassignment guidance only when the provided historical incidents support redirecting to another team
    - Pass the prepared context to the existing LLM enrichment port from US-1.3.
- Error path:
    - If same-title lookup fails, continue with main incident plus any successfully fetched referenced incidents.
    - If one related incident fetch fails, keep the remaining related incidents and continue.
    - If no related incidents are found, continue with main incident context only.

### LLM prompt and response design

- Prompt responsibilities:
    - Tell the model it is analyzing one active incident with supporting historical context.
    - Label context sections so the model can distinguish:
        - the main incident
        - related incidents explicitly referenced in the main incident
        - same-title incidents retrieved by exact `short_description` match
    - Make clear that same-title incidents are useful mainly as historical precedent, especially the latest closed
      tickets with actionable `close_notes`.
    - Tell the model to ground every suggestion only in the supplied incident data and never invent incident references.
- Summary rules:
    - The summary must be simple, formal, and human-readable.
    - The summary must focus on what happened, what context is relevant, and what is likely useful for the support or
      development team to understand quickly.
    - The summary must not surface basic ticket administration data that is already obvious or not useful to the user,
      including:
        - state (`open`, `closed`, `cancelled`, etc.)
        - priority
        - impact
        - urgency
        - assignment team
- Suggestion rules:
    - Each suggestion must be grounded in one or more related incidents or same-title incidents when such evidence
      exists.
    - Each suggestion must explicitly cite its source incident number or numbers.
    - Each suggestion must be structured in this order:
        - investigation suggestion
        - mitigation suggestion
        - suggested resolution note text for the developer to adapt when solving the incident
    - If historical incidents show the issue is commonly transferred or redirected, the LLM may suggest reassignment to
      another team, but it must cite the supporting incident number or numbers.
- Output-shaping rule:
    - The software engineer must ensure the prompt and response parser preserve enough structure to keep source
      attribution attached to each suggestion.

## 7) Data and Integration Design

- External dependencies: ITSM incident adapter and existing LLM gateway adapter from US-1.3.
- Domain additions:
    - `MainIncidentContext` (or equivalent) capable of carrying all non-sensitive fields from the fetched main incident
    - `RelatedIncidentContext` for the field subset reused across discovered and same-title incidents
    - provenance metadata showing which discovery mechanisms identified each related incident
    - LLM prompt input model that distinguishes current incident context from historical related context
- Discovery rules:
    - Treat `parent_incident` as a structured reference when it contains an incident identifier.
    - Treat `description`, `close_notes`, `comments`, `work_notes`, and `hold_reason` as free-text sources from which
      incident identifiers are extracted using normalized incident-number matching.
    - Normalize incident numbers to a canonical uppercase representation before deduplication.
- Mapping rules:
    - Main incident mapping expands beyond the minimal US-1.2 base model, but still must not expose `caller_id`,
      `assigned_to`, `resolved_by`, or `attachments` to domain or LLM payloads.
    - Related-incident mapping is intentionally narrower than the main incident mapping and is limited to the fields
      listed in scope.
- Merge rules:
    - Deduplicate by incident number after combining:
        - explicitly referenced related incidents
        - same-title incidents
    - Preserve all discovery sources for a single incident record instead of keeping duplicates.
- Prompt-context rules:
    - Same-title incidents should carry enough metadata for the prompt builder to favor the latest relevant closed
      tickets, especially those with meaningful `close_notes`.
    - Related incident provenance must remain available to the prompt builder so suggestion citations can be traced back
      to supporting incidents.
- Request construction for same-title lookup:
    - Method: `GET`
    - Query filter: exact `short_description=<main short_description>`
    - Fetch limit: `RELATED_INCIDENTS_MAX_SAME_TITLE`
    - Post-fetch recency filter: sort by `resolved_at` descending and keep top `RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT`
    - Authentication and host headers remain infrastructure concerns

## 7a) Environment Configuration

The related-incident enrichment behavior is controlled server-side to stay aligned with the Phase 1 source policy in
`docs/requirements.md`.

### Required Configuration

| Variable                                  | Purpose                                                                 | Notes                                             |
|-------------------------------------------|-------------------------------------------------------------------------|---------------------------------------------------|
| `RELATED_INCIDENTS_MAX_SAME_TITLE`        | Maximum number of incidents fetched from same-title ITSM lookup         | Must be a positive integer (recommended: `100`)   |
| `RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT` | Maximum number of recent same-title incidents kept after recency sorting | Must be a positive integer (recommended: `10`) and should be <= fetch limit |

### Optional Configuration

These controls decide whether related-incident `comments` and `work_notes` are included in the LLM input payload for
historical context. They are server-side configuration flags only and must not be controlled per request.

| Variable                               | Default | Purpose                                                    | Notes                                    |
|----------------------------------------|---------|------------------------------------------------------------|------------------------------------------|
| `RELATED_INCIDENTS_INCLUDE_COMMENTS`   | `true`  | Include related-incident `comments` in the LLM input context | Server-side only; not request-controlled |
| `RELATED_INCIDENTS_INCLUDE_WORK_NOTES` | `true`  | Include related-incident `work_notes` in the LLM input context | Server-side only; not request-controlled |

## 8) Token Efficiency Design

- Deduplicate incident numbers before fetching related-incident details.
- Deduplicate related incidents again after merging referenced and same-title results so the same incident is never sent
  twice to the LLM.
- Keep related-incident mapping intentionally narrower than the main incident mapping.
- Allow server-side exclusion of related-incident `comments` and `work_notes` to reduce prompt size when needed.
- Reuse the already fetched main incident payload; do not refetch it for LLM preparation.
- Exclude summary-irrelevant administrative fields from prompt instructions for the summary objective even if they
  remain available elsewhere in the main incident context.
- Favor recent closed same-title incidents with actionable `close_notes` by sorting with `resolved_at` and applying a
  strict recent-limit subset before prompt rendering.

## 9) Observability

- Add tracing spans around:
    - main incident context mapping
    - related incident discovery
    - same-title incident lookup
    - parallel related-incident detail fetch
    - LLM context preparation
- Record lightweight internal attributes when observability is enabled:
    - main incident number
    - discovered related incident count (excluding the main incident)
    - same-title fetched count (`total_incidents_title`) before recency filtering and excluding the main incident
    - same-title recent-kept count
    - deduplicated related incident count
    - fallback fetched count (`total_incidents_fallback`) before recency filtering and excluding the main incident
    - flags indicating whether comments/work notes were included for related incidents

## 10) Risks and Mitigations

| Risk                                                                   | Impact                                         | Mitigation                                                                                                |
|------------------------------------------------------------------------|------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| Free-text fields contain noisy or malformed incident references        | Unnecessary fetches or bad correlation context | Normalize identifiers strictly, exclude the main incident number, and deduplicate before fetching         |
| Same-title searches return too many historical incidents               | Increased latency and prompt size              | Bound fetches with `RELATED_INCIDENTS_MAX_SAME_TITLE`, then recency-truncate with `RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT` |
| Related incident comments and work notes add too much noise            | Higher token cost and lower answer quality     | Control inclusion with server-side configuration and keep them optional in the context builder            |
| Enriched context accidentally reintroduces excluded fields from US-1.2 | Security and data-minimization regression      | Keep US-1.2 exclusions explicit at every mapping boundary for both main and related incidents             |
| Sequential related-incident fetching increases latency                 | Slower incident analysis requests              | Fetch discovered related incidents in parallel                                                            |
| Prompt instructions are too vague about source attribution             | Suggestions become hard to trust or audit      | Require every suggestion to cite supporting incident numbers                                              |
| Summary includes noisy administrative ticket fields                    | Summary becomes less useful to humans          | Explicitly exclude state, priority, impact, urgency, and assignment team from summary guidance            |
| Old historical incidents outweigh newer precedent                      | Suggestions become outdated                    | Instruct prompt builder and model to favor recent closed same-title incidents with meaningful close notes |

## 11) Test Plan

### Unit tests

- Main incident mapping preserves non-sensitive fields and excludes the US-1.2 restricted fields.
- Incident-number extraction from each discovery field (`parent_incident`, `description`, `close_notes`, `comments`,
  `work_notes`, `hold_reason`).
- Deduplication and canonical normalization of incident numbers.
- Same-title lookup request construction with configured limit.
- Same-title recency filtering sorts by `resolved_at` descending and keeps the configured recent-limit subset.
- Related-incident mapping for the required field subset.
- Merge behavior that keeps one incident record with multiple provenance sources.
- Related-incident context building when comments or work notes are disabled by configuration.
- Prompt rendering that clearly separates main incident, referenced related incidents, and same-title incidents.
- Prompt instructions that exclude state, priority, impact, urgency, and assignment team from the summary objective.
- Prompt rendering and parsing that preserve source attribution per suggestion.
- Suggestion output parsing that enforces investigation-first, mitigation-second, resolution-note-last structure.

### Integration tests

- `GET /incident/details` uses expanded main-incident context plus related incidents in the LLM request flow.
- Parallel related-incident detail fetching tolerates partial failures without breaking the main request.
- Same-title incidents and explicitly referenced incidents are merged without duplicate LLM context entries.
- LLM enrichment uses recent closed same-title incidents with `close_notes` as supporting precedent for suggestions.
- Response shaping preserves cited source incidents for every suggestion.

## 12) Implementation Notes

- Planned files/modules:
    - `src/domain/incident/*` for expanded incident context and correlation orchestration
    - `src/domain/correlation/*` for discovery, deduplication, and merge rules if separated by current architecture
    - `src/infrastructure/adapters/itsm/*` for same-title lookup and related-incident detail retrieval
    - `src/infrastructure/prompt/*` or existing LLM context-building path from US-1.3 for richer payload rendering and
      stricter prompt instructions
    - `.env_template` for new related-incident configuration
- Compatibility note:
    - This specification extends the internal domain and LLM payload preparation flow without requiring a
      contract-breaking API change.
- Prompt-update note:
    - The prompt file introduced by US-1.3 must be updated so it explicitly understands the richer context categories
      and the mandatory output structure for summary and suggestions.

## 13) Definition of Done

- The specification defines how the main incident context is expanded without violating US-1.2 exclusions.
- The specification defines how related incidents are discovered, fetched, deduplicated, and merged.
- Same-title lookup is explicitly bounded by server-side configuration and recency-filtered before prompt usage.
- The specification defines how the richer incident context is prepared for the existing LLM enrichment flow.
- The specification defines the prompt expectations and output structure clearly enough for implementation without
  adding new product assumptions.
- Test expectations cover extraction, deduplication, mapping, merge, prompt rendering, and graceful-degradation
  behavior.
