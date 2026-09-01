# Specification ID: US-1.5

## 1) Header

- **Title:** Running manual release-by-release evaluation
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Draft
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`, `docs/specs/phase1/US-1.4-output-metrics.md`

## 2) Problem Statement

Once request latency and LLM usage cost are available from the normal analysis flow, the project needs a repeatable way
to compare candidate releases using a fixed benchmark dataset. This benchmark evaluation is the correct place to compute
lexical quality metrics such as BLEU, METEOR, and ROUGE, because only the benchmark dataset provides stable human
references for comparison.

## 3) User Story

> As a researcher, I want to run the same benchmark incidents against each release manually, so that I can compare which
> release gives the best balance of quality, cost, and latency.

## 4) Scope

### In scope

- Manual execution of a fixed benchmark dataset against a selected release/configuration
- Capture of per-incident outputs and per-request measurements
- Computation of BLEU, METEOR, and ROUGE against benchmark reference summaries and mitigation texts
- Release-level comparison using BLEU, METEOR, ROUGE, LLM token usage, estimated monetary cost, and latency
- Recording release metadata such as release label, model, prompt version, and enabled sources
- Aggregated comparison across benchmark runs

### Out of scope

- Fully automated CI benchmark orchestration
- Online dashboards
- Automatic human judgment collection
- Statistical significance tooling beyond basic descriptive comparison

## 5) Acceptance Criteria

| ID   | Given                                                                     | When                                                | Then                                                                                                                                                                                 |
|------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | A benchmark dataset with incident IDs and reference outputs exists        | A researcher runs a manual evaluation for a release | Each benchmark incident is executed, its generated outputs are compared against the benchmark references, and lexical metrics, token usage, estimated cost, and latency are recorded |
| CA-2 | Two or more benchmark runs exist for different releases or configurations | The researcher compares the runs                    | The results can be compared release by release using aggregated quality, cost, and latency values over the same dataset                                                              |
| CA-3 | Some benchmark incidents fail or return incomplete metric data            | The manual run completes                            | Failures are recorded per incident and the remaining benchmark cases still contribute to the release comparison                                                                      |
| CA-4 | Per-incident raw results are available                                    | The researcher analyzes release performance         | The primary comparison is done at release level, while per-incident records remain available for diagnosis of outliers and regressions                                               |

## 6) Functional Design

- Entry point: manual evaluator workflow triggered by a researcher for a chosen release, configuration, or experiment
  label.
- Inputs:
    - fixed benchmark dataset containing incident identifiers and reference outputs
    - release metadata (`release_label`, model, prompt version, enabled sources)
    - raw request results from the analysis service, including runtime telemetry from US-1.4
- Outputs:
    - per-incident evaluation records
    - per-run aggregated comparison records
- Happy path:
    - Researcher selects a release/configuration and runs the benchmark dataset manually.
    - Each incident request returns generated outputs plus usage and latency metadata.
    - The evaluation flow matches each generated output to its benchmark references.
    - The evaluation flow computes BLEU, METEOR, and ROUGE outside the live request response.
    - The flow records per-incident quality metrics and request telemetry.
    - The run produces aggregated values per release to support decision-making.
- Error path:
    - Individual incident failures are logged as part of the run result.
    - Missing references skip only the affected lexical metrics.
    - A partially completed run remains analyzable as long as missing cases are explicit.

## 7) Data and Integration Design

- External dependencies: benchmark dataset storage, existing analysis service, lexical metric computation capability,
  runtime telemetry from US-1.4.
- Benchmark dataset minimum structure:
    - `incident_id`
    - reference summary
    - reference mitigation suggestion
    - optional notes for evaluator context
- Run metadata minimum structure:
    - `run_id`
    - `release_label`
    - `dataset_version`
    - `model_name`
    - `prompt_version`
    - enabled sources/configuration notes
- Per-incident result minimum structure:
    - `incident_id`
    - summary metrics
    - mitigation metrics
    - `tokens_in`
    - `tokens_out`
    - `tokens_total`
    - estimated cost
    - latency
    - execution status/error notes

## 8) Token Efficiency Design

- Reuse the normal analysis request flow instead of creating a benchmark-specific prompt path.
- Run the benchmark only on the fixed dataset to keep comparisons reproducible and bounded.
- Compare releases on the same dataset and configuration dimensions whenever possible.

## 9) Observability

- Track each benchmark request with release label, dataset version, incident ID, model, prompt version, enabled sources,
  token usage, estimated cost, and latency.
- Preserve both per-incident raw values and aggregated release-level summaries.
- Make metric gaps and failed benchmark cases explicit in the recorded output.
- Keep BLEU, METEOR, and ROUGE as benchmark artifacts only, not normal live-response fields.

## 10) Risks and Mitigations

| Risk                                                                    | Impact                                | Mitigation                                                       |
|-------------------------------------------------------------------------|---------------------------------------|------------------------------------------------------------------|
| Different releases are tested with different datasets or configurations | Results become unfair or incomparable | Require dataset version and release metadata in every run record |
| Manual execution introduces inconsistency                               | Harder academic comparison            | Use a fixed run checklist and standardized output fields         |
| Low-quality reference texts bias lexical metrics                        | Misleading conclusions                | Curate benchmark references carefully and version the dataset    |
| Focusing only on averages hides regressions                             | Bad release choice                    | Keep per-incident raw records to inspect outliers and failures   |

## 11) Test Plan

### Unit tests

- Aggregation logic for release-level averages or summary statistics.
- Mapping of per-incident request outputs into benchmark result records.
- Handling of partial failures and missing references.

### Integration tests

- Manual benchmark run produces per-incident and aggregated release records using the US-1.4 runtime telemetry outputs.

## 12) Implementation Notes

- Planned files/modules:
    - benchmark dataset definition under project evaluation assets
    - release evaluation runner or documented manual procedure
    - aggregation/reporting module for benchmark runs
- Analysis rule:
    - Record data per incident/request.
    - Compute BLEU, METEOR, and ROUGE only in the benchmark evaluation flow against fixed references.
    - Choose the preferred solution by comparing aggregated results per release/configuration on the same benchmark
      dataset.

## 13) Definition of Done

- A manual benchmark workflow is specified for running the same dataset across releases.
- The specification defines how to capture and compare quality, cost, and latency.
- The specification makes benchmark-only lexical metrics separate from the live request response.
- Release-level comparison criteria are explicit, while per-incident records remain available for detailed analysis.
