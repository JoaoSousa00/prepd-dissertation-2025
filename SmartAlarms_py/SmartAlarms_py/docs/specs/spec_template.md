# Specification Template (SDD)

Use this template for each user story/specification in `docs/specs/phase*/`.

---

## 1) Header

- **Specification ID:** (e.g., US-3.5)
- **Title:**
- **Phase:**
- **Owner:**
- **Status:** Draft | In Review | Approved | Implemented
- **Related documents:** `docs/requirements.md`, ADR links, contract links

## 2) Problem Statement

- What problem does this specification solve?
- Why now?
- What constraints apply (tokens, cache, no DB, etc.)?

## 3) User Story

> As a ..., I want ..., so that ...

## 4) Scope

### In scope
- 

### Out of scope
- 

## 5) Acceptance Criteria

| ID | Given | When | Then |
|----|-------|------|------|
| CA-1 |  |  |  |
| CA-2 |  |  |  |

## 6) Functional Design

- Entry point(s): CI trigger, MCP tool, or both.
- Inputs and outputs (refer to `docs/contracts/tools.md` when applicable).
- Happy-path flow.
- Error-path flow.

## 7) Data and Integration Design

- External dependencies (ITSM/Logs/Confluence/LLM).
- Cache usage:
    - key format
    - TTL
    - invalidation strategy
- Identity/permissions assumptions.

## 8) Token Efficiency Design

- How this specification minimizes tokens.
- What is cached and reused.
- What is filtered/classified before any LLM call.
- Prompt size limits.

## 9) Observability

- Metrics to emit (Prometheus names).
- Tracing spans and attributes (Langfuse/OTel).
- Cost attribution fields (`user`).

## 10) Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
|  |  |  |

## 11) Test Plan

### Unit tests
- 

### Integration tests
-

## 12) Implementation Notes

- Planned files/modules.
- Dependency changes.
- Migration notes (if applicable).

## 13) Definition of Done

- Acceptance criteria met.
- Tests pass in CI.
- Required metrics and traces verified.
- Documentation/contract updates integrated.
