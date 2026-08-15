# Project Objective

The objective of this project is to develop a simple and modular solution capable of supporting support teams in interpreting and mitigating IT incidents through the use of Large Language Models (LLMs).

The solution should be able to:

* Correlate similar incidents based on history;
* Generate natural-language summaries to make ticket understanding easier;
* Suggest possible mitigation actions;
* Optionally analyze logs and additional information from external tools.

The main focus of the project is not to build a complex AI system, but to validate whether using LLMs and historical information can reduce the manual effort associated with incident investigation.

### Phase-based Approach

Development should be organized into 2 phases, iteratively and in a comparable way:

* **Phase 1**: basic service that communicates directly with required components (ITSM, logs, LLM), keeping the flow simple with direct integrations and minimal architectural complexity;
* **Phase 2**: more robust service, with structured metrics, rich logs, exception handling, ability to handle multiple requests in parallel, and optional connection to ITSM and other components through MCP.

**Evaluation Metrics**: In both phases, collect lexical similarity metrics (**BLEU**, **METEOR**, **ROUGE**) over LLM outputs (summaries and suggestions) to enable comparison and validation of improvements between phases.

---

# General Principles

## Simplicity and Pragmatism

The solution should prioritize simplicity, clarity, and avoid overengineering.

Avoid:
* Patterns without practical need;
* Premature abstractions;
* Complex distributed architectures;
* Unnecessary microservices;
* Full CQRS, Event Sourcing, or full hexagonal architecture.

Prefer:
* Clear and direct code;
* Simple separation between domain, application, and infrastructure;
* Small, testable components;
* Decoupled and localized integrations.

---

# Recommended Structure

```text
src/
 ├── domain/
 │    ├── incident/
 │    ├── correlation/
 │    └── mitigation/
 │
 ├── application/
 │    ├── usecases/
 │    └── services/
 │
 ├── infrastructure/
 │    ├── adapters/
 │    │    ├── itsm/
 │    │    ├── llm/
 │    │    ├── logs/
 │    │    └── mcp/
 │    └── persistence/
 │
 ├── presentation/
 │    └── api/
 │
 └── shared/
```

---

# Layer Responsibilities

## Domain

Contains:

* Main entities;
* Domain objects;
* Business rules;
* Important interfaces.

Examples:

* Incident
* RelatedIncident
* MitigationSuggestion

The domain layer should not know:

* External APIs;
* Databases;
* Frameworks.

---

## Application

Contains use cases and orchestration:

Examples:

* AnalyzeIncidentUseCase
* CorrelateIncidentsUseCase
* GenerateMitigationUseCase

Responsible for:

* Coordinating services;
* Orchestrating calls;
* Applying application flow.

---

## Infrastructure

Responsible for all external integrations:

Examples:

* ServiceNow connector;
* Kibana connector;
* CloudWatch connector;
* LLM provider;
* Repositories.

### Persistence
* Repositories to store history;
* Correlated incident cache (if needed).

This layer can be replaced without changing domain or application.

---

## Presentation

Responsible for exposure:

Examples:

* REST API;
* Web application;
* Controllers.

Should not contain business logic.

---

# Expected Flow (Phase 1)

```text
1. Receive one or more incident IDs via GET /incident/details
2. Fetch primary incident details from ITSM (and related history when available)
3. Call LLM to:
   - Generate natural-language summary
   - Correlate with previous incidents
   - Suggest mitigation actions
4. Collect responses and evaluate with BLEU/METEOR/ROUGE
5. Return result to user
6. Store feedback (if applicable) for future analysis
```

---

# Technologies (Phase 1)

### Integrations (enable as needed)
* ITSM access
* Log access
* **LLM API** (Copilot, GAIA, configurable...)

### Output Evaluation
* **BLEU**: `nltk` package or similar
* **ROUGE**: `rouge` package or similar
* **METEOR**: `nltk` package with METEOR data

---

# Technologies (Phase 2)

Keeps everything from Phase 1 and adds:

* **Structured logging**
* **Metrics** (LLM usage and token cost with LangFuse)
* **Tracing**
* **Concurrency**
* **MCP Servers**
* **Cache**

---

# Frontend

Do not implement for now. Future aspiration: browser extension developed in TypeScript.

---

# Remaining Considerations

## Simple but Explicit Boundaries

* Phase 1 does not handle multiple parallel requests with strong guarantees;
* Phase 1 does not include structured observability;
* Phase 2 refactors only what is necessary for robustness, without radical domain changes.

## Success Metrics

* **Phase 1**: Can the LLM generate useful summaries and suggestions? (validate with BLEU/METEOR/ROUGE and human review);
* **Phase 2**: Can the system support multiple requests without crashes? Did metrics improve?

## Next Steps

1. Implement domain and application (Phase 1);
2. Integrate ITSM, LLM, and logs locally;
3. Collect output metrics;
4. Evaluate feasibility with real data;
5. Outline Phase 2 with robustness and MCP.
