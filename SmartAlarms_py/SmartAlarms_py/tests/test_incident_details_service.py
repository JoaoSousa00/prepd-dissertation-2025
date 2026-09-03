from src.application.incident_details import IncidentDetailsService
from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import BaseIncident
from src.domain.llm import (
    IncidentEnrichment,
    LlmGatewayUnavailableError,
    LlmSummary,
    LlmUsage,
    MitigationSuggestion,
)
from src.shared.observability import RequestLogContext, bind_request_context, get_current_request_context


class FakeIncidentSource:
    def __init__(self, incidents=None):
        self._incidents = incidents or {}

    def fetch_base_incident(self, incident_id):
        return self._incidents.get(incident_id)


class SuccessfulLlmGateway:
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None):
        return IncidentEnrichment(
            summary=LlmSummary(text=f"Summary for {incident_id}"),
            related_incidents=["INC0002", "INC0002", "INC0003"],
            mitigation_suggestions=[
                MitigationSuggestion(
                    suggestion="Restart service",
                    related_incidents=["INC0002"],
                    related_log_ids=["log-1"],
                )
            ],
            usage=LlmUsage(
                model="openai/gpt-5",
                tokens_in=100,
                tokens_out=25,
                tokens_total=125,
                estimated_cost=0.0125,
            ),
        )


class FailingLlmGateway:
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None):
        raise LlmGatewayUnavailableError("gateway unavailable")


def test_fetch_incident_details_without_llm_returns_base_incidents():
    service = IncidentDetailsService(
        IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    )
                }
            )
        )
    )

    details = service.fetch_incident_details(["INC0001"])

    assert len(details) == 1
    assert details[0].id == "INC0001"
    assert details[0].summary is None
    assert details[0].resolution_suggestions == []
    assert details[0].related_incidents == []


def test_fetch_incident_details_with_llm_adds_enrichment_fields():
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    )
                }
            )
        ),
        llm_gateway=SuccessfulLlmGateway(),
    )

    details = service.fetch_incident_details(["INC0001"])

    assert len(details) == 1
    assert details[0].summary == "Summary for INC0001"
    assert details[0].related_incidents == ["INC0002", "INC0003"]
    assert len(details[0].resolution_suggestions) == 1
    assert details[0].resolution_suggestions[0].suggestion == "Restart service"
    assert details[0].llm_usage is not None
    assert details[0].llm_usage.tokens_total == 125
    assert details[0].request_latency_ms is not None


def test_fetch_incident_details_with_failing_llm_returns_base_data():
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    )
                }
            )
        ),
        llm_gateway=FailingLlmGateway(),
    )

    details = service.fetch_incident_details(["INC0001"])

    assert len(details) == 1
    assert details[0].id == "INC0001"
    assert details[0].summary is None
    assert details[0].resolution_suggestions == []


def test_fetch_incident_details_does_not_double_count_suggestions():
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                    ),
                    "INC0002": BaseIncident(
                        id="INC0002",
                        short_description="DB latency spike",
                        description="Database queries are slow.",
                    ),
                }
            )
        ),
        llm_gateway=SuccessfulLlmGateway(),
    )

    with bind_request_context(RequestLogContext(request_id="req-dup")):
        details = service.fetch_incident_details(["INC0001", "INC0002"])
        payload = get_current_request_context().build_summary_payload()

    assert len(details) == 2
    assert payload["itsm_summary"]["suggestions_number"] == 2
