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

- Manual execution of a fixed benchmark dataset against a selected local release/configuration through a CLI
- Configurable repeated local-service calls for every benchmark incident
- Capture of per-incident aggregated outputs and per-request measurements
- Computation of a 1-5 LLM-judged semantic score for the natural-language summary, semantic Top-K accuracy and rank
  for mitigation suggestions, and precision for related-incident references against benchmark outputs
- Release-level comparison using summary semantic score, mitigation semantic Top-K accuracy, related-incident precision, LLM token usage,
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
| CA-1 | A benchmark dataset with incident IDs and reference outputs exists        | A researcher runs the validation CLI against the local service | The CLI requests `GET /incident/details` for every benchmark incident ID without requiring a pre-captured response file |
| CA-2 | A positive repetition count is supplied or the default is used | A researcher runs the validation CLI | Every benchmark incident is requested that many times, with a default of ten calls per incident |
| CA-3 | Repeated responses exist for a benchmark incident | The report is written | The report contains one aggregate record for that incident with average 1-5 summary score, semantic Top-K accuracy, related-incident precision, token usage, cost, latency, judge telemetry, and the call counts |
| CA-4 | A local-service request fails or omits the requested incident | The remaining calls continue | The failed call is explicit in the aggregate incident record and successful calls continue to contribute to its averages |
| CA-5 | A benchmark case has no related incidents in either the reference or output | The evaluator computes the related-incident precision | The score is recorded as `1.0` because both sides are empty and the case is a valid no-correlation outcome |
| CA-6 | Two or more benchmark runs exist for different releases or configurations | The researcher compares the reports | The results can be compared release by release using aggregated quality, cost, and latency values over the same dataset |

## 6) Functional Design

- Entry point: offline benchmark evaluator script or CLI triggered by a researcher for a chosen release,
  configuration, or experiment label.
- Inputs:
    - fixed benchmark dataset containing incident identifiers and reference outputs
    - release metadata (`release_label`, model)
    - local incident-details endpoint URL and configurable repetition count
- Outputs:
    - one aggregated per-incident evaluation record, including call counts and metric averages
    - per-run aggregated comparison records
- Happy path:
    - Researcher selects a release/configuration and runs the benchmark dataset manually.
    - Each incident request returns generated outputs plus usage and latency metadata.
    - The evaluation flow matches each generated output to its benchmark references.
    - The evaluation flow invokes a deterministic LLM judge to score summary semantic equivalence from 1 to 5 and
      suggestion equivalence from 1 to 5. Suggestion scores of 4 or 5 are semantic matches; their generated
      1-based rank determines Top-K accuracy. The flow computes exact-ID precision for related incidents outside
      the live request response.
    - The flow records per-incident quality metrics and request telemetry.
    - The run produces aggregated values per release to support decision-making.
- Validation benchmark rules:
    - The golden-reference file contains benchmark incident IDs and expected outputs; it is the only validation input file.
    - The CLI calls the local `GET /incident/details` endpoint separately for each incident ID and repetition, then reads
      the returned `incidents[]` payload.
    - Model metadata is read from `llmUsage.model` in the first successful service response when available.
    - If `run_id` is not supplied, a UTC timestamp in the form `YYYYMMDDTHHMMSSZ` is generated automatically.
    - The related-incident precision metric treats an empty reference set and an empty generated set as a perfect
      match (`1.0`) so valid no-correlation cases are not penalized.
    - The report records the judge model, decision, reason, usage, cost, and latency separately from the evaluated
      service telemetry.
- Error path:
    - Individual request failures are recorded in the aggregate incident result without preventing remaining requests.
    - Missing references skip only the affected benchmark metrics.
    - A partially completed run remains analyzable as long as missing cases are explicit.

## 7) Data and Integration Design

- External dependencies: benchmark dataset storage, existing analysis service, benchmark metric computation capability,
  runtime telemetry from US-1.4.
- Benchmark dataset minimum structure:
    - `incident_id`
    - reference summary
    - reference mitigation suggestion(s), each with separate investigation and mitigation text
    - reference related-incident set (may be empty)
    - optional notes for evaluator context
- Test assets minimum structure:
    - `tests/validation/golden_reference.json` with the benchmark expected outputs
    - `tests/validation/iteration_template.json` for per-run output and benchmark metrics
      (summary score, service and judge cost/latency, semantic `Top-K`, generated suggestion ranks, and
      related-incident correlation/precision)
    - `tests/validation/README.md` with instructions for running the validation suite
    - free-text area for manual notes
- Run metadata minimum structure:
    - `run_id` (generated as UTC timestamp if not supplied)
    - `release_label`
    - `dataset_version`
    - `model_name` (derived from the service payload when available)
    - `judge_model_name`
    - configuration notes
- Per-incident result minimum structure:
    - `incident_id`
    - summary semantic score (1-5) and judge reason
    - mitigation semantic Top-K accuracy and per-reference generated rank
    - related-incident precision metrics
    - `tokens_in`
    - `tokens_out`
    - `tokens_total`
    - estimated cost
    - latency
    - judge model, token usage, estimated cost, latency, and decisions
    - total and successful call counts
    - execution status/error notes

## 8) Token Efficiency Design

- Reuse the normal analysis request flow instead of creating a benchmark-specific prompt path.
- Run the benchmark only on the fixed dataset to keep comparisons reproducible and bounded.
- Compare releases on the same dataset and configuration dimensions whenever possible.

## 9) Observability

- Track each benchmark request with release label, dataset version, incident ID, model, token usage, estimated cost,
  and latency.
- Preserve per-incident call counts, failed-call details, and averaged metrics alongside aggregated release-level summaries.
- Make metric gaps and failed benchmark cases explicit in the recorded output.
- Keep summary semantic score, mitigation semantic Top-K accuracy, and related-incident precision as benchmark artifacts only, not normal
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
- Mapping repeated local-service responses into one per-incident aggregate result.
- Handling of partial failures and missing references.
- LLM-judged 1-5 semantic summary scoring, including the full scoring rubric.
- LLM-judged semantic Top-K and generated rank computation for mitigation suggestions, including partial matches.
- Precision computation for related-incident references, including the empty/empty edge case.
- Loading of golden references from a validation fixture file.
- Writing of per-iteration result templates for validation runs.
- Validation README describing how to execute the benchmark/validation suite.
- CLI-based local-service execution that writes a JSON validation report to a chosen output path.
- Configurable repeated requests, response model metadata extraction, and timestamp-based run IDs.

### Integration tests

- Manual benchmark run produces per-incident and aggregated release records using the US-1.4 runtime telemetry outputs.

## 12) Implementation Notes

- Planned files/modules:
    - benchmark dataset definition under project evaluation assets
    - release evaluation CLI for repeated local-service benchmark runs
    - aggregation/reporting module for benchmark runs
    - `tests/validation/` fixture file for golden references
    - `tests/validation/` template file for per-iteration benchmark results
    - `tests/validation/README.md` for execution instructions
- Analysis rule:
    - Record data per incident/request.
    - Compute a 1-5 semantic summary score, semantic Top-K accuracy for mitigation suggestions, and precision for related-
      incident references in the benchmark evaluation flow against fixed references.
    - Choose the preferred solution by comparing aggregated results per release/configuration on the same benchmark
      dataset.
    - Use a versioned, deterministic (`temperature=0`) LLM judge prompt and preserve every judge decision in the
      generated report.

## 13) Definition of Done

- A manual benchmark workflow is specified for running the same dataset across releases.
- The specification defines how to capture and compare quality, cost, and latency.
- The specification makes benchmark-only evaluation metrics separate from the live request response.
- Release-level comparison criteria are explicit, while per-incident records remain available for detailed analysis.
