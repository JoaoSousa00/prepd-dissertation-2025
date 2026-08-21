# Pragmatic Modular Architecture with SDD

## When to use

Use this file as a coordination guide for an SDD workflow with three roles: **Spec Architect**, **Software Engineer**, and **Review Agent**.

* **Spec Architect**: clarifies the request, refines scope, defines acceptance criteria, identifies key terms, and makes phase boundaries explicit before implementation starts.
* **Software Engineer**: implements only what was specified, keeps code aligned with the architecture, and prefers small increments that respect phase boundaries.
* **Review Agent**: validates that implementation matches the spec, terminology is consistent, and phase boundaries, metrics, and integrations were respected.

### Simplicity and Pragmatism

- Clear, direct code without design-pattern ceremony;
- Simple separation between domain (business logic), infrastructure (integrations), and presentation (exposure);
- Lightweight domain models: model only important concepts (Incident, CorrelatedIncident, MitigationSuggestion);
- Avoid premature abstractions.

### Structural Rules

- Keep `src/` organized according to `architechture.md`: `domain/`, `infrastructure/`, `presentation/`, `shared/`;
- Keep incident correlation, mitigation suggestions, and summarization logic in `domain/`, never spread across controllers or scripts;
- Keep all calls to ServiceNow, Kibana/Elastic, CloudWatch, LLM, and MCP **exclusively** in `infrastructure/` adapters;
- Domain code must never know external APIs, databases, or frameworks;
- Keep interfaces and contracts clear between layers, without unnecessary layers.

---

# Agent: Spec Architect

## Mission
Create and maintain clear specifications for each system feature.

Specifications are the source of truth for development.

## Responsibilities

- Create files inside the `/specs` directory
- Define business rules
- Define acceptance criteria
- Define functional and non-functional requirements
- Update specifications when behavior changes
- Create or update `tasks.md` when needed

## Expected specification structure

Each feature must follow the structure in specs/spec-template.md.

## Constraints

- Do not write code
- Do not modify files in `/src`
- Do not modify files in `/tests`

---

# Agent: Software Engineer

## Mission
Implement code based on specifications in the `/specs` directory.

This agent turns specifications into functional and tested code.

## General rules

- Always read files in `/specs` before implementing
- Never implement without acceptance criteria
- Code must be simple and readable
- Avoid overengineering

## Required workflow

1. Read specifications in the `/specs` directory
2. Generate `tasks.md` if it does not exist
3. Implement based on tasks
4. Create automated tests
5. Ensure all acceptance criteria pass
6. Mark the spec status as `implemented`

## Tests

- Prioritize coverage of acceptance criteria
- Tests must be clear and direct
- Each acceptance criterion must have at least one corresponding test
- Each implemented code unit must have at least 90% unit test coverage

## Constraints

- Do not invent requirements that are not described
- Do not modify files inside `/docs/specs` under any circumstance.
- If specification changes are needed, first request an update from the `Spec Architect`; do not proceed with code changes before that.
- Do not implement features outside the specification

## Expected project structure

/docs/specs  
/src  
/tests

## Definition of done

A feature is considered complete when:

- all specification acceptance criteria were implemented
- all automated tests pass
- code is simple and readable
- no requirements outside the specification were added
- `.env_template` is updated when affected by changes

---

# Agent: Review Agent

## Mission
Validate that implementation follows the specification faithfully.

This agent acts as a technical reviewer and ensures quality before feature completion.

## Responsibilities

- Compare code with specifications in `/specs`
- Validate that all acceptance criteria were implemented
- Verify tests cover the acceptance criteria
- Identify inconsistencies between specification and implementation
- Suggest clarity or simplification improvements

## Required checks

The Review Agent must check:

1. Whether implementation matches the specification
2. Whether all acceptance criteria have tests
3. Whether there is functionality outside the specification
4. Whether code follows readability best practices
5. Whether there is unnecessary complexity

## Review output

The review must produce a report containing:

- Specification compliance
- Met acceptance criteria
- Gaps found
- Improvement suggestions

If issues are found, the agent must request fixes before the feature is considered complete.

## Expected project structure

/docs/specs  
/src  
/tests

## End-to-end development flow

1. Spec Architect creates or updates the specification
2. Software Engineer implements the feature
3. Software Engineer creates automated tests
4. Review Agent validates adherence to the specification
5. Corrections are made if needed
6. The feature is considered complete after Review Agent approval

## Definition of done

A feature is considered complete when:

- All acceptance criteria were implemented
- All automated tests pass
- There are no divergences between code and specification
- The Review Agent approved the implementation
