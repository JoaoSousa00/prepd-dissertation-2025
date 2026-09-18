from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping, Optional, Sequence

from src.domain.llm import LlmGatewayError, LlmUsage
from src.infrastructure.llm_config import LlmGatewaySettings, load_llm_gateway_settings
from src.infrastructure.llm_gateway import GaiaLlmGatewayAdapter
from tests.validation.benchmark import (
    BenchmarkCaseOutput,
    BenchmarkCaseReference,
    BenchmarkJudgeDecision,
    BenchmarkJudgeError,
    BenchmarkJudgeUsage,
    BenchmarkSuggestionMatch,
    BenchmarkSummaryJudgment,
)


DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "infrastructure"
    / "prompt"
    / "benchmark_judge_prompt.txt"
)
DEFAULT_MAX_TOKENS = 2000
MAX_GAIA_COMPLETION_TOKENS = 128000


class GaiaLlmBenchmarkJudge:
    """Evaluates benchmark outputs with a deterministic GAIA LLM completion."""

    def __init__(
        self,
        settings: Optional[LlmGatewaySettings] = None,
        gateway: Optional[GaiaLlmGatewayAdapter] = None,
        prompt_path: Optional[Path] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        configured_settings = settings or load_llm_gateway_settings()
        judge_model = os.getenv("GAIA_JUDGE_MODEL", configured_settings.model).strip()
        if not judge_model:
            raise ValueError("GAIA_JUDGE_MODEL must not be empty")

        self._settings = replace(configured_settings, model=judge_model)
        self._gateway = gateway or GaiaLlmGatewayAdapter(settings=self._settings)
        self._prompt_template = (prompt_path or DEFAULT_PROMPT_PATH).read_text(encoding="utf-8")
        configured_max_tokens = (
            max_tokens
            if max_tokens is not None
            else _parse_max_tokens(
                os.getenv("LLM_JUDGE_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
            )
        )
        if not 1 <= configured_max_tokens <= MAX_GAIA_COMPLETION_TOKENS:
            raise ValueError(
                "LLM_JUDGE_MAX_TOKENS must be between 1 and "
                f"{MAX_GAIA_COMPLETION_TOKENS}; use {DEFAULT_MAX_TOKENS} for benchmark judging."
            )
        self._max_tokens = configured_max_tokens

    @property
    def model_name(self) -> str:
        return self._settings.model

    def evaluate(
        self,
        reference: BenchmarkCaseReference,
        output: BenchmarkCaseOutput,
    ) -> BenchmarkJudgeDecision:
        prompt = self._prompt_template.replace(
            "{evaluation_input}",
            json.dumps(
                {
                    "reference_summary": reference.reference_summary,
                    "generated_summary": output.generated_summary,
                    "reference_suggestions": [
                        {
                            "index": index,
                            "investigation": suggestion.investigation,
                            "mitigation": suggestion.mitigation,
                        }
                        for index, suggestion in enumerate(
                            reference.reference_mitigation_suggestions,
                            start=1,
                        )
                    ],
                    "generated_suggestions": [
                        {
                            "index": index,
                            "investigation": suggestion.investigation,
                            "mitigation": suggestion.mitigation,
                        }
                        for index, suggestion in enumerate(
                            output.generated_mitigation_suggestions,
                            start=1,
                        )
                    ],
                },
                ensure_ascii=True,
            ),
        )
        started_at = time.perf_counter()
        try:
            response, usage = self._gateway.complete_prompt(
                prompt=prompt,
                max_tokens=self._max_tokens,
                temperature=0,
            )
        except LlmGatewayError as exc:
            raise BenchmarkJudgeError(f"LLM judge request failed: {exc}") from exc

        latency_ms = (time.perf_counter() - started_at) * 1000
        decision = self._parse_decision(
            response,
            reference_suggestion_count=len(reference.reference_mitigation_suggestions),
            generated_suggestion_count=len(output.generated_mitigation_suggestions),
        )
        return replace(
            decision,
            usage=BenchmarkJudgeUsage.from_llm_usage(
                model_name=self.model_name,
                usage=usage,
                latency_ms=latency_ms,
            ),
        )

    def _parse_decision(
        self,
        response: Mapping[str, Any],
        *,
        reference_suggestion_count: int,
        generated_suggestion_count: int,
    ) -> BenchmarkJudgeDecision:
        content = _message_content(response)
        try:
            payload = json.loads(_strip_code_fence(content))
        except json.JSONDecodeError as exc:
            raise BenchmarkJudgeError("LLM judge returned invalid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise BenchmarkJudgeError("LLM judge response must be a JSON object.")

        summary = payload.get("summary")
        if not isinstance(summary, Mapping):
            raise BenchmarkJudgeError("LLM judge response is missing the summary judgment.")
        summary_score = _score(summary.get("score"), "summary score")
        summary_reason = _required_text(summary.get("reason"), "summary reason")

        raw_matches = payload.get("suggestion_matches")
        if not isinstance(raw_matches, Sequence) or isinstance(raw_matches, (str, bytes)):
            raise BenchmarkJudgeError("LLM judge response is missing suggestion matches.")

        matches: list[BenchmarkSuggestionMatch] = []
        expected_indexes = set(range(1, reference_suggestion_count + 1))
        for raw_match in raw_matches:
            if not isinstance(raw_match, Mapping):
                raise BenchmarkJudgeError("LLM judge suggestion match must be an object.")
            reference_index = _positive_index(raw_match.get("reference_index"), "reference index")
            generated_rank = _optional_positive_index(
                raw_match.get("generated_rank"),
                "generated rank",
            )
            score = _score(raw_match.get("score"), "suggestion score")
            reason = _required_text(raw_match.get("reason"), "suggestion reason")
            if reference_index not in expected_indexes:
                raise BenchmarkJudgeError("LLM judge returned an unknown reference suggestion index.")
            if generated_rank is not None and generated_rank > generated_suggestion_count:
                raise BenchmarkJudgeError("LLM judge returned an unknown generated suggestion rank.")
            if score >= 4 and generated_rank is None:
                raise BenchmarkJudgeError("Equivalent suggestions require a generated rank.")
            if score < 4 and generated_rank is not None:
                raise BenchmarkJudgeError("Non-equivalent suggestions must not have a generated rank.")
            matches.append(
                BenchmarkSuggestionMatch(
                    reference_index=reference_index,
                    generated_rank=generated_rank,
                    score=score,
                    reason=reason,
                )
            )

        actual_indexes = {match.reference_index for match in matches}
        if len(matches) != len(actual_indexes) or actual_indexes != expected_indexes:
            raise BenchmarkJudgeError(
                "LLM judge must return exactly one match for every reference suggestion."
            )
        matched_ranks = [
            match.generated_rank for match in matches if match.generated_rank is not None
        ]
        if len(matched_ranks) != len(set(matched_ranks)):
            raise BenchmarkJudgeError(
                "LLM judge assigned one generated suggestion to multiple references."
            )

        return BenchmarkJudgeDecision(
            summary=BenchmarkSummaryJudgment(score=summary_score, reason=summary_reason),
            suggestion_matches=matches,
        )


def _message_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise BenchmarkJudgeError("LLM judge response has no choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise BenchmarkJudgeError("LLM judge response choice must be an object.")
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise BenchmarkJudgeError("LLM judge response choice has no message.")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        text = content.get("text")
        if isinstance(text, str):
            return text
    raise BenchmarkJudgeError("LLM judge response message has no text content.")


def _strip_code_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return stripped


def _score(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in range(1, 6):
        raise BenchmarkJudgeError(f"LLM judge {field_name} must be an integer from 1 to 5.")
    return value


def _positive_index(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BenchmarkJudgeError(f"LLM judge {field_name} must be a positive integer.")
    return value


def _optional_positive_index(value: object, field_name: str) -> Optional[int]:
    if value is None:
        return None
    return _positive_index(value, field_name)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkJudgeError(f"LLM judge {field_name} must be non-empty text.")
    return value.strip()


def _parse_max_tokens(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("LLM_JUDGE_MAX_TOKENS must be an integer.") from exc
