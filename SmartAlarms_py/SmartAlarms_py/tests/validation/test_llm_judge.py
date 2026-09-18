from src.domain.llm import LlmUsage
from src.infrastructure.llm_config import LlmGatewaySettings
from tests.validation.benchmark import (
    BenchmarkCaseOutput,
    BenchmarkCaseReference,
    BenchmarkJudgeError,
    BenchmarkResolutionSuggestion,
)
from tests.validation.llm_judge import GaiaLlmBenchmarkJudge


def _settings():
    return LlmGatewaySettings(
        endpoint="https://gaia.example/v1",
        model="service-model",
        auth_endpoint="https://auth.example/token",
        api_key="test-key",
        client_secret="test-secret",
        ca_cert_path="/path/to/cert",
        ca_cert_url="https://ca.example/cert.pem",
    )


class _FakeGateway:
    def __init__(self, response):
        self.response = response
        self.request = None

    def complete_prompt(self, *, prompt, max_tokens, temperature):
        self.request = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        return self.response, LlmUsage(
            model="judge-model",
            tokens_in=11,
            tokens_out=7,
            tokens_total=18,
            estimated_cost=0.002,
        )


def test_gaia_llm_benchmark_judge_parses_summary_score_and_suggestion_rank(monkeypatch):
    monkeypatch.setenv("GAIA_JUDGE_MODEL", "judge-model")
    gateway = _FakeGateway(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":{"score":4,"reason":"Same incident meaning."},'
                            '"suggestion_matches":[{"reference_index":1,"generated_rank":2,'
                            '"score":5,"reason":"Same mitigation."}]}'
                        )
                    }
                }
            ]
        }
    )
    judge = GaiaLlmBenchmarkJudge(settings=_settings(), gateway=gateway, max_tokens=500)
    reference = BenchmarkCaseReference(
        incident_id="INC001",
        reference_summary="Session Store job failed.",
        reference_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(
                investigation="Check job logs.",
                mitigation="Retry the failed job.",
            )
        ],
    )
    output = BenchmarkCaseOutput(
        incident_id="INC001",
        generated_summary="The Session Store task failed.",
        generated_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(mitigation="Escalate."),
            BenchmarkResolutionSuggestion(
                investigation="Review task logs.",
                mitigation="Restart the failed Session Store task.",
            ),
        ],
    )

    decision = judge.evaluate(reference, output)

    assert gateway.request["temperature"] == 0
    assert gateway.request["max_tokens"] == 500
    assert '"reference_summary": "Session Store job failed."' in gateway.request["prompt"]
    assert decision.summary.score == 4
    assert decision.suggestion_matches[0].generated_rank == 2
    assert decision.usage.tokens_total == 18
    assert decision.usage.estimated_cost == 0.002


def test_gaia_llm_benchmark_judge_rejects_reused_generated_suggestion_rank(monkeypatch):
    monkeypatch.setenv("GAIA_JUDGE_MODEL", "judge-model")
    gateway = _FakeGateway(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":{"score":5,"reason":"Equivalent."},"suggestion_matches":['
                            '{"reference_index":1,"generated_rank":1,"score":5,"reason":"Same."},'
                            '{"reference_index":2,"generated_rank":1,"score":4,"reason":"Same."}]}'
                        )
                    }
                }
            ]
        }
    )
    judge = GaiaLlmBenchmarkJudge(settings=_settings(), gateway=gateway)
    reference = BenchmarkCaseReference(
        incident_id="INC001",
        reference_summary="Summary.",
        reference_mitigation_suggestions=[
            BenchmarkResolutionSuggestion(mitigation="First mitigation."),
            BenchmarkResolutionSuggestion(mitigation="Second mitigation."),
        ],
    )
    output = BenchmarkCaseOutput(
        incident_id="INC001",
        generated_mitigation_suggestions=[BenchmarkResolutionSuggestion(mitigation="Action.")],
    )

    try:
        judge.evaluate(reference, output)
    except BenchmarkJudgeError as exc:
        assert "multiple references" in str(exc)
    else:
        raise AssertionError("Expected the judge to reject duplicate generated ranks.")


def test_gaia_llm_benchmark_judge_rejects_provider_token_limit():
    with pytest.raises(ValueError, match="between 1 and 128000"):
        GaiaLlmBenchmarkJudge(
            settings=_settings(),
            gateway=_FakeGateway({}),
            max_tokens=128001,
        )
import pytest
