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
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None, **kwargs):
        return IncidentEnrichment(
            summary=LlmSummary(text=f"Summary for {incident_id}"),
            related_incidents=["INC0002", "INC0002", "INC0003"],
            mitigation_suggestions=[
                MitigationSuggestion(
                    confidence="evidence-based",
                    investigation="Check service health.",
                    mitigation="Restart service.",
                    resolution_note="Service restarted and healthy.",
                    related_incidents=["INC0002"],
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
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None, **kwargs):
        raise LlmGatewayUnavailableError("gateway unavailable")


class CapturingLlmGateway:
    def __init__(self):
        self.kwargs = None

    def enrich_incident(self, incident_id, short_description, description, max_tokens=None, **kwargs):
        self.kwargs = kwargs
        return IncidentEnrichment(summary=LlmSummary(text=f"Summary for {incident_id}"))


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
    assert details[0].resolution_suggestions[0].confidence == "evidence-based"
    assert details[0].resolution_suggestions[0].investigation == "Check service health."
    assert details[0].resolution_suggestions[0].mitigation == "Restart service."
    assert details[0].resolution_suggestions[0].resolution_note == "Service restarted and healthy."
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


def test_fetch_incident_details_passes_sanitized_main_incident_context_to_llm():
    gateway = CapturingLlmGateway()
    service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(
            FakeIncidentSource(
                incidents={
                    "INC0001": BaseIncident(
                        id="INC0001",
                        short_description="API latency spike",
                        description="Requests slowed down during load peak.",
                        raw={
                            "number": "INC0001",
                            "short_description": "API latency spike",
                            "description": "Requests slowed down during load peak.",
                            "state": "New",
                            "priority": "3 - Moderate",
                            "impact": "2 - Medium",
                            "urgency": "2 - Medium",
                            "assignment_group": {"name": "Ops"},
                            "caller_id": {"name": "Hidden Caller"},
                            "assigned_to": {"name": "Hidden Assignee"},
                            "resolved_by": {"name": "Hidden Resolver"},
                            "attachments": [{"name": "secret.txt"}],
                            "comments": ["comment-1"],
                            "work_notes": ["work-note-1"],
                            "ci_item": [{"name": "Service"}],
                        },
                    )
                }
            )
        ),
        llm_gateway=gateway,
    )

    service.fetch_incident_details(["INC0001"])

    context = gateway.kwargs["main_incident_context"]
    assert "number: INC0001" in context
    assert "short_description: API latency spike" in context
    assert "description: Requests slowed down during load peak." in context
    assert "state: New" in context
    assert "priority: 3 - Moderate" in context
    assert "impact: 2 - Medium" in context
    assert "urgency: 2 - Medium" in context
    assert "assignment_group" in context
    assert "ci_item" in context
    assert "caller_id" not in context
    assert "assigned_to" not in context
    assert "resolved_by" not in context
    assert "attachments" not in context
