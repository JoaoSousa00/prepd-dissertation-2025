# Specification ID: US-1.5

## 1) Header

- **Title:** Running manual release-by-release evaluation
- **Phase:** Phase 1
- **Owner:** Spec Architect
- **Status:** Implemented / Updated
- **Related documents:** `docs/requirements.md`, `docs/architechture.md`, `docs/specs/phase1/US-1.4-output-metrics.md`

## 2) Problem Statement

Once request latency and LLM usage cost are available from the normal analysis flow, the project needs a repeatable way
to compare candidate releases using a fixed benchmark dataset. This benchmark evaluation is the correct place to compute
benchmark quality metrics, because only the benchmark dataset provides stable human references for comparison. The
evaluation should be run through a dedicated offline script or CLI.

## 3) User Story

> As a researcher, I want to run the same benchmark incidents against each release manually, so that I can compare which
> release gives the best balance of quality, cost, and latency.

## 4) Scope

### In scope

- Manual execution of a fixed benchmark dataset against a selected release/configuration through an offline script or CLI
- Capture of per-incident outputs and per-request measurements
- Computation of ROUGE for the natural-language summary, Top-K accuracy for mitigation suggestions, and precision for
  related-incident references against benchmark outputs
- Release-level comparison using ROUGE, mitigation Top-K accuracy, related-incident precision, LLM token usage,
  estimated monetary cost, and latency
- Recording release metadata such as release label and model, with automatic run identifiers generated as UTC timestamps
  when no explicit run ID is supplied
- Aggregated comparison across benchmark runs
- Benchmark-only evaluation logic kept entirely outside the live service response contract and runtime application code

### Out of scope

- Fully automated CI benchmark orchestration
- Online dashboards
- Automatic human judgment collection
- Statistical significance tooling beyond basic descriptive comparison

## 5) Acceptance Criteria

| ID   | Given                                                                     | When                                                | Then                                                                                                                                                                                 |
|------|---------------------------------------------------------------------------|-----------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CA-1 | A benchmark dataset with incident IDs and reference outputs exists        | A researcher runs a manual evaluation for a release | Each benchmark incident is executed, its generated outputs are compared against the benchmark references, and ROUGE, Top-K accuracy, precision, token usage, estimated cost, and latency are recorded |
| CA-2 | Two or more benchmark runs exist for different releases or configurations | The researcher compares the runs                    | The results can be compared release by release using aggregated quality, cost, and latency values over the same dataset                                                              |
| CA-3 | Some benchmark incidents fail or return incomplete metric data            | The manual run completes                            | Failures are recorded per incident and the remaining benchmark cases still contribute to the release comparison                                                                      |
| CA-4 | Per-incident raw results are available                                    | The researcher analyzes release performance         | The primary comparison is done at release level, while per-incident records remain available for diagnosis of outliers and regressions                                               |
| CA-5 | A benchmark case has no related incidents in either the reference or output | The evaluator computes the related-incident precision | The score is recorded as `1.0` because both sides are empty and the case is a valid no-correlation outcome                                                                             |

## 6) Functional Design

- Entry point: offline benchmark evaluator script or CLI triggered by a researcher for a chosen release,
  configuration, or experiment label.
- Inputs:
    - fixed benchmark dataset containing incident identifiers and reference outputs
    - release metadata (`release_label`, model)
    - raw request results from the analysis service, including runtime telemetry from US-1.4
- Outputs:
    - per-incident evaluation records
    - per-run aggregated comparison records
- Happy path:
    - Researcher selects a release/configuration and runs the benchmark dataset manually.
    - Each incident request returns generated outputs plus usage and latency metadata.
    - The evaluation flow matches each generated output to its benchmark references.
    - The evaluation flow computes ROUGE for the summary, Top-K accuracy for mitigation suggestions, and precision
      for related-incident references outside the live request response.
    - The flow records per-incident quality metrics and request telemetry.
    - The run produces aggregated values per release to support decision-making.
- Validation benchmark rules:
    - Validation inputs are file-based fixtures under `tests/validation/`, not live API calls.
    - The benchmark accepts a service-response-shaped payload with `incidents[]`, and reads model metadata from
      `llmUsage.model` when available.
    - If `run_id` is not supplied, a UTC timestamp in the form `YYYYMMDDTHHMMSSZ` is generated automatically.
    - The related-incident precision metric treats an empty reference set and an empty generated set as a perfect
      match (`1.0`) so valid no-correlation cases are not penalized.
- Error path:
    - Individual incident failures are logged as part of the run result.
    - Missing references skip only the affected benchmark metrics.
    - A partially completed run remains analyzable as long as missing cases are explicit.

## 7) Data and Integration Design

- External dependencies: benchmark dataset storage, existing analysis service, benchmark metric computation capability,
  runtime telemetry from US-1.4.
- Benchmark dataset minimum structure:
    - `incident_id`
    - reference summary
    - reference mitigation suggestion(s)
    - reference related-incident set (may be empty)
    - optional notes for evaluator context
- Test assets minimum structure:
    - `tests/validation/golden_reference.json` with the benchmark expected outputs
    - `tests/validation/sample_service_response.json` with a representative service payload containing `incidents[]`
    - `tests/validation/iteration_template.json` for per-run output and benchmark metrics
      (`ROUGE`, estimated cost, latency, `Top-K`, and related-incident correlation/precision)
    - `tests/validation/README.md` with instructions for running the validation suite
    - free-text area for manual notes
- Run metadata minimum structure:
    - `run_id` (generated as UTC timestamp if not supplied)
    - `release_label`
    - `dataset_version`
    - `model_name` (derived from the service payload when available)
    - configuration notes
- Per-incident result minimum structure:
    - `incident_id`
    - summary ROUGE metrics
    - mitigation Top-K accuracy metrics
    - related-incident precision metrics
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

- Track each benchmark request with release label, dataset version, incident ID, model, token usage, estimated cost,
  and latency.
- Preserve both per-incident raw values and aggregated release-level summaries.
- Make metric gaps and failed benchmark cases explicit in the recorded output.
- Keep ROUGE, mitigation Top-K accuracy, and related-incident precision as benchmark artifacts only, not normal
  live-response fields.

## 10) Risks and Mitigations

| Risk                                                                    | Impact                                | Mitigation                                                       |
|-------------------------------------------------------------------------|---------------------------------------|------------------------------------------------------------------|
| Different releases are tested with different datasets or configurations | Results become unfair or incomparable | Require dataset version and release metadata in every run record |
| Manual execution introduces inconsistency                               | Harder academic comparison            | Use a fixed run checklist and standardized output fields         |
| Low-quality reference texts bias benchmark metrics                      | Misleading conclusions                | Curate benchmark references carefully and version the dataset    |
| Focusing only on averages hides regressions                             | Bad release choice                    | Keep per-incident raw records to inspect outliers and failures   |

## 11) Test Plan

### Validation tests

- Aggregation logic for release-level averages or summary statistics.
- Mapping of per-incident request outputs into benchmark result records.
- Handling of partial failures and missing references.
- ROUGE computation for summaries using `rouge-score`.
- Top-K accuracy computation for mitigation suggestions.
- Precision computation for related-incident references, including the empty/empty edge case.
- Loading of golden references from a validation fixture file.
- Writing of per-iteration result templates for validation runs.
- Validation README describing how to execute the benchmark/validation suite.
- CLI-based offline execution that writes a JSON validation report to a chosen output path.
- Metadata extraction from the service response payload, including model name and timestamp-based run IDs.

### Integration tests

- Manual benchmark run produces per-incident and aggregated release records using the US-1.4 runtime telemetry outputs.

## 12) Implementation Notes

- Planned files/modules:
    - benchmark dataset definition under project evaluation assets
    - release evaluation script or CLI for offline benchmark runs
    - aggregation/reporting module for benchmark runs
    - `tests/validation/` fixture file for golden references
    - `tests/validation/` template file for per-iteration benchmark results
    - `tests/validation/README.md` for execution instructions
- Analysis rule:
    - Record data per incident/request.
    - Compute ROUGE only for the summary, Top-K accuracy for mitigation suggestions, and precision for related-
      incident references in the benchmark evaluation flow against fixed references.
    - Choose the preferred solution by comparing aggregated results per release/configuration on the same benchmark
      dataset.
    - Use `rouge-score` in the test suite to validate ROUGE-based summary evaluation against the golden reference.

## 13) Definition of Done

- A manual benchmark workflow is specified for running the same dataset across releases.
- The specification defines how to capture and compare quality, cost, and latency.
- The specification makes benchmark-only evaluation metrics separate from the live request response.
- Release-level comparison criteria are explicit, while per-incident records remain available for detailed analysis.
