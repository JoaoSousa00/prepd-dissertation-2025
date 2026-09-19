from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence
import json

import httpx2 as httpx


DEFAULT_LOCAL_SERVICE_URL = "http://127.0.0.1:8080/incident/details"
ProgressCallback = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class BenchmarkResolutionSuggestion:
    investigation: str = ""
    mitigation: str = ""


class BenchmarkJudgeError(RuntimeError):
    """Raised when a benchmark judgment cannot be produced or validated."""


@dataclass(frozen=True)
class BenchmarkJudgeUsage:
    model_name: str
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    tokens_total: Optional[int] = None
    estimated_cost: Optional[float] = None
    latency_ms: Optional[float] = None

    @classmethod
    def from_llm_usage(
        cls,
        *,
        model_name: str,
        usage: Any,
        latency_ms: float,
    ) -> "BenchmarkJudgeUsage":
        return cls(
            model_name=model_name,
            tokens_in=getattr(usage, "tokens_in", None),
            tokens_out=getattr(usage, "tokens_out", None),
            tokens_total=getattr(usage, "tokens_total", None),
            estimated_cost=getattr(usage, "estimated_cost", None),
            latency_ms=latency_ms,
        )


@dataclass(frozen=True)
class BenchmarkSummaryJudgment:
    score: int
    reason: str


@dataclass(frozen=True)
class BenchmarkSuggestionMatch:
    reference_index: int
    generated_rank: Optional[int]
    score: int
    reason: str


@dataclass(frozen=True)
class BenchmarkJudgeDecision:
    summary: BenchmarkSummaryJudgment
    suggestion_matches: List[BenchmarkSuggestionMatch] = field(default_factory=list)
    usage: Optional[BenchmarkJudgeUsage] = None


@dataclass(frozen=True)
class BenchmarkCaseReference:
    incident_id: str
    reference_summary: str
    reference_mitigation_suggestions: List[BenchmarkResolutionSuggestion] = field(
        default_factory=list
    )
    reference_related_incidents: List[str] = field(default_factory=list)
    reference_related_pages: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class BenchmarkCaseOutput:
    incident_id: str
    generated_summary: str = ""
    generated_mitigation_suggestions: List[BenchmarkResolutionSuggestion] = field(
        default_factory=list
    )
    generated_related_incidents: List[str] = field(default_factory=list)
    generated_related_pages: List[str] = field(default_factory=list)
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    tokens_total: Optional[int] = None
    estimated_cost: Optional[float] = None
    latency_ms: Optional[float] = None
    status: str = "success"
    error_notes: str = ""
    call_number: Optional[int] = None


@dataclass(frozen=True)
class BenchmarkRunMetadata:
    run_id: str
    release_label: str
    dataset_version: str
    model_name: str
    judge_model_name: str = ""
    configuration_notes: str = ""
    manual_notes: str = ""


class BenchmarkJudge(Protocol):
    """Port for semantic benchmark assessment."""

    @property
    def model_name(self) -> str: ...

    def evaluate(
        self,
        reference: BenchmarkCaseReference,
        output: BenchmarkCaseOutput,
    ) -> BenchmarkJudgeDecision: ...


@dataclass(frozen=True)
class BenchmarkCaseResult:
    incident_id: str
    status: str
    summary_score: Optional[float]
    mrr: Optional[float]
    related_incident_precision: Optional[float]
    related_page_precision: Optional[float]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    tokens_total: Optional[int]
    estimated_cost: Optional[float]
    latency_ms: Optional[float]
    summary_judgment: Optional[BenchmarkSummaryJudgment] = None
    suggestion_matches: List[BenchmarkSuggestionMatch] = field(default_factory=list)
    judge_usage: Optional[BenchmarkJudgeUsage] = None
    error_notes: str = ""
    call_number: Optional[int] = None


@dataclass(frozen=True)
class BenchmarkCaseAverage:
    summary_score: Optional[float]
    mrr: Optional[float]
    related_incident_precision: Optional[float]
    related_page_precision: Optional[float]
    tokens_in: Optional[float]
    tokens_out: Optional[float]
    tokens_total: Optional[float]
    estimated_cost: Optional[float]
    latency_ms: Optional[float]
    judge_tokens_in: Optional[float]
    judge_tokens_out: Optional[float]
    judge_tokens_total: Optional[float]
    judge_estimated_cost: Optional[float]
    judge_latency_ms: Optional[float]


@dataclass(frozen=True)
class AggregatedBenchmarkCaseResult:
    incident_id: str
    status: str
    call_count: int
    successful_call_count: int
    results: List[BenchmarkCaseResult] = field(default_factory=list)
    average: Optional[BenchmarkCaseAverage] = None
    error_notes: str = ""


@dataclass(frozen=True)
class BenchmarkEvaluationResult:
    metadata: BenchmarkRunMetadata
    cases: List[BenchmarkCaseResult]
    metrics: Dict[str, Any]


@dataclass(frozen=True)
class _BenchmarkRequest:
    request_number: int
    call_number: int
    reference: BenchmarkCaseReference


def load_golden_reference(path: Path | str) -> List[BenchmarkCaseReference]:
    payload = _load_json(path)
    incidents = payload.get("incidents", []) if isinstance(payload, Mapping) else payload
    return [
        BenchmarkCaseReference(
            incident_id=incident["incident_id"],
            reference_summary=incident["reference_summary"],
            reference_mitigation_suggestions=_load_resolution_suggestions(
                incident.get("reference_mitigation_suggestions", [])
            ),
            reference_related_incidents=list(
                incident.get("reference_related_incidents", [])
            ),
            reference_related_pages=_load_related_page_urls(
                incident.get("reference_related_pages", [])
            ),
            notes=incident.get("notes", ""),
        )
        for incident in incidents
    ]


def load_golden_reference_metadata(path: Path | str) -> Mapping[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, Mapping) else {}


def collect_benchmark_outputs(
    references: Sequence[BenchmarkCaseReference],
    service_url: str = DEFAULT_LOCAL_SERVICE_URL,
    repetitions: int = 1,
    timeout_seconds: float = 300.0,
    max_concurrency: int = 10,
    client: Optional[httpx.Client] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> tuple[BenchmarkRunMetadata, List[BenchmarkCaseOutput]]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    owns_client = client is None
    request_client = client or httpx.Client(timeout=timeout_seconds)
    total_requests = len(references) * repetitions
    requests = [
        _BenchmarkRequest(
            request_number=request_number,
            call_number=call_number,
            reference=reference,
        )
        for request_number, (reference, call_number) in enumerate(
            (
                (reference, call_number)
                for reference in references
                for call_number in range(1, repetitions + 1)
            ),
            start=1,
        )
    ]
    collected_outputs: List[
        tuple[int, BenchmarkCaseOutput, Optional[Mapping[str, Any]]]
    ] = []

    try:
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            futures = {}
            for request in requests:
                if progress_callback is not None:
                    progress_callback(
                        "requesting",
                        request.request_number,
                        total_requests,
                        request.reference.incident_id,
                    )
                future = executor.submit(
                    _request_incident_output,
                    request_client,
                    service_url,
                    request.reference.incident_id,
                )
                futures[future] = request

            for future in as_completed(futures):
                request = futures[future]
                output, payload = future.result()
                output = replace(output, call_number=request.call_number)
                collected_outputs.append((request.request_number, output, payload))
                if progress_callback is not None:
                    progress_callback(
                        output.status,
                        request.request_number,
                        total_requests,
                        request.reference.incident_id,
                    )
    finally:
        if owns_client:
            request_client.close()

    collected_outputs.sort(key=lambda item: item[0])
    outputs = [output for _, output, _ in collected_outputs]
    metadata_payload = next(
        (
            payload
            for _, output, payload in collected_outputs
            if output.status == "success" and payload is not None
        ),
        None,
    )
    return _build_metadata(metadata_payload), outputs


def _request_incident_output(
    client: httpx.Client,
    service_url: str,
    incident_id: str,
) -> tuple[BenchmarkCaseOutput, Optional[Mapping[str, Any]]]:
    try:
        response = client.get(service_url, params={"incidentIds": incident_id})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return _request_failure(incident_id, f"{type(exc).__name__}: {exc}"), None

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        return _request_failure(incident_id, f"Invalid JSON response: {exc}"), None

    if not isinstance(payload, Mapping):
        return _request_failure(incident_id, "Service response must be a JSON object."), None

    incidents = payload.get("incidents")
    if not isinstance(incidents, Sequence) or isinstance(incidents, (str, bytes)):
        return _request_failure(incident_id, "Service response does not contain an incidents list."), payload

    incident = next(
        (
            item
            for item in incidents
            if isinstance(item, Mapping)
            and item.get("id", item.get("incident_id", item.get("number"))) == incident_id
        ),
        None,
    )
    if incident is None:
        return _request_failure(
            incident_id,
            "Service response does not contain the requested incident.",
        ), payload

    return _build_case_output(incident), payload


def _request_failure(incident_id: str, error_notes: str) -> BenchmarkCaseOutput:
    return BenchmarkCaseOutput(
        incident_id=incident_id,
        status="request_failed",
        error_notes=error_notes,
    )


def _build_metadata(payload: Mapping[str, Any] | None) -> BenchmarkRunMetadata:
    payload = payload or {}
    incidents = payload.get("incidents", []) if isinstance(payload, Mapping) else []
    model_name = None
    if isinstance(incidents, Sequence):
        for incident in incidents:
            if not isinstance(incident, Mapping):
                continue
            llm_usage = incident.get("llmUsage") or {}
            candidate = llm_usage.get("model") or incident.get("model")
            if candidate:
                model_name = candidate
                break
    if not model_name:
        model_name = payload.get("model_name")

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
            generated_mitigation_suggestions=_load_resolution_suggestions(
                item.get("generated_mitigation_suggestions", [])
            ),
            generated_related_incidents=list(item.get("generated_related_incidents", [])),
            generated_related_pages=_load_related_page_urls(
                item.get("generated_related_pages", [])
            ),
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
            generated_mitigation_suggestions=_load_resolution_suggestions(
                item.get("generated_mitigation_suggestions", [])
            ),
            generated_related_incidents=list(item.get("generated_related_incidents", [])),
            generated_related_pages=_load_related_page_urls(
                item.get("generated_related_pages", [])
            ),
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
    generated_mitigation_suggestions = _load_resolution_suggestions(resolve_suggestions)
    generated_related_incidents = list(item.get("relatedIncidents", [])) or list(
        {
            related_incident
            for entry in resolve_suggestions
            if isinstance(entry, Mapping)
            for related_incident in entry.get("relatedIncidents", [])
        }
    )
    generated_related_pages = _load_related_page_urls(item.get("relatedPages", [])) or [
        page_url
        for entry in resolve_suggestions
        if isinstance(entry, Mapping)
        for page_url in _load_related_page_urls(entry.get("relatedPages", []))
    ]
    usage_tokens_in = llm_usage.get("tokensIn", llm_usage.get("tokens_in"))
    usage_tokens_out = llm_usage.get("tokensOut", llm_usage.get("tokens_out"))
    usage_tokens_total = llm_usage.get("tokensTotal", llm_usage.get("tokens_total"))
    usage_cost = llm_usage.get("cost_USD", llm_usage.get("estimatedCost", llm_usage.get("estimated_cost")))
    return BenchmarkCaseOutput(
        incident_id=item.get("id", item.get("incident_id", "")),
        generated_summary=item.get("summary", ""),
        generated_mitigation_suggestions=generated_mitigation_suggestions,
        generated_related_incidents=generated_related_incidents,
        generated_related_pages=generated_related_pages,
        tokens_in=usage_tokens_in,
        tokens_out=usage_tokens_out,
        tokens_total=usage_tokens_total,
        estimated_cost=usage_cost,
        latency_ms=item.get("requestLatencyMs", item.get("latency_ms")),
        status=item.get("status", "success"),
        error_notes=item.get("errorNotes", item.get("error_notes", "")),
    )


def _load_resolution_suggestions(
    suggestions: Any,
) -> List[BenchmarkResolutionSuggestion]:
    if not isinstance(suggestions, Sequence) or isinstance(suggestions, (str, bytes)):
        return []

    normalized_suggestions: List[BenchmarkResolutionSuggestion] = []
    for suggestion in suggestions:
        if isinstance(suggestion, str) and suggestion.strip():
            normalized_suggestions.append(
                BenchmarkResolutionSuggestion(mitigation=suggestion.strip())
            )
            continue
        if not isinstance(suggestion, Mapping):
            continue

        investigation = suggestion.get("investigation")
        mitigation = suggestion.get("mitigation", suggestion.get("suggestion"))
        normalized_investigation = investigation.strip() if isinstance(investigation, str) else ""
        normalized_mitigation = mitigation.strip() if isinstance(mitigation, str) else ""
        if normalized_investigation or normalized_mitigation:
            normalized_suggestions.append(
                BenchmarkResolutionSuggestion(
                    investigation=normalized_investigation,
                    mitigation=normalized_mitigation,
                )
            )

    return normalized_suggestions


def _load_related_page_urls(pages: Any) -> List[str]:
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)):
        return []

    urls = []
    for page in pages:
        if isinstance(page, str):
            url = page
        elif isinstance(page, Mapping):
            url = page.get("url")
        else:
            continue
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def evaluate_benchmark_run(
    references: Sequence[BenchmarkCaseReference],
    outputs: Sequence[BenchmarkCaseOutput],
    metadata: BenchmarkRunMetadata,
    judge: BenchmarkJudge,
) -> BenchmarkEvaluationResult:
    reference_map = {reference.incident_id: reference for reference in references}
    outputs_by_incident: Dict[str, List[BenchmarkCaseOutput]] = {}
    for output in outputs:
        outputs_by_incident.setdefault(output.incident_id, []).append(output)
    case_results: List[BenchmarkCaseResult] = []

    for incident_id, reference in reference_map.items():
        incident_outputs = outputs_by_incident.pop(incident_id, [])
        if not incident_outputs:
            case_results.append(
                BenchmarkCaseResult(
                    incident_id=incident_id,
                    status="missing_output",
                    summary_score=None,
                    mrr=None,
                    related_incident_precision=None,
                    related_page_precision=None,
                    tokens_in=None,
                    tokens_out=None,
                    tokens_total=None,
                    estimated_cost=None,
                    latency_ms=None,
                    error_notes="No generated output was provided for this incident.",
                )
            )
            continue

        for output in incident_outputs:
            if output.status != "success":
                case_results.append(
                    BenchmarkCaseResult(
                        incident_id=incident_id,
                        status=output.status,
                        summary_score=None,
                        mrr=None,
                        related_incident_precision=None,
                        related_page_precision=None,
                        tokens_in=output.tokens_in,
                        tokens_out=output.tokens_out,
                        tokens_total=output.tokens_total,
                        estimated_cost=output.estimated_cost,
                        latency_ms=output.latency_ms,
                        error_notes=output.error_notes,
                        call_number=output.call_number,
                    )
                )
                continue

            try:
                judgment = judge.evaluate(reference, output)
            except BenchmarkJudgeError as exc:
                case_results.append(
                    BenchmarkCaseResult(
                        incident_id=incident_id,
                        status="judge_failed",
                        summary_score=None,
                        mrr=None,
                        related_incident_precision=None,
                        related_page_precision=None,
                        tokens_in=output.tokens_in,
                        tokens_out=output.tokens_out,
                        tokens_total=output.tokens_total,
                        estimated_cost=output.estimated_cost,
                        latency_ms=output.latency_ms,
                        error_notes=str(exc),
                        call_number=output.call_number,
                    )
                )
                continue

            mrr = _compute_mrr(judgment.suggestion_matches)
            related_precision = _compute_reference_coverage(
                reference.reference_related_incidents,
                output.generated_related_incidents,
            )
            related_page_precision = _compute_reference_coverage(
                reference.reference_related_pages,
                output.generated_related_pages,
            )
            case_results.append(
                BenchmarkCaseResult(
                    incident_id=incident_id,
                    status=output.status,
                    summary_score=judgment.summary.score,
                    mrr=mrr,
                    related_incident_precision=related_precision,
                    related_page_precision=related_page_precision,
                    tokens_in=output.tokens_in,
                    tokens_out=output.tokens_out,
                    tokens_total=output.tokens_total,
                    estimated_cost=output.estimated_cost,
                    latency_ms=output.latency_ms,
                    summary_judgment=judgment.summary,
                    suggestion_matches=judgment.suggestion_matches,
                    judge_usage=judgment.usage,
                    error_notes=output.error_notes,
                    call_number=output.call_number,
                )
            )

    for incident_id, unexpected_outputs in outputs_by_incident.items():
        for output in unexpected_outputs:
            case_results.append(
                BenchmarkCaseResult(
                    incident_id=incident_id,
                    status="unexpected_output",
                    summary_score=None,
                    mrr=None,
                    related_incident_precision=None,
                    related_page_precision=None,
                    tokens_in=output.tokens_in,
                    tokens_out=output.tokens_out,
                    tokens_total=output.tokens_total,
                    estimated_cost=output.estimated_cost,
                    latency_ms=output.latency_ms,
                    error_notes="Generated output has no matching benchmark reference.",
                    call_number=output.call_number,
                )
            )

    return BenchmarkEvaluationResult(
        metadata=metadata,
        cases=case_results,
        metrics=_aggregate_metrics(case_results),
    )


def render_iteration_template(result: BenchmarkEvaluationResult) -> Dict[str, Any]:
    aggregated_cases = aggregate_benchmark_case_results(result.cases)
    cases = [_render_aggregated_case(case) for case in aggregated_cases]

    return {
        "run_id": result.metadata.run_id,
        "release_label": result.metadata.release_label,
        "dataset_version": result.metadata.dataset_version,
        "model_name": result.metadata.model_name,
        "judge_model_name": result.metadata.judge_model_name,
        "configuration_notes": result.metadata.configuration_notes,
        "metrics": {
            "summary_score": result.metrics.get("summary_score"),
            "mrr": result.metrics.get("mrr"),
            "related_incident_precision": result.metrics.get("related_incident_precision"),
            "related_page_precision": result.metrics.get("related_page_precision"),
            "cost_USD": result.metrics.get("estimated_cost"),
            "latency_ms": result.metrics.get("latency_ms"),
            "judge_tokens_in": result.metrics.get("judge_tokens_in"),
            "judge_tokens_out": result.metrics.get("judge_tokens_out"),
            "judge_tokens_total": result.metrics.get("judge_tokens_total"),
            "judge_cost_USD": result.metrics.get("judge_estimated_cost"),
            "judge_latency_ms": result.metrics.get("judge_latency_ms"),
        },
        "manual_notes": result.metadata.manual_notes,
        "status": "complete" if result.cases else "empty",
        "cases": cases,
    }


def aggregate_benchmark_case_results(
    case_results: Sequence[BenchmarkCaseResult],
) -> List[AggregatedBenchmarkCaseResult]:
    cases_by_incident: Dict[str, List[BenchmarkCaseResult]] = {}
    for case in case_results:
        cases_by_incident.setdefault(case.incident_id, []).append(case)

    aggregated_cases = []
    for incident_id, incident_cases in cases_by_incident.items():
        successful_cases = [
            case for case in incident_cases if case.status in {"success", "judge_failed"}
        ]
        evaluated_cases = [case for case in incident_cases if case.status == "success"]
        call_count = len(incident_cases)
        successful_call_count = len(successful_cases)
        if successful_call_count < call_count:
            status = "partial_failure" if successful_call_count else "request_failed"
        elif len(evaluated_cases) < call_count:
            status = "judge_failed"
        else:
            status = "success"

        error_notes = _combine_error_notes(
            case.error_notes for case in incident_cases if case.error_notes
        )
        aggregated_cases.append(
            AggregatedBenchmarkCaseResult(
                incident_id=incident_id,
                status=status,
                call_count=call_count,
                successful_call_count=successful_call_count,
                results=incident_cases,
                average=_build_case_average(successful_cases, evaluated_cases),
                error_notes=error_notes,
            )
        )
    return aggregated_cases


def _render_aggregated_case(case: AggregatedBenchmarkCaseResult) -> Dict[str, Any]:
    return {
        "incident_id": case.incident_id,
        "status": case.status,
        "call_count": case.call_count,
        "successful_call_count": case.successful_call_count,
        "results": _render_case_results(case.results),
        "average": _render_case_average(case.average),
        "error_notes": case.error_notes,
    }


def _render_case_results(case_results: Sequence[BenchmarkCaseResult]) -> List[Dict[str, Any]]:
    indexed_results = list(enumerate(case_results, start=1))
    return [
        _render_case_result(result.call_number or fallback_call_number, result)
        for fallback_call_number, result in sorted(
            indexed_results,
            key=lambda item: item[1].call_number or item[0],
        )
    ]


def _render_case_result(call_number: int, result: BenchmarkCaseResult) -> Dict[str, Any]:
    judge_decision = None
    if result.summary_judgment is not None:
        judge_decision = {
            "summary": asdict(result.summary_judgment),
            "suggestion_matches": [asdict(match) for match in result.suggestion_matches],
            "usage": _render_judge_usage(result.judge_usage),
        }

    return {
        "call_number": call_number,
        "status": result.status,
        "summary_score": result.summary_score,
        "mrr": result.mrr,
        "related_incident_precision": result.related_incident_precision,
        "related_page_precision": result.related_page_precision,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "tokens_total": result.tokens_total,
        "cost_USD": result.estimated_cost,
        "latency_ms": result.latency_ms,
        "judge_decision": judge_decision,
        "error_notes": result.error_notes,
    }


def _render_case_average(average: Optional[BenchmarkCaseAverage]) -> Optional[Dict[str, Optional[float]]]:
    if average is None:
        return None
    return {
        "summary_score": average.summary_score,
        "mrr": average.mrr,
        "related_incident_precision": average.related_incident_precision,
        "related_page_precision": average.related_page_precision,
        "tokens_in": average.tokens_in,
        "tokens_out": average.tokens_out,
        "tokens_total": average.tokens_total,
        "cost_USD": average.estimated_cost,
        "latency_ms": average.latency_ms,
        "judge_tokens_in": average.judge_tokens_in,
        "judge_tokens_out": average.judge_tokens_out,
        "judge_tokens_total": average.judge_tokens_total,
        "judge_cost_USD": average.judge_estimated_cost,
        "judge_latency_ms": average.judge_latency_ms,
    }


def _render_judge_usage(usage: Optional[BenchmarkJudgeUsage]) -> Optional[Dict[str, Any]]:
    if usage is None:
        return None
    return {
        "model_name": usage.model_name,
        "tokens_in": usage.tokens_in,
        "tokens_out": usage.tokens_out,
        "tokens_total": usage.tokens_total,
        "cost_USD": usage.estimated_cost,
        "latency_ms": usage.latency_ms,
    }


def _build_case_average(
    successful_cases: Sequence[BenchmarkCaseResult],
    evaluated_cases: Sequence[BenchmarkCaseResult],
) -> BenchmarkCaseAverage:
    return BenchmarkCaseAverage(
        summary_score=_mean(case.summary_score for case in evaluated_cases),
        mrr=_mean(case.mrr for case in evaluated_cases),
        related_incident_precision=_mean(
            case.related_incident_precision for case in evaluated_cases
        ),
        related_page_precision=_mean(
            case.related_page_precision for case in evaluated_cases
        ),
        tokens_in=_mean(case.tokens_in for case in successful_cases),
        tokens_out=_mean(case.tokens_out for case in successful_cases),
        tokens_total=_mean(case.tokens_total for case in successful_cases),
        estimated_cost=_mean(case.estimated_cost for case in successful_cases),
        latency_ms=_mean(case.latency_ms for case in successful_cases),
        judge_tokens_in=_mean(
            case.judge_usage.tokens_in
            for case in evaluated_cases
            if case.judge_usage is not None
        ),
        judge_tokens_out=_mean(
            case.judge_usage.tokens_out
            for case in evaluated_cases
            if case.judge_usage is not None
        ),
        judge_tokens_total=_mean(
            case.judge_usage.tokens_total
            for case in evaluated_cases
            if case.judge_usage is not None
        ),
        judge_estimated_cost=_mean(
            case.judge_usage.estimated_cost
            for case in evaluated_cases
            if case.judge_usage is not None
        ),
        judge_latency_ms=_mean(
            case.judge_usage.latency_ms
            for case in evaluated_cases
            if case.judge_usage is not None
        ),
    )


def _compute_mrr(suggestion_matches: Sequence[BenchmarkSuggestionMatch]) -> float:
    matching_ranks = [
        match.generated_rank
        for match in suggestion_matches
        if match.score >= 4 and match.generated_rank is not None
    ]
    if not matching_ranks:
        return 0.0
    return 1.0 / min(matching_ranks)


def _compute_reference_coverage(
    reference_items: Sequence[str],
    generated_items: Sequence[str],
) -> float:
    reference_set = set(reference_items)
    generated_set = set(generated_items)

    if not reference_set:
        return 1.0

    matched_references = sum(1 for item in reference_set if item in generated_set)
    return matched_references / len(reference_set)


def _aggregate_metrics(case_results: Sequence[BenchmarkCaseResult]) -> Dict[str, Optional[float]]:
    summary_scores = [case.summary_score for case in case_results if case.summary_score is not None]
    mrr_values = [case.mrr for case in case_results if case.mrr is not None]
    precision_values = [
        case.related_incident_precision for case in case_results if case.related_incident_precision is not None
    ]
    page_precision_values = [
        case.related_page_precision for case in case_results if case.related_page_precision is not None
    ]
    cost_values = [case.estimated_cost for case in case_results if case.estimated_cost is not None]
    latency_values = [case.latency_ms for case in case_results if case.latency_ms is not None]
    judge_tokens_in = [
        case.judge_usage.tokens_in
        for case in case_results
        if case.judge_usage is not None and case.judge_usage.tokens_in is not None
    ]
    judge_tokens_out = [
        case.judge_usage.tokens_out
        for case in case_results
        if case.judge_usage is not None and case.judge_usage.tokens_out is not None
    ]
    judge_tokens_total = [
        case.judge_usage.tokens_total
        for case in case_results
        if case.judge_usage is not None and case.judge_usage.tokens_total is not None
    ]
    judge_cost_values = [
        case.judge_usage.estimated_cost
        for case in case_results
        if case.judge_usage is not None and case.judge_usage.estimated_cost is not None
    ]
    judge_latency_values = [
        case.judge_usage.latency_ms
        for case in case_results
        if case.judge_usage is not None and case.judge_usage.latency_ms is not None
    ]

    return {
        "summary_score": _mean(summary_scores),
        "mrr": _mean(mrr_values),
        "related_incident_precision": _mean(precision_values),
        "related_page_precision": _mean(page_precision_values),
        "estimated_cost": _mean(cost_values),
        "latency_ms": _mean(latency_values),
        "judge_tokens_in": _mean(judge_tokens_in),
        "judge_tokens_out": _mean(judge_tokens_out),
        "judge_tokens_total": _mean(judge_tokens_total),
        "judge_estimated_cost": _mean(judge_cost_values),
        "judge_latency_ms": _mean(judge_latency_values),
    }


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    collected = [value for value in values if value is not None]
    if not collected:
        return None
    return sum(collected) / len(collected)


def _combine_error_notes(notes: Iterable[str]) -> str:
    unique_notes = list(dict.fromkeys(notes))
    return "; ".join(unique_notes)


def _load_json(path: Path | str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
