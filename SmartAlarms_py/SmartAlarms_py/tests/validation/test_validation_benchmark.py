from collections import Counter
import json
from pathlib import Path

import httpx2 as httpx
import pytest

from tests.validation.benchmark import (
    BenchmarkCaseReference,
    BenchmarkCaseOutput,
    BenchmarkJudgeDecision,
    BenchmarkJudgeError,
    BenchmarkJudgeUsage,
    BenchmarkRunMetadata,
    BenchmarkResolutionSuggestion,
    BenchmarkSuggestionMatch,
    BenchmarkSummaryJudgment,
    collect_benchmark_outputs,
    evaluate_benchmark_run,
    load_golden_reference,
    render_iteration_template,
)
from tests.validation.cli import main as validation_main


FIXTURE_DIR = Path(__file__).resolve().parent


class _MatchingJudge:
    model_name = "judge-model"

    def evaluate(self, reference, output):
        matches = []
        for reference_index, reference_suggestion in enumerate(
            reference.reference_mitigation_suggestions,
            start=1,
        ):
            generated_rank = next(
                (
                    index
                    for index, generated_suggestion in enumerate(
                        output.generated_mitigation_suggestions,
                        start=1,
                    )
                    if generated_suggestion == reference_suggestion
                ),
                None,
            )
            matches.append(
                BenchmarkSuggestionMatch(
                    reference_index=reference_index,
                    generated_rank=generated_rank,
                    score=5 if generated_rank is not None else 1,
                    reason="Equivalent." if generated_rank is not None else "Not equivalent.",
                )
            )
        return BenchmarkJudgeDecision(
            summary=BenchmarkSummaryJudgment(score=5, reason="Equivalent."),
            suggestion_matches=matches,
            usage=BenchmarkJudgeUsage(
                model_name=self.model_name,
                tokens_in=20,
                tokens_out=10,
                tokens_total=30,
                estimated_cost=0.001,
                latency_ms=100,
            ),
        )


class _RankedJudge:
    model_name = "judge-model"

    def __init__(self, summary_score, matches):
        self._summary_score = summary_score
        self._matches = matches

    def evaluate(self, _reference, _output):
        return BenchmarkJudgeDecision(
            summary=BenchmarkSummaryJudgment(
                score=self._summary_score,
                reason="Semantic evaluation.",
            ),
            suggestion_matches=self._matches,
        )


def _service_incident(reference, call_number):
    return {
        "id": reference.incident_id,
        "summary": reference.reference_summary,
        "resolutionSuggestions": [
            {
                "investigation": suggestion.investigation,
                "mitigation": suggestion.mitigation,
            }
            for suggestion in reference.reference_mitigation_suggestions
        ],
        "relatedIncidents": reference.reference_related_incidents,
        "llmUsage": {
            "model": "provider-returned-model",
            "tokensIn": 100 * call_number,
            "tokensOut": 10 * call_number,
            "tokensTotal": 110 * call_number,
            "cost_USD": 0.01 * call_number,
        },
        "requestLatencyMs": 1000 * call_number,
    }


def _successful_output(reference, call_number):
    return BenchmarkCaseOutput(
        incident_id=reference.incident_id,
        generated_summary=reference.reference_summary,
        generated_mitigation_suggestions=reference.reference_mitigation_suggestions,
        generated_related_incidents=reference.reference_related_incidents,
        tokens_in=100 * call_number,
        tokens_out=10 * call_number,
        tokens_total=110 * call_number,
        estimated_cost=0.01 * call_number,
        latency_ms=1000 * call_number,
    )


def test_load_golden_reference_reads_validation_dataset():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")

    assert references
    assert all(reference.incident_id.startswith("INC") for reference in references)
    assert all(reference.reference_summary for reference in references)
    assert all(
        isinstance(suggestion, BenchmarkResolutionSuggestion)
        for reference in references
        for suggestion in reference.reference_mitigation_suggestions
    )


def test_related_incident_precision_is_one_when_both_sides_are_empty():
    from tests.validation.benchmark import _compute_precision

    assert _compute_precision([], []) == pytest.approx(1.0)


def test_evaluate_benchmark_run_records_semantic_suggestion_rank():
    reference = BenchmarkCaseReference(
        incident_id="INC000000000001",
        reference_summary="Session Store job failed.",
        reference_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(
                investigation="Check Session Store job logs.",
                mitigation="Retry the Session Store job.",
            )
        ],
    )
    output = BenchmarkCaseOutput(
        incident_id=reference.incident_id,
        generated_summary="The Session Store task failed.",
        generated_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(
                investigation="Review Session Store execution logs.",
                mitigation="Restart the failed Session Store task.",
            )
        ],
    )
    metadata = BenchmarkRunMetadata(
        run_id="run",
        release_label="local",
        dataset_version="dataset",
        model_name="provider-returned-model",
    )

    judge = _RankedJudge(
        summary_score=4,
        matches=[
            BenchmarkSuggestionMatch(
                reference_index=1,
                generated_rank=1,
                score=4,
                reason="Same operational action.",
            )
        ],
    )
    evaluation = evaluate_benchmark_run([reference], [output], metadata, judge=judge, top_k=1)

    assert evaluation.metrics["summary_score"] == pytest.approx(4.0)
    assert evaluation.metrics["top_k_accuracy"] == pytest.approx(1.0)
    assert evaluation.cases[0].suggestion_matches[0].generated_rank == 1


def test_evaluate_benchmark_run_excludes_partial_suggestions_from_top_k():
    reference = BenchmarkCaseReference(
        incident_id="INC000000000001",
        reference_summary="Session Store job failed.",
        reference_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(mitigation="Retry the Session Store job.")
        ],
    )
    output = BenchmarkCaseOutput(incident_id=reference.incident_id)
    metadata = BenchmarkRunMetadata("run", "local", "dataset", "service-model")
    judge = _RankedJudge(
        summary_score=3,
        matches=[
            BenchmarkSuggestionMatch(
                reference_index=1,
                generated_rank=None,
                score=3,
                reason="Important mitigation detail is missing.",
            )
        ],
    )

    evaluation = evaluate_benchmark_run([reference], [output], metadata, judge=judge, top_k=3)

    assert evaluation.metrics["summary_score"] == pytest.approx(3.0)
    assert evaluation.metrics["top_k_accuracy"] == pytest.approx(0.0)


def test_evaluate_benchmark_run_computes_all_validation_metrics():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    metadata = BenchmarkRunMetadata(
        run_id="run",
        release_label="local",
        dataset_version="dataset",
        model_name="provider-returned-model",
    )
    outputs = [_successful_output(reference, 1) for reference in references]

    evaluation = evaluate_benchmark_run(
        references,
        outputs,
        metadata,
        judge=_MatchingJudge(),
        top_k=1,
    )

    assert evaluation.metrics["summary_score"] == pytest.approx(5.0)
    assert evaluation.metrics["top_k_accuracy"] == pytest.approx(1.0)
    assert evaluation.metrics["related_incident_precision"] == pytest.approx(1.0)
    assert evaluation.metrics["estimated_cost"] == pytest.approx(0.01)
    assert evaluation.metrics["latency_ms"] == pytest.approx(1000)
    assert evaluation.metrics["judge_estimated_cost"] == pytest.approx(0.001)
    assert len(evaluation.cases) == len(references)
    assert evaluation.cases[0].status == "success"


def test_collect_benchmark_outputs_calls_each_incident_for_every_repetition():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    calls = Counter()
    progress_events = []

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/incident/details"
        incident_id = request.url.params["incidentIds"]
        calls[incident_id] += 1
        reference = next(item for item in references if item.incident_id == incident_id)
        return httpx.Response(
            200,
            json={"incidents": [_service_incident(reference, calls[incident_id])]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata, outputs = collect_benchmark_outputs(
            references,
            service_url="http://validation.local/incident/details",
            repetitions=3,
            client=client,
            progress_callback=lambda status, request_number, total_requests, incident_id: progress_events.append(
                (status, request_number, total_requests, incident_id)
            ),
        )

    assert calls == Counter({reference.incident_id: 3 for reference in references})
    assert len(outputs) == len(references) * 3
    assert metadata.model_name == "provider-returned-model"
    total_requests = len(references) * 3
    assert progress_events[0] == ("requesting", 1, total_requests, references[0].incident_id)
    assert progress_events[-1] == ("success", total_requests, total_requests, references[-1].incident_id)
    assert len(progress_events) == total_requests * 2
    assert outputs[0].generated_mitigation_suggestions == references[0].reference_mitigation_suggestions


def test_render_iteration_template_keeps_repeated_call_results_and_average_by_incident():
    first_reference = BenchmarkCaseReference(
        incident_id="INC000000000001",
        reference_summary="First incident summary.",
        reference_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(
                investigation="Inspect the first incident.",
                mitigation="Mitigate the first incident.",
            )
        ],
    )
    second_reference = BenchmarkCaseReference(
        incident_id="INC000000000002",
        reference_summary="Second incident summary.",
        reference_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(
                investigation="Inspect the second incident.",
                mitigation="Mitigate the second incident.",
            )
        ],
    )
    references = [first_reference, second_reference]
    metadata = BenchmarkRunMetadata(
        run_id="run",
        release_label="local",
        dataset_version="dataset",
        model_name="provider-returned-model",
    )
    outputs = [
        _successful_output(first_reference, 1),
        BenchmarkCaseOutput(
            incident_id=first_reference.incident_id,
            status="request_failed",
            error_notes="ConnectError: unavailable",
        ),
        _successful_output(first_reference, 3),
        _successful_output(second_reference, 2),
        _successful_output(second_reference, 4),
    ]

    report = render_iteration_template(
        evaluate_benchmark_run(references, outputs, metadata, judge=_MatchingJudge(), top_k=1)
    )
    first_case = next(
        case for case in report["cases"] if case["incident_id"] == first_reference.incident_id
    )
    second_case = next(
        case for case in report["cases"] if case["incident_id"] == second_reference.incident_id
    )

    assert len(report["cases"]) == len(references)
    assert first_case["status"] == "partial_failure"
    assert first_case["call_count"] == 3
    assert first_case["successful_call_count"] == 2
    assert [result["call_number"] for result in first_case["results"]] == [1, 2, 3]
    assert first_case["results"][1]["status"] == "request_failed"
    assert first_case["results"][0]["judge_decision"]["suggestion_matches"][0][
        "generated_rank"
    ] == 1
    assert first_case["average"]["summary_score"] == pytest.approx(5.0)
    assert first_case["average"]["tokens_in"] == pytest.approx(200)
    assert first_case["average"]["cost_USD"] == pytest.approx(0.02)
    assert first_case["average"]["latency_ms"] == pytest.approx(2000)
    assert first_case["error_notes"] == "ConnectError: unavailable"
    assert second_case["call_count"] == 2
    assert len(second_case["results"]) == 2
    assert second_case["average"]["tokens_in"] == pytest.approx(300)


def test_collect_benchmark_outputs_records_failures_and_continues():
    reference = load_golden_reference(FIXTURE_DIR / "golden_reference.json")[0]
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"incidents": [_service_incident(reference, calls)]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata, outputs = collect_benchmark_outputs(
            [reference],
            service_url="http://validation.local/incident/details",
            repetitions=3,
            client=client,
        )

    report = render_iteration_template(
        evaluate_benchmark_run([reference], outputs, metadata, judge=_MatchingJudge(), top_k=1)
    )
    case = report["cases"][0]

    assert calls == 3
    assert metadata.model_name == "provider-returned-model"
    assert case["status"] == "partial_failure"
    assert case["call_count"] == 3
    assert case["successful_call_count"] == 2
    assert case["error_notes"].startswith("HTTPStatusError:")


def test_validation_cli_writes_aggregated_report_from_local_service(tmp_path, monkeypatch):
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    output_path = tmp_path / "validation_report.json"
    calls = Counter()
    dotenv_calls = []
    monkeypatch.setattr(
        "tests.validation.cli.load_dotenv",
        lambda: dotenv_calls.append(True),
    )

    def handler(request):
        incident_id = request.url.params["incidentIds"]
        calls[incident_id] += 1
        reference = next(item for item in references if item.incident_id == incident_id)
        return httpx.Response(
            200,
            json={"incidents": [_service_incident(reference, calls[incident_id])]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = validation_main(
            [
                "--references",
                str(FIXTURE_DIR / "golden_reference.json"),
                "--service-url",
                "http://validation.local/incident/details",
                "--output",
                str(output_path),
                "--top-k",
                "1",
            ],
            client=client,
            judge=_MatchingJudge(),
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["run_id"].endswith("Z")
    assert report["dataset_version"] == "phase1-validation-v3"
    assert report["model_name"] == "provider-returned-model"
    assert calls == Counter({reference.incident_id: 10 for reference in references})
    assert len(report["cases"]) == len(references)
    assert all(case["call_count"] == 10 for case in report["cases"])
    assert report["judge_model_name"] == "judge-model"
    assert all(case["average"]["summary_score"] == pytest.approx(5.0) for case in report["cases"])
    assert dotenv_calls == [True]


def test_evaluate_benchmark_run_records_judge_failures_without_losing_service_telemetry():
    reference = BenchmarkCaseReference(
        incident_id="INC000000000001",
        reference_summary="Session Store job failed.",
    )
    output = _successful_output(reference, 1)
    metadata = BenchmarkRunMetadata("run", "local", "dataset", "service-model")

    class _FailingJudge:
        model_name = "judge-model"

        def evaluate(self, _reference, _output):
            raise BenchmarkJudgeError("Invalid judge response.")

    report = render_iteration_template(
        evaluate_benchmark_run(
            [reference],
            [output],
            metadata,
            judge=_FailingJudge(),
            top_k=1,
        )
    )

    case = report["cases"][0]
    assert case["status"] == "judge_failed"
    assert case["successful_call_count"] == 1
    assert case["results"][0]["summary_score"] is None
    assert case["results"][0]["tokens_in"] == pytest.approx(100)
    assert case["average"]["tokens_in"] == pytest.approx(100)
    assert case["error_notes"] == "Invalid judge response."


def test_collect_benchmark_outputs_requires_positive_repetitions():
    with pytest.raises(ValueError, match="at least 1"):
        collect_benchmark_outputs([], repetitions=0)
