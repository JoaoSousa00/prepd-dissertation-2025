from src.application.incident_details import IncidentDetailsService
from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import BaseIncident
from src.domain.llm import IncidentEnrichment, LlmGatewayUnavailableError, LlmSummary, MitigationSuggestion


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
