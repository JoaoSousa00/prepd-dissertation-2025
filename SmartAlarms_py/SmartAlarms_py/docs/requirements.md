# SmartAlarms Requirements

**Status:** Draft v1  
**Last updated:** 2026-09-09  
**Scope:** Academic incident analysis service for incident analysis and mitigation support

## 1) Product Goal

SmartAlarms provides incident analysis and mitigation support in an academic context, helping teams understand incidents
faster by retrieving related history, using that context in an LLM, and generating prioritized mitigation suggestions.

## 2) In Scope

- Receive incidents for analysis through the incident service.
- Fetch relevant incident data, including description, affected service, severity, and other available fields.
- Search incident history for related incidents.
- Use related incidents as context for the LLM.
- Use a preliminary LLM pass over the full incident payload to discover related incidents and a Confluence search term.
- Search service documentation in Confluence only within the `CD Location Services` space and summarize matching pages
  and subpages before the final enrichment call.
- Return Confluence page references at the incident level and inside each suggestion so users can open the source pages
  directly.
- Generate a natural-language incident summary.
- Generate and prioritize mitigation suggestions.
- Expose the information used to support the generated suggestions.

## 3) Out of Scope (Current)

- Automatic remediation execution.
- Enterprise SLA/SLO commitments.
- Mandatory use of every external source on every request.
- Full semantic search / vector-based retrieval as a requirement.

## 4) Runtime and Hosting Assumptions

- The service must run locally inside a Docker image for development and evaluation.
- Environment-specific configuration must be provided through externalized settings, not hardcoded values.

## 5) Functional Requirements

- **FR-01:** The system must allow an incident to be received for analysis through the incident service.
- **FR-02:** The system must retrieve the relevant incident data, including the description, affected service, severity,
  and other available fields.
- **FR-03:** The system must search the history for incidents related to the received incident.
- **FR-04:** The system must use the related incidents as context for the analysis performed by the \gls{LLM}.
- **FR-05:** The system must generate a natural-language summary of the incident.
- **FR-06:** The system must generate mitigation suggestions based on the available information and the related
  incidents.
- **FR-07:** The system must order the mitigation suggestions according to their relevance.
- **FR-08:** The system must present the information used to support the generated suggestions, allowing the related
  incidents to be consulted.
- **FR-09:** The system must allow the most suitable team to be identified for handling the incident, when that
  information is part of the solution's objective.
- **FR-10:** The system must allow the use, or not, of incident comments and analysis notes to be configured.
- **FR-11:** The system must allow the model used by the \gls{LLM} to be configured.
- **FR-12:** The system must use a preliminary LLM prompt to discover relevant related incidents and a Confluence
  documentation search string from the incident context.
- **FR-13:** The system must search Confluence documentation only within the `CD Location Services` space and summarize
  the returned page content, including subpages, before passing it to the final enrichment LLM call.
- **FR-14:** The system must return `relatedPages` for the incident and for each suggestion, with full Confluence URLs.

## 6) Pipeline Constraints (Efficiency)

- Source filtering and normalization happen before expensive LLM calls.
- Prompt construction must be incident-focused and bounded by configurable size limits.
- The system should prioritize reuse of repeated incident context where available.

## 7) Non-Functional Requirements

- **NFR-01:** The system must be able to continue processing requests as long as the required external services are
  available.
- **NFR-02:** The system must not expose confidential incident information to users or services that are not authorized
  to access it.
- **NFR-03:** The system must be organized so that external services can be added, replaced, or removed without
  impacting the rest of the service.
- **NFR-04:** The system must limit the amount of information sent to the \gls{LLM} in order to keep the cost of each
  analysis within acceptable values.
- **NFR-05:** The system must allow the incidents used as context for each analysis to be identified.
- **NFR-06:** The generated responses must provide a quality level suitable for supporting incident analysis and
  resolution.

## 8) Observability & Cost Requirements

- Track `tokens_in`, `tokens_out`, model name, and latency per request.
- Track which historical incidents were used as context.
- Track which Confluence pages and subpages were used as documentation context.
- Track the page URLs exposed in incident and suggestion `relatedPages`.
- Attribute requests by `user` (when available), `workflow`, and `credential_source`.

## 9) Success Metrics

- Reduced mean time to understand incidents in evaluation scenarios.
- Higher relevance of mitigation suggestions in human assessment.
- Clear traceability of the incidents used as context.
- Stable response quality when optional historical context is available or absent.

## 10) Assumptions

- Incident identifiers are sufficient to fetch minimum context for baseline analysis.
- External systems (ITSM/logs/Confluence) may be intermittently unavailable.
- The system can run useful analysis even with only incident-local data.

## 11) Open Questions

- Whether source toggles should be reintroduced later.
- Confidence scoring strategy and thresholds for low-confidence guidance.
- Minimum dataset and benchmark protocol for academic evaluation.
