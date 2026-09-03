from pathlib import Path
import json

import pytest

from tests.validation.benchmark import (
    evaluate_benchmark_run,
    load_benchmark_outputs,
    load_golden_reference,
    render_iteration_template,
)
from tests.validation.cli import main as validation_main


FIXTURE_DIR = Path(__file__).resolve().parent


def test_load_golden_reference_reads_validation_dataset():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")

    assert [reference.incident_id for reference in references] == [
        "INC000111017580",
        "INC000111048388",
    ]
    assert references[0].reference_mitigation_suggestions == [
        "Break down 4xx errors by status code and route to pinpoint the source: analyze CloudWatch metrics and access logs for translations/public, segment by 400/401/403/404/429, and identify top offending clients, user agents, and paths."
    ]


def test_related_incident_precision_is_one_when_both_sides_are_empty():
    from tests.validation.benchmark import _compute_precision

    assert _compute_precision([], []) == pytest.approx(1.0)


def test_evaluate_benchmark_run_computes_all_validation_metrics():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    metadata, outputs = load_benchmark_outputs(FIXTURE_DIR / "sample_service_response.json")

    evaluation = evaluate_benchmark_run(references, outputs, metadata, top_k=1)

    assert evaluation.metrics["rouge"]["f1"] == pytest.approx(1.0)
    assert evaluation.metrics["top_k_accuracy"] == pytest.approx(1.0)
    assert evaluation.metrics["related_incident_precision"] == pytest.approx(1.0)
    assert evaluation.metrics["estimated_cost"] == pytest.approx(0.0352883)
    assert evaluation.metrics["latency_ms"] == pytest.approx(35302.789624998695)
    assert len(evaluation.cases) == 2
    assert evaluation.cases[0].status == "success"
    assert evaluation.cases[0].related_incident_precision == pytest.approx(1.0)


def test_render_iteration_template_includes_all_required_sections():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    metadata, outputs = load_benchmark_outputs(FIXTURE_DIR / "sample_service_response.json")
    evaluation = evaluate_benchmark_run(references, outputs, metadata, top_k=1)

    template = render_iteration_template(evaluation)

    assert template["run_id"].endswith("Z")
    assert "incident_id" in template
    assert template["model_name"] == "openai/gpt-5"
    assert template["metrics"]["top_k_accuracy"] == pytest.approx(1.0)
    assert template["metrics"]["related_incident_correlation"] == pytest.approx(1.0)
    assert template["metrics"]["cost_USD"] == pytest.approx(0.0352883)
    assert template["manual_notes"] == ""
    assert template["cases"]


def test_evaluate_benchmark_run_records_missing_outputs():
    references = load_golden_reference(FIXTURE_DIR / "golden_reference.json")
    metadata, outputs = load_benchmark_outputs(FIXTURE_DIR / "sample_service_response.json")
    filtered_outputs = outputs[:1]

    evaluation = evaluate_benchmark_run(references, filtered_outputs, metadata, top_k=1)

    missing_case = next(case for case in evaluation.cases if case.incident_id == "INC000111048388")
    assert missing_case.status == "missing_output"
    assert missing_case.rouge is None
    assert missing_case.top_k_accuracy is None


def test_validation_cli_writes_report(tmp_path):
    output_path = tmp_path / "validation_report.json"

    exit_code = validation_main(
        [
            "--references",
            str(FIXTURE_DIR / "golden_reference.json"),
            "--outputs",
            str(FIXTURE_DIR / "sample_service_response.json"),
            "--output",
            str(output_path),
            "--top-k",
            "1",
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["run_id"].endswith("Z")
    assert report["metrics"]["top_k_accuracy"] == pytest.approx(1.0)
    assert report["metrics"]["related_incident_precision"] == pytest.approx(1.0)
