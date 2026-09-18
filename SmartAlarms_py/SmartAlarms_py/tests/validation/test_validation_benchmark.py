from collections import Counter
import json
from pathlib import Path

import httpx2 as httpx
import pytest

from tests.validation.benchmark import (
    BenchmarkCaseReference,
    BenchmarkCaseOutput,
    BenchmarkRunMetadata,
    BenchmarkResolutionSuggestion,
    collect_benchmark_outputs,
    evaluate_benchmark_run,
    load_golden_reference,
    render_iteration_template,
)
from tests.validation.cli import main as validation_main


FIXTURE_DIR = Path(__file__).resolve().parent


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

    assert [reference.incident_id for reference in references] == [
        "INC000111017580",
        "INC000110969970",
        "INC000111250397",
    ]
    assert references[0].reference_mitigation_suggestions == [
        BenchmarkResolutionSuggestion(
            investigation="Check requests from los-MobileApp-ChargingTariffsCompositeService to translations/public.",
            mitigation="Confirm translations/public 4XX errors are recovered.",
        )
    ]


def test_related_incident_precision_is_one_when_both_sides_are_empty():
    from tests.validation.benchmark import _compute_precision

    assert _compute_precision([], []) == pytest.approx(1.0)


def test_evaluate_benchmark_run_uses_only_mitigation_for_top_k_accuracy():
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
        generated_summary=reference.reference_summary,
        generated_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(
                investigation="Check CloudWatch alarms.",
                mitigation="Retry the Session Store job.",
            )
        ],
    )
    metadata = BenchmarkRunMetadata(
        run_id="run",
        release_label="local",
        dataset_version="dataset",
        model_name="provider-returned-model",
    )

    evaluation = evaluate_benchmark_run([reference], [output], metadata, top_k=1)

    assert evaluation.metrics["top_k_accuracy"] == pytest.approx(1.0)


def test_evaluate_benchmark_run_computes_all_validation_metrics():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    metadata = BenchmarkRunMetadata(
        run_id="run",
        release_label="local",
        dataset_version="dataset",
        model_name="provider-returned-model",
    )
    outputs = [_successful_output(reference, 1) for reference in references]

    evaluation = evaluate_benchmark_run(references, outputs, metadata, top_k=1)

    assert evaluation.metrics["rouge"]["f1"] == pytest.approx(1.0)
    assert evaluation.metrics["top_k_accuracy"] == pytest.approx(1.0)
    assert evaluation.metrics["related_incident_precision"] == pytest.approx(1.0)
    assert evaluation.metrics["estimated_cost"] == pytest.approx(0.01)
    assert evaluation.metrics["latency_ms"] == pytest.approx(1000)
    assert len(evaluation.cases) == 3
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
    assert len(outputs) == 9
    assert metadata.model_name == "provider-returned-model"
    assert progress_events[0] == ("requesting", 1, 9, "INC000111017580")
    assert progress_events[-1] == ("success", 9, 9, "INC000111250397")
    assert len(progress_events) == 18
    assert outputs[0].generated_mitigation_suggestions == [
        BenchmarkResolutionSuggestion(
            investigation="Check requests from los-MobileApp-ChargingTariffsCompositeService to translations/public.",
            mitigation="Confirm translations/public 4XX errors are recovered.",
        )
    ]


def test_render_iteration_template_aggregates_repeated_calls_by_incident():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    metadata = BenchmarkRunMetadata(
        run_id="run",
        release_label="local",
        dataset_version="dataset",
        model_name="provider-returned-model",
    )
    first_reference, second_reference, _ = references
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
        evaluate_benchmark_run(references, outputs, metadata, top_k=1)
    )
    first_case = next(
        case for case in report["cases"] if case["incident_id"] == first_reference.incident_id
    )
    second_case = next(
        case for case in report["cases"] if case["incident_id"] == second_reference.incident_id
    )

    assert len(report["cases"]) == 3
    assert first_case["status"] == "partial_failure"
    assert first_case["call_count"] == 3
    assert first_case["successful_call_count"] == 2
    assert first_case["rouge"]["f1"] == pytest.approx(1.0)
    assert first_case["tokens_in"] == pytest.approx(200)
    assert first_case["cost_USD"] == pytest.approx(0.02)
    assert first_case["latency_ms"] == pytest.approx(2000)
    assert first_case["error_notes"] == "ConnectError: unavailable"
    assert second_case["call_count"] == 2
    assert second_case["tokens_in"] == pytest.approx(300)


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
        evaluate_benchmark_run([reference], outputs, metadata, top_k=1)
    )
    case = report["cases"][0]

    assert calls == 3
    assert metadata.model_name == "provider-returned-model"
    assert case["status"] == "partial_failure"
    assert case["call_count"] == 3
    assert case["successful_call_count"] == 2
    assert case["error_notes"].startswith("HTTPStatusError:")


def test_validation_cli_writes_aggregated_report_from_local_service(tmp_path):
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    output_path = tmp_path / "validation_report.json"
    calls = Counter()

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
        )

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["run_id"].endswith("Z")
    assert report["dataset_version"] == "phase1-validation-v2"
    assert report["model_name"] == "provider-returned-model"
    assert calls == Counter({reference.incident_id: 10 for reference in references})
    assert len(report["cases"]) == len(references)
    assert all(case["call_count"] == 10 for case in report["cases"])
    assert all(case["rouge"]["f1"] == pytest.approx(1.0) for case in report["cases"])


def test_collect_benchmark_outputs_requires_positive_repetitions():
    with pytest.raises(ValueError, match="at least 1"):
        collect_benchmark_outputs([], repetitions=0)
