from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Optional, Sequence

from dotenv import load_dotenv
import httpx2 as httpx
from tests.validation.benchmark import (
    BenchmarkJudge,
    DEFAULT_LOCAL_SERVICE_URL,
    collect_benchmark_outputs,
    evaluate_benchmark_run,
    load_golden_reference,
    load_golden_reference_metadata,
    render_iteration_template,
)
from tests.validation.llm_judge import GaiaLlmBenchmarkJudge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeated local-service benchmark validation.")
    parser.add_argument("--references", required=True, help="Path to the golden reference JSON file.")
    parser.add_argument("--output", required=True, help="Where to write the validation report JSON.")
    parser.add_argument("--top-k", type=int, default=3, help="Top-K value for mitigation accuracy.")
    parser.add_argument(
        "--service-url",
        default=DEFAULT_LOCAL_SERVICE_URL,
        help=f"Local incident details endpoint (default: {DEFAULT_LOCAL_SERVICE_URL}).",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=10,
        help="Number of requests to make for every referenced incident (default: 10).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=10,
        help="Maximum simultaneous local-service requests (default: 10).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=300.0,
        help="Timeout for each service request in seconds (default: 300).",
    )
    parser.add_argument(
        "--release-label",
        default="local",
        help="Label for the service release being evaluated (default: local).",
    )
    parser.add_argument(
        "--dataset-version",
        help="Dataset version to record; defaults to the golden reference dataset_version.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Optional[httpx.Client] = None,
    judge: Optional[BenchmarkJudge] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.max_concurrency < 1:
        parser.error("--max-concurrency must be at least 1")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than 0")
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")

    load_dotenv()
    references = load_golden_reference(Path(args.references))
    reference_metadata = load_golden_reference_metadata(Path(args.references))
    benchmark_judge = judge or GaiaLlmBenchmarkJudge()
    metadata, outputs = collect_benchmark_outputs(
        references,
        service_url=args.service_url,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout_seconds,
        max_concurrency=args.max_concurrency,
        client=client,
        progress_callback=_print_progress,
    )
    metadata = replace(
        metadata,
        release_label=args.release_label,
        dataset_version=args.dataset_version
        or reference_metadata.get("dataset_version", metadata.dataset_version),
        judge_model_name=benchmark_judge.model_name,
    )
    evaluation = evaluate_benchmark_run(
        references,
        outputs,
        metadata,
        judge=benchmark_judge,
        top_k=args.top_k,
    )
    report = render_iteration_template(evaluation)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=True)
        handle.write("\n")

    return 0


def _print_progress(status: str, request_number: int, total_requests: int, incident_id: str) -> None:
    if status == "requesting":
        message = f"Requesting {incident_id}"
    else:
        message = f"Completed {incident_id} ({status})"
    print(f"[{request_number}/{total_requests}] {message}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
