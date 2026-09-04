from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
import json

from rouge_score import rouge_scorer


@dataclass(frozen=True)
class BenchmarkCaseReference:
    incident_id: str
    reference_summary: str
    reference_mitigation_suggestions: List[str] = field(default_factory=list)
    reference_related_incidents: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class BenchmarkCaseOutput:
    incident_id: str
    generated_summary: str = ""
    generated_mitigation_suggestions: List[str] = field(default_factory=list)
    generated_related_incidents: List[str] = field(default_factory=list)
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    tokens_total: Optional[int] = None
    estimated_cost: Optional[float] = None
    latency_ms: Optional[float] = None
    status: str = "success"
    error_notes: str = ""


@dataclass(frozen=True)
class BenchmarkRunMetadata:
    run_id: str
    release_label: str
    dataset_version: str
    model_name: str
    configuration_notes: str = ""
    manual_notes: str = ""


@dataclass(frozen=True)
class BenchmarkCaseResult:
    incident_id: str
    status: str
    rouge: Optional[Dict[str, float]]
    top_k_accuracy: Optional[float]
    related_incident_precision: Optional[float]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    tokens_total: Optional[int]
    estimated_cost: Optional[float]
    latency_ms: Optional[float]
    error_notes: str = ""


@dataclass(frozen=True)
class BenchmarkEvaluationResult:
    metadata: BenchmarkRunMetadata
    cases: List[BenchmarkCaseResult]
    metrics: Dict[str, Any]


def load_golden_reference(path: Path | str) -> List[BenchmarkCaseReference]:
    payload = _load_json(path)
    incidents = payload.get("incidents", []) if isinstance(payload, Mapping) else payload
    return [
        BenchmarkCaseReference(
            incident_id=incident["incident_id"],
            reference_summary=incident["reference_summary"],
            reference_mitigation_suggestions=list(
                incident.get("reference_mitigation_suggestions", [])
            ),
            reference_related_incidents=list(
                incident.get("reference_related_incidents", [])
            ),
            notes=incident.get("notes", ""),
        )
        for incident in incidents
    ]


def load_benchmark_outputs(path: Path | str) -> tuple[BenchmarkRunMetadata, List[BenchmarkCaseOutput]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        metadata = _build_metadata({})
        outputs = [_build_case_output(item) for item in payload]
        return metadata, outputs

    metadata = _build_metadata(payload)
    outputs = [
        _build_case_output(item)
        for item in payload.get("incidents", [])
    ]
    return metadata, outputs


def _build_metadata(payload: Mapping[str, Any] | None) -> BenchmarkRunMetadata:
    payload = payload or {}
    incidents = payload.get("incidents", []) if isinstance(payload, Mapping) else []
    model_name = payload.get("model_name")
    if not model_name and isinstance(incidents, Sequence):
        for incident in incidents:
            if not isinstance(incident, Mapping):
                continue
            llm_usage = incident.get("llmUsage") or {}
            candidate = llm_usage.get("model") or incident.get("model")
            if candidate:
                model_name = candidate
                break

    run_id = payload.get("run_id")
    if not run_id:
        run_id = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return BenchmarkRunMetadata(
        run_id=run_id,
        release_label=payload.get("release_label", "manual"),
        dataset_version=payload.get("dataset_version", "manual"),
        model_name=model_name or "unknown",
        configuration_notes=payload.get("configuration_notes", ""),
        manual_notes=payload.get("manual_notes", ""),
    )


def _build_case_output(item: Mapping[str, Any]) -> BenchmarkCaseOutput:
    if "number" in item:
        incident_id = item.get("number", item.get("id", item.get("incident_id", "")))
        description = item.get("short_description") or item.get("description") or ""
        generated_summary = item.get("generated_summary", description)
        return BenchmarkCaseOutput(
            incident_id=incident_id,
            generated_summary=generated_summary,
            generated_mitigation_suggestions=list(item.get("generated_mitigation_suggestions", [])),
            generated_related_incidents=list(item.get("generated_related_incidents", [])),
            tokens_in=item.get("tokens_in"),
            tokens_out=item.get("tokens_out"),
            tokens_total=item.get("tokens_total"),
            estimated_cost=item.get("estimated_cost"),
            latency_ms=item.get("latency_ms"),
            status=item.get("status", "success"),
            error_notes=item.get("error_notes", ""),
        )

    if "incident_id" in item or "generated_summary" in item:
        return BenchmarkCaseOutput(
            incident_id=item.get("incident_id", item.get("id", "")),
            generated_summary=item.get("generated_summary", ""),
            generated_mitigation_suggestions=list(item.get("generated_mitigation_suggestions", [])),
            generated_related_incidents=list(item.get("generated_related_incidents", [])),
            tokens_in=item.get("tokens_in"),
            tokens_out=item.get("tokens_out"),
            tokens_total=item.get("tokens_total"),
            estimated_cost=item.get("estimated_cost"),
            latency_ms=item.get("latency_ms"),
            status=item.get("status", "success"),
            error_notes=item.get("error_notes", ""),
        )

    llm_usage = item.get("llmUsage") or {}
    resolve_suggestions = item.get("resolutionSuggestions", []) or item.get("resolution_suggestions", [])
    generated_mitigation_suggestions = [
        _compose_suggestion_text(entry)
        for entry in resolve_suggestions
        if isinstance(entry, Mapping)
        and _compose_suggestion_text(entry)
    ]
    generated_related_incidents = list(item.get("relatedIncidents", [])) or list(
        {
            related_incident
            for entry in resolve_suggestions
            if isinstance(entry, Mapping)
            for related_incident in entry.get("relatedIncidents", [])
        }
    )
    usage_tokens_in = llm_usage.get("tokensIn", llm_usage.get("tokens_in"))
    usage_tokens_out = llm_usage.get("tokensOut", llm_usage.get("tokens_out"))
    usage_tokens_total = llm_usage.get("tokensTotal", llm_usage.get("tokens_total"))
    usage_cost = llm_usage.get("cost_USD", llm_usage.get("estimatedCost", llm_usage.get("estimated_cost")))
    return BenchmarkCaseOutput(
        incident_id=item.get("id", item.get("incident_id", "")),
        generated_summary=item.get("summary", ""),
        generated_mitigation_suggestions=generated_mitigation_suggestions,
        generated_related_incidents=generated_related_incidents,
        tokens_in=usage_tokens_in,
        tokens_out=usage_tokens_out,
        tokens_total=usage_tokens_total,
        estimated_cost=usage_cost,
        latency_ms=item.get("requestLatencyMs", item.get("latency_ms")),
        status=item.get("status", "success"),
        error_notes=item.get("errorNotes", item.get("error_notes", "")),
    )


def _compose_suggestion_text(entry: Mapping[str, Any]) -> str:
    combined = entry.get("suggestion")
    if isinstance(combined, str) and combined.strip():
        return combined.strip()

    confidence = entry.get("confidence")
    investigation = entry.get("investigation")
    mitigation = entry.get("mitigation")
    resolution_note = entry.get("resolutionNote", entry.get("resolution_note"))

    parts: list[str] = []
    if isinstance(confidence, str) and confidence.strip():
        parts.append(f"Confidence: {confidence.strip()}")
    if isinstance(investigation, str) and investigation.strip():
        parts.append(f"Investigation: {investigation.strip()}")
    if isinstance(mitigation, str) and mitigation.strip():
        parts.append(f"Mitigation: {mitigation.strip()}")
    if isinstance(resolution_note, str) and resolution_note.strip():
        parts.append(f"Resolution note: {resolution_note.strip()}")
    return ". ".join(parts)


def evaluate_benchmark_run(
    references: Sequence[BenchmarkCaseReference],
    outputs: Sequence[BenchmarkCaseOutput],
    metadata: BenchmarkRunMetadata,
    top_k: int = 3,
) -> BenchmarkEvaluationResult:
    reference_map = {reference.incident_id: reference for reference in references}
    output_map = {output.incident_id: output for output in outputs}
    case_results: List[BenchmarkCaseResult] = []

    for incident_id, reference in reference_map.items():
        output = output_map.get(incident_id)
        if output is None:
            case_results.append(
                BenchmarkCaseResult(
                    incident_id=incident_id,
                    status="missing_output",
                    rouge=None,
                    top_k_accuracy=None,
                    related_incident_precision=None,
                    tokens_in=None,
                    tokens_out=None,
                    tokens_total=None,
                    estimated_cost=None,
                    latency_ms=None,
                    error_notes="No generated output was provided for this incident.",
                )
            )
            continue

        rouge = _compute_rouge(reference.reference_summary, output.generated_summary)
        top_k_accuracy = _compute_top_k_accuracy(
            reference.reference_mitigation_suggestions,
            output.generated_mitigation_suggestions,
            top_k=top_k,
        )
        related_precision = _compute_precision(
            reference.reference_related_incidents,
            output.generated_related_incidents,
        )
        case_results.append(
            BenchmarkCaseResult(
                incident_id=incident_id,
                status=output.status,
                rouge=rouge,
                top_k_accuracy=top_k_accuracy,
                related_incident_precision=related_precision,
                tokens_in=output.tokens_in,
                tokens_out=output.tokens_out,
                tokens_total=output.tokens_total,
                estimated_cost=output.estimated_cost,
                latency_ms=output.latency_ms,
                error_notes=output.error_notes,
            )
        )

    for incident_id, output in output_map.items():
        if incident_id in reference_map:
            continue
        case_results.append(
            BenchmarkCaseResult(
                incident_id=incident_id,
                status="unexpected_output",
                rouge=None,
                top_k_accuracy=None,
                related_incident_precision=None,
                tokens_in=output.tokens_in,
                tokens_out=output.tokens_out,
                tokens_total=output.tokens_total,
                estimated_cost=output.estimated_cost,
                latency_ms=output.latency_ms,
                error_notes="Generated output has no matching benchmark reference.",
            )
        )

    return BenchmarkEvaluationResult(
        metadata=metadata,
        cases=case_results,
        metrics=_aggregate_metrics(case_results),
    )


def render_iteration_template(result: BenchmarkEvaluationResult) -> Dict[str, Any]:
    cases = []
    for case in result.cases:
        case_dict = asdict(case)
        case_dict["cost_USD"] = case_dict.pop("estimated_cost")
        cases.append(case_dict)

    return {
        "run_id": result.metadata.run_id,
        "release_label": result.metadata.release_label,
        "dataset_version": result.metadata.dataset_version,
        "incident_id": result.cases[0].incident_id if len(result.cases) == 1 else None,
        "model_name": result.metadata.model_name,
        "configuration_notes": result.metadata.configuration_notes,
        "metrics": {
            "rouge": result.metrics.get("rouge"),
            "top_k_accuracy": result.metrics.get("top_k_accuracy"),
            "related_incident_precision": result.metrics.get("related_incident_precision"),
            "related_incident_correlation": result.metrics.get("related_incident_precision"),
            "cost_USD": result.metrics.get("estimated_cost"),
            "latency_ms": result.metrics.get("latency_ms"),
        },
        "manual_notes": result.metadata.manual_notes,
        "status": "complete" if result.cases else "empty",
        "cases": cases,
    }


def _compute_rouge(reference: str, generated: str) -> Dict[str, float]:
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    scores = scorer.score(reference, generated)
    return {
        "precision": _mean(score.precision for score in scores.values()),
        "recall": _mean(score.recall for score in scores.values()),
        "f1": _mean(score.fmeasure for score in scores.values()),
    }


def _compute_top_k_accuracy(
    reference_suggestions: Sequence[str],
    generated_suggestions: Sequence[str],
    top_k: int,
) -> float:
    if not reference_suggestions:
        return 0.0
    top_predictions = list(generated_suggestions[:top_k])
    return 1.0 if any(suggestion in reference_suggestions for suggestion in top_predictions) else 0.0


def _compute_precision(reference_items: Sequence[str], generated_items: Sequence[str]) -> float:
    reference_set = set(reference_items)
    generated_set = set(generated_items)

    if not reference_set and not generated_set:
        return 1.0
    if not generated_set:
        return 0.0

    true_positives = sum(1 for item in generated_set if item in reference_set)
    return true_positives / len(generated_set)


def _aggregate_metrics(case_results: Sequence[BenchmarkCaseResult]) -> Dict[str, Optional[float]]:
    rouge_values = [case.rouge for case in case_results if case.rouge is not None]
    top_k_values = [case.top_k_accuracy for case in case_results if case.top_k_accuracy is not None]
    precision_values = [
        case.related_incident_precision for case in case_results if case.related_incident_precision is not None
    ]
    cost_values = [case.estimated_cost for case in case_results if case.estimated_cost is not None]
    latency_values = [case.latency_ms for case in case_results if case.latency_ms is not None]

    return {
        "rouge": _aggregate_rouge(rouge_values),
        "top_k_accuracy": _mean(top_k_values),
        "related_incident_precision": _mean(precision_values),
        "estimated_cost": _mean(cost_values),
        "latency_ms": _mean(latency_values),
    }


def _aggregate_rouge(rouge_values: Sequence[Mapping[str, float]]) -> Optional[Dict[str, float]]:
    if not rouge_values:
        return None
    return {
        "precision": _mean(value["precision"] for value in rouge_values),
        "recall": _mean(value["recall"] for value in rouge_values),
        "f1": _mean(value["f1"] for value in rouge_values),
    }


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    collected = [value for value in values if value is not None]
    if not collected:
        return None
    return sum(collected) / len(collected)


def _load_json(path: Path | str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
