from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from tests.validation.benchmark import (
    evaluate_benchmark_run,
    load_benchmark_outputs,
    load_golden_reference,
    render_iteration_template,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline benchmark validation workflow.")
    parser.add_argument("--references", required=True, help="Path to the golden reference JSON file.")
    parser.add_argument("--outputs", required=True, help="Path to the generated run output JSON file.")
    parser.add_argument("--output", required=True, help="Where to write the validation report JSON.")
    parser.add_argument("--top-k", type=int, default=3, help="Top-K value for mitigation accuracy.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    references = load_golden_reference(Path(args.references))
    metadata, outputs = load_benchmark_outputs(Path(args.outputs))
    evaluation = evaluate_benchmark_run(references, outputs, metadata, top_k=args.top_k)
    report = render_iteration_template(evaluation)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=True)
        handle.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

