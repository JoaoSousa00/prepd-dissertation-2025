# Specification ID: US-2.4

## 1) Header

- **Title:** Fallback to recent team incidents when same-title lookup returns no results
- **Phase:** Phase 2
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`,
  `docs/specs/phase2/US-2.3-related-incident-context.md`

## 2) Problem Statement

US-2.3 enriches LLM context with incidents that share the same `short_description`, but this path can return zero
results. When that happens, the LLM loses historical context and suggestions become weaker, especially for fresh
incidents where title reuse is low but team-local operational issues are still relevant.

This specification adds a deterministic fallback: when same-title lookup returns no incidents, fetch the latest
incidents from the same assignment group, sort by `resolved_at`, and keep only the most recent subset for contextual
guidance. The prompt must explicitly distinguish this fallback context from related incidents to avoid false correlation
claims.

## 3) User Story

> As a support analyst, I want the system to use recent incidents from my team when same-title history is empty, so that
> the LLM can still provide useful context-aware suggestions for ongoing issues.

## 4) Scope

### In scope

- Trigger fallback only when same-title lookup returns zero incidents (empty result, not error).
- Call ITSM incident API with assignment-group filter:
    - `GET /nowplatform/v1/incident?query=assignment_group=<group>&limit=<fetch_limit>`
- Make both limits configurable:
    - fetch limit: number of incidents requested from ITSM
    - final recent limit: number kept after sorting by `resolved_at` (default target remains 10)
- Sort fetched fallback incidents by `resolved_at` descending and keep only the configured final recent limit.
- Exclude the main incident from fallback context if it appears in the fetched list.
- Reuse the related-incident mapping model from US-2.3 where fields overlap.
- Introduce prompt branching:
    - existing prompt branch when same-title incidents exist
    - fallback prompt branch when same-title incidents are empty and recent team incidents are used
- In fallback prompt branch, explicitly state these incidents are not proven related incidents, only recent team
  context.
- Preserve graceful degradation: if fallback fetch fails, continue with main incident plus any other available context.

### Out of scope

- Replacing the existing same-title strategy.
- Semantic similarity fallback.
- New API endpoints or client-controlled fallback behavior.
- Changing authentication/header ownership (stays in infrastructure adapter).

## 5) Acceptance Criteria

| ID   | Given                                                                   | When                            | Then                                                                                                                     |
|------|-------------------------------------------------------------------------|---------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| CA-1 | Same-title lookup completed successfully with zero incidents            | Context orchestration continues | Fallback lookup by assignment group is executed                                                                          |
| CA-2 | Fallback lookup is executed                                             | ITSM request is built           | Query uses assignment-group filter and configurable fetch limit                                                          |
| CA-3 | Fallback returns incidents with mixed `resolved_at` values              | Fallback post-processing runs   | Incidents are sorted by `resolved_at` descending and truncated to configurable final recent limit                        |
| CA-4 | Fallback list contains the main incident number                         | Fallback context is finalized   | Main incident is excluded from fallback context                                                                          |
| CA-5 | Same-title lookup returns one or more incidents                         | Prompt payload is prepared      | Existing same-title prompt branch is used and fallback is not used                                                       |
| CA-6 | Same-title lookup returns zero incidents and fallback returns incidents | Prompt payload is prepared      | Fallback prompt branch is used and clearly labels incidents as recent team context, not related incidents                |
| CA-7 | Fallback lookup fails or returns no usable incidents                    | Request flow continues          | Service still returns analysis using main incident and any other available context without failing the full request      |
| CA-8 | Configuration variables are missing or invalid                          | Service starts or request runs  | Safe defaults are applied where defined, and invalid values surface clear validation errors consistent with config rules |

## 6) Functional Design

- Entry point: existing `GET /incident/details` flow.
- Decision flow:
    - run same-title lookup from US-2.3;
    - if same-title count > 0, keep current behavior;
    - if same-title count == 0, run assignment-group fallback lookup.
- Fallback fetch flow:
    - build assignment-group query from main incident assignment group;
    - request up to configured fetch limit from ITSM;
    - remove main incident from result set;
    - sort remaining incidents by `resolved_at` descending;
    - keep top N where N is configured final recent limit.
- Prompt flow:
    - Branch A (existing): same-title incidents treated as historical same-title evidence.
    - Branch B (new fallback): recent team incidents treated as contextual signals only; prompt must avoid language that
      implies direct relation to the current incident.
- Error path:
    - same-title failure already follows US-2.3 graceful degradation;
    - fallback failure must not fail the full analysis request.

## 7) Data and Integration Design

- External dependency: ITSM adapter already used by US-2.3.
- Fallback endpoint contract (infrastructure-owned):
    - method: `GET`
    - path: `/nowplatform/v1/incident`
    - query: `assignment_group=<group>` and `limit=<fallback_fetch_limit>`
    - headers remain adapter concerns (e.g., `Accept`, `Authorization`, `Host`, `x-apikey`)
- Sorting field: `resolved_at` (descending recency).
- Domain modeling:
    - keep provenance metadata to mark source as `recent_assignment_group_fallback`;
    - keep same-title provenance untouched when fallback is not used.

## 7a) Environment Configuration

| Variable                                  | Default | Purpose                                                      | Notes                                                 |
|-------------------------------------------|---------|--------------------------------------------------------------|-------------------------------------------------------|
| `RELATED_INCIDENTS_FALLBACK_FETCH_LIMIT`  | `100`   | Max incidents requested from assignment-group fallback query | Must be positive integer                              |
| `RELATED_INCIDENTS_FALLBACK_RECENT_LIMIT` | `10`    | Max incidents kept after `resolved_at` sorting               | Must be positive integer and should be <= fetch limit |

## 8) Token Efficiency Design

- Fallback activates only when same-title returns zero incidents, avoiding duplicate historical sources.
- Keep two-stage limiting:
    - larger fetch limit for better recency coverage
    - tighter final recent limit for prompt size control
- Reuse related-incident mapping subset and existing prompt pipeline to avoid extra payload expansion paths.

## 9) Observability

- Emit counters/attributes for:
    - `fallback_triggered` (boolean)
    - `total_incidents_fallback` before recency filtering and excluding the main incident
    - `fallback_kept_incidents`
- Trace stages:
    - fallback ITSM call
    - `resolved_at` sort and truncation
    - prompt-branch selection

## 10) Risks and Mitigations

| Risk                                                        | Impact                         | Mitigation                                                                             |
|-------------------------------------------------------------|--------------------------------|----------------------------------------------------------------------------------------|
| Team-recent incidents may be unrelated noise                | Lower suggestion precision     | Prompt branch explicitly labels fallback incidents as contextual, not related evidence |
| High fallback fetch limit increases latency                 | Slower response                | Bound by configurable fetch limit and keep strict final recent limit                   |
| Missing/invalid `resolved_at` values reduce recency quality | Poor ranking quality           | Define stable sort behavior with invalid/missing timestamps placed last                |
| Misconfiguration (`recent_limit` > `fetch_limit`)           | Unexpected truncation behavior | Validate configuration at startup and enforce coherent constraints                     |

## 11) Test Plan

### Unit tests

- Fallback trigger logic only runs when same-title count is zero.
- Fallback request builder uses assignment group and configured fetch limit.
- Sorting/truncation logic orders by `resolved_at` descending and keeps configured final recent limit.
- Main incident exclusion from fallback list.
- Prompt branch selector chooses existing prompt vs fallback prompt correctly.
- Fallback prompt text includes explicit disclaimer that fallback incidents are not proven related incidents.
- Config parser validates limits and applies defaults.

### Integration tests

- End-to-end flow where same-title returns zero and fallback context is used in LLM payload.
- End-to-end flow where same-title returns incidents and fallback is not called.
- Partial-degradation flow where fallback fails and analysis still returns with available context.

## 12) Implementation Notes

- Planned files/modules:
    - `src/domain/correlation/*` for fallback decision and ranking logic
    - `src/infrastructure/adapters/itsm/*` for assignment-group fallback query
    - existing prompt builder module from US-1.3/US-2.3 for prompt branch support
    - `.env_template` for new fallback limit variables
- Keep dependency direction unchanged:
    - domain defines fallback selection/ranking behavior
    - infrastructure implements ITSM query details
- Keep naming explicit in context models so downstream logic can distinguish:
    - `same_short_description`
    - `recent_assignment_group_fallback`

## 13) Definition of Done

- Fallback behavior is fully specified for zero-result same-title scenarios.
- Both limits (fetch and final recent subset) are specified as configurable with defaults.
- Prompt branching behavior is specified and prevents false "related incident" claims in fallback mode.
- Graceful degradation and observability expectations are explicitly defined.
- Test expectations cover trigger logic, ranking/truncation, prompt branching, and degraded paths.
