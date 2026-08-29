# Specification ID: US-1.4

## 1) Header

- **Title:** Measuring LLM output quality
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`

## 2) Problem Statement

The project needs simple evaluation metrics to compare the quality of the LLM outputs as the service evolves.

## 3) User Story

> As a researcher, I want the service to measure LLM output quality, so that I can compare changes step by step.

## 4) Scope

### In scope
- BLEU
- METEOR
- ROUGE
- Basic metric storage or emission for later comparison

### Out of scope
- Dashboards
- Human review tooling
- Advanced experiment tracking

## 5) Acceptance Criteria

| ID | Given | When | Then |
|----|-------|------|------|
| CA-1 | An LLM summary exists | The analysis completes | BLEU, METEOR, and ROUGE are computed |
| CA-2 | An LLM mitigation suggestion exists | The analysis completes | BLEU, METEOR, and ROUGE are computed for that output too |
| CA-3 | Metric computation fails | The analysis completes | The main response is still returned |

## 6) Functional Design

- Entry point: domain service after LLM enrichment.
- Inputs: generated text and reference text when available.
- Outputs: internal metric values linked to the analyzed incident.
- Happy path: domain normalizes texts and computes the three metrics.
- Error path: treat metric failure as non-blocking.

## 7) Data and Integration Design

- External dependencies: metric libraries for BLEU, METEOR, and ROUGE.
- Cache usage: none required for the metric values themselves.
- Identity/permissions assumptions: none beyond request context.

## 8) Token Efficiency Design

- Compute metrics after the LLM call.
- Do not add extra model prompts for metrics.

## 9) Observability

- Store or emit the metric names and scores with the incident ID.

## 10) Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Missing reference text | Incomplete evaluation | Skip unavailable comparisons instead of failing |
| Metric errors interrupt analysis | Poor user experience | Keep metrics best-effort |

## 11) Test Plan

### Unit tests
- Metric calculation for summary and suggestion outputs.
- Non-blocking failure handling.

### Integration tests
- LLM output produces metric records.

## 12) Implementation Notes

- Planned files/modules:
  - `src/application/metrics/*`
  - `src/shared/text/*`

## 13) Definition of Done

- The service computes the three metrics.
- Metric failure does not block incident analysis.
